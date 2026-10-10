"""civicbot CLI.

  python -m civicbot simulate --demo --offline
  python -m civicbot simulate --robot joshs_robot:joshua:"Bloomington, IN" "joshua> @joshs_robot pothole at 401 N Morton St"
  python -m civicbot connect --robot joshs_robot --owner joshua --client-id ID --redirect-uri https://example.org/cb
  python -m civicbot simulate --offline "@robot streetlight out" --lat 39.1696 --lng -86.5362
  python -m civicbot endpoints
  python -m civicbot services bloomington-in
  python -m civicbot resolve "1 City Hall Sq, Boston, MA"
  python -m civicbot transit https://example.com/gtfs-rt/tripupdates --stop 123
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .http import HttpTransport
from .registry import Registry
from .resolver import JurisdictionResolver
from .open311 import Open311Client


def _print(title: str, obj) -> None:
    print(f"\n== {title}")
    print(obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str))


def _parse_robot_spec(spec: str):
    """'@joshs_robot:joshua:Bloomington, IN' -> (robot, owner, home_city)."""
    parts = spec.split(":", 2)
    robot = parts[0].lstrip("@")
    owner = (parts[1] if len(parts) > 1 and parts[1] else "").lstrip("@")
    city = parts[2] if len(parts) > 2 else ""
    return robot, owner, city


def _parse_msg(msg: str, default_author: str, default_robot: str):
    """'ana> @ana_robot pothole at ...' -> ('ana', text). Missing @robot gets the default prepended."""
    author, text = default_author, msg
    if ">" in msg.split("@", 1)[0]:
        author, text = (x.strip() for x in msg.split(">", 1))
    if "@" not in text.split(" ", 1)[0]:
        text = f"@{default_robot} {text}"
    return author.lstrip("@"), text


DEMO = {
    "robots": ["joshs_robot:joshua:Bloomington, IN", "anas_robot:ana:New Haven, CT"],
    "msgs": ["joshua> @joshs_robot streetlight out at 401 N Morton St",
             "ana> @anas_robot pothole at Chapel St & College St",
             "randomuser> @joshs_robot pothole at 401 N Morton St",
             "joshua> @joshs_robot YES",
             "ana> @anas_robot STOP"],
}


DEMO_SKILLS = {
    "robots": ["joshs_robot:joshua:Bloomington, IN", "anas_robot:ana:New Haven, CT"],
    "msgs": ["joshua> @joshs_robot skills",
             "joshua> @joshs_robot learn open-meteo-weather",
             "joshua> @joshs_robot what's the weather?",
             "ana> @anas_robot learn open-meteo-weather",
             "ana> @anas_robot weather",
             "joshua> @joshs_robot learn mbta-next-trains",
             "joshua> @joshs_robot next train at place-pktrm",
             "randomuser> @joshs_robot learn https://evil.example/spec.json",
             "joshua> @joshs_robot learn https://localhost/spec.json",
             "joshua> @joshs_robot streetlight out at 401 N Morton St",
             "joshua> @joshs_robot forget mbta-next-trains",
             "joshua> @joshs_robot skills"],
}


def cmd_simulate(a) -> int:
    from .robot import Fleet, ProfileStore, RobotProfile, StubXAdapter
    transport: HttpTransport
    if a.offline:
        from .offline import OfflineTransport
        transport = OfflineTransport()
    else:
        transport = HttpTransport()
    demo = DEMO_SKILLS if a.demo == "skills" else DEMO if a.demo else None
    specs = a.robot or (demo["robots"] if demo else [])
    msgs = list(a.text or []) + (a.then or []) + (demo["msgs"] if demo and not a.text else [])
    if a.offline:
        from .offline import offline_skill_fetcher
        fetcher = offline_skill_fetcher()
    else:
        from .skills import SafeFetcher
        fetcher = SafeFetcher()
    if not specs:
        owner = (a.owner or a.user).lstrip("@")
        specs = [f"{owner}_robot:{owner}:{a.home_city}"]
    store = ProfileStore()
    for spec in specs:
        robot, owner, city = _parse_robot_spec(spec)
        p = RobotProfile(robot_handle=robot, owner_handle=owner or (a.owner or a.user), home_city=city or a.home_city)
        p.grant_consent()  # simulated connect: owner accepted the consent screen
        store.put(p)
    adapters = {}
    fleet = Fleet(store, lambda p: adapters.setdefault(p.robot_id, StubXAdapter(robot=p.robot_id)),
                  resolver=JurisdictionResolver(transport=transport), min_poll_interval=0, fetcher=fetcher)
    first = store.all()[0]
    print("robots:", ", ".join(f"@{p.robot_handle} (owner @{p.owner_handle}, {p.home_city or 'no home city'})"
                               for p in store.all()))
    for i, raw in enumerate(msgs):
        author, text = _parse_msg(raw, first.owner_handle, first.robot_handle)
        targets = [p for p in store.all() if f"@{p.robot_id}" in text.lower()]
        for p in targets:
            m = fleet.adapter(p.robot_id).add_mention(author, text, lat=a.lat if i == 0 else None,
                                                     lng=a.lng if i == 0 else None)
            _print(f"mention {m.id} from @{author} -> @{p.robot_handle}", text)
        for act in fleet.run_once():
            if act.intent is None:
                print("  -", *act.log)
                continue
            print(f"  [@{act.robot}] intent={act.intent.kind}" + (f" skill={act.skill}" if act.skill else "")
                  + (f" issue={act.intent.issue!r} location={act.intent.location!r}" if act.intent.kind == "report" else ""))
            for line in act.log:
                print("  -", line)
            if act.resolution and act.resolution.endpoint:
                r = act.resolution
                print(f"  - jurisdiction: {r.endpoint.id} ({r.method}) at {r.lat},{r.lng}"
                      f"{' via ' + r.geocode.source if r.geocode else ''}")
            label = "DRY-RUN Open311 POST (not sent)" if act.skill == "city-311-report" else "DRY-RUN request (not sent)"
            if act.prepared and a.verbose:
                _print(label, act.prepared)
            elif act.prepared:
                print(f"  - {label}: {act.prepared.get('url')}")
            if act.reply:
                print(f"  REPLY from @{act.robot} ({len(act.reply)} chars): {act.reply}")
            elif act.intent is not None:
                print(f"  (no reply from @{act.robot})")
    print("\n== outboxes (what each robot account would post; nothing was sent to X)")
    for rid, x in adapters.items():
        for post in x.outbox:
            print(f"@{rid} -> reply to {post['in_reply_to']}: {post['text']}")
    return 0


def cmd_connect(a) -> int:
    """Print the X OAuth 2.0 PKCE authorization URL. Makes NO network calls."""
    import os
    from .robot.profile import CONSENT_ACTIONS, FOLLOWUP_ACTION
    from .x.oauth import DEFAULT_SCOPES, OAuthConfig, XOAuth2
    scopes = tuple(a.scopes.split()) if a.scopes else DEFAULT_SCOPES
    oauth = XOAuth2(OAuthConfig(client_id=a.client_id, redirect_uri=a.redirect_uri, scopes=scopes))
    url, pending = oauth.start(robot_hint=a.robot.lstrip("@"), owner_hint=a.owner.lstrip("@"))
    print(f"Connect robot @{a.robot.lstrip('@')} (owner @{a.owner.lstrip('@')}) to civicbot\n")
    print("Before authorizing, the owner must agree that civicbot will:")
    for x in CONSENT_ACTIONS + ((FOLLOWUP_ACTION,) if a.followups else ()):
        print(f"  * {x}")
    print("  You can opt out any time: reply STOP, or revoke access at x.com/settings/connected_apps.\n")
    print("1. Log in to X AS THE ROBOT ACCOUNT (not your personal account), then open:\n")
    print(url)
    print(f"\n2. X redirects to {a.redirect_uri}?state=...&code=... ; the code expires in 30 seconds,")
    print("   so your callback should call civicbot.x.finish_connect(...) right away; it stores the token in an")
    print("   EncryptedFileTokenStore (needs CIVICBOT_TOKEN_KEY).")
    print(f"\nscopes: {' '.join(scopes)}   state: {pending.state}")
    if a.pending_file:
        fd = os.open(a.pending_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(vars(pending), f)
        print(f"PKCE verifier saved (mode 600) to {a.pending_file}; it is not printed.")
    return 0


# --- skills & secrets -------------------------------------------------------------------------
def _home() -> str:
    import os
    return os.environ.get("CIVICBOT_HOME", os.path.expanduser("~/.civicbot"))


def _profiles(a):
    import os
    from .robot import ProfileStore
    os.makedirs(_home(), exist_ok=True)
    return ProfileStore(a.profiles or os.path.join(_home(), "profiles.json"))


def _get_profile(a, store):
    from .robot import RobotProfile
    p = store.get(a.robot)
    if p is None:
        if not a.owner:
            raise SystemExit(f"robot @{a.robot.lstrip('@')} is not set up here; pass --owner to create a local profile "
                             "(connect it to X later with `civicbot connect`)")
        p = RobotProfile(robot_handle=a.robot, owner_handle=a.owner, home_city=a.home_city or "")
        store.put(p)
    return p


def _load_any_spec(ref: str, fetcher=None):
    """catalog name | local .json/.yaml file | https URL -> validated spec."""
    import os
    from .skills import Catalog, SafeFetcher, load_spec_file, validate_spec
    if ref.startswith(("https://", "http://")):
        return validate_spec((fetcher or SafeFetcher()).get_spec(ref)), ref
    if os.path.exists(ref):
        return load_spec_file(ref), os.path.abspath(ref)
    return Catalog().get(ref), f"catalog:{ref}"


def cmd_skill(a) -> int:
    import time as _t
    from .skills import BUILTIN_SKILLS, Catalog, SpecError, from_openapi, load_spec_file
    try:
        if a.action == "catalog":
            cat = Catalog()
            for n in cat.names():
                e = cat.entry(n)
                print(f"{n:32} {e['kind']:5}  {', '.join(e['domains']):30} {e['review'].get('status')}  {e['title']}")
            return 0
        if a.action == "validate":
            spec = load_spec_file(a.ref)
            print(f"OK: {spec['name']} ({spec['kind']}, domains {spec['allowed_domains']})")
            return 0
        if a.action == "reindex":
            idx = Catalog.reindex(a.ref)
            print(f"indexed {len(idx['skills'])} specs in {a.ref}/index.json")
            return 0
        if a.action == "import-openapi":
            import json as _j
            from .skills import SafeFetcher
            if a.ref.startswith("https://"):
                doc = SafeFetcher().request("GET", a.ref, allowed_domains=[a.ref.split("/")[2]], max_bytes=2_000_000).data
            else:
                from .skills.spec import load_spec_text
                doc = load_spec_text(open(a.ref, encoding="utf-8").read(), a.ref)
            spec = from_openapi(doc, a.operation, name=a.name, keywords=a.keywords.split(",") if a.keywords else None,
                                server=a.server)
            out = _j.dumps(spec, indent=2, ensure_ascii=False)
            if a.output:
                open(a.output, "w", encoding="utf-8").write(out + "\n")
                print(f"wrote draft spec {spec['name']} to {a.output}; review triggers/replies, then `civicbot skill add {a.output}`")
            else:
                print(out)
            return 0
        if a.action == "test":
            from .geocode import Geocoder
            from .skills import SafeFetcher, SkillRunner
            spec, src = _load_any_spec(a.ref)
            runner = SkillRunner(SafeFetcher(), Geocoder() if a.live else None)
            ctx = runner.context(spec, a.text or spec["triggers"]["keywords"][0], home_city=a.home_city or "",
                                 lat=a.lat, lng=a.lng)
            call = runner.build(spec, ctx)
            print(f"skill {spec['name']} ({spec['kind']}) from {src}")
            print(f"request: {call['method']} {call['url']} params={call['params']}")
            if spec["kind"] == "write":
                print("write skill: never sent by `skill test` (dry-run)")
                return 0
            if not a.live:
                print("(add --live to call the API read-only)")
                return 0
            log = []
            for r in runner.run_read(spec, ctx, log):
                print(f"reply ({len(r)} chars): {r}")
            for line in log:
                print("  -", line)
            return 0
        store = _profiles(a)
        if a.action == "list":
            if not a.robot:
                for p in store.all():
                    print(f"@{p.robot_handle}: {', '.join(list(p.skills)) or '(built-ins only)'}")
                return 0
            p = _get_profile(a, store)
            for n, s in BUILTIN_SKILLS.items():
                print(f"{n:32} built-in {'(off)' if n in p.disabled_builtins else ''}")
            for n, s in p.skills.items():
                w = "" if s["kind"] == "read" else (" [write: ENABLED]" if n in p.write_enabled else " [write: dry-run]")
                print(f"{n:32} {s['kind']:5} {', '.join(s['allowed_domains'])}  from {s.get('_source')}{w}")
            return 0
        p = _get_profile(a, store)
        if a.action == "add":
            spec, src = _load_any_spec(a.ref)
            if spec["name"] in BUILTIN_SKILLS:
                raise SpecError(["name reserved for a built-in skill"])
            p.skills[spec["name"]] = dict(spec, _source=src, _installed_at=_t.time())
            store.put(p)
            print(f"@{p.robot_handle} learned {spec['name']} ({spec['kind']}; domains {spec['allowed_domains']})"
                  + ("; write skill stays dry-run until `civicbot skill enable`" if spec["kind"] == "write" else ""))
        elif a.action == "remove":
            if p.skills.pop(a.ref, None) is None:
                print(f"@{p.robot_handle} has no skill {a.ref}")
                return 1
            if a.ref in p.write_enabled:
                p.write_enabled.remove(a.ref)
            store.put(p)
            print(f"removed {a.ref} from @{p.robot_handle}")
        elif a.action in ("enable", "disable"):
            s = p.skills.get(a.ref)
            if not s or s["kind"] != "write":
                print(f"{a.ref} is not an installed write skill")
                return 1
            if a.action == "enable" and a.ref not in p.write_enabled:
                p.write_enabled.append(a.ref)
            if a.action == "disable" and a.ref in p.write_enabled:
                p.write_enabled.remove(a.ref)
            store.put(p)
            print(f"{a.ref}: {'ENABLED (each send still needs the owner YES)' if a.action == 'enable' else 'dry-run'}")
        return 0
    except SpecError as e:
        print("spec rejected:")
        for prob in e.problems:
            print("  -", prob)
        return 2
    except KeyError as e:
        print(str(e).strip("'\""))
        return 2


def cmd_secret(a) -> int:
    """Store an owner-provided API key for ONE robot, encrypted. The value is never printed."""
    import getpass
    import os
    import sys as _s
    from .secrets import EncryptedFileSecretStore
    store = EncryptedFileSecretStore(os.path.join(_home(), "secrets.enc"))
    rid = a.robot.lstrip("@").lower()
    if a.action == "set":
        value = getpass.getpass(f"value for {a.ref} (hidden): ") if _s.stdin.isatty() else _s.stdin.readline().strip()
        if not value:
            print("empty value; nothing stored")
            return 1
        store.put(rid, a.ref, value)
        print(f"stored secret '{a.ref}' for @{rid} (encrypted)")
    elif a.action == "list":
        print("\n".join(store.refs(rid)) or "(none)")
    elif a.action == "delete":
        store.delete(rid, a.ref)
        print(f"deleted '{a.ref}' for @{rid}")
    return 0


def cmd_endpoints(a) -> int:
    for e in Registry.load_default().all():
        print(f"{e.id:16} {e.name:55} {e.base_url}")
    return 0


def cmd_services(a) -> int:
    ep = Registry.load_default().get(a.endpoint)
    svcs = Open311Client(ep).list_services(a.lat, a.lng)
    for s in svcs:
        print(f"{str(s.get('service_code')):>10}  {s.get('service_name')}{'  [attrs]' if s.get('metadata') else ''}")
    print(f"\n{len(svcs)} services at {ep.name}")
    return 0


def cmd_resolve(a) -> int:
    r = JurisdictionResolver()
    res = r.resolve_point(a.lat, a.lng) if a.lat is not None else r.resolve_address(a.address)
    _print("resolution", {"endpoint": res.endpoint.id if res.endpoint else None, "method": res.method,
                          "reason": res.reason, "lat": res.lat, "lng": res.lng,
                          "geocoded": res.geocode.matched if res.geocode else None})
    return 0 if res.found else 1


def cmd_transit(a) -> int:
    from .transit import TransitFeed
    feed = TransitFeed(a.url)
    f = feed.fetch()
    arr = feed.arrivals(stop_id=a.stop, route_id=a.route, feed=f)[:10]
    _print("arrivals", [vars(x) for x in arr])
    _print("vehicles", len(feed.vehicles(feed=f)))
    return 0


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="civicbot")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("simulate", help="end-to-end robot flow with fake X adapters (never posts or files anything)")
    s.add_argument("text", nargs="*", help="mention(s): '[author>] @robot text'")
    s.add_argument("--robot", action="append", help="robot account 'handle[:owner[:home city]]' (repeatable)")
    s.add_argument("--owner", help="default owner for robots/messages")
    s.add_argument("--user", default="joshua", help="(legacy) same as --owner")
    s.add_argument("--home-city", default="", help="appended to locations without a city, e.g. 'Bloomington, IN'")
    s.add_argument("--lat", type=float)
    s.add_argument("--lng", type=float)
    s.add_argument("--then", action="append", help="follow-up mention(s), e.g. YES or STOP")
    s.add_argument("--demo", nargs="?", const="robots", choices=["robots", "skills"],
                   help="'robots': two users/robots/cities; 'skills': owners teach their robots catalog skills")
    s.add_argument("--offline", action="store_true", help="use bundled fixtures instead of the network")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_simulate)
    c = sub.add_parser("connect", help="print the X OAuth 2.0 PKCE URL for a robot account (no network)")
    c.add_argument("--robot", required=True); c.add_argument("--owner", required=True)
    c.add_argument("--client-id", required=True); c.add_argument("--redirect-uri", required=True)
    c.add_argument("--scopes", help="space-separated; default 'tweet.read tweet.write users.read offline.access'")
    c.add_argument("--followups", action="store_true", help="also ask consent for status follow-up replies")
    c.add_argument("--pending-file", help="save state+PKCE verifier here (mode 600) for the callback")
    c.set_defaults(fn=cmd_connect)
    sk = sub.add_parser("skill", help="teach a robot new API skills (catalog, file, URL, OpenAPI)")
    sk.add_argument("action", choices=["list", "catalog", "add", "remove", "enable", "disable", "test", "validate",
                                       "import-openapi", "reindex"])
    sk.add_argument("ref", nargs="?", default="", help="catalog name, spec file, https URL, or skill name")
    sk.add_argument("--robot", default=""); sk.add_argument("--owner", default="")
    sk.add_argument("--home-city", default=""); sk.add_argument("--profiles", default="")
    sk.add_argument("--text", default="", help="(test) the mention text to route/extract from")
    sk.add_argument("--lat", type=float); sk.add_argument("--lng", type=float)
    sk.add_argument("--live", action="store_true", help="(test) call the API for real; read skills only")
    sk.add_argument("--operation", default="", help="(import-openapi) operationId or 'GET /path'")
    sk.add_argument("--name"); sk.add_argument("--keywords"); sk.add_argument("--server"); sk.add_argument("-o", "--output")
    sk.set_defaults(fn=cmd_skill)
    se = sub.add_parser("secret", help="store an owner's API key for one robot (encrypted, never printed)")
    se.add_argument("action", choices=["set", "list", "delete"]); se.add_argument("ref", nargs="?", default="")
    se.add_argument("--robot", required=True); se.set_defaults(fn=cmd_secret)
    e = sub.add_parser("endpoints"); e.set_defaults(fn=cmd_endpoints)
    sv = sub.add_parser("services"); sv.add_argument("endpoint"); sv.add_argument("--lat", type=float)
    sv.add_argument("--lng", type=float); sv.set_defaults(fn=cmd_services)
    r = sub.add_parser("resolve"); r.add_argument("address", nargs="?"); r.add_argument("--lat", type=float)
    r.add_argument("--lng", type=float); r.set_defaults(fn=cmd_resolve)
    t = sub.add_parser("transit"); t.add_argument("url"); t.add_argument("--stop"); t.add_argument("--route")
    t.set_defaults(fn=cmd_transit)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
