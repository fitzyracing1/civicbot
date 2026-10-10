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


def cmd_simulate(a) -> int:
    from .robot import Fleet, ProfileStore, RobotProfile, StubXAdapter
    transport: HttpTransport
    if a.offline:
        from .offline import OfflineTransport
        transport = OfflineTransport()
    else:
        transport = HttpTransport()
    specs = a.robot or (DEMO["robots"] if a.demo else [])
    msgs = list(a.text or []) + (a.then or []) + (DEMO["msgs"] if a.demo and not a.text else [])
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
                  resolver=JurisdictionResolver(transport=transport), min_poll_interval=0)
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
            print(f"  [@{act.robot}] intent={act.intent.kind} issue={act.intent.issue!r} location={act.intent.location!r}")
            for line in act.log:
                print("  -", line)
            if act.resolution and act.resolution.endpoint:
                r = act.resolution
                print(f"  - jurisdiction: {r.endpoint.id} ({r.method}) at {r.lat},{r.lng}"
                      f"{' via ' + r.geocode.source if r.geocode else ''}")
            if act.prepared and a.verbose:
                _print("DRY-RUN Open311 POST (not sent)", act.prepared)
            elif act.prepared:
                print(f"  - DRY-RUN Open311 POST (not sent): {act.prepared.get('url')}")
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
    s.add_argument("--demo", action="store_true", help="two users, two robots, two cities")
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
