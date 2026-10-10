# Changelog

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
