"""Review screen: proposed items sorted by confidence; accept / fix / reject in bulk.

Run: .venv/bin/streamlit run src/projectmodel/app/review_app.py
Decisions are written to data/kg.sqlite with method=human and survive mapper reruns.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import review  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.scoring.score import DEFAULT_ACCEPT, GT_DIR, load_ground_truth, score_project  # noqa: E402

DB = ROOT / "data/kg.sqlite"

st.set_page_config(page_title="Project Model review", layout="wide")


@st.cache_resource
def knowledge_model():
    return load_knowledge_model()


@st.cache_resource
def ground_truth(site: str):
    return load_ground_truth(site)


km = knowledge_model()
store = Store(DB)

# --- Sidebar: project, reviewer, live score ----------------------------------------------------
projects = [r[0] for r in store.conn.execute("SELECT DISTINCT project FROM nodes ORDER BY project")]
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
with st.sidebar:
    st.header("Review")
    default = projects.index("alpha/names_paths") if "alpha/names_paths" in projects else 0
    project = st.selectbox("Project", projects, index=default)
    reviewer = st.text_input("Reviewer", value=st.session_state.get("reviewer", ""), placeholder="your name")
    st.session_state["reviewer"] = reviewer
    accept_at = st.slider("Auto-accept at confidence ≥", 0.0, 1.0, DEFAULT_ACCEPT, 0.05)

    site = project.split("/")[0]
    if (GT_DIR / site).exists():
        s = score_project(store, project, ground_truth(site), km, accept_at)
        st.subheader("Score")
        if site == "bravo":
            st.caption("Bravo is the held-out test set. Don't tune on it.")
        c1, c2 = st.columns(2)
        c1.metric("H1 grouping", f"{s['H1_grouped_right_pct']}%")
        c2.metric("H2 class exact", f"{s['H2_exact_pct']}%")
        c1.metric("Exact, auto-accepted", f"{s['H2_auto_accepted_exact_pct']}%")
        c2.metric("To review", f"{s['review_pct']}%")
        st.metric("Decided by a human", s["human_decided"])
    else:
        st.caption("No ground truth for this project, so no score.")


def need_reviewer() -> bool:
    if not reviewer.strip():
        st.error("Enter your name in the sidebar first, so every decision is attributed.")
        return True
    return False


def frame(kind: str) -> pd.DataFrame:
    rows = []
    hp = {e["dst"]: e["src"] for e in store.edges(project, "hasPoint") if e["status"] != "rejected"}
    for n in store.nodes(project, kind):
        a = json.loads(n["attrs"])
        alts = ", ".join(f"{c} ({s:g})" for c, s in a.get("alternatives", [])[1:4])
        rows.append({
            "select": False, "id": n["id"], "name": n["label"],
            "equipment": (hp.get(n["id"], "")[3:] if kind == "point" else a.get("template") or ""),
            "class": n["class"] or "", "confidence": n["confidence"], "method": n["method"],
            "status": n["status"], "alternatives": alts if kind == "point" else "",
            "points": a.get("points", "") if kind == "equipment" else "",
        })
    return pd.DataFrame(rows)


def review_tab(kind: str):
    df = frame(kind)
    if df.empty:
        st.info(f"No {kind} nodes.")
        return
    f1, f2, f3, f4 = st.columns([1.2, 1, 1.4, 1.4])
    statuses = f1.multiselect("Status", ["proposed", "confirmed", "rejected"], ["proposed"], key=f"st_{kind}")
    max_conf = f2.slider("Confidence ≤", 0.0, 1.0, 1.0, 0.05, key=f"mc_{kind}")
    text = f3.text_input("Name / equipment contains", key=f"tx_{kind}")
    cls_filter = f4.selectbox("Class", ["(any)"] + sorted(c for c in df["class"].unique() if c), key=f"cl_{kind}")
    view = df[df["status"].isin(statuses) & (df["confidence"] <= max_conf)]
    if text:
        view = view[view["name"].str.contains(text, case=False) | view["equipment"].str.contains(text, case=False)]
    if cls_filter != "(any)":
        view = view[view["class"] == cls_filter]
    view = view.sort_values(["confidence", "name"]).reset_index(drop=True)

    limit = st.number_input("Rows shown", 10, 5000, 200, 50, key=f"lim_{kind}")
    st.caption(f"{len(view)} {kind} items match, lowest confidence first. Showing {min(len(view), limit)}.")
    view = view.head(int(limit))
    if st.checkbox("Select all shown", key=f"all_{kind}"):
        view["select"] = True
    cols = ["select", "name", "equipment", "class", "confidence", "method", "status"]
    cols += ["alternatives"] if kind == "point" else ["points"]
    edited = st.data_editor(
        view[cols + ["id"]], hide_index=True, width="stretch", height=420,
        disabled=[c for c in cols + ["id"] if c != "select"],
        column_config={"id": None, "confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                       "select": st.column_config.CheckboxColumn("✓", width="small")},
        key=f"ed_{kind}_{project}",
    )
    chosen = edited[edited["select"]]["id"].tolist()
    st.write(f"**{len(chosen)} selected**")

    a1, a2, a3 = st.columns([1, 1, 2.5])
    if a1.button("Accept", key=f"acc_{kind}", disabled=not chosen, type="primary"):
        if not need_reviewer():
            st.session_state["flash"] = f"Accepted {review.accept(store, project, chosen, reviewer)} {kind} items."
            st.rerun()
    if a2.button("Reject", key=f"rej_{kind}", disabled=not chosen):
        if not need_reviewer():
            st.session_state["flash"] = f"Rejected {review.reject(store, project, chosen, reviewer)} {kind} items."
            st.rerun()
    with a3.form(key=f"fix_{kind}", border=False):
        options = km.by_kind("point" if kind == "point" else "equipment")
        c_sel, c_btn = st.columns([3, 1])
        new_cls = c_sel.selectbox("Fix class to", options, label_visibility="collapsed", key=f"fc_{kind}")
        if c_btn.form_submit_button("Fix class", disabled=not chosen) and not need_reviewer():
            n = review.fix_class(store, km, project, chosen, new_cls, reviewer)
            st.session_state["flash"] = f"Set {n} {kind} items to {new_cls}."
            st.rerun()
    if kind == "point":
        equips = sorted(n["id"] for n in store.nodes(project, "equipment"))
        with st.form(key="move", border=False):
            m1, m2 = st.columns([3, 1])
            target = m1.selectbox("Move selected points to equipment", equips, format_func=lambda e: e[3:])
            if m2.form_submit_button("Move", disabled=not chosen) and not need_reviewer():
                n = review.move_points(store, project, chosen, target, reviewer)
                st.session_state["flash"] = f"Moved {n} points to {target[3:]}."
                st.rerun()


st.title("Project Model review")
st.caption(f"{project} · knowledge graph in {DB.relative_to(ROOT)} · decisions are saved as method=human")
if msg := st.session_state.pop("flash", None):
    st.success(msg)
tab_p, tab_e = st.tabs(["Points", "Equipment"])
with tab_p:
    review_tab("point")
with tab_e:
    review_tab("equipment")
