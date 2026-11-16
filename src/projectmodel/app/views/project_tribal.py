"""Tribal knowledge of one project: what people know about this building that no document or export says, and the
rules that teach the reader this job's names. Notes are context; conventions and setup rules change the mapping.
The shared view, above all projects, is Shared knowledge → Tribal knowledge."""

import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import notes  # noqa: E402
from projectmodel.app.shell import active_project, box, get_store  # noqa: E402
from projectmodel.conventions import layer_entries, load_layers, scopes_for  # noqa: E402
from projectmodel.intake import knowledge  # noqa: E402
from projectmodel.intake.state import Intake  # noqa: E402
from projectmodel.projects import label, list_projects, summaries  # noqa: E402

store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet.")
    st.stop()
project = active_project(projects)
every = notes.notes_by_project(store, project, status=None)
active = [x for x in every if x["status"] == "active"]
scopes = scopes_for(project)
conventions = layer_entries(load_layers(scopes)) if scopes else []
setup = Intake(project.split("/")[0]) if project.endswith("/documents") else None
rules = knowledge.get(setup) if setup and setup.s else {"tags": [], "terms": [], "notes": []}
human = summaries(store).get(project, {}).get("human", 0)

with box("tk_head", f"Tribal knowledge · {label(project)}", "groups"):
    st.caption("What engineers, operators and contractors know about this building that no document says. Notes "
               "travel with the graph as context; conventions and rules change how the names are read.")
    c = st.columns(4)
    c[0].metric("Notes", len(active), f"{len(every) - len(active)} resolved or superseded" if len(every) > len(active)
                else None, border=True, delta_color="off")
    c[1].metric("Conventions in force", len(conventions), border=True)
    c[2].metric("Setup rules", len(rules["tags"]) + len(rules["terms"]), border=True)
    c[3].metric("Review decisions", human, help="Every correction a person saved is knowledge about one point.",
                border=True)

left, right = st.columns([1.4, 1], gap="medium")
with left, box("tk_notes", "Notes", "sticky_note_2", fit=True):
    if not active:
        st.info("No notes yet. Add them on the Tree page (select equipment or a point), or in the guided setup's "
                "last step.", icon=":material/sticky_note_2:")
    else:
        topics = Counter(x["topic"] for x in active)
        st.caption(" · ".join(f"**{t}** {n}" for t, n in topics.most_common()))
        for x in sorted(active, key=lambda x: (x["topic"], -x["id"])):
            with st.container(border=True):
                st.markdown(f"**{x['target_label'] or 'The whole building'}** · {x['topic']}")
                st.markdown(x["body"])
                st.caption(f"{x['author']} · {x['source']} · {x['updated_at'][:10]}")
    st.page_link("views/notes.py", label="Filter every note", icon=":material/filter_list:")
with right, box("tk_rules", "Rules for this building", "rule", fit=True):
    if conventions:
        st.markdown("**Conventions** (conventions/, layered knowledge model ← contractor ← customer ← site)")
        st.dataframe(pd.DataFrame(conventions), hide_index=True, width="stretch")
    if rules["tags"] or rules["terms"]:
        st.markdown("**Taught in the guided setup**")
        st.dataframe(pd.DataFrame(
            [{"kind": "tag", "says": f"{t['prefix']} is a {t['class']}", "by": t["by"]} for t in rules["tags"]]
            + [{"kind": "term", "says": f"{t['phrase']} is a {t['class']}", "by": t["by"]} for t in rules["terms"]]),
            hide_index=True, width="stretch")
    if not conventions and not (rules["tags"] or rules["terms"]):
        st.caption("No rules of its own: this building is read with the shared knowledge model alone.")
    st.page_link("views/tribal.py", label="Shared tribal knowledge, above all projects", icon=":material/groups:")
