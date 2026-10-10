"""Real X API v2 adapter for ONE robot account (user-context OAuth 2.0 token).

DISABLED unless constructed with enabled=True and a token is present in the store.
civicbot's single developer app uses one adapter per connected robot, so each robot
reads its own mentions and replies from its own account.

Endpoints (https://docs.x.com):
  GET  /2/users/me
  GET  /2/users/:id/mentions   (per-user limit 300/15min; per-app 450/15min)
  POST /2/tweets               (per-user 100/15min; per-app 10,000/24h)
Self-serve tiers: a reply is only accepted if the original post's author "summoned" the
robot (@mentioned it or quoted it); since 2026-02-23, see docs.x.com/changelog.
"""
from __future__ import annotations

from typing import List, Optional

from ..http import HttpError, HttpTransport
from ..robot.x_adapter import Mention
from .oauth import OAuthError, XOAuth2
from .tokens import TokenStore

API = "https://api.x.com/2"


class XApiError(Exception):
    pass


class XApiV2Adapter:
    def __init__(self, robot_id: str, oauth: Optional[XOAuth2] = None, store: Optional[TokenStore] = None,
                 transport: Optional[HttpTransport] = None, robot_user_id: Optional[str] = None,
                 enabled: bool = False):
        self.robot_id = robot_id
        self.oauth, self.store, self.enabled = oauth, store, enabled
        self.http = transport or (oauth.http if oauth else HttpTransport())
        self.robot_user_id = robot_user_id

    # -- auth -----------------------------------------------------------------
    def _guard(self) -> None:
        if not self.enabled:
            raise RuntimeError("XApiV2Adapter is disabled (pass enabled=True deliberately)")
        if not (self.oauth and self.store and self.store.get(self.robot_id)):
            raise RuntimeError(f"robot {self.robot_id!r} is not connected (no OAuth token)")

    def _token(self, force_refresh: bool = False) -> str:
        tok = self.store.get(self.robot_id)
        if force_refresh or tok.expiring():
            try:
                tok = self.oauth.refresh(tok)
            except OAuthError as e:
                raise XApiError(f"token refresh failed for {self.robot_id}; owner must reconnect: {e}") from None
            self.store.put(self.robot_id, tok)
        return tok.access_token

    def _call(self, fn, *args, **kw):
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {self._token(force_refresh=attempt == 1)}"}
            try:
                return fn(*args, headers=headers, **kw)
            except HttpError as e:
                if e.status == 401 and attempt == 0:
                    continue  # access token revoked/expired early -> refresh once
                if e.status == 429:
                    raise XApiError(f"rate limited for {self.robot_id}; back off until x-rate-limit-reset") from None
                raise XApiError(f"X API HTTP {e.status}: {e.body[:200]}") from None

    # -- reads ----------------------------------------------------------------
    def me(self) -> dict:
        self._guard()
        data = self._call(self.http.get_json, f"{API}/users/me", {"user.fields": "username"})
        self.robot_user_id = data["data"]["id"]
        return data["data"]

    def poll_mentions(self, since_id: Optional[str] = None) -> List[Mention]:
        self._guard()
        if not self.robot_user_id:
            self.me()
        params = {"since_id": since_id, "max_results": 100,
                  "expansions": "author_id", "user.fields": "username",
                  "tweet.fields": "author_id,conversation_id,created_at,geo"}
        data = self._call(self.http.get_json, f"{API}/users/{self.robot_user_id}/mentions", params)
        users = {u["id"]: u["username"] for u in (data.get("includes") or {}).get("users", [])}
        out = [Mention(id=t["id"], author=users.get(t.get("author_id"), t.get("author_id", "")),
                       text=t.get("text", ""), conversation_id=t.get("conversation_id", ""),
                       robot=self.robot_id)
               for t in data.get("data", [])]
        return sorted(out, key=lambda m: int(m.id)) if all(m.id.isdigit() for m in out) else out

    # -- writes ---------------------------------------------------------------
    def post_reply(self, in_reply_to_id: str, text: str) -> str:
        self._guard()
        if len(text) > 280:
            raise ValueError("post exceeds 280 chars")
        payload = {"text": text, "reply": {"in_reply_to_tweet_id": in_reply_to_id}}
        data = self._call(self.http.post_json, f"{API}/tweets", payload)
        return data["data"]["id"]

    def poll_dms(self, since_id: Optional[str] = None) -> List[Mention]:  # pragma: no cover
        raise NotImplementedError("DMs need dm.read/dm.write scopes + GET /2/dm_events; not in v0.2")
