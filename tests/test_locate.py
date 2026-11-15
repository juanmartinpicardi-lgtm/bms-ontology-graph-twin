"""Locate the building: provider answers become locations with address parts and coordinates, the confirmed one is
stored per site, and the page runs without a key. No test calls a provider: answers are canned."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from projectmodel.db.store import Store
from projectmodel.locate import (GoogleGeocoder, LocateError, NominatimGeocoder, get_geocoder, get_location,
                                 google_map_html, osm_embed_url, parse_google, parse_nominatim, save_location)

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/kg.sqlite"

GOOGLE = {"status": "OK", "results": [{
    "formatted_address": "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA", "place_id": "ChIJ2eUgeAK6j4ARbn5u_wAGqWA",
    "types": ["street_address"], "geometry": {"location": {"lat": 37.4224764, "lng": -122.0842499}},
    "address_components": [
        {"long_name": "1600", "short_name": "1600", "types": ["street_number"]},
        {"long_name": "Amphitheatre Parkway", "short_name": "Amphitheatre Pkwy", "types": ["route"]},
        {"long_name": "Mountain View", "short_name": "Mountain View", "types": ["locality", "political"]},
        {"long_name": "Santa Clara County", "short_name": "Santa Clara County",
         "types": ["administrative_area_level_2", "political"]},
        {"long_name": "California", "short_name": "CA", "types": ["administrative_area_level_1", "political"]},
        {"long_name": "United States", "short_name": "US", "types": ["country", "political"]},
        {"long_name": "94043", "short_name": "94043", "types": ["postal_code"]}]}]}
NOMINATIM = [{"display_name": "Hugo, Lincoln County, Colorado, 80821, United States", "lat": "39.1361", "lon": "-103.4699",
              "osm_type": "relation", "osm_id": 112233, "type": "administrative",
              "address": {"town": "Hugo", "county": "Lincoln County", "state": "Colorado", "postcode": "80821",
                          "country": "United States", "country_code": "us"}}]


def test_google_answer_becomes_a_location():
    (loc,) = parse_google(GOOGLE, "googleplex")
    assert (loc.lat, loc.lng, loc.provider, loc.kind, loc.query) == (37.4224764, -122.0842499, "google",
                                                                     "street_address", "googleplex")
    assert loc.place_id.startswith("ChIJ") and loc.address.startswith("1600 Amphitheatre")
    assert loc.components == {"street_number": "1600", "street": "Amphitheatre Parkway", "city": "Mountain View",
                              "county": "Santa Clara County", "region": "California", "postcode": "94043",
                              "country": "United States", "country_code": "US"}


def test_google_no_result_and_errors():
    assert parse_google({"status": "ZERO_RESULTS", "results": []}) == []
    with pytest.raises(LocateError, match="REQUEST_DENIED.*not authorized"):
        parse_google({"status": "REQUEST_DENIED", "error_message": "This API key is not authorized."})


def test_nominatim_answer_becomes_a_location():
    (loc,) = parse_nominatim(NOMINATIM, "Hugo, CO")
    assert (loc.lat, loc.lng, loc.provider, loc.place_id) == (39.1361, -103.4699, "openstreetmap", "relation/112233")
    assert loc.components == {"city": "Hugo", "county": "Lincoln County", "region": "Colorado", "postcode": "80821",
                              "country": "United States", "country_code": "US"}


def test_provider_follows_the_key():
    assert isinstance(get_geocoder("a-key"), GoogleGeocoder)
    assert isinstance(get_geocoder(""), NominatimGeocoder)


def test_confirmed_location_is_stored_per_site():
    store = Store(":memory:")
    assert get_location(store, "nowhere") is None
    assert get_location(store, "alpha")["address"].startswith("La Pièce 16")  # from data/sites/alpha.yaml
    save_location(store, "alpha", parse_nominatim(NOMINATIM, "Hugo, CO")[0], "ana")
    save_location(store, "alpha", parse_google(GOOGLE, "googleplex")[0], "ben")  # a new confirmation replaces it
    got = get_location(store, "alpha")
    assert (got["provider"], got["confirmed_by"], got["query"], got["lat"]) == ("google", "ben", "googleplex", 37.4224764)
    assert got["components"]["city"] == "Mountain View" and got["confirmed_at"]


def test_maps():
    html = google_map_html(39.1361, -103.4699, 'Alpha </script>', "KEY 1")
    assert '"lat": 39.1361' in html and "key=KEY%201&" in html and "</script>'" not in html
    assert "Alpha <\\/script>" in html
    assert "marker=39.1361%2C-103.4699" in osm_embed_url(39.1361, -103.4699)


@pytest.mark.skipif(not DB.exists(), reason="run scripts/run_mapper.py first")
def test_page_runs_without_a_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    at = AppTest.from_file(str(ROOT / "src/projectmodel/app/views/location.py"), default_timeout=30)
    at.secrets["google_maps_api_key"] = at.secrets["google_maps_browser_key"] = ""  # whatever the local file holds
    at.run()
    assert not at.exception
    assert at.text_input(key="loc_query").value == "Rolle, Switzerland"
    assert any("OpenStreetMap" in c.value for c in at.caption)
