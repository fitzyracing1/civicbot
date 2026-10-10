"""Pick the right Open311 endpoint for a place."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .geocode import Geocoder, GeocodeResult
from .http import HttpError, HttpTransport
from .open311 import Open311Client
from .registry import Endpoint, Registry


@dataclass
class Resolution:
    endpoint: Optional[Endpoint]
    lat: Optional[float]
    lng: Optional[float]
    method: str  # "registry-bbox" | "seeclickfix" | "none"
    reason: str = ""
    geocode: Optional[GeocodeResult] = None

    @property
    def found(self) -> bool:
        return self.endpoint is not None


class JurisdictionResolver:
    def __init__(self, registry: Optional[Registry] = None, transport: Optional[HttpTransport] = None,
                 geocoder: Optional[Geocoder] = None, check_seeclickfix: bool = True):
        self.registry = registry or Registry.load_default()
        self.http = transport or HttpTransport()
        self.geocoder = geocoder or Geocoder(self.http)
        self.check_seeclickfix = check_seeclickfix

    def client_for(self, res: Resolution) -> Open311Client:
        if not res.endpoint:
            raise LookupError(res.reason or "no endpoint")
        return Open311Client(res.endpoint, self.http)

    def resolve_point(self, lat: float, lng: float) -> Resolution:
        ep = self.registry.by_location(lat, lng)
        if ep:
            return Resolution(ep, lat, lng, "registry-bbox", f"inside {ep.name} bounding box")
        fb = self.registry.fallback
        if fb and self.check_seeclickfix:
            try:
                services = Open311Client(fb, self.http).list_services(lat, lng)
            except (HttpError, OSError, ValueError) as e:
                return Resolution(None, lat, lng, "none", f"SeeClickFix lookup failed: {e}")
            if services:
                return Resolution(fb, lat, lng, "seeclickfix",
                                  f"SeeClickFix serves this point ({len(services)} request types)")
        return Resolution(None, lat, lng, "none",
                          "no known 311 API covers this location (most US towns have none)")

    def resolve_address(self, address: str) -> Resolution:
        g = self.geocoder.geocode(address)
        if not g:
            return Resolution(None, None, None, "none", f"could not geocode {address!r}")
        res = self.resolve_point(g.lat, g.lng)
        res.geocode = g
        return res
