"""Knowledge model explorer: the reusable model measured against one mapped project. Read-only.
The model is edited in /knowledge_model (YAML/TTL, reviewed in git); this page shows where it is weak.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import km_explorer as kx  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.scoring.score import DEFAULT_ACCEPT, GT_DIR, load_ground_truth  # noqa: E402

DB = ROOT / "data/kg.sqlite"
st.set_page_config(page_title="Knowledge model", layout="wide")


@st.cache_resource
def knowledge_model():
    return load_knowledge_model()


@st.cache_resource
def ground_truth(site: str):
    return load_ground_truth(site)


km = knowledge_model()
store = Store(DB)
projects = [r[0] for r in store.conn.execute("SELECT DISTINCT project FROM nodes ORDER BY project")]
with st.sidebar:
    st.header("Measure against")
    if projects:
        default = projects.index("alpha/names_paths") if "alpha/names_paths" in projects else 0
        project = st.selectbox("Project", projects, index=default, key="km_project")
    else:
        project = None
        st.caption("No mapped projects yet, so only the model itself is shown.")
    accept = st.slider("Auto-accept at confidence ≥", 0.0, 1.0, DEFAULT_ACCEPT, 0.05, key="km_accept")
    site = project.split("/")[0] if project else ""
    gt = ground_truth(site) if project and (GT_DIR / site).exists() else None
    if site == "bravo":
        st.warning("Bravo is the held-out test set. Look, but don't change the model because of what you see here.")
    st.caption("Edit the model in `knowledge_model/` and rerun the mapper; this page is read-only.")

st.title("Knowledge model")
classes = km.classes.values()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Classes", len(km.classes), help="Brick subset + BA extension")
c2.metric("Equipment / point classes", f"{sum(i.kind == 'equipment' for i in classes)} / {sum(i.kind == 'point' for i in classes)}")
c3.metric("From the BA extension", sum(i.source == "ba" for i in classes))
c4.metric("Templates", len(km.templates))
c5.metric("Abbreviations / words", f"{len(km.name_rules.abbreviations)} / {len(km.name_rules.vocabulary)}")
st.caption(f"Brick {km.brick_version} subset · relations: {', '.join(km.relations)} · "
           f"BA relations: {', '.join(km.ba_relations)}"
           + (f" · measured against **{project}**" + (" with ground truth" if gt else " (no ground truth)") if project else ""))

if not project:
    st.stop()

tab_c, tab_t, tab_u, tab_r, tab_m = st.tabs(["Classes", "Templates", "Unknown words", "Relations", "Missing from the model"])

# --- Classes -----------------------------------------------------------------------------------
with tab_c:
    cov = pd.DataFrame(kx.class_coverage(km, store, project, gt, accept))
    f1, f2, f3 = st.columns([1, 1, 2])
    kind = f1.selectbox("Kind", ["all", "point", "equipment", "other"], key="km_kind")
    used = f2.toggle("Only classes used here", key="km_used")
    weak = f3.toggle("Only weak classes (precision or recall below 80%)", disabled=gt is None, key="km_weak")
    view = cov
    if kind != "all":
        view = view[view["kind"] == kind]
    if used:
        view = view[(view["instances"] > 0) | (view["true points"] > 0)]
    if weak:
        view = view[(view["precision %"].fillna(100) < 80) | (view["recall %"].fillna(100) < 80)]
    view = view.assign(name=[" " * d + c for c, d in zip(view["class"], view["depth"])]).reset_index(drop=True)
    cols = ["name", "kind", "defined in", "instances", "to review", "human decided", "true points",
            "precision %", "recall %", "used by templates"]
    st.caption(f"{len(view)} of {len(cov)} classes, indented under their parent in the model. "
               "Precision: of points we gave this class, % right. Recall: of points that truly are this class, % found. "
               "Select a row for details.")
    left, right = st.columns([1.6, 1])
    with left:
        ev = st.dataframe(view[cols], hide_index=True, width="stretch", height=560, on_select="rerun",
                          selection_mode="single-row", key=f"km_cls_{project}",
                          column_config={"name": st.column_config.TextColumn("class", width="medium"),
                                         "defined in": st.column_config.TextColumn("from", width="small"),
                                         "kind": st.column_config.TextColumn(width="small"),
                                         "precision %": st.column_config.NumberColumn(format="%.0f"),
                                         "recall %": st.column_config.NumberColumn(format="%.0f")})
    with right:
        if not ev.selection.rows:
            st.info("Select a class.")
        else:
            row = view.iloc[ev.selection.rows[0]]
            d = kx.class_detail(km, store, project, row["class"], gt)
            st.subheader(row["class"])
            st.caption(" › ".join(reversed(d["ancestors"])) or "(top of the model)")
            if d["definition"]:
                st.write(d["definition"])
            st.markdown(f"`{d['uri']}` · {row['defined in']} · group *{row['group']}*")
            if d["children"]:
                st.markdown("**Subclasses in the model:** " + ", ".join(d["children"]))
            if row["used by templates"]:
                st.markdown(f"**Templates:** {row['used by templates']}")
            if d["examples"]:
                st.markdown("**Example names here:** " + ", ".join(f"`{e}`" for e in d["examples"]))
            if gt is not None:
                if d["truly this, mapper said"]:
                    st.markdown("**Truly this class, but the mapper said**")
                    st.dataframe(pd.DataFrame(d["truly this, mapper said"], columns=["mapper said", "points"]),
                                 hide_index=True, width="stretch")
                if d["mapper said this, truly"]:
                    st.markdown("**The mapper said this class, but truly**")
                    st.dataframe(pd.DataFrame(d["mapper said this, truly"], columns=["true class", "points"]),
                                 hide_index=True, width="stretch")

# --- Templates ---------------------------------------------------------------------------------
with tab_t:
    fit = kx.template_fit(km, store, project)
    st.dataframe(pd.DataFrame([{k: t[k] for k in ("template", "class", "instances", "missing a required point",
                                                  "fewer points than expected", "more points than expected",
                                                  "expected points")} for t in fit]),
                 hide_index=True, width="stretch")
    tid = st.selectbox("Template", [t["template"] for t in fit], key="km_tpl")
    t = next(x for x in fit if x["template"] == tid)
    st.markdown(f"**{t['template']}** → `{t['class']}` · {t['description']}")
    a, b = st.columns([1.5, 1])
    with a:
        st.markdown(f"**Point slots**: how often each is filled on the {t['instances']} equipment of this type")
        st.dataframe(pd.DataFrame(t["slots"]), hide_index=True, width="stretch",
                     column_config={"filled %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%")})
    with b:
        st.markdown("**Point classes that fit no slot** (candidates for a new slot, or wrong classes)")
        if t["extra classes"]:
            st.dataframe(pd.DataFrame(t["extra classes"], columns=["class", "points"]), hide_index=True, width="stretch")
        else:
            st.caption("None.")
        st.markdown("**Relations the template expects**")
        st.dataframe(pd.DataFrame(t["relations"]), hide_index=True, width="stretch")

# --- Unknown words -----------------------------------------------------------------------------
with tab_u:
    unk = pd.DataFrame(kx.unknown_tokens(store, project, accept))
    if unk.empty:
        st.success("Every word in the point names is known to the name rules.")
    else:
        st.caption(f"{len(unk)} words the name rules don't know, touching {unk['points'].sum()} point mentions. "
                   "Each one added to `knowledge_model/name_rules/abbreviations.yaml` can lift every point that uses it.")
        st.dataframe(unk, hide_index=True, width="stretch", height=560)

# --- Relations ---------------------------------------------------------------------------------
with tab_r:
    rel = pd.DataFrame(kx.relation_usage(km, store, project))
    gap = rel[(rel["links"] == 0) & rel["expected by a template"]]
    if len(gap):
        st.warning(f"{len(gap)} relation(s) the templates expect were never found in this project.")
    st.caption("Equipment-to-equipment relations in the graph, grouped by class (has point is left out).")
    st.dataframe(rel, hide_index=True, width="stretch", height=560)

# --- Missing -----------------------------------------------------------------------------------
with tab_m:
    if gt is None:
        st.info("Needs ground truth for this project.")
    else:
        miss = pd.DataFrame(kx.missing_classes(km, store, project, gt))
        if miss.empty:
            st.success("Every ground-truth class in this project is in the model.")
        else:
            st.caption(f"{len(miss)} ground-truth classes ({miss['points'].sum()} points) are not in the model, "
                       "so the mapper can never get them exactly right.")
            st.dataframe(miss, hide_index=True, width="stretch")
