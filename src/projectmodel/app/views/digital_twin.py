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

from projectmodel.app import screen  # noqa: E402
from projectmodel.app.bridge import frame  # noqa: E402
from projectmodel.app.shell import active_project, box, get_store  # noqa: E402
from projectmodel.projects import list_projects, site_of  # noqa: E402
from projectmodel.twin_view import render_html, twin_payload  # noqa: E402

store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)
if msg := st.session_state.pop("flash", None):  # just finished the guided setup: the project lands here
    st.toast(msg, icon=":material/task_alt:")

payload = twin_payload(store, project, site_of(project).name)
if not any(e["type"].startswith("VAV") for e in payload["equip"]):
    st.info("This input has no zones grouped under their equipment yet, so there is little to place on floors. "
            "The twin is most useful on a Names + folders input.", icon=":material/info:")
# Equipment with a 3D model opens on the Equipment 3D page (the top window, not inside the iframe).
payload["links"] = {e["id"]: "/Equipment_3D?" + urlencode({"project": project, "equip": e["id"]})
                    for e in payload["equip"] if e["type"] in ("AHU", "VAV", "VAV (dual duct)", "Chiller", "Boiler",
                                                               "Pump")}
with box("twin", fit=True):  # down to the bottom of the screen; the viewer fills it
    # The viewer says what is selected (a floor, a zone or a unit): kept for the agent's context chips.
    ev = frame(render_html(payload, st.context.theme.type), None, 800, key=f"twin_{project}", title="Digital twin")
if ev and ev.get("name") == "context":
    screen.remember("twin", ev)
if picked := screen.recall("twin"):
    if fl := picked.get("floor"):
        screen.floor(fl["id"], fl["label"])
    if sel := picked.get("sel"):
        screen.focus("equipment", sel["id"], sel["label"])
