"""3D view of one piece of equipment: its parametric model with every point pinned on it, provenance on click, and
simulated values (spec-equipment-3d §7).

Left: every piece of equipment with a 3D model in the active project, filtered by type and name, so you always see
what else there is and pick one. Above the viewer: previous / next and the equipment this one is fed by or feeds.

Deep link: /Equipment_3D?project=alpha/names_paths&equip=eq:Airside AHU-2
Fed-by / feeds links inside the viewer open the linked equipment on this page.
"""

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app import screen  # noqa: E402
from projectmodel.app.shell import active_project, get_store, knowledge_model, page_tools, box  # noqa: E402
from projectmodel.equipment_view import equipment_payload, load_anchors, render_html  # noqa: E402
from projectmodel.projects import list_projects  # noqa: E402

PAGE = "/Equipment_3D"
TYPES = {"ahu": "AHU", "vav": "VAV", "fcu": "FCU", "chiller": "Chiller", "boiler": "Boiler",
         "pump": "Pump"}  # templates with a 3D model, in picker order
ALL = "all"
# Simulated-value scenarios (keys and labels as in equipment3d/sim.js). One runs app-wide: its clock keeps going as
# you move between equipment, so a fault develops the same way on the plant, the AHU and the VAV.
SCENARIOS = {"normal": "Normal day", "hot": "Hot afternoon", "stuck": "Stuck reheat valve (VAVs with reheat)",
             "chw_warm": "Chilled water running warm"}


def start_scenario() -> None:
    st.session_state["sim_started"] = time.time()


@st.cache_resource
def anchors():
    return load_anchors()


def natural(label: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", label)]


def link(project: str, equip: str, scenario: str = "normal") -> str:
    q = {"project": project, "equip": equip} | ({"scenario": scenario} if scenario != "normal" else {})
    return f"{PAGE}?{urlencode(q)}"


store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)  # the header dropdown; a ?project= deep link sets it

# --- the equipment of this project, with a 3D model -------------------------------------------
rows = {r["id"]: (r["label"], json.loads(r["attrs"])) for r in store.nodes(project, "equipment")}
models = sorted((i for i, (_, a) in rows.items() if a.get("template") in TYPES and a.get("template") in anchors()),
                key=lambda i: (list(TYPES).index(rows[i][1]["template"]), natural(rows[i][0])))
if not models:
    st.warning("This project has no equipment with a 3D model yet.")
    st.stop()
kind = {i: rows[i][1]["template"] for i in models}
fed_by: dict[str, list[str]] = {}
feeds: dict[str, list[str]] = {}
for e in store.edges(project, "feeds"):
    if e["status"] != "rejected" and e["src"] in rows and e["dst"] in rows:
        fed_by.setdefault(e["dst"], []).append(e["src"])
        feeds.setdefault(e["src"], []).append(e["dst"])
parts: dict[str, list[str]] = {}
part_of: dict[str, str] = {}
for e in store.edges(project, "hasPart"):
    if e["status"] != "rejected" and e["dst"] in kind:
        parts.setdefault(e["src"], []).append(e["dst"])
        part_of[e["dst"]] = e["src"]


def upstream(i: str) -> list[str]:
    """What feeds this one, as equipment with a model: a plant group has none, so its lead unit stands in (the
    chilled water plant -> CH-1), which keeps the walk from a VAV up to the chiller one click per step."""
    out = []
    for f in fed_by.get(i, []):
        if f in kind:
            out.append(f)
        elif units := sorted(parts.get(f, []), key=lambda u: (kind[u] not in ("chiller", "boiler"), natural(rows[u][0]))):
            out.append(units[0])
    return out


def downstream(i: str) -> list[str]:
    """What this one feeds, with a model; a plant's unit (CH-1) feeds what its plant feeds."""
    plant_unit = kind[i] in ("chiller", "boiler", "pump")  # a VAV is also a part (of its AHU) but feeds nothing
    return [d for d in feeds.get(i) or (feeds.get(part_of.get(i, ""), []) if plant_unit else []) if d in kind]


counts = Counter(kind.values())
untemplated = len(rows) - len(models)

# --- which one is open: a deep link wins once, then the browser below decides ------------------
qp = st.query_params
asked = qp.get("equip")
if asked and asked != st.session_state.get("_linked_equip"):
    st.session_state["_linked_equip"] = asked
    if asked in kind:
        st.session_state["equip"] = asked
        st.session_state["eq_type"] = kind[asked]
    else:
        st.toast(f"{rows.get(asked, (asked,))[0]} has no 3D model; showing the first AHU instead.",
                 icon=":material/info:")
if (sc := qp.get("scenario")) in SCENARIOS and sc != st.session_state.get("_linked_scenario"):
    st.session_state["_linked_scenario"] = st.session_state["sim_scenario"] = sc
    start_scenario()
if st.session_state.get("equip") not in kind:  # first visit, or the project changed
    st.session_state["equip"] = models[0]
    st.session_state["eq_type"] = kind[models[0]]
equip = st.session_state["equip"]
screen.focus("equipment", equip, rows[equip][0])
if (sc := st.session_state.get("sim_scenario")) and sc != "normal":
    screen.scenario(sc, SCENARIOS.get(sc, sc) + " (simulated)")


def name(i: str) -> str:
    """List label: the type only when the name doesn't already say it ("VAV 1-2-81", but "Chiller · CH-1")."""
    label, t = rows[i][0], TYPES[kind[i]]
    return label if t.lower() in label.lower() else f"{t} · {label}"


def caption(i: str) -> str:
    up = fed_by.get(i, [])
    return f"{rows[i][1].get('points', 0)} points" + (
        f" · fed by {rows[up[0]][0]}" + (f" +{len(up) - 1}" if len(up) > 1 else "") if up else "")


def shown_list() -> list[str]:
    t, q = st.session_state.get("eq_type") or ALL, st.session_state.get("eq_q", "").strip().lower()
    if q:  # a search looks across every type: typing "1-2-8" should find the VAVs whatever the type filter
        return [i for i in models if q in rows[i][0].lower() or any(q in rows[f][0].lower() for f in fed_by.get(i, []))]
    return [i for i in models if t == ALL or kind[i] == t]


def go(target: str) -> None:
    st.session_state["equip"] = target
    if st.session_state.get("eq_type") not in (None, ALL, kind[target]):  # keep the target visible in the list
        st.session_state["eq_type"] = kind[target]


def step(delta: int) -> None:
    lst = shown_list() or models
    i = lst.index(st.session_state["equip"]) if st.session_state["equip"] in lst else -delta
    go(lst[(i + delta) % len(lst)])


with page_tools():
    scenario = st.selectbox("Scenario", list(SCENARIOS), key="sim_scenario", format_func=SCENARIOS.get,
                            on_change=start_scenario, label_visibility="collapsed", width=240,
                            help="Simulated values. The scenario keeps running as you move between equipment.")
browser, main = st.columns([1, 3.4], gap="medium")

# --- browser: type, search, list ---------------------------------------------------------------
with browser, box("eq_list", "Equipment", "view_in_ar", fit=True):
    st.pills("Type", [ALL] + [t for t in TYPES if counts[t]], key="eq_type", label_visibility="collapsed",
             format_func=lambda t: f"All {len(models)}" if t == ALL else f"{TYPES[t]} {counts[t]}")
    st.text_input("Find equipment", key="eq_q", placeholder="Find by name or AHU…", icon=":material/search:",
                  label_visibility="collapsed")
    lst = shown_list()
    with st.container(height=520, border=False):
        if not lst:
            st.caption("No equipment matches.")
        else:
            st.session_state["eq_pick"] = equip if equip in lst else None  # the list always shows what is open
            st.radio("Equipment", lst, key="eq_pick", label_visibility="collapsed",
                     on_change=lambda: st.session_state["eq_pick"] and go(st.session_state["eq_pick"]),
                     format_func=name, captions=[caption(i) for i in lst])
    st.html(f"""<script>/* {json.dumps(equip)} */
      (function scroll(tries) {{
        const el = parent.document.querySelector('.st-key-eq_pick input:checked')?.closest('label');
        if (!el) return tries > 0 && setTimeout(() => scroll(tries - 1), 100);
        let box = el.parentElement;
        while (box && box.scrollHeight <= box.clientHeight + 1) box = box.parentElement;
        if (box) box.scrollTo({{ top: el.offsetTop - box.clientHeight / 2, behavior: "smooth" }});
      }})(60);</script>""", unsafe_allow_javascript=True)
    st.caption(f"{untemplated} more equipment have no 3D model yet (meters, drives, plant groups, or no "
               "template match).")

# --- viewer, with previous / next and related equipment ---------------------------------------
with main, box("eq_view", fit=True):
    lst = shown_list()
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.button("", icon=":material/chevron_left:", on_click=step, args=(-1,), help="Previous in the list",
                  key="eq_prev")
        st.button("", icon=":material/chevron_right:", on_click=step, args=(1,), help="Next in the list",
                  key="eq_next")
        where = f"{lst.index(equip) + 1} of {len(lst)}" if equip in lst else "not in the filtered list"
        st.markdown(f"**{name(equip)}** <span style='opacity:.6'>· {where}</span>",
                    unsafe_allow_html=True, width="content")
        for rel, verb, ids, icon in [("fed by", "is fed by", upstream(equip), ":material/north:"),
                                     ("feeds", "feeds", downstream(equip), ":material/south:")]:
            for i in ids[:2]:
                st.button(rows[i][0], icon=icon, on_click=go, args=(i,), key=f"rel_{rel}_{i}",
                          help=f"{rows[equip][0]} {verb} {rows[i][0]}"
                               + ("" if i in fed_by.get(equip, []) + feeds.get(equip, []) else " (its plant)"),
                          type="tertiary")
            if len(ids) > 2:
                st.caption(f"+{len(ids) - 2} more", width="content")

    qp.update(project=project, equip=equip)  # the address bar is always a deep link to what is on screen
    if scenario != "normal":
        qp["scenario"] = st.session_state["_linked_scenario"] = scenario
    else:
        qp.pop("scenario", None)
        st.session_state["_linked_scenario"] = scenario
    st.session_state["_linked_equip"] = equip
    payload = equipment_payload(store, project, equip, knowledge_model(), anchors())
    # Links inside the viewer open the target on this page (the top window), not inside the iframe.
    payload["links"] = {i: link(project, i, scenario) for i in models if i != equip}
    # The start time, not the elapsed time: the page stays identical between reruns, so the viewer doesn't reload.
    payload["sim"] = {"scenario": scenario, "started": st.session_state.setdefault("sim_started", time.time())}
    payload["link_target"] = "top"
    st.iframe(render_html(payload, st.context.theme.type), height=760)
