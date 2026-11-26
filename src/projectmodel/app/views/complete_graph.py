"""Complete graph: what a complete, reliable building graph is for this use case, layer by layer, where each fact
comes from, and how far Alpha (names + folders) is today. The definition lives in projectmodel/graph_standard.py;
the page is graph_standard.html.

Below it, the SHACL check of each exported project (W2): pass and fail counts per rule, and the failing nodes, read
from reports/shacl/<project>.json, which scripts/export_brick.py writes.
"""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import get_store, knowledge_model  # noqa: E402
from projectmodel.export.run import REPORT_DIR, SCOPES, load_reports  # noqa: E402
from projectmodel.graph_standard import PROJECT, definition, render_html, status  # noqa: E402
from projectmodel.projects import label, list_projects  # noqa: E402
from projectmodel.sequences import behaviour, document_path, sequences_payload  # noqa: E402
from projectmodel.scoring.score import DEFAULT_ACCEPT, GT_DIR, load_ground_truth, score_project  # noqa: E402

APP = ROOT / "src/projectmodel/app"
SOURCES = [ROOT / "data/kg.sqlite", APP / "graph_standard.html", ROOT / "src/projectmodel/graph_standard.py",
           document_path(PROJECT.split("/")[0])]
SCOPE_LABEL = {"confirmed": "Confirmed facts", "with_proposed": "Confirmed + proposed"}
PROJECT_LABEL = {"alpha": "Alpha · names + folders", "troop_d": "Troop D · from documents"}


@st.cache_data(show_spinner="Measuring the graph…")
def page(theme: str | None, stamp: tuple) -> str:
    store, km = get_store(), knowledge_model()
    mapped = PROJECT in list_projects(store)
    site = PROJECT.split("/")[0]
    score = score_project(store, PROJECT, load_ground_truth(site), km, DEFAULT_ACCEPT) \
        if mapped and (GT_DIR / site).exists() else None
    seqs = behaviour(sequences_payload(store, km, PROJECT)) if mapped else None
    st_ = status(store, km, PROJECT, score, seqs) if mapped else \
        {f["id"]: {"pct": None, "state": "missing", "note": "Project not mapped yet."} for f in definition()["facts"]}
    return render_html(dict(definition(), status=st_, project_label=label(PROJECT)), theme)


@st.cache_data
def reports(stamp: tuple) -> dict:
    return load_reports()


def rule_rows(report: dict) -> list[dict]:
    return [{"Rule": r["label"], "From": "Building rule" if r["origin"] == "building" else "Brick",
             "Severity": r["severity"], "Checked": r["targets"], "Pass": r["passed"], "Fail": r["failed"]}
            for r in report["rules"]]


def shacl_section() -> None:
    st.header("SHACL check of the export")
    st.write("Each project is exported as Brick Turtle and checked against Brick 1.4.4's own shapes and our "
             "building rules (`knowledge_model/shapes/`). A failure is a gap in the graph to fix in the data or the "
             "readers, never by loosening a rule.")
    found = reports(tuple(p.stat().st_mtime for p in sorted(REPORT_DIR.glob("*.json"))))
    if not found:
        st.info("No SHACL report yet. Run `.venv/bin/python scripts/export_brick.py alpha` (and `troop_d`).")
        return
    c1, c2 = st.columns(2)
    name = c1.selectbox("Project", list(found), format_func=lambda n: PROJECT_LABEL.get(n, found[n]["project"]),
                        key="shacl_project")
    doc = found[name]
    scopes = [s for s in SCOPES.values() if s in doc["scopes"]]
    scope = c2.segmented_control("Facts", scopes, default=scopes[0], format_func=SCOPE_LABEL.get,
                                 key=f"shacl_scope_{name}") or scopes[0]
    rep = doc["scopes"][scope]
    t, ex = rep["totals"], rep["export"]
    m = st.columns(4)
    m[0].metric("Nodes exported", ex["nodes"])
    m[1].metric("Edges exported", ex["edges"])
    m[2].metric("Building rules passing", f"{t['building_rules'] - t['building_rules_failing']} / {t['building_rules']}")
    m[3].metric("Brick violations", t["brick_violations"], help=f"{t['brick_warnings']} warnings besides")
    notes = [f"{rep['project']} · {rep['scope']} · {rep['engine']} · {rep['generated']}",
             "round trip ok" if rep["roundtrip"]["ok"] else "round trip MISMATCH"]
    if ex["edges_left_out"]:
        notes.append("left out because an end is not exported: " +
                     ", ".join(f"{n} {r}" for r, n in ex["edges_left_out"].items()))
    st.caption(" · ".join(notes))
    st.dataframe(rule_rows(rep), hide_index=True, width="stretch")
    for r in rep["rules"]:
        if not r["failed"]:
            continue
        with st.expander(f"**{r['label']}** · {r['failed']} of {r['targets']} fail"):
            if r["comment"]:
                st.caption(r["comment"])
            st.dataframe([{"Node": f["id"], "Label": f["label"], "Class": f["class"], "Why": "; ".join(f["messages"])}
                          for f in r["failing"]], hide_index=True, width="stretch")
            if r["failed"] > len(r["failing"]):
                st.caption(f"The first {len(r['failing'])} of {r['failed']}, as the report keeps them.")
    st.caption("Refresh with `.venv/bin/python scripts/export_brick.py <project> [--include-proposed]`.")


st.title("What a complete graph is")
st.write("For agents to monitor, diagnose and act on a building, the graph must hold everything the building has "
         "(**complete**) and every fact in it must be trustworthy (**reliable**). This page defines both, fact by "
         "fact, and names the source of each one.")
st.iframe(page(st.context.theme.type, tuple(p.stat().st_mtime for p in SOURCES if p.exists())), height="content")
st.caption(f"Today's status is measured live on {label(PROJECT)}. Project documents are read by the guided setup "
           "(Projects › Add a building); sources marked “next” arrive with the Niagara and CPO Studio adapters; "
           "“later” with live data and the site team.")
shacl_section()
