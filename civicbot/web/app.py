"""The signup site + owner dashboard (FastAPI, server-rendered HTML, no JavaScript).

Wizard: 1 sign in with your personal X account -> 2 create a robot account (checklist) ->
3 connect the robot (second OAuth, consent) -> 4 home city -> 5 skills -> 6 done.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select, text
from starlette.middleware.sessions import SessionMiddleware

from ..robot.profile import CONSENT_ACTIONS, CONSENT_VERSION, FOLLOWUP_ACTION, ProfileStore, RobotProfile
from ..skills import BUILTIN_SKILLS, SpecError
from ..robot.engine import MAX_SKILLS
from ..x.api import XApiV2Adapter
from ..x.connect import disconnect, finish_connect
from ..x.oauth import OAuthError
from ..x.tokens import InMemoryTokenStore
from .budget import PRICE_POST_READ, PRICE_REPLY, PRICE_USER_READ, utc_day
from .config import Settings
from .db import DevCode, EventRow, Owner, RobotRow, UsageRow
from .fakex import DEV_AUTHORIZE_PATH, add_mention, issue_code, posts_for
from .logs import log, setup_logging
from .security import (CsrfError, RateLimited, RateLimiter, SecurityHeaders, check_csrf, client_ip,
                       csrf_token)
from .services import Services, build_services
from .stores import NullProfileStore, OwnershipError, SqlProfileStore, profile_from_json, profile_to_json

logger = logging.getLogger("civicbot.web")
HERE = Path(__file__).parent
HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
STEPS = ["Sign in", "Robot account", "Connect robot", "Home city", "Skills", "Done"]


def _ago(ts: float) -> str:
    d = max(0, int(time.time() - ts))
    return "just now" if d < 60 else f"{d // 60} min ago" if d < 3600 else f"{d // 3600} h ago" if d < 86400 else f"{d // 86400} days ago"


class NeedLogin(Exception):
    pass


def create_app(settings: Optional[Settings] = None, services: Optional[Services] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    svc = services or build_services(settings)
    setup_logging()
    app = FastAPI(title="civicbot", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.svc, app.state.limiter = svc, RateLimiter()
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["ago"] = _ago
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.add_middleware(SecurityHeaders, hsts=settings.secure_cookies)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                       session_cookie="__Host-civicbot" if settings.secure_cookies else "civicbot_session",
                       max_age=14 * 24 * 3600, same_site="lax", https_only=settings.secure_cookies)
    s, sf = settings, svc.sf

    # ---- helpers ----------------------------------------------------------------------------
    def limit(request: Request, bucket: str, n: int) -> None:
        app.state.limiter.hit(f"{bucket}:{client_ip(request, s.trust_proxy)}", n)

    async def form_csrf(request: Request):
        form = await request.form()
        check_csrf(request, form, s.base_url)
        return form

    def flash(request: Request, msg: str, kind: str = "info") -> None:
        request.session.setdefault("flash", []).append([kind, msg])

    def owner_of(request: Request) -> Optional[Owner]:
        oid = request.session.get("owner_id")
        if not oid:
            return None
        with sf() as db:
            return db.get(Owner, oid)

    def need_owner(request: Request) -> Owner:
        o = owner_of(request)
        if not o:
            raise NeedLogin()
        return o

    def owned(owner: Owner, rid: str):
        with sf() as db:
            row = db.get(RobotRow, rid.lower())
        if not row or row.owner_id != owner.id:  # someone else's robot looks exactly like a missing one
            raise HTTPException(404)
        return row, profile_from_json(row.profile_json)

    def save_profile(owner: Owner, p: RobotProfile) -> None:
        SqlProfileStore(sf, bind_owner_id=owner.id).put(p)

    def event(rid: str, kind: str, summary: str) -> None:
        with sf() as db, db.begin():
            db.add(EventRow(robot_id=rid, kind=kind, summary=summary[:400]))

    def robots_of(owner: Owner):
        with sf() as db:
            return list(db.scalars(select(RobotRow).where(RobotRow.owner_id == owner.id).order_by(RobotRow.created_at)))

    def render(request: Request, name: str, status: int = 200, **ctx):
        o = ctx.pop("owner", None) or owner_of(request)
        base = {"request": request, "csrf": csrf_token(request), "owner": o, "dev": s.dev_mode,
                "flashes": request.session.pop("flash", []), "steps": STEPS, "step": ctx.pop("step", None),
                "settings": s}
        base.update(ctx)
        return templates.TemplateResponse(request, name, base, status_code=status)

    def go(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    # ---- errors -----------------------------------------------------------------------------
    @app.exception_handler(NeedLogin)
    async def _need_login(request: Request, exc: NeedLogin):
        return go("/start")

    @app.exception_handler(CsrfError)
    async def _csrf(request: Request, exc: CsrfError):
        log(logger, "csrf_rejected", level=logging.WARNING, path=request.url.path)
        return render(request, "error.html", 403, title="Request blocked",
                      message="This form expired or came from another site. Go back, reload the page and try again.")

    @app.exception_handler(RateLimited)
    async def _rl(request: Request, exc: RateLimited):
        log(logger, "rate_limited", level=logging.WARNING, path=request.url.path)
        r = render(request, "error.html", 429, title="Slow down",
                   message="Too many attempts from your connection. Wait a minute and try again.")
        r.headers["Retry-After"] = "60"
        return r

    @app.exception_handler(404)
    async def _nf(request: Request, exc):
        return render(request, "error.html", 404, title="Not found", message="That page or robot doesn't exist.")

    # ---- public pages ---------------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request):
        return render(request, "landing.html")

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        return render(request, "privacy.html")

    @app.get("/terms", response_class=HTMLResponse)
    def terms(request: Request):
        return render(request, "terms.html")

    @app.get("/healthz")
    def healthz(strict: int = 0):
        from .worker import HEARTBEAT_STALE_S, heartbeat_age
        try:
            with sf() as db:
                db.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        age = heartbeat_age(svc) if db_ok else None
        worker_ok = age is not None and age < max(HEARTBEAT_STALE_S, s.worker_tick_s * 4)
        body = {"status": "ok" if db_ok and (worker_ok or not strict) else "degraded", "db": db_ok,
                "worker": {"ok": worker_ok, "heartbeat_age_s": None if age is None else round(age, 1)},
                "dev_mode": s.dev_mode, "x_write_enabled": s.x_write_enabled or s.dev_mode}
        return JSONResponse(body, status_code=200 if body["status"] == "ok" else 503)

    # ---- step 1: owner sign-in ----------------------------------------------------------------
    @app.get("/start", response_class=HTMLResponse)
    def start(request: Request):
        o = owner_of(request)
        if o:
            return go("/dashboard" if robots_of(o) else "/setup/robot-account")
        return render(request, "start.html", step=1)

    @app.post("/auth/owner")
    async def auth_owner(request: Request):
        limit(request, "signup", s.signup_rate_limit)
        await form_csrf(request)
        url, pending = svc.oauth_owner.start()
        request.session["oauth"] = {"state": pending.state, "kind": "owner", "t": time.time()}
        log(logger, "owner_signin_started")
        return go(url)

    @app.get("/auth/x/callback")
    def callback(request: Request, state: str = "", code: str = "", error: str = ""):
        limit(request, "signup", s.signup_rate_limit)
        flow = request.session.pop("oauth", None) or {}
        expected = str(flow.get("state", ""))
        if not expected or not state or not secrets.compare_digest(state, expected):
            # state must match the one THIS browser started (login-CSRF / mix-up protection)
            log(logger, "oauth_state_mismatch", level=logging.WARNING)
            return render(request, "error.html", 400, title="Sign-in didn't match",
                          message="That sign-in link wasn't started from this browser, or it was already used. Please start again.",
                          retry="/start")
        oauth = svc.oauth_owner if flow.get("kind") == "owner" else svc.oauth_robot
        if error or not code:
            oauth.pending.pop(state, None)
            flash(request, "You cancelled on X, so nothing was connected.", "warn")
            return go("/start" if flow.get("kind") == "owner" else "/setup/connect")
        if flow.get("kind") == "owner":
            return _finish_owner(request, state, code)
        return _finish_robot(request, flow, state, code)

    def _finish_owner(request: Request, state: str, code: str):
        oauth = svc.oauth_owner
        try:
            token, _ = oauth.exchange(state, code)
            probe = InMemoryTokenStore()
            probe.put("owner-probe", token)
            me = XApiV2Adapter("owner-probe", oauth, probe, enabled=True).me()
            svc.budget.record("app", "signin_user_reads", 1, PRICE_USER_READ)
        except Exception as e:
            log(logger, "owner_signin_failed", level=logging.WARNING, error=str(e)[:200])
            return render(request, "error.html", 400, title="Couldn't sign you in",
                          message=f"X said: {str(e)[:160]}", retry="/start")
        try:  # we only needed to know who you are: give the token straight back
            oauth.revoke(token)
        except OAuthError as e:
            log(logger, "owner_token_revoke_failed", level=logging.WARNING, error=str(e)[:200])
        with sf() as db, db.begin():
            o = db.scalar(select(Owner).where(Owner.x_user_id == me["id"]))
            if o:
                o.handle, o.last_login_at = me["username"], time.time()
            else:
                o = Owner(x_user_id=me["id"], handle=me["username"])
                db.add(o)
            db.flush()
            oid = o.id
        request.session.clear()  # new session id/contents after login (no fixation)
        request.session["owner_id"] = oid
        csrf_token(request)
        log(logger, "owner_signed_in", owner_id=oid)
        flash(request, f"Signed in as @{me['username']}.")
        return go("/start")

    # ---- step 2: create the robot account -------------------------------------------------------
    CHECKS = [("separate", "I created a NEW X account just for my robot (not my personal account)."),
              ("bio", "Its bio says it's a bot run by me, e.g. \"Robot run by @me. Helps with 311 & city info.\""),
              ("automated", "On the robot account I turned on the Automated label with my personal account as the managing account."),
              ("password", "I can log in to the robot account (I know its password / have 2FA set up).")]

    @app.get("/setup/robot-account", response_class=HTMLResponse)
    def robot_account(request: Request):
        o = need_owner(request)
        return render(request, "robot_account.html", step=2, owner=o, checks=CHECKS,
                      robot_hint=request.session.get("robot_hint", ""))

    @app.post("/setup/robot-account")
    async def robot_account_post(request: Request):
        o = need_owner(request)
        limit(request, "signup", s.signup_rate_limit)
        form = await form_csrf(request)
        handle = str(form.get("robot_handle", "")).strip().lstrip("@")
        problems = []
        if not HANDLE_RE.match(handle):
            problems.append("Enter the robot's @handle (letters, numbers, underscores; up to 15).")
        elif handle.lower() == o.handle.lower():
            problems.append("That's your personal account. The robot needs its own, separate account.")
        missing = [label for key, label in CHECKS if form.get(key) != "on"]
        if missing:
            problems.append("Please finish every item on the checklist first.")
        if problems:
            return render(request, "robot_account.html", 400, step=2, owner=o, checks=CHECKS, robot_hint=handle,
                          problems=problems, ticked={k for k, _ in CHECKS if form.get(k) == "on"})
        request.session["robot_hint"] = handle
        return go("/setup/connect")

    # ---- step 3: connect the robot (second OAuth) -------------------------------------------------
    @app.get("/setup/connect", response_class=HTMLResponse)
    def connect_page(request: Request, robot: str = ""):
        o = need_owner(request)
        if robot and HANDLE_RE.match(robot.lstrip("@")):
            owned(o, robot.lstrip("@"))  # reconnecting: must be yours
            request.session["robot_hint"] = robot.lstrip("@")
        hint = request.session.get("robot_hint")
        if not hint:
            return go("/setup/robot-account")
        return render(request, "connect.html", step=3, owner=o, robot_hint=hint, actions=CONSENT_ACTIONS,
                      followup=FOLLOWUP_ACTION, consent_version=CONSENT_VERSION)

    @app.post("/setup/connect")
    async def connect_post(request: Request):
        o = need_owner(request)
        limit(request, "signup", s.signup_rate_limit)
        form = await form_csrf(request)
        hint = request.session.get("robot_hint", "")
        if not hint:
            return go("/setup/robot-account")
        if form.get("consent") != "on":
            return render(request, "connect.html", 400, step=3, owner=o, robot_hint=hint, actions=CONSENT_ACTIONS,
                          followup=FOLLOWUP_ACTION, consent_version=CONSENT_VERSION,
                          problems=["Your robot can't act until you agree to what it will do."])
        mine = {r.robot_id for r in robots_of(o)}
        if hint.lower() not in mine and len(mine) >= s.max_robots_per_owner:
            return render(request, "error.html", 400, title="Robot limit reached",
                          message=f"Each person can connect up to {s.max_robots_per_owner} robots.", retry="/dashboard")
        url, pending = svc.oauth_robot.start(robot_hint=hint, owner_hint=o.handle)
        request.session["oauth"] = {"state": pending.state, "kind": "robot", "t": time.time(),
                                    "followups": form.get("followups") == "on"}
        log(logger, "robot_connect_started", owner_id=o.id)
        return go(url)

    def _finish_robot(request: Request, flow: dict, state: str, code: str):
        o = owner_of(request)
        if not o:
            svc.oauth_robot.pending.pop(state, None)
            return go("/start")
        staged_tokens, staged_profiles = InMemoryTokenStore(), ProfileStore(None)
        try:  # the shared civicbot.x code: state check, code exchange, /users/me, consent recording
            p = finish_connect(svc.oauth_robot, staged_tokens, staged_profiles, state=state, code=code,
                               consent_accepted=True, followups=bool(flow.get("followups")))
            svc.budget.record("app", "connect_user_reads", 1, PRICE_USER_READ)
        except OAuthError as e:
            log(logger, "robot_connect_failed", level=logging.WARNING, owner_id=o.id, error=str(e)[:200])
            msg = str(e)
            m = re.match(r"authorized as @(\w+), expected robot @(\w+)", msg)
            if m:
                msg = (f"X says you approved as @{m.group(1)}, but this robot is @{m.group(2)}. Nothing was connected and "
                       f"that access was revoked. In X, switch to @{m.group(2)} (or use a private window signed in as "
                       f"the robot), then try again.")
            return render(request, "error.html", 400, title="Couldn't connect the robot", message=msg[:400],
                          retry="/setup/connect")
        token = staged_tokens.get(p.robot_id)

        def refuse(msg: str):
            try:
                svc.oauth_robot.revoke(token)
            except OAuthError:
                pass
            log(logger, "robot_connect_refused", level=logging.WARNING, owner_id=o.id, reason=msg[:120])
            return render(request, "error.html", 400, title="Couldn't connect the robot", message=msg, retry="/setup/connect")

        if p.robot_user_id == o.x_user_id:
            return refuse("That's your personal account. Sign in to X as the robot account (a private window helps) and try again.")
        with sf() as db:
            row = db.get(RobotRow, p.robot_id)
        if row and row.owner_id != o.id:
            return refuse(f"@{p.robot_handle} is already connected to someone else's civicbot. They have to disconnect it first.")
        mine = {r.robot_id for r in robots_of(o)}
        if not row and len(mine) >= s.max_robots_per_owner:
            return refuse(f"Each person can connect up to {s.max_robots_per_owner} robots.")
        if row:  # reconnect: keep the owner's settings, refresh identity + consent
            old = profile_from_json(row.profile_json)
            old.robot_handle, old.robot_user_id, old.consent, old.status_updates = p.robot_handle, p.robot_user_id, p.consent, p.status_updates
            old.connected_at = p.connected_at
            p = old
        else:
            p.disabled_builtins = ["gtfs-transit"]  # needs a transit feed; owners can't set one in the wizard yet
        p.owner_handle, p.owner_user_id = o.handle, o.x_user_id
        try:
            save_profile(o, p)
        except OwnershipError as e:
            return refuse(str(e))
        svc.tokens.put(p.robot_id, token)
        with sf() as db, db.begin():
            r = db.get(RobotRow, p.robot_id)
            r.status, r.last_error = "active", ""
        event(p.robot_id, "connected", f"Connected @{p.robot_handle} (consent {CONSENT_VERSION})")
        request.session.pop("robot_hint", None)
        log(logger, "robot_connected", owner_id=o.id, robot=p.robot_id)
        flash(request, f"Connected @{p.robot_handle}.")
        return go(f"/robots/{p.robot_id}/city" if not row else "/dashboard")

    # ---- step 4: home city -----------------------------------------------------------------
    @app.get("/robots/{rid}/city", response_class=HTMLResponse)
    def city(request: Request, rid: str):
        o = need_owner(request)
        row, p = owned(o, rid)
        return render(request, "city.html", step=4, owner=o, robot=p)

    @app.post("/robots/{rid}/city", response_class=HTMLResponse)
    async def city_check(request: Request, rid: str):
        o = need_owner(request)
        row, p = owned(o, rid)
        limit(request, "lookup", s.lookup_rate_limit)
        form = await form_csrf(request)
        place = str(form.get("place", "")).strip()[:120]
        if len(place) < 3:
            return render(request, "city.html", 400, step=4, owner=o, robot=p, problems=["Type a city and state, like \"Bloomington, IN\"."])
        try:
            res = svc.resolver.resolve_address(place)
        except Exception as e:
            log(logger, "city_lookup_failed", level=logging.WARNING, error=str(e)[:200])
            res = None
        if res is None or res.lat is None:
            return render(request, "city.html", 400, step=4, owner=o, robot=p, place=place,
                          problems=["We couldn't find that place. Try \"City, ST\"."])
        return render(request, "city.html", step=4, owner=o, robot=p, place=place, res=res)

    @app.post("/robots/{rid}/city/save")
    async def city_save(request: Request, rid: str):
        o = need_owner(request)
        row, p = owned(o, rid)
        form = await form_csrf(request)
        try:
            lat, lng = float(form.get("lat", "")), float(form.get("lng", ""))
            assert -90 <= lat <= 90 and -180 <= lng <= 180
        except (ValueError, AssertionError):
            raise HTTPException(400)
        p.home_city = str(form.get("place", "")).strip()[:120]
        p.default_lat, p.default_lng = round(lat, 4), round(lng, 4)  # ~10 m: a place, not a doorstep
        has311 = form.get("has311") == "1"
        for b in ("city-311-report", "city-311-status"):
            if has311 and b in p.disabled_builtins:
                p.disabled_builtins.remove(b)
            if not has311 and b not in p.disabled_builtins:
                p.disabled_builtins.append(b)
        save_profile(o, p)
        return go(f"/robots/{p.robot_id}/skills" if form.get("wizard") == "1" else "/dashboard")

    # ---- step 5: skills ----------------------------------------------------------------------
    def skill_rows(p: RobotProfile):
        builtins = [{"name": n, "title": sp["title"], "description": sp["description"], "kind": sp["kind"],
                     "on": n not in p.disabled_builtins,
                     "blocked": "needs a transit feed (not available in the wizard yet)" if n == "gtfs-transit" and not p.transit_feed_url else ""}
                    for n, sp in BUILTIN_SKILLS.items()]
        cat = []
        for n in svc.catalog.names():
            e = svc.catalog.entry(n)
            try:
                desc = svc.catalog.get(n).get("description", "")
            except SpecError:
                continue  # edited without re-review: hide
            cat.append({"name": n, "title": e.get("title", n), "description": desc, "kind": e["kind"],
                        "domains": e.get("domains", []), "review": (e.get("review") or {}).get("status", "unreviewed"),
                        "on": n in p.skills})
        return builtins, cat

    @app.get("/robots/{rid}/skills", response_class=HTMLResponse)
    def skills(request: Request, rid: str):
        o = need_owner(request)
        row, p = owned(o, rid)
        b, c = skill_rows(p)
        return render(request, "skills.html", step=5, owner=o, robot=p, builtins=b, catalog=c)

    @app.post("/robots/{rid}/skills")
    async def skills_post(request: Request, rid: str):
        o = need_owner(request)
        row, p = owned(o, rid)
        form = await form_csrf(request)
        chosen = set(form.getlist("skill"))
        for n in BUILTIN_SKILLS:
            if n == "gtfs-transit" and not p.transit_feed_url:
                continue
            if n in chosen and n in p.disabled_builtins:
                p.disabled_builtins.remove(n)
            elif n not in chosen and n not in p.disabled_builtins:
                p.disabled_builtins.append(n)
        for n in svc.catalog.names():
            if n in chosen and n not in p.skills and len(p.skills) < MAX_SKILLS:
                try:
                    p.skills[n] = svc.catalog.get(n)
                except SpecError:
                    continue
            elif n not in chosen and n in p.skills and n in svc.catalog.names():
                p.skills.pop(n)
        save_profile(o, p)
        event(p.robot_id, "settings", "Skills: " + (", ".join(sorted(p.skills)) or "built-ins only"))
        return go(f"/robots/{p.robot_id}/done" if form.get("wizard") == "1" else "/dashboard")

    # ---- step 6: done -------------------------------------------------------------------------
    def examples(p: RobotProfile):
        h, out = "@" + p.robot_handle, []
        place = p.home_city.split(",")[0] if p.home_city else "Main St"
        if "city-311-report" not in p.disabled_builtins:
            out.append((f"{h} pothole at {'401 N Morton St' if 'bloomington' in p.home_city.lower() else 'Main St & 1st Ave'}",
                        "prepares a 311 report for the right city and asks you to confirm"))
        if "city-311-status" not in p.disabled_builtins:
            out.append((f"{h} status #12345", "checks a request it filed"))
        for n, sp in p.skills.items():
            trig = (sp.get("triggers") or {})
            phrase = (trig.get("phrases") or trig.get("keywords") or [n])[0]
            out.append((f"{h} {phrase}" + (f" in {place}" if sp.get("location") == "required" else ""), sp.get("title", n)))
        out += [(f"{h} skills", "lists what it can do"), (f"{h} STOP", "it stops replying to you (START to resume)")]
        return out

    @app.get("/robots/{rid}/done", response_class=HTMLResponse)
    def done(request: Request, rid: str):
        o = need_owner(request)
        row, p = owned(o, rid)
        return render(request, "done.html", step=6, owner=o, robot=p, examples=examples(p))

    # ---- dashboard -----------------------------------------------------------------------------
    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        o = need_owner(request)
        from .worker import heartbeat_age
        age = heartbeat_age(svc)
        cards = []
        day = utc_day()
        with sf() as db:
            for row in robots_of(o):
                p = profile_from_json(row.profile_json)
                use = {u.metric: u for u in db.scalars(select(UsageRow).where(UsageRow.period == day, UsageRow.scope == row.robot_id))}
                evs = list(db.scalars(select(EventRow).where(EventRow.robot_id == row.robot_id).order_by(EventRow.id.desc()).limit(8)))
                cards.append({"row": row, "p": p, "events": evs,
                              "mentions": use["mentions"].count if "mentions" in use else 0,
                              "replies": use["replies"].count if "replies" in use else 0,
                              "cost": sum(u.cost_usd for u in use.values()),
                              "skills": [n for n in BUILTIN_SKILLS if n not in p.disabled_builtins] + sorted(p.skills),
                              "examples": examples(p),
                              "fake_posts": posts_for(sf, row.robot_id, 5) if s.dev_mode else []})
        return render(request, "dashboard.html", owner=o, cards=cards, worker_age=age,
                      prices={"read": PRICE_POST_READ, "user": PRICE_USER_READ, "reply": PRICE_REPLY})

    @app.post("/robots/{rid}/{action}")
    async def robot_action(request: Request, rid: str, action: str):
        o = need_owner(request)
        row, p = owned(o, rid)
        form = await form_csrf(request)
        if action == "pause":
            _status(rid, "paused")
            event(rid, "settings", "Paused by owner")
            flash(request, f"@{p.robot_handle} is paused. It won't read or reply until you resume.")
        elif action == "resume":
            if not svc.tokens.get(rid):
                flash(request, "Reconnect the robot first.", "warn")
                return go(f"/setup/connect?robot={rid}")
            _status(rid, "active")
            event(rid, "settings", "Resumed by owner")
            flash(request, f"@{p.robot_handle} is running again.")
        elif action == "sending":
            want = form.get("enable") == "1"
            if want and form.get("confirm") != "on":
                flash(request, "Tick the box to confirm you understand real 311 requests will be filed.", "warn")
                return go("/dashboard")
            p.send_enabled = want
            save_profile(o, p)
            event(rid, "settings", f"311 sending {'ON' if want else 'off'}")
            flash(request, "311 sending is ON: after you reply YES, your robot files real requests with the city."
                  if want else "311 sending is off (dry run).", "warn" if want else "info")
        elif action == "disconnect":
            _disconnect(request, rid)
            _status(rid, "disconnected")
            event(rid, "settings", "Disconnected: tokens revoked and deleted")
            flash(request, f"Disconnected @{p.robot_handle}. Its X access was revoked; your settings are kept.")
        elif action == "delete":
            if form.get("confirm_handle", "").strip().lstrip("@").lower() != rid:
                flash(request, "Type the robot's handle to confirm deletion.", "warn")
                return go("/dashboard")
            _delete_robot(request, rid)
            flash(request, f"Deleted @{p.robot_handle} and all its data from civicbot.")
        else:
            raise HTTPException(404)
        return go("/dashboard")

    def _status(rid: str, status: str) -> None:
        with sf() as db, db.begin():
            db.get(RobotRow, rid).status = status

    def _disconnect(request: Request, rid: str) -> None:
        try:
            disconnect(svc.oauth_robot, svc.tokens, NullProfileStore(), rid)  # revoke at X, then delete locally
        except OAuthError as e:
            log(logger, "revoke_failed", level=logging.WARNING, robot=rid, error=str(e)[:200])
            flash(request, "X didn't confirm the revoke. We deleted our copy of the tokens anyway; you can also remove "
                  "civicbot under Settings > Security and account access > Apps and sessions on the robot account.", "warn")

    def _delete_robot(request: Request, rid: str) -> None:
        _disconnect(request, rid)
        with sf() as db, db.begin():
            db.execute(delete(EventRow).where(EventRow.robot_id == rid))
            db.execute(delete(UsageRow).where(UsageRow.scope == rid))
            db.execute(delete(RobotRow).where(RobotRow.robot_id == rid))
        log(logger, "robot_deleted", robot=rid)

    # ---- account ----------------------------------------------------------------------------------
    @app.get("/account", response_class=HTMLResponse)
    def account(request: Request):
        o = need_owner(request)
        return render(request, "account.html", owner=o, robots=robots_of(o))

    @app.get("/account/export")
    def export(request: Request):
        o = need_owner(request)
        with sf() as db:
            rows = robots_of(o)
            data = {"owner": {"x_user_id": o.x_user_id, "handle": o.handle, "created_at": o.created_at},
                    "robots": [{"status": r.status, "profile": json.loads(r.profile_json),
                                "events": [{"ts": e.ts, "kind": e.kind, "summary": e.summary} for e in
                                           db.scalars(select(EventRow).where(EventRow.robot_id == r.robot_id))]} for r in rows],
                    "note": "OAuth tokens are never exported."}
        return Response(json.dumps(data, indent=2), media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=civicbot-my-data.json"})

    @app.post("/account/delete")
    async def account_delete(request: Request):
        o = need_owner(request)
        form = await form_csrf(request)
        if str(form.get("confirm", "")).strip() != "DELETE":
            flash(request, "Type DELETE to confirm.", "warn")
            return go("/account")
        for r in robots_of(o):
            _delete_robot(request, r.robot_id)
        with sf() as db, db.begin():
            db.execute(delete(Owner).where(Owner.id == o.id))
        log(logger, "owner_deleted", owner_id=o.id)
        request.session.clear()
        flash(request, "Your civicbot account and all robot data were deleted.")
        return go("/")

    @app.post("/logout")
    async def logout(request: Request):
        await form_csrf(request)
        request.session.clear()
        return go("/")

    # ---- dev mode only -------------------------------------------------------------------------------
    if s.dev_mode:
        @app.get(DEV_AUTHORIZE_PATH, response_class=HTMLResponse)
        def dev_authorize(request: Request, client_id: str = "", redirect_uri: str = "", state: str = "",
                          code_challenge: str = "", code_challenge_method: str = "", scope: str = ""):
            if client_id != s.x_client_id or redirect_uri != s.redirect_uri or code_challenge_method != "S256" or not code_challenge:
                return render(request, "error.html", 400, title="Fake X: bad authorize request",
                              message="client_id, redirect_uri (exact match) and an S256 code_challenge are required.")
            flow = request.session.get("oauth") or {}
            hint = request.session.get("robot_hint", "") if flow.get("kind") == "robot" else ""
            return render(request, "dev_authorize.html", q={"redirect_uri": redirect_uri, "state": state,
                          "code_challenge": code_challenge}, scopes=scope.split(), hint=hint, kind=flow.get("kind", "owner"))

        @app.post(DEV_AUTHORIZE_PATH)
        async def dev_authorize_post(request: Request):
            form = await form_csrf(request)
            ru, st = str(form.get("redirect_uri")), str(form.get("state"))
            if ru != s.redirect_uri:
                raise HTTPException(400)
            if form.get("action") != "approve":
                return go(ru + "?" + urlencode({"state": st, "error": "access_denied"}))
            user = str(form.get("username", "")).strip().lstrip("@")
            if not HANDLE_RE.match(user):
                raise HTTPException(400)
            code = issue_code(sf, user, str(form.get("code_challenge")), ru)
            return go(ru + "?" + urlencode({"state": st, "code": code}))

        @app.post("/dev/robots/{rid}/mention")
        async def dev_mention(request: Request, rid: str):
            o = need_owner(request)
            owned(o, rid)
            form = await form_csrf(request)
            author = str(form.get("author") or o.handle).strip().lstrip("@")[:15] or o.handle
            text_ = str(form.get("text", "")).strip()[:270]
            if text_:
                add_mention(sf, rid, author, f"@{rid} {text_}" if not text_.lower().startswith("@") else text_)
                flash(request, f"Fake X: @{author} mentioned @{rid}. Click 'Run the runner now' (or wait for the worker).")
            return go("/dashboard")

        @app.post("/dev/tick")
        async def dev_tick(request: Request):
            need_owner(request)
            await form_csrf(request)
            from .worker import tick
            acts = tick(svc)
            flash(request, f"Runner tick: {len(acts)} mention(s) handled.")
            return go("/dashboard")

    return app


def main() -> None:  # python -m civicbot.web
    import os
    import uvicorn
    setup_logging()
    app = create_app()
    if os.environ.get("CIVICBOT_EMBEDDED_WORKER", "").lower() in ("1", "true", "yes"):
        import threading
        from .worker import run_forever
        threading.Thread(target=run_forever, args=(app.state.svc, threading.Event()), daemon=True,
                         name="civicbot-worker").start()
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")),
                proxy_headers=Settings.from_env().trust_proxy, log_config=None)
