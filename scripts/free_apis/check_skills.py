"""Live read-only check of every free catalog skill; optionally (re)record the mocked-test fixtures.

    CIVICBOT_SSRF_ALLOW_NETS=... python scripts/free_apis/check_skills.py [--record] [skill ...]

One real GET per skill (through SafeFetcher, same rules as a robot). With --record, the API response and the
sample question are saved to tests/fixtures/free_skills/<skill>.json; tests/test_free_skills.py replays them offline.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from civicbot.skills import SafeFetcher, SkillRunner, validate_spec  # noqa: E402
from civicbot.skills.catalog import Catalog, free_catalog_dir  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "free_skills"
BLOOM = ("Bloomington, IN", 39.1653, -86.5264)
LISBON = ("Lisbon", 38.7223, -9.1393)
SAMPLES = {
    "open-meteo-tomorrow": ("weather tomorrow", BLOOM),
    "air-quality": ("how's the air quality", BLOOM),
    "uv-index": ("uv index today", BLOOM),
    "sun-times": ("when is sunset", BLOOM),
    "marine-waves": ("wave height", ("Cascais", 38.6913, -9.4215)),
    "elevation": ("elevation here", BLOOM),
    "uk-carbon-intensity": ("uk grid carbon intensity", None),
    "ipma-forecast": ("ipma forecast", None),
    "nws-alerts": ("any alerts", BLOOM),
    "earthquakes-near": ("any earthquakes", ("Anchorage", 61.2181, -149.9003)),
    "emsc-earthquakes": ("emsc earthquake", LISBON),
    "active-storms": ("any tropical storms", None),
    "natural-events": ("natural events", None),
    "fema-disasters": ("fema disasters in tx", None),
    "river-flow": ("river level 01646500", None),
    "tides-today": ("when is high tide", None),
    "mbta-alerts": ("mbta alerts", None),
    "tube-status": ("tube status", None),
    "seeclickfix-nearby": ("open issues near here", ("New Haven, CT", 41.3083, -72.9259)),
    "nyc-311-nearby": ("nyc 311 near me", ("Lower Manhattan", 40.7128, -74.0060)),
    "census-district": ("what district am I in", BLOOM),
    "zip-lookup": ("zip code 47401", None),
    "wikipedia-nearby": ("places near me", LISBON),
    "moon-phase": ("next full moon", None),
    "public-holidays": ("next holidays in PT", None),
    "currency-convert": ("exchange rate usd to eur", None),
    "wikipedia-summary": ("wiki Lisbon", None),
    "book-lookup": ("book the power broker", None),
    "food-recalls": ("latest food recalls", None),
    "vehicle-recalls": ("recalls 2018 honda civic", None),
    "food-barcode": ("barcode 3017624010701", None),
    "iss-location": ("where is the iss", None),
    "next-launch": ("next rocket launch", None),
}


def main(argv) -> int:
    record = "--record" in argv
    only = {a for a in argv if not a.startswith("--")}
    cat = Catalog(free_catalog_dir()) if (free_catalog_dir() / "index.json").exists() else None
    files = sorted((free_catalog_dir() / "skills").glob("*.json"))
    captured = {}

    class Recorder(SafeFetcher):
        def request(self, *a, **k):
            res = super().request(*a, **k)
            captured["data"] = res.data
            return res

    runner = SkillRunner(Recorder())
    bad = 0
    for f in files:
        spec = validate_spec(json.loads(f.read_text()))
        name = spec["name"]
        if only and name not in only:
            continue
        if name not in SAMPLES:
            print(f"?? {name}: no sample question"); bad += 1; continue
        text, loc = SAMPLES[name]
        home, lat, lng = loc if loc else ("", None, None)
        captured.clear()
        log = []
        t0 = time.monotonic()
        try:
            ctx = runner.context(spec, text, home_city=home, default_lat=lat, default_lng=lng)
            replies = runner.run_read(spec, ctx, log)
            ok = True
        except Exception as e:  # noqa: BLE001
            replies, ok = [f"{type(e).__name__}: {e}"], False
            bad += 1
        ms = int((time.monotonic() - t0) * 1000)
        print(("OK " if ok else "FAIL ") + f"{name} ({ms} ms): {replies[0][:230]}")
        if record and ok:
            (FIX / f"{name}.json").write_text(json.dumps({
                "skill": name, "text": text, "home_city": home, "lat": lat, "lng": lng, "now": ctx.now,
                "recorded": time.strftime("%Y-%m-%d"), "response": captured.get("data")}, ensure_ascii=False) + "\n")
        time.sleep(0.5)
    _ = cat
    print(f"{len(files)} specs, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
