"""Why it matters: the case for a building knowledge graph as the foundation for agentic, autonomous buildings.
Numbers come from the latest score report, so the page never claims more than was measured."""

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

REPORT = ROOT / "reports/score_v1.json"


def scores() -> dict:
    try:
        return {r["project"]: r for r in json.loads(REPORT.read_text())}
    except (OSError, ValueError, KeyError):
        return {}


s = scores()
alpha, bravo = s.get("alpha/names_paths"), s.get("bravo/names_paths")

st.html("<style>.lead{font-size:1.3rem;line-height:1.5;opacity:.85;max-width:52rem}</style>")
st.title("Buildings can't run themselves until software understands them")
st.html('<p class="lead">Every building automation system holds thousands of points with names like '
        "<code>AHU1_SAT-sp</code> or <code>Clg_Valve_Cmd</code>. People decode them by hand, building by "
        "building. AI agents can't. The <b>knowledge graph</b> turns that tangle into a typed, connected, "
        "traceable map of the building: the foundation agents need to monitor, diagnose and act.</p>")

if alpha:
    secs = alpha["points"] * alpha["seconds_per_1000_points"] / 1000
    c = st.columns(4)
    c[0].metric(f"Points mapped in {secs:.1f} s", f"{alpha['points']:,}", border=True)
    c[1].metric("On the right equipment", f"{alpha['H1_grouped_right_pct']:.0f}%", border=True)
    c[2].metric("Need no human review", f"{100 - alpha['review_pct']:.0f}%", border=True)
    c[3].metric("Facts with source + confidence", "100%", border=True)
    st.caption("Measured against ground truth on Project Haystack example site Alpha, from names and folders "
               f"only, with {alpha['llm_calls']} LLM calls.")

st.divider()
st.header("The problem")
c = st.columns(3)
with c[0].container(border=True):
    st.subheader(":material/password: Cryptic")
    st.write("Thousands of points per building, named differently by every contractor. "
             "`CWP-1 ISO Valve`, `DSP_SP_Curr_Value`, `Occupied Htg Setpoint`.")
with c[1].container(border=True):
    st.subheader(":material/engineering: Manual")
    st.write("Engineers decode names, tag points and draw the relationships by hand. "
             "Weeks per building, redone on every project.")
with c[2].container(border=True):
    st.subheader(":material/visibility_off: Invisible to agents")
    st.write("An agent can't tell a setpoint from a sensor, or which boiler heats which room. "
             "Without that, it can watch data but can't reason or act.")

st.header("The knowledge graph")
st.write("Each point gets a meaning, a home and its connections, every one with its source and confidence:")
with st.container(border=True):
    st.markdown("`Clg_Valve_Cmd` &nbsp;→&nbsp; **Valve command** (cooling) &nbsp;·&nbsp; on **AHU-2** "
                "&nbsp;·&nbsp; AHU-2 is fed by the **chilled water plant** &nbsp;·&nbsp; AHU-2 feeds **88 VAV boxes**")
    st.caption("A real fact from Alpha's graph. The class comes from the shared knowledge model (Brick standard), "
               "the links from the equipment templates.")

st.header("What it unlocks: agents that act")
st.write("**\"Zone 1-2-81 is too warm. What's wrong?\"** An agent walks the graph instead of the drawings:")
# Each step opens that equipment in 3D with the "Chilled water running warm" scenario, so the walk can be shown live.
DEMO = "alpha/names_paths"
steps = [
    ("thermostat", "Zone temperature", "belongs to **VAV 1-2-81**: damper 100% open, airflow below setpoint",
     "eq:Airside AHU-2/VAV 1-2-81"),
    ("air", "VAV 1-2-81", "is fed by **AHU-2**: supply air around 61 °F against a 55 °F setpoint, cooling valve 100%",
     "eq:Airside AHU-2"),
    ("water_drop", "AHU-2", "is fed by the **chilled water plant**: CH-1 supply water running warm, over 50 °F",
     "eq:Waterside Chilled Water Plant/CH-1"),
    ("build", "Conclusion", "the cause is upstream. **One work order for the chilled water plant**, "
                            "not thirty hot-call tickets for thirty zones", None),
]
for icon, head, text, equip in steps:
    with st.container(border=True, horizontal=True, vertical_alignment="center"):
        st.markdown(f":material/{icon}: **{head}** {text}")
        if equip:
            st.page_link("views/equipment_3d.py", label="See it live", icon=":material/view_in_ar:",
                         query_params={"project": DEMO, "equip": equip, "scenario": "chw_warm"}, width="content")
st.caption("Simulated values from the \"Chilled water running warm\" scenario; the path through the graph is real.")

st.header("What you can build on it")
uses = [
    ("monitor_heart", "Fault detection & diagnosis", "Rules and agents that know what each point means and what it affects."),
    ("energy_savings_leaf", "Energy optimisation", "Reset setpoints across the chain from plant to zone, safely."),
    ("task_alt", "Commissioning & QA", "Check every expected sensor exists and is wired to the right equipment."),
    ("forum", "Ask the building", "Plain-language questions answered from the graph, with sources."),
    ("handyman", "Work orders", "Route the right fault to the right trade with the right context."),
    ("domain", "Portfolio rollout", "Same apps on every building, without per-site engineering."),
]
for row in (uses[:3], uses[3:]):
    for col, (icon, head, text) in zip(st.columns(3), row):
        with col.container(border=True):
            st.markdown(f"**:material/{icon}: {head}**")
            st.caption(text)

st.header("Why it compounds")
c = st.columns(3)
c[0].markdown("**1 · Map a building**  \nRules and templates do most of the work; people review the rest.")
c[1].markdown("**2 · Learn from the review**  \nRepeated fixes become conventions for that contractor or customer.")
c[2].markdown("**3 · The next building maps better**  \nShared knowledge improves with every project; "
              "each graph stays the customer's own.")

if bravo:
    st.info(f"**Honest numbers.** On an unseen hospital (Bravo, held out from all tuning), "
            f"{bravo['H1_grouped_right_pct']:.0f}% of points land on the right equipment and "
            f"{bravo['H2_exact_pct']:.0f}% get the exact class on first sight. That gap is what review and tribal "
            "knowledge close.", icon=":material/science:")

c = st.columns([1, 1, 3])
c[0].page_link("views/how.py", label="How it works", icon=":material/arrow_forward:")
c[1].page_link("views/projects.py", label="See the projects", icon=":material/apartment:")
