"""Per-robot secret store for skill credentials (API keys an OWNER provides for their robot).

Specs only carry a ``secret_ref`` name (e.g. "socrata_app_token"); the value lives here, encrypted
at rest with Fernet (key from CIVICBOT_SECRET_KEY, falling back to CIVICBOT_TOKEN_KEY). Secrets are
scoped per robot: one owner's key is never visible to another robot's skills.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Protocol


class SecretStore(Protocol):
    def get(self, robot_id: str, ref: str) -> Optional[str]: ...
    def put(self, robot_id: str, ref: str, value: str) -> None: ...
    def delete(self, robot_id: str, ref: str) -> None: ...
    def refs(self, robot_id: str) -> List[str]: ...


class InMemorySecretStore:
    def __init__(self):
        self._d: Dict[str, Dict[str, str]] = {}

    def get(self, robot_id, ref):
        return self._d.get(robot_id, {}).get(ref)

    def put(self, robot_id, ref, value):
        self._d.setdefault(robot_id, {})[ref] = value

    def delete(self, robot_id, ref):
        self._d.get(robot_id, {}).pop(ref, None)

    def refs(self, robot_id):
        return sorted(self._d.get(robot_id, {}))


class EncryptedFileSecretStore(InMemorySecretStore):
    def __init__(self, path: str, key: Optional[bytes] = None):
        super().__init__()
        try:
            from cryptography.fernet import Fernet
        except ImportError as e:  # pragma: no cover
            raise ImportError("pip install 'civicbot[secure]' for encrypted secret storage") from e
        key = key or (os.environ.get("CIVICBOT_SECRET_KEY") or os.environ.get("CIVICBOT_TOKEN_KEY", "")).encode()
        if not key:
            raise ValueError("no encryption key: pass key= or set CIVICBOT_SECRET_KEY")
        self._f, self.path = Fernet(key), Path(path)
        if self.path.exists():
            self._d = json.loads(self._f.decrypt(self.path.read_bytes()))

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._f.encrypt(json.dumps(self._d).encode()))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def put(self, robot_id, ref, value):
        super().put(robot_id, ref, value)
        self._save()

    def delete(self, robot_id, ref):
        super().delete(robot_id, ref)
        self._save()
