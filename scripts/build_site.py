"""Assemble the GitHub Pages site into _site/ (used by .github/workflows/pages.yml; also handy locally).

    python scripts/build_site.py && python -m http.server -d _site 8000
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from civicbot.skills import default_catalog  # noqa: E402

CORE_TRY = {"open-meteo-weather": "what's the weather", "mbta-next-trains": "next train at place-pktrm",
            "chicago-311-nearby": "311 requests near 121 N LaSalle St, Chicago", "carris-metropolitana-arrivals": "carris 020429"}


def main(out: str = "_site") -> int:
    dst = ROOT / out
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ROOT / "site", dst)
    (dst / "data").mkdir()
    for f in ("free_apis.json", "endpoints.json"):
        shutil.copy(ROOT / "civicbot" / "data" / f, dst / "data" / f)
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_skills", ROOT / "scripts" / "free_apis" / "check_skills.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tries = {**CORE_TRY, **{k: v[0] for k, v in mod.SAMPLES.items()}}
    cat = default_catalog()
    skills = []
    for n in cat.names():
        s, e = cat.get(n), cat.entry(n)
        skills.append({"name": n, "title": s.get("title", n), "description": s["description"], "free": e.get("free", False),
                       "api_id": s.get("api_id", ""), "domains": s["allowed_domains"], "try": tries.get(n, n)})
    (dst / "data" / "skills.json").write_text(json.dumps({"skills": skills}, ensure_ascii=False, indent=1) + "\n")
    (dst / ".nojekyll").write_text("")
    print(f"built {dst} ({len(skills)} skills)")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
