import copy
import json
import os
import shutil
import stat
import time

import pytest

from civicbot.resolver import JurisdictionResolver
from civicbot.robot import Fleet, ProfileStore, Robot, RobotProfile, StubXAdapter
from civicbot.secrets import EncryptedFileSecretStore, InMemorySecretStore
from civicbot.skills import (BUILTIN_SKILLS, Catalog, FetchBlocked, FetchError, SafeFetcher, SkillInputError,
                             SkillRouter, SkillRunner, SpecError, from_openapi, usage_check, validate_spec)
from civicbot.skills.template import get_path, render, sanitize, MissingValue

CAT = Catalog()


def spec(name):
    return copy.deepcopy(CAT.get(name))


def bad(mutate, name="open-meteo-weather"):
    s = copy.deepcopy(json.loads((CAT.dir / CAT.entry(name)["file"]).read_text()))
    mutate(s)
    with pytest.raises(SpecError) as e:
        validate_spec(s)
    return " | ".join(e.value.problems)


class FakeNet:
    """raw() replacement: records calls, answers by host."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def __call__(self, method, url, headers, body, timeout, max_bytes):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body,
                           "timeout": timeout, "max_bytes": max_bytes})
        host = url.split("/")[2]
        a = self.answers.get(host, (200, {"ok": True}))
        status, payload = a if isinstance(a, tuple) else (200, a)
        data = payload if isinstance(payload, bytes) else json.dumps(payload(url) if callable(payload) else payload).encode()
        return status, {}, data


def fetcher(net, ips=("93.184.216.34",)):
    return SafeFetcher(resolve=lambda h: list(ips), raw=net, min_host_interval=0, allow_nets=[])


WEATHER = {"current": {"time": "2026-10-10T18:15", "temperature_2m": 66.9, "apparent_temperature": 64.4,
                       "weather_code": 3, "wind_speed_10m": 7.5}}


def iso(mins):
    import datetime as dt
    return dt.datetime.fromtimestamp(time.time() + mins * 60, dt.timezone.utc).isoformat()


# --- spec validation ---------------------------------------------------------------------------
def test_catalog_specs_valid_and_hash_pinned():
    assert set(CAT.names()) == {"open-meteo-weather", "mbta-next-trains", "chicago-311-nearby",
                                "carris-metropolitana-arrivals"}
    for n in CAT.names():
        s = CAT.get(n)
        assert s["kind"] == "read" and s["request"]["method"] == "GET"
        assert CAT.entry(n)["review"]["status"] == "reviewed"


def test_catalog_rejects_tampered_spec(tmp_path):
    d = tmp_path / "cat"
    shutil.copytree(CAT.dir, d)
    f = d / "skills" / "open-meteo-weather.json"
    s = json.loads(f.read_text())
    s["allowed_domains"].append("evil.example")
    f.write_text(json.dumps(s))
    with pytest.raises(SpecError, match="sha256"):
        Catalog(str(d)).get("open-meteo-weather")


@pytest.mark.parametrize("mutate,expect", [
    (lambda s: s.update(extra=1), "unknown field 'extra'"),
    (lambda s: s.pop("triggers"), "missing 'triggers'"),
    (lambda s: s["request"].update(base_url="http://api.open-meteo.com"), "does not match"),
    (lambda s: s["request"].update(method="POST"), "kind 'read' skills must use GET"),
    (lambda s: s.update(allowed_domains=["example.com"]), "not in allowed_domains"),
    (lambda s: s["request"].update(headers={"Authorization": "x"}), "looks like a credential"),
    (lambda s: s["request"]["params"].update(api_key="abc"), "looks like a credential"),
    (lambda s: s["request"]["params"].update(x="Bearer abcdefghijklmnop"), "embedded secret"),
    (lambda s: s["request"]["params"].update(x="sk-" + "a" * 30), "embedded secret"),
    (lambda s: s["request"].update(path="/v1/{text}"), "may not be used in the path"),
    (lambda s: s["request"]["params"].update(q="name = '{text}'"), "must be the whole value"),
    (lambda s: s["request"]["params"].update(q="{secret.thing}"), "unknown variable"),
    (lambda s: s["response"]["replies"].append("see https://x.example/a for more"), "links are not allowed"),
    (lambda s: s["response"]["replies"].append("cc @someone about {temp}"), "@mentions are not allowed"),
    (lambda s: s["response"]["replies"].append("value {nope}"), "is not extracted"),
    (lambda s: s.update(handler="builtin:report"), "reserved"),
    (lambda s: s.update(auth={"type": "api_key", "secret_ref": "my_key"}), "needs 'in', 'name'"),
    (lambda s: s.update(limits={"timeout_s": 60}), "above 15"),
])
def test_spec_rules(mutate, expect):
    assert expect in bad(mutate)


def test_spec_input_patterns_anchored():
    def m(s):
        s["inputs"]["stop"]["pattern"] = "[0-9]{6}"
    assert "anchored" in bad(m, "carris-metropolitana-arrivals")


# --- templates ---------------------------------------------------------------------------------
def test_template_paths_filters_and_safety():
    d = {"a": {"b": [None, {"c": 5}]}, "x": None, "y": "Y"}
    assert get_path(d, "a.b.1.c") == 5 and get_path(d, "x||y") == "Y" and get_path(d, "$") is d
    assert render("{t|round}F {c|wmo}", {"t": 66.6, "c": 3}.get) == "67F overcast"
    assert sanitize("hi @bob see https://evil.example/x\nok") == "hi bob see ok"
    with pytest.raises(MissingValue):
        render("{a.__class__}", lambda n: get_path({"a": 1}, n))


# --- SafeFetcher / SSRF ------------------------------------------------------------------------
@pytest.mark.parametrize("url,ips,msg", [
    ("http://api.open-meteo.com/x", ["93.184.216.34"], "only https"),
    ("https://api.open-meteo.com:8443/x", ["93.184.216.34"], "port 443"),
    ("https://user:pw@api.open-meteo.com/x", ["93.184.216.34"], "credentials"),
    ("https://evil.example/x", ["93.184.216.34"], "not on this skill's allowed_domains"),
    ("https://api.open-meteo.com/x", ["10.0.0.5"], "SSRF"),
    ("https://api.open-meteo.com/x", ["127.0.0.1"], "SSRF"),
    ("https://api.open-meteo.com/x", ["169.254.169.254"], "SSRF"),
    ("https://api.open-meteo.com/x", ["100.64.1.1"], "SSRF"),
    ("https://api.open-meteo.com/x", ["::1"], "SSRF"),
    ("https://api.open-meteo.com/x", ["::ffff:127.0.0.1"], "SSRF"),
    ("https://api.open-meteo.com/x", ["93.184.216.34", "192.168.1.1"], "SSRF"),
    ("https://localhost/x", ["127.0.0.1"], "not allowed"),
])
def test_fetch_blocks(url, ips, msg):
    net = FakeNet()
    f = fetcher(net, ips)
    with pytest.raises(FetchBlocked, match=msg):
        f.request("GET", url, allowed_domains=["api.open-meteo.com", "localhost"])
    assert net.calls == []


def test_fetch_ip_literal_and_redirect_and_size():
    net = FakeNet({"api.open-meteo.com": (302, {"moved": 1})})
    with pytest.raises(FetchBlocked, match="redirect"):
        fetcher(net).request("GET", "https://api.open-meteo.com/x", allowed_domains=["api.open-meteo.com"])
    with pytest.raises(FetchBlocked):
        fetcher(FakeNet()).request("GET", "https://10.1.2.3/x", allowed_domains=["10.1.2.3"])
    big = FakeNet({"api.open-meteo.com": (200, b"[" + b"1," * 5000 + b"1]")})
    with pytest.raises(FetchError, match="larger"):
        fetcher(big).request("GET", "https://api.open-meteo.com/x", allowed_domains=["api.open-meteo.com"], max_bytes=2048)
    html = FakeNet({"api.open-meteo.com": (200, b"<html>")})
    with pytest.raises(FetchError, match="not JSON"):
        fetcher(html).request("GET", "https://api.open-meteo.com/x", allowed_domains=["api.open-meteo.com"])
    ok = FakeNet()
    r = fetcher(ok).request("GET", "https://api.open-meteo.com/x", allowed_domains=["open-meteo.com"],
                            timeout=99, max_bytes=10**9)
    assert r.data == {"ok": True} and ok.calls[0]["timeout"] == 15 and ok.calls[0]["max_bytes"] == 1048576


def test_fetch_sandbox_allow_nets_env(monkeypatch):
    monkeypatch.setenv("CIVICBOT_SSRF_ALLOW_NETS", "198.18.0.0/15")
    f = SafeFetcher(resolve=lambda h: ["198.18.0.1"], raw=FakeNet(), min_host_interval=0)
    assert f.request("GET", "https://api.open-meteo.com/x", allowed_domains=["api.open-meteo.com"]).data
    with pytest.raises(FetchBlocked):  # still blocks real private ranges
        SafeFetcher(resolve=lambda h: ["10.0.0.1"], raw=FakeNet(), min_host_interval=0).check_url(
            "https://api.open-meteo.com/", ["api.open-meteo.com"])


# --- runner --------------------------------------------------------------------------------------
class Geo:
    def __init__(self, table):
        self.table, self.calls = table, []

    def geocode(self, q):
        from civicbot.geocode import GeocodeResult
        self.calls.append(q)
        for k, (lat, lng) in self.table.items():
            if k in q.lower():
                return GeocodeResult(lat, lng, q, "fake")
        return None


def test_runner_weather_uses_location_then_home_city():
    net = FakeNet({"api.open-meteo.com": WEATHER})
    r = SkillRunner(fetcher(net), Geo({"new haven": (41.3083, -72.9259), "bloomington": (39.1653, -86.5264)}))
    s = spec("open-meteo-weather")
    ctx = r.context(s, "weather in New Haven, CT", home_city="Bloomington, IN")
    out = r.run_read(s, ctx, [])
    assert "latitude=41.3083" in net.calls[0]["url"] and out[0].startswith("New Haven, CT: 67°F")
    ctx = r.context(s, "weather", home_city="Bloomington, IN")
    assert ctx.location_text == "Bloomington, IN" and ctx.lat == 39.1653
    with pytest.raises(SkillInputError, match="Where"):
        SkillRunner(fetcher(net), Geo({})).context(s, "weather")


def test_runner_list_filters_past_and_sorts():
    data = {"data": [
        {"attributes": {"arrival_time": None, "departure_time": None}, "relationships": {"route": {"data": {"id": "X"}}}},
        {"attributes": {"departure_time": iso(-5)}, "relationships": {"route": {"data": {"id": "Old"}}}},
        {"attributes": {"departure_time": iso(9.5)}, "relationships": {"route": {"data": {"id": "Red"}}}},
        {"attributes": {"departure_time": iso(2.5)}, "relationships": {"route": {"data": {"id": "Green-E"}}}}]}
    net = FakeNet({"api-v3.mbta.com": data})
    r = SkillRunner(fetcher(net))
    s = spec("mbta-next-trains")
    out = r.run_read(s, r.context(s, "next train at place-sstat"), [])
    assert "filter%5Bstop%5D=place-sstat" in net.calls[0]["url"]
    assert "Green-E 2 min, Red 9 min" in out[0] and "Old" not in out[0] and "X " not in out[0]
    net.answers["api-v3.mbta.com"] = {"data": []}
    assert "No upcoming" in r.run_read(s, r.context(s, "next train"), [])[0] or "nothing" in \
        r.run_read(s, r.context(s, "next train"), [])[0]


def test_runner_path_input_validated():
    r = SkillRunner(fetcher(FakeNet()))
    s = spec("carris-metropolitana-arrivals")
    assert r.context(s, "carris 020429").inputs["stop"] == "020429"
    assert r.context(s, "carris").inputs["stop"] == "020429"  # default
    s["inputs"]["stop"]["regex"] = r"stop (\S+)"
    with pytest.raises(SkillInputError, match="isn't a valid"):
        r.context(s, "carris stop ../../admin")


def test_runner_secrets_applied_but_never_logged():
    net = FakeNet({"data.cityofchicago.org": []})
    secrets = {"socrata_app_token": "TOPSECRET-123"}
    r = SkillRunner(fetcher(net), Geo({"lasalle": (41.8837, -87.6319)}), secrets.get)
    s = spec("chicago-311-nearby")
    log = []
    out = r.run_read(s, r.context(s, "311 requests near 121 N LaSalle St, Chicago, IL"), log)
    assert net.calls[0]["headers"]["X-App-Token"] == "TOPSECRET-123"
    assert "TOPSECRET" not in " ".join(log) and "No Chicago 311" in out[0]
    assert "within_circle%28location%2C+41.8837%2C+-87.6319%2C+400%29" in net.calls[0]["url"]
    s["auth"]["required"] = True
    with pytest.raises(SkillInputError, match="secret"):
        SkillRunner(fetcher(net), Geo({"lasalle": (1, 1)})).run_read(
            s, SkillRunner(fetcher(net), Geo({"lasalle": (1, 1)})).context(s, "311 near 121 N LaSalle"), [])


def test_usage_limits():
    s = {"name": "x", "limits": {"min_interval_s": 5, "max_calls_per_day": 2}}
    u = {}
    assert usage_check(u, s, now=1000) is None
    assert "just used" in usage_check(u, s, now=1002)
    assert usage_check(u, s, now=1010) is None
    assert "daily limit" in usage_check(u, s, now=1020)
    assert usage_check(u, s, now=1000 + 86400) is None


# --- routing -----------------------------------------------------------------------------------
def test_router_prefers_user_skill_but_keeps_builtins():
    skills = list(BUILTIN_SKILLS.values()) + [spec("open-meteo-weather"), spec("mbta-next-trains")]
    r = SkillRouter()
    assert r.route("what's the weather", "report", skills).skill["name"] == "open-meteo-weather"
    assert r.route("pothole at 5th and Main", "report", skills).skill["name"] == "city-311-report"
    assert r.route("status #123", "status", skills).skill["name"] == "city-311-status"
    assert r.route("next train at place-pktrm", "transit", skills).skill["name"] == "mbta-next-trains"
    assert r.route("next bus", "transit", list(BUILTIN_SKILLS.values()), transit_available=True).skill["name"] == "gtfs-transit"
    assert r.route("hello there", "help", skills) is None


# --- robot integration -------------------------------------------------------------------------
def make_robot(fake, net=None, ips=("93.184.216.34",), **kw):
    p = RobotProfile(robot_handle="joshs_robot", owner_handle="joshua", home_city="Bloomington, IN",
                     allowlist=["friend"], **kw)
    p.grant_consent()
    changes = []
    net = net or FakeNet({"api.open-meteo.com": WEATHER})
    r = Robot(p, resolver=JurisdictionResolver(transport=fake), fetcher=fetcher(net, ips),
              on_profile_change=changes.append)
    r.runner.geocoder = Geo({"bloomington": (39.1653, -86.5264), "new haven": (41.3, -72.9)})
    return r, StubXAdapter(robot="joshs_robot"), net, changes


def test_owner_teaches_robot_then_uses_skill(fake):
    r, x, net, changes = make_robot(fake)
    x.add_mention("joshua", "@joshs_robot learn open-meteo-weather")
    x.add_mention("joshua", "@joshs_robot what's the weather?")
    a1, a2 = r.run_once(x)
    assert "open-meteo-weather" in r.profile.skills and changes and "open-meteo-weather" in a1.reply
    assert a2.skill == "open-meteo-weather" and "67°F" in a2.reply and len(a2.reply) <= 280
    assert len(x.outbox) == 2  # one reply per mention
    assert r.run_once(x) == []


def test_non_owner_cannot_add_skills(fake):
    r, x, net, _ = make_robot(fake)
    x.add_mention("friend", "@joshs_robot learn open-meteo-weather")       # allowlisted user: refused
    x.add_mention("stranger", "@joshs_robot learn open-meteo-weather")     # stranger: ignored entirely
    x.add_mention("friend", "@joshs_robot add api https://api.open-meteo.com/spec.json")
    acts = r.run_once(x)
    assert r.profile.skills == {} and net.calls == []
    assert "Only joshua" in acts[0].reply and acts[1].reply is None and "Only joshua" in acts[2].reply


def test_learn_from_url_validated_and_ssrf_guarded(fake):
    good = json.loads((CAT.dir / CAT.entry("open-meteo-weather")["file"]).read_text())
    evil = dict(good, name="evil-skill", allowed_domains=["api.open-meteo.com"])
    evil["request"] = dict(good["request"], headers={"Authorization": "Bearer abcdefghijklmnopqrstuvwxyz"})
    net = FakeNet({"specs.example.org": lambda url: good if "good" in url else evil})
    r, x, _, _ = make_robot(fake, net=net)
    x.add_mention("joshua", "@joshs_robot learn https://t.co/abc123", urls=["https://specs.example.org/good.json"])
    x.add_mention("joshua", "@joshs_robot learn https://specs.example.org/evil.json")
    a1, a2 = r.run_once(x)
    assert "open-meteo-weather" in r.profile.skills and r.profile.skills["open-meteo-weather"]["_source"].endswith("good.json")
    assert "evil-skill" not in r.profile.skills and "Can't learn" in a2.reply
    r2, x2, net2, _ = make_robot(fake, ips=("10.0.0.7",))
    x2.add_mention("joshua", "@joshs_robot learn https://intranet.example.org/spec.json")
    (a,) = r2.run_once(x2)
    assert "SSRF" in " ".join(a.log) and net2.calls == [] and r2.profile.skills == {}


def test_skill_list_forget_and_builtin_toggle(fake):
    r, x, _, _ = make_robot(fake)
    for t in ["learn mbta-next-trains", "skills", "forget mbta-next-trains", "forget city-311-report",
              "pothole at 401 N Morton St", "learn city-311-report", "learn nonexistent-skill"]:
        x.add_mention("joshua", f"@joshs_robot {t}")
    acts = r.run_once(x)
    assert "mbta-next-trains" in acts[1].reply and r.profile.skills == {}
    assert "Turned off" in acts[3].reply and acts[4].skill is None  # report built-in off -> help
    assert "is on" in acts[5].reply and r.profile.disabled_builtins == []
    assert "No catalog skill" in acts[6].reply


WRITE_SPEC = {
    "spec_version": 1, "name": "demo-feedback", "description": "Send feedback to a demo API (test only)",
    "kind": "write", "triggers": {"keywords": ["feedback"]},
    "request": {"base_url": "https://api.demo.example", "path": "/feedback", "method": "POST",
                "body": {"message": "{text}", "near": "{location.text}"}},
    "auth": {"type": "bearer", "secret_ref": "demo_token"},
    "allowed_domains": ["api.demo.example"], "location": "optional",
    "response": {"extract": {"id": "id"}, "replies": ["Sent feedback #{id}.", "Feedback filed as #{id}."]},
    "limits": {"min_interval_s": 1},
}


def test_write_skill_dry_run_until_enabled_then_needs_yes(fake):
    net = FakeNet({"api.demo.example": {"id": "F-9"}})
    r, x, _, _ = make_robot(fake, net=net)
    r.profile.skills["demo-feedback"] = validate_spec(copy.deepcopy(WRITE_SPEC))
    r.secrets.put("joshs_robot", "demo_token", "TOKEN-XYZ")
    x.add_mention("joshua", "@joshs_robot feedback the bench is great")
    (a,) = r.run_once(x)
    assert "Dry run" in a.reply and net.calls == [] and a.prepared["method"] == "POST"
    for t in ["enable skill demo-feedback", "feedback the bench is great", "yes"]:
        x.add_mention("joshua", f"@joshs_robot {t}")
    acts = r.run_once(x)
    assert "send real requests" in acts[0].reply and "Reply YES" in acts[1].reply
    assert len(net.calls) == 1 and net.calls[0]["method"] == "POST"
    assert net.calls[0]["headers"]["Authorization"] == "Bearer TOKEN-XYZ"
    assert json.loads(net.calls[0]["body"])["message"].startswith("feedback the bench")
    assert "F-9" in acts[2].reply and "TOKEN" not in " ".join(acts[2].log)


def test_secrets_are_per_robot(fake):
    store = InMemorySecretStore()
    store.put("joshs_robot", "socrata_app_token", "JOSH-KEY")
    net = FakeNet({"data.cityofchicago.org": []})
    p = RobotProfile(robot_handle="anas_robot", owner_handle="ana", home_city="Chicago, IL")
    p.grant_consent()
    r = Robot(p, resolver=JurisdictionResolver(transport=fake), fetcher=fetcher(net), secrets=store)
    r.runner.geocoder = Geo({"chicago": (41.88, -87.63)})
    r.profile.skills["chicago-311-nearby"] = spec("chicago-311-nearby")
    x = StubXAdapter(robot="anas_robot")
    x.add_mention("ana", "@anas_robot recent 311 requests near me")
    r.run_once(x)
    assert "X-App-Token" not in net.calls[0]["headers"]


def test_encrypted_secret_store(tmp_path):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    path = tmp_path / "secrets.enc"
    s = EncryptedFileSecretStore(str(path), key=key)
    s.put("joshs_robot", "socrata_app_token", "VERY-SECRET-VALUE")
    assert b"VERY-SECRET" not in path.read_bytes() and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert EncryptedFileSecretStore(str(path), key=key).get("joshs_robot", "socrata_app_token") == "VERY-SECRET-VALUE"


def test_fleet_persists_installed_skills(fake, tmp_path):
    store = ProfileStore(str(tmp_path / "profiles.json"))
    p = RobotProfile(robot_handle="joshs_robot", owner_handle="joshua", home_city="Bloomington, IN")
    p.grant_consent()
    store.put(p)
    x = StubXAdapter(robot="joshs_robot")
    fleet = Fleet(store, lambda p: x, resolver=JurisdictionResolver(transport=fake), min_poll_interval=0,
                  fetcher=fetcher(FakeNet()))
    x.add_mention("joshua", "@joshs_robot learn chicago-311-nearby")
    fleet.run_once()
    saved = json.loads((tmp_path / "profiles.json").read_text())
    assert "chicago-311-nearby" in saved["joshs_robot"]["skills"]


# --- OpenAPI import ----------------------------------------------------------------------------
OPENAPI = {
    "openapi": "3.0.0", "servers": [{"url": "https://api.parks.example.gov/v1"}],
    "components": {"securitySchemes": {"ApiKey": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}}},
    "paths": {"/parks/{parkId}/events": {"get": {
        "operationId": "listParkEvents", "summary": "List upcoming park events",
        "parameters": [{"name": "parkId", "in": "path", "required": True, "schema": {"type": "string"}},
                       {"name": "lat", "in": "query"}, {"name": "lon", "in": "query"},
                       {"name": "q", "in": "query"}, {"name": "limit", "in": "query"}]}},
        "/feedback": {"post": {"operationId": "sendFeedback", "summary": "Send feedback"}}}}


def test_openapi_import():
    s = from_openapi(OPENAPI, "listParkEvents", keywords=["park", "events"])
    assert s["request"]["base_url"] == "https://api.parks.example.gov"
    assert s["request"]["path"] == "/v1/parks/{inputs.parkid}/events"
    assert s["request"]["params"] == {"lat": "{location.lat}", "lon": "{location.lng}", "q": "{query}"}
    assert s["auth"] == {"type": "api_key", "in": "header", "name": "X-Api-Key", "secret_ref": "apikey", "required": True}
    assert s["kind"] == "read" and "REVIEW" in s["author"]
    assert from_openapi(OPENAPI, "POST /feedback")["kind"] == "write"
    with pytest.raises(KeyError):
        from_openapi(OPENAPI, "nope")


# --- CLI ---------------------------------------------------------------------------------------
def test_cli_skill_commands(tmp_path, monkeypatch, capsys):
    from civicbot.__main__ import main
    monkeypatch.setenv("CIVICBOT_HOME", str(tmp_path))
    assert main(["skill", "catalog"]) == 0
    assert main(["skill", "add", "mbta-next-trains", "--robot", "joshs_robot", "--owner", "joshua"]) == 0
    assert main(["skill", "list", "--robot", "joshs_robot"]) == 0
    assert main(["skill", "test", "carris-metropolitana-arrivals", "--text", "carris 020113"]) == 0
    assert main(["skill", "remove", "mbta-next-trains", "--robot", "joshs_robot"]) == 0
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps(dict(WRITE_SPEC, request=dict(WRITE_SPEC["request"], headers={"Cookie": "a=b"}))))
    assert main(["skill", "validate", str(bad_file)]) == 2
    out = capsys.readouterr().out
    assert "mbta-next-trains" in out and "/v2/arrivals/by_stop/020113" in out and "credential" in out
    openapi = tmp_path / "openapi.json"
    openapi.write_text(json.dumps(OPENAPI))
    assert main(["skill", "import-openapi", str(openapi), "--operation", "listParkEvents",
                 "-o", str(tmp_path / "parks.json")]) == 0
    assert main(["skill", "validate", str(tmp_path / "parks.json")]) == 0


def test_cli_skills_demo_offline(capsys):
    from civicbot.__main__ import main
    assert main(["simulate", "--demo", "skills", "--offline"]) == 0
    out = capsys.readouterr().out
    assert "installed open-meteo-weather from catalog" in out and "skill=mbta-next-trains" in out
    assert "@randomuser is not @joshs_robot's owner" in out and "not allowed" in out
    assert "skill=city-311-report" in out and "Forgot skill" in out
