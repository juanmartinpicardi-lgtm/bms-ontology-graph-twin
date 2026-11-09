"""New project: placeholder for the add-a-building flow. Today projects are added from the command line."""

import streamlit as st

st.info("Coming soon. This is the flow we will build; the controls are disabled for now.", icon=":material/construction:")

with st.container(border=True):
    st.text_input("Building name", placeholder="e.g. Riverside Hospital", disabled=True)
    st.selectbox("Source", ["Project Haystack (JSON / Zinc)", "Niagara station export (.bog), later",
                            "CPO Studio export, later"], disabled=True)
    st.file_uploader("Export file", disabled=True)
    st.multiselect("Conventions to apply", ["Contractor: …", "Customer: …", "Site: new"], disabled=True,
                   help="Shared tribal knowledge layered on top of the knowledge model.")
    st.button("Create and map", type="primary", disabled=True)

st.subheader("Today")
st.write("Add a Haystack example site from the command line (raw export saved as data/raw/haystack/<site>.json), "
         "then it appears under Projects:")
st.code(".venv/bin/python scripts/build_golden.py <site>\n.venv/bin/python scripts/build_blind.py <site>\n"
        ".venv/bin/python scripts/run_mapper.py <site> names_paths", language="bash")
st.caption("The raw export goes in data/raw/ untouched. Sources are only ever read, never written back.")
