"""3D view of one piece of equipment: its parametric model with every point pinned on it, provenance on click, and
simulated values (spec-equipment-3d §7).

Deep link: /Equipment_3D?project=alpha/names_paths&equip=eq:Airside AHU-2
Fed-by / feeds links inside the viewer open the linked equipment on this page.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.db.store import Store  # noqa: E402
from projectmodel.equipment_view import equipment_payload, load_anchors, render_html  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402

DB = ROOT / "data/kg.sqlite"
PAGE = "/Equipment_3D"
TYPES = {"ahu": "AHU", "vav": "VAV", "fcu": "FCU", "chiller": "Chiller", "boiler": "Boiler",
         "pump": "Pump"}  # templates with a 3D model, in picker order

st.set_page_config(page_title="Equipment 3D", layout="wide")


@st.cache_resource
def knowledge_model():
    return load_knowledge_model()


@st.cache_resource
def anchors():
    return load_anchors()


def natural(label: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", label)]


def link(project: str, equip: str) -> str:
    return f"{PAGE}?{urlencode({'project': project, 'equip': equip})}"


store = Store(DB)
projects = [r[0] for r in store.conn.execute("SELECT DISTINCT project FROM nodes ORDER BY project")]
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()

qp = st.query_params
with st.sidebar:
    want = qp.get("project")
    default = projects.index(want) if want in projects else projects.index("alpha/names_paths") \
        if "alpha/names_paths" in projects else 0
    project = st.selectbox("Project", projects, index=default)
    rows = [(r["id"], r["label"], json.loads(r["attrs"]).get("template")) for r in store.nodes(project, "equipment")]
    models = sorted(((i, label, t) for i, label, t in rows if t in TYPES and t in anchors()),
                    key=lambda r: (list(TYPES).index(r[2]), natural(r[1])))
    if not models:
        st.warning("This project has no equipment with a 3D model yet.")
        st.stop()
    ids = [i for i, _, _ in models]
    names = {i: f"{TYPES[t]} · {label}" for i, label, t in models}
    asked = qp.get("equip")
    if asked and asked not in names:
        st.info(f"`{asked}` has no 3D model; showing the first AHU instead.")
    equip = st.selectbox("Equipment (type to search)", ids, index=ids.index(asked) if asked in names else 0,
                         format_func=names.get)
    others = len([r for r in rows if r[2] not in TYPES])
    st.caption(f"{len(ids)} with a 3D model; {others} more equipment have none (untemplated equipment needs "
               "review first).")
    height = st.slider("Viewer height", 500, 1400, 820, 20)
    st.caption("Values are simulated. Review decisions show up here after a page refresh.")
qp.update(project=project, equip=equip)  # the address bar is always a deep link to what is on screen

payload = equipment_payload(store, project, equip, knowledge_model(), anchors())
# Links inside the viewer open the target on this page (the top window), not inside the iframe.
payload["links"] = {i: link(project, i) for i in ids if i != equip}
payload["link_target"] = "top"
st.iframe(render_html(payload, st.context.theme.type), height=height)
