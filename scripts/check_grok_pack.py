"""Live check of every URL in the Grok pack: each skill template filled with its sample values, the geocoder,
the 311 service lists and submit links, and every keyless directory example. Read-only GETs, polite pacing.

    python scripts/check_grok_pack.py                 # exit 1 if any URL is not HTTP 200
    python scripts/check_grok_pack.py --site URL      # also check the deployed pack files (e.g. after Pages deploy)
"""
from __future__ import annotations

import concurrent.futures as cf
import importlib.util
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (compatible; civicbot-grok-pack-check/1.0; +https://github.com/fitzyracing1/civicbot)"
REPORT = HERE / "free_apis" / "grok_pack_report.json"

_spec = importlib.util.spec_from_file_location("build_grok_pack", HERE / "build_grok_pack.py")
gp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gp)


def urls(site: str = "") -> list:
    p = gp.build_pack()
    out = [("skill:" + s["name"], s["sample"]["url"]) for s in p["skills"]]
    out.append(("geocoder", gp.fill(p["geocoder"], {"place": "Bloomington"})))
    out.append(("311:seeclickfix-services", gp.fill(p["open311"]["seeclickfix_services"], {"lat": 41.3083, "lng": -72.9259})))
    out.append(("311:seeclickfix-submit", p["open311"]["seeclickfix_submit"]))
    for c in p["open311"]["cities"]:
        out.append((f"311:{c['id']}:submit", c["submit"]))
        if c["services"]:
            out.append((f"311:{c['id']}:services", c["services"]))
    out += [("api:" + a["id"], a["example"]) for a in p["apis"]]
    if site:
        out += [("site:" + f, site.rstrip("/") + "/" + f) for f in
                ("grok.txt", "grok-apis.txt", "llms.txt", "grok-instructions.txt", "grok-project.txt",
                 "data/grok-pack.json", "grok.html")]
    return out


def get(url: str) -> tuple:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*;q=0.5"})
    t0 = time.monotonic()
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read(2_000_000)
                return r.status, int((time.monotonic() - t0) * 1000), ""
        except urllib.error.HTTPError as e:
            status, err = e.code, ""
        except Exception as e:  # noqa: BLE001
            status, err = None, f"{type(e).__name__}: {e}"[:160]
        if attempt == 1 and status not in (400, 401, 403, 404):
            time.sleep(4)
            continue
        return status, int((time.monotonic() - t0) * 1000), err


def main(argv) -> int:
    site = argv[argv.index("--site") + 1] if "--site" in argv else ""
    todo = urls(site)
    by_host = defaultdict(list)
    for name, u in todo:
        by_host[urllib.parse.urlsplit(u).hostname].append((name, u))

    def run_host(items):
        res = []
        for i, (name, u) in enumerate(items):
            if i:
                time.sleep(1.2)
            res.append((name, u) + get(u))
        return res

    results = []
    with cf.ThreadPoolExecutor(8) as ex:
        for r in ex.map(run_host, by_host.values()):
            results += r
    results.sort()
    bad = [r for r in results if r[2] != 200]
    for name, u, st, ms, err in results:
        if st != 200:
            print(f"FAIL {name} {st} {err} {u}")
    print(f"{len(results) - len(bad)}/{len(results)} URLs returned 200")
    REPORT.write_text(json.dumps({"checked": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "ok": len(results) - len(bad),
                                  "total": len(results),
                                  "results": [{"name": n, "url": u, "http": s, "ms": m, "error": e}
                                              for n, u, s, m, e in results]}, indent=1) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
