"""Live verification helpers: one polite GET per candidate, redirects recorded (never followed silently),
response checked against what the candidate claims to be. classify() is pure so it can be unit-tested."""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

UA = "civicbot-directory/1.0 (+https://github.com/fitzyracing1/civicbot; free API directory check)"
ORIGIN = "https://fitzyracing1.github.io"
CAPS = {"zip": 4096, "gtfsrt": 262_144, "docs": 524_288}
DEFAULT_CAP = 3_000_000
MAX_REDIRECTS = 3


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _decode(body: bytes, enc: str) -> bytes:
    try:
        if enc == "gzip" or body[:2] == b"\x1f\x8b":
            return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
        if enc == "deflate":
            return zlib.decompress(body)
    except Exception:  # noqa: BLE001  (truncated stream: keep what we can)
        try:
            return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(body)
        except Exception:  # noqa: BLE001
            return body
    return body


def fetch(url: str, expect: str, timeout: float = 20.0) -> dict:
    """GET with no automatic redirects. Up to MAX_REDIRECTS hops are followed explicitly and recorded."""
    hops, cur = [], url
    t0 = time.monotonic()
    for _ in range(MAX_REDIRECTS + 1):
        headers = {"User-Agent": UA, "Origin": ORIGIN, "Accept-Encoding": "gzip",
                   "Accept": "application/json, application/xml;q=0.9, */*;q=0.5"}
        if expect == "zip":
            headers["Range"] = "bytes=0-4095"
        req = urllib.request.Request(cur, headers=headers)
        status, hdrs, body, err = None, {}, b"", ""
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                status, hdrs = r.status, {k.lower(): v for k, v in r.headers.items()}
                body = r.read(CAPS.get(expect, DEFAULT_CAP) + 1)
        except urllib.error.HTTPError as e:
            status, hdrs = e.code, {k.lower(): v for k, v in (e.headers or {}).items()}
            try:
                body = e.read(20000)
            except Exception:  # noqa: BLE001
                body = b""
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:180]
        if status in (301, 302, 303, 307, 308) and hdrs.get("location"):
            nxt = urllib.parse.urljoin(cur, hdrs["location"])
            hops.append({"status": status, "to": nxt})
            cur = nxt
            continue
        break
    body = _decode(body, hdrs.get("content-encoding", ""))
    return {"status": status, "headers": hdrs, "body": body, "error": err, "redirects": hops, "final": cur,
            "ms": int((time.monotonic() - t0) * 1000), "truncated": len(body) > CAPS.get(expect, DEFAULT_CAP)}


def _is_html(body: bytes, ctype: str) -> bool:
    head = body[:600].lstrip().lower()
    return "text/html" in ctype or head.startswith((b"<!doctype html", b"<html"))


def _json(body: bytes):
    try:
        return json.loads(body.decode("utf-8-sig"))
    except Exception:  # noqa: BLE001
        return None


def classify(expect: str, status, headers: dict, body: bytes, truncated: bool = False) -> tuple:
    """-> (ok, mode, reason). mode is what we publish; reason explains a failure."""
    ctype = (headers or {}).get("content-type", "").lower()
    if status is None:
        return False, "", "no response"
    if expect == "key":
        if status in (401, 403):
            return True, "reachable (key required, not called with a key)", ""
        if status == 200:
            return True, "live GET ok (answered without a key)", ""
        return False, "", f"HTTP {status}"
    if expect == "zip":
        if status in (200, 206) and body[:2] == b"PK":
            return True, "live GET ok (GTFS zip)", ""
        return False, "", f"HTTP {status}" if status not in (200, 206) else "not a zip file"
    if status != 200:
        return False, "", f"HTTP {status}"
    if not body.strip():
        return False, "", "empty body"
    if expect == "docs":
        return True, "docs page reachable (endpoint not tested)", ""
    if expect == "gtfsrt":
        if _is_html(body, ctype):
            return False, "", "HTML instead of a protobuf feed"
        if body.lstrip()[:1] in (b"{", b"[") and b"error" in body[:400].lower():
            return False, "", "error JSON instead of a feed"
        return True, "live GET ok (GTFS-RT feed)", ""
    if expect in ("xml",):
        if _is_html(body, ctype):
            return False, "", "HTML instead of XML"
        return (True, "live GET ok", "") if body.lstrip()[:1] == b"<" else (False, "", "not XML")
    if expect in ("text", "csv"):
        return (False, "", "HTML instead of data") if _is_html(body, ctype) else (True, "live GET ok", "")
    # JSON family
    if _is_html(body, ctype):
        return False, "", "HTML instead of JSON"
    data = _json(body)
    if data is None:
        if truncated and body.lstrip()[:1] in (b"{", b"["):
            return True, "live GET ok (large JSON, truncated read)", ""
        return False, "", "response is not valid JSON"
    if expect == "gbfs":
        if isinstance(data, dict) and isinstance(data.get("data"), (dict, list)):
            return True, "live GET ok (GBFS)", ""
        return False, "", "not a GBFS discovery document"
    if expect == "ckan":
        if isinstance(data, dict) and data.get("success") is True:
            return True, "live GET ok (CKAN API)", ""
        return False, "", "CKAN API did not report success"
    if expect == "socrata":
        if isinstance(data, dict) and (data.get("resultSetSize") or 0) > 0:
            return True, "live GET ok (Socrata catalog)", ""
        return False, "", "Socrata catalog empty for this domain"
    if expect == "ods":
        if isinstance(data, dict) and ("total_count" in data or "results" in data):
            return True, "live GET ok (Opendatasoft API)", ""
        return False, "", "not an Opendatasoft catalog response"
    return True, "live GET ok", ""


def check(c: dict, retry_wait: float = 5.0) -> dict:
    r = fetch(c["check"], c["expect"])
    ok, mode, reason = classify(c["expect"], r["status"], r["headers"], r["body"], r["truncated"])
    retried = False
    if not ok and (r["status"] is None or r["status"] in (429, 500, 502, 503, 504)):
        time.sleep(retry_wait)
        r = fetch(c["check"], c["expect"])
        ok, mode, reason = classify(c["expect"], r["status"], r["headers"], r["body"], r["truncated"])
        retried = True
    acao = r["headers"].get("access-control-allow-origin", "")
    return {"ok": ok, "mode": mode, "reason": reason or (r["error"] if not ok else ""), "http": r["status"],
            "ms": r["ms"], "redirects": r["redirects"], "final": r["final"], "retried": retried,
            "cors": acao == "*" or acao == ORIGIN, "error": r["error"]}
