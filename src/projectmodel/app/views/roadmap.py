"""Roadmap: docs/plan-workflow-ai.md in plain words for a new user. What the app does, the principles, where AI
plays (today and next), Brick versus what we add, the harsh reality (the stress test), the work packages, and how
complete each project is with what to do next.

A scroll-synced story (app/story.py) like How it works and Ontology. Live data: the stages and packages from
projectmodel/roadmap.py, the stress results from reports/stress_intake.json (scripts/stress_intake.py), and each
project's completeness from projectmodel/progress.py (the graph standard behind the Complete graph page).
"""

import json
import sys
from html import escape
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import progress  # noqa: E402
from projectmodel.app.shell import get_store, knowledge_model  # noqa: E402
from projectmodel.app.story import Go, Section, features, hero, icon, p, steps, story, tiles  # noqa: E402
from projectmodel.intake.coverage import stress_state  # noqa: E402
from projectmodel.intake.state import list_intakes  # noqa: E402
from projectmodel.projects import label, list_projects, main_projects  # noqa: E402
from projectmodel.roadmap import PACKAGES, PRINCIPLES, REAL_SETS, STAGES, WAVES  # noqa: E402

STRESS = ROOT / "reports/stress_intake.json"
REAL = ROOT / "reports/real_sets.json"
DB = ROOT / "data/kg.sqlite"
km = knowledge_model()

STYLE = """<style>
.story { --c-ok: #1D9E75; --c-ai: #6E64D8; --c-ask: #C98316; --c-bad: #D85A30; }
.rm-ok { --c: var(--c-ok); } .rm-ai { --c: var(--c-ai); } .rm-ask { --c: var(--c-ask); } .rm-bad { --c: var(--c-bad); }
.rm-off { --c: var(--muted); }
.rm-b { display: inline-flex; align-items: center; gap: 4px; font-size: .68rem; font-weight: 600; line-height: 1;
  padding: 4px 7px; border-radius: 4px; white-space: nowrap; border: 1px solid color-mix(in srgb, var(--c) 50%, transparent);
  background: color-mix(in srgb, var(--c) 13%, var(--bg)); color: color-mix(in srgb, var(--c) 75%, var(--fg)); }
.rm-b.rm-dash { background: transparent; border-style: dashed; }
.rm-b .ms { font-size: 13px; }
.rm-box { background: var(--bg); border: 1px solid var(--line); border-radius: 10px; overflow: hidden;
  box-shadow: 0 10px 28px -18px rgba(0, 0, 0, .3); max-width: 470px !important; }
.rm-box > header { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-bottom: 1px solid var(--line);
  font-size: .78rem; color: var(--muted); flex-wrap: wrap; }
.rm-rows { list-style: none; margin: 0; padding: 2px 0; }
.rm-rows li { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 10px; align-items: center; margin: 0;
  padding: 7px 14px; border-bottom: 1px solid color-mix(in srgb, var(--fg) 6%, transparent); }
.rm-rows li:last-child { border-bottom: 0; }
.rm-rows li > .ms { font-size: 18px; color: var(--muted); }
.rm-rows b { font-size: .82rem; font-weight: 600; display: block; }
.rm-rows small { font-size: .72rem; color: var(--muted); line-height: 1.35; display: block; }
.rm-roles { display: flex; gap: 4px; }
.rm-lays { display: grid; gap: 8px; max-width: 460px !important; }
.rm-lay { padding: 12px 14px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--c) 45%, transparent);
  background: color-mix(in srgb, var(--c) 8%, var(--bg)); }
.rm-lay h4 { margin: 0 0 3px; padding: 0; font-size: .86rem; font-weight: 600; }
.rm-lay span { font-size: .76rem; color: var(--muted); line-height: 1.4; }
.rm-waves { display: grid; gap: 10px; max-width: 470px !important; }
.rm-wave h5 { margin: 0 0 5px; padding: 0; font-size: .7rem; letter-spacing: .06em; text-transform: uppercase;
  color: var(--muted); font-weight: 600; }
.rm-pk { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; gap: 8px; align-items: start; padding: 7px 10px;
  border: 1px solid var(--line); border-radius: 8px; background: var(--bg); margin-bottom: 5px; }
.rm-pk > code { font-size: .74rem; font-weight: 600; color: var(--acc); padding-top: 1px; }
.rm-pk b { font-size: .8rem; font-weight: 600; display: block; }
.rm-pk small { font-size: .72rem; color: var(--muted); line-height: 1.35; display: block; }
.rm-parts { list-style: none; margin: 6px 0 0; padding: 0; display: grid; gap: 2px; }
.rm-parts li { font-size: .72rem; color: var(--muted); display: flex; gap: 5px; align-items: center; margin: 0; }
.rm-parts .ms { font-size: 14px; }
.rm-parts .rm-y { color: var(--c-ok); }
.rm-meter { height: 6px; border-radius: 3px; background: color-mix(in srgb, var(--fg) 9%, transparent); overflow: hidden; }
.rm-meter i { display: block; height: 100%; border-radius: 3px; background: var(--c, var(--acc)); }
.rm-projs { display: grid; gap: 12px; max-width: 470px !important; }
.rm-proj { background: var(--bg); border: 1px solid var(--line); border-radius: 10px; padding: 14px;
  box-shadow: 0 10px 28px -18px rgba(0, 0, 0, .3); }
.rm-top { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.rm-ring { --p: 0; width: 54px; height: 54px; border-radius: 50%; flex: none; display: grid; place-items: center;
  background: conic-gradient(var(--acc) calc(var(--p) * 1%), color-mix(in srgb, var(--fg) 9%, transparent) 0); }
.rm-ring b { width: 42px; height: 42px; border-radius: 50%; background: var(--bg); display: grid; place-items: center;
  font-size: .8rem; }
.rm-top h4 { margin: 0; padding: 0; font-size: .9rem; font-weight: 600; display: flex; gap: 6px; align-items: center;
  flex-wrap: wrap; }
.rm-top small { font-size: .74rem; color: var(--muted); }
.rm-lbars { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px 12px; margin-bottom: 10px; }
.rm-lbar span { font-size: .7rem; color: var(--muted); display: flex; justify-content: space-between; gap: 4px;
  margin-bottom: 3px; }
.rm-next { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; border-top: 1px solid var(--line);
  padding-top: 8px; }
.rm-next li { margin: 0; }
.rm-next button, .rm-next div { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto; gap: 8px; width: 100%;
  align-items: start; padding: 5px 6px; border-radius: 6px; font-size: .75rem; line-height: 1.4; }
.rm-next button:hover { background: var(--tint); }
.rm-next .ms { font-size: 16px; color: var(--acc); }
.rm-next div .ms { color: var(--muted); }
.rm-cap { font-size: .68rem; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); font-weight: 600;
  margin: 2px 0 4px; }
.rm-stats { display: flex; gap: 8px; padding: 10px 14px; border-bottom: 1px solid var(--line); }
.rm-stats div { flex: 1; text-align: center; padding: 6px 4px; border-radius: 8px;
  background: color-mix(in srgb, var(--c) 9%, var(--bg)); }
.rm-stats b { display: block; font-size: 1.2rem; color: color-mix(in srgb, var(--c) 80%, var(--fg)); }
.rm-stats span { font-size: .68rem; color: var(--muted); }
@container (max-width: 520px) { .rm-lbars { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>"""


def badge(text: str, kind: str, ic: str = "", dash: bool = False) -> str:
    return (f'<span class="rm-b rm-{kind}{" rm-dash" if dash else ""}">{icon(ic) if ic else ""}'
            f'{escape(text)}</span>')


def meter(pct: float, kind: str = "") -> str:
    return f'<div class="rm-meter {f"rm-{kind}" if kind else ""}"><i style="width:{max(pct, 1.5 if pct else 0):.0f}%">' \
           '</i></div>'


# 1 · What it does
pipeline = steps([
    ("upload_file", "Documents and BMS data", "Floor plans, schedules, sequences, the controls submittal, the BMS "
                                              "export.", Go("Add a building", "views/add_building.py")),
    ("rule", "Readers", "Rules read what they know. Where rules run out, they ask you; an AI reader comes next.",
     None),
    ("hub", "Knowledge graph", "Every unit, point, room and control link, typed in Brick plus our extension, each "
                               "with its source.", Go("See the ontology", "views/ontology.py", "category")),
    ("fact_check", "Review", "You confirm, fix or reject. Nothing unsure is accepted silently.", None),
    ("view_in_ar", "Graphics, digital twin, agent", "Built from the confirmed graph, never from guesses.",
     Go("Digital twin", "views/digital_twin.py", "domain")),
])


# 3 · Where AI plays
def role(kind: str, on: str) -> str:
    """One stage's three roles as badges: rules always, a model now / next / never, a person."""
    ai = {"now": badge("AI now", "ai", "auto_awesome"), "next": badge("AI next", "ai", "schedule", dash=True),
          "never": badge("no AI", "off", "block", dash=True)}[on]
    return f'<span class="rm-roles">{badge("Rules", "ok")}{ai}{badge("You", "ask")}</span>' if kind else ai


stage_rows = "".join(
    f'<li>{icon(s["icon"])}<span><b>{escape(s["name"])}</b><small>{escape(s["model"])}</small></span>'
    f'{role("all", s["ai"])}</li>' for s in STAGES)
n_now = sum(1 for s in STAGES if s["ai"] == "now")
n_next = sum(1 for s in STAGES if s["ai"] == "next")
ai_map = (STYLE + f'<div class="rm-box"><header>{badge("Rules", "ok")} every stage {badge("AI now", "ai")} '
          f'{n_now} stages {badge("AI next", "ai", dash=True)} {n_next} stages {badge("You", "ask")} decide</header>'
          f'<ul class="rm-rows">{stage_rows}</ul></div>')


# 4 · Brick and what we add
brick = [c for c, i in km.classes.items() if i.source == "brick"]
ba = [c for c, i in km.classes.items() if i.source == "ba"]
layers = STYLE + '<div class="rm-lays">' + "".join(
    f'<div class="rm-lay rm-{k}"><h4>{escape(h)}</h4><span>{escape(t)}</span></div>' for k, h, t in [
        ("ok", f"Brick, the standard · {len(brick)} classes, {len(km.relations)} relations",
         "The words for equipment, points and spaces (VAV, Zone_Air_Temperature_Sensor, feeds, hasPoint). Anyone "
         "who knows Brick can read our graph."),
        ("ai", f"Our BA extension · {len(ba)} classes, {len(km.ba_relations)} relations",
         "What Brick lacks for building automation: controllers, networks, schedules, trend logs, and which "
         "controller hosts which point. Each hangs under a Brick parent."),
        ("off", "Our own layer · not ontology",
         f"Provenance on every fact, {len(km.templates)} equipment templates, "
         f"{len(km.name_rules.abbreviations)} naming abbreviations, conventions and notes. What makes the graph "
         "trustworthy and reusable."),
        ("ai", "Declared in W1",
         "Control links from sequences (drives, resets, requires…) and serves in the extension; Floor, Room and "
         "Zone as RealEstateCore locations. The loader refuses any term the app writes that is not declared."),
    ]) + "</div>"


# 5 · The harsh reality
def stress_view() -> tuple[str, dict]:
    if not STRESS.exists():
        return p("Run <code>scripts/stress_intake.py</code> to measure."), {}
    runs = json.loads(STRESS.read_text())
    base = next((r for r in runs if r["scenario"] == "baseline"), None)
    if not base or "read" not in base:
        return p("Re-run <code>scripts/stress_intake.py</code>: the report is from an older version."), {}

    out, counts = [], {"reads": 0, "asks": 0, "quiet": 0, "silent": 0}
    for r in runs:
        if r["scenario"] == "baseline":
            continue
        state, short = stress_state(r, base)
        counts[state] += 1
        kind, ic, word = {"reads": ("ok", "check", "reads it"), "asks": ("ask", "help", "asks you"),
                          "quiet": ("bad", "visibility_off", "partly, quietly"),
                          "silent": ("bad", "error", "silent")}[state]
        why = {"reads": "same result as the original",
               "asks": f"short on {', '.join(short)}; it says so and asks",
               "quiet": f"short on {', '.join(short)}, and nothing says so yet",
               "silent": "a step read nothing and asked nothing"}[state]
        out.append(f'<li>{icon("description")}<span><b>{escape(r["scenario"])}</b><small>{escape(why)}</small></span>'
                   f'{badge(word, kind, ic)}</li>')
    stats_html = "".join(f'<div class="rm-{k}"><b>{counts[s]}</b><span>{w}</span></div>' for s, k, w in [
        ("reads", "ok", "rules read it"), ("asks", "ask", "rules ask you"),
        ("quiet", "bad", "partly, quietly"), ("silent", "bad", "silent")])
    return (STYLE + f'<div class="rm-box"><div class="rm-stats">{stats_html}</div>'
            f'<ul class="rm-rows">{"".join(out)}</ul></div>'), counts


stress_html, stress_counts = stress_view()


def real_view() -> str:
    """The rules on real buildings from other firms (scripts/run_real_sets.py), against a person's hand count. Dev
    sets only: the held-out set is never shown in detail."""
    if not REAL.exists():
        return ""
    runs = [r for r in json.loads(REAL.read_text()) if r.get("role") == "dev" and r.get("mode") == "sheets"
            and r["set"] in REAL_SETS]
    rows = []
    for r in runs:
        exp, h = REAL_SETS[r["set"]], r["headline"]
        cells = []
        for k, word in (("rooms", "rooms"), ("equipment", "units"), ("sequences", "sequences")):
            pct = 100 * h.get(k, 0) / exp[k] if exp[k] else 0
            kind = "ok" if pct >= 90 else "ask" if pct >= 40 else "bad"
            cells.append(f'<div class="rm-lbar"><span>{word}<b>{h.get(k, 0)} of ~{exp[k]}</b></span>'
                         f'{meter(min(pct, 100), kind)}</div>')
        rows.append(f'<li>{icon("apartment")}<span><b>{escape(exp["name"])}</b><div class="rm-lbars" '
                    f'style="margin:6px 0 0">{"".join(cells)}</div></span><span></span></li>')
    return (f'<div class="rm-box"><header>{icon("travel_explore")} Real buildings from other '
            f'firms · rules only · a third set is held out</header><ul class="rm-rows">{"".join(rows)}</ul></div>')


real_html = real_view()


# 6 · Roadmap
def package(pk: dict) -> str:
    st_ = {"done": badge("done", "ok", "check"), "doing": badge("in progress", "ai", "progress_activity"),
           "next": badge("next", "ai", dash=True), "later": badge("later", "off", dash=True)}[pk["status"]]
    parts = ""
    if pk.get("parts"):
        done = sum(1 for _, d in pk["parts"] if d)
        parts = meter(100 * done / len(pk["parts"]), "ok") + '<ul class="rm-parts">' + "".join(
            f'<li><span class="ms{" rm-y" if d else ""}">{"check_circle" if d else "radio_button_unchecked"}</span>'
            f'{escape(t)}</li>' for t, d in pk["parts"]) + "</ul>"
    plain = f'<small>{escape(pk["plain"])}</small>' if pk["wave"] < 3 else ""  # later waves: one line each
    return (f'<div class="rm-pk" title="{escape(pk["plain"])}"><code>{pk["id"]}</code><span><b>{escape(pk["name"])}'
            f'</b>{plain}{parts}</span>{st_}</div>')


waves = STYLE + '<div class="rm-waves">' + "".join(
    f'<div class="rm-wave"><h5>{escape(name)}</h5>{"".join(package(pk) for pk in PACKAGES if pk["wave"] == w)}</div>'
    for w, name in WAVES.items()) + "</div>"


# 7 · Your projects
@st.cache_data(show_spinner="Measuring each project…")
def measured(stamp: float) -> tuple[list[dict], list[dict]]:
    store = get_store()
    projs = [progress.project_progress(store, km, pr, n_next=3) for pr in main_projects(list_projects(store))]
    setups = [progress.setup(i["slug"]) for i in list_intakes()]
    return projs, [s for s in setups if not s["published"]]


def project_card(r: dict) -> str:
    bars = "".join(f'<div class="rm-lbar"><span>{escape(lay["name"])}<b>{lay["pct"]:.0f}%</b></span>'
                   f'{meter(lay["pct"], "ok" if lay["pct"] >= 90 else "ask" if lay["pct"] >= 40 else "bad")}</div>'
                   for lay in r["layers"])
    rows = []
    for n in r["next"]:
        pkg = badge(n["package"], "ai", dash=True) if n["package"] else ""
        body = f'{icon("arrow_forward" if n["page"] else "schedule")}<span>{escape(n["action"])}</span>{pkg}'
        go = Go(n["name"], n["page"]) if n["page"] else None
        rows.append(f'<li><button type="button" {go.attrs()}>{body}</button></li>' if go else f"<li><div>{body}</div></li>")
    demo = badge("Demo set", "ai", "star") if r["demo"] else ""
    cap = "What a building from documents adds" if r["demo"] else "Next, to complete it"
    note = ("BMS points only (Project Haystack): kept as is, for demos and scoring." if r["demo"] else
            f'{r["done"]} of {r["facts"]} facts done')
    return (f'<div class="rm-proj"><div class="rm-top"><div class="rm-ring" style="--p:{r["overall"]:.0f}">'
            f'<b>{r["overall"]:.0f}%</b></div><div><h4>{escape(label(r["project"]))} {demo}</h4>'
            f'<small>{escape(note)}</small></div></div><div class="rm-lbars">{bars}</div>'
            f'<div class="rm-cap">{cap}</div><ul class="rm-next">{"".join(rows)}</ul></div>')


def setup_card(s: dict) -> str:
    go = Go("Continue the setup", "views/add_building.py")
    cov = badge(f'{s["coverage"]} coverage gaps', "bad", "error") if s["coverage"] else ""
    return (f'<div class="rm-proj"><div class="rm-top"><div class="rm-ring" style="--p:{s["pct"]}"><b>{s["pct"]}%'
            f'</b></div><div><h4>{escape(s["name"])} {badge("In the guided setup", "ask", "pending")}</h4>'
            f'<small>{s["read"]} of {s["steps"]} documents read · {s["questions"]} open questions</small> {cov}</div>'
            f'</div><ul class="rm-next"><li><button type="button" {go.attrs()}>{icon("arrow_forward")}'
            f'<span>{escape(s["next"])}</span></button></li></ul></div>')


projs, setups = measured(DB.stat().st_mtime if DB.exists() else 0.0)
projects_html = STYLE + '<div class="rm-projs">' + "".join(map(project_card, projs)) + \
    "".join(map(setup_card, setups)) + "</div>"
demo = next((r for r in projs if r["demo"]), None)
others = [r for r in projs if not r["demo"]]

hero("Where we are, and where this goes.",
     "The app turns a building's documents and BMS data into a reviewed knowledge graph. Rules do the exact work; "
     "AI reads what rules can't; you decide. This page explains the principles, where AI plays, how we build on "
     "Brick, and what comes next, with how complete each of your projects is today.")

story([
    Section("What it does", "conversion_path", "From documents to a graph you can trust.",
            p("Upload a building's documents one step at a time. Each reader turns pages and rows into facts: rooms, "
              "units, points, control links. Every fact keeps the page it came from and how sure we are.",
              "The facts become one <b>knowledge graph</b> of the building. Graphics, the digital twin and the agent "
              "are all built from it, so they are only as good as what you confirmed.")
            + features([("star", "Alpha stays the demo.", "A public BMS-only site, kept unchanged for demos and "
                                                          "scoring."),
                        ("add_business", "New buildings use the new workflow.", "The guided setup, with the "
                                                                                "guardrails below.")]),
            STYLE + pipeline),
    Section("Principles", "rule", "Six rules for using AI without losing exactness.",
            p("AI is good at reading drawings, odd tables and prose. It is not good at being exactly right every "
              "time. So it proposes, rules check, and you decide.",
              "A model is used where rules run out, never everywhere. The cheapest model that beats rules on a "
              "measured test gets the job."),
            tiles([(ic, h, t) for ic, h, t in PRINCIPLES])),
    Section("Where AI plays", "auto_awesome", "Rules in every stage. AI where the documents vary. You decide.",
            p("Every stage keeps its rules. AI runs in two stages today: classifying BMS points the rules can't, "
              "and the agent. The next ones are the stages where real documents vary the most.")
            + features([("map", "Floor plans first.", "Room outlines, which room a tag sits in, scanned sheets."),
                        ("link", "Point binding.", "Tying one point across BMS, submittal, equipment and graphic."),
                        ("view_in_ar", "Graphics.", "Generated as code and data, never as pictures."),
                        ("block", "Validation never.", "The building rules stay exact.")]),
            ai_map),
    Section("Brick and ours", "category", "Brick is the language. We add what it lacks.",
            p("<b>Brick</b> is an open standard for describing buildings: its classes and relations are the "
              "vocabulary of our graph, so the graph is readable by any Brick tool.",
              "Brick has no words for some building-automation facts, so <b>our extension</b> adds them under Brick "
              "parents. Our <b>own layer</b> (provenance, templates, naming rules) is what lets a graph be trusted "
              "and lets the next building go faster."),
            layers,
            [Go("See the ontology", "views/ontology.py", "category")]),
    Section("Harsh reality", "crisis_alert", "Another firm's documents break rules. Real buildings break them more.",
            p("First, one building with one realistic change at a time: another firm's titles, room numbers, heading "
              "style, another vendor's export, a scanned sheet.",
              f"Before the guardrails, 9 of the first 16 dropped a step to zero or near it, 7 of them silently. Now, "
              f"of {sum(stress_counts.values())}, "
              f"<b>{stress_counts.get('reads', 0)}</b> read correctly, <b>{stress_counts.get('asks', 0)}</b> say "
              f"what they missed and ask you, <b>{stress_counts.get('quiet', 0)}</b> still read only part with "
              f"nothing said, and <b>{stress_counts.get('silent', 0)}</b> are silent.",
              "Then three real buildings from other firms, read by the rules unchanged (below the list). Most of "
              "each building is missed, and some facts are wrong: canopy hoods tagged CH-n become chillers. Those "
              "sets are the yardstick for the AI reader (W6, W8), and one stays held out to keep the score honest.")
            if stress_counts else p("The stress test results are not available yet."),
            f'<div style="display:grid;gap:12px;width:100%">{stress_html}{real_html}</div>'),
    Section("Roadmap", "route", "What comes next, in order.",
            p("The plan is built in waves. The first wave makes the base honest: guardrails, valid ontology terms, "
              "a data model for many sources, and a scorer for every AI job.",
              "The second wave brings AI into the readers, plans first. Graphics, binding and the learning loop "
              "follow. Each package lands only when it beats rules alone on a measured test.")
            + features([("check_circle", "First wave done:", "guardrails and real test sets (W0), every term "
                                                             "declared (W1), facts proposed until two sources agree "
                                                             "(W3), and calibrated confidence: 90% sure is right 9 "
                                                             "times in 10 (W5)."),
                        ("check_circle", "Second wave done:", "Brick export checked by SHACL (W2), controllers, "
                                                              "networks and units from the riser (W4), an AI plan "
                                                              "reader: 49% → 83% on real sets (W6), and sequences "
                                                              "read as control logic: 18% → 87% (W8)."),
                        ("pending", "Now:", "W7 point binding with AI and W10 the learning loop. Then W9 graphics "
                                            "and W11 agent tools.")]),
            waves),
    Section("Your projects", "monitoring", "How complete each project is, and what to do next.",
            p("Each project is measured against the same standard as the Complete graph page: six layers, from "
              "spaces to trust. The ring is the share of that standard the graph meets today.",
              (f"The demo set, Alpha, is at <b>{demo['overall']:.0f}%</b>: strong on equipment, points and "
               "behaviour, empty on spaces, because a BMS export has no floor plans. That gap is exactly what the "
               "guided setup fills for a new building." if demo else "")
              + (f" {len(others)} other projects are measured the same way." if others else "")
              + (f" {len(setups)} building{'s are' if len(setups) != 1 else ' is'} still in the guided setup." if
                 setups else "")),
            projects_html,
            [Go("What a complete graph is", "views/complete_graph.py", "task_alt"),
             Go("Add a building", "views/add_building.py", "add_business")]),
], key="roadmap")
