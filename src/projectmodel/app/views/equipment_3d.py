"""Equipment 3D: placeholder until the viewer in docs/spec-equipment-3d.md lands."""

import json
import sys
from collections import Counter
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import active_project, get_store  # noqa: E402
from projectmodel.projects import label, list_projects  # noqa: E402

store = get_store()
projects = list_projects(store)

st.title("Equipment 3D")
st.info("Being built. See docs/spec-equipment-3d.md.", icon=":material/construction:")
st.write("Pick a piece of equipment and see it in 3D: a cut-away model with every point placed where it sits, "
         "live values, moving airflow, and the equipment it feeds.")

if projects:
    project = active_project(projects)
    templates = Counter(json.loads(n["attrs"]).get("template") for n in store.nodes(project, "equipment"))
    shown = {t: n for t, n in templates.items() if t}
    st.subheader(f"Ready to show in {label(project)}")
    cols = st.columns(max(len(shown), 1))
    for col, (t, n) in zip(cols, sorted(shown.items(), key=lambda kv: -kv[1])):
        col.metric(t.upper(), n, border=True)
    st.caption(f"Equipment with a recognised template. {templates.get(None, 0)} more without one "
               "(fan drives, meters, plant groups) will show inside their parent equipment.")
