"""One building being set up from its documents: the uploaded files, what was read from them, and what a person
decided.

Kept as files under data/intake/<slug>/ (not in git):
    uploads/<step>/<file>   the uploaded files, untouched
    state.json              files (name, sha256, pages), facts per step, decisions, the reading log

A fact is one thing read from a document, always with where it came from and how:
    {"id", "kind", "label", "data", "src": {"file", "page", "bbox", "sheet"}, "method", "conf", "step", "ask"}
`ask` is set when the reader wants a person to decide: {"q", "field", "options": [{"value", "label"}]}.

Reading a step again replaces that step's facts and keeps every decision, so a person's answer survives a re-read.
A fact's status: the decision if there is one (method becomes `human`); else confirmed when its confidence is at
least AUTO_ACCEPT and nothing is asked; else proposed.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INTAKE_DIR = ROOT / "data/intake"
AUTO_ACCEPT = 0.9


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "building"


def list_intakes() -> list[dict]:
    out = []
    for f in sorted(INTAKE_DIR.glob("*/state.json")):
        s = json.loads(f.read_text())
        out.append({"slug": f.parent.name, "name": s["name"], "updated": s.get("updated", 0),
                    "created": s.get("created", 0)})
    return sorted(out, key=lambda s: -s["updated"])


def clear_test_intakes(root: Path = INTAKE_DIR) -> list[str]:
    """Remove the buildings started from the test package (marked test=True at creation). Run when the server
    starts, so the list of buildings in progress keeps only real ones. Returns the slugs removed."""
    gone = []
    for f in sorted(root.glob("*/state.json")):
        try:
            test = json.loads(f.read_text()).get("test", False)
        except (OSError, ValueError):
            continue
        if test:
            shutil.rmtree(f.parent, ignore_errors=True)
            gone.append(f.parent.name)
    return gone


class Intake:
    def __init__(self, slug: str, root: Path = INTAKE_DIR):
        self.slug = slug
        self.dir = root / slug
        path = self.dir / "state.json"
        self.s = json.loads(path.read_text()) if path.exists() else None

    @classmethod
    def create(cls, name: str, address: str = "", root: Path = INTAKE_DIR, test: bool = False) -> "Intake":
        """A new, empty building. `test`: started from the test package; cleared when the server restarts."""
        slug, n = slugify(name), 2
        while (root / slug).exists():
            slug = f"{slugify(name)}-{n}"
            n += 1
        it = cls(slug, root)
        it.s = {"name": name, "address": address, "test": test, "created": time.time(), "updated": time.time(),
                "files": {}, "facts": {}, "decisions": {}, "log": {}}
        it.save()
        return it

    @property
    def name(self) -> str:
        return self.s["name"]

    @property
    def location(self) -> dict | None:
        """Where the building is, as a person confirmed it (step 0): address, its parts, coordinates, provider."""
        return self.s.get("location")

    def set_location(self, loc: dict, confirmed_by: str) -> None:
        self.s["location"] = dict(loc, confirmed_by=confirmed_by, confirmed_at=time.strftime("%Y-%m-%d"),
                                  method="human")
        self.s["address"] = loc.get("address", self.s.get("address", ""))
        self.save()

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.s["updated"] = time.time()
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(self.s, indent=1, ensure_ascii=False))
        tmp.replace(self.dir / "state.json")

    # ---------------------------------------------------------------- files

    def add_file(self, step: str, filename: str, data: bytes) -> Path:
        """Store an upload untouched. The same content uploaded again is not stored twice."""
        digest = hashlib.sha256(data).hexdigest()
        files = self.s["files"].setdefault(step, [])
        if any(f["sha256"] == digest for f in files):
            return self.dir / next(f["path"] for f in files if f["sha256"] == digest)
        name = Path(filename).name
        path = self.dir / "uploads" / step / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        files.append({"name": name, "path": str(path.relative_to(self.dir)), "sha256": digest, "size": len(data),
                      "added": time.time()})
        self.save()
        return path

    def remove_file(self, step: str, name: str) -> None:
        files = self.s["files"].get(step, [])
        for f in [f for f in files if f["name"] == name]:
            (self.dir / f["path"]).unlink(missing_ok=True)
            files.remove(f)
        self.save()

    def files(self, step: str) -> list[dict]:
        return self.s["files"].get(step, [])

    def path(self, f: dict) -> Path:
        return self.dir / f["path"]

    def file_by_name(self, name: str) -> Path | None:
        for files in self.s["files"].values():
            for f in files:
                if f["name"] == name:
                    return self.dir / f["path"]
        return None

    # ---------------------------------------------------------------- facts and decisions

    def set_step(self, step: str, facts: list[dict], log: list[str]) -> None:
        self.s["facts"][step] = {f["id"]: f for f in facts}
        self.s["log"][step] = log
        self.s.setdefault("read_at", {})[step] = time.time()
        self.save()

    def changed_since(self, step: str, t: float) -> bool:
        """A re-read or an answer in `step` after time t."""
        if self.s.get("read_at", {}).get(step, 0) > t:
            return True
        ids = self.s["facts"].get(step, {})
        return any(d["at"] > t for fid, d in self.s["decisions"].items() if fid in ids)

    def read_at(self, step: str) -> float:
        return self.s.get("read_at", {}).get(step, 0)

    def clear_step(self, step: str) -> None:
        self.s["facts"].pop(step, None)
        self.s["log"].pop(step, None)
        self.save()

    def log(self, step: str) -> list[str]:
        return self.s["log"].get(step, [])

    def done(self, step: str) -> bool:
        return step in self.s["facts"]

    def decide(self, fact_id: str, status: str, value=None, field: str | None = None) -> None:
        """A person's answer: confirmed, rejected or fixed (a new value for `field`)."""
        self.s["decisions"][fact_id] = {"status": status, "value": value, "field": field, "at": time.time()}
        self.save()

    def undo(self, fact_id: str) -> None:
        self.s["decisions"].pop(fact_id, None)
        self.save()

    def facts(self, step: str | None = None, kind: str | None = None, live: bool = False) -> list[dict]:
        """Facts with their decisions applied. live=True leaves rejected facts out."""
        steps = [step] if step else list(self.s["facts"])
        out = []
        for st in steps:
            for f in self.s["facts"].get(st, {}).values():
                if kind and f["kind"] != kind:
                    continue
                f = self._effective(f)
                if live and f["status"] == "rejected":
                    continue
                out.append(f)
        return out

    def fact(self, fact_id: str) -> dict | None:
        for facts in self.s["facts"].values():
            if fact_id in facts:
                return self._effective(facts[fact_id])
        return None

    def _effective(self, f: dict) -> dict:
        f = dict(f, data=dict(f["data"]))
        d = self.s["decisions"].get(f["id"])
        if d:
            f["status"] = "rejected" if d["status"] == "rejected" else "confirmed"
            f["method"] = "human"
            f["decided"] = d["status"]
            if d["status"] == "fixed" and d.get("field"):
                f["data"][d["field"]] = d["value"]
                shown = d["value"] if d["value"] not in (None, "", "__new__") else (
                    "a unit of its own" if d["value"] == "__new__" else "none / outside" if d["value"] is None else "kept")
                if isinstance(shown, list):
                    shown = f"{len(shown)} units"
                f["label"] = f"{f['label']} → {shown} (you)"
            elif d["status"] == "rejected":
                f["label"] = f"{f['label']} (rejected by you)"
        else:
            f["status"] = "confirmed" if f["conf"] >= AUTO_ACCEPT and not f.get("ask") else "proposed"
        return f

    def open_questions(self, step: str | None = None) -> list[dict]:
        """Facts waiting for a person: proposed, with a question. Proposed facts without one wait for a later
        document (a tag seen on a plan waits for its schedule row)."""
        return [f for f in self.facts(step) if f["status"] == "proposed" and f.get("ask")]
