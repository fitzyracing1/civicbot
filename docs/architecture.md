# Architecture

| Path | Role |
|---|---|
| `civicbot/open311.py` | Open311 GeoReport v2 client; `create_request` defaults to `dry_run=True` |
| `civicbot/registry.py`, `data/endpoints.json` | bundled registry of verified endpoints |
| `civicbot/resolver.py`, `geocode.py` | address/location → city endpoint |
| `civicbot/transit.py` | transit feeds (GTFS-realtime via the optional `transit` extra) |
| `civicbot/robot/` | `engine`, `intent`, `matcher`, `replies`, `profile`, `fleet`, `x_adapter` |
| `civicbot/x/` | X OAuth 2.0 PKCE (`oauth`, `connect`), `tokens`, `api` |
| `civicbot/skills/` | skill specs (`schema.json`, `spec`, `openapi` import), `router`, `runner`, `fetch`, `template`, `builtin` |
| `civicbot/catalog/` | community skill catalog; `catalog/free/` holds keyless skills |
| `civicbot/secrets.py` | per-robot encrypted secrets (optional `secure` extra) |
| `civicbot/offline.py`, `data/fixtures.json` | offline sample responses |
| `directory/`, `scripts/directory/`, `scripts/free_apis/` | builder and verifier for the free-API directory |
| `site/`, `scripts/build_site.py` | GitHub Pages site and playground |
| `tests/` | pytest suites; `live` marker for network tests |

Workflows: `ci.yml` (tests), `directory-recheck.yml`, `pages.yml`, `release.yml`. Background research notes are in `docs/research.md`.
