"""Rule-based skill routing (no LLM: X requires prior approval for AI reply bots)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

USER_SKILL_BONUS = 0.5  # an owner-installed skill wins a tie against a generic built-in


def _has(text: str, kw: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(kw.lower()) + r"(?![\w-])", text) is not None


def keyword_score(spec: dict, text: str) -> float:
    t = text.lower()
    trig = spec.get("triggers", {})
    s = sum(1.0 for k in set(trig.get("keywords", [])) if _has(t, k))
    s += sum(2.0 for p in set(trig.get("phrases", [])) if p.lower() in t)
    return s


@dataclass
class Route:
    skill: dict
    score: float
    why: str


class SkillRouter:
    def route(self, text: str, intent_kind: str, skills: Iterable[dict], *,
              transit_available: bool = False) -> Optional[Route]:
        cands: List[Route] = []
        for s in skills:
            h = s.get("handler")
            if h == "builtin:report":
                if intent_kind == "report":
                    cands.append(Route(s, 1.0 + keyword_score(s, text), "built-in report"))
            elif h == "builtin:status":
                if intent_kind == "status":
                    cands.append(Route(s, 3.0, "built-in status"))
            elif h == "builtin:transit":
                if intent_kind == "transit" and transit_available:
                    cands.append(Route(s, 2.0, "built-in transit"))
            else:
                sc = keyword_score(s, text)
                if sc >= s.get("triggers", {}).get("min_score", 1):
                    cands.append(Route(s, sc + USER_SKILL_BONUS, f"keywords score {sc:g}"))
        if not cands:
            return None
        return max(cands, key=lambda r: r.score)
