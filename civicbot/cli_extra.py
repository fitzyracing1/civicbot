"""v0.4 CLI additions (additive): `chat`, `apis`, `run`, and `connect --listen`.

  civicbot chat --free --city "Bloomington, IN"            # talk to a robot locally: no X account, no cost
  civicbot chat --offline -c "weather tomorrow"            # one question, recorded sample data, no network
  civicbot apis --category Transit                         # the verified free-API directory
  civicbot run --robot my_robot --owner me --state-dir .civicbot   # one poll of YOUR robot's X mentions (shadow)
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import List, Optional

CHAT_ROBOT, CHAT_OWNER = "yourrobot", "you"


# --- chat ---------------------------------------------------------------------------------------
def _chat_robot(a):
    from .resolver import JurisdictionResolver
    from .robot import Robot, RobotProfile
    from .skills import default_catalog, is_free
    if a.offline:
        from .offline import OfflineTransport, offline_skill_fetcher
        transport, fetcher = OfflineTransport(), offline_skill_fetcher()
    else:
        from .http import HttpTransport
        from .skills import SafeFetcher
        transport, fetcher = HttpTransport(), SafeFetcher()
    p = RobotProfile(robot_handle=CHAT_ROBOT, owner_handle=CHAT_OWNER, home_city=a.city or "",
                     plan="free" if a.free else "")
    if a.lat is not None and a.lng is not None:
        p.default_lat, p.default_lng = a.lat, a.lng
    p.grant_consent()  # you are the owner, chatting with your own local robot
    cat = default_catalog()
    want = a.skills or "all"
    names = cat.names() if want in ("all", "free") else [s.strip() for s in want.split(",") if s.strip()]
    for n in names:
        spec = cat.get(n)
        if (a.free or want == "free") and not is_free(spec):
            continue
        # A local chat robot knows every chosen catalog skill at once (on X a robot learns up to 25).
        p.skills[spec["name"]] = dict(spec, _source=f"catalog:{spec['name']}", _installed_at=time.time())
    return Robot(p, resolver=JurisdictionResolver(transport=transport), fetcher=fetcher, catalog=cat,
                 free=True if a.free else None)


def cmd_chat(a) -> int:
    from .robot.x_adapter import Mention
    robot = _chat_robot(a)
    mode = "FREE mode" if robot.free else "standard mode"
    data = "recorded sample data (offline)" if a.offline else "live free APIs"
    n = [0]

    def ask(line: str) -> str:
        n[0] += 1
        m = Mention(id=f"chat-{int(time.time())}-{n[0]}", author=CHAT_OWNER, text=f"@{CHAT_ROBOT} {line}",
                    robot=CHAT_ROBOT, lat=None, lng=None)
        act = robot.handle(m)
        if a.verbose:
            for x in act.log:
                print("   ·", x)
        return act.reply or "(no reply)"

    if a.c:
        for line in a.c:
            print(f"you> {line}\n@{CHAT_ROBOT}> {ask(line)}")
        return 0
    print(f"civicbot chat: @{CHAT_ROBOT}, {mode}, {len(robot.profile.skills)} skills, {data}. "
          "Nothing is posted to X and no 311 request is ever filed. Type 'skills', 'help', or 'quit'.")
    if not (robot.profile.home_city or robot.profile.default_lat is not None):
        print("Tip: add --city \"Your City, ST\" so weather/air/sun questions know where you are.")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.lower() in ("quit", "exit", ":q"):
            return 0
        print(f"@{CHAT_ROBOT}> {ask(line)}")


# --- free API directory --------------------------------------------------------------------------
def load_free_apis() -> dict:
    from importlib import resources
    return json.loads(resources.files("civicbot").joinpath("data/free_apis.json").read_text("utf-8"))


def cmd_apis(a) -> int:
    d = load_free_apis()
    q = (a.search or "").lower()
    rows = [x for x in d["apis"]
            if (not a.category or a.category.lower() in x["category"].lower())
            and (not q or q in json.dumps(x, ensure_ascii=False).lower())
            and (not a.cors or x.get("cors"))
            and (not a.no_key or x["auth"] == "none")]
    if a.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return 0
    print(f"{len(rows)} of {d['count']} free APIs (each verified live on {d['generated']}); categories: "
          f"{', '.join(d['categories'])}\n")
    for x in rows:
        skills = f"  -> learn {', '.join(x['skills'])}" if x.get("skills") else ""
        print(f"{x['name']}  [{x['category']}; {'no key' if x['auth'] == 'none' else 'free key'}"
              f"{'; CORS' if x.get('cors') else ''}]\n    {x['answers']}\n    {x['base_url']}  docs: {x['docs']}{skills}")
    return 0


# --- run your own robot (one poll) ---------------------------------------------------------------
class ShadowAdapter:
    """Reads the robot's real mentions but only PRINTS replies (default for `civicbot run`)."""

    def __init__(self, inner):
        self.inner, self.outbox = inner, []

    def poll_mentions(self, since_id: Optional[str] = None):
        return self.inner.poll_mentions(since_id)

    def post_reply(self, in_reply_to_id: str, text: str) -> str:
        self.outbox.append({"in_reply_to": in_reply_to_id, "text": text})
        return f"shadow-{in_reply_to_id}"


def _oauth_from_env(redirect_uri: str = "http://127.0.0.1:8765/callback", client_id: str = ""):
    from .x.oauth import OAuthConfig, XOAuth2
    cid = client_id or os.environ.get("X_CLIENT_ID", "")
    if not cid:
        raise SystemExit("set X_CLIENT_ID (your own X app's OAuth 2.0 client id; X_CLIENT_SECRET too if confidential)")
    return XOAuth2(OAuthConfig(client_id=cid, client_secret=os.environ.get("X_CLIENT_SECRET") or None,
                               redirect_uri=os.environ.get("X_REDIRECT_URI", redirect_uri)))


def cmd_run(a) -> int:
    from .robot import Fleet, ProfileStore
    from .x.api import XApiV2Adapter
    from .x.tokens import EncryptedFileTokenStore
    os.makedirs(a.state_dir, exist_ok=True)
    profiles = ProfileStore(os.path.join(a.state_dir, "profiles.json"))
    p = profiles.get(a.robot)
    if p is None:
        raise SystemExit(f"@{a.robot} is not connected in {a.state_dir}; run `civicbot connect --listen` first")
    if a.free and p.plan != "free":
        p.plan = "free"
        profiles.put(p)
    tokens = EncryptedFileTokenStore(os.path.join(a.state_dir, "tokens.enc"))
    oauth = _oauth_from_env()
    adapters = {}

    def factory(prof):
        real = XApiV2Adapter(prof.robot_id, oauth, tokens, robot_user_id=prof.robot_user_id or None, enabled=True)
        return adapters.setdefault(prof.robot_id, real if a.post else ShadowAdapter(real))
    fleet = Fleet(profiles, factory, state_dir=a.state_dir, min_poll_interval=0)
    acts = fleet.run_once()
    mode = "POSTING" if a.post else "SHADOW (nothing posted)"
    print(f"civicbot run: @{p.robot_handle}, {mode}, free={'yes' if fleet.robot(p.robot_id).free else 'no'}, "
          f"{len(acts)} mention(s) handled")
    for act in acts:
        if a.verbose:
            for line in act.log:
                print("  -", line)
        if act.intent is None and act.log:
            print("  !", "; ".join(act.log)[:300])
    for ad in adapters.values():
        for post in getattr(ad, "outbox", []):
            print(f"  would reply to {post['in_reply_to']}: {post['text']}")
    return 0


def cmd_connect_listen(a) -> int:
    """Local OAuth callback on 127.0.0.1 (no hosting needed): open the URL as the ROBOT, we catch the code."""
    import http.server
    import urllib.parse
    import webbrowser
    from .robot import ProfileStore
    from .robot.profile import CONSENT_ACTIONS
    from .x.connect import finish_connect
    from .x.tokens import EncryptedFileTokenStore
    port = a.port
    oauth = _oauth_from_env(f"http://127.0.0.1:{port}/callback", getattr(a, "client_id", "") or "")
    os.makedirs(a.state_dir, exist_ok=True)
    tokens = EncryptedFileTokenStore(os.path.join(a.state_dir, "tokens.enc"))
    profiles = ProfileStore(os.path.join(a.state_dir, "profiles.json"))
    print(f"Connect robot @{a.robot.lstrip('@')} (owner @{a.owner.lstrip('@')}). The owner agrees that civicbot will:")
    for x in CONSENT_ACTIONS:
        print(f"  * {x}")
    if not a.consent:
        if input("Type YES to agree: ").strip().upper() != "YES":
            print("Not connected (no consent).")
            return 1
    url, pending = oauth.start(robot_hint=a.robot.lstrip("@"), owner_hint=a.owner.lstrip("@"))
    result: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            try:
                prof = finish_connect(oauth, tokens, profiles, state=q.get("state", ""), code=q.get("code", ""),
                                      consent_accepted=True, home_city=a.home_city or "")
                if a.free:
                    prof.plan = "free"
                    profiles.put(prof)
                result["ok"], msg = prof.robot_handle, f"Connected @{prof.robot_handle}. You can close this tab."
            except Exception as e:  # noqa: BLE001
                result["err"], msg = str(e)[:200], f"Not connected: {str(e)[:200]}"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())

        def log_message(self, *args):  # keep the code out of logs
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    srv.timeout = 300
    print(f"\nLog in to X AS THE ROBOT ACCOUNT, then open:\n\n{url}\n\nWaiting on http://127.0.0.1:{port}/callback ...")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    srv.handle_request()
    srv.server_close()
    if "ok" in result:
        print(f"Connected @{result['ok']}. Encrypted token saved to {a.state_dir}/tokens.enc (key: CIVICBOT_TOKEN_KEY).")
        return 0
    print(f"Not connected: {result.get('err', 'timed out')}")
    return 1


def register(sub) -> None:
    ch = sub.add_parser("chat", help="talk to a robot in your terminal (no X account, nothing posted, free)")
    ch.add_argument("-c", action="append", help="ask one question and exit (repeatable)")
    ch.add_argument("--free", action="store_true", help="free mode: only free keyless catalog skills, 311 dry-run")
    ch.add_argument("--city", default="", help="home city, e.g. 'Bloomington, IN'")
    ch.add_argument("--lat", type=float); ch.add_argument("--lng", type=float)
    ch.add_argument("--skills", default="all", help="'all' (default), 'free', or a comma list of catalog skills")
    ch.add_argument("--offline", action="store_true", help="recorded sample responses, no network")
    ch.add_argument("-v", "--verbose", action="store_true")
    ch.set_defaults(fn=cmd_chat)
    ap = sub.add_parser("apis", help="the verified free-API directory (also on the GitHub Pages site)")
    ap.add_argument("--category"); ap.add_argument("--search"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--cors", action="store_true", help="only browser-callable (CORS) APIs")
    ap.add_argument("--no-key", action="store_true", help="only APIs that need no key at all")
    ap.set_defaults(fn=cmd_apis)
    r = sub.add_parser("run", help="poll YOUR robot's X mentions once and reply (shadow by default)")
    r.add_argument("--robot", required=True); r.add_argument("--state-dir", default=".civicbot")
    r.add_argument("--free", action="store_true"); r.add_argument("--post", action="store_true",
                                                                  help="really post replies (default: shadow, print only)")
    r.add_argument("--once", action="store_true", help="(default) one poll then exit; for cron / GitHub Actions")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(fn=cmd_run)
