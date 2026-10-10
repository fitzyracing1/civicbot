"""Hosted runner: operates every connected robot with the existing multi-tenant Fleet engine.

    python -m civicbot.web.worker            # loop forever (Ctrl-C to stop)
    python -m civicbot.web.worker --once     # one tick
    python -m civicbot.web.worker --check    # healthcheck: exit 1 if the last heartbeat is stale

Each tick: load active robots from the DB -> Fleet.run_once() through MeteredAdapter guardrails ->
persist each robot's state, poll time, errors and an activity log -> heartbeat.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
import signal
import sys
import threading
import time
from typing import List, Optional

from sqlalchemy import select

from ..robot.engine import Robot, RobotAction, RobotState
from ..robot.fleet import Fleet
from ..robot.profile import RobotProfile
from ..robot.replies import FleetDuplicateGuard
from ..secrets import InMemorySecretStore
from ..x.api import XApiV2Adapter
from .budget import GuardrailHit, MeteredAdapter
from .config import Settings
from .db import EventRow, Heartbeat, RobotRow
from .logs import log, setup_logging
from .services import Services, build_services
from .stores import SqlProfileStore

logger = logging.getLogger("civicbot.worker")
HEARTBEAT_STALE_S = 120


class HostedFleet(Fleet):
    """Fleet whose per-robot state lives in the DB instead of JSON files."""

    def __init__(self, svc: Services, guard: FleetDuplicateGuard):
        s = svc.settings
        api_keys = s.city_api_keys if s.allow_311_sending else {}  # no keys = robots can't file 311
        super().__init__(SqlProfileStore(svc.sf, active_only=True), self._adapter_for, resolver=svc.resolver,
                         api_keys=api_keys, min_poll_interval=s.poll_interval_s, fetcher=svc.fetcher,
                         secrets=InMemorySecretStore(), catalog=svc.catalog)
        self.svc, self.guard = svc, guard
        with svc.sf() as db:
            rows = list(db.scalars(select(RobotRow).where(RobotRow.status == "active")))
        self._rows = {r.robot_id: (r.state_json, r.last_poll_at) for r in rows}
        self._last_poll = {rid: t for rid, (_, t) in self._rows.items() if t}

    def _adapter_for(self, p: RobotProfile) -> MeteredAdapter:
        svc = self.svc
        inner = XApiV2Adapter(p.robot_id, svc.oauth_robot, svc.tokens, robot_user_id=p.robot_user_id or None, enabled=True)
        return MeteredAdapter(inner, svc.budget, p.robot_id, write_enabled=svc.settings.x_write_enabled or svc.settings.dev_mode,
                              sf=svc.sf)

    def robot(self, robot_id: str) -> Robot:
        if robot_id not in self._robots:
            p = self.profiles.get(robot_id)
            if p is None:
                raise KeyError(robot_id)
            raw = (self._rows.get(robot_id) or ("", None))[0]
            state = RobotState(**json.loads(raw)) if raw else RobotState()
            self._robots[robot_id] = Robot(p, resolver=self.resolver, api_keys=self.api_keys, state=state,
                                           guard=self.guard, fetcher=self.fetcher, secrets=self.secrets,
                                           catalog=self.catalog, on_profile_change=self.profiles.put)
        return self._robots[robot_id]


def tick(svc: Services, guard: Optional[FleetDuplicateGuard] = None, now: Optional[float] = None) -> List[RobotAction]:
    guard = guard or FleetDuplicateGuard()
    now = time.time() if now is None else now
    spent, cap = svc.budget.spent_today(), svc.settings.daily_spend_cap_usd
    if spent >= cap:
        log(logger, "daily_spend_cap_reached", level=logging.WARNING, spent_usd=round(spent, 3), cap_usd=cap)
        _heartbeat(svc, {"skipped": "spend_cap", "spent_usd": round(spent, 3)})
        return []
    fleet = HostedFleet(svc, guard)
    before = dict(fleet._last_poll)
    actions = fleet.run_once(now=now)
    polled = {rid for rid, t in fleet._last_poll.items() if before.get(rid) != t}
    with svc.sf() as db, db.begin():
        for rid in polled:
            row = db.get(RobotRow, rid)
            if not row:
                continue
            row.last_poll_at = fleet._last_poll[rid]
            row.last_error = ""
            if rid in fleet._robots:
                row.state_json = json.dumps(asdict(fleet._robots[rid].state))
        for a in actions:
            row = db.get(RobotRow, a.robot)
            failed = [l for l in a.log if l.startswith("poll failed:")]
            if failed and row:
                msg = failed[0][len("poll failed: "):][:300]
                row.last_error = msg
                if "must reconnect" in msg or "not connected" in msg:
                    row.status = "needs_reconnect"
                db.add(EventRow(robot_id=a.robot, kind="guardrail" if "cap" in msg or "limit" in msg or "today" in msg else "error",
                                summary=msg))
                log(logger, "robot_poll_failed", level=logging.WARNING, robot=a.robot, error=msg)
                continue
            if a.reply:
                db.add(EventRow(robot_id=a.robot, kind="reply", summary=a.reply[:400]))
            log(logger, "mention_handled", robot=a.robot, mention_id=a.mention_id,
                intent=getattr(a.intent, "kind", None), skill=a.skill, replied=bool(a.reply))
    _heartbeat(svc, {"robots_polled": len(polled), "actions": len(actions)})
    log(logger, "tick", robots_polled=len(polled), actions=len(actions), spent_usd=round(svc.budget.spent_today(), 3))
    return actions


def _heartbeat(svc: Services, info: dict) -> None:
    with svc.sf() as db, db.begin():
        db.merge(Heartbeat(name="worker", ts=time.time(), info=json.dumps(info)))


def heartbeat_age(svc: Services) -> Optional[float]:
    with svc.sf() as db:
        hb = db.get(Heartbeat, "worker")
        return None if hb is None else time.time() - hb.ts


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="civicbot.web.worker")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    setup_logging()
    svc = build_services(Settings.from_env())
    if args.check:
        age = heartbeat_age(svc)
        ok = age is not None and age < max(HEARTBEAT_STALE_S, svc.settings.worker_tick_s * 4)
        print(json.dumps({"worker_ok": ok, "heartbeat_age_s": None if age is None else round(age, 1)}))
        return 0 if ok else 1
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    run_forever(svc, stop, once=args.once)
    return 0


def run_forever(svc: Services, stop: threading.Event, once: bool = False) -> None:
    """The runner loop. Also used in-process by the web app when CIVICBOT_EMBEDDED_WORKER=1
    (single-machine deploys where web and worker must share one SQLite volume)."""
    log(logger, "worker_start", dev_mode=svc.settings.dev_mode, x_write_enabled=svc.settings.x_write_enabled,
        daily_spend_cap_usd=svc.settings.daily_spend_cap_usd)
    guard = FleetDuplicateGuard()
    while not stop.is_set():
        try:
            tick(svc, guard)
        except Exception:  # keep the runner alive; the error is logged (redacted)
            logger.exception("tick_failed")
        if once:
            return
        stop.wait(svc.settings.worker_tick_s)


if __name__ == "__main__":
    sys.exit(main())
