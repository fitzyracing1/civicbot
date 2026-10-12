# Usage

Subcommands come from `civicbot/__main__.py` and `civicbot/cli_extra.py`. Run `civicbot <cmd> --help` for the full option list.

| Command | Purpose |
|---|---|
| `simulate` | end-to-end robot flow with fake X adapters (`--robot handle[:owner[:city]]`, `--demo robots\|skills`, `--offline`, `--free`, `--then YES`) |
| `connect` | print the X OAuth 2.0 PKCE URL for a robot (`--robot`, `--owner`, `--client-id`, `--redirect-uri`, `--scopes`, `--listen` to catch the callback on 127.0.0.1:`--port` 8765) |
| `skill <action> [ref]` | `list, catalog, add, remove, enable, disable, test, validate, import-openapi, reindex` |
| `secret` | store an owner's API key for one robot (encrypted, never printed) |
| `endpoints` | list the bundled Open311 endpoints |
| `services <endpoint>` | list services for an endpoint |
| `resolve [address]` | resolve an address or `--lat/--lng` to an endpoint |
| `transit <url>` | read a transit feed (`--stop`, `--route`) |
| `chat` | terminal REPL (`--free`, `--city`, `--skills all\|free\|list`, `--offline`) |
| `apis` | browse the free-API directory (`--category`, `--search`, `--json`, `--cors`, `--no-key`) |
| `run` | poll your robot's X mentions once and reply (`--robot`, `--state-dir .civicbot`, `--free`, `--post`, `--once`). Without `--post` it runs in shadow mode |

Live tests are marked `live` and only run when `CIVICBOT_LIVE=1` is set. A GitHub Actions example is in `examples/github-actions/civicbot-robot.yml`.
