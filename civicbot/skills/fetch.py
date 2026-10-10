"""SafeFetcher: the only way skills touch the network.

Guards: https only, port 443, host must be on the skill's allowed_domains, every resolved IP must
be public (no loopback/private/link-local/CGNAT/metadata/multicast/reserved -> SSRF protection),
no redirects, timeout, response size cap, JSON only, per-host politeness via HttpTransport-like
spacing. Known limitation: DNS is checked before the connection, so a DNS-rebinding attacker with
a very short TTL could still race it; run skills behind an egress proxy that blocks private ranges
in production.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ..http import DEFAULT_USER_AGENT

HARD_MAX_BYTES = 1_048_576
HARD_MAX_TIMEOUT = 15.0
BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata", "instance-data"}


class FetchBlocked(Exception):
    """Request refused by a safety rule (never sent)."""


class FetchError(Exception):
    def __init__(self, msg: str, status: Optional[int] = None):
        super().__init__(msg)
        self.status = status


def host_allowed(host: str, allowed: Iterable[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in (a.lower() for a in allowed))


def _env_nets() -> list:
    """CIVICBOT_SSRF_ALLOW_NETS="198.18.0.0/15": for sandboxes whose DNS returns proxy 'fake IPs'.
    Never set this in production."""
    raw = os.environ.get("CIVICBOT_SSRF_ALLOW_NETS", "")
    return [ipaddress.ip_network(n.strip()) for n in raw.split(",") if n.strip()]


def ip_is_public(ip: str, allow_nets: Iterable = ()) -> bool:
    a = ipaddress.ip_address(ip)
    if any(a in n for n in allow_nets):
        return True
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global and not (a.is_multicast or a.is_reserved or a.is_loopback or a.is_link_local
                                or a.is_private or a.is_unspecified)


def default_resolve(host: str) -> List[str]:
    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def default_raw(method: str, url: str, headers: Dict[str, str], body: Optional[bytes],
                timeout: float, max_bytes: int) -> Tuple[int, Dict[str, str], bytes]:
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read(min(max_bytes, 2000))
    with resp:
        data = resp.read(max_bytes + 1)
        return resp.status, dict(resp.headers), data


@dataclass
class FetchResult:
    status: int
    url: str
    data: Any
    nbytes: int


class SafeFetcher:
    def __init__(self, resolve: Callable[[str], List[str]] = default_resolve,
                 raw: Callable[..., Tuple[int, Dict[str, str], bytes]] = default_raw,
                 user_agent: str = DEFAULT_USER_AGENT, min_host_interval: float = 0.5,
                 allow_nets: Optional[Iterable[str]] = None):
        self.resolve, self.raw, self.ua = resolve, raw, user_agent
        self.allow_nets = [ipaddress.ip_network(n) for n in allow_nets] if allow_nets is not None else _env_nets()
        self.min_host_interval = min_host_interval
        self._last: Dict[str, float] = {}
        self.log: List[str] = []

    def check_url(self, url: str, allowed_domains: Iterable[str]) -> str:
        p = urllib.parse.urlsplit(url)
        if p.scheme != "https":
            raise FetchBlocked("only https:// URLs are allowed")
        if p.username or p.password:
            raise FetchBlocked("credentials in URL are not allowed")
        if p.port not in (None, 443):
            raise FetchBlocked("only port 443 is allowed")
        host = (p.hostname or "").lower()
        if not host or host in BLOCKED_HOSTS or host.endswith((".local", ".internal", ".localhost")):
            raise FetchBlocked(f"host {host!r} is not allowed")
        if not host_allowed(host, allowed_domains):
            raise FetchBlocked(f"{host} is not on this skill's allowed_domains")
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            literal = None
        ips = [str(literal)] if literal else self.resolve(host)
        if not ips:
            raise FetchBlocked(f"{host} did not resolve")
        bad = [ip for ip in ips if not ip_is_public(ip, self.allow_nets)]
        if bad:
            raise FetchBlocked(f"{host} resolves to non-public address(es) {bad} (SSRF guard)")
        return host

    def request(self, method: str, url: str, *, allowed_domains: Iterable[str], params: Optional[Dict] = None,
                headers: Optional[Dict[str, str]] = None, json_body: Optional[Dict] = None,
                form_body: Optional[Dict] = None, timeout: float = 10.0, max_bytes: int = 262_144) -> FetchResult:
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        host = self.check_url(url, allowed_domains)
        timeout = min(float(timeout), HARD_MAX_TIMEOUT)
        max_bytes = min(int(max_bytes), HARD_MAX_BYTES)
        wait = self._last.get(host, 0) + self.min_host_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()
        h = {"User-Agent": self.ua, "Accept": "application/json"}
        h.update(headers or {})
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode()
            h["Content-Type"] = "application/json"
        elif form_body is not None:
            body = urllib.parse.urlencode(form_body).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            status, rh, data = self.raw(method, url, h, body, timeout, max_bytes)
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
            raise FetchError(f"{host}: {getattr(e, 'reason', e)}") from None
        if 300 <= status < 400:
            raise FetchBlocked(f"{host} answered with a redirect ({status}); redirects are not followed")
        if len(data) > max_bytes:
            raise FetchError(f"{host}: response larger than {max_bytes} bytes")
        if status >= 400:
            raise FetchError(f"{host}: HTTP {status}", status)
        try:
            parsed = json.loads(data.decode("utf-8")) if data else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise FetchError(f"{host}: response is not JSON") from None
        return FetchResult(status, url, parsed, len(data))

    def get_spec(self, url: str, max_bytes: int = 65_536) -> Any:
        """Fetch a skill spec document from any public https host (owner-initiated)."""
        host = urllib.parse.urlsplit(url).hostname or ""
        return self.request("GET", url, allowed_domains=[host] if host else [], max_bytes=max_bytes,
                            timeout=10).data
