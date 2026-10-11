"""Verify directory candidates live and publish the global directory (directory/data/), or re-check it.

    python scripts/verify_apis.py                         # verify all candidates, write data shards + failed.json
    python scripts/verify_apis.py --sources curated gbfs  # only some candidate files (others keep last results)
    python scripts/verify_apis.py --checkpoint /tmp/v.jsonl   # resumable: results are appended as they arrive
    python scripts/verify_apis.py --recheck --report dead.md  # weekly: re-check published entries, report dead ones
                                                              # (never deletes; exit 0 even if some are dead)
Politeness: identifying User-Agent, one request per candidate, >= 1.2 s between requests to the same host,
20 s timeout, one retry on network errors / 429 / 5xx, redirects recorded rather than silently followed.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import sys
import threading
import time
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from directory import geo, prompts as P, sources as S, verify as V  # noqa: E402

DIR = ROOT / "directory"
CAND = DIR / "candidates"
DATA = DIR / "data"
SPACING = 1.2
KEEP = ("id", "name", "category", "answers", "kind", "auth", "country", "city", "continent", "region", "language",
        "docs", "example", "format", "tier", "source", "terms", "limits", "legacy", "cors_listed")


def load_candidates(only=None) -> list:
    out = []
    for f in sorted(CAND.glob("*.json")):
        if f.stem == "dropped" or (only and f.stem not in only):
            continue
        out += json.loads(f.read_text(encoding="utf-8"))["candidates"]
    return out


def run_checks(cands: list, workers: int = 48, checkpoint: Path | None = None, progress=True) -> dict:
    done = {}
    if checkpoint and checkpoint.exists():
        for line in checkpoint.read_text().splitlines():
            r = json.loads(line)
            done[r["id"]] = r
    todo = [c for c in cands if c["id"] not in done]
    by_host = defaultdict(list)
    for c in todo:
        by_host[urllib.parse.urlsplit(c["check"]).hostname or "?"].append(c)
    lock = threading.Lock()
    fh = checkpoint.open("a") if checkpoint else None
    count = [0]

    def host_worker(items):
        for i, c in enumerate(items):
            if i:
                time.sleep(SPACING)
            r = V.check(c)
            r["id"] = c["id"]
            r["checked_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with lock:
                done[c["id"]] = r
                count[0] += 1
                if fh:
                    fh.write(json.dumps(r) + "\n")
                    fh.flush()
                if progress and count[0] % 250 == 0:
                    print(f"  {count[0]}/{len(todo)} checked", flush=True)

    # biggest hosts first so the long tails start early
    groups = sorted(by_host.values(), key=len, reverse=True)
    with cf.ThreadPoolExecutor(workers) as ex:
        list(ex.map(host_worker, groups))
    if fh:
        fh.close()
    return done


def entry(c: dict, r: dict) -> dict:
    e = {k: c[k] for k in KEEP if c.get(k) not in (None, "", [])}
    e["country_name"] = geo.country_name(c.get("country")) or None
    e["check_type"] = c["expect"]
    if c["check"] != c["example"]:
        e["check"] = c["check"]
    e["cors"] = r.get("cors", False)
    e["verified"] = {"date": r["checked_at"][:10], "http": r.get("http"), "ms": r.get("ms"), "mode": r.get("mode") or r.get("reason")}
    e["verified_at"] = r["checked_at"]
    e["last_status"] = "ok" if r["ok"] else "failing"
    if r.get("redirects"):
        # redirect targets can carry provider-issued keys or signed-URL tokens: never store them
        e["redirects"] = [dict(x, to=S.scrub_url(x.get("to", ""))) for x in r["redirects"]]
        e["resolved"] = S.scrub_url(r["final"])
    return {k: v for k, v in e.items() if v not in (None, "")}


def publish(cands: list, results: dict) -> dict:
    entries, failed = [], []
    for c in cands:
        r = results.get(c["id"])
        if not r:
            continue
        if r["ok"] or c.get("legacy"):  # the v0.4 entries are always kept, with their latest status
            entries.append(entry(c, r))
        else:
            failed.append({"id": c["id"], "name": c["name"], "source": c["source"], "url": c["check"], "expect": c["expect"],
                           "http": r.get("http"), "reason": r.get("reason") or r.get("error") or "unknown",
                           "checked_at": r["checked_at"]})
    entries.sort(key=lambda e: (e["continent"], e.get("country") or "", e["category"], e["id"]))
    P.apply(entries)  # 'Paste into Grok' prompt per entry
    DATA.mkdir(parents=True, exist_ok=True)
    for old in DATA.glob("*.json"):
        old.unlink()
    shards = []
    for cont in geo.CONTINENTS:
        mine = [e for e in entries if e["continent"] == cont]
        if not mine:
            continue
        fn = geo.slug(cont) + ".json"
        (DATA / fn).write_text(json.dumps({"continent": cont, "count": len(mine), "apis": mine}, ensure_ascii=False,
                                          separators=(",", ":")) + "\n", encoding="utf-8")
        shards.append({"continent": cont, "file": fn, "count": len(mine)})
    ok = [e for e in entries if e["last_status"] == "ok"]
    by_country = {}
    for e in ok:
        cc = e.get("country")
        if cc:
            d = by_country.setdefault(cc, {"name": geo.country_name(cc), "continent": e["continent"], "count": 0})
            d["count"] += 1
    index = {
        "version": 1, "generated": dt.date.today().isoformat(), "count": len(entries), "ok": len(ok),
        "endpoint_verified": sum(1 for e in ok if e.get("tier") == "endpoint"),
        "docs_only": sum(1 for e in ok if e.get("tier") == "docs"),
        "by_continent": dict(Counter(e["continent"] for e in ok).most_common()),
        "by_category": dict(Counter(e["category"] for e in ok).most_common()),
        "by_auth": dict(Counter(e["auth"] for e in ok).most_common()),
        "by_kind": dict(Counter(e["kind"] for e in ok).most_common()),
        "by_source": dict(Counter(e["source"] for e in ok).most_common()),
        "by_country": dict(sorted(by_country.items())),
        "shards": shards, "sources": S.SOURCES,
        "failed": len(failed),
        "note": "Each entry was called live on verified.date with an identifying User-Agent. tier=endpoint: the example "
                "URL answered with the expected format. tier=docs: only the documentation page was reachable (from "
                "public-apis); the API itself is not yet tested. auth: none | free-key (free signup) | demo-key. "
                "Respect each provider's terms and limits.",
    }
    (DATA / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    failed.sort(key=lambda f: (f["source"], f["id"]))
    (DIR / "failed.json").write_text(json.dumps({"generated": index["generated"], "count": len(failed),
                                                 "by_reason": dict(Counter(_bucket(f["reason"]) for f in failed).most_common()),
                                                 "failed": failed}, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    return index


def _bucket(reason: str) -> str:
    r = reason or ""
    for k in ("HTTP 404", "HTTP 403", "HTTP 401", "HTTP 410", "HTTP 429", "HTTP 5", "HTTP 400", "timed out", "SSL", "Name or service",
              "not valid JSON", "HTML instead", "not a zip", "CKAN", "Socrata", "GBFS", "Connection refused", "Connection reset"):
        if k in r:
            return {"HTTP 5": "HTTP 5xx", "Name or service": "DNS failure"}.get(k, k)
    return r.split(":")[0][:40] or "unknown"


def load_published() -> list:
    out = []
    for f in sorted(DATA.glob("*.json")):
        if f.name == "index.json":
            continue
        for e in json.loads(f.read_text(encoding="utf-8"))["apis"]:
            out.append(dict(e, check=e.get("check", e["example"]), expect=e["check_type"]))
    return out


def recheck(report: Path | None, workers: int) -> int:
    entries = [e for e in load_published() if e.get("last_status") == "ok"]
    res = run_checks(entries, workers)
    dead = [(e, res[e["id"]]) for e in entries if not res[e["id"]]["ok"]]
    lines = [f"# Directory re-check {dt.date.today().isoformat()}", "",
             f"{len(entries) - len(dead)} of {len(entries)} published entries still answer. "
             f"{len(dead)} did not. Nothing was deleted; review and fix or remove them in a follow-up PR.", ""]
    if dead:
        lines += ["| id | source | HTTP | reason | url |", "|---|---|---|---|---|"]
        lines += [f"| {e['id']} | {e['source']} | {r.get('http')} | {(r.get('reason') or '')[:60]} | {e['check']} |" for e, r in dead[:300]]
    text = "\n".join(lines) + "\n"
    (DIR / "recheck_report.json").write_text(json.dumps({"date": dt.date.today().isoformat(), "checked": len(entries),
                                                         "dead": [{"id": e["id"], "http": r.get("http"), "reason": r.get("reason")} for e, r in dead]},
                                                        indent=0) + "\n")
    if report:
        report.write_text(text)
    print(text[:2000])
    return len(dead)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="*")
    ap.add_argument("--checkpoint", type=Path)
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--report", type=Path)
    ap.add_argument("--publish-only", action="store_true",
                    help="publish what the --checkpoint already holds (unchecked candidates stay queued for the next run)")
    a = ap.parse_args(argv)
    if a.recheck:
        n = recheck(a.report, a.workers)
        print(f"dead: {n}")
        return 0
    cands = load_candidates()
    selected = [c for c in cands if not a.sources or c["source"] in a.sources]
    t0 = time.time()
    print(f"verifying {len(selected)} candidates ...", flush=True)
    if a.publish_only:
        if not (a.checkpoint and a.checkpoint.exists()):
            ap.error("--publish-only needs an existing --checkpoint")
        results = {}
        for line in a.checkpoint.read_text().splitlines():
            r = json.loads(line)
            results[r["id"]] = r
        results = {c["id"]: results[c["id"]] for c in selected if c["id"] in results}
    else:
        results = run_checks(selected, a.workers, a.checkpoint)
    queued = sorted(c["id"] for c in selected if c["id"] not in results)
    if a.sources:  # keep the previous results for sources not re-checked this time
        prev = {e["id"]: e for e in load_published()}
        for c in cands:
            if c["id"] not in results and c["id"] in prev:
                p = prev[c["id"]]
                results[c["id"]] = {"ok": p["last_status"] == "ok", "mode": p["verified"]["mode"], "http": p["verified"]["http"],
                                    "ms": p["verified"]["ms"], "cors": p.get("cors"), "checked_at": p["verified_at"],
                                    "redirects": p.get("redirects", []), "final": p.get("resolved", p["example"])}
    idx = publish(cands, results)
    (DIR / "last_run.json").write_text(json.dumps({"date": idx["generated"], "seconds": int(time.time() - t0),
                                                   "checked": len(selected) - len(queued), "ok": idx["ok"], "failed": idx["failed"],
                                                   "queued": len(queued), "queued_ids": queued}, indent=1) + "\n")
    print(json.dumps({k: idx[k] for k in ("count", "ok", "endpoint_verified", "docs_only", "failed", "by_continent", "by_auth")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
