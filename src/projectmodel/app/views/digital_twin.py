"""The digital twin: the active project's knowledge graph as a building you can walk through. Floors, zones and
equipment in 3D (analysis or realistic), a floor plan, filters, and every asset's points and provenance.

Equipment, points and relations come from the knowledge graph; floors are inferred, geometry is generated and values
are simulated (twin_view.py, and the "What is real" notes in the page). The viewer runs in the browser, so moving
around doesn't rerun the app.
"""

import sys
from pathlib import Path
from html import escape
from urllib.parse import urlencode

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app import screen  # noqa: E402
from projectmodel.app.bridge import frame  # noqa: E402
from projectmodel.app.shell import THEME, active_project, box, get_store, theme  # noqa: E402
from projectmodel.completeness import completeness  # noqa: E402
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
# On top: how complete the graph and the twin are (completeness.py), one card per measure.
c = THEME[theme()]
HUE = {"trusted": "#3BA7FF", "grouped": "#C77DFF", "classed": "#E8A33D", "linked": c["good"], "twin": "#E05FA8"}
cards = "".join(
    f'<div class="kc" title="{escape(k.sub)}"><span class="kc-i" style="--h:{HUE.get(k.key, c["accent"])}">'
    f'<span class="ms">{k.icon}</span></span><div class="kc-b"><p class="kc-t">{escape(k.title)}</p>'
    f'<p class="kc-v" style="color:{c[k.tone]}">{k.share:.0%}</p><p class="kc-s">{escape(k.sub)}</p>'
    f'<div class="kc-bar"><i style="width:{k.share * 100:.1f}%;background:{c[k.tone]}"></i></div></div></div>'
    for k in completeness(store, project, payload))
st.html(f"""<style>
.kcards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }}
.kc {{ display: flex; gap: 10px; padding: 10px 12px 12px; border-radius: 10px; background: {c["card"]};
  box-shadow: {c["shadow"]}; min-width: 0; }}
.kc-i {{ flex: none; width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
  border: 1.5px solid var(--h); color: var(--h); }}
.kc-i .ms {{ font-family: 'Material Symbols Rounded'; font-size: 17px; line-height: 1; }}
.kc-b {{ min-width: 0; flex: 1; }}
.kc-b p {{ margin: 0; line-height: 1.3; }}
.kc-t {{ font-size: 12.5px; color: {c["text2"]}; }}
.kc-v {{ font-size: 18px; font-weight: 700; }}
.kc-s {{ font-size: 11.5px; color: {c["mute"]}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.kc-bar {{ height: 3px; border-radius: 2px; background: {c["line"]}; margin-top: 7px; overflow: hidden; }}
.kc-bar i {{ display: block; height: 100%; border-radius: 2px; }}
</style><div class="kcards">{cards}</div>""")

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
