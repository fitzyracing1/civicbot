"""Pluggable storage for per-robot OAuth tokens.

* InMemoryTokenStore - tests / simulation.
* EncryptedFileTokenStore - tokens encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256,
  from the `cryptography` package: pip install 'civicbot[secure]'). Key comes from the
  CIVICBOT_TOKEN_KEY env var (generate with EncryptedFileTokenStore.generate_key()).
  Production: swap in a KMS/Secrets Manager-backed store implementing the same protocol.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional, Protocol

from .oauth import OAuthToken


class TokenStore(Protocol):
    def get(self, robot_id: str) -> Optional[OAuthToken]: ...
    def put(self, robot_id: str, token: OAuthToken) -> None: ...
    def delete(self, robot_id: str) -> None: ...


class InMemoryTokenStore:
    def __init__(self):
        self._d: Dict[str, OAuthToken] = {}

    def get(self, robot_id: str) -> Optional[OAuthToken]:
        return self._d.get(robot_id)

    def put(self, robot_id: str, token: OAuthToken) -> None:
        self._d[robot_id] = token

    def delete(self, robot_id: str) -> None:
        self._d.pop(robot_id, None)


class EncryptedFileTokenStore:
    def __init__(self, path: str, key: Optional[bytes] = None):
        try:
            from cryptography.fernet import Fernet
        except ImportError as e:  # pragma: no cover
            raise ImportError("pip install 'civicbot[secure]' (cryptography) for encrypted token storage") from e
        key = key or os.environ.get("CIVICBOT_TOKEN_KEY", "").encode()
        if not key:
            raise ValueError("no encryption key: pass key= or set CIVICBOT_TOKEN_KEY")
        self._f = Fernet(key)
        self.path = Path(path)

    @staticmethod
    def generate_key() -> bytes:
        from cryptography.fernet import Fernet
        return Fernet.generate_key()

    def _load(self) -> Dict[str, dict]:
        if not self.path.exists():
            return {}
        return json.loads(self._f.decrypt(self.path.read_bytes()))

    def _save(self, d: Dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._f.encrypt(json.dumps(d).encode()))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def get(self, robot_id: str) -> Optional[OAuthToken]:
        d = self._load().get(robot_id)
        return OAuthToken(**d) if d else None

    def put(self, robot_id: str, token: OAuthToken) -> None:
        d = self._load()
        d[robot_id] = token.to_dict()
        self._save(d)

    def delete(self, robot_id: str) -> None:
        d = self._load()
        if d.pop(robot_id, None) is not None:
            self._save(d)
