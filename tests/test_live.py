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


def _free_names():
    from civicbot.skills.catalog import Catalog, free_catalog_dir
    return Catalog(free_catalog_dir()).names()


@pytest.mark.parametrize("name", _free_names())
def test_live_free_catalog_skill(name):
    """v0.4: every free catalog skill answers live with its sample question (one read-only GET each)."""
    import importlib.util
    import pathlib
    import time
    from civicbot.skills import FetchError, SafeFetcher, SkillRunner
    from civicbot.skills.catalog import Catalog, free_catalog_dir
    path = pathlib.Path(__file__).parents[1] / "scripts" / "free_apis" / "check_skills.py"
    mod_spec = importlib.util.spec_from_file_location("check_skills", path)
    mod = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(mod)
    text, loc = mod.SAMPLES[name]
    home, lat, lng = loc if loc else ("", None, None)
    spec = Catalog(free_catalog_dir()).get(name)
    runner = SkillRunner(SafeFetcher())
    try:
        replies = runner.run_read(spec, runner.context(spec, text, home_city=home, default_lat=lat, default_lng=lng), [])
    except (FetchError, OSError) as e:
        pytest.skip(f"network unavailable: {e}")
    time.sleep(0.3)
    assert replies and replies[0]
    print(name, "->", replies[0])
