"""Minimal GTFS-Realtime reader (optional dependency: gtfs-realtime-bindings).

Point it at any agency's GTFS-RT TripUpdates / VehiclePositions / Alerts URL
(find feeds at https://mobilitydatabase.org or https://www.transit.land).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from .http import HttpTransport


def _pb2():
    try:
        from google.transit import gtfs_realtime_pb2  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install 'civicbot[transit]' (gtfs-realtime-bindings)") from e
    return gtfs_realtime_pb2


@dataclass
class Arrival:
    route_id: str
    trip_id: str
    stop_id: str
    time: Optional[int]
    delay: Optional[int]


class TransitFeed:
    def __init__(self, url: str, transport: Optional[HttpTransport] = None,
                 headers: Optional[Mapping[str, str]] = None, params: Optional[Mapping[str, Any]] = None):
        self.url, self.http = url, transport or HttpTransport()
        self.headers, self.params = dict(headers or {}), dict(params or {})

    def fetch(self):
        msg = _pb2().FeedMessage()
        msg.ParseFromString(self.http.get_bytes(self.url, self.params, headers=self.headers))
        return msg

    @staticmethod
    def parse(raw: bytes):
        msg = _pb2().FeedMessage()
        msg.ParseFromString(raw)
        return msg

    def arrivals(self, stop_id: Optional[str] = None, route_id: Optional[str] = None,
                 feed=None) -> List[Arrival]:
        feed = feed or self.fetch()
        out: List[Arrival] = []
        for ent in feed.entity:
            if not ent.HasField("trip_update"):
                continue
            tu = ent.trip_update
            if route_id and tu.trip.route_id != route_id:
                continue
            for stu in tu.stop_time_update:
                if stop_id and stu.stop_id != stop_id:
                    continue
                ev = stu.arrival if stu.HasField("arrival") and stu.arrival.time else stu.departure
                out.append(Arrival(tu.trip.route_id, tu.trip.trip_id, stu.stop_id,
                                   ev.time or None, ev.delay if ev.HasField("delay") else None))
        # timed predictions first, soonest first; untimed (e.g. skipped stops) last
        return sorted(out, key=lambda a: (a.time is None, a.time or 0))

    def vehicles(self, route_id: Optional[str] = None, feed=None) -> List[Dict[str, Any]]:
        feed = feed or self.fetch()
        out = []
        for ent in feed.entity:
            if ent.HasField("vehicle"):
                v = ent.vehicle
                if route_id and v.trip.route_id != route_id:
                    continue
                out.append({"vehicle_id": v.vehicle.id, "route_id": v.trip.route_id,
                            "lat": v.position.latitude, "lng": v.position.longitude,
                            "timestamp": v.timestamp})
        return out

    def alerts(self, feed=None) -> List[str]:
        feed = feed or self.fetch()
        out = []
        for ent in feed.entity:
            if ent.HasField("alert") and ent.alert.header_text.translation:
                out.append(ent.alert.header_text.translation[0].text)
        return out
