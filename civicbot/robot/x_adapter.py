"""X adapter interface + an in-memory fake.

``StubXAdapter`` is used by tests and the CLI simulator. The real adapter lives in
``civicbot.x.api.XApiV2Adapter`` and is disabled unless explicitly enabled with a token.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import List, Optional, Protocol


@dataclass
class Mention:
    id: str
    author: str  # handle without @
    text: str
    conversation_id: str = ""
    in_reply_to_id: str = ""
    lat: Optional[float] = None  # from post geo, if the user shared it
    lng: Optional[float] = None
    robot: str = ""        # which robot account received it (multi-tenant routing)
    channel: str = "mention"  # "mention" | "dm"


class XAdapter(Protocol):
    def poll_mentions(self, since_id: Optional[str] = None) -> List[Mention]: ...
    def post_reply(self, in_reply_to_id: str, text: str) -> str: ...


@dataclass
class StubXAdapter:
    """Fake X for ONE robot account. Records what the robot would post."""
    robot: str = ""  # robot account id; "" = unscoped (single-robot scripts)
    inbox: List[Mention] = field(default_factory=list)
    outbox: List[dict] = field(default_factory=list)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def add_mention(self, author: str, text: str, **kw) -> Mention:
        kw.setdefault("robot", self.robot)
        m = Mention(id=f"{self.robot + '-' if self.robot else ''}m{next(self._ids)}", author=author.lstrip("@"), text=text, **kw)
        self.inbox.append(m)
        return m

    def poll_mentions(self, since_id: Optional[str] = None) -> List[Mention]:
        if since_id is None:
            return list(self.inbox)
        ids = [m.id for m in self.inbox]
        return self.inbox[ids.index(since_id) + 1:] if since_id in ids else list(self.inbox)

    def post_reply(self, in_reply_to_id: str, text: str) -> str:
        if len(text) > 280:
            raise ValueError("post exceeds 280 chars")
        pid = f"{self.robot + '-' if self.robot else ''}p{next(self._ids)}"
        self.outbox.append({"id": pid, "from": self.robot, "in_reply_to": in_reply_to_id, "text": text})
        return pid
