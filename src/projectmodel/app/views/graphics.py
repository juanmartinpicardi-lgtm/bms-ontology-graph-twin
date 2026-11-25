"""Graphics: the 2D graphics generated from the knowledge graph and the equipment templates (plan §5.4), and how
well they cover the active project.

- Coverage: each equipment type, whether it has a graphic (2D and 3D), its points bound to template anchors, its QA
  result, and the classes of the points that land on no anchor.
- Floors: each level's plan with its units in their rooms (hasLocation / serves, room positions from the plans).
- Systems: the water side (feeds between plant equipment) and the air side (air handlers and what they feed).
- Equipment: the 2D graphic of any equipment, with its QA; the 3D one is on the Equipment 3D page.

Values are simulated (value_model), and every graphic says so.
"""

import sys
from pathlib import Path
from urllib.parse import urlencode

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import active_project, box, get_store, knowledge_model, table  # noqa: E402
from projectmodel.equipment_view import equipment_payload, load_anchors  # noqa: E402
from projectmodel.graphics.drawing import img_tag  # noqa: E402
from projectmodel.graphics.coverage import by_type, equipment_coverage, orphan_points  # noqa: E402
from projectmodel.graphics.equipment2d import render  # noqa: E402
from projectmodel.graphics.floor import render_floor  # noqa: E402
from projectmodel.graphics.qa import check_equipment  # noqa: E402
from projectmodel.graphics.system import render_air, render_water  # noqa: E402
from projectmodel.projects import list_projects, site_of  # noqa: E402
from projectmodel.tree import build_tree  # noqa: E402
from projectmodel.twin_view import twin_payload  # noqa: E402

QA_ICON = {"pass": "✅", "warn": "⚠️", "fail": "❌", "no points": "○", "passive, no points": "·", "no graphic": "—"}

store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)
theme = st.context.theme.type or "light"


@st.cache_data(show_spinner="Rendering every equipment graphic…", ttl=300)
def coverage(project: str, revision: int):
    tree = build_tree(store, project)
    rows = equipment_coverage(store, project, knowledge_model(), load_anchors(), tree)
    return rows, by_type(rows), orphan_points(tree)


revision = max((r["revision"] for r in store.nodes(project)), default=0)
rows, types, orphans = coverage(project, revision)
if not rows:
    st.info("This project has no equipment yet.")
    st.stop()


def svg(g) -> None:
    st.html(f"<div style='overflow:auto'>{img_tag(g.svg(theme, max_width=None), g.drawing.title)}</div>")


def qa_line(qa: dict) -> None:
    st.caption(f"{QA_ICON.get(qa['status'], '')} QA **{qa['status']}** · "
               + " · ".join(f"{c['rule']}: {c['detail']}" for c in qa["checks"]))


tab_cov, tab_floor, tab_sys, tab_eq = st.tabs(["Coverage", "Floors", "Systems", "Equipment"])

with tab_cov, box("gx_cov", "Coverage per equipment type", "fact_check"):
    total, bound = sum(t.points for t in types), sum(t.bound for t in types)
    need = [t for t in types if t.needs_graphic]
    c1, c2, c3 = st.columns(3)
    c1.metric("Types with a graphic", f"{sum(t.has_graphic for t in need)} of {len(need)}",
              help="Types with no template and no points (passive specialties) need none.")
    c2.metric("Points on their anchor", f"{bound} of {total}", f"{100 * bound / max(1, total):.0f}%", delta_color="off")
    c3.metric("Graphics passing QA", f"{sum(1 for r in rows if r.status == 'pass')} of "
                                     f"{sum(1 for r in rows if r.qa)}")
    table([{"Type": t.cls, "Units": t.count, "Template": ", ".join(t.templates) or "—",
            "Graphic": "yes" if t.has_graphic else "no" if t.needs_graphic else "not needed",
            "Points bound": f"{t.bound} / {t.points}",
            "QA": ", ".join(f"{QA_ICON.get(k, '')} {k} {v}" for k, v in sorted(t.qa.items())),
            "On no anchor": ", ".join(f"{c} ×{n}" for c, n in t.unplaced_classes.most_common(6))}
           for t in types], hide_index=True)
    if orphans:
        st.caption(f"{len(orphans)} points are on no equipment in the graph (no hasPoint), so on no graphic: "
                   + ", ".join(lb for _, lb, _ in orphans[:30]) + (" …" if len(orphans) > 30 else ""))

twin = twin_payload(store, project, site_of(project).name)

with tab_floor, box("gx_floor", "Floor graphics", "layers"):
    if twin.get("source") != "graph":
        st.info("This project's graph has no floors or rooms (a Haystack site), so there is no plan to place units "
                "on. Floor graphics come from projects built from drawings.", icon=":material/info:")
    else:
        lv = st.pills("Level", [lv["id"] for lv in twin["levels"]], default=twin["levels"][0]["id"],
                      key="gx_level", format_func=lambda i: next(x["name"] for x in twin["levels"] if x["id"] == i))
        if lv:
            g = render_floor(twin, lv)
            qa_line(g.qa)
            svg(g)

with tab_sys, box("gx_sys", "System graphics", "account_tree"):
    which = st.segmented_control("System", ["Water side", "Air side"], default="Water side", key="gx_sys_kind")
    g = render_water(twin) if which != "Air side" else render_air(twin)
    qa_line(g.qa)
    svg(g)

with tab_eq, box("gx_eq", "Equipment graphics", "view_in_ar"):
    drawn = [r for r in rows if r.has_2d]
    if not drawn:
        st.info("No equipment here matches a template with a graphic.")
    else:
        pick = st.selectbox("Equipment", [r.id for r in drawn], key="gx_eq_pick",
                            format_func=lambda i: next(f"{r.label} · {r.template}" for r in drawn if r.id == i))
        p = equipment_payload(store, project, pick, knowledge_model(), load_anchors())
        g = render(p)
        qa_line(check_equipment(p, g))
        st.markdown(f"[Open in 3D](/Equipment_3D?{urlencode({'project': project, 'equip': pick})})")
        svg(g)
