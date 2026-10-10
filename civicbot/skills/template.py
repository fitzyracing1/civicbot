"""Tiny, safe template + JSON-path helpers for skill specs.

Templates use ``{name}`` or ``{name|filter}``. Lookup is a plain dict/JSON walk: no attribute
access, no indexing expressions, no code. Values coming from APIs are sanitized before they are
placed into a post (no @mentions, no links, no control characters).
"""
from __future__ import annotations

import datetime as _dt
import re
import time
from typing import Any, Callable, Dict, Optional

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*(?:\|\|[A-Za-z0-9_.]+)*)(?:\|([a-z_]+))?\}")
URL_RE = re.compile(r"(https?://|www\.)\S+", re.I)

WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers",
       81: "rain showers", 82: "violent rain showers", 85: "snow showers", 86: "heavy snow showers",
       95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail"}


def _to_epoch(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if re.fullmatch(r"\d{9,11}(\.\d+)?", s):
        return float(s)
    try:
        d = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.timestamp()


def minutes_from_now(v: Any, now: Optional[float] = None) -> Optional[int]:
    t = _to_epoch(v)
    if t is None:
        return None
    return int((t - (time.time() if now is None else now)) // 60)


def _fmt_time(v: Any) -> str:
    s = str(v)
    m = re.search(r"T?(\d{2}):(\d{2})", s)
    return f"{m.group(1)}:{m.group(2)}" if m else s


FILTERS: Dict[str, Callable[[Any], Any]] = {
    "upper": lambda v: str(v).upper(),
    "lower": lambda v: str(v).lower(),
    "title": lambda v: str(v).title(),
    "round": lambda v: round(float(v)) if _num(v) else v,
    "int": lambda v: int(float(v)) if _num(v) else v,
    "minutes_from_now": lambda v: minutes_from_now(v),
    "time_hm": _fmt_time,
    "date": lambda v: str(v)[:10],
    "wmo": lambda v: WMO.get(int(float(v)), f"code {v}") if _num(v) else v,
}


def _num(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def get_path(data: Any, path: str) -> Any:
    """'a.b.0.c' with '||' fallbacks: 'attributes.arrival_time||attributes.departure_time'."""
    if path in ("", "$"):
        return data
    for alt in path.split("||"):
        cur = data
        ok = True
        for part in alt.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                ok = False
                break
        if ok and cur is not None and cur != "":
            return cur
    return None


def sanitize(value: Any, max_len: int = 80) -> str:
    """Make API data safe to post: no links, no @mentions/#cashtag spam, one line, bounded."""
    s = str(value)
    s = URL_RE.sub("", s)
    s = re.sub(r"[@＠](\w)", r"\1", s)
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", s)
    s = " ".join(s.split())
    return s[:max_len]


class MissingValue(KeyError):
    pass


def render(template: str, lookup: Callable[[str], Any], *, sanitize_values: bool = True, strict: bool = True,
           max_value_len: int = 80) -> str:
    def sub(m: re.Match) -> str:
        name, flt = m.group(1), m.group(2)
        v = lookup(name)
        if v is not None and flt:
            v = FILTERS[flt](v)
        if v is None:
            if strict:
                raise MissingValue(name)
            return ""
        if isinstance(v, float) and sanitize_values:  # replies: 1 decimal; requests: full value
            v = f"{v:.1f}".rstrip("0").rstrip(".")
        return sanitize(v, max_value_len) if sanitize_values else str(v)
    return PLACEHOLDER_RE.sub(sub, template)


def placeholders(template: str):
    return [(m.group(1), m.group(2)) for m in PLACEHOLDER_RE.finditer(template)]
