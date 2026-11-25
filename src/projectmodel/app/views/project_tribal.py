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

from projectmodel import curator, interview, notes  # noqa: E402
from projectmodel.app.shell import active_project, box, get_store, knowledge_model, table  # noqa: E402
from projectmodel.conventions import layer_table, load_layers, scopes_for  # noqa: E402
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
conventions = layer_table(load_layers(scopes)) if scopes else []
setup = Intake(project.split("/")[0]) if project.endswith("/documents") else None
rules = knowledge.get(setup) if setup and setup.s else {"tags": [], "terms": [], "notes": []}
human = summaries(store).get(project, {}).get("human", 0)
waiting = curator.pending(store, project)

with box("tk_head", f"Tribal knowledge · {label(project)}", "groups"):
    st.caption("What engineers, operators and contractors know about this building that no document says. Notes "
               "travel with the graph as context; conventions and rules change how the names are read.")
    c = st.columns(4)
    c[0].metric("Notes", len(active), f"{len(every) - len(active)} resolved or superseded" if len(every) > len(active)
                else None, border=True, delta_color="off")
    c[1].metric("Conventions in force", len(conventions), border=True)
    c[2].metric("Setup rules", len(rules["tags"]) + len(rules["terms"]), border=True)
    c[3].metric("Review decisions", human, f"{len(waiting)} proposed convention{'s' if len(waiting) != 1 else ''}"
                if waiting else None, help="Every correction a person saved is knowledge about one point; the same "
                "fix made twice becomes a proposed convention (Shared knowledge → Tribal knowledge).", border=True,
                delta_color="off")

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
    if waiting:
        st.markdown(f"**Proposed from review fixes, waiting for approval** ({len(waiting)})")
        table(pd.DataFrame([{"proposal": p["id"], "says": p["payload"]["title"],
                             "fixes": len(p["evidence"]), "would change": p["checks"]["would_change"]}
                            for p in waiting]), hide_index=True, width="stretch")
    if conventions:
        st.markdown("**Conventions** (conventions/ and learned conventions in knowledge/skills/, layered knowledge "
                    "model ← contractor ← customer ← site)")
        table(pd.DataFrame(conventions), hide_index=True, width="stretch")
    if rules["tags"] or rules["terms"]:
        st.markdown("**Taught in the guided setup**")
        table(pd.DataFrame(
            [{"kind": "tag", "says": f"{t['prefix']} is a {t['class']}", "by": t["by"]} for t in rules["tags"]]
            + [{"kind": "term", "says": f"{t['phrase']} is a {t['class']}", "by": t["by"]} for t in rules["terms"]]),
            hide_index=True, width="stretch")
    if not conventions and not (rules["tags"] or rules["terms"]):
        st.caption("No rules of its own: this building is read with the shared knowledge model alone.")
    st.page_link("views/tribal.py", label="Shared tribal knowledge, above all projects", icon=":material/groups:")

with box("tk_interview", "Interview a site person", "record_voice_over"):
    st.caption("A short scripted interview (the voice agent asks the same questions). Every answer becomes a note; "
               "answers that state a naming rule in the shape asked for become proposed conventions, which change "
               "nothing until a person approves them under Shared knowledge → Tribal knowledge.")
    with st.form("tk_interview_form", clear_on_submit=True):
        person = st.text_input("Who is answering", placeholder="Name and role, e.g. Sam, facilities lead")
        answers = {qid: st.text_area(text, key=f"tk_q_{qid}", height=68) for qid, _, text in interview.QUESTIONS}
        if st.form_submit_button("File the answers", icon=":material/save:"):
            if not person.strip():
                st.error("Say who is answering.")
            else:
                res = interview.capture(store, knowledge_model(), project, answers, person.strip())
                st.success(f"{len(res['notes'])} notes filed, {len(res['proposals'])} conventions proposed.")
                for u in res["unread"]:
                    st.caption(f"Kept as a note only: “{u['answer']}” ({u['why']})")
