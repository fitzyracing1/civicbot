"""Rule-based intent parsing for robot mentions. No LLM required.

Pass ``llm_hook`` (a callable ``text -> Intent | None``) to IntentParser to
plug in a model for messages the rules can't handle. Note: X requires
prior written approval for AI reply bots; see README.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

STOP_WORDS = {"stop", "unsubscribe", "opt out", "optout", "leave me alone", "cancel"}
TRANSIT_RE = re.compile(r"\b(bus|buses|train|trains|tram|subway|metro|next|arrivals?|route|stop id|transit)\b", re.I)
STATUS_RE = re.compile(r"\b(status|update|any news|progress)\b.*?#?(?P<id>[A-Za-z0-9-]{3,})?\s*$", re.I)
REQUEST_ID_RE = re.compile(r"#(?P<id>[A-Za-z0-9-]{3,})")
COORDS_RE = re.compile(r"\(?\s*(?P<lat>-?\d{1,2}\.\d{3,})\s*,\s*(?P<lng>-?\d{1,3}\.\d{3,})\s*\)?")
LOC_SPLIT_RE = re.compile(r"\s(?:at|on|near|by|outside|in front of|@)\s+(?P<loc>.+)$", re.I)
HANDLE_RE = re.compile(r"(^|\s)@\w{1,15}")


@dataclass
class Intent:
    kind: str  # report | status | transit | confirm | updates | stop | help
    text: str
    issue: str = ""
    location: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    request_id: str = ""
    extra: dict = field(default_factory=dict)


class IntentParser:
    def __init__(self, llm_hook: Optional[Callable[[str], Optional[Intent]]] = None):
        self.llm_hook = llm_hook

    @staticmethod
    def clean(text: str) -> str:
        return re.sub(r"\s+", " ", HANDLE_RE.sub(" ", text)).strip()

    def parse(self, text: str, lat: Optional[float] = None, lng: Optional[float] = None) -> Intent:
        body = self.clean(text)
        low = body.lower().strip(" .!?")
        if low in STOP_WORDS or any(low.startswith(w) for w in ("stop ", "unsubscribe")):
            return Intent("stop", body)
        if low in {"updates on", "updates off", "notify me", "no updates"}:
            return Intent("updates", body, extra={"on": low in {"updates on", "notify me"}})
        if low in {"yes", "y", "file it", "confirm", "do it", "send it"}:
            return Intent("confirm", body)
        if not low or low in {"help", "?", "hi", "hello"}:
            return Intent("help", body)

        m = COORDS_RE.search(body)
        if m:
            lat, lng = float(m.group("lat")), float(m.group("lng"))
            body = (body[:m.start()] + body[m.end():]).strip()

        rid = REQUEST_ID_RE.search(body)
        if STATUS_RE.search(body) and (rid or "status" in low):
            return Intent("status", body, request_id=rid.group("id") if rid else "", lat=lat, lng=lng)

        if TRANSIT_RE.search(body) and not re.search(r"\b(shelter|bench|sign)\b", low):
            return Intent("transit", body, lat=lat, lng=lng)

        issue, location = body, ""
        lm = LOC_SPLIT_RE.search(body)
        if lm:
            issue, location = body[:lm.start()].strip(), lm.group("loc").strip(" .!")
        prev = None
        while prev != issue:
            prev = issue
            issue = re.sub(r"^(please|report|there'?s|there is|a|an|the)\s+", "", issue, flags=re.I).strip(" ,.-:")
        if self.llm_hook and not self._looks_like_issue(issue):
            hooked = self.llm_hook(text)  # rules unsure -> ask the model (if one is plugged in)
            if hooked:
                return hooked
        if issue:
            return Intent("report", body, issue=issue, location=location, lat=lat, lng=lng)
        return Intent("help", body)

    @staticmethod
    def _looks_like_issue(issue: str) -> bool:
        from .matcher import ServiceMatcher
        return ServiceMatcher().canonicalize(issue) is not None
