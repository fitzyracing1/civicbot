"""Offline transport backed by real responses captured 2026-10-10 (data/fixtures.json).

Used by `simulate --offline` and handy for demos without network.
"""
from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any, Mapping, Optional

from .http import HttpError, HttpTransport

GEOCODES = {
    "401 n morton st": (39.169570, -86.536198, "401 N MORTON ST, BLOOMINGTON, IN, 47404"),
    "kirkwood": (39.166700, -86.534500, "Kirkwood Ave & College Ave, Bloomington, IN"),
    "chapel st": (41.306400, -72.928900, "Chapel St, New Haven, CT"),
    "121 n lasalle": (41.883700, -87.631900, "121 N LASALLE ST, CHICAGO, IL, 60602"),
    "bloomington, in": (39.165300, -86.526400, "Bloomington, Indiana"),
    "new haven, ct": (41.308300, -72.925900, "New Haven, Connecticut"),
}


def _skill_raw(method, url, headers, body, timeout, max_bytes):
    """Canned answers for the catalog skills (shapes copied from live responses on 2026-10-10;
    times are generated relative to now so 'minutes from now' stays meaningful)."""
    import time as _t
    import datetime as _dt
    now = _t.time()
    iso = lambda m: _dt.datetime.fromtimestamp(now + m * 60, _dt.timezone(_dt.timedelta(hours=-4))).isoformat(timespec="seconds")
    host = url.split("/")[2]
    if host == "api.open-meteo.com":
        lat = 41.3 if "latitude=41" in url else 39.17
        d = {"current_units": {"temperature_2m": "°F"},
             "current": {"time": _dt.datetime.now().strftime("%Y-%m-%dT%H:%M"), "temperature_2m": 61.2 if lat > 40 else 66.9,
                         "apparent_temperature": 59.0 if lat > 40 else 64.4, "weather_code": 2 if lat > 40 else 3,
                         "wind_speed_10m": 9.1 if lat > 40 else 7.5}}
    elif host == "api-v3.mbta.com":
        d = {"data": [{"attributes": {"arrival_time": None, "departure_time": None}, "relationships": {"route": {"data": {"id": "Red"}}}},
                      {"attributes": {"arrival_time": iso(2), "departure_time": iso(3)}, "relationships": {"route": {"data": {"id": "Green-E"}}}},
                      {"attributes": {"arrival_time": iso(4), "departure_time": iso(5)}, "relationships": {"route": {"data": {"id": "Red"}}}},
                      {"attributes": {"arrival_time": iso(6), "departure_time": iso(7)}, "relationships": {"route": {"data": {"id": "Green-D"}}}}]}
    elif host == "data.cityofchicago.org":
        d = [{"sr_type": "Ridesharing Complaint", "status": "Open", "created_date": "2026-10-10T12:19:10.000"},
             {"sr_type": "Traffic Signal Out Complaint", "status": "Completed", "created_date": "2026-10-10T12:07:41.000"}]
    elif host == "api.carrismetropolitana.pt":
        d = [{"line_id": "3514", "headsign": "Cacilhas (Terminal)", "estimated_arrival_unix": None,
              "scheduled_arrival_unix": int(now + 240)},
             {"line_id": "3507", "headsign": "Cacilhas (Terminal)", "estimated_arrival_unix": int(now + 2640),
              "scheduled_arrival_unix": int(now + 2600)}]
    else:
        return 404, {}, b'{"error":"no offline fixture"}'
    return 200, {"Content-Type": "application/json"}, json.dumps(d).encode()


def offline_skill_fetcher():
    """SafeFetcher with every safety check intact, but canned responses and a fake public DNS answer."""
    from .skills.fetch import SafeFetcher

    def resolve(host):
        return ["127.0.0.1"] if host in ("localhost", "internal.example") else ["93.184.216.34"]
    return SafeFetcher(resolve=resolve, raw=_skill_raw, min_host_interval=0, allow_nets=[])


class OfflineTransport(HttpTransport):
    def __init__(self):
        super().__init__()
        self.fx = json.loads(resources.files("civicbot").joinpath("data/fixtures.json").read_text("utf-8"))
        self.calls = []

    def get_json(self, url: str, params: Optional[Mapping[str, Any]] = None, headers=None) -> Any:
        self.calls.append(("GET", url, dict(params or {})))
        if "geocoding.geo.census.gov" in url or "nominatim" in url:
            q = str((params or {}).get("address") or (params or {}).get("q") or "").lower()
            for k, (lat, lng, label) in GEOCODES.items():
                if k in q:
                    if "census" in url:
                        return {"result": {"addressMatches": [{"coordinates": {"x": lng, "y": lat}, "matchedAddress": label}]}}
                    return [{"lat": str(lat), "lon": str(lng), "display_name": label}]
            return {"result": {"addressMatches": []}} if "census" in url else []
        if "bloomington.in.gov" in url:
            if url.endswith("/services.json"):
                return self.fx["bloomington_services"]
            if re.search(r"/services/69\.json$", url):
                return self.fx["bloomington_def_69"]
            if re.search(r"/services/\w+\.json$", url):
                return {"attributes": []}
        if "seeclickfix.com" in url and url.endswith("/services.json"):
            lat = float((params or {}).get("lat", 0))
            return self.fx["seeclickfix_newhaven_services"] if 41.2 < lat < 41.4 else []
        if "seeclickfix.com" in url and "/services/" in url:
            return {"attributes": []}
        raise HttpError(599, url, "offline: no fixture")

    def post_form(self, url, data):  # pragma: no cover - never used by simulate
        raise RuntimeError("offline transport never sends")
