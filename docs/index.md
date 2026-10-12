# civicbot

civicbot is a Python package (v0.4.0, `pyproject.toml`) for personal robots that call city-operated APIs. The APIs include Open311 GeoReport v2 for 311 reports, transit feeds, and open data. Each owner brings their own robot X account. The robot reads mentions, resolves which city an address is in, picks a 311 service, prepares the request, and replies from that account.

**Dry-run by default.** It never files a real 311 request, sends a write-skill request, or posts to X unless you enable each one. The README calls the project an early prototype.

- Python ≥ 3.10, no required runtime dependencies. Optional extras: `transit` (gtfs-realtime-bindings), `secure` (cryptography), `dev`.
- Console script: `civicbot` (`civicbot.__main__:main`)
- Web playground and API directory: https://fitzyracing1.github.io/civicbot/

Pages: [Getting started](getting-started.md) · [Usage](usage.md) · [Architecture](architecture.md) · [Contributing](contributing.md)

CI (`.github/workflows/ci.yml`) runs `pytest -q -m "not live"`. A run is **lit** when it succeeds and **dark** otherwise.

MIT License. Copyright (c) 2026 Joshua Almeida
