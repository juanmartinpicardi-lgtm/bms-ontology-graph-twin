"""Locate the building (workflow step 0, docs/spec-submittals-workflow.md §4): a name or address typed by a person
becomes candidates with a full address and coordinates; the one the person picks is stored as the site's location.

Two providers behind one interface:
  google         Google Maps Platform Geocoding API. Needs an API key (.streamlit/secrets.toml, never in git).
  openstreetmap  Nominatim, OpenStreetMap's public geocoder. No key; at most one request per second, no bulk use.
The typed address is sent to the chosen provider: the only place where project data leaves the app. Nothing is
written back to any source. The stored location records the provider, the query and who confirmed it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .db.store import Store

GOOGLE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "projectmodel-prototype/0.1"  # Nominatim's policy asks for an identifying agent, not a library default
# Our address parts <- the provider's (first one present wins).
GOOGLE_PARTS = {"street_number": ["street_number"], "street": ["route"], "city": ["locality", "postal_town"],
                "county": ["administrative_area_level_2"], "region": ["administrative_area_level_1"],
                "postcode": ["postal_code"], "country": ["country"]}
OSM_PARTS = {"street_number": ["house_number"], "street": ["road"], "city": ["city", "town", "village", "hamlet"],
             "county": ["county"], "region": ["state"], "postcode": ["postcode"], "country": ["country"]}


class LocateError(RuntimeError):
    pass


@dataclass
class Location:
    address: str
    lat: float
    lng: float
    provider: str
    place_id: str = ""
    components: dict = field(default_factory=dict)  # street_number, street, city, county, region, postcode, country
    kind: str = ""  # what the provider says it found: "premise", "street_address", "locality"...
    query: str = ""


class Geocoder(Protocol):
    name: str

    def search(self, query: str) -> list[Location]: ...


def _get(url: str, params: dict) -> object:
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise LocateError(f"could not reach {urllib.parse.urlsplit(url).netloc}: {e}") from e


def parse_google(data: dict, query: str = "") -> list[Location]:
    status = data.get("status")
    if status == "ZERO_RESULTS":
        return []
    if status != "OK":
        raise LocateError(f"Google Geocoding API: {status}. {data.get('error_message', '')}".strip())
    out = []
    for r in data.get("results", []):
        by_type = {t: c for c in r.get("address_components", []) for t in c.get("types", [])}
        parts = {k: next((by_type[t]["long_name"] for t in ts if t in by_type), "") for k, ts in GOOGLE_PARTS.items()}
        if "country" in by_type:
            parts["country_code"] = by_type["country"]["short_name"]
        loc = r["geometry"]["location"]
        out.append(Location(r.get("formatted_address", ""), float(loc["lat"]), float(loc["lng"]), "google",
                            r.get("place_id", ""), {k: v for k, v in parts.items() if v},
                            (r.get("types") or [""])[0], query))
    return out


def parse_nominatim(data: list, query: str = "") -> list[Location]:
    out = []
    for r in data:
        a = r.get("address", {})
        parts = {k: next((a[t] for t in ts if a.get(t)), "") for k, ts in OSM_PARTS.items()}
        if a.get("country_code"):
            parts["country_code"] = a["country_code"].upper()
        place = f"{r.get('osm_type', '')}/{r.get('osm_id', '')}".strip("/")
        out.append(Location(r.get("display_name", ""), float(r["lat"]), float(r["lon"]), "openstreetmap", place,
                            {k: v for k, v in parts.items() if v}, r.get("type", ""), query))
    return out


class GoogleGeocoder:
    name = "google"

    def __init__(self, key: str):
        self.key = key

    def search(self, query: str) -> list[Location]:
        return parse_google(_get(GOOGLE_URL, {"address": query, "key": self.key}), query)


class NominatimGeocoder:
    name = "openstreetmap"

    def search(self, query: str) -> list[Location]:
        return parse_nominatim(_get(NOMINATIM_URL, {"q": query, "format": "jsonv2", "addressdetails": 1, "limit": 5}),
                               query)


def get_geocoder(google_key: str | None) -> Geocoder:
    return GoogleGeocoder(google_key) if google_key else NominatimGeocoder()


# storage -------------------------------------------------------------------------------------

# Created here on first use, not with the store's schema: a running app that picks up this module without
# restarting (Streamlit Cloud after a push) still has the store it loaded before, which knows nothing of this table.
SITES_SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    site         TEXT PRIMARY KEY,
    address      TEXT NOT NULL,
    lat          REAL NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lng          REAL NOT NULL CHECK (lng BETWEEN -180 AND 180),
    place_id     TEXT NOT NULL DEFAULT '',
    components   TEXT NOT NULL DEFAULT '{}',
    kind         TEXT NOT NULL DEFAULT '',
    provider     TEXT NOT NULL CHECK (provider IN ('google', 'openstreetmap')),
    query        TEXT NOT NULL DEFAULT '',
    confirmed_by TEXT NOT NULL,
    confirmed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def save_location(store: Store, site: str, loc: Location, confirmed_by: str) -> None:
    """The site's location: one per site, replaced when a person confirms another."""
    with store.conn:
        store.conn.executescript(SITES_SCHEMA)
        store.conn.execute(
            "INSERT OR REPLACE INTO sites (site, address, lat, lng, place_id, components, kind, provider, query,"
            " confirmed_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (site, loc.address, loc.lat, loc.lng, loc.place_id, json.dumps(loc.components), loc.kind, loc.provider,
             loc.query, confirmed_by))


def get_location(store: Store, site: str) -> dict | None:
    store.conn.executescript(SITES_SCHEMA)
    row = store.conn.execute("SELECT * FROM sites WHERE site = ?", (site,)).fetchone()
    return dict(row) | {"components": json.loads(row["components"])} if row else None


# map -----------------------------------------------------------------------------------------

def osm_embed_url(lat: float, lng: float, span: float = 0.004) -> str:
    box = f"{lng - span},{lat - span / 2},{lng + span},{lat + span / 2}"
    return "https://www.openstreetmap.org/export/embed.html?" + urllib.parse.urlencode(
        {"bbox": box, "layer": "mapnik", "marker": f"{lat},{lng}"})


GOOGLE_MAP = """<!doctype html><html><head><meta charset="utf-8"><style>
html, body { height: 100%; margin: 0; font: 14px system-ui, sans-serif; }
#map2d, #map3d { position: absolute; inset: 0; } #map3d { display: none; }
#bar { position: absolute; z-index: 5; top: 10px; left: 10px; display: flex; gap: 6px; }
#bar button { border: 0; border-radius: 6px; padding: 7px 12px; background: #fff; color: #222; cursor: pointer;
  box-shadow: 0 1px 4px rgba(0,0,0,.35); } #bar button.on { background: #1F7FCC; color: #fff; }
#msg { position: absolute; z-index: 5; bottom: 10px; left: 10px; right: 10px; padding: 8px 10px; border-radius: 6px;
  background: #fff; color: #222; display: none; }
</style></head><body>
<div id="bar"><button id="b2" class="on">Map</button><button id="b3">3D</button></div>
<div id="map2d"></div><div id="map3d"></div><div id="msg"></div>
<script>
const SITE = /*__SITE__*/null;
const pos = {lat: SITE.lat, lng: SITE.lng};
const $ = id => document.getElementById(id);
const say = t => { $("msg").textContent = t; $("msg").style.display = t ? "block" : "none"; };
window.gm_authFailure = () => say("Google rejected the API key: check that Maps JavaScript API is enabled and the " +
                                  "key's restrictions allow this page.");
let built3d = false;
async function show3d() {
  if (!built3d) {
    const { Map3DElement, Marker3DElement } = await google.maps.importLibrary("maps3d");
    const map = new Map3DElement({center: {...pos, altitude: 0}, range: 600, tilt: 60, heading: 0, mode: "HYBRID"});
    map.append(new Marker3DElement({position: pos, label: SITE.label}));
    $("map3d").append(map);
    built3d = true;
  }
}
function pick(three) {
  $("map2d").style.display = three ? "none" : "block";
  $("map3d").style.display = three ? "block" : "none";
  $("b2").className = three ? "" : "on";
  $("b3").className = three ? "on" : "";
  say("");
  if (three) show3d().catch(e => say("3D view not available here: " + e.message));
}
function init() {
  const map = new google.maps.Map($("map2d"), {center: pos, zoom: 18, mapTypeId: "hybrid", tilt: 0,
    mapTypeControlOptions: {position: google.maps.ControlPosition.TOP_RIGHT}, fullscreenControl: false});
  new google.maps.Marker({position: pos, map, title: SITE.label});
  $("b2").onclick = () => pick(false);
  $("b3").onclick = () => pick(true);
}
</script>
<script async src="https://maps.googleapis.com/maps/api/js?key=__KEY__&v=beta&loading=async&callback=init"></script>
</body></html>"""


def google_map_html(lat: float, lng: float, label: str, browser_key: str) -> str:
    """A navigable Google map (satellite with labels) and a photorealistic 3D view of the same spot. The key is
    visible to the browser, as with any Maps JavaScript page: restrict it to this app's address in the console."""
    site = json.dumps({"lat": lat, "lng": lng, "label": label}).replace("</", "<\\/")
    return GOOGLE_MAP.replace("/*__SITE__*/null", site).replace("__KEY__", urllib.parse.quote(browser_key, safe=""))


def location_dict(loc: Location) -> dict:
    return asdict(loc)
