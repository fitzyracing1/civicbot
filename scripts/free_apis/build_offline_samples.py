"""Pack tests/fixtures/free_skills/*.json into civicbot/data/free_skill_samples.json for `--offline` demos.

Each sample is matched by host + path + the set of query-parameter names the skill sends.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from civicbot.skills import SkillRunner, validate_spec  # noqa: E402
from civicbot.skills.catalog import free_catalog_dir  # noqa: E402


def main() -> int:
    runner = SkillRunner(fetcher=None)
    out = {}
    for f in sorted((ROOT / "tests" / "fixtures" / "free_skills").glob("*.json")):
        fx = json.loads(f.read_text())
        spec = validate_spec(json.loads((free_catalog_dir() / "skills" / f"{fx['skill']}.json").read_text()))
        ctx = runner.context(spec, fx["text"], home_city=fx["home_city"], default_lat=fx["lat"], default_lng=fx["lng"])
        call = runner.build(spec, ctx)
        host, path = call["url"].split("/", 3)[2], "/" + call["url"].split("/", 3)[3]
        if "{" in spec["request"]["path"]:  # inputs in the path: match the fixed prefix only
            path = spec["request"]["path"].split("{", 1)[0]
        out[fx["skill"]] = {"host": host, "path": path, "prefix": "{" in spec["request"]["path"],
                            "keys": sorted(call["params"]), "recorded": fx["recorded"], "response": fx["response"]}
    dst = ROOT / "civicbot" / "data" / "free_skill_samples.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(out)} samples -> {dst} ({dst.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
