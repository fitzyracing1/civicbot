"""Tests for scripts/build_grok_pack.py (the "civicbot for Grok" pack). Offline: nothing is fetched."""
import importlib.util
import json
import re
import urllib.parse
from pathlib import Path

import pytest

from civicbot.skills import default_catalog
from civicbot.skills.runner import SkillRunner

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_grok_pack", ROOT / "scripts" / "build_grok_pack.py")
gp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gp)
NOW = 1_791_000_000.0  # fixed clock for date tokens


@pytest.fixture(scope="module")
def pack():
    return gp.build_pack("2026-10-10")


def _free_names():
    cat = default_catalog()
    return [n for n in cat.names() if cat.entry(n).get("free")]


def test_every_free_catalog_skill_is_in_the_pack(pack):
    assert [s["name"] for s in pack["skills"]] == _free_names()
    assert len(pack["skills"]) >= 30


def test_templates_use_only_known_tokens(pack):
    for s in pack["skills"]:
        assert s["url"].startswith("https://"), s["name"]
        assert urllib.parse.urlsplit(s["url"]).hostname in default_catalog().get(s["name"])["allowed_domains"]
        for t in s["tokens"]:
            assert t in s["inputs"] or t in ("lat", "lng", "today", "now_unix") or re.fullmatch(r"days_ago_\d+", t), (s["name"], t)
        assert "|" not in "".join(re.findall(r"\{[^}]*\}", s["url"])), "filters must not leak into templates"
        if s["needs_location"]:
            assert {"lat", "lng"} <= set(s["tokens"]), s["name"]


@pytest.mark.parametrize("name", _free_names())
def test_filled_template_equals_what_the_robot_would_request(name):
    """The pack URL, filled with the sample values, is the exact request SkillRunner.build() makes."""
    cat = default_catalog()
    spec = cat.get(name)
    sample = gp._samples()[name]
    vals = gp.sample_values(spec, sample, now=NOW)
    url = gp.fill(gp.url_template(spec), vals)
    text, loc = sample
    kw = {"lat": loc[1], "lng": loc[2], "home_city": loc[0]} if loc else {}
    runner = SkillRunner(fetcher=None)
    call = runner.build(spec, runner.context(spec, text, now=NOW, **kw))
    got = urllib.parse.urlsplit(url)
    assert f"{got.scheme}://{got.netloc}{urllib.parse.unquote(got.path)}" == urllib.parse.unquote(call["url"])
    want = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in call["params"].items()}
    assert dict(urllib.parse.parse_qsl(got.query, keep_blank_values=True)) == want


def test_fill_encodes_values():
    t = "https://x.example/a/{site}?q={title}&p={lat},{lng}"
    u = gp.fill(t, {"site": "a b/c", "title": "War & Peace", "lat": 1.5, "lng": -2})
    assert u == "https://x.example/a/a%20b%2Fc?q=War%20%26%20Peace&p=1.5,-2"


def test_token_clash_is_rejected():
    spec = {"name": "t", "request": {"base_url": "https://x.example", "path": "/{inputs.city}",
                                     "params": {"c": "{owner.home_city}"}}}
    with pytest.raises(ValueError):
        gp.url_template(spec)


def test_pack_has_no_keys_or_keyed_apis(pack):
    blob = json.dumps(pack).lower()
    for bad in ("api_key=", "key=mw9s", "demo_key", "token=", "secret"):
        assert bad not in blob, bad
    ids = {a["id"] for a in pack["apis"]}
    assert not {"openaq", "open-charge-map", "bart-legacy", "nasa-neows"} & ids
    assert len(pack["apis"]) >= 100


def test_open311_cities_match_endpoints(pack):
    eps = json.loads((ROOT / "civicbot" / "data" / "endpoints.json").read_text())
    assert [c["id"] for c in pack["open311"]["cities"]] == [e["id"] for e in eps["endpoints"]]
    for c in pack["open311"]["cities"]:
        assert c["submit"].startswith("https://"), c["id"]
        assert not c["services"] or c["services"].endswith("/services.json")


def test_text_files(tmp_path):
    info = gp.write(tmp_path, "2026-10-10")
    txt = (tmp_path / "grok.txt").read_text()
    assert info["bytes"]["grok.txt"] < 30_000, "keep grok.txt small enough for an assistant to read in one go"
    for must in ("NEVER file", "Never invent", "Data: <source>", "grok-apis.txt", "seeclickfix.com/open311/v2/services.json"):
        assert must in txt, must
    for s in gp.build_pack("2026-10-10")["skills"]:
        assert f"url: {s['url']}" in txt
    ci = (tmp_path / "grok-instructions.txt").read_text()
    assert len(ci) < 1000 and "grok.txt" in ci and "never file" in ci
    proj = (tmp_path / "grok-project.txt").read_text()
    assert len(proj) < 1500 and "never file" in proj
    assert (tmp_path / "llms.txt").read_text().startswith("# civicbot\n\n> ")
    apis = (tmp_path / "grok-apis.txt").read_text().splitlines()
    assert sum(1 for line in apis if not line.startswith("#")) == info["apis"]
    assert json.loads((tmp_path / "data" / "grok-pack.json").read_text())["version"] == 1


def test_build_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    gp.write(a, "2026-10-10")
    gp.write(b, "2026-10-10")
    for f in ("grok.txt", "grok-apis.txt", "llms.txt", "data/grok-pack.json"):
        if f == "data/grok-pack.json":  # sample URLs carry today's date tokens; compare the rest
            ja, jb = (json.loads((x / f).read_text()) for x in (a, b))
            for j in (ja, jb):
                for s in j["skills"]:
                    s.pop("sample")
            assert ja == jb
        else:
            assert (a / f).read_text() == (b / f).read_text(), f


def test_site_build_includes_pack(tmp_path):
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "site"
    assert mod.main(str(out)) == 0
    for f in ("grok.txt", "llms.txt", "grok-apis.txt", "grok.html", "assets/grok.js", "data/grok-pack.json"):
        assert (out / f).exists(), f
