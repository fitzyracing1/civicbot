"""SQL-backed implementations of civicbot's storage protocols, shared by the web app and the worker.

* SqlTokenStore   - civicbot.x.tokens.TokenStore protocol; Fernet-encrypted at rest with the same
                    CIVICBOT_TOKEN_KEY the file-based EncryptedFileTokenStore uses.
* SqlProfileStore - civicbot.robot.profile.ProfileStore interface (get/put/delete/all), so the
                    existing Fleet runs unchanged on top of it. Ownership-aware.
* SqlPending      - dict-like store for XOAuth2.pending (PKCE verifiers), so a connect that starts
                    on one web process can finish on another. Encrypted, single-use, TTL'd.
"""
from __future__ import annotations

import json
import time
from collections.abc import MutableMapping
from dataclasses import asdict
from typing import Iterator, List, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select

from ..robot.profile import RobotProfile
from ..x.oauth import PENDING_TTL, OAuthToken, PendingAuth
from .db import PendingRow, RobotRow, TokenRow


class OwnershipError(PermissionError):
    pass


def profile_to_json(p: RobotProfile) -> str:
    return json.dumps(asdict(p))


def profile_from_json(s: str) -> RobotProfile:
    return RobotProfile(**json.loads(s))


class SqlTokenStore:
    def __init__(self, sf, key: str | bytes):
        self.sf = sf
        self._f = Fernet(key if isinstance(key, bytes) else key.encode())

    def get(self, robot_id: str) -> Optional[OAuthToken]:
        with self.sf() as db:
            row = db.get(TokenRow, robot_id)
            if not row:
                return None
            try:
                return OAuthToken(**json.loads(self._f.decrypt(row.ciphertext.encode())))
            except InvalidToken:
                raise RuntimeError("token ciphertext does not match CIVICBOT_TOKEN_KEY (key rotated?)") from None

    def put(self, robot_id: str, token: OAuthToken) -> None:
        ct = self._f.encrypt(json.dumps(token.to_dict()).encode()).decode()
        with self.sf() as db, db.begin():
            row = db.get(TokenRow, robot_id)
            if row:
                row.ciphertext = ct
            else:
                db.add(TokenRow(robot_id=robot_id, ciphertext=ct))

    def delete(self, robot_id: str) -> None:
        with self.sf() as db, db.begin():
            db.execute(delete(TokenRow).where(TokenRow.robot_id == robot_id))


class SqlProfileStore:
    """bind_owner_id: the signed-in owner (web requests). New robots are created for that owner and a
    robot that belongs to someone else can't be overwritten. active_only: what the worker iterates."""

    def __init__(self, sf, bind_owner_id: Optional[int] = None, active_only: bool = False):
        self.sf, self.bind_owner_id, self.active_only = sf, bind_owner_id, active_only

    def get(self, robot_id: str) -> Optional[RobotProfile]:
        with self.sf() as db:
            row = db.get(RobotRow, robot_id.lstrip("@").lower())
            if not row or (self.bind_owner_id is not None and row.owner_id != self.bind_owner_id):
                return None
            return profile_from_json(row.profile_json)

    def put(self, p: RobotProfile) -> None:
        with self.sf() as db, db.begin():
            row = db.get(RobotRow, p.robot_id)
            if row:
                if self.bind_owner_id is not None and row.owner_id != self.bind_owner_id:
                    raise OwnershipError(f"@{p.robot_handle} is connected to a different owner")
                row.profile_json = profile_to_json(p)
            else:
                if self.bind_owner_id is None:
                    raise OwnershipError("new robots can only be created by a signed-in owner")
                db.add(RobotRow(robot_id=p.robot_id, owner_id=self.bind_owner_id, status="active",
                                profile_json=profile_to_json(p)))

    def delete(self, robot_id: str) -> None:
        with self.sf() as db, db.begin():
            row = db.get(RobotRow, robot_id.lstrip("@").lower())
            if row and (self.bind_owner_id is None or row.owner_id == self.bind_owner_id):
                db.delete(row)

    def all(self) -> List[RobotProfile]:
        with self.sf() as db:
            q = select(RobotRow)
            if self.bind_owner_id is not None:
                q = q.where(RobotRow.owner_id == self.bind_owner_id)
            if self.active_only:
                q = q.where(RobotRow.status == "active")
            return [profile_from_json(r.profile_json) for r in db.scalars(q.order_by(RobotRow.robot_id))]


class NullProfileStore:
    """For disconnect(): revoke + drop tokens but keep the robot's settings row."""

    def delete(self, robot_id: str) -> None:
        pass


class SqlPending(MutableMapping):
    def __init__(self, sf, key: str | bytes, ttl: float = PENDING_TTL):
        self.sf, self.ttl = sf, ttl
        self._f = Fernet(key if isinstance(key, bytes) else key.encode())

    def _gc(self, db) -> None:
        db.execute(delete(PendingRow).where(PendingRow.created_at < time.time() - self.ttl * 2))

    def __setitem__(self, state: str, pending: PendingAuth) -> None:
        ct = self._f.encrypt(json.dumps(asdict(pending)).encode()).decode()
        with self.sf() as db, db.begin():
            self._gc(db)
            db.merge(PendingRow(state=state, ciphertext=ct, created_at=pending.created_at))

    def __getitem__(self, state: str) -> PendingAuth:
        with self.sf() as db:
            row = db.get(PendingRow, state)
            if not row:
                raise KeyError(state)
            return PendingAuth(**json.loads(self._f.decrypt(row.ciphertext.encode())))

    def __delitem__(self, state: str) -> None:
        with self.sf() as db, db.begin():
            if db.execute(delete(PendingRow).where(PendingRow.state == state)).rowcount == 0:
                raise KeyError(state)

    def pop(self, state, default=None):  # atomic single-use: only the request that deletes the row wins
        try:
            p = self[state]
            del self[state]
            return p
        except KeyError:
            return default

    def __iter__(self) -> Iterator[str]:
        with self.sf() as db:
            return iter([r for r in db.scalars(select(PendingRow.state))])

    def __len__(self) -> int:
        return len(list(iter(self)))
