"""Dev mode: a fake X that speaks just enough of the real wire protocol for the REAL civicbot code
(XOAuth2, finish_connect, XApiV2Adapter) to run end-to-end with no credentials and no network.

* /dev/x/oauth2/authorize (served by the web app) stands in for https://x.com/i/oauth2/authorize
* FakeXTransport answers POST /2/oauth2/token|revoke, GET /2/users/me, GET /2/users/:id/mentions and
  POST /2/tweets from the dev_x_* tables. PKCE (S256) and client auth are actually checked.
Never enabled unless CIVICBOT_DEV_MODE=1.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from typing import Any, Mapping, Optional

from sqlalchemy import select

from ..http import HttpError, HttpTransport
from ..x.oauth import AUTHORIZE_URL, XOAuth2
from .db import DevCode, DevMention, DevPost, DevToken

DEV_AUTHORIZE_PATH = "/dev/x/oauth2/authorize"
CODE_TTL = 30  # X auth codes expire after 30 s


def fake_user_id(username: str) -> str:
    return str(int(hashlib.sha256(username.lower().encode()).hexdigest()[:12], 16))


class DevXOAuth2(XOAuth2):
    """Real XOAuth2, but the browser is sent to the local fake authorize page."""

    def __init__(self, config, transport, base_url: str):
        super().__init__(config, transport)
        self.base_url = base_url.rstrip("/")

    def start(self, robot_hint: str = "", owner_hint: str = ""):
        url, pending = super().start(robot_hint, owner_hint)
        return url.replace(AUTHORIZE_URL, self.base_url + DEV_AUTHORIZE_PATH, 1), pending


def issue_code(sf, username: str, challenge: str, redirect_uri: str) -> str:
    code = "devcode_" + secrets.token_urlsafe(18)
    with sf() as db, db.begin():
        db.add(DevCode(code=code, username=username.lstrip("@"), challenge=challenge, redirect_uri=redirect_uri))
    return code


def add_mention(sf, robot_username: str, author: str, text: str) -> int:
    with sf() as db, db.begin():
        m = DevMention(robot_username=robot_username.lower(), author=author.lstrip("@"), text=text[:400])
        db.add(m)
        db.flush()
        return m.id


def posts_for(sf, robot_username: str, limit: int = 20):
    with sf() as db:
        q = select(DevPost).where(DevPost.robot_username == robot_username.lower()).order_by(DevPost.id.desc()).limit(limit)
        return list(db.scalars(q))


class FakeXTransport(HttpTransport):
    def __init__(self, sf, client_id: str, client_secret: str):
        super().__init__()
        self.sf, self.client_id, self.client_secret = sf, client_id, client_secret

    # -- helpers ------------------------------------------------------------------------
    def _check_client(self, headers: Mapping[str, str]) -> None:
        want = "Basic " + base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        if (headers or {}).get("Authorization") != want:
            raise HttpError(401, "fake-x", '{"error":"unauthorized_client"}')

    def _new_token(self, db, username: str, kind: str) -> str:
        t = f"dev{kind[0]}t_" + secrets.token_urlsafe(24)
        db.add(DevToken(token=t, username=username, kind=kind))
        return t

    def _bearer_user(self, headers: Mapping[str, str]) -> str:
        auth = (headers or {}).get("Authorization", "")
        with self.sf() as db:
            row = db.get(DevToken, auth.removeprefix("Bearer "))
            if not row or row.kind != "access" or row.revoked or time.time() - row.created_at > 7200:
                raise HttpError(401, "fake-x", '{"title":"Unauthorized"}')
            return row.username

    # -- OAuth --------------------------------------------------------------------------
    def post_form(self, url: str, data: Mapping[str, Any], headers: Optional[Mapping[str, str]] = None) -> Any:
        self._check_client(headers)
        if url.endswith("/2/oauth2/revoke"):
            with self.sf() as db, db.begin():
                row = db.get(DevToken, data.get("token", ""))
                if row:
                    row.revoked = True
            return {"revoked": True}
        if not url.endswith("/2/oauth2/token"):
            raise HttpError(404, url, "fake-x: unknown endpoint")
        with self.sf() as db, db.begin():
            if data.get("grant_type") == "authorization_code":
                c = db.get(DevCode, data.get("code", ""))
                if not c or c.used or time.time() - c.created_at > CODE_TTL:
                    raise HttpError(400, url, '{"error":"invalid_request","error_description":"Value passed for the authorization code was invalid."}')
                c.used = True
                verifier = str(data.get("code_verifier", ""))
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                if challenge != c.challenge or data.get("redirect_uri") != c.redirect_uri:
                    raise HttpError(400, url, '{"error":"invalid_request","error_description":"PKCE or redirect_uri mismatch"}')
                user = c.username
            elif data.get("grant_type") == "refresh_token":
                r = db.get(DevToken, data.get("refresh_token", ""))
                if not r or r.kind != "refresh" or r.revoked:
                    raise HttpError(400, url, '{"error":"invalid_request"}')
                r.revoked = True  # X rotates refresh tokens
                user = r.username
            else:
                raise HttpError(400, url, '{"error":"unsupported_grant_type"}')
            return {"token_type": "bearer", "expires_in": 7200, "scope": "tweet.read tweet.write users.read offline.access",
                    "access_token": self._new_token(db, user, "access"), "refresh_token": self._new_token(db, user, "refresh")}

    # -- API v2 -------------------------------------------------------------------------
    def get_json(self, url: str, params: Optional[Mapping[str, Any]] = None, headers=None) -> Any:
        user = self._bearer_user(headers)
        path = urllib.parse.urlparse(url).path
        if path == "/2/users/me":
            return {"data": {"id": fake_user_id(user), "username": user, "name": user}}
        if path.startswith("/2/users/") and path.endswith("/mentions"):
            if path.split("/")[3] != fake_user_id(user):
                raise HttpError(403, url, '{"title":"Forbidden"}')
            since = int((params or {}).get("since_id") or 0)
            with self.sf() as db:
                rows = list(db.scalars(select(DevMention).where(DevMention.robot_username == user.lower(),
                                                                DevMention.id > since).order_by(DevMention.id).limit(100)))
            if not rows:
                return {"meta": {"result_count": 0}}
            return {"data": [{"id": str(r.id), "text": r.text, "author_id": fake_user_id(r.author),
                              "conversation_id": str(r.id)} for r in rows],
                    "includes": {"users": [{"id": fake_user_id(r.author), "username": r.author} for r in rows]},
                    "meta": {"result_count": len(rows)}}
        raise HttpError(404, url, "fake-x: unknown endpoint")

    def post_json(self, url: str, payload: Any, headers=None) -> Any:
        user = self._bearer_user(headers)
        if not url.endswith("/2/tweets"):
            raise HttpError(404, url, "fake-x: unknown endpoint")
        with self.sf() as db, db.begin():
            p = DevPost(robot_username=user.lower(), in_reply_to=str((payload.get("reply") or {}).get("in_reply_to_tweet_id", "")),
                        text=str(payload.get("text", ""))[:400])
            db.add(p)
            db.flush()
            return {"data": {"id": f"9{p.id:08d}", "text": p.text}}
