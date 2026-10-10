import pytest

from civicbot import JurisdictionResolver
from civicbot.x import XApiV2Adapter
from civicbot.robot import (IntentParser, Robot, ServiceMatcher, StubXAdapter,
                            compose_report_reply, fit_280)
from conftest import FakeTransport


@pytest.mark.parametrize("text,kind,issue,loc", [
    ("@joshua_robot streetlight out at 5th & Oak", "report", "streetlight out", "5th & Oak"),
    ("@joshua_robot there's a pothole on Kirkwood Ave", "report", "pothole", "Kirkwood Ave"),
    ("@joshua_robot graffiti", "report", "graffiti", ""),
    ("@joshua_robot status #12345", "status", "", ""),
    ("@joshua_robot when is the next bus?", "transit", "", ""),
    ("@joshua_robot bus shelter broken at Main St", "report", "bus shelter broken", "Main St"),
    ("@joshua_robot STOP", "stop", "", ""),
    ("@joshua_robot yes", "confirm", "", ""),
    ("@joshua_robot", "help", "", ""),
])
def test_intent_rules(text, kind, issue, loc):
    i = IntentParser().parse(text)
    assert i.kind == kind
    if kind == "report":
        assert i.issue == issue and i.location == loc
    if kind == "status":
        assert i.request_id == "12345"


def test_intent_coordinates_and_llm_hook():
    i = IntentParser().parse("@r tree down (39.1653, -86.5264)")
    assert i.kind == "report" and i.lat == 39.1653 and i.lng == -86.5264 and i.issue == "tree down"
    from civicbot.robot import Intent
    hooked = IntentParser(llm_hook=lambda t: Intent("transit", t)).parse("@r at")
    assert hooked.kind == "transit"


@pytest.mark.parametrize("issue,fixture,expected", [
    ("streetlight out", "bloomington_services", "Street Lights"),
    ("streetlight out", "scf_services", "Street Lamp"),
    ("pothole", "bloomington_services", "Potholes, Other Street Repair"),
    ("pothole", "scf_services", "Potholes"),
    ("broken traffic light", "bloomington_services", "Traffic Signals"),
    ("dead deer", "scf_services", "Deceased Animals"),
    ("abandoned car", "boston_services", "Abandoned Vehicle"),
    ("rats", "boston_services", "Rodent Sighting"),
    ("streetlight out", "boston_services", None),
    ("my neighbor is loud", "bloomington_services", None),
])
def test_matcher(issue, fixture, expected, request):
    m = ServiceMatcher().match(issue, request.getfixturevalue(fixture))
    assert (m.service_name if m else None) == expected


def test_replies_fit_280():
    assert len(fit_280("x" * 500)) == 280
    r = compose_report_reply(user="joshua", service_name="S" * 200, city="C" * 100, location="L" * 100, dry_run=True)
    assert len(r) <= 280 and not r.startswith("@") and r.endswith("[bot]")


def robot(fake, **kw):
    return Robot(owner="joshua", resolver=JurisdictionResolver(transport=fake), **kw)


def test_end_to_end_report_dry_run(fake):
    r, x = robot(fake), StubXAdapter()
    x.add_mention("joshua", "@joshua_robot streetlight out at 401 N Morton St, Bloomington, IN")
    [act] = r.run_once(x)
    assert act.resolution.endpoint.id == "bloomington-in"
    assert act.service["service_code"] == "69"
    assert act.prepared["dry_run"] and act.prepared["form"]["service_code"] == "69"
    assert fake.posts == []
    assert len(x.outbox) == 1 and "Street Lights" in x.outbox[0]["text"] and len(x.outbox[0]["text"]) <= 280


def test_seeclickfix_autofills_required_location(fake):
    fake.add(r"nominatim", lambda u, p: [{"lat": "41.31", "lon": "-72.94", "display_name": "Chapel Street"}]
             if p["q"].startswith("Chapel Street") else [])
    r, x = robot(fake, home_city="New Haven, CT"), StubXAdapter()
    x.add_mention("joshua", "@joshua_robot pothole at Chapel St & College St")
    [act] = r.run_once(x)
    form = act.prepared["form"]
    assert act.resolution.endpoint.id == "seeclickfix"
    assert form["attribute[189]"] == "Chapel St & College St"
    assert form["address_string"] == "Chapel St & College St, New Haven, CT" and "lat" in form


def test_policy_guards(fake):
    r, x = robot(fake), StubXAdapter()
    stranger = x.add_mention("randomuser", "@joshua_robot pothole at 401 N Morton St, Bloomington, IN")
    r.run_once(x)
    assert x.outbox == []  # never replies to non-owners
    m = x.add_mention("joshua", "@joshua_robot STOP")
    r.run_once(x)
    assert "Opted out" in x.outbox[-1]["text"]
    x.add_mention("joshua", "@joshua_robot pothole at 401 N Morton St, Bloomington, IN")
    r.run_once(x)
    assert len(x.outbox) == 1  # opted out -> silent
    assert r.handle(m).reply is None  # duplicate mention -> no second reply
    assert stranger.id in r.state.handled


def test_confirm_disabled_by_default(fake):
    r, x = robot(fake), StubXAdapter()
    x.add_mention("joshua", "@joshua_robot pothole at 401 N Morton St, Bloomington, IN")
    x.add_mention("joshua", "@joshua_robot YES")
    r.run_once(x)
    assert "not filed" in x.outbox[-1]["text"] and fake.posts == []


def test_confirm_enabled_files_and_status_updates(fake, tmp_path):
    state = tmp_path / "state.json"
    r = robot(fake, send_enabled=True, api_keys={"bloomington-in": "KEY"}, state_path=str(state),
              auto_status_updates=True)
    x = StubXAdapter()
    first = x.add_mention("joshua", "@joshua_robot pothole at 401 N Morton St, Bloomington, IN")
    x.add_mention("joshua", "@joshua_robot yes")
    r.run_once(x)
    assert len(fake.posts) == 1 and fake.posts[0][1]["api_key"] == "KEY"   # fake transport, nothing real
    assert "Filed" in x.outbox[-1]["text"] and "#999" in x.outbox[-1]["text"]
    fake.add(r"requests/999\.json", [{"service_request_id": "999", "status": "closed", "status_notes": "Fixed."}])
    updates = r.poll_status_updates(x)
    assert updates and "CLOSED" in updates[0] and x.outbox[-1]["in_reply_to"] == first.id
    assert r.poll_status_updates(x) == []  # no change -> no post
    assert state.exists() and "999" in state.read_text()


def test_x_api_adapter_is_disabled():
    with pytest.raises(RuntimeError):
        XApiV2Adapter("123").poll_mentions()
    with pytest.raises(RuntimeError):
        XApiV2Adapter("123").post_reply("1", "hi")


def test_cli_simulate_offline(capsys):
    from civicbot.__main__ import main
    assert main(["simulate", "--offline", "@joshua_robot streetlight out at 401 N Morton St, Bloomington, IN",
                 "--then", "YES"]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN Open311 POST (not sent)" in out and "Street Lights" in out and "NOT filed" in out


def test_status_updates_not_posted_unless_enabled(fake):
    r = robot(fake, send_enabled=True, api_keys={"bloomington-in": "KEY"})
    x = StubXAdapter()
    x.add_mention("joshua", "@joshua_robot pothole at 401 N Morton St, Bloomington, IN")
    x.add_mention("joshua", "@joshua_robot yes")
    r.run_once(x)
    n = len(x.outbox)
    fake.add(r"requests/999\.json", [{"service_request_id": "999", "status": "closed"}])
    assert r.poll_status_updates(x) and len(x.outbox) == n
    x.add_mention("joshua", "@joshua_robot status #999")
    r.run_once(x)
    assert "CLOSED" in x.outbox[-1]["text"]
