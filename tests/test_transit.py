from google.transit import gtfs_realtime_pb2

from civicbot import TransitFeed
from conftest import FakeTransport


def make_feed() -> bytes:
    f = gtfs_realtime_pb2.FeedMessage()
    f.header.gtfs_realtime_version = "2.0"
    f.header.timestamp = 1_800_000_000
    for i, (route, stop, t) in enumerate([("6", "S1", 1_800_000_600), ("3", "S1", 1_800_000_300), ("6", "S2", 1_800_000_900)]):
        e = f.entity.add(); e.id = f"tu{i}"
        e.trip_update.trip.trip_id = f"trip{i}"; e.trip_update.trip.route_id = route
        s = e.trip_update.stop_time_update.add(); s.stop_id = stop; s.arrival.time = t; s.arrival.delay = 60
    v = f.entity.add(); v.id = "v1"
    v.vehicle.vehicle.id = "bus42"; v.vehicle.trip.route_id = "6"
    v.vehicle.position.latitude = 39.16; v.vehicle.position.longitude = -86.53
    a = f.entity.add(); a.id = "a1"
    a.alert.header_text.translation.add().text = "Detour on Kirkwood"
    return f.SerializeToString()


def test_transit_feed_parsing():
    t = FakeTransport({r"example\.com/rt": make_feed()})
    feed = TransitFeed("https://example.com/rt", t, headers={"x-api-key": "k"})
    msg = feed.fetch()
    arr = feed.arrivals(stop_id="S1", feed=msg)
    assert [a.route_id for a in arr] == ["3", "6"] and arr[0].delay == 60
    assert [a.stop_id for a in feed.arrivals(route_id="6", feed=msg)] == ["S1", "S2"]
    assert feed.vehicles(feed=msg)[0]["vehicle_id"] == "bus42"
    assert feed.alerts(feed=msg) == ["Detour on Kirkwood"]
