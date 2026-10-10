"""Signup site + hosted runner, end to end against the dev-mode fake X (no network, no credentials)."""
import json
import logging
import re
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("cryptography")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from civicbot.web.app import create_app  # noqa: E402
from civicbot.web.budget import Budget, GuardrailHit, MeteredAdapter  # noqa: E402
from civicbot.web.config import ConfigError, Settings  # noqa: E402
from civicbot.web.db import DevPost, DevToken, EventRow, Owner, RobotRow, TokenRow, UsageRow  # noqa: E402
from civicbot.web.fakex import add_mention  # noqa: E402
from civicbot.web.logs import redact  # noqa: E402
from civicbot.web.services import build_services  # noqa: E402
from civicbot.web.worker import tick  # noqa: E402
from civicbot.robot.x_adapter import StubXAdapter  # noqa: E402

BASE = "http://localhost:8000"


def make(tmp_path, **kw):
    s = Settings(dev_mode=True, database_url=f"sqlite:///{tmp_path}/t.db", data_dir=str(tmp_path), base_url=BASE,
                 poll_interval_s=0, **kw).finalize()
    svc = build_services(s)
    app = create_app(s, svc)
    return TestClient(app, base_url=BASE, follow_redirects=False), svc


def csrf(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def x_approve(c, location: str, username: str, action: str = "approve"):
    """Play the person on the (fake) X authorize page; returns the callback response."""
    assert location.startswith(BASE + "/dev/x/oauth2/authorize")
    page = c.get(location)
    assert page.status_code == 200
    q = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
    r = c.post("/dev/x/oauth2/authorize", data={"csrf_token": csrf(page.text), "redirect_uri": q["redirect_uri"],
                                                "state": q["state"], "code_challenge": q["code_challenge"],
                                                "username": username, "action": action})
    assert r.status_code == 303 and r.headers["location"].startswith(BASE + "/auth/x/callback?")
    return c.get(r.headers["location"])


def sign_in(c, handle):
    page = c.get("/start")
    r = c.post("/auth/owner", data={"csrf_token": csrf(page.text)})
    assert r.status_code == 303
    cb = x_approve(c, r.headers["location"], handle)
    assert cb.status_code == 303 and cb.headers["location"] == "/start", cb.text[:300]
    return cb


CHECKS = {"separate": "on", "bio": "on", "automated": "on", "password": "on"}


def connect_robot(c, robot, as_user=None, followups=False):
    page = c.get("/setup/robot-account")
    r = c.post("/setup/robot-account", data={"csrf_token": csrf(page.text), "robot_handle": robot, **CHECKS})
    assert r.status_code == 303 and r.headers["location"] == "/setup/connect", r.text[:400]
    page = c.get("/setup/connect")
    data = {"csrf_token": csrf(page.text), "consent": "on"}
    if followups:
        data["followups"] = "on"
    r = c.post("/setup/connect", data=data)
    assert r.status_code == 303
    return x_approve(c, r.headers["location"], as_user or robot)


def finish_wizard(c, rid, place="Bloomington, IN", skills=("city-311-report", "city-311-status", "open-meteo-weather")):
    page = c.get(f"/robots/{rid}/city")
    r = c.post(f"/robots/{rid}/city", data={"csrf_token": csrf(page.text), "place": place})
    assert r.status_code == 200
    m = re.search(r'name="lat" value="([^"]+)".*?name="lng" value="([^"]+)".*?name="has311" value="(\d)"', r.text, re.S)
    r2 = c.post(f"/robots/{rid}/city/save", data={"csrf_token": csrf(r.text), "place": place, "lat": m.group(1),
                                                  "lng": m.group(2), "has311": m.group(3), "wizard": "1"})
    assert r2.headers["location"] == f"/robots/{rid}/skills"
    page = c.get(f"/robots/{rid}/skills")
    r3 = c.post(f"/robots/{rid}/skills", data={"csrf_token": csrf(page.text), "skill": list(skills), "wizard": "1"})
    assert r3.headers["location"] == f"/robots/{rid}/done"
    return r


def test_full_signup_flow_and_runner_reply(tmp_path):
    c, svc = make(tmp_path)
    assert "Get your robot" in c.get("/").text
    sign_in(c, "ana_demo")
    assert c.get("/start").headers["location"] == "/setup/robot-account"
    cb = connect_robot(c, "anas_robot", followups=True)
    assert cb.headers["location"] == "/robots/anas_robot/city"
    city = finish_wizard(c, "anas_robot")
    assert "311 is available here" in city.text and "Bloomington" in city.text
    done = c.get("/robots/anas_robot/done").text
    assert "@anas_robot pothole at 401 N Morton St" in done and "@anas_robot STOP" in done
    assert "what&#39;s the weather in Bloomington" in done or "weather in Bloomington" in done

    with svc.sf() as db:
        o = db.scalar(select(Owner))
        row = db.get(RobotRow, "anas_robot")
        p = json.loads(row.profile_json)
        assert o.handle == "ana_demo" and row.owner_id == o.id and row.status == "active"
        assert p["owner_user_id"] == o.x_user_id and p["consent"]["version"] and p["status_updates"] is True
        assert "open-meteo-weather" in p["skills"] and p["default_lat"] == pytest.approx(39.1653, abs=1e-3)
        # owner's sign-in token was revoked right after identifying them
        assert all(t.revoked for t in db.scalars(select(DevToken).where(DevToken.username == "ana_demo")))

    # owner mentions the robot on (fake) X; the runner replies from the robot account
    dash = c.get("/dashboard").text
    c.post("/dev/robots/anas_robot/mention", data={"csrf_token": csrf(dash), "author": "ana_demo",
                                                    "text": "pothole at 401 N Morton St"})
    add_mention(svc.sf, "anas_robot", "stranger", "@anas_robot pothole at Kirkwood")  # not allowlisted
    add_mention(svc.sf, "anas_robot", "ana_demo", "@anas_robot weather")
    acts = tick(svc)
    assert len(acts) == 3
    with svc.sf() as db:
        posts = list(db.scalars(select(DevPost).order_by(DevPost.id)))
        texts = [x.text for x in posts]
    assert len(posts) == 2, texts                      # nobody but the owner gets a reply
    assert any("Street Lights" in t or "311" in t for t in texts) and any("°F" in t for t in texts)
    assert all("http" not in t for t in texts)
    assert tick(svc) == []                             # handled mentions are not answered twice
    dash = c.get("/dashboard").text
    assert "2 replies" in dash and "Bloomington" in dash and "anas_robot" in dash
    assert c.get("/healthz").json()["worker"]["ok"] is True
    with svc.sf() as db:
        u = {x.metric: x for x in db.scalars(select(UsageRow).where(UsageRow.scope == "anas_robot"))}
    assert u["mentions"].count == 3 and u["replies"].count == 2
    assert u["mentions"].cost_usd == pytest.approx(3 * 0.005 + 2 * 0.010)


def test_no_311_city_disables_report_skill(tmp_path):
    c, svc = make(tmp_path)
    sign_in(c, "sam")
    connect_robot(c, "sams_bot")
    r = finish_wizard(c, "sams_bot", place="Springfield, MO", skills=("open-meteo-weather",))
    assert "No 311 API here yet" in r.text
    p = json.loads(svc.sf().get(RobotRow, "sams_bot").profile_json)
    assert "city-311-report" in p["disabled_builtins"] and "pothole" not in c.get("/robots/sams_bot/done").text


def test_csrf_required_and_cross_origin_refused(tmp_path):
    c, _ = make(tmp_path)
    page = c.get("/start")
    assert c.post("/auth/owner", data={}).status_code == 403
    assert c.post("/auth/owner", data={"csrf_token": "nope"}).status_code == 403
    r = c.post("/auth/owner", data={"csrf_token": csrf(page.text)}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_oauth_state_must_match_this_browser(tmp_path):
    c, _ = make(tmp_path)
    page = c.get("/start")
    r = c.post("/auth/owner", data={"csrf_token": csrf(page.text)})
    q = parse_qs(urlparse(r.headers["location"]).query)
    other = TestClient(c.app, base_url=BASE, follow_redirects=False)  # attacker's browser
    bad = other.get("/auth/x/callback", params={"state": q["state"][0], "code": "devcode_x"})
    assert bad.status_code == 400 and "start again" in bad.text
    assert c.get("/auth/x/callback", params={"state": "forged", "code": "x"}).status_code == 400


def test_callback_replay_refused(tmp_path):
    c, _ = make(tmp_path)
    page = c.get("/start")
    loc = c.post("/auth/owner", data={"csrf_token": csrf(page.text)}).headers["location"]
    q = {k: v[0] for k, v in parse_qs(urlparse(loc).query).items()}
    auth = c.get(loc)
    r = c.post("/dev/x/oauth2/authorize", data={"csrf_token": csrf(auth.text), "redirect_uri": q["redirect_uri"],
                                                "state": q["state"], "code_challenge": q["code_challenge"],
                                                "username": "ana_demo", "action": "approve"})
    cb_url = r.headers["location"]
    assert c.get(cb_url).headers["location"] == "/start"
    assert c.get(cb_url).status_code == 400            # same state+code again: refused


def test_cancel_on_x_connects_nothing(tmp_path):
    c, svc = make(tmp_path)
    page = c.get("/start")
    loc = c.post("/auth/owner", data={"csrf_token": csrf(page.text)}).headers["location"]
    cb = x_approve(c, loc, "ana_demo", action="cancel")
    assert cb.headers["location"] == "/start" and "cancelled" in c.get("/start").text
    with svc.sf() as db:
        assert db.scalar(select(Owner)) is None


def test_robot_must_differ_from_owner_and_match_hint(tmp_path):
    c, svc = make(tmp_path)
    sign_in(c, "joshua_demo")
    page = c.get("/setup/robot-account")
    r = c.post("/setup/robot-account", data={"csrf_token": csrf(page.text), "robot_handle": "joshua_demo", **CHECKS})
    assert r.status_code == 400 and "personal account" in r.text
    r = c.post("/setup/robot-account", data={"csrf_token": csrf(page.text), "robot_handle": "joshs_robot", "bio": "on"})
    assert r.status_code == 400 and "checklist" in r.text
    # approving on X with the PERSONAL account is caught and the token revoked
    cb = connect_robot(c, "joshs_robot", as_user="joshua_demo")
    assert cb.status_code == 400 and "you approved as @joshua_demo, but this robot is @joshs_robot" in cb.text
    assert c.get("/setup/connect").status_code == 200   # "Try again" keeps the robot handle
    with svc.sf() as db:
        assert db.get(RobotRow, "joshs_robot") is None and db.scalar(select(TokenRow)) is None
        assert all(t.revoked for t in db.scalars(select(DevToken).where(DevToken.username == "joshua_demo")))


def test_owner_isolation(tmp_path):
    a, svc = make(tmp_path)
    sign_in(a, "ana_demo")
    connect_robot(a, "anas_robot")
    b = TestClient(a.app, base_url=BASE, follow_redirects=False)
    sign_in(b, "ben_demo")
    assert b.get("/robots/anas_robot/city").status_code == 404
    assert b.get("/robots/anas_robot/skills").status_code == 404
    tok = csrf(b.get("/setup/robot-account").text)
    for act in ("pause", "disconnect", "delete", "sending"):
        assert b.post(f"/robots/anas_robot/{act}", data={"csrf_token": tok, "confirm_handle": "anas_robot"}).status_code == 404
    assert b.post("/dev/robots/anas_robot/mention", data={"csrf_token": tok, "text": "hi"}).status_code == 404
    assert "anas_robot" not in b.get("/dashboard").text
    # Ben can't take over Ana's robot by connecting it himself
    cb = connect_robot(b, "anas_robot")
    assert cb.status_code == 400 and "someone else" in cb.text
    with svc.sf() as db:
        assert db.get(RobotRow, "anas_robot").owner_id == db.scalar(select(Owner).where(Owner.handle == "ana_demo")).id
    assert svc.tokens.get("anas_robot") is not None


def test_signup_rate_limited(tmp_path):
    c, _ = make(tmp_path, signup_rate_limit=3)
    tok = csrf(c.get("/start").text)
    codes = [c.post("/auth/owner", data={"csrf_token": tok}).status_code for _ in range(4)]
    assert codes[:3] == [303, 303, 303] and codes[3] == 429


def test_tokens_encrypted_and_never_logged(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    c, svc = make(tmp_path)
    sign_in(c, "ana_demo")
    connect_robot(c, "anas_robot")
    with svc.sf() as db:
        secrets_ = [t.token for t in db.scalars(select(DevToken))]
        ct = db.get(TokenRow, "anas_robot").ciphertext
    assert secrets_ and all(s not in ct for s in secrets_) and ct.startswith("gAAAA")
    raw = (tmp_path / "t.db").read_bytes()
    live = svc.tokens.get("anas_robot")
    assert live.access_token.encode() not in raw and live.refresh_token.encode() not in raw
    logged = caplog.text + "".join(r.getMessage() for r in caplog.records)
    assert all(s not in logged for s in secrets_)
    assert "devcode_" not in logged or "[REDACTED]" in logged
    assert "access_token" not in repr(live)


def test_redaction():
    s = redact("GET /auth/x/callback?state=abc123&code=devcode_SECRET HTTP/1.1 Authorization: Bearer AAAA.bbb")
    assert "SECRET" not in s and "abc123" not in s and "AAAA.bbb" not in s
    assert "SECRETTOKEN" not in redact('{"access_token": "SECRETTOKEN", "refresh_token":"r1"}')


def test_pause_disconnect_revokes_and_delete_account(tmp_path):
    c, svc = make(tmp_path)
    sign_in(c, "ana_demo")
    connect_robot(c, "anas_robot")
    tok = csrf(c.get("/dashboard").text)
    c.post("/robots/anas_robot/pause", data={"csrf_token": tok})
    add_mention(svc.sf, "anas_robot", "ana_demo", "@anas_robot weather")
    assert tick(svc) == []                                 # paused robots aren't polled
    c.post("/robots/anas_robot/resume", data={"csrf_token": tok})
    c.post("/robots/anas_robot/disconnect", data={"csrf_token": tok})
    with svc.sf() as db:
        assert db.get(RobotRow, "anas_robot").status == "disconnected"
        assert db.get(TokenRow, "anas_robot") is None
        assert all(t.revoked for t in db.scalars(select(DevToken).where(DevToken.username == "anas_robot")))
    r = c.post("/robots/anas_robot/resume", data={"csrf_token": tok})
    assert r.headers["location"].startswith("/setup/connect")
    exported = c.get("/account/export")
    assert exported.status_code == 200 and "anas_robot" in exported.text and "access_token" not in exported.text
    assert c.post("/account/delete", data={"csrf_token": tok, "confirm": "nope"}).headers["location"] == "/account"
    r = c.post("/account/delete", data={"csrf_token": tok, "confirm": "DELETE"})
    assert r.headers["location"] == "/"
    with svc.sf() as db:
        assert db.scalar(select(Owner)) is None and db.scalar(select(RobotRow)) is None
        assert db.scalar(select(EventRow)) is None and db.scalar(select(UsageRow).where(UsageRow.scope == "anas_robot")) is None
    assert c.get("/dashboard").headers["location"] == "/start"


def test_sending_toggle_needs_confirmation(tmp_path):
    c, svc = make(tmp_path)
    sign_in(c, "ana_demo")
    connect_robot(c, "anas_robot")
    tok = csrf(c.get("/dashboard").text)
    c.post("/robots/anas_robot/sending", data={"csrf_token": tok, "enable": "1"})
    assert json.loads(svc.sf().get(RobotRow, "anas_robot").profile_json)["send_enabled"] is False
    c.post("/robots/anas_robot/sending", data={"csrf_token": tok, "enable": "1", "confirm": "on"})
    assert json.loads(svc.sf().get(RobotRow, "anas_robot").profile_json)["send_enabled"] is True
    assert "ON, files real requests after your YES" in c.get("/dashboard").text
    c.post("/robots/anas_robot/sending", data={"csrf_token": tok, "enable": "0"})
    assert json.loads(svc.sf().get(RobotRow, "anas_robot").profile_json)["send_enabled"] is False


def test_spend_cap_and_per_robot_caps(tmp_path):
    c, svc = make(tmp_path, daily_spend_cap_usd=0.0)
    sign_in(c, "ana_demo")
    connect_robot(c, "anas_robot")
    add_mention(svc.sf, "anas_robot", "ana_demo", "@anas_robot weather")
    assert tick(svc) == []
    with svc.sf() as db:
        assert db.scalar(select(DevPost)) is None
    svc.settings.daily_spend_cap_usd = 5.0
    svc.settings.robot_daily_replies = 0
    acts = tick(svc)
    assert acts and "replies today" in acts[0].log[0]
    with svc.sf() as db:
        assert db.scalar(select(DevPost)) is None
        assert db.get(RobotRow, "anas_robot").last_error.startswith("robot posted 0 replies")
        assert db.scalar(select(EventRow).where(EventRow.kind == "guardrail")) is not None


def test_shadow_mode_records_but_does_not_post(tmp_path):
    _, svc = make(tmp_path)
    stub = StubXAdapter(robot="r1")
    m = MeteredAdapter(stub, Budget(svc.sf, svc.settings), "r1", write_enabled=False, sf=svc.sf)
    assert m.post_reply("1", "hello").startswith("shadow-") and stub.outbox == []
    svc.settings.app_polls_per_15min = 0
    with pytest.raises(GuardrailHit):
        m.poll_mentions()


def test_security_headers_and_cookie_flags(tmp_path):
    s = Settings(dev_mode=False, base_url="https://civicbot.example", database_url=f"sqlite:///{tmp_path}/p.db",
                 data_dir=str(tmp_path), session_secret="x" * 40, token_key=__import__("cryptography.fernet").fernet.Fernet.generate_key().decode(),
                 x_client_id="id", x_client_secret="sec").finalize()
    c = TestClient(create_app(s), base_url="https://civicbot.example")
    r = c.get("/start")
    ck = r.headers["set-cookie"].lower()
    assert ck.startswith("__host-civicbot=") and "secure" in ck and "httponly" in ck and "samesite=lax" in ck
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"
    assert "strict-transport-security" in r.headers
    assert c.get("/dev/x/oauth2/authorize").status_code == 404     # no fake X outside dev mode
    loc = c.post("/auth/owner", data={"csrf_token": csrf(r.text)}, follow_redirects=False).headers["location"]
    assert loc.startswith("https://x.com/i/oauth2/authorize?") and "code_challenge_method=S256" in loc
    assert "redirect_uri=https%3A%2F%2Fcivicbot.example%2Fauth%2Fx%2Fcallback" in loc


def test_production_config_requires_secrets(monkeypatch):
    for k in ("CIVICBOT_DEV_MODE", "SESSION_SECRET", "CIVICBOT_TOKEN_KEY", "X_CLIENT_ID", "X_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env()
    with pytest.raises(ConfigError):
        Settings(base_url="http://civicbot.example", session_secret="x" * 40, token_key="k", x_client_id="i",
                 x_client_secret="s").finalize()


def test_healthz_reports_db_and_worker(tmp_path):
    c, svc = make(tmp_path)
    h = c.get("/healthz").json()
    assert h["db"] is True and h["worker"]["ok"] is False
    assert c.get("/healthz?strict=1").status_code == 503
    tick(svc)
    assert c.get("/healthz?strict=1").status_code == 200
