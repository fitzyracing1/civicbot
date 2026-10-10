"""Hosted civicbot: a signup site where regular people connect their own robot X account, plus a
background runner that operates every connected robot.

    pip install 'civicbot[web]'
    CIVICBOT_DEV_MODE=1 python -m civicbot.web          # site on :8000 with a fake X (no credentials)
    CIVICBOT_DEV_MODE=1 python -m civicbot.web.worker   # the runner

See docs/DEPLOY.md.
"""
