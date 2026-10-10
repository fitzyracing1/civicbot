from civicbot import Geocoder, JurisdictionResolver
from conftest import FakeTransport, census_hit


def test_census_geocode(fake):
    g = Geocoder(fake).geocode("401 N Morton St, Bloomington, IN")
    assert g.source == "census" and abs(g.lat - 39.16957) < 1e-6 and not g.approximate


def test_intersection_skips_census_and_falls_back_to_street(fake):
    calls = []

    def nom(url, params):
        calls.append(params["q"])
        return [{"lat": "41.31", "lon": "-72.94", "display_name": "Chapel Street"}] if params["q"].startswith("Chapel Street") else []
    t = FakeTransport({r"nominatim": nom})
    g = Geocoder(t).geocode("Chapel St & College St, New Haven, CT")
    assert g.approximate and g.source == "nominatim-street-approx"
    assert not any("census" in u for u, _ in t.calls)
    assert calls[0] == "Chapel St & College St, New Haven, CT"
    assert calls[-1].startswith("Chapel Street")


def test_geocode_miss_returns_none():
    t = FakeTransport({r"census": {"result": {"addressMatches": []}}, r"nominatim": []})
    assert Geocoder(t).geocode("nowhere") is None


def test_resolver_bbox(fake):
    r = JurisdictionResolver(transport=fake).resolve_address("401 N Morton St, Bloomington, IN")
    assert r.found and r.endpoint.id == "bloomington-in" and r.method == "registry-bbox"


def test_resolver_seeclickfix_and_none(fake):
    r = JurisdictionResolver(transport=fake)
    hit = r.resolve_point(41.307, -72.925)
    assert hit.endpoint.id == "seeclickfix" and "44" in hit.reason
    miss = r.resolve_point(44.97, -93.26)
    assert not miss.found and miss.method == "none"


def test_resolver_can_skip_seeclickfix(fake):
    r = JurisdictionResolver(transport=fake, check_seeclickfix=False)
    assert not r.resolve_point(41.307, -72.925).found
