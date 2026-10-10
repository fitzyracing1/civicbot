"""X OAuth 2.0 Authorization Code Flow with PKCE (user-context tokens).

Endpoints and behavior per https://docs.x.com/resources/fundamentals/authentication/oauth-2-0/authorization-code
and .../user-access-token (checked 2026-10-10):

* authorize: https://x.com/i/oauth2/authorize  (response_type=code, client_id, redirect_uri,
  scope, state, code_challenge, code_challenge_method=S256)
* token:     POST https://api.x.com/2/oauth2/token  (x-www-form-urlencoded; confidential clients
  send HTTP Basic client_id:client_secret)
* revoke:    POST https://api.x.com/2/oauth2/revoke
* auth codes expire after 30 seconds; access tokens last 2 hours; a refresh token is
  only issued with the offline.access scope.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

from ..http import HttpError, HttpTransport

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
REVOKE_URL = "https://api.x.com/2/oauth2/revoke"
# tweet.read+users.read: read mentions & resolve the robot's own id; tweet.write: reply;
# offline.access: refresh token so the robot keeps working past 2 hours.
DEFAULT_SCOPES = ("tweet.read", "tweet.write", "users.read", "offline.access")
PENDING_TTL = 10 * 60  # seconds a started-but-unfinished connect stays valid


class OAuthError(Exception):
    pass


def make_pkce_pair() -> "tuple[str, str]":
    """RFC 7636: 43-128 char verifier, S256 challenge."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()[:128]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


@dataclass
class OAuthConfig:
    client_id: str
    redirect_uri: str
    client_secret: Optional[str] = None  # set for confidential clients (server-side app)
    scopes: Sequence[str] = DEFAULT_SCOPES


@dataclass
class OAuthToken:
    access_token: str
    token_type: str = "bearer"
    expires_at: float = 0.0
    refresh_token: Optional[str] = None
    scope: str = ""

    @classmethod
    def from_response(cls, data: dict, now: Optional[float] = None) -> "OAuthToken":
        if "access_token" not in data:
            raise OAuthError(f"token endpoint returned no access_token: {data}")
        now = time.time() if now is None else now
        return cls(access_token=data["access_token"], token_type=data.get("token_type", "bearer"),
                   expires_at=now + float(data.get("expires_in", 7200)),
                   refresh_token=data.get("refresh_token"), scope=data.get("scope", ""))

    def expiring(self, within: float = 120.0, now: Optional[float] = None) -> bool:
        return (time.time() if now is None else now) >= self.expires_at - within

    def to_dict(self) -> dict:
        return asdict(self)

    def __repr__(self) -> str:  # never print secrets
        return f"OAuthToken(expires_at={self.expires_at:.0f}, scope={self.scope!r}, refresh={'yes' if self.refresh_token else 'no'})"


@dataclass
class PendingAuth:
    state: str
    code_verifier: str
    robot_hint: str
    owner_hint: str
    created_at: float = field(default_factory=time.time)


class XOAuth2:
    def __init__(self, config: OAuthConfig, transport: Optional[HttpTransport] = None):
        self.config = config
        self.http = transport or HttpTransport()
        self.pending: Dict[str, PendingAuth] = {}

    # step 1 ---------------------------------------------------------------
    def start(self, robot_hint: str = "", owner_hint: str = "") -> "tuple[str, PendingAuth]":
        """Return (authorize_url, pending). No network. The person must open the URL while
        logged in as their ROBOT account (not their personal account)."""
        verifier, challenge = make_pkce_pair()
        state = secrets.token_urlsafe(24)
        pending = PendingAuth(state, verifier, robot_hint.lstrip("@"), owner_hint.lstrip("@"))
        self.pending[state] = pending
        params = {"response_type": "code", "client_id": self.config.client_id,
                  "redirect_uri": self.config.redirect_uri, "scope": " ".join(self.config.scopes),
                  "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
        return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote), pending

    # step 2 ---------------------------------------------------------------
    def _headers(self) -> dict:
        if not self.config.client_secret:
            return {}
        raw = f"{self.config.client_id}:{self.config.client_secret}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}

    def _post(self, url: str, data: dict) -> dict:
        try:
            return self.http.post_form(url, data, headers=self._headers())
        except HttpError as e:
            raise OAuthError(f"{url} -> HTTP {e.status}: {e.body[:200]}") from None

    def exchange(self, state: str, code: str, now: Optional[float] = None) -> "tuple[OAuthToken, PendingAuth]":
        """Callback handler: validate state (CSRF), then trade the code for tokens."""
        pending = self.pending.pop(state, None)
        if pending is None:
            raise OAuthError("unknown or already-used state (possible CSRF or replay)")
        if (time.time() if now is None else now) - pending.created_at > PENDING_TTL:
            raise OAuthError("connect attempt expired; start again")
        data = {"code": code, "grant_type": "authorization_code", "client_id": self.config.client_id,
                "redirect_uri": self.config.redirect_uri, "code_verifier": pending.code_verifier}
        return OAuthToken.from_response(self._post(TOKEN_URL, data), now), pending

    # step 3 ---------------------------------------------------------------
    def refresh(self, token: OAuthToken, now: Optional[float] = None) -> OAuthToken:
        if not token.refresh_token:
            raise OAuthError("no refresh token (was offline.access granted?)")
        data = {"refresh_token": token.refresh_token, "grant_type": "refresh_token",
                "client_id": self.config.client_id}
        new = OAuthToken.from_response(self._post(TOKEN_URL, data), now)
        if not new.refresh_token:  # X rotates refresh tokens; keep old one only if none returned
            new.refresh_token = token.refresh_token
        return new

    def revoke(self, token: OAuthToken) -> None:
        for t, hint in ((token.access_token, "access_token"), (token.refresh_token, "refresh_token")):
            if t:
                self._post(REVOKE_URL, {"token": t, "token_type_hint": hint, "client_id": self.config.client_id})
