"""Map free-text issues to a city's Open311 service_code.

Each city names services differently ("Street Lights", "Street Lamp",
"Streetlight Out"). We expand the user's words with a small synonym table
then score every service by token overlap. Deterministic and explainable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

CANONICAL: Dict[str, List[str]] = {
    "streetlight": ["streetlight", "street light", "street lamp", "lamp", "light out", "light", "lights", "lighting", "dark"],
    "pothole": ["pothole", "potholes", "pot hole", "street repair", "road damage", "pavement", "crack"],
    "graffiti": ["graffiti", "tag", "tagging", "vandalism", "spray paint"],
    "trash": ["trash", "garbage", "litter", "missed pickup", "missed trash", "overflowing", "bin", "dumping", "dumped"],
    "recycling": ["recycling", "recycle"],
    "sidewalk": ["sidewalk", "curb", "trip hazard", "blocked sidewalk"],
    "signal": ["traffic signal", "traffic light", "signal", "pedestrian signal", "walk signal"],
    "sign": ["sign", "stop sign", "street sign", "signs"],
    "tree": ["tree", "branch", "limb", "fallen tree", "street trees"],
    "abandoned_vehicle": ["abandoned car", "abandoned vehicle", "junk car", "abandoned"],
    "parking": ["illegal parking", "parked", "blocking driveway", "parking violation", "parking"],
    "snow": ["snow", "ice", "unplowed", "plow"],
    "animal": ["dead animal", "deer", "raccoon", "animal", "deceased"],
    "rodent": ["rat", "rats", "rodent", "mice"],
    "scooter": ["scooter", "e-bike", "bike share", "bird", "lime"],
    "drainage": ["drainage", "flood", "flooding", "drain", "storm drain", "catch basin", "sewer"],
    "encampment": ["encampment", "homeless", "tent"],
    "needles": ["needle", "needles", "syringe"],
}
GENERIC = {"street", "repair", "damage", "new", "public", "city", "service", "concerns", "concern"}
STOP = {"the", "a", "an", "is", "are", "at", "on", "of", "and", "or", "to", "in", "out", "my", "our", "other", "request", "requests", "issues", "related", "complaints", "problems", "general"}


def _tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in STOP]


def _stem(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") else t


@dataclass
class ServiceMatch:
    service: dict
    score: float
    canonical: Optional[str]
    why: str

    @property
    def service_code(self) -> str:
        return str(self.service.get("service_code"))

    @property
    def service_name(self) -> str:
        return str(self.service.get("service_name", ""))


class ServiceMatcher:
    def __init__(self, synonyms: Optional[Dict[str, List[str]]] = None, min_score: float = 2.0):
        self.synonyms = synonyms or CANONICAL
        self.min_score = min_score

    def canonicalize(self, text: str) -> Optional[str]:
        low = f" {text.lower()} "
        best, best_len = None, 0
        for canon, words in self.synonyms.items():
            for w in words:
                if re.search(rf"\b{re.escape(w)}\b", low) and len(w) > best_len:
                    best, best_len = canon, len(w)
        return best

    def match(self, issue: str, services: Iterable[dict]) -> Optional[ServiceMatch]:
        canon = self.canonicalize(issue)
        query = {_stem(t) for t in _tokens(issue)}
        expanded = set(query)
        if canon:
            for w in self.synonyms[canon]:
                expanded |= {_stem(t) for t in _tokens(w)}
        best: Optional[ServiceMatch] = None
        for svc in services:
            name = str(svc.get("service_name", ""))
            name_toks = {_stem(t) for t in _tokens(name)}
            other_toks = {_stem(t) for t in _tokens(" ".join(str(svc.get(k) or "") for k in ("description", "keywords", "group")))}
            strong = name_toks - GENERIC
            direct = len(query & strong) * 2.0
            synonym = len((expanded - query) & strong) * 1.5
            context = len(expanded & other_toks) * 0.5
            phrase = 0.0
            if canon and any(w in name.lower() for w in self.synonyms[canon] if len(w) > 3):
                phrase = 1.5
            unmatched = len(name_toks - expanded) * 0.5  # prefer specific, concise names
            score = direct + synonym + context + phrase - unmatched
            if score > (best.score if best else 0):
                best = ServiceMatch(svc, score, canon,
                                    f"direct={direct} synonym={synonym} context={context} phrase={phrase} unmatched=-{unmatched}")
        if best and best.score >= self.min_score:
            return best
        return None
