"""Cost and rate guardrails for the hosted runner.

X API pay-per-use prices (README "Costs", docs.x.com pricing, checked 2026-10-10); the app owner pays
for every connected robot:
    Posts: Read            $0.005 per post returned  (each mention)
    User: Read             $0.010 per user returned  (author expansion, /users/me)
    Post: Create (summoned reply, no URL)  $0.010 per request
X bills per UTC day and dedupes resources within it, so these are conservative upper estimates.

Guardrails (all configurable, see config.Settings):
* global daily spend cap for the whole app (estimated, UTC day). Before each poll the runner checks
  spent < cap; a single poll can overshoot by at most one page of mentions, so ALSO set a hard
  spending limit in the X Developer Console as the backstop.
* per-robot daily caps on mentions read and replies posted
* per-app mention polls per 15 minutes (X: 450/15 min) and posts per day (X: 10,000/24 h)
"""
from __future__ import annotations

import datetime as _dt
import time
from typing import List, Optional

from sqlalchemy import func, select

from ..robot.x_adapter import Mention, XAdapter
from .db import EventRow, UsageRow

PRICE_POST_READ = 0.005
PRICE_USER_READ = 0.010
PRICE_REPLY = 0.010


class GuardrailHit(Exception):
    """A cap was reached; the robot is skipped (not an error in the robot itself)."""


def utc_day(now: Optional[float] = None) -> str:
    return _dt.datetime.fromtimestamp(time.time() if now is None else now, _dt.timezone.utc).strftime("%Y-%m-%d")


def window15(now: Optional[float] = None) -> str:
    return f"w{int((time.time() if now is None else now) // 900)}"


class Budget:
    def __init__(self, sf, settings):
        self.sf, self.s = sf, settings

    def _add(self, db, period: str, scope: str, metric: str, n: int, cost: float) -> None:
        row = db.get(UsageRow, (period, scope, metric))
        if row is None:
            row = UsageRow(period=period, scope=scope, metric=metric, count=0, cost_usd=0.0)
            db.add(row)
        row.count += n
        row.cost_usd += cost

    def record(self, scope: str, metric: str, n: int = 1, cost: float = 0.0, now: Optional[float] = None) -> None:
        day = utc_day(now)
        with self.sf() as db, db.begin():
            self._add(db, day, scope, metric, n, cost)
            if scope != "app":
                self._add(db, day, "app", metric, n, cost)

    def count(self, scope: str, metric: str, period: Optional[str] = None) -> int:
        with self.sf() as db:
            row = db.get(UsageRow, (period or utc_day(), scope, metric))
            return row.count if row else 0

    def spent_today(self, scope: str = "app", now: Optional[float] = None) -> float:
        with self.sf() as db:
            v = db.scalar(select(func.sum(UsageRow.cost_usd)).where(UsageRow.period == utc_day(now), UsageRow.scope == scope))
            return float(v or 0.0)

    # -- checks (return a reason string when blocked) --------------------------------------
    def poll_blocked(self, robot_id: str, now: Optional[float] = None) -> Optional[str]:
        if self.spent_today(now=now) >= self.s.daily_spend_cap_usd:
            return f"daily spend cap ${self.s.daily_spend_cap_usd:.2f} reached for the app"
        if self.count("app", "polls", window15(now)) >= self.s.app_polls_per_15min:
            return f"app poll limit {self.s.app_polls_per_15min}/15min reached"
        if self.count(robot_id, "mentions") >= self.s.robot_daily_mentions:
            return f"robot read {self.s.robot_daily_mentions} mentions today"
        if self.count(robot_id, "replies") >= self.s.robot_daily_replies:
            return f"robot posted {self.s.robot_daily_replies} replies today"
        return None

    def reply_blocked(self, robot_id: str, now: Optional[float] = None) -> Optional[str]:
        if self.spent_today(now=now) + PRICE_REPLY > self.s.daily_spend_cap_usd:
            return f"daily spend cap ${self.s.daily_spend_cap_usd:.2f} reached for the app"
        if self.count("app", "replies") >= self.s.app_posts_per_day:
            return f"app post limit {self.s.app_posts_per_day}/day reached"
        if self.count(robot_id, "replies") >= self.s.robot_daily_replies:
            return f"robot posted {self.s.robot_daily_replies} replies today"
        return None

    def record_poll(self, robot_id: str, mentions: List[Mention], now: Optional[float] = None) -> None:
        with self.sf() as db, db.begin():
            self._add(db, window15(now), "app", "polls", 1, 0.0)
        authors = {m.author.lower() for m in mentions}
        cost = len(mentions) * PRICE_POST_READ + len(authors) * PRICE_USER_READ
        self.record(robot_id, "polls", 1, 0.0, now)
        if mentions:
            self.record(robot_id, "mentions", len(mentions), cost, now)


class MeteredAdapter:
    """Wraps a robot's XAdapter with the guardrails. In shadow mode (x_write_enabled=False) replies
    are recorded as events and NOT posted."""

    def __init__(self, inner: XAdapter, budget: Budget, robot_id: str, write_enabled: bool, sf):
        self.inner, self.budget, self.robot_id, self.write_enabled, self.sf = inner, budget, robot_id, write_enabled, sf
        self._shadow = 0

    def poll_mentions(self, since_id: Optional[str] = None) -> List[Mention]:
        why = self.budget.poll_blocked(self.robot_id)
        if why:
            raise GuardrailHit(why)
        ms = self.inner.poll_mentions(since_id)
        self.budget.record_poll(self.robot_id, ms)
        return ms

    def post_reply(self, in_reply_to_id: str, text: str) -> str:
        why = self.budget.reply_blocked(self.robot_id)
        if why:
            raise GuardrailHit(why)
        if not self.write_enabled:
            self._shadow += 1
            with self.sf() as db, db.begin():
                db.add(EventRow(robot_id=self.robot_id, kind="shadow_reply", summary=f"(not posted: shadow mode) {text}"[:400]))
            return f"shadow-{self._shadow}"
        pid = self.inner.post_reply(in_reply_to_id, text)
        self.budget.record(self.robot_id, "replies", 1, PRICE_REPLY)
        return pid
