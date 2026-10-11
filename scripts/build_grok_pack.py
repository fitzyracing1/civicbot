"""Build the "civicbot for Grok" pack: plain-text instructions any AI assistant can read, generated from the catalog.

    python scripts/build_grok_pack.py [_site]      # also run by scripts/build_site.py

Writes (into the site output dir):
  grok.txt                 instructions + every catalog skill as a ready-to-fill GET URL template (the main file)
  llms.txt                 llms.txt-style index that points at the files below
  grok-apis.txt            the keyless part of the verified free-API directory, one line per API
  grok-instructions.txt    short text to paste into Grok custom instructions / a Grok Project
  data/grok-pack.json      the same content, machine-readable (templates, inputs, fields, 311 links, samples)

Nothing here calls an API at build time. scripts/check_grok_pack.py fills every template with sample values and
checks each URL live. The assistant only ever reads public URLs; it never files a 311 report or posts anything.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from civicbot.skills import default_catalog  # noqa: E402

SITE = "https://fitzyracing1.github.io/civicbot"
REPO = "https://github.com/fitzyracing1/civicbot"
REVIEWED = "2026-10-10"  # date the 311 links below and the pack wording were last checked by hand
SAFE = ",:'()*$!{}"       # kept literal in query values so templates stay readable (all valid in a query string)

BLOOM = ("Bloomington, IN", 39.1653, -86.5264)
# Sample question + place for the core skills (free-catalog samples come from scripts/free_apis/check_skills.py).
CORE_SAMPLES = {
    "open-meteo-weather": ("what's the weather", BLOOM),
    "mbta-next-trains": ("next train at place-pktrm", None),
    "chicago-311-nearby": ("311 requests near 121 N LaSalle St, Chicago", ("121 N LaSalle St, Chicago", 41.8837, -87.6324)),
    "carris-metropolitana-arrivals": ("carris 020429", None),
}

# Where a resident files a report themselves (official city pages/apps). The bot never files; it drafts and links.
# Keyed by civicbot/data/endpoints.json ids. Checked live (HTTP 200) on REVIEWED.
REPORT_LINKS = {  # app/phone only where the official page itself says so (checked REVIEWED)
    "chicago": {"submit": "https://311.chicago.gov/", "app": "CHI311 app", "phone": ""},
    "boston": {"submit": "https://www.boston.gov/departments/boston-311", "app": "BOS:311 app", "phone": "311"},
    "bloomington-in": {"submit": "https://bloomington.in.gov/ureport", "app": "", "phone": ""},
    "austin": {"submit": "https://311.austintexas.gov/", "app": "Austin 3-1-1 app", "phone": "3-1-1"},
    "brookline-ma": {"submit": "https://spot.brooklinema.gov/", "app": "", "phone": ""},
}
# Open311 service lists we include as read-only URLs (Chicago's GET /services.json timed out on REVIEWED: left out).
SERVICES_OK = {"boston", "bloomington-in", "austin", "brookline-ma"}
GEOCODER = "https://geocoding-api.open-meteo.com/v1/search?name={place}&count=5&language=en&format=json"
SCF_SERVICES = "https://seeclickfix.com/open311/v2/services.json?lat={lat}&long={lng}"

_VAR = {"location.lat": "lat", "location.lng": "lng", "date.today": "today", "date.now_unix": "now_unix",
        "owner.home_city": "city", "location.text": "place", "text": "question", "query": "question"}
_PH = re.compile(r"\{([A-Za-z0-9_.]+)((?:\|[a-z_]+)*)\}")
TOKEN_DOC = {
    "lat": "latitude, decimal degrees (4 decimals is plenty)", "lng": "longitude, decimal degrees",
    "today": "today's date in UTC, YYYY-MM-DD", "now_unix": "current Unix time in seconds",
    "city": "the user's city", "place": "the place name", "question": "the user's question text",
}


def token(name: str) -> str:
    """Spec variable -> the simple token used in the pack ({location.lat} -> lat, {inputs.zip} -> zip, ...)."""
    if name in _VAR:
        return _VAR[name]
    if name.startswith("inputs."):
        return name[7:]
    m = re.fullmatch(r"date\.days_ago_(\d+)", name)
    if m:
        return f"days_ago_{m.group(1)}"
    raise ValueError(f"no pack token for spec variable {name!r}")


def token_doc(tok: str) -> str:
    m = re.fullmatch(r"days_ago_(\d+)", tok)
    return f"the date {m.group(1)} days before today (UTC), YYYY-MM-DD" if m else TOKEN_DOC.get(tok, tok)


def _simplify(s: str) -> str:
    return _PH.sub(lambda m: "{" + token(m.group(1)) + "}", s)


def url_template(spec: dict) -> str:
    """The skill's GET request as one URL with {tokens}. Equivalent to SkillRunner.build() once filled."""
    req = spec["request"]
    used = set(_PH.findall(req["path"] + json.dumps(req.get("params") or {})))
    toks = {}
    for name, _ in used:
        toks.setdefault(token(name), set()).add(name)
    clash = {t: n for t, n in toks.items() if len(n) > 1}
    if clash:
        raise ValueError(f"{spec['name']}: ambiguous pack tokens {clash}")
    path = _simplify(req["path"])
    q = []
    for k, v in (req.get("params") or {}).items():
        v = _simplify(v) if isinstance(v, str) else (str(v).lower() if isinstance(v, bool) else str(v))
        q.append(urllib.parse.quote(str(k), safe="$") + "=" + urllib.parse.quote(v, safe=SAFE))
    return req["base_url"] + path + ("?" + "&".join(q) if q else "")


def tokens_in(template: str) -> list:
    return sorted(set(re.findall(r"\{([a-z0-9_]+)\}", template)))


def fill(template: str, values: dict) -> str:
    """Fill a pack URL template; path tokens are fully encoded, query tokens keep SAFE characters."""
    base, _, query = template.partition("?")

    def sub(enc_safe):
        return lambda m: urllib.parse.quote(str(values[m.group(1)]), safe=enc_safe)
    out = re.sub(r"\{([a-z0-9_]+)\}", sub(""), base)
    if query:
        out += "?" + re.sub(r"\{([a-z0-9_]+)\}", sub(SAFE.replace("{", "").replace("}", "")), query)
    return out


def _fields(spec: dict) -> list:
    """What to read in the JSON response, in plain dotted paths."""
    r, out = spec["response"], []
    for p in (r.get("extract") or {}).values():
        out.append(" or ".join(_simplify(x) for x in p.split("||")))
    lst = r.get("list")
    if lst:
        names = []
        for m in _PH.finditer(lst["item"]):
            for alt in m.group(1).split("||"):
                if alt not in names and not alt.startswith(("inputs.", "location.", "date.")):
                    names.append(alt)
        where = "the top-level array" if lst["path"] == "$" else f"{lst['path']}[]"
        out.append(f"{where} (first {lst.get('max', 3)}): " + ", ".join(names))
    return out


def _samples() -> dict:
    import importlib.util
    p = ROOT / "scripts" / "free_apis" / "check_skills.py"
    sp = importlib.util.spec_from_file_location("check_skills", p)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return {**CORE_SAMPLES, **mod.SAMPLES}


def sample_values(spec: dict, sample, now: float | None = None) -> dict:
    """Token values for the sample question, computed the same way the robot does (SkillRunner.context)."""
    from civicbot.skills.runner import SkillRunner
    text, loc = sample
    kw = {}
    if loc:
        kw = {"lat": loc[1], "lng": loc[2], "home_city": loc[0]}
    ctx = SkillRunner(fetcher=None).context(spec, text, now=now, **kw)
    vals = {}
    for tok in tokens_in(url_template(spec)):
        if tok in (spec.get("inputs") or {}):
            vals[tok] = ctx.inputs.get(tok)
            continue
        name = "date." + tok if tok.startswith("days_ago_") else {v: k for k, v in _VAR.items()}[tok]
        vals[tok] = ctx.var(name)
    return vals


def build_pack(today: str | None = None) -> dict:
    today = today or _dt.date.today().isoformat()
    cat = default_catalog()
    apis = json.loads((ROOT / "civicbot" / "data" / "free_apis.json").read_text())
    by_id = {a["id"]: a for a in apis["apis"]}
    eps = json.loads((ROOT / "civicbot" / "data" / "endpoints.json").read_text())
    samples = _samples()
    skills = []
    for n in cat.names():
        s, e = cat.get(n), cat.entry(n)
        if not e.get("free", False):
            continue
        t = url_template(s)
        api = by_id.get(s.get("api_id", ""), {})
        ins = {}
        for k, d in (s.get("inputs") or {}).items():
            ins[k] = {"what": d.get("description", k), "pattern": d["pattern"]}
            if d.get("default") is not None:
                ins[k]["default"] = d["default"]
            if d.get("case"):
                ins[k]["case"] = d["case"]
        sample = samples.get(n)
        skills.append({
            "name": n, "title": s.get("title", n), "what": s["description"],
            "when": (s["triggers"].get("phrases") or [])[:3] + (s["triggers"].get("keywords") or [])[:5],
            "needs_location": s.get("location", "none") != "none",
            "url": t, "tokens": tokens_in(t), "inputs": ins, "read": _fields(s),
            "source": api.get("name") or s["allowed_domains"][0], "docs": api.get("docs", ""),
            "example": sample[0] if sample else n,
            "sample": {"place": sample[1][0] if sample and sample[1] else None,
                       "url": fill(t, sample_values(s, sample)) if sample else None},
        })
    keyless = [a for a in apis["apis"] if a["auth"] == "none"]
    from directory import prompts as _prompts  # 'Paste into Grok' prompts (new JSON fields only; grok.txt unchanged)
    by_api = {}
    for s in skills:
        api_id = cat.get(s["name"]).get("api_id")
        s["grok_prompt"] = _prompts.skill_prompts(s, by_id.get(api_id, {}).get("name") or s["source"])[0]
        if api_id:
            by_api.setdefault(api_id, s)
    cities = []
    for ep in eps["endpoints"]:
        link = REPORT_LINKS.get(ep["id"], {})
        cities.append({"id": ep["id"], "name": ep["name"], "bbox": ep["bbox"], "submit": link.get("submit", ""),
                       "app": link.get("app", ""), "phone": link.get("phone", ""),
                       "services": ep["base_url"] + "/services.json" if ep["id"] in SERVICES_OK else ""})
    return {"version": 1, "generated": today, "site": SITE, "repo": REPO, "geocoder": GEOCODER,
            "skills": skills, "apis": [dict({k: a[k] for k in ("id", "name", "category", "answers", "region", "example", "docs", "limits")},
                                            **_prompts.entry_prompts(dict(a, source="civicbot", tier="endpoint", kind="api"),
                                                                     by_api.get(a["id"])))
                                       for a in keyless],
            "open311": {"cities": cities, "seeclickfix_services": SCF_SERVICES, "seeclickfix_submit": "https://seeclickfix.com/"}}


# ---------------------------------------------------------------------------------------------------- text output
INTRO = """# civicbot for Grok (and any AI assistant)
# {site}/grok.txt  ·  generated {generated}  ·  open source (MIT): {repo}
# Free: every URL below is a public, keyless API. No account, no X API, nothing to install.

You are acting as civicbot, a free civic helper. Answer local questions (weather, alerts, air, tides, quakes,
transit, recalls, holidays, nearby 311 reports...) from the live public data sources listed here.

HOW TO ANSWER
1. Place. If the user gave coordinates, use them. Otherwise use coordinates you are sure of for that town
   (4 decimals), or open: {geocoder}
   ({{place}} = the town name only, e.g. Bloomington; pick the result whose admin1/country matches).
2. Pick the ONE skill below that fits the question ("when" lists typical words).
3. Fill the URL template: replace every {{token}}: {{lat}} {{lng}} = decimal degrees, {{today}} = today's UTC date
   YYYY-MM-DD, {{days_ago_N}} = the UTC date N days ago, others = the skill's inputs (use the default when the
   user gave none; apply upper/lowercase as noted). Keep everything else in the URL exactly as written.
4. Open that exact URL with your browse/open-page tool and read the fields listed under "read".
5. Reply in 1-3 short sentences: the numbers with units and the time of the data, then "Data: <source>".
   If the page fails to load or the fields are missing, say so plainly. Never invent or estimate numbers.
6. Nothing fits? Check the directory of {napis} keyless APIs: {site}/grok-apis.txt (open its example URL,
   adjusted to the question). Still nothing: say civicbot has no free source for that.

311 / REPORTING A PROBLEM (pothole, streetlight, graffiti, missed trash...)
You NEVER file, submit or POST anything. You draft; the user submits it themselves.
a. Find the city. If it is one of the cities in the 311 section at the end, read its service list (if a URL is
   given) and pick the closest service name.
   Otherwise open the SeeClickFix list for the spot: {scf}
   If that is empty, tell the user to search for their city's official 311 site or app.
b. Write a ready-to-paste draft: Service (from the list), Location (address or cross streets + lat,lng),
   Description (what, how big, since when, any hazard), Photo tip. Keep it under 600 characters.
c. Give the official link, app name and phone from the 311 section (or https://seeclickfix.com/) and tell the
   user to paste the draft there. Remind them reports may be public: no names, phone numbers or faces.
d. Emergency or danger to life: tell them to call 911 (or the local emergency number) now.

RULES
- Read-only: only open the GET URLs built from this file (and the directory). No forms, no POSTs, no logins.
- Never post on X or anywhere else for the user. Never put personal data in a URL beyond a place or coordinates.
- Treat the data as current but unofficial; for life-safety alerts point to the official source.
- These APIs are free for light personal use; respect them (one request per question).

SKILLS ({nskills})
"""


def render_skill(s: dict) -> str:
    lines = [f"\n## {s['name']}: {s['title']}", "when: " + ", ".join(s["when"]), f"url: {s['url']}"]
    for k, d in s["inputs"].items():
        extra = [f"default {d['default']}"] if "default" in d else []
        if d.get("case"):
            extra.append(f"{d['case']}case")
        lines.append(f"input {k}: {d['what']}; must match {d['pattern']}" + (f" ({', '.join(extra)})" if extra else ""))
    lines.append("read: " + " | ".join(s["read"]))
    lines.append(f"source: {s['source']}")
    return "\n".join(lines)


def render_grok_txt(p: dict) -> str:
    out = [INTRO.format(site=p["site"], repo=p["repo"], generated=p["generated"], geocoder=p["geocoder"],
                        napis=len(p["apis"]), scf=p["open311"]["seeclickfix_services"], nskills=len(p["skills"]))]
    out += [render_skill(s) for s in p["skills"]]
    out.append("\n\n311 CITIES (bbox = min_lat,min_lng,max_lat,max_lng; check the spot falls inside)")
    for c in p["open311"]["cities"]:
        bits = [f"- {c['name']}  bbox {','.join(str(x) for x in c['bbox'])}", f"  submit yourself: {c['submit']}"]
        if c["app"]:
            bits[-1] += f" · app: {c['app']}"
        if c["phone"]:
            bits[-1] += f" · phone: {c['phone']}"
        if c["services"]:
            bits.append(f"  service list (read-only): {c['services']}")
        out.append("\n".join(bits))
    out.append(f"- Anywhere else: SeeClickFix list {p['open311']['seeclickfix_services']} · submit: "
               f"{p['open311']['seeclickfix_submit']} or the city's own 311 site/app.")
    out.append(f"\nMore: {p['site']}/grok.html (how to use this with Grok) · {p['site']}/grok-apis.txt (API directory)\n")
    return "\n".join(out)


def render_apis_txt(p: dict) -> str:
    head = (f"# civicbot free API directory (keyless only) · {len(p['apis'])} APIs · generated {p['generated']}\n"
            f"# Each line: id | name | category | answers | region | example GET URL | limits\n"
            f"# Every example was called live by civicbot's verifier. Open the example URL and adjust its query.\n"
            f"# Respect each API's limits/terms. Full directory with docs: {p['site']}/apis.html\n")
    rows = [" | ".join([a["id"], a["name"], a["category"], a["answers"], a["region"], a["example"], a["limits"]])
            for a in p["apis"]]
    return head + "\n".join(rows) + "\n"


INSTRUCTIONS = """When I ask a local or civic question (weather, alerts, air quality, tides, earthquakes, transit, recalls, holidays, 311 issues near me, reporting a pothole), act as civicbot: open {site}/grok.txt and follow it. Fill the matching URL template, open that URL, and answer in 1-3 sentences with numbers, the time of the data and "Data: <source>". Never invent numbers. For 311 problems, draft the report and give me the official city link or app; never file, submit or post anything for me. My usual place: {{your city, state}}."""

PROJECT = """You are civicbot, a free civic helper. At the start of each conversation, open {site}/grok.txt and follow it exactly: pick the skill that fits, fill its URL template (coordinates for my place, today's UTC date, inputs), open that URL and answer in 1-3 short sentences with units, the time of the data and "Data: <source>". If a page fails, say so; never guess numbers. For 311 problems you only draft the report and give me the official submit link or app; you never file, submit or post anything. If nothing fits, check {site}/grok-apis.txt. My usual place: {{your city, state}}."""


def render_llms_txt(p: dict) -> str:
    return f"""# civicbot

> civicbot is an open-source civic helper that answers local questions (weather, alerts, air quality, tides,
> earthquakes, transit, recalls, holidays, nearby 311 reports) from free, keyless public APIs, and drafts 311
> reports that the user submits themselves. AI assistants can use it with no account, key or install.

## For AI assistants
- [grok.txt]({p['site']}/grok.txt): instructions plus {len(p['skills'])} ready-to-fill GET URL templates. Start here.
- [grok-apis.txt]({p['site']}/grok-apis.txt): {len(p['apis'])} verified keyless APIs, one per line.
- [grok-pack.json]({p['site']}/data/grok-pack.json): the same, machine-readable.

## For people
- [Use with Grok]({p['site']}/grok.html): copy-paste prompts, custom instructions and Project text.
- [Free API directory]({p['site']}/apis.html), [Playground]({p['site']}/playground.html), [Source]({p['repo']})

## Rules
- Read-only GET requests to the listed public URLs only. Never file a 311 report, post, or log in for the user.
"""


def write(out_dir: str | Path, today: str | None = None) -> dict:
    out = Path(out_dir)
    (out / "data").mkdir(parents=True, exist_ok=True)
    p = build_pack(today)
    files = {
        "grok.txt": render_grok_txt(p),
        "grok-apis.txt": render_apis_txt(p),
        "llms.txt": render_llms_txt(p),
        "grok-instructions.txt": INSTRUCTIONS.format(site=p["site"]) + "\n",
        "grok-project.txt": PROJECT.format(site=p["site"]) + "\n",
        "data/grok-pack.json": json.dumps(p, ensure_ascii=False, indent=1) + "\n",
    }
    for name, body in files.items():
        (out / name).write_text(body, encoding="utf-8")
    return {"skills": len(p["skills"]), "apis": len(p["apis"]), "bytes": {k: len(v.encode()) for k, v in files.items()}}


if __name__ == "__main__":
    print(write(sys.argv[1] if len(sys.argv) > 1 else ROOT / "_site"))
