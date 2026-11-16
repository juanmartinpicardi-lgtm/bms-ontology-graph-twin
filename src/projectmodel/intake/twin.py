"""The building as it is being built, in 3D: each floor plan page becomes a floor plate, stacked in its level order,
with the rooms read from it and every unit placed where the documents put it. Colour says what kind of unit; the
ring says how sure: solid confirmed, dashed proposed, amber waiting for you.

Pure HTML and CSS 3D, no library: it runs in Streamlit's iframe and turning it does not rerun the app.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from . import pdfdoc

FAMILY_COLOR = {"ahu": "#E8833A", "vav": "#4DA3E8", "fvav": "#8E7CF0", "fcu": "#4DA3E8", "chiller": "#2BB3A3",
                "pump": "#3C8DBC", "ef": "#A0A6AD", "split": "#D96BA6", "uh": "#E0B33A", "specialty": "#8A8F96",
                "boiler": "#D9534F", "other": "#8A8F96"}
FAMILY_NAME = {"ahu": "Air handler", "vav": "VAV box", "fvav": "Fan-powered box", "chiller": "Chiller", "pump": "Pump",
               "ef": "Exhaust fan", "split": "Mini-split", "uh": "Unit heater", "specialty": "Hydronic specialty",
               "fcu": "Fan coil", "boiler": "Boiler", "other": "Other"}


def plate_image(path: Path, page: int, crop: list[float] | None, width: int = 1100) -> str:
    img = pdfdoc.render(path, page, width=width, crop=crop)
    buf = io.BytesIO()
    img.convert("L").save(buf, "JPEG", quality=62)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def payload(b: dict, images: dict[str, str], selected: str | None, needs_you: set[str]) -> dict:
    floors = []
    for f in b["floors"]:
        crop = f["crop"]
        if not crop:
            continue
        w, h = crop[2] - crop[0], crop[3] - crop[1]
        norm = lambda xy: [round((xy[0] - crop[0]) / w, 4), round((xy[1] - crop[1]) / h, 4)]  # noqa: E731
        rooms = [{"n": r["number"], "name": r["name"], "xy": norm(r["anchor"]),
                  "s": "ask" if r["fact"] in needs_you else r["status"], "units": r["units"], "id": r["fact"]}
                 for r in b["rooms"] if r["floor"] == f["id"]]
        anchors = {r["number"]: r["anchor"] for r in b["rooms"]}
        units = []
        for e in b["equip"].values():
            if e["floor"] != f["id"]:
                continue
            xy = e["xy"] or anchors.get(e["room"])
            if not xy:
                continue
            ask = e["fact"] in needs_you or (e.get("room_fact") in needs_you)
            units.append({"tag": e["tag"], "fam": e["family"], "cls": e["class"], "xy": norm(xy),
                          "s": "ask" if ask else e["status"] if e["room_status"] in (None, "confirmed") else "proposed",
                          "room": e["room"], "rs": e.get("room_source"), "rel": e["rel"], "pts": e["points"],
                          "ctrl": (e["controller"] or {}).get("device"), "seq": e["sequence"],
                          "bms": e["bms"], "id": e["fact"], "rid": e.get("room_fact")})
        floors.append({"id": f["id"], "name": f["name"], "sheet": f["sheet"], "img": images.get(f["id"], ""),
                       "aspect": round(h / w, 4), "rooms": rooms, "units": units})
    legend = sorted({u["fam"] for f in floors for u in f["units"]})
    return {"floors": floors, "selected": selected,
            "legend": [{"fam": k, "name": FAMILY_NAME.get(k, k), "color": FAMILY_COLOR.get(k, "#888")} for k in legend],
            "colors": FAMILY_COLOR}


def render(data: dict, height: int = 620) -> str:
    return HTML.replace("__DATA__", json.dumps(data).replace("</", "<\\/")).replace("__H__", str(height))


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><style>
:root{--bg:#0F1114;--fg:#E8E9EA;--mut:#9AA0A6;--line:#2A2E33;--acc:#4DA3E8;--ask:#F0A030;--ok:#3CB371}
html,body{margin:0;height:__H__px;background:var(--bg);color:var(--fg);font:12px/1.35 system-ui,-apple-system,Segoe UI,sans-serif;overflow:hidden}
#stage{position:absolute;inset:0;perspective:2200px;cursor:grab}
#stage.drag{cursor:grabbing}
#world{position:absolute;left:50%;top:56%;transform-style:preserve-3d}
.plate{position:absolute;transform-style:preserve-3d;border:2px solid #4A6A8C;background:#1B232D;box-shadow:0 0 40px #0009;transition:transform .5s ease,opacity .4s}
.plate img{position:absolute;inset:0;width:100%;height:100%;opacity:.7;filter:invert(1) brightness(1.25) contrast(1.05);mix-blend-mode:screen;pointer-events:none}
.plate.dim{opacity:.18}
.plabel{position:absolute;left:-2px;top:-34px;font-weight:700;font-size:22px;color:var(--fg);white-space:nowrap}
.plabel small{color:var(--mut);font-weight:400;margin-left:6px}
.room{position:absolute;transform:translate(-50%,-50%);font-size:9px;color:#9CC7EE;padding:0 3px;border-radius:3px;background:#12324E99;border:1px solid #2D5E8A;white-space:nowrap}
.room.ask{color:#FFD08A;background:#4A330F;border-color:var(--ask)}
.room.proposed{border-style:dashed}
.unit{position:absolute;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;border:2px solid #fff;box-sizing:border-box;cursor:pointer}
.unit.proposed{border-style:dashed;border-color:#ddd}
.unit.ask{border-color:var(--ask);box-shadow:0 0 0 3px #F0A03055}
.unit.sel,.room.sel{animation:pulse 1.1s ease-in-out infinite;z-index:5}
.unit.big{width:22px;height:22px;margin:-11px 0 0 -11px}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 #ffffffaa}50%{box-shadow:0 0 0 10px #ffffff00}}
.pop{animation:pop .5s cubic-bezier(.2,1.6,.4,1) both}
@keyframes pop{from{transform:scale(0);opacity:0}to{transform:scale(1);opacity:1}}
#hud{position:absolute;left:10px;top:10px;display:flex;gap:6px;flex-wrap:wrap;z-index:10}
#hud button{background:#1C2025;color:var(--fg);border:1px solid var(--line);border-radius:999px;padding:4px 11px;font-size:12px;cursor:pointer}
#hud button.on{border-color:var(--acc);background:#1D3550}
#legend{position:absolute;left:10px;bottom:10px;display:flex;gap:10px;flex-wrap:wrap;z-index:10;color:var(--mut);max-width:70%}
#legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:-1px}
#key{position:absolute;right:10px;top:12px;z-index:10;color:var(--mut);text-align:right;font-size:11px}
#tip{position:absolute;z-index:20;pointer-events:none;background:#16191DF2;border:1px solid var(--line);border-radius:8px;padding:8px 10px;max-width:260px;display:none}
#tip b{font-size:13px}#tip .m{color:var(--mut)}
#empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--mut);font-size:14px;text-align:center;padding:30px}
</style></head><body>
<div id="stage"><div id="world"></div></div>
<div id="hud"></div><div id="legend"></div>
<div id="key">● solid: confirmed &nbsp; ◌ dashed: proposed &nbsp; <span style="color:#F0A030">●</span> waiting for you<br>drag to turn · scroll to zoom</div>
<div id="tip"></div>
<script>
const D = __DATA__;
const world = document.getElementById("world"), stage = document.getElementById("stage"), tip = document.getElementById("tip");
let rotZ = -32, rotX = 56, zoom = 1, focus = null;
const W = 620;
if (!D.floors.length) {
  document.body.insertAdjacentHTML("beforeend", '<div id="empty">Upload the floor plans: each level becomes a floor here, with its rooms, and every unit appears where the documents put it.</div>');
}
function esc(s){return String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function build(){
  world.innerHTML = "";
  const n = D.floors.length;
  D.floors.forEach((f, i) => {
    const h = W * f.aspect, gap = Math.max(170, h * 0.55);
    const p = document.createElement("div");
    p.className = "plate" + (focus && focus !== f.id ? " dim" : "");
    p.style.width = W + "px"; p.style.height = h + "px";
    p.style.left = -W / 2 + "px"; p.style.top = -h / 2 + "px";
    const z = focus ? (focus === f.id ? 0 : (i - D.floors.findIndex(x => x.id === focus)) * 900) : (i - (n - 1) / 2) * gap;
    p.style.transform = `translateZ(${z}px)`;
    if (focus && focus !== f.id) p.style.opacity = 0;
    p.innerHTML = (f.img ? `<img src="${f.img}">` : "") + `<div class="plabel">${esc(f.name)}<small>${esc(f.sheet || "")} · ${f.rooms.length} rooms · ${f.units.length} units</small></div>`;
    f.rooms.forEach((r, k) => {
      const el = document.createElement("div");
      el.className = `room ${r.s}` + (D.selected === r.id ? " sel" : "");
      el.style.left = r.xy[0] * 100 + "%"; el.style.top = r.xy[1] * 100 + "%";
      el.textContent = r.n;
      el.onmouseenter = ev => show(ev, `<b>Room ${esc(r.n)}</b> ${esc(r.name)}<div class="m">${r.units.length ? "Units: " + esc(r.units.join(", ")) : "No unit placed here"}</div><div class="m">${label(r.s)}</div>`);
      el.onmouseleave = hide;
      p.appendChild(el);
    });
    f.units.forEach((u, k) => {
      const el = document.createElement("div");
      const sel = D.selected === u.id || D.selected === u.rid;
      el.className = `unit ${u.s} pop` + (sel ? " sel" : "") + (u.fam === "ahu" || u.fam === "chiller" ? " big" : "");
      el.style.background = D.colors[u.fam] || "#888";
      el.style.left = u.xy[0] * 100 + "%"; el.style.top = u.xy[1] * 100 + "%";
      el.style.animationDelay = (k * 12) + "ms";
      el.onmouseenter = ev => show(ev, `<b>${esc(u.tag)}</b> <span class="m">${esc(u.cls)}</span>`
        + `<div>${u.room ? esc(u.rel) + " room " + esc(u.room) + ` <span class="m">(${esc(u.rs)})</span>` : '<span class="m">no room yet</span>'}</div>`
        + (u.ctrl ? `<div>Controller ${esc(u.ctrl)} · ${u.pts} points</div>` : "")
        + (u.bms ? `<div>BMS: ${esc(u.bms)}</div>` : "")
        + (u.seq ? `<div class="m">Sequence: ${esc(u.seq)}</div>` : "")
        + `<div class="m">${label(u.s)}</div>`);
      el.onmouseleave = hide;
      p.appendChild(el);
    });
    world.appendChild(p);
  });
  turn();
}
function label(s){return s === "ask" ? "Waiting for your answer" : s === "confirmed" ? "Confirmed" : "Proposed: waits for a second source";}
function turn(){
  let z = zoom;
  if (focus) { const f = D.floors.find(x => x.id === focus); z = zoom * Math.min((innerWidth - 40) / W, (innerHeight - 110) / (W * f.aspect)) / Math.max(.3, zoom0); }
  world.style.transform = `scale(${z}) rotateX(${focus ? 12 : rotX}deg) rotateZ(${focus ? 0 : rotZ}deg)`;
}
function show(ev, html){ tip.innerHTML = html; tip.style.display = "block"; move(ev); }
function move(ev){ if (tip.style.display !== "block") return; const x = Math.min(ev.clientX + 14, innerWidth - 270); tip.style.left = x + "px"; tip.style.top = (ev.clientY + 14) + "px"; }
function hide(){ tip.style.display = "none"; }
document.addEventListener("mousemove", move);
let drag = null;
stage.onmousedown = e => { drag = [e.clientX, e.clientY, rotZ, rotX]; stage.classList.add("drag"); };
addEventListener("mouseup", () => { drag = null; stage.classList.remove("drag"); });
addEventListener("mousemove", e => { if (!drag || focus) return; rotZ = drag[2] + (e.clientX - drag[0]) * .3; rotX = Math.max(0, Math.min(80, drag[3] - (e.clientY - drag[1]) * .25)); turn(); });
stage.onwheel = e => { e.preventDefault(); zoom = Math.max(.4, Math.min(2.6, zoom * (e.deltaY < 0 ? 1.08 : .93))); turn(); };
const hud = document.getElementById("hud");
function buttons(){
  hud.innerHTML = "";
  const mk = (txt, on, fn) => { const b = document.createElement("button"); b.textContent = txt; if (on) b.className = "on"; b.onclick = fn; hud.appendChild(b); };
  if (!D.floors.length) return;
  mk("All floors", !focus, () => { focus = null; build(); buttons(); });
  D.floors.slice().reverse().forEach(f => mk(f.name, focus === f.id, () => { focus = f.id; build(); buttons(); }));
}
const sel = D.floors.find(f => f.units.some(u => u.id === D.selected || u.rid === D.selected) || f.rooms.some(r => r.id === D.selected));
if (sel) focus = sel.id;
document.getElementById("legend").innerHTML = D.legend.map(l => `<span><i style="background:${l.color}"></i>${esc(l.name)}</span>`).join("");
// Fit the stack: plates are W wide and stand about a plate's height apart once tilted.
const fit = () => { const n = Math.max(1, D.floors.length); zoom = Math.max(.3, Math.min(1.1, innerWidth / 1250, innerHeight / (n * 200 + 420))); };
fit(); const zoom0 = zoom; build(); buttons();
</script></body></html>"""
