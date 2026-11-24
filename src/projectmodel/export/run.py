"""One export run: resolve the project, export it, read the file back, validate, and write the SHACL report.

Projects by name:
    alpha    -> alpha/names_paths in the app's store (data/kg.sqlite; scripts/run_mapper.py builds it)
    troop_d  -> the Troop D test package (test_packages/troop_d) run through the guided setup with rules only
                (PM_AI=off) and published into an in-memory store, so the report is reproducible and the app's store
                is untouched
    anything else: a project id in the store ("alpha/names_only"), or a site with one project there

Reports: reports/shacl/<key>.json holds one entry per scope ("confirmed", "with_proposed"); a run replaces its own
scope and keeps the other, so the Complete graph page can show both.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from ..db.store import Store
from ..knowledge_model import KnowledgeModel
from .brick import Export, export_project, load_export
from .shacl import validate

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data" / "kg.sqlite"
REPORT_DIR = ROOT / "reports" / "shacl"
EXPORT_DIR = ROOT / "data" / "export"
ALIASES = {"alpha": "alpha/names_paths"}
TROOP_D = "troop_d"
SCOPES = {False: "confirmed", True: "with_proposed"}


def key_of(name: str) -> str:
    """The file name of a project's report and export."""
    return name.replace("/", "__")


def troop_d_store() -> tuple[Store, str]:
    """Troop D, built from its test package by the guided setup with rules only, in a fresh in-memory store."""
    from ..ai.calls import set_default_router
    from ..ai.config import load_config
    from ..intake import steps
    from ..intake.publish import publish
    from ..intake.state import Intake

    old = {k: os.environ.get(k) for k in ("PM_AI",)}
    os.environ["PM_AI"] = "off"
    load_config.cache_clear()
    set_default_router(None)
    try:
        it = Intake.create("Troop D", root=Path(tempfile.mkdtemp()), test=True)
        for s in steps.STEPS[:-1]:
            it.add_file(s.id, s.test_file, (steps.TEST_PACKAGE / s.test_file).read_bytes())
            steps.run(it, s.id, lambda m: None)
        store = Store(":memory:")
        return store, publish(it, store)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        load_config.cache_clear()
        set_default_router(None)


def resolve(name: str, store_path: Path = STORE) -> tuple[Store, str]:
    """(store, project id) for a project name (see module docstring)."""
    if name == TROOP_D:
        return troop_d_store()
    store = Store(store_path)
    projects = [r[0] for r in store.conn.execute("SELECT DISTINCT project FROM nodes")]
    project = ALIASES.get(name, name)
    if project in projects:
        return store, project
    site = [p for p in projects if p.split("/")[0] == name]
    if len(site) == 1:
        return store, site[0]
    raise SystemExit(f"project {name!r} is not in {store_path}" + (f"; this site has {site}" if site else
                                                                   f"; projects: {sorted(projects)}"))


def roundtrip(export: Export, path: Path) -> dict:
    """Read the written file back: the node and edge counts must match what was exported."""
    back = load_export(path)
    ok = (len(back["nodes"]) == export.summary["nodes"] and len(back["edges"]) == export.summary["edges"]
          and not back["statements_without_fact"] and back["ids_roundtrip"])
    return {"ok": ok, "nodes": len(back["nodes"]), "edges": len(back["edges"]),
            "statements_without_fact": back["statements_without_fact"]}


def run(name: str, km: KnowledgeModel, include_proposed: bool = False, out: Path | None = None,
        report_dir: Path = REPORT_DIR, store_path: Path = STORE, engine: str | None = None) -> dict:
    """Export, read back, validate; write the Turtle file and the report. Returns the report entry."""
    store, project = resolve(name, store_path)
    t0 = time.perf_counter()
    export = export_project(store, project, km, include_proposed=include_proposed)
    scope = SCOPES[include_proposed]
    out = Path(out) if out else EXPORT_DIR / f"{key_of(name)}.{scope}.ttl"
    export.write(out)
    seconds = round(time.perf_counter() - t0, 2)
    rt = roundtrip(export, out)
    report = validate(export, km, engine=engine)
    report.update(name=name, export_seconds=seconds, roundtrip=rt, generated=time.strftime("%Y-%m-%d %H:%M"),
                  turtle=_display(out))
    path = Path(report_dir) / f"{key_of(name)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = json.loads(path.read_text()) if path.exists() else {}
    doc.update(name=name, project=project)
    doc.setdefault("scopes", {})[scope] = report
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    report["report_path"] = _display(path)
    return report


def _display(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def load_reports(report_dir: Path = REPORT_DIR) -> dict[str, dict]:
    """Every report on disk, by name: {"name", "project", "scopes": {scope: report}}."""
    out = {}
    for path in sorted(Path(report_dir).glob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("scopes"):
            out[doc.get("name") or path.stem] = doc
    return out


def text(report: dict) -> str:
    """The report as the script prints it."""
    ex, t, rt = report["export"], report["totals"], report["roundtrip"]
    lines = [
        f"{report['project']}  ({report['scope']})",
        f"  export: {ex['nodes']} nodes {ex['nodes_by_kind']}, {ex['edges']} edges {ex['edges_by_relation']}"
        f"  -> {report['turtle']}",
    ]
    if ex["edges_left_out"]:
        lines.append(f"  edges left out (an end is not exported): {ex['edges_left_out']}")
    if ex["undeclared"]["classes"] or ex["undeclared"]["relations"]:
        lines.append(f"  UNDECLARED terms: {ex['undeclared']}")
    lines.append(f"  round trip: {'ok' if rt['ok'] else 'MISMATCH'} ({rt['nodes']} nodes, {rt['edges']} edges read back)")
    lines.append(f"  SHACL ({report['engine']}, {report['seconds']} s): "
                 f"building rules {t['building_rules'] - t['building_rules_failing']}/{t['building_rules']} pass, "
                 f"{t['building_failures']} failing nodes; Brick shapes: {t['brick_violations']} violations, "
                 f"{t['brick_warnings']} warnings")
    for r in report["rules"]:
        mark = "FAIL" if r["failed"] else "ok  "
        lines.append(f"    {mark} {r['origin']:8} {r['label'][:60]:60} {r['passed']:>5} pass {r['failed']:>5} fail")
        for f in r["failing"][:3]:
            lines.append(f"           - {f['id']} ({f['class']}): {'; '.join(f['messages'])[:110]}")
    if t["outside_project"]:
        lines.append(f"  results on the ontology itself, not the project (ignored): {t['outside_project']}")
    lines.append(f"  report: {report.get('report_path', '')}")
    return "\n".join(lines)
