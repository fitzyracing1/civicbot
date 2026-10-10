"""Settings from environment variables (see .env.example). Nothing secret has a default outside dev mode."""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


class ConfigError(Exception):
    pass


def _bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v not in (None, "") else default


def _int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v not in (None, "") else default


@dataclass
class Settings:
    dev_mode: bool = False
    base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./civicbot-data/civicbot.db"
    session_secret: str = ""
    token_key: str = ""
    x_client_id: str = ""
    x_client_secret: str = ""
    # --- guardrails (X pay-per-use prices: README "Costs") ---
    daily_spend_cap_usd: float = 5.00       # whole app, per UTC day (X dedupes/bills per UTC day)
    robot_daily_replies: int = 50           # per robot per UTC day (X allows 100 per 15 min per user)
    robot_daily_mentions: int = 200         # mentions read per robot per UTC day
    app_polls_per_15min: int = 300          # X per-app ceiling for GET /2/users/:id/mentions is 450/15 min
    app_posts_per_day: int = 9000           # X per-app ceiling for POST /2/tweets is 10,000/24 h
    poll_interval_s: float = 120.0          # min seconds between polls of the same robot
    worker_tick_s: float = 15.0
    max_robots_per_owner: int = 3
    signup_rate_limit: int = 20             # sign-in/connect requests per IP per minute (one full signup uses ~7)
    lookup_rate_limit: int = 20             # address lookups per IP per minute
    trust_proxy: bool = False               # honor X-Forwarded-For (only behind your own proxy)
    x_write_enabled: bool = False           # False = "shadow mode": read mentions, log replies, post nothing
    allow_311_sending: bool = False         # operator kill switch for real 311 filing
    city_api_keys: Dict[str, str] = field(default_factory=dict)
    data_dir: str = "./civicbot-data"

    @property
    def redirect_uri(self) -> str:
        return self.base_url.rstrip("/") + "/auth/x/callback"

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(
            dev_mode=_bool("CIVICBOT_DEV_MODE"),
            base_url=os.environ.get("PUBLIC_BASE_URL", cls.base_url).rstrip("/"),
            database_url=os.environ.get("DATABASE_URL", cls.database_url),
            session_secret=os.environ.get("SESSION_SECRET", ""),
            token_key=os.environ.get("CIVICBOT_TOKEN_KEY", ""),
            x_client_id=os.environ.get("X_CLIENT_ID", ""),
            x_client_secret=os.environ.get("X_CLIENT_SECRET", ""),
            daily_spend_cap_usd=_float("CIVICBOT_DAILY_SPEND_CAP_USD", cls.daily_spend_cap_usd),
            robot_daily_replies=_int("CIVICBOT_ROBOT_DAILY_REPLIES", cls.robot_daily_replies),
            robot_daily_mentions=_int("CIVICBOT_ROBOT_DAILY_MENTIONS", cls.robot_daily_mentions),
            app_polls_per_15min=_int("CIVICBOT_APP_POLLS_PER_15MIN", cls.app_polls_per_15min),
            app_posts_per_day=_int("CIVICBOT_APP_POSTS_PER_DAY", cls.app_posts_per_day),
            poll_interval_s=_float("CIVICBOT_POLL_INTERVAL_S", cls.poll_interval_s),
            worker_tick_s=_float("CIVICBOT_WORKER_TICK_S", cls.worker_tick_s),
            max_robots_per_owner=_int("CIVICBOT_MAX_ROBOTS_PER_OWNER", cls.max_robots_per_owner),
            signup_rate_limit=_int("CIVICBOT_SIGNUP_RATE_LIMIT", cls.signup_rate_limit),
            lookup_rate_limit=_int("CIVICBOT_LOOKUP_RATE_LIMIT", cls.lookup_rate_limit),
            trust_proxy=_bool("CIVICBOT_TRUST_PROXY"),
            x_write_enabled=_bool("CIVICBOT_X_WRITE_ENABLED"),
            allow_311_sending=_bool("CIVICBOT_ALLOW_311_SENDING"),
            city_api_keys=json.loads(os.environ.get("CIVICBOT_CITY_API_KEYS") or "{}"),
            data_dir=os.environ.get("CIVICBOT_DATA_DIR", cls.data_dir),
        )
        if s.dev_mode and not os.environ.get("CIVICBOT_POLL_INTERVAL_S"):
            s.poll_interval_s = 3.0  # dev: "Run the runner now" should always poll
        return s.finalize()

    def finalize(self) -> "Settings":
        if self.dev_mode:
            self.x_client_id = self.x_client_id or "dev-client-id"
            self.x_client_secret = self.x_client_secret or "dev-client-secret"
            self.session_secret = self.session_secret or secrets.token_urlsafe(32)
            if not self.token_key:
                self.token_key = _dev_key(self.data_dir)
            return self
        missing = [n for n, v in (("SESSION_SECRET", self.session_secret), ("CIVICBOT_TOKEN_KEY", self.token_key),
                                  ("X_CLIENT_ID", self.x_client_id), ("X_CLIENT_SECRET", self.x_client_secret)) if not v]
        if missing:
            raise ConfigError(f"missing required settings: {', '.join(missing)} (or set CIVICBOT_DEV_MODE=1)")
        if len(self.session_secret) < 32:
            raise ConfigError("SESSION_SECRET must be at least 32 characters")
        if not self.base_url.startswith("https://") and "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            raise ConfigError("PUBLIC_BASE_URL must be https:// in production")
        return self


def _dev_key(data_dir: str) -> str:
    """Dev only: one Fernet key shared by the web and worker processes via the data dir."""
    from cryptography.fernet import Fernet
    p = Path(data_dir) / ".dev-token-key"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(Fernet.generate_key())
        os.chmod(p, 0o600)
    return p.read_text().strip()
