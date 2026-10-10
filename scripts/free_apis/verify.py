"""Verify every candidate free API live and write civicbot/data/free_apis.json (only the ones that work).

    python scripts/free_apis/verify.py            # ~2 minutes; polite: 1 request per API, >=1.1 s between same-host calls

For each API one real GET is made with an identifying User-Agent and an Origin header, recording HTTP status,
latency, whether the body parses, and whether CORS allows a browser (Access-Control-Allow-Origin).
"free-key" APIs are listed when the endpoint is reachable and asks for a key (401/403); they are never called with one.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "civicbot" / "data" / "free_apis.json"
REPORT = HERE / "last_report.json"
UA = "civicbot/0.4 (+https://github.com/fitzyracing1/civicbot; free API directory check)"
ORIGIN = "https://fitzyracing1.github.io"

ns: dict = {}
exec((HERE / "candidates.py").read_text(), ns)
CANDIDATES = ns["C"]


def skill_map() -> dict:
    """api id -> catalog skill name, from each spec's terms.notes 'directory: <id>' tag (see catalog/free)."""
    from civicbot.skills.catalog import default_catalog
    out = {}
    cat = default_catalog()
    for n in cat.names():
        api = (cat.entry(n) or {}).get("api_id")
        if api:
            out.setdefault(api, []).append(n)
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None  # a moved API is reported (and the URL fixed in candidates.py), never silently followed


_OPENER = urllib.request.build_opener(_NoRedirect)


def check_with_retry(c: dict) -> dict:
    r = check(c)
    if not r["ok"] and r["status"] not in (301, 302, 307, 308, 404):
        time.sleep(5)
        r2 = check(c)
        r2["retried"] = True
        return r2
    return r


def check(c: dict) -> dict:
    req = urllib.request.Request(c["check"], headers={"User-Agent": UA, "Origin": ORIGIN,
                                                      "Accept": "application/json, */*;q=0.5"})
    t0 = time.monotonic()
    status, headers, body, err = None, {}, b"", ""
    try:
        with _OPENER.open(req, timeout=25) as r:
            status, headers, body = r.status, dict(r.headers), r.read(3_000_000)
    except urllib.error.HTTPError as e:
        status, headers, body = e.code, dict(e.headers or {}), e.read(20000) if e.fp else b""
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"[:200]
    ms = int((time.monotonic() - t0) * 1000)
    h = {k.lower(): v for k, v in headers.items()}
    acao = h.get("access-control-allow-origin", "")
    cors = acao == "*" or acao == ORIGIN
    ok, why = False, err
    if status == 200:
        if c["format"] == "json":
            try:
                txt = body.decode("utf-8-sig")
                json.loads(txt)
                ok = c["expect"] is None or c["expect"] in txt
                why = "" if ok else f"expected '{c['expect']}' not in body"
            except Exception as e:  # noqa: BLE001
                why = f"not JSON: {type(e).__name__}"
        else:
            ok, why = len(body) > 0, "" if body else "empty body"
    elif c["auth"] == "free-key" and status in (401, 403):
        ok, why = True, "reachable; key required"
    elif status in (301, 302, 307, 308):
        why = f"HTTP {status} redirect -> {h.get('location', '?')[:120]}"
    elif status:
        why = f"HTTP {status}"
    return {"id": c["id"], "ok": ok, "status": status, "ms": ms, "cors": cors, "why": why}


def main() -> int:
    by_host = defaultdict(list)
    for c in CANDIDATES:
        by_host[urllib.parse.urlsplit(c["check"]).hostname].append(c)

    def run_host(cs):
        out = []
        for i, c in enumerate(cs):
            if i:
                time.sleep(1.2)  # politeness (Nominatim: max 1 req/s)
            out.append(check_with_retry(c))
        return out

    results = {}
    with cf.ThreadPoolExecutor(12) as ex:
        for rs in ex.map(run_host, by_host.values()):
            for r in rs:
                results[r["id"]] = r
    today = dt.date.today().isoformat()
    skills = skill_map()
    apis, failed = [], []
    for c in CANDIDATES:
        r = results[c["id"]]
        if not r["ok"]:
            failed.append(r)
            continue
        u = urllib.parse.urlsplit(c["check"])
        e = {k: c[k] for k in ("id", "name", "category", "answers", "auth", "region", "docs", "limits", "format")}
        e["base_url"] = f"{u.scheme}://{u.netloc}"
        e["example"] = c["check"]
        if c["key_note"]:
            e["key_note"] = c["key_note"]
        if c["terms"]:
            e["terms"] = c["terms"]
        e["cors"] = r["cors"]
        e["verified"] = {"date": today, "http": r["status"], "ms": r["ms"],
                         "mode": "reachable (key required, not called with a key)" if r["why"] == "reachable; key required" else "live GET ok"}
        e["skills"] = skills.get(c["id"], [])
        apis.append(e)
    cats = sorted({a["category"] for a in apis})
    OUT.write_text(json.dumps({"generated": today, "checked_with": UA, "count": len(apis), "categories": cats,
                               "note": "Each entry was called live on the 'verified.date'. 'auth: none' = no key or signup. "
                                       "Respect each API's limits/terms; civicbot is not affiliated with any provider.",
                               "apis": apis}, indent=1, ensure_ascii=False) + "\n")
    REPORT.write_text(json.dumps({"date": today, "checked": len(CANDIDATES), "listed": len(apis), "failed": failed},
                                 indent=1) + "\n")
    print(f"checked {len(CANDIDATES)}, listed {len(apis)}, failed {len(failed)}")
    for f in failed:
        print("  FAIL", f["id"], f["status"], f["why"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
