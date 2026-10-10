"""Replay every free catalog skill against its recorded live response (tests/fixtures/free_skills)."""
import json
import pathlib

import pytest

from civicbot.robot.replies import Phraser
from civicbot.skills import SafeFetcher, SkillRouter, SkillRunner, default_catalog
from civicbot.skills.catalog import Catalog, free_catalog_dir
from civicbot.skills.template import URL_RE

FIX = pathlib.Path(__file__).parent / "fixtures" / "free_skills"
FREE = Catalog(free_catalog_dir())
DIRECTORY = json.loads((pathlib.Path(__file__).parents[1] / "civicbot" / "data" / "free_apis.json").read_text())


def test_every_free_skill_has_a_fixture():
    assert sorted(p.stem for p in FIX.glob("*.json")) == sorted(FREE.names())


@pytest.mark.parametrize("name", FREE.names())
def test_free_skill_replays_recorded_response(name):
    fx = json.loads((FIX / f"{name}.json").read_text())
    spec = FREE.get(name)
    calls = []

    def raw(method, url, headers, body, timeout, max_bytes):
        calls.append((method, url))
        return 200, {"Content-Type": "application/json"}, json.dumps(fx["response"]).encode()
    runner = SkillRunner(SafeFetcher(resolve=lambda h: ["93.184.216.34"], raw=raw, min_host_interval=0, allow_nets=[]))
    ctx = runner.context(spec, fx["text"], home_city=fx["home_city"], default_lat=fx["lat"], default_lng=fx["lng"],
                         now=fx["now"])
    log = []
    replies = runner.run_read(spec, ctx, log)
    assert calls and all(m == "GET" for m, _ in calls)
    assert calls[0][1].split("/")[2] in spec["allowed_domains"]
    for r in replies:
        assert r and not URL_RE.search(r) and "@" not in r
        assert len(Phraser("r").text(r)) <= 280


@pytest.mark.parametrize("name", FREE.names())
def test_sample_question_routes_to_its_skill(name):
    fx = json.loads((FIX / f"{name}.json").read_text())
    cat = default_catalog()
    skills = [cat.get(n) for n in cat.names()]
    route = SkillRouter().route(fx["text"].lower(), "help", skills)
    assert route and route.skill["name"] == name, (fx["text"], route and route.skill["name"])


def test_directory_shape_and_links():
    d = DIRECTORY
    assert 50 <= d["count"] == len(d["apis"]) <= 150
    ids = [a["id"] for a in d["apis"]]
    assert len(ids) == len(set(ids))
    assert set(d["categories"]) == {a["category"] for a in d["apis"]}
    names = set(default_catalog().names())
    for a in d["apis"]:
        for k in ("name", "category", "answers", "base_url", "docs", "limits", "verified", "auth", "cors"):
            assert k in a, (a["id"], k)
        assert a["auth"] in ("none", "demo-key", "free-key") and a["docs"].startswith("https://")
        assert a["verified"]["date"] == d["generated"]
        assert set(a["skills"]) <= names
    linked = {s for a in d["apis"] for s in a["skills"]}
    for n in FREE.names():
        assert n in linked, f"{n}: its api_id is not in the verified directory"
