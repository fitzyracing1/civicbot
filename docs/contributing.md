# Contributing

1. `pip install -e '.[dev]'`
2. `pytest -q -m "not live"` must pass (this is what CI runs). Live tests (`CIVICBOT_LIVE=1 pytest -m live`) are read-only.
3. Keep write paths gated: no real 311 filing, write-skill call, or X post without an explicit opt-in.
4. New catalog skills go in `civicbot/catalog/` and must validate with `civicbot skill validate <file>`.

Notable changes go in `CHANGELOG.md`.
