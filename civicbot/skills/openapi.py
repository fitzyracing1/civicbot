"""Generate a draft skill spec from ONE OpenAPI 3.x operation.

The draft is marked for review: the owner still has to check triggers, replies and limits.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .spec import validate_spec

PARAM_MAP = {
    "lat": "{location.lat}", "latitude": "{location.lat}",
    "lon": "{location.lng}", "lng": "{location.lng}", "long": "{location.lng}", "longitude": "{location.lng}",
    "q": "{query}", "query": "{query}", "search": "{query}", "text": "{text}",
    "date": "{date.today}", "address": "{location.text}", "location": "{location.text}",
}


def _find_op(doc: dict, operation: str) -> Tuple[str, str, dict]:
    for path, item in (doc.get("paths") or {}).items():
        for method, op in item.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete") or not isinstance(op, dict):
                continue
            if op.get("operationId") == operation or f"{method.upper()} {path}" == operation:
                return path, method.upper(), op
    ops = [f"{m.upper()} {p} ({o.get('operationId', '-')})" for p, it in (doc.get("paths") or {}).items()
           for m, o in it.items() if isinstance(o, dict)]
    raise KeyError(f"operation {operation!r} not found; available: {ops[:20]}")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "imported-skill"


def from_openapi(doc: dict, operation: str, *, name: Optional[str] = None, keywords: Optional[List[str]] = None,
                 server: Optional[str] = None) -> dict:
    path, method, op = _find_op(doc, operation)
    base = (server or ((doc.get("servers") or [{}])[0].get("url", ""))).rstrip("/")
    m = re.match(r"^(https://[A-Za-z0-9.-]+)(/.*)?$", base)
    if not m:
        raise ValueError(f"need an https server URL (got {base!r}); pass server=")
    base_url, prefix = m.group(1), (m.group(2) or "")
    host = base_url[len("https://"):]
    params: Dict[str, Any] = {}
    inputs: Dict[str, dict] = {}
    for p in op.get("parameters", []) + (doc.get("paths", {}).get(path, {}).get("parameters") or []):
        if "$ref" in p:
            continue
        pname, where = p.get("name", ""), p.get("in")
        mapped = PARAM_MAP.get(pname.lower())
        if where == "path" or (not mapped and p.get("required")):
            key = re.sub(r"[^a-z0-9_]", "_", pname.lower())[:30] or "value"
            enum = (p.get("schema") or {}).get("enum")
            pattern = "^(" + "|".join(re.escape(str(e)) for e in enum) + ")$" if enum else "^[A-Za-z0-9_.-]{1,40}$"
            inputs[key] = {"regex": rf"\b{re.escape(pname)}\s*[:=]?\s*([A-Za-z0-9_.-]{{1,40}})", "pattern": pattern,
                           "required": bool(p.get("required")), "description": (p.get("description") or pname)[:200]}
            ref = f"{{inputs.{key}}}"
            if where == "path":
                path = path.replace("{" + pname + "}", ref)
            else:
                params[pname] = ref
        elif where == "query" and mapped:
            params[pname] = mapped
    title = op.get("summary") or op.get("operationId") or f"{method} {path}"
    kw = keywords or [w for w in re.findall(r"[a-z]{4,}", title.lower())][:5] or ["lookup"]
    spec = {
        "spec_version": 1, "name": name or _slug(op.get("operationId") or title), "title": title[:80],
        "description": (op.get("description") or title)[:400].ljust(5, "."),
        "kind": "read" if method == "GET" else "write",
        "author": "imported from OpenAPI (REVIEW BEFORE INSTALLING)",
        "triggers": {"keywords": kw},
        "request": {"base_url": base_url, "path": prefix + path, "method": method, **({"params": params} if params else {})},
        "auth": {"type": "none"},
        "allowed_domains": [host],
        "response": {"replies": [f"{title[:60]}: done. (edit this reply template to show response fields)"]},
        "limits": {"timeout_s": 10, "max_bytes": 262144, "min_interval_s": 5, "max_calls_per_day": 100},
    }
    if inputs:
        spec["inputs"] = inputs
    if any("location." in str(v) for v in params.values()):
        spec["location"] = "required"
    schemes = (doc.get("components") or {}).get("securitySchemes") or {}
    for sname, sch in schemes.items():
        if sch.get("type") == "apiKey" and sch.get("in") in ("header", "query"):
            spec["auth"] = {"type": "api_key", "in": sch["in"], "name": sch["name"],
                            "secret_ref": _slug(sname).replace("-", "_")[:40] or "api_key", "required": True}
            break
        if sch.get("type") == "http" and sch.get("scheme") == "bearer":
            spec["auth"] = {"type": "bearer", "secret_ref": _slug(sname).replace("-", "_")[:40] or "token"}
            break
    return validate_spec(spec)
