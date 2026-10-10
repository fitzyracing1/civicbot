import pytest

from civicbot.resolver import JurisdictionResolver
from civicbot.robot import (Fleet, FleetDuplicateGuard, Phraser, ProfileStore, Robot, RobotProfile,
                            StubXAdapter)


def profile(robot, owner, city="Bloomington, IN", consent=True, **kw):
    p = RobotProfile(robot_handle=robot, owner_handle=owner, home_city=city, **kw)
    if consent:
        p.grant_consent()
    return p


def make_fleet(fake, *profiles, **kw):
    store = ProfileStore()
    for p in profiles:
        store.put(p)
    adapters = {}
    fleet = Fleet(store, lambda p: adapters.setdefault(p.robot_id, StubXAdapter(robot=p.robot_id)),
                  resolver=JurisdictionResolver(transport=fake), min_poll_interval=0, **kw)
    return fleet, adapters


def test_robot_must_be_separate_from_owner():
    with pytest.raises(ValueError):
        RobotProfile(robot_handle="joshua", owner_handle="@joshua")


def test_each_robot_replies_from_its_own_account(fake):
    fleet, ad = make_fleet(fake, profile("joshs_robot", "joshua"), profile("anas_robot", "ana", "New Haven, CT"))
    fleet.adapter("joshs_robot").add_mention("joshua", "@joshs_robot streetlight out at 401 N Morton St")
    fleet.adapter("anas_robot").add_mention("ana", "@anas_robot pothole at Chapel St & College St")
    fake.add(r"geocoding\.geo\.census\.gov", lambda u, p: (
        {"result": {"addressMatches": [{"coordinates": {"x": -86.536198, "y": 39.16957}, "matchedAddress": "M"}]}}
        if "Bloomington" in p.get("address", "") else {"result": {"addressMatches": []}}))
    fake.add(r"nominatim", lambda u, p: [{"lat": "41.3064", "lon": "-72.9289", "display_name": "Chapel St"}])
    acts = {a.robot: a for a in fleet.run_once()}
    assert acts["joshs_robot"].resolution.endpoint.id == "bloomington-in"
    assert acts["anas_robot"].resolution.endpoint.id == "seeclickfix"
    assert [p["from"] for p in ad["joshs_robot"].outbox] == ["joshs_robot"]
    assert [p["from"] for p in ad["anas_robot"].outbox] == ["anas_robot"]
    assert "Street Lights" in ad["joshs_robot"].outbox[0]["text"]
    assert "Potholes" in ad["anas_robot"].outbox[0]["text"] and "New Haven" in ad["anas_robot"].outbox[0]["text"]
    assert fake.posts == []  # dry-run: nothing filed


def test_owner_only_and_allowlist(fake):
    fleet, ad = make_fleet(fake, profile("joshs_robot", "joshua", allowlist=["@friend"]))
    x = fleet.adapter("joshs_robot")
    x.add_mention("stranger", "@joshs_robot pothole at 401 N Morton St")
    x.add_mention("ana", "@joshs_robot help")                 # another robot's owner: still a stranger here
    x.add_mention("friend", "@joshs_robot help")
    acts = fleet.run_once()
    assert [bool(a.reply) for a in acts] == [False, False, True]
    assert len(ad["joshs_robot"].outbox) == 1


def test_owner_cannot_drive_someone_elses_robot(fake):
    fleet, ad = make_fleet(fake, profile("joshs_robot", "joshua"), profile("anas_robot", "ana"))
    fleet.adapter("anas_robot").add_mention("joshua", "@anas_robot help")
    fleet.run_once()
    assert ad.get("anas_robot").outbox == []


def test_ignores_posts_that_dont_summon_robot(fake):
    fleet, ad = make_fleet(fake, profile("joshs_robot", "joshua"))
    fleet.adapter("joshs_robot").add_mention("joshua", "help", robot="joshs_robot")  # e.g. a quote without @
    fleet.run_once()
    assert ad["joshs_robot"].outbox == []


def test_dm_channel_owner_only(fake):
    fleet, ad = make_fleet(fake, profile("joshs_robot", "joshua"))
    x = fleet.adapter("joshs_robot")
    x.add_mention("joshua", "help", channel="dm")
    x.add_mention("stranger", "help", channel="dm")
    acts = fleet.run_once()
    assert [bool(a.reply) for a in acts] == [True, False]


def test_no_consent_no_action(fake):
    fleet, ad = make_fleet(fake, profile("joshs_robot", "joshua", consent=False))
    fleet.adapter("joshs_robot").add_mention("joshua", "@joshs_robot help")
    assert fleet.run_once() == [] and ad["joshs_robot"].outbox == []
    r = Robot(profile("x_robot", "joshua", consent=False), resolver=JurisdictionResolver(transport=fake))
    s = StubXAdapter(robot="x_robot")
    s.add_mention("joshua", "@x_robot help")
    acts = r.run_once(s)
    assert "consent" in acts[0].log[0] and s.outbox == []


def test_replies_vary_across_robots():
    guard = FleetDuplicateGuard()
    texts = set()
    for i in range(12):
        ph = Phraser(f"robot{i}", guard)
        texts.add(ph.report(seed="m1", service="Potholes", city="Bloomington, IN", location="401 N Morton St",
                            dry_run=True))
    assert len(texts) == 12  # never identical, even for the exact same request
    assert all(len(t) <= 280 and t.endswith("[bot]") and not t.startswith("@") for t in texts)


def test_fixed_texts_never_identical_across_robots():
    guard = FleetDuplicateGuard()
    a, b = Phraser("a_robot", guard), Phraser("b_robot", guard)
    ta, tb = a.text("Opted out."), b.text("Opted out.")
    assert ta != tb and "b_robot" in tb and a.text("Opted out.") == ta
    r1 = a.report(seed="1", service="S", city="C", location="L", dry_run=True)
    r2 = b.report(seed="1", service="S", city="C", location="L", dry_run=True)
    assert r1 != r2


def test_status_followups_need_owner_permission(fake):
    p = profile("joshs_robot", "joshua", send_enabled=True)
    r = Robot(p, resolver=JurisdictionResolver(transport=fake), api_keys={"bloomington-in": "KEY"})
    x = StubXAdapter(robot="joshs_robot")
    x.add_mention("joshua", "@joshs_robot pothole at 401 N Morton St")
    x.add_mention("joshua", "@joshs_robot yes")
    r.run_once(x)
    assert len(fake.posts) == 1  # fake transport only
    n = len(x.outbox)
    fake.add(r"requests/999\.json", [{"service_request_id": "999", "status": "closed"}])
    assert r.poll_status_updates(x) and len(x.outbox) == n      # no permission -> not posted
    x.add_mention("joshua", "@joshs_robot updates on")
    r.run_once(x)
    assert p.status_updates and "ON" in x.outbox[-1]["text"]
    fake.add(r"requests/999\.json", [{"service_request_id": "999", "status": "open", "status_notes": "reopened"}])
    n = len(x.outbox)
    r.poll_status_updates(x)
    assert len(x.outbox) == n + 1 and "OPEN" in x.outbox[-1]["text"]


def test_fleet_isolates_failures(fake):
    store = ProfileStore()
    store.put(profile("bad_robot", "a"))
    store.put(profile("good_robot", "b"))

    class Broken(StubXAdapter):
        def poll_mentions(self, since_id=None):
            raise RuntimeError("token revoked")
    good = StubXAdapter(robot="good_robot")
    good.add_mention("b", "@good_robot help")
    fleet = Fleet(store, lambda p: Broken(robot=p.robot_id) if p.robot_id == "bad_robot" else good,
                  resolver=JurisdictionResolver(transport=fake), min_poll_interval=0)
    acts = fleet.run_once()
    assert any("poll failed" in a.log[0] for a in acts if a.intent is None) and len(good.outbox) == 1


def test_fleet_poll_interval(fake):
    fleet, ad = make_fleet(fake, profile("joshs_robot", "joshua"))
    fleet.min_poll_interval = 60
    fleet.adapter("joshs_robot").add_mention("joshua", "@joshs_robot help")
    assert len(fleet.run_once(now=1000)) == 1
    fleet.adapter("joshs_robot").add_mention("joshua", "@joshs_robot help")
    assert fleet.run_once(now=1030) == [] and len(fleet.run_once(now=1061)) == 1


def test_profile_store_persists_without_secrets(tmp_path):
    path = tmp_path / "profiles.json"
    s = ProfileStore(str(path))
    s.put(profile("joshs_robot", "joshua"))
    assert ProfileStore(str(path)).get("@JOSHS_ROBOT").owner_handle == "joshua"
    assert "token" not in path.read_text().lower()


def test_cli_connect_no_network(capsys, monkeypatch, tmp_path):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("network!"))
    from civicbot.__main__ import main
    pend = tmp_path / "pending.json"
    assert main(["connect", "--robot", "@joshs_robot", "--owner", "joshua", "--client-id", "CID",
                 "--redirect-uri", "http://127.0.0.1:8765/cb", "--pending-file", str(pend)]) == 0
    out = capsys.readouterr().out
    assert "https://x.com/i/oauth2/authorize?" in out and "code_challenge_method=S256" in out
    assert "offline.access" in out and "LOG IN" not in out and "ROBOT ACCOUNT" in out
    import json, os, stat
    saved = json.loads(pend.read_text())
    assert saved["code_verifier"] not in out and stat.S_IMODE(os.stat(pend).st_mode) == 0o600


def test_cli_two_robot_demo(capsys):
    from civicbot.__main__ import main
    assert main(["simulate", "--demo", "--offline"]) == 0
    out = capsys.readouterr().out
    assert "REPLY from @joshs_robot" in out and "REPLY from @anas_robot" in out
    assert "bloomington-in" in out and "seeclickfix" in out
    assert "@randomuser is not @joshs_robot's owner" in out
    assert "nothing was sent to X" in out
