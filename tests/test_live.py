"""Live READ-ONLY smoke tests. Run with: CIVICBOT_LIVE=1 pytest -m live"""
import os

import pytest

from civicbot import Open311Client, Registry

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("CIVICBOT_LIVE") != "1", reason="set CIVICBOT_LIVE=1")]


@pytest.mark.parametrize("endpoint_id", ["bloomington-in", "boston"])
def test_live_services_list(endpoint_id):
    c = Open311Client(Registry.load_default().get(endpoint_id))
    try:
        svcs = c.list_services()
    except OSError as e:
        pytest.skip(f"network unavailable: {e}")
    assert svcs and all("service_code" in s for s in svcs)


def test_live_seeclickfix_geo_lookup():
    c = Open311Client(Registry.load_default().fallback)
    try:
        svcs = c.list_services(41.307153, -72.925791)  # New Haven, CT
    except OSError as e:
        pytest.skip(f"network unavailable: {e}")
    assert len(svcs) > 0


def test_live_dry_run_against_real_schema():
    c = Open311Client(Registry.load_default().get("bloomington-in"))
    p = c.create_request("69", lat=39.16957, lng=-86.536198, description="smoke test (dry run)",
                         validate_remote=True)
    assert p.dry_run and p.response is None


def test_live_gtfs_rt_mbta():
    from civicbot import TransitFeed
    feed = TransitFeed("https://cdn.mbta.com/realtime/TripUpdates.pb")  # public, no key
    try:
        arr = feed.arrivals(route_id="Red")
    except OSError as e:
        pytest.skip(f"network unavailable: {e}")
    assert any(a.time for a in arr)


CATALOG_LIVE = {
    "open-meteo-weather": ("weather in Bloomington, IN", "°F"),
    "mbta-next-trains": ("next train at place-pktrm", "place-pktrm"),
    "chicago-311-nearby": ("311 requests near 121 N LaSalle St, Chicago, IL", "LaSalle"),
    "carris-metropolitana-arrivals": ("carris 020429", "020429"),
}


@pytest.mark.parametrize("name", sorted(CATALOG_LIVE))
def test_live_catalog_skill(name):
    """Each reviewed catalog skill answers live (read-only GET through SafeFetcher with all guards)."""
    from civicbot.geocode import Geocoder
    from civicbot.skills import Catalog, FetchError, SafeFetcher, SkillRunner
    spec = Catalog().get(name)
    text, expect = CATALOG_LIVE[name]
    runner = SkillRunner(SafeFetcher(), Geocoder())
    log = []
    try:
        replies = runner.run_read(spec, runner.context(spec, text), log)
    except (FetchError, OSError) as e:
        pytest.skip(f"network unavailable: {e}")
    assert replies and all(len(r) <= 270 for r in replies)
    assert expect in replies[0]
    print(name, "->", replies[0])
