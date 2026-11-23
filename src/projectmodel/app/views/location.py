"""Location: find the building on the map (workflow step 0). A person types a name or address, picks the right
result and confirms it; the site keeps the full address, its parts and the coordinates.

With a Google Maps Platform key (.streamlit/secrets.toml) the search uses Google's Geocoding API and the map is
Google's, with a 3D view. Without one, the search uses OpenStreetMap and the map is OpenStreetMap's.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import active_project, box, get_store, secret, site_map  # noqa: E402
from projectmodel.locate import LocateError, get_geocoder, get_location, save_location  # noqa: E402
from projectmodel.projects import list_projects, site_of  # noqa: E402


store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)
site_id, site = project.split("/")[0], site_of(project)
server_key = secret("google_maps_api_key")
geocoder = get_geocoder(server_key)
provider = "Google Maps" if server_key else "OpenStreetMap"
saved = get_location(store, site_id)

left, right = st.columns([2, 3], gap="medium")
with left, box("loc_info", "Where it is", "location_on", fit=True):
    if saved:
        st.subheader(saved["address"])
        st.caption(f"{saved['lat']:.6f}, {saved['lng']:.6f} · confirmed by {saved['confirmed_by']} on "
                   f"{saved['confirmed_at'][:10]} · from {saved['provider']}")
        parts = saved["components"]
        rows = [("Street", " ".join(x for x in (parts.get("street_number"), parts.get("street")) if x)),
                ("City", parts.get("city")), ("County", parts.get("county")), ("Region", parts.get("region")),
                ("Postcode", parts.get("postcode")), ("Country", parts.get("country")),
                ("Latitude", f"{saved['lat']:.6f}"), ("Longitude", f"{saved['lng']:.6f}"),
                ("Found as", saved["kind"]), ("Place id", saved["place_id"]), ("Searched for", saved["query"])]
        st.dataframe(pd.DataFrame([(k, v) for k, v in rows if v], columns=["Field", "Value"]), hide_index=True,
                     width="stretch")
    else:
        st.info(f"{site.name} is not located yet. Search for it below.", icon=":material/location_off:")

    with st.form("locate"):
        st.markdown("**Find the building**" if not saved else "**Change the location**")
        query = st.text_input("Building name or address", value=site.location, key="loc_query")
        who = st.text_input("Your name", key="loc_who", help="Recorded with the location you confirm.")
        search = st.form_submit_button("Search", icon=":material/search:")
    st.caption(f"The text you search for is sent to {provider}. Nothing else leaves the app."
               + ("" if server_key else " Add a Google Maps Platform key to .streamlit/secrets.toml to use Google "
                                        "and get the 3D view."))
    if search and query.strip():
        try:
            st.session_state["loc_results"] = geocoder.search(query.strip())
        except LocateError as e:
            st.session_state["loc_results"] = []
            st.error(str(e))
    results = st.session_state.get("loc_results")
    if results == []:
        st.warning("Nothing found. Try the street address with the city.")
    elif results:
        i = st.radio("Results", range(len(results)), key="loc_pick",
                     format_func=lambda i: f"{results[i].address}  ({results[i].lat:.5f}, {results[i].lng:.5f})")
        if st.button("Use this location", type="primary", disabled=not who.strip(),
                     help=None if who.strip() else "Enter your name first."):
            save_location(store, site_id, results[i], who.strip())
            del st.session_state["loc_results"]
            st.rerun()

with right, box("loc_map", "Map", "map", fit=True):
    picked = st.session_state.get("loc_results") or []
    shown = picked[st.session_state.get("loc_pick", 0)] if picked else None
    lat, lng = (shown.lat, shown.lng) if shown else (saved["lat"], saved["lng"]) if saved else (None, None)
    if lat is None:
        st.caption("The map appears once the building is found.")
    else:
        site_map(lat, lng, site.name, 620)
    if shown:
        st.caption("Preview of the selected result. It is saved only when you press Use this location.")
