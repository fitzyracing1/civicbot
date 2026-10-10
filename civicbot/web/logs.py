"""Structured JSON logs with secret redaction (tokens, auth codes, PKCE verifiers never reach logs)."""
from __future__ import annotations

import json
import logging
import re
import sys
import time

_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(access_token|refresh_token|token|code|code_verifier|client_secret|state)(=|\"?\s*:\s*\"?)([^&\s\"',}]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=]+"), r"\1[REDACTED]"),
    (re.compile(r"gAAAAA[A-Za-z0-9_=-]{20,}"), "[REDACTED-FERNET]"),
    (re.compile(r"\bdev[ar]t_[A-Za-z0-9_-]+"), "[REDACTED]"),
]


def redact(s: str) -> str:
    for pat, rep in _PATTERNS:
        s = pat.sub(rep, s)
    return s


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        record.msg, record.args = redact(msg), ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": round(time.time(), 3), "level": record.levelname.lower(), "logger": record.name,
               "msg": record.getMessage()}
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            out.update({k: (redact(v) if isinstance(v, str) else v) for k, v in extra.items()})
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, default=str)


_configured = False


def setup_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    h.addFilter(RedactFilter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):  # access logs carry ?code=&state=
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
        lg.addFilter(RedactFilter())
    logging.getLogger("httpx").setLevel(logging.WARNING)  # test client noise
    _configured = True


def log(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, msg, extra={"fields": fields})
