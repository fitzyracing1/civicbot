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
