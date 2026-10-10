"""Persistence (SQLAlchemy 2). SQLite by default; set DATABASE_URL=postgresql+psycopg://... for Postgres.

Columns holding JSON are TEXT so the schema is portable. Token ciphertext only - never plaintext.
"""
from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owners"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    x_user_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    handle: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_login_at: Mapped[float] = mapped_column(Float, default=time.time)


class RobotRow(Base):
    __tablename__ = "robots"
    robot_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # lowercased handle
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|paused|needs_reconnect|disconnected
    profile_json: Mapped[str] = mapped_column(Text)
    state_json: Mapped[str] = mapped_column(Text, default="")
    last_poll_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)


class TokenRow(Base):
    __tablename__ = "tokens"
    robot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)


class PendingRow(Base):
    __tablename__ = "oauth_pending"
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)  # encrypted PKCE verifier + hints
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


class UsageRow(Base):
    __tablename__ = "usage"
    period: Mapped[str] = mapped_column(String(24), primary_key=True)   # "2026-10-10" or "w1891234"
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)    # "app" or a robot_id
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class EventRow(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    robot_id: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    kind: Mapped[str] = mapped_column(String(24))
    summary: Mapped[str] = mapped_column(String(400), default="")


class Heartbeat(Base):
    __tablename__ = "heartbeats"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[float] = mapped_column(Float)
    info: Mapped[str] = mapped_column(Text, default="")


# ---- dev mode only: the fake X ------------------------------------------------------------
class DevCode(Base):
    __tablename__ = "dev_x_codes"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(32))
    challenge: Mapped[str] = mapped_column(String(128))
    redirect_uri: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class DevToken(Base):
    __tablename__ = "dev_x_tokens"
    token: Mapped[str] = mapped_column(String(96), primary_key=True)
    username: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(8))  # access|refresh
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class DevMention(Base):
    __tablename__ = "dev_x_mentions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    robot_username: Mapped[str] = mapped_column(String(32), index=True)
    author: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class DevPost(Base):
    __tablename__ = "dev_x_posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    robot_username: Mapped[str] = mapped_column(String(32), index=True)
    in_reply_to: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


def make_engine(url: str) -> Engine:
    kw = {}
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            from pathlib import Path
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kw["connect_args"] = {"check_same_thread": False, "timeout": 15}
        if path in ("", ":memory:"):
            from sqlalchemy.pool import StaticPool
            kw["poolclass"] = StaticPool
    eng = create_engine(url, future=True, pool_pre_ping=True, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _):  # web + worker share the file: WAL + busy timeout
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return eng


def init_db(url: str):
    eng = make_engine(url)
    Base.metadata.create_all(eng)
    return eng, sessionmaker(eng, expire_on_commit=False, future=True)
