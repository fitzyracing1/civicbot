"""'Paste into Grok' prompts: one short, self-contained prompt per directory entry, built from the data.

Every prompt starts with PRE (pointing Grok at grok.txt), names the API, includes the URL that was verified live
(or, for catalog skills, the skill's URL template filled for a sample place) and asks a natural question.
Skill-backed, location-aware entries also get a grok_prompt_template with {place} for the site's place box."""
from __future__ import annotations

PRE = "Use https://fitzyracing1.github.io/civicbot/grok.txt as your civicbot instructions."

CATQ = {
    "Weather & climate": "what's the weather{where} right now?",
    "Alerts & hazards": "are there any current alerts or events{where}?",
    "Air quality & environment": "what's the latest reading{where}?",
    "Transit": "what's the live service status or next departures{where}?",
    "Bikeshare & micromobility": "how many bikes or scooters are available{where} right now?",
    "Open data portals": "what are a few recent datasets{where}, and how do I query one?",
    "311 & service requests": "what kinds of problems can I report{where}?",
    "Statistics & economy": "what's the latest figure{where}?",
    "Money": "what's the latest rate?",
    "Health": "what does it say{where}? Summarize briefly.",
    "Science & research": "show me one recent result and what it means.",
    "Books, words & knowledge": "show me one result and summarize it.",
    "Sports & games": "what's the latest result?",
    "Animals & nature": "show me one result and summarize it.",
    "Sun, time & holidays": "what's the answer{where} for today?",
    "Geocoding & places": "what place does it return, with coordinates?",
    "Flights & space": "what's happening right now?",
    "Energy": "what's the latest figure{where}?",
    "Government & safety": "what's the latest{where}?",
    "Water, tides & marine": "what's the latest reading{where}?",
    "City open data": "what's the latest{where}?",
    "Portugal & EU": "what's the latest{where}?",
}


def _where(e: dict) -> str:
    place = e.get("city") or e.get("country_name") or ""
    if not place and e.get("country") and e["country"] != "EU":
        from . import geo
        place = geo.country_name(e["country"]) or ""
    return f" in {place}" if place else ""


def _short(text: str, n: int = 80) -> str:
    text = " ".join(str(text).split()).rstrip(".")
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def _q(e: dict) -> str:
    ans = e.get("answers") or ""
    if e.get("category") != "Open data portals" and 8 <= len(ans):
        a = _short(ans)
        w = _where(e)
        return f'what does it show for "{a}"{w if w[4:] not in ans else ""} right now? Summarize briefly.'
    q = CATQ.get(e.get("category", ""), "what does it return? Summarize the answer briefly.")
    return q.replace("{where}", _where(e))


def skill_prompts(skill: dict, api_name: str) -> tuple:
    """(prompt filled for the sample place, template with {place} or None) for a grok-pack skill."""
    ex = skill["example"]
    place = (skill.get("sample") or {}).get("place")
    url = (skill.get("sample") or {}).get("url") or skill["url"]
    prompt = f'{PRE} Using the {api_name} API ({url}), answer: "{ex}"' + (f" for {place}." if place else ".")
    tmpl = None
    if skill.get("needs_location"):
        tmpl = f'{PRE} Using the {api_name} API ({skill["url"]}, with {{lat}},{{lng}} for my place), answer: "{ex}" for {{place}}.'
    return prompt, tmpl


def entry_prompts(e: dict, skill: dict | None = None) -> dict:
    """grok_prompt (+ grok_prompt_template when a place can be filled in) for one directory entry."""
    if skill:
        p, t = skill_prompts(skill, e["name"])
        return {"grok_prompt": p, **({"grok_prompt_template": t} if t else {})}
    name, url, kind = e["name"], e["example"], e.get("kind", "api")
    if e.get("tier") == "docs":
        body = f"Using the {name} API (docs: {url}), find a keyless endpoint and show me one example result."
        if e.get("auth") == "free-key":
            body = f"Using the {name} API (docs: {url}; it needs a free key), what does it offer and how do I get a key?"
    elif e.get("auth") == "free-key":
        body = f"Using the {name} API ({url}; it needs a free key, so don't call it), what does it offer and how do I get a key?"
    elif kind == "gtfs":
        body = f"Using the {name} schedule feed ({url}, a GTFS zip), which agency and area does it cover? If you can't open zip files, say so."
    elif kind == "gtfs-rt":
        body = f"Using the {name} real-time feed ({url}, GTFS-RT protobuf), what does it report? If you can't read protobuf, say so."
    elif kind == "gbfs":
        body = f"Using the {name} feed ({url}), how many bikes or scooters are available{_where(e)} right now?"
    else:
        body = f"Using the {name} API ({url}), {_q(e)}"
    return {"grok_prompt": f"{PRE} {body}"}


def skill_map(pack: dict, catalog) -> dict:
    """api_id -> first grok-pack skill for that API (catalog order)."""
    out = {}
    for s in pack["skills"]:
        api = catalog.get(s["name"]).get("api_id")
        if api and api not in out:
            out[api] = s
    return out


_CTX: dict = {}


def _context() -> tuple:
    """(grok pack, api_id -> skill) built once from the catalog via scripts/build_grok_pack.py."""
    if not _CTX:
        import importlib.util
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location("build_grok_pack", root / "scripts" / "build_grok_pack.py")
        gp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gp)
        from civicbot.skills import default_catalog
        pack = gp.build_pack()
        _CTX["pack"], _CTX["skills"] = pack, skill_map(pack, default_catalog())
    return _CTX["pack"], _CTX["skills"]


def apply(entries: list) -> list:
    """Set grok_prompt (and grok_prompt_template where useful) on every entry, in place."""
    _, skills = _context()
    for e in entries:
        e.pop("grok_prompt_template", None)
        e.update(entry_prompts(e, skills.get(e["id"]) if e.get("source") == "civicbot" else None))
    return entries
