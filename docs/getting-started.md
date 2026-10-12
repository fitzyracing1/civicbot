# Getting started

From the README Quickstart:

```bash
git clone https://github.com/fitzyracing1/civicbot && cd civicbot
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest -q                                   # unit tests (mocked HTTP)
CIVICBOT_LIVE=1 pytest -q -m live           # read-only live smoke tests

python -m civicbot simulate --demo           # fake X, real read-only city APIs
python -m civicbot simulate --demo --offline # bundled fixtures, no network
python -m civicbot chat --free               # terminal REPL, nothing posted
```
