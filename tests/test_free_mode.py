"""v0.4 free mode + free catalog + spec additions. All offline (fake network)."""
import copy
import json
import subprocess
import sys

import pytest

from civicbot.resolver import JurisdictionResolver
from civicbot.robot import Robot, RobotProfile, StubXAdapter
from civicbot.robot.engine import free_mode, skill_allowed_in_free_mode
from civicbot.skills import (Catalog, CatalogSet, SafeFetcher, SkillRunner, SpecError, default_catalog, is_free,
                             validate_spec)
from civicbot.skills.catalog import free_catalog_dir
from civicbot.skills.template import render

CORE = {"open-meteo-weather", "mbta-next-trains", "chicago-311-nearby", "carris-metropolitana-arrivals"}


class Net:
    def __init__(self, answers=None):
        self.answers, self.calls = answers or {}, []

    def __call__(self, method, url, headers, body, timeout, max_bytes):
        self.calls.append(url)
        host = url.split("/")[2]
        return 200, {}, json.dumps(self.answers.get(host, {"ok": True})).encode()


def fetcher(net):
    return SafeFetcher(resolve=lambda h: ["93.184.216.34"], raw=net, min_host_interval=0, allow_nets=[])


def robot(fake, net=None, *, free=None, plan="", **kw):
    p = RobotProfile(robot_handle="joshua_robot", owner_handle="joshua", home_city="Bloomington, IN", plan=plan, **kw)
    p.grant_consent()
    return Robot(p, resolver=JurisdictionResolver(transport=fake), fetcher=fetcher(net or Net()), free=free)


# --- catalog ---------------------------------------------------------------------------------
def test_core_catalog_unchanged_and_free_catalog_separate():
    assert set(Catalog().names()) == CORE
    free = Catalog(free_catalog_dir())
    assert len(free.names()) >= 20 and not (set(free.names()) & CORE)
    allc = default_catalog()
    assert isinstance(allc, CatalogSet) and set(allc.names()) == CORE | set(free.names())
    assert set(allc.free_names()) == set(allc.names())  # everything shipped is free + keyless


def test_every_free_spec_is_pinned_reviewed_free_and_keyless():
    cat = Catalog(free_catalog_dir())
    for n in cat.names():
        e, s = cat.entry(n), cat.get(n)  # get() verifies sha256
        assert e["review"]["status"] == "reviewed" and e["free"] is True and e["api_id"] == s["api_id"]
        assert s["kind"] == "read" and s["cost"] == "free" and (s.get("auth") or {}).get("type", "none") == "none"
        assert s["terms"]["url"].startswith("https://") and s["terms"]["attribution"]


def test_is_free_rules():
    base = Catalog().get("open-meteo-weather")
    assert is_free(base)
    assert not is_free({k: v for k, v in base.items() if k != "cost"})          # untagged = not free
    assert not is_free(dict(base, cost="free-key"))
    assert not is_free(dict(base, auth={"type": "api_key", "in": "header", "name": "k", "secret_ref": "k"}))
    assert is_free(Catalog().get("mbta-next-trains"))  # optional key (required: false) still free


# --- spec additions are backward compatible --------------------------------------------------
def test_old_specs_without_new_fields_still_validate():
    s = copy.deepcopy(Catalog().get("open-meteo-weather"))
    for k in ("cost", "api_id"):
        s.pop(k, None)
    validate_spec(s)


def test_bad_new_fields_rejected():
    s = copy.deepcopy(Catalog().get("open-meteo-weather"))
    with pytest.raises(SpecError):
        validate_spec(dict(s, cost="cheap"))
    with pytest.raises(SpecError):
        validate_spec(dict(s, api_id="Not Valid!"))
    r = copy.deepcopy(s)
    r["response"]["replies"] = ["{temp|nosuchfilter} now"]
    with pytest.raises(SpecError) as e:
        validate_spec(r)
    assert "unknown filter" in str(e.value.problems)
    r = copy.deepcopy(s)
    r["response"]["extract"]["temp"] = "current.{location.lat}"
    with pytest.raises(SpecError) as e:
        validate_spec(r)
    assert "extract paths" in str(e.value.problems)


def test_input_case_and_input_in_extract_path():
    s = copy.deepcopy(default_catalog().get("currency-convert"))
    runner = SkillRunner(fetcher=None)
    ctx = runner.context(s, "convert gbp to jpy")
    assert ctx.inputs == {"from": "GBP", "to": "JPY"}
    out = runner.replies(s, {"date": "2026-10-09", "rates": {"JPY": 201.12346}}, ctx)
    assert "1 GBP = 201.1235 JPY" in out[0]


def test_new_filters():
    look = {"a": 0.89241, "ms": 1791648000000}.get
    assert render("{a|rate} {a|money} {ms|ms_date} {ms|ms_time}", look) == "0.8924 0.89 2026-10-10 16:00 UTC"


# --- free mode -------------------------------------------------------------------------------
def test_free_mode_switches(monkeypatch):
    monkeypatch.delenv("CIVICBOT_FREE", raising=False)
    assert not free_mode(RobotProfile(robot_handle="r", owner_handle="o"))
    assert free_mode(RobotProfile(robot_handle="r", owner_handle="o", plan="free"))
    monkeypatch.setenv("CIVICBOT_FREE", "1")
    assert free_mode(RobotProfile(robot_handle="r", owner_handle="o"))


def test_free_mode_learns_only_free_catalog_skills(fake, monkeypatch):
    monkeypatch.delenv("CIVICBOT_FREE", raising=False)
    net = Net({"api.open-meteo.com": {"elevation": [239.0]}})
    r, x = robot(fake, net, plan="free"), StubXAdapter(robot="joshua_robot")
    assert r.free
    for t in ["learn elevation", "learn https://specs.example.org/x.json", "learn not-a-skill", "elevation here"]:
        x.add_mention("joshua", f"@joshua_robot {t}")
    a1, a2, a3, a4 = r.run_once(x)
    assert "elevation" in r.profile.skills and "Learned" in a1.reply or "learned" in a1.reply.lower()
    assert "Free mode" in a2.reply and "Free mode" in a3.reply
    assert not any("specs.example.org" in u for u in net.calls)  # refused before any fetch
    assert "239 m" in a4.reply


def test_free_mode_hides_non_free_installed_skills(fake):
    r = robot(fake, free=True)
    spec = copy.deepcopy(Catalog().get("open-meteo-weather"))
    r.profile.skills["weather-from-file"] = dict(spec, name="weather-from-file", _source="/tmp/x.json")
    r.profile.skills["open-meteo-weather"] = dict(spec, _source="catalog:open-meteo-weather")
    names = {s["name"] for s in r.skills()}
    assert "open-meteo-weather" in names and "weather-from-file" not in names
    assert {"city-311-report", "city-311-status"} <= names  # built-ins stay
    assert skill_allowed_in_free_mode({"handler": "builtin:report"})
    r2 = robot(fake, free=False)
    r2.profile.skills = dict(r.profile.skills)
    assert "weather-from-file" in {s["name"] for s in r2.skills()}  # standard mode unchanged


def test_free_mode_311_stays_dry_run_even_with_key(fake):
    r = robot(fake, free=True, send_enabled=True)
    r.api_keys = {"bloomington-in": "KEY"}
    x = StubXAdapter(robot="joshua_robot")
    x.add_mention("joshua", "@joshua_robot pothole at 401 N Morton St, Bloomington, IN")
    x.add_mention("joshua", "@joshua_robot yes")
    a1, a2 = r.run_once(x)
    assert a1.prepared and fake.posts == [] and "not filed" in a2.reply


def test_free_mode_cannot_enable_write_skills(fake):
    r = robot(fake, free=True)
    r.profile.skills["demo-write"] = {"name": "demo-write", "kind": "write", "_source": "catalog:demo-write"}
    x = StubXAdapter(robot="joshua_robot")
    x.add_mention("joshua", "@joshua_robot enable skill demo-write")
    (a,) = r.run_once(x)
    assert "dry-run" in a.reply and r.profile.write_enabled == []


def test_profile_plan_roundtrip(tmp_path):
    from civicbot.robot import ProfileStore
    st = ProfileStore(str(tmp_path / "p.json"))
    st.put(RobotProfile(robot_handle="r", owner_handle="o", plan="free"))
    assert ProfileStore(str(tmp_path / "p.json")).get("r").plan == "free"
    old = json.loads((tmp_path / "p.json").read_text())
    old["r"].pop("plan")
    (tmp_path / "p.json").write_text(json.dumps(old))  # profiles saved by v0.3 still load
    assert ProfileStore(str(tmp_path / "p.json")).get("r").plan == ""


# --- CLI -------------------------------------------------------------------------------------
def _cli(*args, env=None):
    import os
    e = dict(os.environ, **(env or {}))
    e.pop("CIVICBOT_FREE", None)
    return subprocess.run([sys.executable, "-m", "civicbot", *args], capture_output=True, text=True, timeout=60, env=e)


def test_cli_chat_offline_free():
    p = _cli("chat", "--offline", "--free", "--city", "Bloomington, IN", "-c", "weather tomorrow", "-c", "usd to eur",
             "-c", "learn https://example.org/x.json")
    assert p.returncode == 0, p.stderr
    assert "Bloomington, IN" in p.stdout and "72°F" in p.stdout and "0.8924" in p.stdout and "Free mode only" in p.stdout


def test_cli_apis_json_and_simulate_free():
    p = _cli("apis", "--category", "Transit", "--json")
    rows = json.loads(p.stdout)
    assert rows and all(r["category"] == "Transit" for r in rows)
    s = _cli("simulate", "--offline", "--free", "--robot", "joshs_robot:joshua:Bloomington, IN",
             "joshua> @joshs_robot learn https://example.org/x.json", "joshua> @joshs_robot learn uv-index")
    assert s.returncode == 0 and "Free mode only" in s.stdout and "uv-index" in s.stdout


def test_cli_run_is_shadow_by_default(tmp_path, monkeypatch, capsys):
    """`civicbot run` polls the robot's mentions and only PRINTS replies unless --post (fake X adapter)."""
    pytest.importorskip("cryptography")
    from civicbot import cli_extra
    from civicbot.robot import ProfileStore
    from civicbot.robot.x_adapter import Mention
    from civicbot.x import api as xapi
    from civicbot.x.tokens import EncryptedFileTokenStore
    monkeypatch.setenv("CIVICBOT_TOKEN_KEY", EncryptedFileTokenStore.generate_key().decode())
    monkeypatch.setenv("X_CLIENT_ID", "test-client")
    monkeypatch.delenv("CIVICBOT_FREE", raising=False)
    st = ProfileStore(str(tmp_path / "profiles.json"))
    p = RobotProfile(robot_handle="my_robot", owner_handle="me", home_city="Bloomington, IN", robot_user_id="42")
    p.grant_consent()
    st.put(p)
    posted = []

    class FakeX:
        def __init__(self, robot_id, *a, **k):
            self.robot_id = robot_id

        def poll_mentions(self, since_id=None):
            return [Mention(id="100", author="me", text="@my_robot learn https://example.org/x.json", robot="my_robot")]

        def post_reply(self, in_reply_to_id, text):
            posted.append(text)
            return "1"
    monkeypatch.setattr(xapi, "XApiV2Adapter", FakeX)
    args = type("A", (), {"robot": "my_robot", "state_dir": str(tmp_path), "free": True, "post": False, "verbose": False})
    assert cli_extra.cmd_run(args) == 0
    out = capsys.readouterr().out
    assert "SHADOW" in out and "would reply to 100" in out and "Free mode only" in out and posted == []
    assert ProfileStore(str(tmp_path / "profiles.json")).get("my_robot").plan == "free"
