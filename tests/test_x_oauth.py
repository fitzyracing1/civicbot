import base64
import hashlib
import json
import os
import stat
import time
import urllib.parse

import pytest

from civicbot.http import HttpError
from civicbot.robot import ProfileStore
from civicbot.x import (AUTHORIZE_URL, REVOKE_URL, TOKEN_URL, EncryptedFileTokenStore, InMemoryTokenStore,
                        OAuthConfig, OAuthError, OAuthToken, XApiError, XApiV2Adapter, XOAuth2, finish_connect,
                        make_pkce_pair)
from conftest import FakeTransport

TOKEN_RESP = {"token_type": "bearer", "expires_in": 7200, "access_token": "AT-1",
              "refresh_token": "RT-1", "scope": "tweet.read tweet.write users.read offline.access"}


def oauth(transport=None, secret=None):
    return XOAuth2(OAuthConfig("CLIENT", "https://civicbot.example/cb", client_secret=secret),
                   transport or FakeTransport())


def test_pkce_pair_s256():
    v, c = make_pkce_pair()
    assert 43 <= len(v) <= 128
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def test_authorize_url_no_network():
    t = FakeTransport()
    url, pending = oauth(t).start("@joshs_robot", "joshua")
    assert url.startswith(AUTHORIZE_URL + "?") and t.calls == [] and t.posts == []
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert q["response_type"] == "code" and q["client_id"] == "CLIENT"
    assert q["scope"] == "tweet.read tweet.write users.read offline.access"
    assert "%20" in url and "+" not in url  # space-encoded scopes
    assert q["code_challenge_method"] == "S256" and q["state"] == pending.state
    expect = base64.urlsafe_b64encode(hashlib.sha256(pending.code_verifier.encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == expect and pending.code_verifier not in url
    assert pending.robot_hint == "joshs_robot"


def test_exchange_public_client():
    t = FakeTransport(post_response=TOKEN_RESP)
    o = oauth(t)
    _, p = o.start("joshs_robot", "joshua")
    tok, p2 = o.exchange(p.state, "CODE", now=1000)
    url, data = t.posts[0]
    assert url == TOKEN_URL and data["grant_type"] == "authorization_code" and data["code"] == "CODE"
    assert data["code_verifier"] == p.code_verifier and data["redirect_uri"] == "https://civicbot.example/cb"
    assert "Authorization" not in t.headers[-1]
    assert tok.access_token == "AT-1" and tok.expires_at == 1000 + 7200 and tok.refresh_token == "RT-1"
    assert "AT-1" not in repr(tok) and "RT-1" not in repr(tok)
    with pytest.raises(OAuthError):  # state is single-use
        o.exchange(p.state, "CODE")


def test_exchange_confidential_basic_auth():
    t = FakeTransport(post_response=TOKEN_RESP)
    o = oauth(t, secret="SECRET")
    _, p = o.start()
    o.exchange(p.state, "CODE")
    assert t.headers[-1]["Authorization"] == "Basic " + base64.b64encode(b"CLIENT:SECRET").decode()


def test_exchange_rejects_bad_state_and_expired():
    o = oauth(FakeTransport(post_response=TOKEN_RESP))
    with pytest.raises(OAuthError):
        o.exchange("forged", "CODE")
    _, p = o.start()
    with pytest.raises(OAuthError, match="expired"):
        o.exchange(p.state, "CODE", now=p.created_at + 3600)


def test_exchange_http_error_wrapped():
    class Boom(FakeTransport):
        def post_form(self, url, data, headers=None):
            raise HttpError(400, url, '{"error":"invalid_request"}')
    o = oauth(Boom())
    _, p = o.start()
    with pytest.raises(OAuthError, match="400"):
        o.exchange(p.state, "CODE")


def test_refresh_and_revoke():
    t = FakeTransport(post_response={"access_token": "AT-2", "expires_in": 7200})
    o = oauth(t)
    new = o.refresh(OAuthToken("AT-1", refresh_token="RT-1"), now=0)
    assert t.posts[0][1] == {"refresh_token": "RT-1", "grant_type": "refresh_token", "client_id": "CLIENT"}
    assert new.access_token == "AT-2" and new.refresh_token == "RT-1"
    with pytest.raises(OAuthError):
        o.refresh(OAuthToken("AT-1"))
    o.revoke(new)
    assert [p[0] for p in t.posts[1:]] == [REVOKE_URL, REVOKE_URL]


def test_encrypted_store_roundtrip(tmp_path):
    key = EncryptedFileTokenStore.generate_key()
    path = tmp_path / "tokens.enc"
    s = EncryptedFileTokenStore(str(path), key=key)
    s.put("joshs_robot", OAuthToken("SUPERSECRET-ACCESS", refresh_token="SUPERSECRET-REFRESH", expires_at=5))
    raw = path.read_bytes()
    assert b"SUPERSECRET" not in raw and b"joshs_robot" not in raw
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert EncryptedFileTokenStore(str(path), key=key).get("joshs_robot").refresh_token == "SUPERSECRET-REFRESH"
    with pytest.raises(Exception):
        EncryptedFileTokenStore(str(path), key=EncryptedFileTokenStore.generate_key()).get("joshs_robot")
    s.delete("joshs_robot")
    assert s.get("joshs_robot") is None


def test_encrypted_store_requires_key(monkeypatch, tmp_path):
    monkeypatch.delenv("CIVICBOT_TOKEN_KEY", raising=False)
    with pytest.raises(ValueError):
        EncryptedFileTokenStore(str(tmp_path / "t"))


# --- real adapter (against a fake transport only) ------------------------------------------
MENTIONS = {"data": [{"id": "1002", "text": "@joshs_robot pothole at 401 N Morton St", "author_id": "u1",
                      "conversation_id": "1002"},
                     {"id": "1001", "text": "@joshs_robot hi", "author_id": "u2", "conversation_id": "1001"}],
            "includes": {"users": [{"id": "u1", "username": "joshua"}, {"id": "u2", "username": "someone"}]}}


def connected(t, expires_at=None):
    store = InMemoryTokenStore()
    store.put("joshs_robot", OAuthToken("AT-1", refresh_token="RT-1",
                                        expires_at=time.time() + 7200 if expires_at is None else expires_at))
    return store, XApiV2Adapter("joshs_robot", oauth(t), store, robot_user_id="555", enabled=True)


def test_adapter_disabled_without_flag_or_token():
    t = FakeTransport()
    store = InMemoryTokenStore()
    with pytest.raises(RuntimeError, match="disabled"):
        XApiV2Adapter("joshs_robot", oauth(t), store).poll_mentions()
    with pytest.raises(RuntimeError, match="not connected"):
        XApiV2Adapter("joshs_robot", oauth(t), store, enabled=True).post_reply("1", "hi")
    assert t.calls == [] and t.posts == []


def test_adapter_polls_and_replies_with_user_token():
    t = FakeTransport({r"api\.x\.com/2/users/555/mentions": MENTIONS})
    t.add_post(r"api\.x\.com/2/tweets", {"data": {"id": "2001", "text": "ok"}})
    _, x = connected(t)
    ms = x.poll_mentions(since_id="1000")
    assert [m.id for m in ms] == ["1001", "1002"] and ms[1].author == "joshua" and ms[1].robot == "joshs_robot"
    assert t.calls[0][1]["since_id"] == "1000" and t.headers[0]["Authorization"] == "Bearer AT-1"
    assert x.post_reply("1002", "Drafted ... [bot]") == "2001"
    url, payload = t.posts[-1]
    assert url == "https://api.x.com/2/tweets"
    assert payload == {"text": "Drafted ... [bot]", "reply": {"in_reply_to_tweet_id": "1002"}}
    with pytest.raises(ValueError):
        x.post_reply("1002", "x" * 281)


def test_adapter_refreshes_expiring_token_and_saves_it():
    t = FakeTransport({r"mentions": {"data": []}})
    t.add_post(r"oauth2/token", {"access_token": "AT-2", "refresh_token": "RT-2", "expires_in": 7200})
    store, x = connected(t, expires_at=time.time() + 10)
    x.poll_mentions()
    assert store.get("joshs_robot").access_token == "AT-2" and t.headers[-1]["Authorization"] == "Bearer AT-2"


def test_adapter_rate_limit_error():
    def limited(u, p):
        raise HttpError(429, u, "Too Many Requests")
    _, x = connected(FakeTransport({r"mentions": limited}))
    with pytest.raises(XApiError, match="rate limited"):
        x.poll_mentions()


def test_finish_connect_checks_robot_identity_and_consent():
    t = FakeTransport({r"users/me": {"data": {"id": "555", "username": "joshs_robot"}}}, post_response=TOKEN_RESP)
    o, tokens, profiles = oauth(t), InMemoryTokenStore(), ProfileStore()
    _, p = o.start("joshs_robot", "joshua")
    with pytest.raises(OAuthError, match="consent"):
        finish_connect(o, tokens, profiles, state=p.state, code="C", consent_accepted=False)
    prof = finish_connect(o, tokens, profiles, state=p.state, code="C", consent_accepted=True,
                          home_city="Bloomington, IN")
    assert prof.robot_user_id == "555" and prof.owner_handle == "joshua" and prof.has_consent
    assert not prof.status_updates and tokens.get("joshs_robot").access_token == "AT-1"
    assert profiles.get("joshs_robot") is prof and len(tokens._d) == 1


def test_finish_connect_rejects_personal_account():
    t = FakeTransport({r"users/me": {"data": {"id": "1", "username": "joshua"}}}, post_response=TOKEN_RESP)
    o, tokens = oauth(t), InMemoryTokenStore()
    _, p = o.start("", "joshua")
    with pytest.raises(OAuthError, match="personal account"):
        finish_connect(o, tokens, ProfileStore(), state=p.state, code="C", consent_accepted=True)
    assert tokens._d == {} and any(u == REVOKE_URL for u, _ in t.posts)
