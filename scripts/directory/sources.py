"""Candidate collectors. Each returns a list of candidate dicts (see directory/README.md for the schema).
Parsers take raw text so they can be tested offline; collect_apis.py does the downloading."""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
from pathlib import Path

from . import curated, geo

ROOT = Path(__file__).resolve().parents[2]

SOURCES = {
    "civicbot": {"name": "civicbot v0.4 verified directory", "url": "https://github.com/fitzyracing1/civicbot/blob/main/civicbot/data/free_apis.json", "license": "MIT"},
    "curated": {"name": "civicbot curated list", "url": "https://github.com/fitzyracing1/civicbot/blob/main/scripts/directory/curated.py", "license": "MIT"},
    "gbfs": {"name": "MobilityData GBFS systems.csv", "url": "https://github.com/MobilityData/gbfs/blob/master/systems.csv", "license": "CC-BY-3.0", "raw": "https://raw.githubusercontent.com/MobilityData/gbfs/master/systems.csv"},
    "mobility-database": {"name": "Mobility Database catalog", "url": "https://mobilitydatabase.org/", "license": "Apache-2.0", "raw": "https://files.mobilitydatabase.org/feeds_v2.csv"},
    "ckan-instances": {"name": "CKAN instances list", "url": "https://github.com/ckan/ckan-instances", "license": "see repository", "raw": "https://raw.githubusercontent.com/ckan/ckan-instances/gh-pages/config/instances.json"},
    "public-apis": {"name": "public-apis/public-apis", "url": "https://github.com/public-apis/public-apis", "license": "MIT", "raw": "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"},
}

# Query parameters that look like credentials: candidates carrying one are refused (never stored or called).
CRED_RE = re.compile(r"(?:^|[?&;])(api[_-]?key|apikey|key|token|access[_-]?token|auth|secret|password|passwd|client[_-]?secret|sig|signature|subscription-key)=", re.I)


SCRUB_RE = re.compile(r"([?&;](?:[\w.-]*(?:key|token|secret|signature|credential|password|passwd)[\w.-]*|sig|auth)=)[^&;#]*", re.I)


def scrub_url(url: str) -> str:
    """Redact credential-like query values (e.g. provider-issued keys or signed-URL tokens in redirect targets)."""
    return SCRUB_RE.sub(r"\1REDACTED", url or "")


def has_credential(url: str) -> bool:
    return bool(CRED_RE.search(urllib.parse.urlsplit(url).query or ""))


def _cand(**kw) -> dict:
    cc = geo.norm_code(kw.get("country"))
    c = {"id": kw["id"], "name": kw["name"].strip(), "category": kw["category"], "answers": (kw.get("answers") or "").strip(),
         "kind": kw.get("kind", "api"), "auth": kw.get("auth", "none"), "country": cc, "city": kw.get("city") or None,
         "continent": kw.get("continent") or ("Europe" if cc == "EU" else geo.continent(cc)),
         "region": kw.get("region") or (", ".join(x for x in (kw.get("city"), geo.country_name(cc)) if x) or "Global"),
         "language": kw.get("language"), "docs": kw.get("docs") or "", "example": kw["example"], "check": kw.get("check") or kw["example"],
         "expect": kw.get("expect", "json"), "format": kw.get("format", "json"), "tier": kw.get("tier", "endpoint"),
         "source": kw["source"], "terms": kw.get("terms")}
    return c


def from_civicbot() -> list:
    """The existing 120 verified entries, read-only (civicbot/data/free_apis.json is never modified)."""
    d = json.loads((ROOT / "civicbot" / "data" / "free_apis.json").read_text())
    out = []
    for a in d["apis"]:
        cc = _region_to_cc(a.get("region", ""))
        c = _cand(id=a["id"], name=a["name"], category=a["category"], answers=a["answers"], auth=a["auth"], country=cc,
                  docs=a["docs"], example=a["example"], expect="key" if a["auth"] == "free-key" else "json",
                  format=a.get("format", "json"), source="civicbot", terms=a.get("terms"), region=a.get("region"))
        c["limits"] = a.get("limits")
        c["legacy"] = True  # keeps its v0.4 id and fields; shown as-is
        out.append(c)
    return out


def _region_to_cc(region: str) -> str | None:
    r = (region or "").strip()
    if not r or r.lower().startswith(("global", "worldwide")):
        return None
    if r in ("EU", "Europe", "European Union"):
        return "EU"
    return geo.code_from_text(r) or geo.code_from_text(r.split("(")[0])


def from_curated() -> list:
    out = []
    for (cid, name, cat, cc, city, auth, expect, example, docs, answers) in curated.C:
        fmt = {"xml": "xml", "text": "text", "csv": "csv"}.get(expect, "json")
        out.append(_cand(id=cid, name=name, category=cat, country=cc, city=city, auth=auth, expect=expect, example=example,
                         docs=docs, answers=answers, format=fmt, source="curated",
                         kind="open311" if cat == curated.O311 else ("portal" if cat == curated.OD else "api")))
    for dom, name, cc, city in curated.SOCRATA:
        out.append(_cand(id="socrata-" + geo.slug(dom), name=name, category=curated.OD, country=cc, city=city,
                         example=f"https://{dom}/api/catalog/v1?domains={dom}&search_context={dom}&limit=1",
                         docs=f"https://{dom}/", answers=f"Open datasets from {name} (Socrata SODA API)",
                         expect="socrata", kind="portal", source="curated"))
    for dom, name, cc, city in curated.OPENDATASOFT:
        out.append(_cand(id="ods-" + geo.slug(dom), name=name, category=curated.OD, country=cc, city=city,
                         example=f"https://{dom}/api/explore/v2.1/catalog/datasets?limit=1", docs=f"https://{dom}/api/explore/v2.1/console",
                         answers=f"Open datasets from {name} (Opendatasoft Explore API)", expect="ods", kind="portal", source="curated"))
    return out


def parse_gbfs(text: str) -> list:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        url = (r.get("Auto-Discovery URL") or "").strip()
        if not url or (r.get("Authentication Type") or "").strip():
            continue
        name, city = r["Name"].strip(), (r.get("Location") or "").strip()
        out.append(_cand(id="gbfs-" + geo.slug(r["System ID"]), name=f"{name} (GBFS)", category="Bikeshare & micromobility",
                         country=r["Country Code"], city=city, example=url, docs=(r.get("URL") or "").strip(),
                         answers=f"Live bikes/scooters and docks for {name}" + (f" in {city}" if city else ""),
                         expect="gbfs", kind="gbfs", source="gbfs", terms="https://github.com/MobilityData/gbfs/blob/master/systems.csv"))
    return out


def parse_mobility_database(text: str, include_static: bool = True) -> list:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        if (r.get("status") or "active") != "active" or (r.get("urls.authentication_type") or "0") not in ("", "0"):
            continue
        url = (r.get("urls.direct_download") or "").strip()
        if not url.startswith("http"):
            continue
        rt = r["data_type"] == "gtfs_rt"
        if not rt and not include_static:
            continue
        place = ", ".join(x for x in (r.get("location.municipality"), r.get("location.subdivision_name")) if x)
        label = r.get("name") or (r.get("entity_type") or "").replace("|", ", ")
        name = f"{r.get('provider', '').strip()}" + (f" – {label}" if label else "")
        out.append(_cand(id=("gtfsrt-" if rt else "gtfs-") + r["id"], name=name[:120] + (" (GTFS-RT)" if rt else " (GTFS)"),
                         category="Transit", country=r.get("location.country_code"), city=place or None,
                         example=url, docs=r.get("urls.license") or "https://mobilitydatabase.org/feeds/" + r["id"],
                         answers=("Real-time " + ((r.get("entity_type") or "updates").replace("|", ", ")) if rt else "Schedules (GTFS zip)") + (f" for {place}" if place else ""),
                         expect="gtfsrt" if rt else "zip", format="protobuf" if rt else "zip", kind="gtfs-rt" if rt else "gtfs",
                         source="mobility-database", terms=r.get("urls.license") or None))
    return out


def parse_ckan_instances(text: str) -> list:
    out = []
    for i in json.loads(text):
        base = (i.get("url-api") or i.get("url") or "").strip().rstrip("/")
        if not base.startswith("http"):
            continue
        loc = (i.get("location") or "").strip()
        cc = geo.code_from_text(loc)
        region = next((f["value"] for f in i.get("facets", []) if f.get("key") == "Region"), "")
        cont = None if cc else {"Australasia": "Oceania", "Worldwide": "Global"}.get(region, region if region in geo.CONTINENTS else None)
        out.append(_cand(id="ckan-" + geo.slug(i.get("id") or i["title"]), name=i["title"].strip(), category="Open data portals",
                         country=cc, city=None, continent=cont, region=loc or region or None,
                         example=base + "/api/3/action/package_search?rows=1", docs=(i.get("url") or base),
                         answers=(i.get("description") or "CKAN open-data portal").strip().split("\n")[0][:200],
                         expect="ckan", kind="portal", source="ckan-instances"))
    return out


_ROW = re.compile(r"^\|\s*\[(?P<name>[^\]]+)\]\((?P<link>[^)]+)\)\s*\|(?P<desc>[^|]*)\|(?P<auth>[^|]*)\|(?P<https>[^|]*)\|(?P<cors>[^|]*)\|")


def parse_public_apis(md: str) -> list:
    out, cat, started = [], None, False
    for line in md.splitlines():
        if line.startswith("### "):
            cat, started = line[4:].strip(), True
            continue
        if not started or not line.startswith("| ["):
            continue
        m = _ROW.match(line)
        if not m:
            continue
        auth = m["auth"].strip().strip("`")
        if auth not in ("No", "apiKey", "User-Agent", "X-Mashape-Key"):
            continue  # OAuth etc.: not a simple free path
        link = _strip_tracking(m["link"].strip())
        if not link.startswith("http"):
            continue
        cors = m["cors"].strip().lower()
        out.append(_cand(id="pa-" + geo.slug(m["name"]), name=m["name"].strip(), category=cat, country=None,
                         example=link, docs=link, answers=m["desc"].strip(),
                         auth="none" if auth in ("No", "User-Agent") else "free-key",
                         expect="docs", tier="docs", format="unknown", source="public-apis"))
        out[-1]["cors_listed"] = {"yes": True, "no": False}.get(cors)
    return out


def _strip_tracking(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), p.fragment))


def dedupe(cands: list) -> tuple:
    """Keep the first candidate per id and per example URL (sources are passed in priority order)."""
    seen_ids, seen_urls, keep, dropped = set(), set(), [], []
    for c in cands:
        key = c["example"].split("#")[0].rstrip("/").lower()
        if c["id"] in seen_ids or key in seen_urls:
            dropped.append({"id": c["id"], "source": c["source"], "reason": "duplicate"})
            continue
        if has_credential(c["example"]) and c["source"] != "civicbot":
            dropped.append({"id": c["id"], "source": c["source"], "reason": "URL carries a credential-like parameter (not stored)"})
            continue
        seen_ids.add(c["id"])
        seen_urls.add(key)
        keep.append(c)
    return keep, dropped
