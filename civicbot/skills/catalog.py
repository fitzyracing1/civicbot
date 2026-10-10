"""Community catalog of reviewed skill specs (civicbot/catalog/ in the repo).

index.json lists each spec with its sha256; install-by-name verifies the hash, so an edited spec
can't be installed until it is re-reviewed and the index regenerated (`civicbot skill reindex`).
"""
from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Dict, List, Optional

from .spec import SpecError, validate_spec


def _default_dir() -> Path:
    return Path(str(resources.files("civicbot").joinpath("catalog")))


class Catalog:
    def __init__(self, directory: Optional[str] = None):
        self.dir = Path(directory) if directory else _default_dir()
        idx = self.dir / "index.json"
        self.index: Dict[str, dict] = {e["name"]: e for e in json.loads(idx.read_text("utf-8"))["skills"]} if idx.exists() else {}

    def names(self) -> List[str]:
        return sorted(self.index)

    def entry(self, name: str) -> Optional[dict]:
        return self.index.get(name)

    def get(self, name: str) -> dict:
        e = self.index.get(name)
        if not e:
            raise KeyError(f"'{name}' is not in the catalog")
        raw = (self.dir / e["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != e["sha256"]:
            raise SpecError([f"catalog spec {name} does not match its reviewed sha256; re-review and reindex"])
        return validate_spec(json.loads(raw))

    @staticmethod
    def reindex(directory: str, reviewed: Optional[Dict[str, dict]] = None) -> dict:
        d = Path(directory)
        old = {}
        if (d / "index.json").exists():
            old = {e["name"]: e for e in json.loads((d / "index.json").read_text())["skills"]}
        out = []
        for f in sorted((d / "skills").glob("*.json")):
            raw = f.read_bytes()
            spec = validate_spec(json.loads(raw))
            prev = old.get(spec["name"], {})
            e = {"name": spec["name"], "file": f"skills/{f.name}", "title": spec.get("title", spec["name"]),
                 "kind": spec["kind"], "domains": spec["allowed_domains"], "sha256": hashlib.sha256(raw).hexdigest(),
                 "review": (reviewed or {}).get(spec["name"]) or prev.get("review") or {"status": "unreviewed"}}
            if "cost" in spec:
                e["cost"] = spec["cost"]
                e["free"] = is_free(spec)
            if "api_id" in spec:
                e["api_id"] = spec["api_id"]
            out.append(e)
        index = {"catalog_version": 1, "skills": out}
        (d / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
        return index


def is_free(spec: dict) -> bool:
    """Free mode rule: the spec says cost "free" AND it needs no credential (auth none, or an optional key)."""
    auth = spec.get("auth") or {"type": "none"}
    return spec.get("cost") == "free" and (auth.get("type", "none") == "none" or auth.get("required") is False)


class CatalogSet:
    """Several catalogs searched in order (first match wins). Same read interface as Catalog."""

    def __init__(self, catalogs: List[Catalog]):
        self.catalogs = list(catalogs)
        self.dir = self.catalogs[0].dir

    def _find(self, name: str) -> Optional[Catalog]:
        return next((c for c in self.catalogs if name in c.index), None)

    def names(self) -> List[str]:
        return sorted({n for c in self.catalogs for n in c.names()})

    def entry(self, name: str) -> Optional[dict]:
        c = self._find(name)
        return c.entry(name) if c else None

    def get(self, name: str) -> dict:
        c = self._find(name)
        if not c:
            raise KeyError(f"'{name}' is not in the catalog")
        return c.get(name)

    def free_names(self) -> List[str]:
        return [n for n in self.names() if (self.entry(n) or {}).get("free")]


def free_catalog_dir() -> Path:
    return _default_dir() / "free"


def default_catalog() -> CatalogSet:
    """The core reviewed catalog plus the free-API catalog added in v0.4 (catalog/free/)."""
    cats = [Catalog()]
    if (free_catalog_dir() / "index.json").exists():
        cats.append(Catalog(str(free_catalog_dir())))
    return CatalogSet(cats)
