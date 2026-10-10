"""Execute a (validated) user skill for one mention: build request -> safe fetch -> reply text."""
from __future__ import annotations

import datetime as _dt
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..geocode import Geocoder
from .fetch import FetchBlocked, FetchError, SafeFetcher
from .template import MissingValue, _to_epoch, get_path, minutes_from_now, render

LOC_RE = re.compile(r"\b(?:at|on|near|in|around|by|for|outside)\s+(?P<loc>[^?!]+?)\s*[?.!]*$", re.I)
COORD_RE = re.compile(r"(?P<lat>-?\d{1,2}\.\d{3,})\s*,\s*(?P<lng>-?\d{1,3}\.\d{3,})")


class SkillInputError(Exception):
    """The mention is missing something the skill needs; message is safe to post."""


@dataclass
class SkillOutcome:
    reply: Optional[str] = None
    log: List[str] = field(default_factory=list)
    prepared: Optional[dict] = None   # write skills: the call that would be made (no secrets)
    pending: Optional[dict] = None    # write skills awaiting YES


@dataclass
class SkillContext:
    text: str
    home_city: str = ""
    location_text: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    inputs: Dict[str, str] = field(default_factory=dict)
    now: float = field(default_factory=time.time)

    def var(self, name: str) -> Any:
        if name in ("text", "query"):
            return self.text
        if name == "owner.home_city":
            return self.home_city
        if name == "location.text":
            return self.location_text or self.home_city
        if name == "location.lat":
            return None if self.lat is None else round(self.lat, 5)
        if name == "location.lng":
            return None if self.lng is None else round(self.lng, 5)
        if name.startswith("inputs."):
            return self.inputs.get(name[7:])
        if name.startswith("date."):
            today = _dt.datetime.fromtimestamp(self.now, _dt.timezone.utc).date()
            if name == "date.today":
                return today.isoformat()
            if name == "date.now_unix":
                return int(self.now)
            m = re.fullmatch(r"date\.days_ago_(\d+)", name)
            if m:
                return (today - _dt.timedelta(days=int(m.group(1)))).isoformat()
        return None


class SkillRunner:
    def __init__(self, fetcher: SafeFetcher, geocoder: Optional[Geocoder] = None,
                 secret_lookup: Callable[[str], Optional[str]] = lambda ref: None):
        self.fetcher, self.geocoder, self.secret = fetcher, geocoder, secret_lookup

    # -- context -------------------------------------------------------------------------
    def context(self, spec: dict, text: str, *, home_city: str = "", default_lat=None, default_lng=None,
                lat=None, lng=None, now: Optional[float] = None) -> SkillContext:
        ctx = SkillContext(text=text, home_city=home_city, now=time.time() if now is None else now)
        for name, d in spec.get("inputs", {}).items():
            val = None
            if d.get("regex"):
                m = re.search(d["regex"], text, re.I)
                if m:
                    val = (m.group(1) if m.groups() else m.group(0)).strip()
            val = val if val is not None else d.get("default")
            if val is not None and d.get("case"):
                val = val.upper() if d["case"] == "upper" else val.lower()
            if val is None:
                if d.get("required"):
                    raise SkillInputError(f"Need {d.get('description') or name} for {spec['name']}.")
                continue
            if not re.fullmatch(d["pattern"].strip("^$"), val):
                raise SkillInputError(f"'{val[:30]}' isn't a valid {name} for {spec['name']}.")
            ctx.inputs[name] = val
        if spec.get("location", "none") == "none":
            return ctx
        m = COORD_RE.search(text)
        if lat is None and m:
            lat, lng = float(m.group("lat")), float(m.group("lng"))
        if lat is not None:
            ctx.lat, ctx.lng, ctx.location_text = lat, lng, f"{lat:.4f},{lng:.4f}"
            return ctx
        lm = LOC_RE.search(COORD_RE.sub("", text))
        place = lm.group("loc").strip(" ,") if lm else ""
        if place and self.geocoder:
            q = place if ("," in place or not home_city) else f"{place}, {home_city}"
            g = self.geocoder.geocode(q)
            if g:
                ctx.lat, ctx.lng, ctx.location_text = g.lat, g.lng, place
                return ctx
        if default_lat is not None:
            ctx.lat, ctx.lng, ctx.location_text = default_lat, default_lng, home_city or "your default spot"
            return ctx
        if home_city and self.geocoder:
            g = self.geocoder.geocode(home_city)
            if g:
                ctx.lat, ctx.lng, ctx.location_text = g.lat, g.lng, home_city
                return ctx
        if spec.get("location") == "required":
            raise SkillInputError(f"Where? Add a place, e.g. '{spec['triggers']['keywords'][0]} in <city>'.")
        return ctx

    # -- request -------------------------------------------------------------------------
    def build(self, spec: dict, ctx: SkillContext) -> dict:
        req = spec["request"]

        def lookup(n):
            v = ctx.var(n)
            if v is None:
                raise SkillInputError(f"{spec['name']} needs {n}, which I couldn't work out.")
            return v

        path = render(req["path"], lambda n: urllib.parse.quote(str(lookup(n)), safe=""), sanitize_values=False)

        def rv(v):
            return render(v, lookup, sanitize_values=False) if isinstance(v, str) else v
        params = {k: rv(v) for k, v in (req.get("params") or {}).items()}
        body = {k: rv(v) for k, v in (req.get("body") or {}).items()} if req.get("body") else None
        headers = {k: rv(v) for k, v in (req.get("headers") or {}).items()}
        return {"method": req["method"], "url": req["base_url"] + path, "params": params, "headers": headers,
                "body": body, "body_format": req.get("body_format", "json")}

    def _auth(self, spec: dict, call: dict, log: List[str]) -> dict:
        auth = spec.get("auth") or {"type": "none"}
        if auth["type"] == "none":
            return call
        value = self.secret(auth["secret_ref"])
        if not value:
            if auth.get("required", True):
                raise SkillInputError(f"{spec['name']} needs the owner's secret '{auth['secret_ref']}' "
                                      "(civicbot secret set).")
            log.append(f"optional secret {auth['secret_ref']} not set; calling without it")
            return call
        call = dict(call, params=dict(call["params"]), headers=dict(call["headers"]))
        if auth["type"] == "bearer":
            call["headers"]["Authorization"] = f"Bearer {value}"
        elif auth["in"] == "header":
            call["headers"][auth["name"]] = value
        else:
            call["params"][auth["name"]] = value
        log.append(f"auth: secret {auth['secret_ref']} applied ({auth['type']}, value hidden)")
        return call

    def execute(self, spec: dict, call: dict, log: List[str]) -> Any:
        call = self._auth(spec, call, log)
        lim = spec.get("limits", {})
        kw = {"allowed_domains": spec["allowed_domains"], "params": call["params"] or None,
              "headers": call["headers"], "timeout": lim.get("timeout_s", 10), "max_bytes": lim.get("max_bytes", 262_144)}
        if call.get("body") is not None:
            kw["json_body" if call.get("body_format", "json") == "json" else "form_body"] = call["body"]
        res = self.fetcher.request(call["method"], call["url"], **kw)
        log.append(f"{call['method']} {urllib.parse.urlsplit(call['url']).hostname} -> {res.status} ({res.nbytes} bytes)")
        return res.data

    # -- response ------------------------------------------------------------------------
    def replies(self, spec: dict, data: Any, ctx: SkillContext) -> List[str]:
        resp = spec["response"]
        def _path(p: str) -> str:  # v0.4: extract paths may name an input, e.g. "rates.{inputs.to}"
            if "{" not in p:
                return p
            try:
                return render(p, ctx.var, sanitize_values=False)
            except MissingValue:
                return "\x00missing"
        values: Dict[str, Any] = {k: get_path(data, _path(p)) for k, p in resp.get("extract", {}).items()}
        empty = False
        if "list" in resp:
            L = resp["list"]
            rows = get_path(data, L["path"])
            rows = rows if isinstance(rows, list) else []
            out = []
            if L.get("sort"):
                rows = sorted(rows, key=lambda r: _to_epoch(get_path(r, L["sort"])) or float("inf"))
            for r in rows:
                if any(get_path(r, q) is None for q in L.get("require", [])):
                    continue
                if L.get("skip_past"):
                    mins = minutes_from_now(get_path(r, L["skip_past"]), ctx.now)
                    if mins is None or mins < 0:
                        continue
                try:
                    out.append(render(L["item"], lambda n, r=r: get_path(r, n)))
                except MissingValue:
                    continue
                if len(out) >= L.get("max", 3):
                    break
            values["items"] = L.get("join", ", ").join(out)
            values["count"] = len(out)
            empty = not out

        def lookup(n):
            if n in values:
                return values[n]
            return ctx.var(n)
        templates = (resp.get("empty_replies") or ["Nothing found right now."]) if empty else resp["replies"]
        rendered = []
        for t in templates:
            try:
                rendered.append(render(t, lookup, max_value_len=220))
            except MissingValue:
                continue
        if not rendered:
            raise SkillInputError(f"{spec['name']}: the API answered, but not in the shape the skill expects.")
        return rendered

    # -- one-shot for reads (and `civicbot skill test`) ----------------------------------
    def run_read(self, spec: dict, ctx: SkillContext, log: List[str]) -> List[str]:
        call = self.build(spec, ctx)
        log.append(f"request {call['method']} {call['url']} params={call['params']}")
        return self.replies(spec, self.execute(spec, call, log), ctx)


def usage_check(usage: Dict[str, dict], spec: dict, now: Optional[float] = None) -> Optional[str]:
    """Per-robot, per-skill rate limits. Returns a refusal message or None (and records the call)."""
    now = time.time() if now is None else now
    lim = spec.get("limits", {})
    day = _dt.datetime.fromtimestamp(now, _dt.timezone.utc).date().isoformat()
    u = usage.setdefault(spec["name"], {"day": day, "count": 0, "last": 0.0})
    if u["day"] != day:
        u.update(day=day, count=0)
    if now - u["last"] < lim.get("min_interval_s", 2):
        return f"{spec['name']} was just used; try again in a few seconds."
    if u["count"] >= lim.get("max_calls_per_day", 200):
        return f"{spec['name']} hit its daily limit ({lim.get('max_calls_per_day', 200)} calls)."
    u["last"], u["count"] = now, u["count"] + 1
    return None


__all__ = ["SkillRunner", "SkillContext", "SkillOutcome", "SkillInputError", "usage_check",
           "FetchBlocked", "FetchError"]
