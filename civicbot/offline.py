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
}


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
