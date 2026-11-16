"""The digital twin: the active project's knowledge graph as a building you can walk through. Floors, zones and
equipment in 3D (analysis or realistic), a floor plan, filters, and every asset's points and provenance.

Equipment, points and relations come from the knowledge graph; floors are inferred, geometry is generated and values
are simulated (twin_view.py, and the "What is real" notes in the page). The viewer runs in the browser, so moving
around doesn't rerun the app.
"""

import sys
from pathlib import Path
from urllib.parse import urlencode

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import active_project, get_store, page_tools, viewer_options  # noqa: E402
from projectmodel.projects import list_projects, site_of  # noqa: E402
from projectmodel.twin_view import render_html, twin_payload  # noqa: E402

store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)

with page_tools():
    height = viewer_options("twin", 900)

payload = twin_payload(store, project, site_of(project).name)
if not any(e["type"].startswith("VAV") for e in payload["equip"]):
    st.info("This input has no zones grouped under their equipment yet, so there is little to place on floors. "
            "The twin is most useful on a Names + folders input.", icon=":material/info:")
# Equipment with a 3D model opens on the Equipment 3D page (the top window, not inside the iframe).
payload["links"] = {e["id"]: "/Equipment_3D?" + urlencode({"project": project, "equip": e["id"]})
                    for e in payload["equip"] if e["type"] in ("AHU", "VAV", "VAV (dual duct)", "Chiller", "Boiler",
                                                               "Pump")}
st.iframe(render_html(payload, st.context.theme.type), height=height)
