# Changelog

## Unreleased (data and site only, 2026-10-10): global free-API directory, batch 1

Strictly additive. These are unchanged:
- `civicbot/data/free_apis.json` (pinned by a test)
- the catalog skills, `grok.txt`, the Python package, and PR #2

Added:
- **`directory/`**: a global directory of verified free APIs and open feeds.
  - Sources: the 120 v0.4 entries, a curated list, MobilityData GBFS, Mobility Database GTFS/GTFS-RT (keyless),
    CKAN instances and public-apis, each with recorded provenance and license.
  - Published as per-continent JSON shards plus `index.json`. `failed.json` keeps every failure with its reason for retries.
- **`scripts/collect_apis.py`** and **`scripts/verify_apis.py`**: re-runnable collection and verification.
  - Polite live checks: identifying UA, 1.2 s spacing per host, 20 s timeout, one retry, recorded redirects. No keys used.
  - `--recheck` produces a dead-entry report.
- **`.github/workflows/directory-recheck.yml`**: a weekly re-check that opens or updates an issue. It never deletes.
- **Site**: `directory.html` with continent, country, category, key-type, kind, verification and CORS filters,
  pagination, and counts by region. Links were added to the nav, `apis.html` and `grok.html`.
- **Assistant files**: `grok-global.txt`, `grok-apis-<continent>.txt` and `grok-apis-<country>.txt` (keyless JSON/XML/text
  APIs only). A "Global directory" section was appended to `llms.txt`.
- **"Paste into Grok" copy bar on every API card** (the original 120 on `apis.html` and every global entry on
  `directory.html`). Each card shows a one-line prompt and a Copy button.
  - The prompt points Grok at `grok.txt`, names the API, includes its verified URL and asks a natural question.
  - Skill-backed APIs reuse the skill's URL template, filled for a sample place. With an optional place box, location
    skills use your place instead.
  - Prompts are generated at build time by `scripts/directory/prompts.py`. They appear as new fields:
    - `grok_prompt` and `grok_prompt_template` in the directory shards
    - `grok_prompt` in `data/grok-pack.json` skills and apis
    - `data/grok_prompts.json`
    - a new last column in `grok-apis-<region>.txt`
  - `grok.txt` is unchanged.

## Unreleased (site only, 2026-10-10): use civicbot free inside Grok

No Python package changes, so no new PyPI release. Website and scripts only:

- **Grok / LLM pack** (`scripts/build_grok_pack.py`, built into the Pages site by `scripts/build_site.py`):
  - `grok.txt`: instructions plus every free catalog skill as a GET URL template
  - `grok-apis.txt`: the keyless directory APIs
  - `llms.txt`
  - `grok-instructions.txt` and `grok-project.txt`
  - `data/grok-pack.json`
  - 311 is draft-and-link only.
- **Use with Grok page** (`site/grok.html`): copy buttons, example prompts, custom-instructions, Project and Automation
  text, a fallback for other assistants, and honest limits.
- **`scripts/check_grok_pack.py`**: live-checks every URL in the pack.
- **`tests/test_grok_pack.py`**: each filled template equals the request the Python robot builds.

## 0.4.0 (2026-10-10): free mode

Additive release: nothing was removed, and every v0.3 test passes unchanged.

- **Free mode**: turned on by `--free`, `CIVICBOT_FREE=1` or profile `plan: "free"`. The robot learns only free, keyless
  catalog skills (it refuses URLs and files), hides non-free installed skills, keeps 311 a dry run even when sending is
  enabled, and won't enable write skills.
- **Free catalog**: 33 new reviewed, sha256-pinned, read-only skills in `civicbot/catalog/free/`, combined with the core
  catalog by `default_catalog()` / `CatalogSet`. Each was checked live, and offline tests replay the recorded responses.
- **Free API directory**: `civicbot/data/free_apis.json` lists 120 free public APIs in 15 categories, each verified live on
  2026-10-10 (`scripts/free_apis/verify.py`). Browse it with `civicbot apis` or on the website.
- **Spec v1 additions (optional)**: `cost`, `api_id`, input `case`, `{inputs.x}` in extract paths, and the filters
  `rate`, `money`, `ms_date` and `ms_time`. Unknown filters are rejected.
- **CLI**: `civicbot chat` (REPL and `-c` one-shots, `--offline` sample data), `civicbot apis`, `simulate --free`,
  `connect --listen` (local OAuth callback on 127.0.0.1 with an encrypted token store) and `run --once` (one poll of your
  own robot, shadow by default; `--post` to really reply).
- **GitHub Pages site** (`site/`, deployed by `.github/workflows/pages.yml`): landing page, directory, in-browser
  playground and an honest "run your own robot" guide. No trackers.
- **GitHub Actions template**: `examples/github-actions/civicbot-robot.yml` runs your robot on a schedule (shadow by default).
- The core catalog specs are tagged `cost: free` with an `api_id`. The User-Agent is now `civicbot/0.4 (+repo URL)`.
- Release workflow: `skip-existing: true` on the PyPI upload.

## 0.3.0

- Bring-your-own-robot OAuth 2.0 PKCE, user-taught skills (catalog, file, URL, OpenAPI import), encrypted secrets,
  write skills behind enable + YES, Trusted Publishing release workflow.
