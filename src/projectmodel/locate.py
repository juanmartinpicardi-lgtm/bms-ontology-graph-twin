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
from pathlib import Path
from typing import Protocol

import yaml

from .db.store import Store
from .fonts import with_fonts

SEEDS = Path(__file__).resolve().parents[2] / "data/sites"
GOOGLE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELDS = "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.addressComponents"
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


def _post(url: str, body: dict, headers: dict) -> object:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise LocateError(f"{urllib.parse.urlsplit(url).netloc}: HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise LocateError(f"could not reach {urllib.parse.urlsplit(url).netloc}: {e}") from e


def parse_places(data: dict, query: str = "") -> list[Location]:
    """Google Places text search: buildings and places by name ("Troop D headquarters, Springfield") as well as
    by address, with the place's own name in front of its address."""
    out = []
    for r in data.get("places", []):
        by_type = {t: c for c in r.get("addressComponents", []) for t in c.get("types", [])}
        parts = {k: next((by_type[t]["longText"] for t in ts if t in by_type), "") for k, ts in GOOGLE_PARTS.items()}
        if "country" in by_type:
            parts["country_code"] = by_type["country"].get("shortText", "")
        name, address = r.get("displayName", {}).get("text", ""), r.get("formattedAddress", "")
        loc = r.get("location", {})
        if "latitude" not in loc:
            continue
        label = address if not name or address.startswith(name) else f"{name}, {address}"
        out.append(Location(label, float(loc["latitude"]), float(loc["longitude"]), "google", r.get("id", ""),
                            {k: v for k, v in parts.items() if v}, (r.get("types") or [""])[0], query))
    return out


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
        """Places first (it knows buildings by name), then the geocoder (addresses); the same spot only once. A key
        without the Places API (New) gets the geocoder alone."""
        try:
            found = parse_places(_post(PLACES_URL, {"textQuery": query, "maxResultCount": 5},
                                       {"X-Goog-Api-Key": self.key, "X-Goog-FieldMask": PLACES_FIELDS}), query)
        except LocateError:
            found = []
        seen = {(round(x.lat, 4), round(x.lng, 4)) for x in found}
        geo = parse_google(_get(GOOGLE_URL, {"address": query, "key": self.key}), query)
        return found + [g for g in geo if (round(g.lat, 4), round(g.lng, 4)) not in seen]


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
    """The site's confirmed location. A site with none yet takes the one in data/sites/<site>.yaml, if any."""
    store.conn.executescript(SITES_SCHEMA)
    row = store.conn.execute("SELECT * FROM sites WHERE site = ?", (site,)).fetchone()
    seed = SEEDS / f"{site}.yaml"
    if row is None and seed.exists():
        d = yaml.safe_load(seed.read_text())
        save_location(store, site, Location(d["address"], d["lat"], d["lng"], d["provider"], d.get("place_id", ""),
                                            d.get("components", {}), d.get("kind", ""), d.get("query", "")),
                      d["confirmed_by"])
        row = store.conn.execute("SELECT * FROM sites WHERE site = ?", (site,)).fetchone()
    return dict(row) | {"components": json.loads(row["components"])} if row else None


# map -----------------------------------------------------------------------------------------

def osm_embed_url(lat: float, lng: float, span: float = 0.004) -> str:
    box = f"{lng - span},{lat - span / 2},{lng + span},{lat + span / 2}"
    return "https://www.openstreetmap.org/export/embed.html?" + urllib.parse.urlencode(
        {"bbox": box, "layer": "mapnik", "marker": f"{lat},{lng}"})


GOOGLE_MAP = """<!doctype html><html><head><meta charset="utf-8">
<!--__FONTS__--><style>
:root { --bg: #1e1e1e; --panel: rgba(48,48,48,.94); --text: #f0f0f0; --muted: #a0a0a0; --accent: #64c3ff;
  --on: #1e1e1e; --line: #505050; }
:root[data-theme="light"] { --bg: #f0f0f0; --panel: rgba(255,255,255,.95); --text: #303030; --muted: #707070;
  --accent: #1792e5; --on: #ffffff; --line: #d0d0d0; }
html, body { height: 100%; margin: 0; background: var(--bg); font: 500 13px "Roobert", system-ui, sans-serif; color: var(--text); }
/* Two views of the same spot: the satellite map (2D) and Google's photorealistic 3D. Side by side in a wide frame,
   one above the other in a tall one; or one of them alone. */
#views { position: absolute; inset: 0; display: grid; gap: 8px; grid-template: "a" 1fr "b" 1fr / 1fr; }
@media (min-aspect-ratio: 7/5) { #views { grid-template: "a b" 1fr / 1fr 1fr; } }
#views.only2d { grid-template: "a" 1fr / 1fr; } #views.only3d { grid-template: "b" 1fr / 1fr; }
#views.only2d #p3, #views.only3d #p2 { display: none; }
.pane { position: relative; border-radius: 8px; overflow: hidden; background: #111; }
#p2 { grid-area: a; } #p3 { grid-area: b; }
#map2d, #map3d { position: absolute; inset: 0; }
.tag { position: absolute; z-index: 5; left: 10px; bottom: 10px; padding: 4px 9px; border-radius: 6px;
  background: var(--panel); color: var(--text); font-weight: 700; font-size: 12px; pointer-events: none; }
#bar { position: absolute; z-index: 6; top: 10px; left: 10px; display: flex; gap: 2px; padding: 3px;
  border-radius: 9px; background: var(--panel); box-shadow: 0 2px 10px rgba(0,0,0,.25); }
#bar button { border: 0; border-radius: 6px; padding: 6px 12px; background: transparent; color: var(--text);
  cursor: pointer; font: inherit; font-weight: 700; }
#bar button.on { background: var(--accent); color: var(--on); }
#bar .sep { width: 1px; background: var(--line); margin: 4px 3px; }
.msg { position: absolute; z-index: 5; left: 10px; right: 10px; top: 10px;
  padding: 10px 12px; border-radius: 6px; background: var(--panel); color: var(--text); display: none; text-align: center; }
</style></head><body>
<div id="views">
  <div class="pane" id="p2"><div id="map2d"></div><div class="tag">Satellite · 2D</div><div class="msg" id="m2"></div></div>
  <div class="pane" id="p3"><div id="map3d"></div><div class="tag">Photorealistic · 3D</div><div class="msg" id="m3"></div></div>
</div>
<div id="bar"><button data-v="both" class="on">2D + 3D</button><button data-v="only2d">2D</button>
  <button data-v="only3d">3D</button><span class="sep"></span><button id="orbit" class="on" title="Turn slowly around the building">Orbit</button></div>
<script>
const SITE = /*__SITE__*/null;
document.documentElement.dataset.theme = SITE.theme;
const pos = {lat: SITE.lat, lng: SITE.lng};
const $ = id => document.getElementById(id);
const say = (id, t) => { $(id).textContent = t; $(id).style.display = t ? "block" : "none"; };
window.gm_authFailure = () => say("m2", "Google rejected the API key: check that the Maps JavaScript API is enabled and " +
                                        "the key's restrictions allow this page.");
let map3d = null, orbiting = true;
const CAM = {center: {...pos, altitude: 0}, range: 420, tilt: 62, heading: 20};
// The orbit turns the camera's heading around the building, a little every frame; any drag or wheel stops it.
let spin = null;
function orbit(on) {
  orbiting = on;
  $("orbit").className = on ? "on" : "";
  cancelAnimationFrame(spin); spin = null;
  if (!on || !map3d) return;
  const step = () => { map3d.heading = ((map3d.heading || 0) + 0.06) % 360; spin = requestAnimationFrame(step); };
  spin = requestAnimationFrame(step);
}
// The 3D camera looks at a point given in metres above sea level, so it needs the ground's height there: from Google's
// elevation service (the Elevation API on the same key). Without it, the view looks straight down from high up, where
// the ground's height does not matter.
async function groundHeight() {
  try {
    const { ElevationService } = await google.maps.importLibrary("elevation");
    const r = await new ElevationService().getElevationForLocations({locations: [pos]});
    return r.results?.[0]?.elevation ?? null;
  } catch (e) { return null; }
}
async function build3d() {
  try {
    const { Map3DElement, Marker3DElement } = await google.maps.importLibrary("maps3d");
    const ground = await groundHeight();
    if (ground === null) {
      Object.assign(CAM, {center: {...pos, altitude: 0}, range: 1700, tilt: 0});
      say("m3", "Seen from above: enable the Elevation API on this key for the angled view.");
      setTimeout(() => say("m3", ""), 6000);
    } else CAM.center = {...pos, altitude: ground + 8};
    map3d = new Map3DElement({...CAM, mode: "HYBRID"});
    map3d.append(new Marker3DElement({position: pos, label: SITE.label, altitudeMode: "CLAMP_TO_GROUND"}));
    $("map3d").append(map3d);
    if (orbiting) orbit(true);
    for (const ev of ["pointerdown", "wheel"]) $("map3d").addEventListener(ev, () => orbiting && orbit(false), {capture: true, passive: true});
  } catch (e) {
    say("m3", "The 3D view is not available for this key or browser: " + e.message);
  }
}
function view(v) {
  $("views").className = v === "both" ? "" : v;
  document.querySelectorAll("#bar [data-v]").forEach(b => b.className = b.dataset.v === v ? "on" : "");
  dispatchEvent(new Event("resize"));
}
document.querySelectorAll("#bar [data-v]").forEach(b => b.onclick = () => view(b.dataset.v));
$("orbit").onclick = () => orbit(!orbiting);
function init() {
  const map = new google.maps.Map($("map2d"), {center: pos, zoom: 19, mapTypeId: "hybrid", tilt: 0,
    mapTypeControl: false, streetViewControl: true, fullscreenControl: true, rotateControl: false});
  new google.maps.Marker({position: pos, map, title: SITE.label});
  build3d();
}
</script>
<script async src="https://maps.googleapis.com/maps/api/js?key=__KEY__&v=beta&loading=async&callback=init"></script>
</body></html>"""


def google_map_html(lat: float, lng: float, label: str, browser_key: str, theme: str = "dark") -> str:
    """The exact spot twice: Google's satellite map (2D, with labels and Street View) and its photorealistic 3D view,
    turning slowly around the building. The key is visible to the browser, as with any Maps JavaScript page: restrict
    it to this app's address in the console."""
    site = json.dumps({"lat": lat, "lng": lng, "label": label, "theme": theme}).replace("</", "<\\/")
    return with_fonts(GOOGLE_MAP).replace("/*__SITE__*/null", site).replace("__KEY__", urllib.parse.quote(browser_key, safe=""))


def location_dict(loc: Location) -> dict:
    return asdict(loc)
