"""Tiny stdlib HTTP transport with per-host rate limiting.

Every network call in civicbot goes through a transport object, so tests can
swap in a fake and nothing touches the network by accident.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Mapping, Optional

DEFAULT_USER_AGENT = "civicbot/0.3 (prototype; city API client)"


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status, self.url, self.body = status, url, body


class RateLimiter:
    """Minimum interval between calls to the same host (politeness, Nominatim's 1 req/s)."""

    def __init__(self, min_interval: float = 1.0, per_host: Optional[Mapping[str, float]] = None):
        self.min_interval = min_interval
        self.per_host = dict(per_host or {})
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        interval = self.per_host.get(host, self.min_interval)
        with self._lock:
            now = time.monotonic()
            delay = self._last.get(host, 0.0) + interval - now
            if delay > 0:
                time.sleep(delay)
            self._last[host] = time.monotonic()


class HttpTransport:
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: float = 20.0,
                 rate_limiter: Optional[RateLimiter] = None):
        self.user_agent = user_agent
        self.timeout = timeout
        self.rate_limiter = rate_limiter or RateLimiter(
            min_interval=0.5, per_host={"nominatim.openstreetmap.org": 1.1})

    def _open(self, req: urllib.request.Request) -> bytes:
        host = urllib.parse.urlparse(req.full_url).netloc
        self.rate_limiter.wait(host)
        req.add_header("User-Agent", self.user_agent)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise HttpError(e.code, req.full_url, e.read().decode("utf-8", "replace")) from None

    @staticmethod
    def build_url(url: str, params: Optional[Mapping[str, Any]] = None) -> str:
        if not params:
            return url
        clean = {k: v for k, v in params.items() if v is not None}
        sep = "&" if "?" in url else "?"
        return url + sep + urllib.parse.urlencode(clean, doseq=True)

    def get_bytes(self, url: str, params: Optional[Mapping[str, Any]] = None,
                  headers: Optional[Mapping[str, str]] = None) -> bytes:
        req = urllib.request.Request(self.build_url(url, params), headers=dict(headers or {}))
        return self._open(req)

    def get_json(self, url: str, params: Optional[Mapping[str, Any]] = None,
                 headers: Optional[Mapping[str, str]] = None) -> Any:
        raw = self.get_bytes(url, params, headers={"Accept": "application/json", **dict(headers or {})})
        return json.loads(raw.decode("utf-8"))

    def post_form(self, url: str, data: Mapping[str, Any],
                  headers: Optional[Mapping[str, str]] = None) -> Any:
        body = urllib.parse.urlencode(data, doseq=True).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
            **dict(headers or {})})
        return json.loads(self._open(req).decode("utf-8"))

    def post_json(self, url: str, payload: Any, headers: Optional[Mapping[str, str]] = None) -> Any:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json", **dict(headers or {})})
        return json.loads(self._open(req).decode("utf-8"))
