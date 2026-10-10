"""Skill spec loading + validation (JSON Schema subset + civicbot safety rules)."""
from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Optional

from .template import PLACEHOLDER_RE, URL_RE, placeholders

SCHEMA = json.loads(resources.files("civicbot.skills").joinpath("schema.json").read_text("utf-8"))

FREE_TEXT_VARS = {"text", "query", "location.text", "owner.home_city"}
NUMERIC_VARS = {"location.lat", "location.lng", "date.now_unix"}
DATE_RE = re.compile(r"^date\.(today|days_ago_([1-9]\d{0,2}))$")
SECRET_HEADER_NAMES = {"authorization", "proxy-authorization", "cookie", "x-api-key", "api-key", "apikey",
                       "x-app-token", "x-auth-token", "token"}
SECRET_PARAM_RE = re.compile(r"(api[_-]?key|apikey|token|secret|password|passwd|auth|access[_-]?key|app[_-]?token)$", re.I)
SECRET_VALUE_RE = re.compile(r"(Bearer\s+\S{8,}|Basic\s+[A-Za-z0-9+/=]{12,}|sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,}"
                             r"|github_pat_|AKIA[0-9A-Z]{16}|xox[abpr]-|AIza[0-9A-Za-z_-]{30,}|-----BEGIN"
                             r"|(?<![{.\w])[A-Za-z0-9_\-]{32,}(?![}\w]))")
MENTION_RE = re.compile(r"(^|[^\w])[@＠]\w")


class SpecError(ValueError):
    def __init__(self, problems: List[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# --- minimal JSON Schema (draft-07 subset) validator -----------------------------------------
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}


def _type_ok(v: Any, t: str) -> bool:
    if t in ("integer", "number") and isinstance(v, bool):
        return False
    return isinstance(v, _TYPES[t])


def schema_errors(v: Any, s: Dict[str, Any], path: str = "$") -> List[str]:
    errs: List[str] = []
    if "enum" in s and v not in s["enum"]:
        return [f"{path}: must be one of {s['enum']}"]
    t = s.get("type")
    if t:
        ts = t if isinstance(t, list) else [t]
        if not any(_type_ok(v, x) for x in ts):
            return [f"{path}: expected {t}"]
    if isinstance(v, str):
        if "minLength" in s and len(v) < s["minLength"]:
            errs.append(f"{path}: too short")
        if "maxLength" in s and len(v) > s["maxLength"]:
            errs.append(f"{path}: longer than {s['maxLength']}")
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{path}: does not match {s['pattern']}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            errs.append(f"{path}: below {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            errs.append(f"{path}: above {s['maximum']}")
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]:
            errs.append(f"{path}: needs at least {s['minItems']} item(s)")
        if "maxItems" in s and len(v) > s["maxItems"]:
            errs.append(f"{path}: at most {s['maxItems']} items")
        if "items" in s:
            for i, x in enumerate(v):
                errs += schema_errors(x, s["items"], f"{path}[{i}]")
    if isinstance(v, dict):
        for r in s.get("required", []):
            if r not in v:
                errs.append(f"{path}: missing '{r}'")
        if "maxProperties" in s and len(v) > s["maxProperties"]:
            errs.append(f"{path}: too many properties")
        props = s.get("properties", {})
        addl = s.get("additionalProperties", True)
        for k, x in v.items():
            if k in props:
                errs += schema_errors(x, props[k], f"{path}.{k}")
            elif addl is False:
                errs.append(f"{path}: unknown field '{k}'")
            elif isinstance(addl, dict):
                errs += schema_errors(x, addl, f"{path}.{k}")
    return errs


# --- civicbot rules ---------------------------------------------------------------------------
def _walk_strings(obj: Any, path: str):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def _var_ok(name: str, inputs: Dict[str, Any]) -> bool:
    if name in FREE_TEXT_VARS or name in NUMERIC_VARS or DATE_RE.match(name):
        return True
    return name.startswith("inputs.") and name[len("inputs."):] in inputs


def validate_spec(spec: Any, *, allow_builtin: bool = False) -> Dict[str, Any]:
    """Return the spec (with defaults filled) or raise SpecError listing every problem."""
    if not isinstance(spec, dict):
        raise SpecError(["spec must be a JSON object"])
    if spec.get("handler") and allow_builtin:
        return spec
    problems = schema_errors(spec, SCHEMA)
    if problems:
        raise SpecError(problems)
    if "handler" in spec:
        problems.append("'handler' is reserved for built-in skills")
    req, auth = spec["request"], spec.get("auth", {"type": "none"})
    inputs = spec.get("inputs", {})
    host = req["base_url"][len("https://"):].split(":")[0].lower()
    if not any(host == d or host.endswith("." + d) for d in spec["allowed_domains"]):
        problems.append(f"base_url host {host} is not in allowed_domains")
    if spec["kind"] == "read" and req["method"] != "GET":
        problems.append("kind 'read' skills must use GET")
    if spec["kind"] == "write" and req["method"] == "GET":
        problems.append("kind 'write' skills must not use GET")
    # no secrets inside the spec
    for k in (req.get("headers") or {}):
        if k.lower() in SECRET_HEADER_NAMES:
            problems.append(f"header '{k}' looks like a credential; use auth.secret_ref instead")
    for section in ("params", "body"):
        for k, v in (req.get(section) or {}).items():
            if SECRET_PARAM_RE.search(k) and not (isinstance(v, str) and PLACEHOLDER_RE.fullmatch(v)):
                problems.append(f"{section}.{k} looks like a credential; use auth.secret_ref instead")
    for p, s in _walk_strings(spec, "$"):
        if SECRET_VALUE_RE.search(s):
            problems.append(f"{p}: looks like an embedded secret/token; specs must not contain secrets")
    if auth["type"] == "api_key" and not all(auth.get(x) for x in ("in", "name", "secret_ref")):
        problems.append("auth api_key needs 'in', 'name' and 'secret_ref'")
    if auth["type"] == "bearer" and not auth.get("secret_ref"):
        problems.append("auth bearer needs 'secret_ref'")
    # inputs: regexes must compile, patterns are anchored
    for name, d in inputs.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", name):
            problems.append(f"inputs.{name}: bad name")
        for key in ("regex", "pattern"):
            try:
                re.compile(d.get(key, ""))
            except re.error as e:
                problems.append(f"inputs.{name}.{key}: {e}")
        if not (d["pattern"].startswith("^") and d["pattern"].endswith("$")):
            problems.append(f"inputs.{name}.pattern must be anchored with ^...$")
        if "default" in d and not re.fullmatch(d["pattern"].strip("^$"), d["default"]):
            problems.append(f"inputs.{name}.default does not match its pattern")
    # placeholders in the request: known vars only; free text only as a whole value, never in the path
    uses_location = False
    for p, s in _walk_strings({"path": req["path"], "params": req.get("params"), "headers": req.get("headers"),
                               "body": req.get("body")}, "$.request"):
        for name, flt in placeholders(s):
            if flt:
                problems.append(f"{p}: filters are not allowed in requests")
            if not _var_ok(name, inputs):
                problems.append(f"{p}: unknown variable '{{{name}}}'")
                continue
            uses_location |= name.startswith("location.")
            if name in FREE_TEXT_VARS:
                if p.startswith(("$.request.path", "$.request.headers")):
                    problems.append(f"{p}: free text '{{{name}}}' may not be used in the path or headers")
                elif PLACEHOLDER_RE.fullmatch(s) is None:
                    problems.append(f"{p}: free text '{{{name}}}' must be the whole value (no query injection)")
    if uses_location and spec.get("location", "optional") == "none":
        problems.append("request uses location.* but location is 'none'")
    # replies: no links (cost + spam), no @mentions, sane placeholders
    resp = spec["response"]
    names = set(resp.get("extract", {})) | {"items", "count"} | FREE_TEXT_VARS | {f"inputs.{k}" for k in inputs}
    for p, s in _walk_strings({"replies": resp["replies"], "empty_replies": resp.get("empty_replies", [])}, "$.response"):
        if URL_RE.search(s):
            problems.append(f"{p}: links are not allowed in replies (X charges $0.20 per post with a URL)")
        if MENTION_RE.search(s):
            problems.append(f"{p}: @mentions are not allowed in replies")
        for name, flt in placeholders(s):
            if name not in names and not name.startswith("location."):
                problems.append(f"{p}: '{{{name}}}' is not extracted or known")
    if "list" in resp and not any("{items}" in r for r in resp["replies"]):
        problems.append("response.list is set but no reply uses {items}")
    if problems:
        raise SpecError(problems)
    out = dict(spec)
    out.setdefault("auth", {"type": "none"})
    out.setdefault("location", "required" if uses_location else "none")
    out.setdefault("limits", {})
    return out


def load_spec_text(text: str, source: str = "") -> Dict[str, Any]:
    """JSON always; YAML if PyYAML is installed and the source looks like YAML."""
    if source.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise SpecError(["YAML specs need PyYAML (pip install pyyaml); JSON works without it"]) from None
        return yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SpecError([f"not valid JSON: {e}"]) from None


def load_spec_file(path: str) -> Dict[str, Any]:
    p = Path(path)
    if p.stat().st_size > 65_536:
        raise SpecError(["spec file larger than 64 KB"])
    return validate_spec(load_spec_text(p.read_text("utf-8"), p.name))
