"""The 'X robot' layer: mention -> intent -> city API call (dry-run) -> reply."""
from .intent import Intent, IntentParser
from .matcher import ServiceMatcher, ServiceMatch
from .replies import (FleetDuplicateGuard, Phraser, compose_report_reply, compose_status_reply,
                      fit_280)
from .x_adapter import Mention, XAdapter, StubXAdapter
from .profile import CONSENT_ACTIONS, ProfileStore, RobotProfile
from .engine import Robot, RobotAction, RobotState
from .fleet import Fleet

__all__ = ["Intent", "IntentParser", "ServiceMatcher", "ServiceMatch", "FleetDuplicateGuard", "Phraser",
           "compose_report_reply", "compose_status_reply", "fit_280", "Mention", "XAdapter",
           "StubXAdapter", "CONSENT_ACTIONS", "ProfileStore", "RobotProfile", "Robot", "RobotAction",
           "RobotState", "Fleet"]
