import pytest

from civicbot import Open311Client, Open311Error, Registry, ValidationError
from conftest import FakeTransport


@pytest.fixture
def reg():
    return Registry.load_default()


def test_registry_has_verified_endpoints_and_fallback(reg):
    ids = {e.id for e in reg.endpoints}
    assert {"chicago", "boston", "bloomington-in", "austin", "brookline-ma"} <= ids
    assert reg.fallback.id == "seeclickfix" and reg.fallback.geo_scoped


@pytest.mark.parametrize("lat,lng,expected", [
    (41.8781, -87.6298, "chicago"), (42.3601, -71.0589, "boston"), (39.1653, -86.5264, "bloomington-in"),
    (30.2672, -97.7431, "austin"), (42.3318, -71.1212, "brookline-ma"), (44.9778, -93.2650, None)])
def test_registry_by_location(reg, lat, lng, expected):
    ep = reg.by_location(lat, lng)
    assert (ep.id if ep else None) == expected


def test_list_services_and_definition(reg, fake):
    c = Open311Client(reg.get("bloomington-in"), fake)
    svcs = c.list_services()
    assert len(svcs) == 63
    assert fake.calls[-1][0] == "https://bloomington.in.gov/crm/open311/v2/services.json"
    c.list_services()  # cached
    assert len(fake.calls) == 1
    d = c.get_service_definition("69")
    assert d["attributes"][0]["code"] == "issue"


def test_geo_scoped_passes_lat_long(reg, fake):
    c = Open311Client(reg.fallback, fake)
    assert len(c.list_services(41.307, -72.925)) == 44
    assert fake.calls[-1][1] == {"lat": 41.307, "long": -72.925}
    assert c.list_services(44.97, -93.26) == []


def test_list_and_get_requests(reg):
    t = FakeTransport({r"requests/42\.json": [{"service_request_id": "42", "status": "open"}],
                       r"requests\.json": [{"service_request_id": "1"}]})
    c = Open311Client(reg.get("boston"), t, jurisdiction_id="boston.gov")
    c.list_requests(status="open", service_request_ids=["1", "2"], page_size=5)
    url, params = t.calls[-1]
    assert url.endswith("/requests.json")
    assert params == {"jurisdiction_id": "boston.gov", "status": "open", "service_request_id": "1,2", "page_size": 5}
    assert c.get_request(42)["status"] == "open"


def test_build_request_payload(reg, bloomington_services):
    c = Open311Client(reg.get("bloomington-in"), FakeTransport())
    p = c.build_request("69", lat=39.1, lng=-86.5, description="out", api_key="secret",
                        attributes={"issue": "City Maintained Light", "multi": ["a", "b"]},
                        known_services=bloomington_services)
    assert p.method == "POST" and p.url == "https://bloomington.in.gov/crm/open311/v2/requests.json"
    assert p.form["service_code"] == "69" and p.form["long"] == -86.5
    assert p.form["attribute[issue]"] == "City Maintained Light"
    assert p.form["attribute[multi][]"] == ["a", "b"]
    assert p.redacted_form()["api_key"] == "***" and p.form["api_key"] == "secret"


@pytest.mark.parametrize("kwargs,needle", [
    ({}, "location is required"),
    ({"lat": 1.0}, "together"),
    ({"lat": 99.0, "lng": 0.0}, "out of range"),
    ({"lat": 1.0, "lng": 1.0, "description": "x" * 4001}, "4000"),
])
def test_build_request_validation(reg, kwargs, needle):
    c = Open311Client(reg.get("boston"), FakeTransport())
    with pytest.raises(ValidationError) as e:
        c.build_request("x", **kwargs)
    assert needle in str(e.value)


def test_validation_against_definition_and_service_list(reg, bloomington_services):
    c = Open311Client(reg.get("bloomington-in"), FakeTransport())
    definition = {"attributes": [
        {"code": "req", "required": True, "variable": True, "datatype": "string", "description": "Pole number"},
        {"code": "kind", "required": False, "variable": True, "datatype": "singlevaluelist",
         "values": [{"key": "A"}, {"key": "B"}]}]}
    with pytest.raises(ValidationError) as e:
        c.build_request("nope", lat=1, lng=1, definition=definition, attributes={"kind": "Z"},
                        known_services=bloomington_services)
    msg = str(e.value)
    assert "not offered" in msg and "'req' missing" in msg and "['Z'] not in" in msg


def test_create_request_dry_run_never_posts(reg, fake):
    c = Open311Client(reg.get("bloomington-in"), fake)
    p = c.create_request("69", lat=39.16, lng=-86.53, description="out", validate_remote=True)
    assert p.dry_run and fake.posts == []
    assert any("services/69.json" in u for u, _ in fake.calls)  # definition fetched (read-only)


def test_create_request_send_requires_confirm_and_key(reg, fake):
    c = Open311Client(reg.get("bloomington-in"), fake)
    with pytest.raises(Open311Error, match="confirm"):
        c.create_request("69", dry_run=False, lat=1, lng=1, api_key="k")
    with pytest.raises(Open311Error, match="api_key"):
        c.create_request("69", dry_run=False, confirm="SEND", lat=1, lng=1)
    assert fake.posts == []
    p = c.create_request("69", dry_run=False, confirm="SEND", api_key="k", lat=1, lng=1)
    assert not p.dry_run and p.response == [{"service_request_id": "999"}]
    assert fake.posts[0][0].endswith("/requests.json") and fake.posts[0][1]["api_key"] == "k"
