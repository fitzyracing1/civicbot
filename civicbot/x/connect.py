"""Finish connecting a user-owned robot account (OAuth callback handler logic).

Called from YOUR web callback with the state+code X redirected back with. Makes network
calls (token exchange, GET /2/users/me) - tests run it only against a fake transport.
"""
from __future__ import annotations

import time
from typing import Optional

from ..robot.profile import ProfileStore, RobotProfile
from .api import XApiV2Adapter
from .oauth import OAuthError, XOAuth2
from .tokens import TokenStore


def finish_connect(oauth: XOAuth2, tokens: TokenStore, profiles: ProfileStore, *, state: str, code: str,
                   consent_accepted: bool, home_city: str = "", followups: bool = False,
                   now: Optional[float] = None) -> RobotProfile:
    if not consent_accepted:
        # Automation Rules II.A: OAuth alone is not consent for automated actions.
        raise OAuthError("owner did not accept the automated-actions consent; not connecting")
    token, pending = oauth.exchange(state, code, now=now)
    probe_id = f"pending:{pending.state[:8]}"
    tokens.put(probe_id, token)
    try:
        me = XApiV2Adapter(probe_id, oauth, tokens, enabled=True).me()
    finally:
        tokens.delete(probe_id)
    handle = me["username"]
    if pending.robot_hint and handle.lower() != pending.robot_hint.lower():
        oauth.revoke(token)
        raise OAuthError(f"authorized as @{handle}, expected robot @{pending.robot_hint}; "
                         "log in as the robot account and try again")
    if handle.lower() == pending.owner_hint.lower():
        oauth.revoke(token)
        raise OAuthError("that is the owner's personal account; connect the separate robot account")
    profile = RobotProfile(robot_handle=handle, robot_user_id=me["id"], owner_handle=pending.owner_hint,
                           home_city=home_city, connected_at=time.time() if now is None else now)
    profile.grant_consent(include_followups=followups, now=now)
    tokens.put(profile.robot_id, token)
    profiles.put(profile)
    return profile


def disconnect(oauth: XOAuth2, tokens: TokenStore, profiles: ProfileStore, robot_id: str) -> None:
    tok = tokens.get(robot_id)
    if tok:
        try:
            oauth.revoke(tok)
        finally:
            tokens.delete(robot_id)
    profiles.delete(robot_id)
