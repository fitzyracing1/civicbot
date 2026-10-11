"""Tests for the global free-API directory tooling (scripts/directory, collect/verify/build). Offline only."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from directory import geo, prompts as P, sources as S, verify as V  # noqa: E402

DATA = ROOT / "directory" / "data"
pub = pytest.mark.skipif(not (DATA / "index.json").exists(), reason="directory not published yet")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_existing_v04_directory_file_is_untouched():
    p = ROOT / "civicbot" / "data" / "free_apis.json"
    assert hashlib.sha256(p.read_bytes()).hexdigest() == "78a2ffff76833cbb119f4f6f71c148d67547cbb139e73b2674204a310d3067a6"


def test_geo_table():
    assert geo.continent("PT") == "Europe" and geo.continent("ke") == "Africa" and geo.continent("AQ") == "Antarctica"
    assert geo.continent(None) == "Global" and geo.continent("ZZ") == "Global"
    assert geo.code_from_text("Hamburg, Germany") == "DE" and geo.code_from_text("Reno, NV, USA") == "US"
    assert geo.code_from_text("Suwon,Korea") == "KR" and geo.code_from_text("Worldwide") is None
    assert set(v[1] for v in geo.COUNTRIES.values()) == set(geo.CONTINENTS) - {"Global"}
    assert geo.slug("North America") == "north-america" and geo.slug("Île-de-France") == "ile-de-france"


GBFS = """Country Code,Name,Location,System ID,URL,Auto-Discovery URL,Supported Versions,Authentication Info URL,Authentication Type,Authentication Parameter Name
PT,GIRA,Lisboa,gira,https://www.gira-bicicletasdelisboa.pt/,https://example.org/gira/gbfs.json,2.3,,,
US,Locked,Somewhere,locked,https://x,https://example.org/locked/gbfs.json,2.3,https://x,2,key
"""


def test_parse_gbfs_skips_authenticated_feeds():
    c = S.parse_gbfs(GBFS)
    assert [x["id"] for x in c] == ["gbfs-gira"]
    assert c[0]["continent"] == "Europe" and c[0]["country"] == "PT" and c[0]["expect"] == "gbfs" and c[0]["source"] == "gbfs"


MDB = """id,data_type,entity_type,location.country_code,location.subdivision_name,location.municipality,provider,is_official,name,note,feed_contact_email,static_reference,urls.direct_download,urls.authentication_type,urls.authentication_info,urls.api_key_parameter_name,urls.latest,urls.license,status
mdb-1,gtfs,,KE,Nairobi,Nairobi,Digital Matatus,,,,,,https://example.org/nairobi.zip,0,,,,,active
mdb-2,gtfs_rt,vp,US,MA,Boston,MBTA,,,,,,https://example.org/vp.pb,0,,,,,active
mdb-3,gtfs_rt,tu,US,NY,NYC,MTA,,,,,,https://example.org/tu.pb,2,,api_key,,,active
mdb-4,gtfs,,US,NY,NYC,Old,,,,,,https://example.org/old.zip,0,,,,,deprecated
"""


def test_parse_mobility_database():
    c = S.parse_mobility_database(MDB)
    assert [x["id"] for x in c] == ["gtfs-mdb-1", "gtfsrt-mdb-2"]
    assert c[0]["continent"] == "Africa" and c[0]["kind"] == "gtfs" and c[0]["expect"] == "zip"
    assert c[1]["kind"] == "gtfs-rt" and c[1]["format"] == "protobuf"
    assert [x["id"] for x in S.parse_mobility_database(MDB, include_static=False)] == ["gtfsrt-mdb-2"]


PA = """| [Sponsor](https://sponsor.example/?utm_source=Github) | Ad | x |
### Weather
API | Description | Auth | HTTPS | CORS |
|:---|:---|:---|:---|:---|
| [Open-Thing](https://thing.example/docs?utm_source=x&a=1) | Thing data | No | Yes | Yes |
| [Keyed](https://keyed.example/) | Keyed data | `apiKey` | Yes | Unknown |
| [OAuthy](https://oauth.example/) | Needs OAuth | `OAuth` | Yes | No |
"""


def test_parse_public_apis():
    c = S.parse_public_apis(PA)
    assert [x["name"] for x in c] == ["Open-Thing", "Keyed"]
    assert c[0]["example"] == "https://thing.example/docs?a=1" and c[0]["tier"] == "docs" and c[0]["category"] == "Weather"
    assert c[1]["auth"] == "free-key" and c[0]["auth"] == "none" and c[0]["cors_listed"] is True


def test_parse_ckan_instances():
    txt = json.dumps([{"id": "x_y", "title": "X Portal", "url": "https://data.x.example", "url-api": "", "location": "Kampala, Uganda",
                       "facets": [{"key": "Region", "value": "Africa"}]},
                      {"id": "w", "title": "World", "url": "https://w.example/", "facets": [{"key": "Region", "value": "Worldwide"}]}])
    c = S.parse_ckan_instances(txt)
    assert c[0]["example"] == "https://data.x.example/api/3/action/package_search?rows=1"
    assert c[0]["country"] == "UG" and c[0]["continent"] == "Africa" and c[1]["continent"] == "Global"


def test_credentials_are_refused_and_dupes_dropped():
    assert S.has_credential("https://a.example/x?api_key=abc") and S.has_credential("https://a.example/x?foo=1&token=z")
    assert not S.has_credential("https://a.example/x?keyword=1&monkey=2")
    a = S._cand(id="a", name="A", category="c", example="https://a.example/x", source="curated")
    b = S._cand(id="b", name="B", category="c", example="https://a.example/x/", source="gbfs")
    k = S._cand(id="k", name="K", category="c", example="https://k.example/x?apikey=SECRET", source="gbfs")
    keep, dropped = S.dedupe([a, b, k])
    assert [x["id"] for x in keep] == ["a"]
    assert {d["reason"].split(" ")[0] for d in dropped} == {"duplicate", "URL"}
    assert "SECRET" not in json.dumps(dropped)


@pytest.mark.parametrize("expect,status,ctype,body,ok", [
    ("json", 200, "application/json", b'{"a":1}', True),
    ("json", 200, "text/html", b"<!doctype html><html>", False),
    ("json", 404, "application/json", b"{}", False),
    ("gbfs", 200, "application/json", b'{"data":{"en":{"feeds":[]}}}', True),
    ("gbfs", 200, "application/json", b'{"nope":1}', False),
    ("ckan", 200, "application/json", b'{"success":true,"result":{}}', True),
    ("ckan", 200, "application/json", b'{"success":false}', False),
    ("socrata", 200, "application/json", b'{"results":[{}],"resultSetSize":5}', True),
    ("socrata", 200, "application/json", b'{"results":[],"resultSetSize":0}', False),
    ("ods", 200, "application/json", b'{"total_count":3,"results":[]}', True),
    ("xml", 200, "application/xml", b"<?xml version='1.0'?><a/>", True),
    ("xml", 200, "text/html", b"<html></html>", False),
    ("zip", 206, "application/zip", b"PK\x03\x04rest", True),
    ("zip", 200, "text/html", b"<html>", False),
    ("gtfsrt", 200, "application/octet-stream", b"\x0a\x0d\x0a\x032.0", True),
    ("gtfsrt", 200, "text/html", b"<!DOCTYPE html>", False),
    ("key", 401, "application/json", b"{}", True),
    ("key", 404, "application/json", b"{}", False),
    ("docs", 200, "text/html", b"<html>docs</html>", True),
    ("text", 200, "text/plain", b"   ", False),
])
def test_classify(expect, status, ctype, body, ok):
    assert V.classify(expect, status, {"content-type": ctype}, body)[0] is ok


def test_classify_no_response():
    assert V.classify("json", None, {}, b"") == (False, "", "no response")


def test_gzip_bodies_are_decoded():
    import gzip
    assert V._decode(gzip.compress(b'{"a":1}'), "") == b'{"a":1}'


@pub
def test_published_shards_shape():
    idx = json.loads((DATA / "index.json").read_text())
    ids, n_ok = set(), 0
    legacy = {a["id"]: a for a in json.loads((ROOT / "civicbot" / "data" / "free_apis.json").read_text())["apis"]}
    for s in idx["shards"]:
        d = json.loads((DATA / s["file"]).read_text())
        assert d["count"] == len(d["apis"]) == s["count"] and d["continent"] == s["continent"]
        for e in d["apis"]:
            assert e["id"] not in ids
            ids.add(e["id"])
            for k in ("name", "category", "kind", "auth", "continent", "example", "source", "verified", "verified_at", "last_status", "tier", "check_type"):
                assert k in e, (e["id"], k)
            assert e["continent"] == d["continent"] and e["continent"] in geo.CONTINENTS
            assert e["auth"] in ("none", "free-key", "demo-key") and e["source"] in idx["sources"]
            assert e["example"].startswith(("http://", "https://"))
            if e["source"] != "civicbot":
                assert not S.has_credential(e["example"]), e["id"]
                assert e["last_status"] == "ok"
            else:
                assert e["example"] == legacy[e["id"]]["example"]
            n_ok += e["last_status"] == "ok"
    assert set(legacy) <= ids, "every v0.4 entry is carried into the global directory"
    assert n_ok == idx["ok"] and len(ids) == idx["count"]
    assert sum(idx["by_continent"].values()) == idx["ok"]
    assert idx["endpoint_verified"] + idx["docs_only"] == idx["ok"]
    failed = json.loads((ROOT / "directory" / "failed.json").read_text())
    assert failed["count"] == len(failed["failed"]) == idx["failed"]


@pub
def test_build_directory_site(tmp_path):
    (tmp_path / "llms.txt").write_text("# civicbot\n")
    info = _load("build_directory_site").write(tmp_path)
    g = (tmp_path / "grok-global.txt").read_text()
    assert "grok.txt" in g and "Never invent data" in g and info["assistant_ready"] > 0
    for f in tmp_path.glob("grok-apis-*.txt"):
        for line in f.read_text().splitlines():
            if not line.startswith("#"):
                assert line.count(" | ") == 6, (f.name, line)
                assert line.split(" | ")[6].startswith(P.PRE), (f.name, line)
                assert "GTFS" not in line.split(" | ")[1] or "GBFS" in line
    assert (tmp_path / "data" / "directory" / "index.json").exists()
    assert "Global free-API directory" in (tmp_path / "llms.txt").read_text()
    assert not (tmp_path / "grok.txt").exists(), "the directory builder never writes grok.txt"


# --- "Paste into Grok" prompts: every entry gets one, and it carries the verified URL -------------------------------

def _prompt_url(e: dict, skills: dict) -> str:
    """The URL a prompt must contain: the skill's verified sample URL for skill-backed entries, else the verified example."""
    sk = skills.get(e["id"]) if e.get("source") == "civicbot" else None
    return (sk["sample"]["url"] if sk and sk.get("sample") else sk["url"]) if sk else e["example"]


def _check_prompt(e: dict, skills: dict) -> None:
    p = e["grok_prompt"]
    assert p.startswith(P.PRE + " Using the "), e["id"]
    u = _prompt_url(e, skills)
    assert f"({u}" in p or f"(docs: {u})" in p or f"(docs: {u};" in p, (e["id"], p)
    assert e["name"] in p and "\n" not in p and len(p) <= 700, e["id"]
    t = e.get("grok_prompt_template")
    if t:
        assert t.startswith(P.PRE) and "{place}" in t and "{lat}" in t


def test_every_original_entry_has_a_prompt(tmp_path):
    _, skills = P._context()
    n = _load("build_directory_site").write_prompts(tmp_path)
    m = json.loads((tmp_path / "data" / "grok_prompts.json").read_text())["prompts"]
    legacy = json.loads((ROOT / "civicbot" / "data" / "free_apis.json").read_text())["apis"]
    assert n == len(legacy) == len(m)
    lengths = []
    for a in legacy:
        e = dict(a, source="civicbot", **m[a["id"]])
        _check_prompt(e, skills)
        lengths.append(len(e["grok_prompt"]))
    assert sorted(lengths)[len(lengths) // 2] <= 300, "most prompts stay short"
    assert any("grok_prompt_template" in v for v in m.values()), "location skills offer a {place} template"


def test_prompt_kinds_and_questions():
    base = dict(id="x", name="Demo", example="https://demo.example/a.json", category="Weather & climate", answers="Daily weather")
    assert "(https://demo.example/a.json)" in P.entry_prompts(dict(base))["grok_prompt"]
    assert "needs a free key" in P.entry_prompts(dict(base, auth="free-key"))["grok_prompt"]
    assert "(docs: https://demo.example/a.json)" in P.entry_prompts(dict(base, tier="docs"))["grok_prompt"]
    assert "GTFS zip" in P.entry_prompts(dict(base, kind="gtfs"))["grok_prompt"]
    assert "protobuf" in P.entry_prompts(dict(base, kind="gtfs-rt"))["grok_prompt"]
    assert "in Lisbon" in P.entry_prompts(dict(base, kind="gbfs", city="Lisbon"))["grok_prompt"]
    assert "in Portugal" in P.entry_prompts(dict(base, country="PT"))["grok_prompt"]


def test_grok_pack_json_has_prompts_and_grok_txt_is_unchanged(tmp_path):
    gp = _load("build_grok_pack")
    gp.write(tmp_path, "2026-10-10")
    pack = json.loads((tmp_path / "data" / "grok-pack.json").read_text())
    for s in pack["skills"]:
        assert s["grok_prompt"].startswith(P.PRE) and s["sample"]["url"] in s["grok_prompt"]
    for a in pack["apis"]:
        assert a["grok_prompt"].startswith(P.PRE)
    assert "grok_prompt" not in (tmp_path / "grok.txt").read_text()


@pub
def test_every_published_entry_has_a_prompt_with_its_verified_url():
    _, skills = P._context()
    idx = json.loads((DATA / "index.json").read_text())
    n = 0
    for s in idx["shards"]:
        for e in json.loads((DATA / s["file"]).read_text())["apis"]:
            _check_prompt(e, skills)
            n += 1
    assert n == idx["count"]


def test_redirect_targets_are_scrubbed():
    u = "https://x.example/a?apiKey=abc123&X-Amz-Security-Token=zz&X-Amz-Signature=ff&sig=1&page=2"
    out = S.scrub_url(u)
    assert "abc123" not in out and "zz" not in out and "ff" not in out and "page=2" in out and out.count("REDACTED") == 4
