"""Per-user robot model: each person owns their own robot X account (e.g. @joshs_robot).

civicbot's single developer app acts on each connected robot account on its owner's
behalf. OAuth tokens are NOT stored here; they live in a TokenStore (civicbot.x.tokens).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

CONSENT_VERSION = "2026-10-10"
# X Automation Rules II.A: OAuth alone is not consent for automated actions; describe the
# actions clearly, get express consent, honor opt-out, re-consent on material changes.
CONSENT_ACTIONS = (
    "read posts that @mention your robot account",
    "reply from your robot account, once per mention, only to you (the owner) and people you allow",
    "prepare 311 service requests to city APIs (dry-run; filing needs your explicit YES and sending enabled)",
)
FOLLOWUP_ACTION = "reply again in the same thread when a filed 311 request changes status"


@dataclass
class RobotProfile:
    robot_handle: str
    owner_handle: str
    robot_user_id: str = ""
    owner_user_id: str = ""
    allowlist: List[str] = field(default_factory=list)
    home_city: str = ""
    default_lat: Optional[float] = None
    default_lng: Optional[float] = None
    consent: Optional[dict] = None
    status_updates: bool = False  # separate, explicit opt-in to follow-up replies
    send_enabled: bool = False    # real 311 filing; off by default
    transit_feed_url: str = ""
    transit_stop_id: str = ""
    connected_at: Optional[float] = None
    # user-taught skills (validated specs; never contain secrets) and their switches
    skills: Dict[str, dict] = field(default_factory=dict)
    write_enabled: List[str] = field(default_factory=list)   # write skills the owner explicitly enabled
    disabled_builtins: List[str] = field(default_factory=list)
    plan: str = ""  # v0.4: "free" = free mode (free keyless catalog skills only, 311 dry-run); "" = standard

    def __post_init__(self):
        self.robot_handle = self.robot_handle.lstrip("@")
        self.owner_handle = self.owner_handle.lstrip("@")
        if self.robot_handle.lower() == self.owner_handle.lower():
            raise ValueError("the robot must be a separate account from its owner's personal account")

    @property
    def robot_id(self) -> str:
        return self.robot_handle.lower()

    def allowed(self, handle: str) -> bool:
        h = handle.lstrip("@").lower()
        return h == self.owner_handle.lower() or h in {a.lstrip("@").lower() for a in self.allowlist}

    def grant_consent(self, include_followups: bool = False, now: Optional[float] = None) -> None:
        actions = list(CONSENT_ACTIONS) + ([FOLLOWUP_ACTION] if include_followups else [])
        self.consent = {"version": CONSENT_VERSION, "actions": actions,
                        "granted_at": time.time() if now is None else now}
        self.status_updates = include_followups

    @property
    def has_consent(self) -> bool:
        return bool(self.consent and self.consent.get("version") == CONSENT_VERSION)


class ProfileStore:
    """JSON-file (or in-memory if path=None) store of robot profiles. No secrets inside."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else None
        self._d: Dict[str, RobotProfile] = {}
        if self.path and self.path.exists():
            self._d = {k: RobotProfile(**v) for k, v in json.loads(self.path.read_text()).items()}

    def _save(self) -> None:
        if self.path:
            self.path.write_text(json.dumps({k: asdict(v) for k, v in self._d.items()}, indent=2))

    def put(self, p: RobotProfile) -> None:
        self._d[p.robot_id] = p
        self._save()

    def get(self, robot_id: str) -> Optional[RobotProfile]:
        return self._d.get(robot_id.lstrip("@").lower())

    def delete(self, robot_id: str) -> None:
        self._d.pop(robot_id.lstrip("@").lower(), None)
        self._save()

    def all(self) -> List[RobotProfile]:
        return list(self._d.values())
