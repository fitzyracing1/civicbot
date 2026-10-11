"""Collect free-API candidates from every source into directory/candidates/ (no API is called here).

    python scripts/collect_apis.py                    # download sources, write directory/candidates/*.json
    python scripts/collect_apis.py --cache /tmp/src   # reuse/save the raw source files in a folder
    python scripts/collect_apis.py --no-static        # skip GTFS static zips (Mobility Database)

Then run scripts/verify_apis.py. Sources and their licenses are listed in scripts/directory/sources.py (SOURCES);
every candidate records its source so provenance survives into the published directory.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from directory import sources as S  # noqa: E402

OUT = ROOT / "directory" / "candidates"
UA = "civicbot-directory/1.0 (+https://github.com/fitzyracing1/civicbot; free API directory collector)"
CACHE_NAMES = {"gbfs": "gbfs.csv", "mobility-database": "mdb.csv", "ckan-instances": "ckan-instances.json", "public-apis": "public-apis.md"}


def raw(source: str, cache: Path | None) -> str:
    if cache and (cache / CACHE_NAMES[source]).exists():
        return (cache / CACHE_NAMES[source]).read_text(encoding="utf-8")
    req = urllib.request.Request(S.SOURCES[source]["raw"], headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = r.read().decode("utf-8")
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / CACHE_NAMES[source]).write_text(text, encoding="utf-8")
    return text


def collect(cache: Path | None = None, static: bool = True) -> dict:
    groups = [("civicbot", S.from_civicbot()), ("curated", S.from_curated()),
              ("gbfs", S.parse_gbfs(raw("gbfs", cache))),
              ("ckan-instances", S.parse_ckan_instances(raw("ckan-instances", cache))),
              ("mobility-database", S.parse_mobility_database(raw("mobility-database", cache), include_static=static)),
              ("public-apis", S.parse_public_apis(raw("public-apis", cache)))]
    allc = [c for _, g in groups for c in g]
    keep, dropped = S.dedupe(allc)
    OUT.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, _ in groups:
        mine = sorted((c for c in keep if c["source"] == name), key=lambda c: c["id"])
        counts[name] = len(mine)
        (OUT / f"{name}.json").write_text(json.dumps({"source": S.SOURCES[name], "count": len(mine), "candidates": mine},
                                                     ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    (OUT / "dropped.json").write_text(json.dumps({"count": len(dropped), "dropped": dropped}, indent=0) + "\n")
    return {"candidates": counts, "total": len(keep), "dropped": len(dropped)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--no-static", action="store_true")
    a = ap.parse_args()
    print(json.dumps(collect(a.cache, static=not a.no_static), indent=1))
