"""Why it matters: the case for a building knowledge graph as the foundation for agentic, autonomous buildings.
Numbers come from the latest score report, so the page never claims more than was measured. The page is a
scroll-synced story (app/story.py): one card per argument, each with one visual."""

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.story import Go, Section, features, hero, p, pills, steps, story, tiles  # noqa: E402

REPORT = ROOT / "reports/score_v1.json"


def scores() -> dict:
    try:
        return {r["project"]: r for r in json.loads(REPORT.read_text())}
    except (OSError, ValueError, KeyError):
        return {}


# One real fact from Alpha's graph: a point, its class, its equipment, and what that equipment is fed by and feeds.
FACT = """<svg viewBox="0 0 440 340" role="img" aria-label="Clg_Valve_Cmd is a valve command on AHU-2, which is fed
by the chilled water plant and feeds 88 VAV boxes">
<g class="rise" style="--i:0"><rect class="n" x="20" y="148" width="170" height="44" rx="10"/>
  <text class="mono" x="105" y="175" text-anchor="middle">Clg_Valve_Cmd</text></g>
<g class="rise" style="--i:1"><path class="e" d="M105 192V276"/><text class="lbl" x="115" y="238">is a</text>
  <rect class="n d" x="20" y="276" width="170" height="44" rx="10"/>
  <text x="105" y="303" text-anchor="middle">Valve command</text></g>
<g class="rise" style="--i:2"><path class="e" d="M190 170H250"/>
  <text class="lbl" x="220" y="160" text-anchor="middle">has point</text>
  <rect class="n a" x="250" y="148" width="170" height="44" rx="10"/>
  <text x="335" y="175" text-anchor="middle">AHU-2</text></g>
<g class="rise" style="--i:3"><path class="e" d="M335 64V148"/><text class="lbl" x="345" y="110">feeds</text>
  <rect class="n" x="250" y="20" width="170" height="44" rx="10"/>
  <text x="335" y="47" text-anchor="middle">Chilled water plant</text></g>
<g class="rise" style="--i:4"><path class="e" d="M335 192V276"/><text class="lbl" x="345" y="238">feeds</text>
  <rect class="n" x="250" y="276" width="170" height="44" rx="10"/>
  <text x="335" y="303" text-anchor="middle">88 VAV boxes</text></g>
<g class="rise" style="--i:5"><text class="lbl" x="20" y="38">every node and link carries</text>
  <text class="lbl" x="20" y="54">source · method · confidence</text></g>
</svg>"""

# The loop: map, learn the site's habits, the next building maps better. A dot runs round it.
LOOP = """<svg viewBox="0 0 440 300" role="img" aria-label="A loop: map a building, learn each site's habits, the
next building maps better">
<circle class="ring" cx="220" cy="160" r="92"/>
<circle class="runner" r="4.5"><animateMotion dur="9s" repeatCount="indefinite"
  path="M220 68a92 92 0 1 1 -.1 0z"/></circle>
<text class="big" x="220" y="157" text-anchor="middle">Shared knowledge</text>
<text class="lbl" x="220" y="175" text-anchor="middle">grows with every project</text>
<g class="rise" style="--i:0"><circle class="num" cx="220" cy="68" r="16"/>
  <text x="220" y="73" text-anchor="middle">1</text>
  <text class="big" x="220" y="34" text-anchor="middle">Map a building</text></g>
<g class="rise" style="--i:2"><circle class="num" cx="299.7" cy="206" r="16"/>
  <text x="299.7" y="211" text-anchor="middle">2</text>
  <text class="big" x="330" y="262" text-anchor="middle">Learn each site's habits</text>
  <text class="lbl" x="330" y="280" text-anchor="middle">conventions per contractor, customer</text></g>
<g class="rise" style="--i:4"><circle class="num" cx="140.3" cy="206" r="16"/>
  <text x="140.3" y="211" text-anchor="middle">3</text>
  <text class="big" x="108" y="262" text-anchor="middle">Next building maps better</text>
  <text class="lbl" x="108" y="280" text-anchor="middle">each graph stays the customer's</text></g>
</svg>"""

# Each step opens that equipment in 3D with the "Chilled water running warm" scenario, so the walk can be shown live.
DEMO = "alpha/names_paths"


def live(equip: str) -> Go:
    return Go("See it live in 3D", "views/equipment_3d.py", "view_in_ar",
              {"project": DEMO, "equip": equip, "scenario": "chw_warm"})


WALK = steps([
    ("thermostat", "Zone temperature", "on <b>VAV 1-2-81</b>: damper 100% open, airflow below setpoint",
     live("eq:Airside AHU-2/VAV 1-2-81")),
    ("air", "VAV 1-2-81", "fed by <b>AHU-2</b>: supply air near 61 °F against 55 °F, cooling valve 100%",
     live("eq:Airside AHU-2")),
    ("water_drop", "AHU-2", "fed by the <b>chilled water plant</b>: CH-1 supply water over 50 °F",
     live("eq:Waterside Chilled Water Plant/CH-1")),
    ("build", "One work order", "for the chilled water plant, not thirty hot-call tickets for thirty zones", None),
])

USES = tiles([
    ("monitor_heart", "Fault detection & diagnosis", "Rules and agents that know what each point means and affects."),
    ("energy_savings_leaf", "Energy optimisation", "Reset setpoints from plant to zone, safely."),
    ("task_alt", "Commissioning & QA", "Check every expected sensor exists, on the right equipment."),
    ("forum", "Ask the building", "Plain-language questions answered from the graph, with sources."),
    ("handyman", "Work orders", "The right fault to the right trade, with the right context."),
    ("domain", "Portfolio rollout", "The same apps on every building, no per-site engineering."),
])

s = scores()
alpha = s.get("alpha/names_paths")

hero("Buildings can't run themselves until software understands them",
     "Every building automation system holds thousands of points with names like <code>AHU1_SAT-sp</code> or "
     "<code>Clg_Valve_Cmd</code>. People decode them by hand, building by building. AI agents can't. The "
     "<b>knowledge graph</b> turns that tangle into a typed, connected, traceable map of the building: the "
     "foundation agents need to monitor, diagnose and act.")

if alpha:
    secs = alpha["points"] * alpha["seconds_per_1000_points"] / 1000
    c = st.columns(4)
    c[0].metric(f"Points mapped in {secs:.1f} s", f"{alpha['points']:,}", border=True)
    c[1].metric("On the right equipment", f"{alpha['H1_grouped_right_pct']:.0f}%", border=True)
    c[2].metric("Exactly the right class", f"{alpha['H2_exact_pct']:.0f}%", border=True)
    c[3].metric("Facts with source + confidence", "100%", border=True)
    st.caption("Measured against ground truth on Project Haystack example site Alpha, from names and folders "
               f"only, with {alpha['llm_calls']} LLM calls.")

story([
    Section("The problem", "password", "Thousands of points. No meaning.",
            p("A building's control system speaks in names nobody outside the project can read.")
            + features([
                ("password", "Cryptic.", "Named differently by every contractor, thousands per building."),
                ("engineering", "Manual.", "Engineers decode, tag and link them by hand. Weeks per building, "
                                           "redone on every project."),
                ("visibility_off", "Invisible to agents.", "An agent can't tell a setpoint from a sensor, or which "
                                                           "boiler heats which room."),
            ]),
            pills(["AHU1_SAT-sp", "Clg_Valve_Cmd", "CWP-1 ISO Valve", "DSP_SP_Curr_Value", "Occupied Htg Setpoint"])),
    Section("The knowledge graph", "hub", "Every point gets a meaning, a home and its connections.",
            p("<code>Clg_Valve_Cmd</code> becomes a <b>valve command</b> on <b>AHU-2</b>, which is fed by the "
              "chilled water plant and feeds 88 VAV boxes.",
              "A real fact from Alpha's graph. The class comes from the shared knowledge model (Brick standard), "
              "the links from the equipment templates."),
            FACT, [Go("How it works", "views/how.py")]),
    Section("Agents that act", "smart_toy", "“Zone 1-2-81 is too warm. What's wrong?”",
            p("An agent walks the graph instead of the drawings: from the zone, up to what feeds it, until it "
              "finds the cause.",
              "Values are simulated with the “Chilled water running warm” scenario; the path through the graph "
              "is real."),
            WALK, [Go("Watch the agent do it", "views/agent_tour.py", "play_circle")]),
    Section("What you can build", "widgets", "One graph, many applications.",
            p("Once software knows what each point means and what it affects, the same applications run on every "
              "building."),
            USES, [Go("What a complete graph is", "views/complete_graph.py")]),
    Section("Why it compounds", "trending_up", "Every building makes the next one easier.",
            p("Rules and templates give every point and equipment a best guess. Each site's naming habits become "
              "conventions for that contractor or customer.",
              "Shared knowledge improves with every project; each graph stays the customer's own."),
            LOOP, [Go("See the projects", "views/projects.py", "apartment")]),
], key="why_story")
