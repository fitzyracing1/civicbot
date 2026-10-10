"""Bundled registry of verified Open311 GeoReport v2 endpoints."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class Endpoint:
    id: str
    name: str
    base_url: str
    bbox: Optional[Sequence[float]] = None  # [min_lat, min_lng, max_lat, max_lng]
    write: bool = False
    api_key_required_for_write: bool = True
    geo_scoped: bool = False  # True = jurisdiction chosen per call by lat/long (SeeClickFix)
    docs: str = ""
    key_request: str = ""

    def contains(self, lat: float, lng: float) -> bool:
        if not self.bbox:
            return False
        a, b, c, d = self.bbox
        return a <= lat <= c and b <= lng <= d

    @classmethod
    def from_dict(cls, d: dict) -> "Endpoint":
        keys = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in keys})


@dataclass
class Registry:
    endpoints: List[Endpoint] = field(default_factory=list)
    fallback: Optional[Endpoint] = None

    @classmethod
    def load_default(cls) -> "Registry":
        text = resources.files("civicbot").joinpath("data/endpoints.json").read_text("utf-8")
        return cls.from_json(json.loads(text))

    @classmethod
    def from_json(cls, data: dict) -> "Registry":
        fb = data.get("fallback")
        return cls([Endpoint.from_dict(e) for e in data.get("endpoints", [])],
                   Endpoint.from_dict(fb) if fb else None)

    def get(self, endpoint_id: str) -> Endpoint:
        for e in self.all():
            if e.id == endpoint_id:
                return e
        raise KeyError(f"unknown endpoint {endpoint_id!r}; known: {[e.id for e in self.all()]}")

    def all(self) -> List[Endpoint]:
        return self.endpoints + ([self.fallback] if self.fallback else [])

    def by_location(self, lat: float, lng: float) -> Optional[Endpoint]:
        def area(e: Endpoint) -> float:
            a, b, c, d = e.bbox
            return (c - a) * (d - b)
        # smallest box first, so enclaves (Brookline inside Boston's box) win
        for e in sorted((e for e in self.endpoints if e.bbox), key=area):
            if e.contains(lat, lng):
                return e
        return None
