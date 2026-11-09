"""All notes for one project: filter by topic, status and author. Orphaned notes (whose equipment,
point or link is no longer in the graph) come first, so nothing written down gets lost silently.
Notes are written and edited in the review app's Tree tab.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import notes  # noqa: E402
from projectmodel.app.shell import active_project, get_store  # noqa: E402
from projectmodel.projects import label, list_projects  # noqa: E402

store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)  # the shared sidebar picker

st.caption(f"{label(project)} · tribal knowledge: context about the building, never graph facts. "
           "Add and edit notes in the review app's Tree tab.")

every = notes.notes_by_project(store, project, status=None)
orphan_ids = {x["id"] for x in notes.orphaned(store, project)}
f1, f2, f3 = st.columns(3)
topics = f1.multiselect("Topic", notes.TOPICS, key="nf_topic")
statuses = f2.multiselect("Status", notes.NOTE_STATUSES, ["active"], key="nf_status")
authors = f3.multiselect("Author", sorted({x["author"] for x in every}), key="nf_author")

shown = [x for x in every if (not topics or x["topic"] in topics) and (not statuses or x["status"] in statuses)
         and (not authors or x["author"] in authors)]
shown.sort(key=lambda x: (x["id"] not in orphan_ids, x["target_kind"] != "project", -x["id"]))
st.caption(f"{len(shown)} of {len(every)} notes shown · {len(orphan_ids)} orphaned in total")
if not shown:
    st.info("No notes match.")
    st.stop()

df = pd.DataFrame([{
    "orphaned": "⚠" if x["id"] in orphan_ids else "",
    "about": x["target_label"] or "(project)", "kind": x["target_kind"], "topic": x["topic"], "note": x["body"],
    "author": x["author"], "source": x["source"] + (f" ({x['source_ref']})" if x["source_ref"] else ""),
    "status": x["status"], "updated": x["updated_at"][:16], "target id": x["target_id"],
} for x in shown])
st.dataframe(df, hide_index=True, width="stretch", height=min(640, 40 + 35 * len(df)),
             column_config={"orphaned": st.column_config.TextColumn("⚠", width="small",
                                                                     help="Target no longer in the graph"),
                            "note": st.column_config.TextColumn(width="large")})
