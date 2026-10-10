"""Free geocoding: US Census geocoder first, then OpenStreetMap Nominatim.

Nominatim usage policy: max 1 request/second and an identifying User-Agent
(https://operations.osmfoundation.org/policies/nominatim/). The default
transport rate-limits nominatim.openstreetmap.org to ~1 req/s.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .http import HttpError, HttpTransport

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


@dataclass
class GeocodeResult:
    lat: float
    lng: float
    matched: str
    source: str
    approximate: bool = False  # True = street centroid, not the exact point


class Geocoder:
    def __init__(self, transport: Optional[HttpTransport] = None, use_census: bool = True,
                 use_nominatim: bool = True, email: Optional[str] = None):
        self.http = transport or HttpTransport()
        self.use_census, self.use_nominatim, self.email = use_census, use_nominatim, email

    def census(self, address: str) -> Optional[GeocodeResult]:
        data = self.http.get_json(CENSUS_URL, {"address": address, "benchmark": "Public_AR_Current",
                                               "format": "json"})
        matches = (data.get("result") or {}).get("addressMatches") or []
        if not matches:
            return None
        m = matches[0]
        c = m["coordinates"]
        return GeocodeResult(float(c["y"]), float(c["x"]), m.get("matchedAddress", address), "census")

    def nominatim(self, query: str) -> Optional[GeocodeResult]:
        params = {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us", "email": self.email}
        data = self.http.get_json(NOMINATIM_URL, params)
        if not data:
            return None
        r = data[0]
        return GeocodeResult(float(r["lat"]), float(r["lon"]), r.get("display_name", query), "nominatim")

    def geocode(self, address: str) -> Optional[GeocodeResult]:
        attempts = []
        is_intersection = bool(re.search(r"\s(&|and|@|at)\s", address))
        if self.use_census and not is_intersection:  # Census can't do intersections
            attempts.append((self.census, address))
        if self.use_nominatim:
            attempts.append((self.nominatim, address))
            if "&" in address:
                attempts.append((self.nominatim, address.replace("&", "and")))
        for fn, q in attempts:
            try:
                res = fn(q)
            except (HttpError, OSError, ValueError, KeyError):
                continue
            if res:
                return res
        if is_intersection and self.use_nominatim:
            # Nominatim can't geocode intersections; fall back to the first street
            # in the same city. Good enough to pick a jurisdiction, NOT for the
            # request point (callers should send address_string only).
            parts = re.split(r"\s(?:&|and|@|at)\s", address, maxsplit=1)
            city = address.split(",", 1)[1] if "," in address else ""
            street = parts[0].split(",")[0]
            street = re.sub(r"\bSt\b\.?", "Street", street)
            street = re.sub(r"\bAve\b\.?", "Avenue", street)
            try:
                res = self.nominatim(f"{street},{city}" if city else street)
            except (HttpError, OSError, ValueError, KeyError):
                res = None
            if res:
                res.approximate = True
                res.source += "-street-approx"
                return res
        return None
