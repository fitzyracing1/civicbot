"""Robot engine: one robot account per person, acting only for its owner.

Policy guards (see README "X policy findings"):
* acts only if the owner gave express consent at connect time (Automation Rules II.A)
* acts only on mentions/DMs from its owner (or people the owner allowlisted)
* at most ONE reply per mention (dedupe by mention id); replies only to posts that
  @mention the robot (X "summoned" rule for API replies)
* STOP opt-out honored immediately and persisted; START resumes
* follow-up status replies only with a separate explicit opt-in ("updates on")
* replies are varied per robot and checked fleet-wide against duplicates
* real 311 filing needs profile.send_enabled + a city API key + the owner's YES
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..open311 import CONFIRM_TOKEN, Open311Client, Open311Error, ValidationError
from ..resolver import JurisdictionResolver, Resolution
from ..transit import TransitFeed
from .intent import Intent, IntentParser
from .matcher import ServiceMatcher
from .profile import RobotProfile
from .replies import FleetDuplicateGuard, Phraser
from .x_adapter import Mention, XAdapter


@dataclass
class RobotState:
    handled: List[str] = field(default_factory=list)
    opted_out: List[str] = field(default_factory=list)
    pending: Dict[str, dict] = field(default_factory=dict)   # user -> prepared request
    tracked: Dict[str, dict] = field(default_factory=dict)   # request_id -> {endpoint, status, mention_id, user}
    since_id: Optional[str] = None

    @classmethod
    def load(cls, path: Optional[Path]) -> "RobotState":
        if path and Path(path).exists():
            return cls(**json.loads(Path(path).read_text()))
        return cls()

    def save(self, path: Optional[Path]) -> None:
        if path:
            Path(path).write_text(json.dumps(asdict(self), indent=2))


@dataclass
class RobotAction:
    robot: str
    mention_id: str
    intent: Intent
    reply: Optional[str] = None
    resolution: Optional[Resolution] = None
    service: Optional[dict] = None
    prepared: Optional[dict] = None
    log: List[str] = field(default_factory=list)


class Robot:
    def __init__(self, profile: Optional[RobotProfile] = None, *, owner: Optional[str] = None,
                 resolver: Optional[JurisdictionResolver] = None, home_city: str = "",
                 allowlist: Optional[List[str]] = None, parser: Optional[IntentParser] = None,
                 matcher: Optional[ServiceMatcher] = None, state: Optional[RobotState] = None,
                 state_path: Optional[str] = None, send_enabled: bool = False,
                 api_keys: Optional[Dict[str, str]] = None, transit_feed: Optional[TransitFeed] = None,
                 transit_stop_id: Optional[str] = None, auto_status_updates: bool = False,
                 guard: Optional[FleetDuplicateGuard] = None):
        if profile is None:  # convenience for single-robot scripts/tests
            if not owner:
                raise ValueError("pass a RobotProfile or owner=")
            profile = RobotProfile(robot_handle=f"{owner.lstrip('@')}_robot", owner_handle=owner,
                                   home_city=home_city, allowlist=list(allowlist or []),
                                   send_enabled=send_enabled)
            profile.grant_consent(include_followups=auto_status_updates)
        self.profile = profile
        self.resolver = resolver or JurisdictionResolver()
        self.parser = parser or IntentParser()
        self.matcher = matcher or ServiceMatcher()
        self.state_path = state_path
        self.state = state or RobotState.load(Path(state_path) if state_path else None)
        self.api_keys = api_keys or {}
        self.transit_feed = transit_feed or (TransitFeed(profile.transit_feed_url, self.resolver.http)
                                             if profile.transit_feed_url else None)
        self.transit_stop_id = transit_stop_id or profile.transit_stop_id or None
        self.phrase = Phraser(profile.robot_id, guard)

    # convenience accessors (kept for older call sites)
    @property
    def owner(self) -> str:
        return self.profile.owner_handle.lower()

    @property
    def home_city(self) -> str:
        return self.profile.home_city

    def _save(self) -> None:
        self.state.save(Path(self.state_path) if self.state_path else None)

    # ------------------------------------------------------------------
    def handle(self, m: Mention) -> RobotAction:
        intent = self.parser.parse(m.text, m.lat, m.lng)
        act = RobotAction(self.profile.robot_id, m.id, intent)
        user = m.author.lower()
        if m.id in self.state.handled:
            act.log.append("already handled (one reply per interaction)")
            return act
        self.state.handled.append(m.id)
        if not self.profile.has_consent:
            act.log.append("ignored: owner has not given express consent for automated actions")
            return act
        if m.robot and m.robot.lower() != self.profile.robot_id:
            act.log.append(f"ignored: addressed to @{m.robot}, not @{self.profile.robot_handle}")
            return act
        if not self.profile.allowed(user):
            act.log.append(f"ignored: @{user} is not @{self.profile.robot_handle}'s owner/allowlist")
            return act
        if m.channel == "mention" and f"@{self.profile.robot_id}" not in m.text.lower():
            act.log.append("ignored: post does not @mention the robot (not 'summoned')")
            return act
        if user in self.state.opted_out:
            if intent.text.lower().strip() in {"start", "resume"}:
                self.state.opted_out.remove(user)
                act.reply = self.phrase.text("You're opted back in.")
            else:
                act.log.append("ignored: user opted out")
            self._save()
            return act

        handler = getattr(self, f"_on_{intent.kind}", self._on_help)
        handler(m, intent, act)
        self._save()
        return act

    def run_once(self, x: XAdapter) -> List[RobotAction]:
        actions = []
        for m in x.poll_mentions(self.state.since_id):
            if not m.robot:
                m.robot = self.profile.robot_id
            act = self.handle(m)
            if act.reply:
                x.post_reply(m.id, act.reply)
            self.state.since_id = m.id
            actions.append(act)
        self._save()
        return actions

    # ------------------------------------------------------------------
    def _locate(self, intent: Intent, act: RobotAction) -> Resolution:
        lat, lng = intent.lat, intent.lng
        if lat is None and not intent.location and self.profile.default_lat is not None:
            lat, lng = self.profile.default_lat, self.profile.default_lng
            act.log.append("no place given; using the owner's default location")
        if lat is not None:
            act.log.append(f"location from coordinates {lat},{lng}")
            return self.resolver.resolve_point(lat, lng)
        loc = self._full_address(intent.location)
        if not loc:
            return Resolution(None, None, None, "none", "no location given")
        act.log.append(f"geocoding {loc!r}")
        return self.resolver.resolve_address(loc)

    def _full_address(self, loc: str) -> str:
        if loc and self.home_city and "," not in loc:
            return f"{loc}, {self.home_city}"
        return loc

    def _city_label(self, res: Resolution, intent: Intent) -> str:
        if res.endpoint and res.endpoint.geo_scoped:
            loc = self._full_address(intent.location) or self.home_city
            hint = loc.split(",", 1)[1].strip(" ,") if "," in loc else ""
            return f"{hint} (SeeClickFix)" if hint else "SeeClickFix"
        return res.endpoint.name if res.endpoint else ""

    @staticmethod
    def _autofill(definition: Optional[dict], intent: Intent, act: RobotAction) -> Dict[str, Any]:
        """Fill required free-text attributes that ask for the location."""
        out: Dict[str, Any] = {}
        for attr in (definition or {}).get("attributes", []):
            desc = str(attr.get("description", "")).lower()
            if (attr.get("required") and attr.get("variable", True)
                    and attr.get("datatype") in ("string", "text") and intent.location
                    and any(k in desc for k in ("address", "intersection", "location", "street", "block"))):
                out[str(attr["code"])] = intent.location
                act.log.append(f"autofilled attribute {attr['code']} with the location")
        return out

    def _on_report(self, m: Mention, intent: Intent, act: RobotAction) -> None:
        res = self._locate(intent, act)
        act.resolution = res
        act.log.append(f"resolver: {res.method} - {res.reason}")
        if not res.found:
            act.reply = self.phrase.text(f"No city 311 API found for that spot ({res.reason[:90]}). "
                                         "Add the city or share a location?")
            return
        client = self.resolver.client_for(res)
        services = client.list_services(res.lat, res.lng)
        match = self.matcher.match(intent.issue, services)
        city = self._city_label(res, intent)
        if not match:
            act.reply = self.phrase.text(f"{city} 311 has {len(services)} request types but none fit "
                                         f"'{intent.issue[:60]}'. Can you rephrase?")
            return
        act.service = match.service
        act.log.append(f"matched service {match.service_code} '{match.service_name}' ({match.why})")
        definition = None
        if match.service.get("metadata"):
            try:
                definition = client.get_service_definition(match.service_code, res.lat, res.lng)
            except Exception as e:  # read-only best effort
                act.log.append(f"service definition unavailable: {e}")
        attributes = self._autofill(definition, intent, act)
        location_label = intent.location or (res.geocode.matched if res.geocode else f"{res.lat:.5f},{res.lng:.5f}")
        approx = bool(res.geocode and res.geocode.approximate)
        full_address = self._full_address(intent.location)
        if approx and res.endpoint.geo_scoped:
            approx = False  # SeeClickFix routes by lat/long, keep the (approximate) point
            act.log.append("location approximate (street centroid); kept lat/long for SeeClickFix routing + address_string")
        elif approx:
            act.log.append("location approximate (intersection); payload uses address_string only")
        try:
            prepared = client.create_request(
                match.service_code, dry_run=True,
                lat=None if approx and intent.location else res.lat,
                lng=None if approx and intent.location else res.lng,
                address_string=full_address or None,
                description=f"{intent.issue} (reported via civicbot by @{m.author})",
                attributes=attributes, definition=definition, known_services=services)
        except ValidationError as e:
            act.log.append(f"validation: {e.problems}")
            act.reply = self.phrase.text(f"{city} needs more info for '{match.service_name}': "
                                         f"{'; '.join(e.problems)[:120]}")
            return
        act.prepared = prepared.as_dict()
        self.state.pending[m.author.lower()] = {"mention_id": m.id, "endpoint": res.endpoint.id,
                                                "form": prepared.form, "service_name": match.service_name,
                                                "city": city, "location": location_label}
        act.reply = self.phrase.report(seed=m.id, service=match.service_name, city=city,
                                       location=location_label, dry_run=True)

    def _on_confirm(self, m: Mention, intent: Intent, act: RobotAction) -> None:
        pending = self.state.pending.get(m.author.lower())
        if not pending:
            act.reply = self.phrase.text("Nothing pending to file.")
            return
        key = self.api_keys.get(pending["endpoint"])
        if not (self.profile.send_enabled and key):
            act.log.append("send disabled - request NOT filed")
            act.reply = self.phrase.text(f"Sending is off for this robot, so '{pending['service_name']}' "
                                         "was not filed (needs send_enabled + a city API key).")
            return
        ep = self.resolver.registry.get(pending["endpoint"])
        client = Open311Client(ep, self.resolver.http)
        form = dict(pending["form"])
        code = form.pop("service_code")
        kw = {k: v for k, v in form.items() if k in {"lat", "address_string", "description"}}
        if "long" in form:
            kw["lng"] = form["long"]
        attrs = {k[len("attribute["):-1]: v for k, v in form.items() if k.startswith("attribute[")}
        try:
            sent = client.create_request(code, dry_run=False, confirm=CONFIRM_TOKEN, api_key=key,
                                         attributes=attrs, **kw)
        except Open311Error as e:
            act.reply = self.phrase.text(f"Filing failed: {e}"[:200])
            return
        resp = sent.response[0] if isinstance(sent.response, list) and sent.response else (sent.response or {})
        rid = str(resp.get("service_request_id") or resp.get("token") or "")
        self.state.tracked[rid] = {"endpoint": ep.id, "status": "open", "mention_id": pending["mention_id"],
                                   "user": m.author.lower(), "city": pending["city"], "filed_at": time.time()}
        del self.state.pending[m.author.lower()]
        act.reply = self.phrase.report(seed=m.id, service=pending["service_name"], city=pending["city"],
                                       location=pending["location"], dry_run=False, request_id=rid,
                                       followups=self.profile.status_updates)

    def _on_status(self, m: Mention, intent: Intent, act: RobotAction) -> None:
        rid = intent.request_id
        tracked = self.state.tracked.get(rid) if rid else None
        if not rid:
            act.reply = self.phrase.text("Which request? Reply 'status #<id>'.")
            return
        if not tracked:
            act.reply = self.phrase.text(f"I'm not tracking #{rid}.")
            return
        req = Open311Client(self.resolver.registry.get(tracked["endpoint"]), self.resolver.http).get_request(rid)
        if not req:
            act.reply = self.phrase.text(f"#{rid} not found at {tracked['endpoint']}.")
            return
        act.reply = self.phrase.status(seed=m.id, request_id=rid, status=req.get("status", "unknown"),
                                       notes=req.get("status_notes") or "", city=tracked.get("city", ""))

    def _on_updates(self, m: Mention, intent: Intent, act: RobotAction) -> None:
        if m.author.lower() != self.owner:
            act.reply = self.phrase.text("Only the robot's owner can change update settings.")
            return
        on = bool(intent.extra.get("on"))
        self.profile.status_updates = on
        if self.profile.consent is not None:
            from .profile import FOLLOWUP_ACTION
            acts = [a for a in self.profile.consent.get("actions", []) if a != FOLLOWUP_ACTION]
            self.profile.consent["actions"] = acts + ([FOLLOWUP_ACTION] if on else [])
        act.reply = self.phrase.text("Status follow-ups ON: I'll reply in-thread when a filed request changes."
                                     if on else "Status follow-ups OFF. Ask 'status #id' any time.")

    def _on_transit(self, m: Mention, intent: Intent, act: RobotAction) -> None:
        if not self.transit_feed:
            act.reply = self.phrase.text("No transit feed configured for this robot yet.")
            return
        arr = [a for a in self.transit_feed.arrivals(stop_id=self.transit_stop_id) if a.time][:3]
        if not arr:
            act.reply = self.phrase.text("No upcoming arrivals in the live feed.")
            return
        now = int(time.time())
        act.reply = self.phrase.text("Next: " + ", ".join(f"{a.route_id} in {max(0, (a.time - now) // 60)} min" for a in arr))

    def _on_stop(self, m: Mention, intent: Intent, act: RobotAction) -> None:
        u = m.author.lower()
        if u not in self.state.opted_out:
            self.state.opted_out.append(u)
        self.state.pending.pop(u, None)
        act.reply = self.phrase.text("Opted out. I won't reply again. Send START to resume.")

    def _on_help(self, m: Mention, intent: Intent, act: RobotAction) -> None:
        act.reply = self.phrase.text("Tell me a problem + place, e.g. 'pothole at 401 N Morton St'. "
                                     "Or 'status #123', 'next bus', 'updates on'. STOP to opt out.")

    # ------------------------------------------------------------------
    def poll_status_updates(self, x: Optional[XAdapter] = None) -> List[str]:
        """Check really-filed requests. Posts follow-ups only if the owner opted in ('updates on')."""
        out = []
        for rid, t in list(self.state.tracked.items()):
            if t["user"] in self.state.opted_out:
                continue
            req = Open311Client(self.resolver.registry.get(t["endpoint"]), self.resolver.http).get_request(rid)
            if req and req.get("status") and req["status"] != t["status"]:
                t["status"] = req["status"]
                text = self.phrase.status(seed=f"{rid}:{req['status']}", request_id=rid, status=req["status"],
                                          notes=req.get("status_notes") or "", city=t.get("city", ""))
                if x and self.profile.status_updates:
                    x.post_reply(t["mention_id"], text)
                out.append(text)
        self._save()
        return out
