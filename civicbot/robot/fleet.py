"""Multi-tenant runner: one civicbot app, many user-owned robot accounts.

Each connected robot gets its own adapter (its own OAuth token) and its own Robot
(profile, state). run_once() polls every robot's mentions and replies from that robot's
own account. A fleet-wide duplicate guard keeps robots from posting identical text.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from ..resolver import JurisdictionResolver
from .engine import Robot, RobotAction
from .profile import ProfileStore, RobotProfile
from .replies import FleetDuplicateGuard
from .x_adapter import XAdapter

AdapterFactory = Callable[[RobotProfile], XAdapter]


class Fleet:
    def __init__(self, profiles: ProfileStore, adapter_factory: AdapterFactory,
                 resolver: Optional[JurisdictionResolver] = None, api_keys: Optional[Dict[str, str]] = None,
                 state_dir: Optional[str] = None, min_poll_interval: float = 60.0,
                 fetcher=None, secrets=None, catalog=None):
        self.profiles = profiles
        self.adapter_factory = adapter_factory
        self.resolver = resolver or JurisdictionResolver()
        self.api_keys = api_keys or {}
        self.state_dir = state_dir
        self.guard = FleetDuplicateGuard()
        self.fetcher, self.secrets, self.catalog = fetcher, secrets, catalog  # shared, but secrets are per-robot
        # GET /2/users/:id/mentions is 300 req/15min per user and 450/15min per APP: with many
        # robots the per-app ceiling binds first (450/15min = 1 poll/2s across the whole fleet).
        self.min_poll_interval = min_poll_interval
        self._robots: Dict[str, Robot] = {}
        self._adapters: Dict[str, XAdapter] = {}
        self._last_poll: Dict[str, float] = {}

    def robot(self, robot_id: str) -> Robot:
        if robot_id not in self._robots:
            p = self.profiles.get(robot_id)
            if p is None:
                raise KeyError(robot_id)
            state_path = f"{self.state_dir}/{p.robot_id}.state.json" if self.state_dir else None
            self._robots[robot_id] = Robot(p, resolver=self.resolver, api_keys=self.api_keys,
                                           state_path=state_path, guard=self.guard, fetcher=self.fetcher,
                                           secrets=self.secrets, catalog=self.catalog,
                                           on_profile_change=self.profiles.put)
        return self._robots[robot_id]

    def adapter(self, robot_id: str) -> XAdapter:
        if robot_id not in self._adapters:
            self._adapters[robot_id] = self.adapter_factory(self.profiles.get(robot_id))
        return self._adapters[robot_id]

    def run_once(self, now: Optional[float] = None) -> List[RobotAction]:
        now = time.time() if now is None else now
        actions: List[RobotAction] = []
        for p in self.profiles.all():
            if not p.has_consent:
                continue
            if now - self._last_poll.get(p.robot_id, -1e18) < self.min_poll_interval:
                continue
            self._last_poll[p.robot_id] = now
            try:
                actions.extend(self.robot(p.robot_id).run_once(self.adapter(p.robot_id)))
            except Exception as e:  # one robot's failure (revoked token, 429) must not stop the fleet
                actions.append(RobotAction(p.robot_id, "", None, log=[f"poll failed: {e}"]))
        return actions
