"""Reply text: <=280 chars, varied per robot.

X Developer Policy: "Never post identical or substantially similar content across multiple
accounts." Many robots run the same software, so replies are (1) built from the specific
request (service, city, place), (2) phrased from a template pool picked by a stable hash of
robot+mention, and (3) checked against a fleet-wide guard of recent posts; on a collision we
rotate the template and finally add a robot-specific sign-off.

Replies do not start with "@owner": X threads replies automatically, and the
changelog says programmatic @mentions carry extra restrictions on self-serve tiers.
"""
from __future__ import annotations

import hashlib
import re
from collections import deque
from typing import Deque, Dict, List, Optional, Set

LIMIT = 280
TAG = "[bot]"


def fit_280(text: str, limit: int = LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


TEMPLATES: Dict[str, List[str]] = {
    "report_dry": [
        "Got it: '{service}' for {location} ({city} 311). Draft is ready, not sent. Reply YES to file or STOP to opt out.",
        "Drafted a {city} 311 '{service}' request at {location}. Nothing filed yet; YES files it, STOP opts out.",
        "{city} 311 can take this as '{service}' ({location}). I've prepared it but not sent it. YES to file / STOP to opt out.",
        "Ready when you are: '{service}' at {location} via {city} 311. Dry run only so far. Reply YES to file, STOP to opt out.",
    ],
    "report_filed": [
        "Filed '{service}' with {city} 311{rid} for {location}.{followup}",
        "Done: {city} 311 has your '{service}' report{rid} at {location}.{followup}",
        "Submitted to {city} 311: '{service}'{rid}, {location}.{followup}",
    ],
    "status": [
        "#{rid}{city}: now {status}.{notes}",
        "Status for #{rid}{city}: {status}.{notes}",
        "Update on #{rid}{city}: {status}.{notes}",
    ],
}
FOLLOWUP_ON = [" I'll post status changes here.", " I'll update this thread if the status changes."]
FOLLOWUP_OFF = [" Ask 'status #{rid_raw}' any time.", " Reply 'status #{rid_raw}' to check."]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower())


class FleetDuplicateGuard:
    """Remembers recent normalized posts across ALL robots in this process/fleet."""

    def __init__(self, maxlen: int = 5000):
        self._q: Deque[tuple] = deque(maxlen=maxlen)
        self._seen: Dict[str, Set[str]] = {}

    def taken_by_other(self, robot_id: str, text: str) -> bool:
        owners = self._seen.get(_norm(text), set())
        return bool(owners - {robot_id})

    def record(self, robot_id: str, text: str) -> None:
        key = _norm(text)
        if len(self._q) == self._q.maxlen:
            old_key, old_robot = self._q[0]
            self._seen.get(old_key, set()).discard(old_robot)
        self._q.append((key, robot_id))
        self._seen.setdefault(key, set()).add(robot_id)


class Phraser:
    def __init__(self, robot_id: str, guard: Optional[FleetDuplicateGuard] = None, tag: str = TAG):
        self.robot_id, self.guard, self.tag = robot_id, guard or FleetDuplicateGuard(), tag

    def _pick(self, kind: str, seed: str, **fields) -> str:
        return self.choose(kind, [t.format(**fields) for t in TEMPLATES[kind]], seed)

    def choose(self, key: str, rendered: List[str], seed: str) -> str:
        """Pick one of several already-rendered phrasings: stable per robot+seed, never a copy
        of what another robot in the fleet posted."""
        rendered = [r for r in rendered if r] or ["Done."]
        start = int(hashlib.sha256(f"{self.robot_id}|{seed}|{key}".encode()).hexdigest(), 16) % len(rendered)
        candidates = [self._tagged(rendered[(start + i) % len(rendered)]) for i in range(len(rendered))]
        for c in candidates:
            if not self.guard.taken_by_other(self.robot_id, c):
                break
        else:
            c = self._tagged(f"{candidates[0][:-len(self.tag)].rstrip()} ({self.robot_id})")
        self.guard.record(self.robot_id, c)
        return c

    def report(self, *, seed: str, service: str, city: str, location: str, dry_run: bool,
               request_id: Optional[str] = None, followups: bool = False) -> str:
        if dry_run:
            return self._pick("report_dry", seed, service=service, city=city, location=location)
        h = int(hashlib.sha256(f"{self.robot_id}|{seed}".encode()).hexdigest(), 16)
        fu = (FOLLOWUP_ON if followups else FOLLOWUP_OFF)[h % 2].format(rid_raw=request_id or "")
        return self._pick("report_filed", seed, service=service, city=city, location=location,
                          rid=f" #{request_id}" if request_id else "", followup=fu)

    def status(self, *, seed: str, request_id: str, status: str, notes: str = "", city: str = "") -> str:
        return self._pick("status", seed, rid=request_id, status=status.upper(),
                          notes=f" {notes}" if notes else "", city=f" ({city})" if city else "")

    def _tagged(self, body: str) -> str:
        """Truncate the body, never the [bot] tag."""
        return f"{fit_280(body, LIMIT - len(self.tag) - 1)} {self.tag}"

    def text(self, body: str) -> str:
        t = self._tagged(body)
        if self.guard.taken_by_other(self.robot_id, t):  # another robot already posted this exact text
            t = self._tagged(f"{body} ({self.robot_id})")
        self.guard.record(self.robot_id, t)
        return t


# backwards-compatible helpers --------------------------------------------------
def compose_report_reply(*, user: str = "", service_name: str, city: str, location: str,
                         dry_run: bool, request_id: Optional[str] = None) -> str:
    return Phraser("default").report(seed=location, service=service_name, city=city, location=location,
                                     dry_run=dry_run, request_id=request_id)


def compose_status_reply(*, user: str = "", request_id: str, status: str, notes: str = "", city: str = "") -> str:
    return Phraser("default").status(seed=request_id, request_id=request_id, status=status, notes=notes, city=city)
