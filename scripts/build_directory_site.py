"""Add the global free-API directory to the built site (run by scripts/build_site.py after everything else).

Copies directory/data/*.json to _site/data/directory/ and writes assistant-readable text files:
  grok-global.txt            how to use the regional files + links with counts
  grok-apis-<continent>.txt  keyless, endpoint-verified, text/JSON APIs for one continent
  grok-apis-<cc>.txt         the same for one country (ISO 3166 alpha-2, lowercase)
and appends a short "Global directory" section to llms.txt. grok.txt is not touched.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from directory import geo, prompts, sources  # noqa: E402

SITE = "https://fitzyracing1.github.io/civicbot"
DATA = ROOT / "directory" / "data"
BINARY_KINDS = {"gtfs", "gtfs-rt"}


def load() -> tuple:
    idx = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    apis = []
    for s in idx["shards"]:
        apis += json.loads((DATA / s["file"]).read_text(encoding="utf-8"))["apis"]
    return idx, apis


def assistant_ready(e: dict) -> bool:
    """What an assistant can actually open and read: keyless, endpoint-verified, currently OK, text/JSON."""
    return (e.get("last_status") == "ok" and e.get("tier") == "endpoint" and e.get("auth") == "none"
            and e.get("kind") not in BINARY_KINDS)


def line(e: dict) -> str:
    where = e.get("city") or e.get("region") or ""
    url = e.get("resolved") or e["example"]
    return " | ".join(x.replace("|", "/").replace("\n", " ") for x in
                      (e["id"], e["name"], e["category"], e.get("answers", ""), where, url, e.get("grok_prompt", "")))


HEAD = """# civicbot global free-API directory: {title}
# {site}/{fname}  ·  generated {date}  ·  {n} keyless APIs, each called live on its verified date
# Each line: id | name | category | answers | place | example GET URL | ready-to-paste Grok prompt
# Open the example URL, adjusting its query to the question. Read-only GET only: never post, file or log in.
# Answer briefly with the numbers, the time of the data and "Data: <name>". If a URL fails, say so; never invent data.
# Respect each provider's limits and terms. Full directory with docs links: {site}/directory.html
"""


def write_prompts(out: Path) -> int:
    """data/grok_prompts.json: id -> 'Paste into Grok' prompt (+ {place} template) for the original 120 (apis.html)."""
    legacy = prompts.apply(sources.from_civicbot())
    m = {e["id"]: {k: e[k] for k in ("grok_prompt", "grok_prompt_template") if k in e} for e in legacy}
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "data" / "grok_prompts.json").write_text(json.dumps({"prefix": prompts.PRE, "prompts": m}, ensure_ascii=False,
                                                               separators=(",", ":")), encoding="utf-8")
    return len(m)


def write(out: Path) -> dict:
    idx, apis = load()
    prompts.apply(apis)  # recompute so wording changes need no re-verification (URLs are the verified ones)
    ddir = out / "data" / "directory"
    ddir.mkdir(parents=True, exist_ok=True)
    for f in DATA.glob("*.json"):
        shutil.copy(f, ddir / f.name)
    for s in idx["shards"]:
        d = json.loads((DATA / s["file"]).read_text(encoding="utf-8"))
        d["apis"] = prompts.apply(d["apis"])
        (ddir / s["file"]).write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    ready = [e for e in apis if assistant_ready(e)]
    date = idx["generated"]
    files = {}
    conts = []
    for cont in geo.CONTINENTS:
        mine = [e for e in ready if e["continent"] == cont]
        if not mine:
            continue
        fname = f"grok-apis-{geo.slug(cont)}.txt"
        files[fname] = HEAD.format(title=cont, site=SITE, fname=fname, date=date, n=len(mine)) + "\n".join(map(line, mine)) + "\n"
        conts.append((cont, fname, len(mine)))
    countries = []
    for cc in sorted({e["country"] for e in ready if e.get("country")}):
        mine = [e for e in ready if e.get("country") == cc]
        fname = f"grok-apis-{cc.lower()}.txt"
        title = f"{geo.country_name(cc)} ({cc})"
        files[fname] = HEAD.format(title=title, site=SITE, fname=fname, date=date, n=len(mine)) + "\n".join(map(line, mine)) + "\n"
        countries.append((cc, geo.country_name(cc), fname, len(mine)))
    g = [f"# civicbot global free-API directory for AI assistants",
         f"# {SITE}/grok-global.txt  ·  generated {date}",
         "",
         f"{len(ready)} free, keyless APIs that answer with JSON, XML or text, out of {idx['ok']} verified directory entries",
         "(the rest are binary transit feeds, APIs needing a free key, or APIs whose docs were reachable but whose",
         "endpoint is not yet tested; those are on the website only).",
         "",
         "HOW TO USE",
         f"1. For civic questions (weather alerts, air, transit, 311...) use {SITE}/grok.txt first: it has ready-made",
         "   URL templates. Use this directory when grok.txt has nothing for the place or topic.",
         "2. Open the file for the user's country below (or continent, or Global for worldwide APIs).",
         "3. Pick the line that fits, open its example URL (adjust the query), read it, answer briefly with the source.",
         "4. Read-only GET requests only. Never file a 311 report, post, buy, or log in for the user. Never invent data.",
         "",
         "BY CONTINENT"]
    g += [f"- {c}: {SITE}/{f} ({n})" for c, f, n in conts]
    g += ["", "BY COUNTRY (ISO code)"]
    g += [f"- {cc} {name}: {SITE}/{f} ({n})" for cc, name, f, n in countries]
    g += ["", f"Machine-readable index and shards: {SITE}/data/directory/index.json", ""]
    files["grok-global.txt"] = "\n".join(g)
    for name, body in files.items():
        (out / name).write_text(body, encoding="utf-8")
    llms = out / "llms.txt"
    if llms.exists():
        extra = (f"\n## Global free-API directory\n"
                 f"- [grok-global.txt]({SITE}/grok-global.txt): {len(ready)} keyless APIs by continent and country, as text files.\n"
                 f"- [Global directory]({SITE}/directory.html): all {idx['ok']} verified entries with filters.\n"
                 f"- [index.json]({SITE}/data/directory/index.json): counts and links to per-continent JSON shards.\n")
        llms.write_text(llms.read_text(encoding="utf-8") + extra, encoding="utf-8")
    write_prompts(out)
    return {"assistant_ready": len(ready), "continent_files": len(conts), "country_files": len(countries)}


if __name__ == "__main__":
    print(write(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_site"))
