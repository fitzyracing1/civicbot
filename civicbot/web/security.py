"""CSRF tokens, Origin checks, per-IP rate limiting and security headers."""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class CsrfError(Exception):
    pass


class RateLimited(Exception):
    pass


def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = request.session["csrf"] = secrets.token_urlsafe(32)
    return tok


def check_csrf(request: Request, form, base_url: str) -> None:
    """Synchronizer token (session vs. form field) + Origin/Referer must be our own site."""
    sent = str(form.get("csrf_token") or "")
    want = request.session.get("csrf") or ""
    if not want or not hmac.compare_digest(sent, want):
        raise CsrfError("missing or invalid CSRF token")
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin and origin != "null":
        o, b = urlparse(origin), urlparse(base_url)
        if (o.scheme, o.netloc) != (b.scheme, b.netloc):
            raise CsrfError("cross-origin form post refused")


class RateLimiter:
    """Sliding window per (bucket, client). In-process: with several web processes put a shared limiter
    (e.g. at the proxy, or Redis) in front - see docs/DEPLOY.md."""

    def __init__(self):
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                raise RateLimited(key)
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class SecurityHeaders(BaseHTTPMiddleware):
    def __init__(self, app, hsts: bool, extra_form_action: str = ""):
        super().__init__(app)
        self.hsts = hsts
        # form-action must allow the OAuth redirect target (browsers apply it to redirects after a POST)
        fa = "'self' https://x.com https://twitter.com" + (f" {extra_form_action}" if extra_form_action else "")
        self.csp = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'none'; "
                    f"form-action {fa}; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")

    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h.setdefault("Content-Security-Policy", self.csp)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "same-origin")  # OAuth codes in our callback URL never leak via Referer
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        if request.url.path.startswith(("/auth", "/dashboard", "/robots", "/setup", "/account", "/dev")):
            h.setdefault("Cache-Control", "no-store")
        if self.hsts:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp
