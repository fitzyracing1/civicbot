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
import re
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
from ..skills import (BUILTIN_SKILLS, Catalog, CatalogSet, FetchBlocked, FetchError, SafeFetcher, SkillInputError,
                      SkillRouter, SkillRunner, SpecError, default_catalog, is_free, usage_check, validate_spec)
from ..secrets import InMemorySecretStore, SecretStore

MAX_SKILLS = 25
CMD_INSTALL = re.compile(r"^(?:learn|install|add (?:api|skill))\s+(?P<arg>\S+)\s*$", re.I)
CMD_REMOVE = re.compile(r"^(?:forget|uninstall|remove (?:api|skill))\s+(?P<arg>[a-z0-9-]+)\s*$", re.I)
CMD_LIST = re.compile(r"^(?:skills|list skills|my skills|what can you do)\??$", re.I)
CMD_ENABLE = re.compile(r"^(?P<op>enable|disable) skill\s+(?P<arg>[a-z0-9-]+)\s*$", re.I)


FREE_ENV = "CIVICBOT_FREE"


def free_mode(profile: Optional[RobotProfile] = None) -> bool:
    """Free mode is on when the profile's plan is 'free' or CIVICBOT_FREE=1 is set."""
    import os
    if profile is not None and getattr(profile, "plan", "") == "free":
        return True
    return os.environ.get(FREE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def skill_allowed_in_free_mode(spec: dict) -> bool:
    if spec.get("handler"):
        return True  # built-ins: 311 (dry-run in free mode), status, transit
    return str(spec.get("_source", "catalog:")).startswith("catalog:") and is_free(spec)


@dataclass
class RobotState:
    handled: List[str] = field(default_factory=list)
    opted_out: List[str] = field(default_factory=list)
    pending: Dict[str, dict] = field(default_factory=dict)   # user -> prepared request
    tracked: Dict[str, dict] = field(default_factory=dict)   # request_id -> {endpoint, status, mention_id, user}
    since_id: Optional[str] = None
    skill_usage: Dict[str, dict] = field(default_factory=dict)  # per-skill rate-limit counters

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
    skill: Optional[str] = None


class Robot:
    def __init__(self, profile: Optional[RobotProfile] = None, *, owner: Optional[str] = None,
                 resolver: Optional[JurisdictionResolver] = None, home_city: str = "",
                 allowlist: Optional[List[str]] = None, parser: Optional[IntentParser] = None,
                 matcher: Optional[ServiceMatcher] = None, state: Optional[RobotState] = None,
                 state_path: Optional[str] = None, send_enabled: bool = False,
                 api_keys: Optional[Dict[str, str]] = None, transit_feed: Optional[TransitFeed] = None,
                 transit_stop_id: Optional[str] = None, auto_status_updates: bool = False,
                 guard: Optional[FleetDuplicateGuard] = None, fetcher: Optional[SafeFetcher] = None,
                 secrets: Optional[SecretStore] = None, catalog: Optional[Catalog] = None,
                 on_profile_change=None, free: Optional[bool] = None):
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
        self.fetcher = fetcher or SafeFetcher()
        self.secrets = secrets or InMemorySecretStore()
        self.catalog = catalog or default_catalog()
        # Free mode (v0.4): only free, keyless catalog skills; 311 stays dry-run; write skills can't be enabled.
        self.free = free_mode(profile) if free is None else bool(free)
        self.router = SkillRouter()
        self.on_profile_change = on_profile_change or (lambda p: None)
        self.runner = SkillRunner(self.fetcher, self.resolver.geocoder,
                                  lambda ref: self.secrets.get(self.profile.robot_id, ref))

    # -- skills ---------------------------------------------------------------------------
    def skills(self) -> List[dict]:
        """Built-ins first (unless the owner removed them), then the owner's installed skills."""
        b = [s for n, s in BUILTIN_SKILLS.items() if n not in self.profile.disabled_builtins]
        user = list(self.profile.skills.values())
        if self.free:
            user = [s for s in user if skill_allowed_in_free_mode(s)]
        return b + user

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

        body = self.parser.clean(m.text)
        if self._manage(m, body, act):
            self._save()
            return act
        if intent.kind in ("stop", "confirm", "updates"):
            getattr(self, f"_on_{intent.kind}")(m, intent, act)
            self._save()
            return act
        route = self.router.route(body, intent.kind, self.skills(), transit_available=self.transit_feed is not None)
        if route is None:
            self._on_help(m, intent, act)
        else:
            act.skill = route.skill["name"]
            act.log.append(f"skill: {route.skill['name']} ({route.why})")
            h = route.skill.get("handler")
            if h:
                getattr(self, "_on_" + h.split(":", 1)[1])(m, intent, act)
            else:
                self._run_skill(route.skill, m, body, act)
        self._save()
        return act

    def _manage(self, m: Mention, body: str, act: RobotAction) -> bool:
        """Owner-only skill management. Returns True if the message was a management command."""
        low = body.strip()
        mi, mr, ml, me = CMD_INSTALL.match(low), CMD_REMOVE.match(low), CMD_LIST.match(low), CMD_ENABLE.match(low)
        if not (mi or mr or ml or me):
            return False
        act.intent.kind = "manage"
        if ml:
            names = [s["name"] + ("*" if s.get("kind") == "write" and not s.get("handler")
                                  and s["name"] not in self.profile.write_enabled else "")
                     for s in self.skills()]
            act.reply = self.phrase.text("Skills: " + ", ".join(names) + ". (* = write, dry-run)")
            return True
        if m.author.lower() != self.owner:
            act.log.append(f"refused: only @{self.profile.owner_handle} can change this robot's skills")
            act.reply = self.phrase.text(f"Only @{self.profile.owner_handle} can change my skills.".replace("@", ""))
            return True
        if mi:
            self._install(mi.group("arg"), m, act)
        elif mr:
            name = mr.group("arg").lower()
            if name in self.profile.skills:
                del self.profile.skills[name]
                if name in self.profile.write_enabled:
                    self.profile.write_enabled.remove(name)
                act.reply = self.phrase.text(f"Forgot skill '{name}'.")
            elif name in BUILTIN_SKILLS and name not in self.profile.disabled_builtins:
                self.profile.disabled_builtins.append(name)
                act.reply = self.phrase.text(f"Turned off built-in '{name}'. 'learn {name}' turns it back on.")
            else:
                act.reply = self.phrase.text(f"I don't have a skill called '{name}'.")
            self.on_profile_change(self.profile)
        else:
            name, on = me.group("arg").lower(), me.group("op").lower() == "enable"
            spec = self.profile.skills.get(name)
            if not spec or spec.get("kind") != "write":
                act.reply = self.phrase.text(f"'{name}' isn't an installed write skill.")
            elif on and self.free:
                act.reply = self.phrase.text(f"Free mode: write skills stay dry-run, so '{name}' can't be enabled.")
            else:
                if on and name not in self.profile.write_enabled:
                    self.profile.write_enabled.append(name)
                if not on and name in self.profile.write_enabled:
                    self.profile.write_enabled.remove(name)
                act.reply = self.phrase.text(f"'{name}' will {'send real requests (after your YES each time)' if on else 'stay dry-run'}.")
                self.on_profile_change(self.profile)
        return True

    def _install(self, arg: str, m: Mention, act: RobotAction) -> None:
        name = arg.lower()
        if name in BUILTIN_SKILLS:
            if name in self.profile.disabled_builtins:
                self.profile.disabled_builtins.remove(name)
                self.on_profile_change(self.profile)
            act.reply = self.phrase.text(f"Built-in '{name}' is on.")
            return
        if self.free and (re.match(r"^https?://", arg, re.I) or name not in self.catalog.names()):
            act.log.append(f"free mode: refused install of {arg[:60]!r} (free mode learns free catalog skills only)")
            act.reply = self.phrase.text("Free mode only learns skills from the civicbot catalog that are free and need "
                                         "no key. Say 'skills' to see what I know.")
            return
        try:
            if re.match(r"^https?://", arg, re.I):
                url = arg
                if re.match(r"^https?://t\.co/", arg, re.I) and m.urls:
                    url = m.urls[0]  # X shortens links; the API gives us the expanded URL
                    act.log.append(f"expanded {arg} -> {url}")
                spec = validate_spec(self.fetcher.get_spec(url))
                source = url
            else:
                spec, source = self.catalog.get(name), f"catalog:{name}"
        except KeyError:
            act.reply = self.phrase.text(f"No catalog skill '{name[:40]}'. Try 'skills' or a link to a spec.")
            return
        except SpecError as e:
            act.log.append(f"spec rejected: {e.problems}")
            act.reply = self.phrase.text(f"Can't learn that spec: {e.problems[0][:150]}")
            return
        except (FetchBlocked, FetchError) as e:
            act.log.append(f"spec fetch refused/failed: {e}")
            act.reply = self.phrase.text(f"Couldn't fetch that spec ({str(e)[:120]}).")
            return
        if spec["name"] in BUILTIN_SKILLS:
            act.reply = self.phrase.text("That name is reserved for a built-in skill.")
            return
        if self.free and not (source.startswith("catalog:") and is_free(spec)):
            act.log.append(f"free mode: refused {spec['name']} from {source} (cost={spec.get('cost', 'unknown')}, "
                           f"auth={(spec.get('auth') or {}).get('type', 'none')})")
            act.reply = self.phrase.text(f"Free mode only learns catalog skills marked free with no key; "
                                         f"'{spec['name'][:40]}' isn't one. Try 'skills' or a free catalog skill.")
            return
        if spec["name"] not in self.profile.skills and len(self.profile.skills) >= MAX_SKILLS:
            act.reply = self.phrase.text(f"I already know {MAX_SKILLS} skills; forget one first.")
            return
        updated = spec["name"] in self.profile.skills
        spec = dict(spec, _source=source, _installed_at=time.time())
        self.profile.skills[spec["name"]] = spec
        self.on_profile_change(self.profile)
        act.log.append(f"installed {spec['name']} from {source} (kind={spec['kind']}, domains={spec['allowed_domains']})")
        extra = " It's a write skill, so it stays dry-run until you 'enable skill " + spec["name"] + "'." \
            if spec["kind"] == "write" else ""
        hint = spec["triggers"].get("phrases", spec["triggers"]["keywords"])[0]
        title = spec.get("title", spec["description"])[:90]
        verb = "Updated" if updated else "Learned"
        act.reply = self.phrase.choose("learn", [
            f"{verb} '{spec['name']}': {title}. Try: '{hint}'.{extra}",
            f"{verb} a skill: {title} ('{spec['name']}'). Ask me '{hint}'.{extra}",
            f"New skill {verb.lower()}: '{spec['name']}' ({title}). Say '{hint}' to use it.{extra}"], m.id)

    def _run_skill(self, spec: dict, m: Mention, body: str, act: RobotAction) -> None:
        try:
            ctx = self.runner.context(spec, body, home_city=self.home_city, default_lat=self.profile.default_lat,
                                      default_lng=self.profile.default_lng, lat=m.lat, lng=m.lng)
            if spec["kind"] == "write":
                call = self.runner.build(spec, ctx)
                act.prepared = {k: v for k, v in call.items() if k != "headers"}
                host = call["url"].split("/")[2]
                if spec["name"] not in self.profile.write_enabled:
                    act.log.append("write skill not enabled -> dry-run, nothing sent")
                    act.reply = self.phrase.text(f"Dry run: '{spec['name']}' would {call['method']} to {host}. "
                                                 f"Not sent. Owner can 'enable skill {spec['name']}'.")
                    return
                self.state.pending[m.author.lower()] = {"type": "skill", "skill": spec["name"], "call": call,
                                                        "mention_id": m.id, "ctx": vars(ctx)}
                act.reply = self.phrase.text(f"Ready to {call['method']} to {host} via '{spec['name']}'. "
                                             "Reply YES to send, STOP to opt out.")
                return
            refusal = usage_check(self.state.skill_usage, spec)
            if refusal:
                act.reply = self.phrase.text(refusal)
                return
            options = self.runner.run_read(spec, ctx, act.log)
            act.reply = self.phrase.choose(spec["name"], options, m.id)
        except SkillInputError as e:
            act.reply = self.phrase.text(str(e))
        except FetchBlocked as e:
            act.log.append(f"blocked: {e}")
            act.reply = self.phrase.text(f"'{spec['name']}' was blocked by a safety rule.")
        except FetchError as e:
            act.log.append(f"fetch error: {e}")
            act.reply = self.phrase.text(f"'{spec['name']}' couldn't reach its API right now.")

    def _send_pending_skill(self, m: Mention, pending: dict, act: RobotAction) -> None:
        spec = self.profile.skills.get(pending["skill"])
        del self.state.pending[m.author.lower()]
        if not spec or spec["name"] not in self.profile.write_enabled:
            act.reply = self.phrase.text("That skill is no longer enabled; nothing sent.")
            return
        refusal = usage_check(self.state.skill_usage, spec)
        if refusal:
            act.reply = self.phrase.text(refusal)
            return
        from ..skills.runner import SkillContext
        ctx = SkillContext(**pending["ctx"])
        try:
            data = self.runner.execute(spec, pending["call"], act.log)
            act.reply = self.phrase.choose(spec["name"], self.runner.replies(spec, data, ctx), m.id)
        except (FetchBlocked, FetchError, SkillInputError) as e:
            act.log.append(f"send failed: {e}")
            act.reply = self.phrase.text(f"'{spec['name']}' failed: {str(e)[:120]}")

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
        if pending.get("type") == "skill":
            self._send_pending_skill(m, pending, act)
            return
        key = self.api_keys.get(pending["endpoint"])
        if not (self.profile.send_enabled and key) or self.free:
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
                                     "Also 'skills', 'learn <skill>', 'status #123'. STOP to opt out.")

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
