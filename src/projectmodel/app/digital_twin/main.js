// The twin page: filters, floor nav, detail panel, and the wiring between the 3D viewer and the plan.
import { D, REAL, FLOORS, FLOOR_IDX, equip, byId, up, down, parts, sim, isZone, servedBy, chainUp, colorOf, C, pointValue, drift, floorById, IMPACT, mountOf } from "./data.js";
import { createViewer } from "./viewer.js";
import { createPlan } from "./plan.js";

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const ALL = { sys: ["Airside", "Waterside", "Metering"], type: [...new Set(equip.map(e => e.type))] };
const S = { surroundings: true, floor: null, sel: null, color: "status", q: "", f: { sys: new Set(), status: new Set(), type: new Set() },
  mode: "analysis", exploded: false, plan: false, hours: 15.5, cut: null, overlay: false, systems: true, labels: true, hq: true };
const matchesExcept = (e, skip) => {
  if (S.q) { const q = S.q.toLowerCase();
    if (!(e.label + " " + e.name + " " + e.type + " " + e.cls + " " + e.points.map(p => p.n + " " + p.c).join(" ")).toLowerCase().includes(q)) return false; }
  for (const [k, v] of [["sys", e.sys], ["status", sim.get(e.id).status], ["type", e.type]]) if (k !== skip && S.f[k].size && !S.f[k].has(v)) return false;
  return true;
};
const matches = e => matchesExcept(e, null);
const filtersOn = () => !!S.q || Object.values(S.f).some(s => s.size);
const pill = st => `<span class="badge" style="border-color:${C[st]};color:${C[st]}"><i class="dot" style="background:${C[st]}"></i>${st}</span>`;

// ---------- viewer + plan ----------
const tip = $("#tip");
function showTip(id, at) {
  if (!id) { tip.style.display = "none"; return; }
  if (id.startsWith("room:")) { const [, fid, ...name] = id.split(":");
    tip.innerHTML = `<b>${esc(name.join(":"))}</b><span style="color:var(--muted)">${esc(floorById(fid).long)} · no terminal serves this room</span>`; }
  else if (id.startsWith("floor:")) { const f = floorById(id.slice(6)), list = equip.filter(e => e.floor === f.id);
    tip.innerHTML = `<b>${f.id} · ${f.long}</b><span style="color:var(--muted)">${list.length} assets · click to open this floor</span>`; }
  else { const e = byId.get(id), s = sim.get(id);
    tip.innerHTML = `<b>${esc(e.label)}</b><span style="color:var(--muted)">${e.type} · ${e.floor}${e.room_name ? ` · ${esc(e.room_name)}` : ""}${isZone(e) ? ` · ${s.temp.toFixed(1)} °F` : ""}</span>
      ${s.note ? `<div style="color:${C[s.status]};margin-top:3px">${esc(s.note)}</div>` : ""}`; }
  Object.assign(tip.style, { display: "block", left: (at.left + 14) + "px", top: (at.top + 12) + "px" });
}
const handlers = { onSelect: id => select(id), onFloor: f => selectFloor(f), onHover: showTip };
let viewer;
try { viewer = createViewer($("#view3d"), handlers); } catch (err) { $("#loading").textContent = "3D failed to start: " + err.message; throw err; }
$("#loading").remove();
const plan = createPlan($("#plan"), handlers);

// ---------- UI ----------
function renderFilters() {
  const had = document.activeElement?.id === "q", caret = had ? $("#q").selectionStart : 0;
  const count = (k, v) => equip.filter(e => matchesExcept(e, k) && (k === "sys" ? e.sys : k === "status" ? sim.get(e.id).status : e.type) === v).length;
  const chips = (k, vals, dot) => vals.map(v => `<button class="chip ${S.f[k].has(v) ? "on" : ""}" data-k="${k}" data-v="${v}">
    ${dot ? `<i class="dot" style="background:${C[v]}"></i>` : ""}${v}<span class="n">${count(k, v)}</span></button>`).join("");
  $("#filters").innerHTML = `
    <label class="search"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
      <input id="q" placeholder="Search assets, zones, points…" value="${esc(S.q)}"><kbd>/</kbd></label>
    ${chips("sys", ALL.sys, true)}<span class="vsep"></span>${chips("status", ["alarm", "warning", "offline"], true)}<span class="vsep"></span>
    <select id="typeSel" class="chip" style="padding:4px 8px;background:var(--bg)"><option value="">All types</option>${ALL.type.map(t => `<option ${S.f.type.has(t) ? "selected" : ""}>${t}</option>`).join("")}</select>
    ${filtersOn() ? `<button class="link" id="clearF">Clear filters</button>` : ""}
    <span class="spacer"></span><span class="lbl">Colour by</span>
    <div class="seg" id="colorSeg">${[["status", "Status"], ["temp", "Zone temp"], ["system", "System"], ["mapping", "Review"]]
      .map(([k, l]) => `<button data-c="${k}" class="${S.color === k ? "on" : ""}">${l}</button>`).join("")}</div>`;
  const q = $("#q"); q.oninput = () => { S.q = q.value; update(); };
  if (had) { q.focus(); q.setSelectionRange(caret, caret); }
  $("#filters").querySelectorAll(".chip[data-k]").forEach(b => b.onclick = () => { const s = S.f[b.dataset.k]; s.has(b.dataset.v) ? s.delete(b.dataset.v) : s.add(b.dataset.v); update(); });
  $("#typeSel").onchange = ev => { S.f.type = new Set(ev.target.value ? [ev.target.value] : []); update(); };
  $("#colorSeg").querySelectorAll("button").forEach(b => b.onclick = () => { S.color = b.dataset.c; update(); });
  if ($("#clearF")) $("#clearF").onclick = clearFilters;
}
function levelsSummary() {
  const n = k => FLOORS.filter(f => k(f)).length, basements = n(f => /^B\d*$/.test(f.id) || f.kind === "plant");
  const levels = n(f => f.kind === "zones" && !/^B\d*$/.test(f.id)), roof = n(f => f.kind === "roof");
  const rooms = REAL ? Object.values(D.rooms).reduce((a, r) => a + r.length, 0) : 0;
  return [`${levels} floor${levels === 1 ? "" : "s"}`, basements && (basements === 1 ? "basement" : basements + " basements"), roof && "roof"]
    .filter(Boolean).join(" + ") + (rooms ? ` · ${rooms} rooms` : "");
}
// What the page says about where the building comes from: the graph's own floors and rooms, or inferred.
if (REAL) {
  const b = document.querySelector("header .badge.inf");
  b.textContent = "◆ Floors & rooms from the plans · layout generated";
  b.title = "Levels, rooms and the room of every unit come from this project's knowledge graph (read from its floor plans and submittal). Room sizes, walls and geometry are generated; rooms keep the plan's arrangement.";
  document.querySelector("#notes li:nth-child(2)").innerHTML = "<b>From the documents</b>: the levels, every room with its number and name, which floor each unit is on and which room it serves or stands in, as published from the guided setup.";
  document.querySelector("#notes li:nth-child(3)").innerHTML = "<b>Generated</b>: room sizes and walls (rooms keep the plan's north–south, west–east order), furniture, facade, site, equipment models. Units are mounted by kind: boxes and heaters in the ceiling, mini-splits on a wall, plant on pads, air handlers and fans on the roof.";
  document.querySelector("#notes li:nth-child(4)").innerHTML = "<b>Simulated</b>: temperatures, alarms, fan speeds, point values. Units are inferred from each point's class.";
}
function clearFilters() { S.q = ""; Object.values(S.f).forEach(s => s.clear()); update(); }
function renderCrumbs() {
  const sel = S.sel && byId.get(S.sel), fl = sel ? sel.floor : S.floor;
  const c = [`<a data-go="site"><b>${esc(D.site.name)}</b></a>`];
  if (!fl) c.push(`<span>${equip.length} equipment · ${equip.reduce((a, x) => a + x.points.length, 0).toLocaleString()} points</span>`);
  if (fl) c.push(`<span class="sep">›</span><a data-go="floor" data-f="${fl}">${floorById(fl).long}</a>`);
  if (sel) c.push(`<span class="sep">›</span><span style="color:var(--text)">${esc(sel.label)}</span>`);
  $("#crumbs").innerHTML = c.join(" ");
  $("#crumbs").querySelectorAll("[data-go]").forEach(a => a.onclick = () => a.dataset.go === "site" ? (S.sel = null, selectFloor(null)) : selectFloor(a.dataset.f));
}
function renderFloorNav() {
  $("#floorNav").innerHTML = `<div class="lbl" style="margin:2px 2px 4px">Floors</div>` + FLOORS.map(f => {
    const list = equip.filter(e => e.floor === f.id), vis = list.filter(matches);
    const st = k => list.filter(e => sim.get(e.id).status === k).length;
    const zones = list.filter(isZone), avg = zones.length ? zones.reduce((a, e) => a + sim.get(e.id).temp, 0) / zones.length : null;
    const segs = ["alarm", "warning", "offline", "normal"].map(k => `<i style="width:${100 * st(k) / list.length}%;background:${C[k]}"></i>`).join("");
    const al = st("alarm"), wa = st("warning");
    return `<div class="floor ${S.floor === f.id ? "on" : ""}" data-f="${f.id}" style="${filtersOn() && !vis.length ? "opacity:.45" : ""}">
      <div class="fid">${f.id}</div><div class="fname">${f.long}</div>
      <div class="fstats"><span>${filtersOn() ? `<b style="color:var(--text)">${vis.length}</b>/` : ""}${list.length} assets</span>${avg ? `<span>${avg.toFixed(1)} °F</span>` : ""}</div>
      <div class="bar">${segs}</div>
      ${al || wa ? `<span class="pill badge" style="border-color:${al ? C.alarm : C.warning};color:${al ? "#F2948E" : "#F0C27A"}">${al ? al + " alarm" : wa + " warn"}</span>` : ""}</div>`;
  }).join("") + `<button class="btn" id="allFloors" ${S.floor ? "" : "disabled"}>Whole building</button>`;
  $("#floorNav").querySelectorAll(".floor").forEach(el => el.onclick = () => selectFloor(el.dataset.f === S.floor ? null : el.dataset.f));
  $("#allFloors").onclick = () => { S.sel = null; selectFloor(null); };
}
function legendHTML() {
  if (S.color === "impact") return `<span>Impact</span><span><i class="dot" style="background:${C.warning}"></i> shut down</span>`
    + `<span><i class="dot" style="background:${C.alarm}"></i> loses service</span><span><i class="dot" style="background:#5A6068"></i> not affected</span>`;
  if (S.color === "temp") return `<span>Zone temp vs setpoint</span><span>−4°F</span><span class="grad"></span><span>+4°F</span>`;
  const keys = { status: ["normal", "warning", "alarm", "offline"], system: ALL.sys, mapping: ["confirmed", "proposed"] }[S.color];
  const name = { status: "Status (simulated)", system: "System", mapping: "Review status" }[S.color];
  return `<span>${name}</span>` + keys.map(k => `<span><i class="dot" style="background:${C[k]}"></i> ${k}</span>`).join("")
    + `<span class="vsep"></span><span><i class="dot" style="background:#4da3e8"></i> air</span><span><i class="dot" style="background:#5fd0ff"></i> chilled water</span><span><i class="dot" style="background:#ff8a4c"></i> hot water</span>`;
}
function renderDetail() {
  const el = $("#detail"), e = S.sel && byId.get(S.sel);
  if (!e) {
    const f = S.floor && floorById(S.floor), list = equip.filter(x => !f || x.floor === f.id);
    const order = ["alarm", "offline", "warning"], flagged = list.filter(x => sim.get(x.id).status !== "normal").sort((a, b) => order.indexOf(sim.get(a.id).status) - order.indexOf(sim.get(b.id).status));
    const types = {}; list.forEach(x => types[x.type] = (types[x.type] || 0) + 1);
    el.innerHTML = `<div class="dh"><div class="lbl">${f ? "Floor" : "Building"}</div><h2>${f ? f.id + " · " + f.long : esc(D.site.name)}</h2>
      <div class="tags"><span class="badge">${list.length} assets</span><span class="badge">${list.reduce((a, x) => a + x.points.length, 0)} points</span>${f ? "" : `<span class="badge">${levelsSummary()}</span>`}</div></div>
      <div class="sec"><h4>Needs attention <span>${flagged.length}</span></h4><div class="chain">${flagged.slice(0, 14).map(x =>
        `<div class="node" data-id="${x.id}"><i class="dot" style="background:${C[sim.get(x.id).status]}"></i><span>${esc(x.label)}</span><span class="fl">${x.floor}</span></div>
         <div class="via" style="padding:0 0 4px 24px">${esc(sim.get(x.id).note)}</div>`).join("") || `<div style="color:var(--muted)">All normal</div>`}</div></div>
      <div class="sec"><h4>Asset mix</h4><div class="chain">${Object.entries(types).sort((a, b) => b[1] - a[1]).map(([t, n]) =>
        `<div class="node" data-type="${esc(t)}"><span>${esc(t)}</span><span class="fl">${n}</span></div>`).join("")}</div></div>
      <div class="sec" style="color:var(--muted);border:0">Click ${f ? "a zone or piece of equipment" : "the building or a floor"} to go in. Lines show what feeds the selection: air, chilled water, hot water.</div>`;
  } else {
    const s = sim.get(e.id), chain = chainUp(e.id), dn = down.get(e.id) || [], kids = parts.get(e.id) || [], parent = e.parent && byId.get(e.parent);
    const kpis = isZone(e) ? [["Zone temp", s.temp.toFixed(1), "°F"], ["Setpoint", s.sp, "°F"], ["Airflow", s.flow, "cfm"], ["Damper", s.damper, "%"]]
      : [["Load", s.load, "%"], ["Speed", Math.round((s.speed || 0) * 100), "%"], ["Serves", dn.length, "assets"], ["Points", e.points.length, ""]];
    const node = (id, extra = "") => { const x = byId.get(id); return `<div class="node" data-id="${id}"><i class="dot" style="background:${C[sim.get(id).status]}"></i>
      <span>${esc(x.label)}</span><span class="fl">${x.type} · ${x.floor}</span></div>${extra}`; };
    el.innerHTML = `<div class="dh"><div class="crumbs"><a data-go="floor" data-f="${e.floor}">${e.floor}</a><span class="sep">›</span><span>${esc(e.type)}</span></div>
        <h2>${esc(e.label)} ${pill(s.status)}</h2>
        <div class="tags"><span class="badge">brick:${esc(e.cls)}</span><span class="badge"><i class="dot" style="background:${C[e.sys]}"></i>${e.sys}</span>${isZone(e) ? `<span class="badge">${esc(e.name)}</span>` : ""}</div>
        ${s.note ? `<div class="flag ${s.status}">${esc(s.note)}</div>` : ""}</div>
      <div class="sec"><h4>Live <span class="badge sim">simulated</span></h4><div class="kpis">${kpis.map(([k, v, u]) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v} <small>${u}</small></div></div>`).join("")}</div></div>
      <div class="sec"><h4>Served by <span>${chain.length}</span></h4><div class="chain">${chain.length ? chain.map(c =>
        node(c.id, `<div class="via" style="padding:0 0 3px ${22 + c.depth * 12}px">↳ feeds ${esc(byId.get(c.from).label)} via ${c.via}</div>`)).join("") : `<div style="color:var(--muted)">Nothing upstream in the graph</div>`}</div></div>
      ${dn.length ? `<div class="sec"><h4>Serves <span>${dn.length}</span></h4><div class="chain">${dn.slice(0, 8).map(d => node(d.id)).join("")}${dn.length > 8 ? `<div class="via">+ ${dn.length - 8} more</div>` : ""}</div></div>` : ""}
      ${parent || kids.length ? `<div class="sec"><h4>Composition</h4><div class="chain">${parent ? `<div class="lbl" style="margin:2px 0">Part of</div>` + node(parent.id) : ""}
        ${kids.length ? `<div class="lbl" style="margin:6px 0 2px">Has parts (${kids.length})</div>` + kids.slice(0, 6).map(k => node(k)).join("") : ""}</div></div>` : ""}
      <div class="sec"><h4>Points <span>${e.points.length}</span></h4><input class="mini-input" placeholder="Filter points…" id="ptq"><table class="pts" id="ptsTable"></table></div>
      <div class="sec"><h4>Provenance</h4><div class="prov">
        <div>Source</div><div>${esc(e.file)} · ${esc(e.row)}</div><div>Equipment id</div><div>${esc(e.id)}</div>
        <div>Class method</div><div>${e.method} · confidence ${e.conf}</div><div>Review</div><div>${pill(e.status)}</div>
        ${e.floor_src === "plans" ? `<div>Floor</div><div><span class="badge">from the plans</span> ${esc(floorById(e.floor).name)}${floorById(e.floor).sheet ? ` · ${esc(floorById(e.floor).sheet)}` : ""}</div>`
          : `<div>Floor</div><div><span class="badge inf">inferred</span> ${isZone(e) && servedBy(e) ? `served by ${esc(servedBy(e))} → ${e.floor}` : `from type → ${e.floor}`}</div>`}
        ${e.room_name ? `<div>Room</div><div><span class="badge">from the documents</span> ${e.room_rel === "serves" ? "serves" : "in"} ${esc(e.room_name)}</div>` : ""}
        <div>Geometry</div><div><span class="badge inf">generated</span> ${isZone(e) ? (e.room_name ? "room layout, " : "room, ") + "box in the ceiling" : e.type.toLowerCase() + " model, " + ({ ceiling: "hung from the ceiling", wall: "on the wall", floor: "on a pad on the floor", roof: "on the roof" })[mountOf(e)]}</div></div></div>
      <div class="sec"><div class="actions">${D.links?.[e.id] ? `<a class="btn" href="${esc(D.links[e.id])}" target="_top" style="text-decoration:none">Open in Equipments ↗</a>` : ""}<button class="btn" id="clearSel">Close</button></div></div>`;
    const drawPts = q => { $("#ptsTable", el).innerHTML = e.points.filter(p => !q || (p.n + " " + p.c).toLowerCase().includes(q)).map(p =>
      `<tr><td>${esc(p.n)}<div class="cls">${esc(p.c || "unmapped")} · ${p.m} ${p.conf}${p.s !== "proposed" ? ` · <span style="color:${C[p.s] || "#999"}">${p.s}</span>` : ""}</div></td><td class="v">${pointValue(e, p)}</td></tr>`).join(""); };
    drawPts(""); $("#ptq", el).oninput = ev => drawPts(ev.target.value.toLowerCase());
    $("#clearSel", el).onclick = () => select(null);
  }
  el.querySelectorAll(".node[data-id]").forEach(n => n.onclick = () => select(n.dataset.id));
  el.querySelectorAll(".node[data-type]").forEach(n => n.onclick = () => { S.f.type = new Set([n.dataset.type]); update(); });
  el.querySelectorAll("[data-go=floor]").forEach(a => a.onclick = () => selectFloor(a.dataset.f));
}
function renderToolbar() {
  $("#modeSeg").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.m === S.mode));
  $("#explodeSeg").style.display = S.mode === "analysis" ? "" : "none";
  $("#explodeSeg").querySelectorAll("button").forEach(b => b.classList.toggle("on", +b.dataset.x === +S.exploded));
  $("#overlayBtn").style.display = S.mode === "realistic" ? "" : "none";
  $("#surrBtn").style.display = S.mode === "realistic" ? "" : "none";
  for (const [id, on] of [["overlayBtn", S.overlay], ["systemsBtn", S.systems], ["labelsBtn", S.labels], ["cutBtn", S.cut != null], ["planBtn", S.plan], ["hqBtn", S.hq], ["surrBtn", S.surroundings]]) $("#" + id).classList.toggle("on", on);
  $("#cutBox").classList.toggle("on", S.cut != null);
  $("#timeBox").classList.toggle("on", S.mode === "realistic");
  $("#dock").classList.toggle("on", S.plan);
  $("#legend").innerHTML = legendHTML();
}
// Tells the app what is selected (the agent's context), once per change; only inside the app's bridge frame.
let sentContext = "";
function emitContext() {
  if (parent === window) return;
  const key = (S.floor || "") + "|" + (S.sel || "");
  if (key === sentContext) return;
  sentContext = key;
  const f = S.floor && floorById(S.floor), e = S.sel && byId.get(S.sel);
  parent.postMessage({ pm: "event", value: { name: "context",
    floor: f ? { id: f.id, label: f.name } : null,
    sel: e ? { id: e.id, label: e.label || e.name, type: e.type || "" } : null } }, "*");
}
function update(viewOpts = {}) {
  emitContext();
  renderFilters(); renderCrumbs(); renderFloorNav(); renderDetail(); renderToolbar();
  viewer.set({ color: S.color, match: matches, sel: S.sel, floor: S.floor, ...viewOpts });
  if (S.plan) plan.render({ ...S, match: matches, filtersOn: filtersOn() });
}
function select(id) { S.sel = id; if (id) S.floor = byId.get(id).floor; update(); }
function selectFloor(fid) { S.floor = fid; if (S.sel && byId.get(S.sel).floor !== fid) S.sel = null; plan.fit(); update(); }

$("#modeSeg").querySelectorAll("button").forEach(b => b.onclick = () => { S.mode = b.dataset.m; update({ mode: S.mode }); });
$("#explodeSeg").querySelectorAll("button").forEach(b => b.onclick = () => { S.exploded = b.dataset.x === "1"; update({ exploded: S.exploded }); });
$("#overlayBtn").onclick = () => { S.overlay = !S.overlay; update({ overlay: S.overlay }); };
$("#systemsBtn").onclick = () => { S.systems = !S.systems; update({ systems: S.systems }); };
$("#labelsBtn").onclick = () => { S.labels = !S.labels; update({ labels: S.labels }); };
$("#surrBtn").onclick = () => { S.surroundings = !S.surroundings; update({ surroundings: S.surroundings }); };
$("#hqBtn").onclick = () => { S.hq = !S.hq; update({ hq: S.hq }); };
$("#cutBtn").onclick = () => { S.cut = S.cut == null ? +$("#cutRange").value : null; update({ cut: S.cut }); };
$("#cutRange").oninput = ev => { S.cut = +ev.target.value; viewer.set({ cut: S.cut }); };
$("#planBtn").onclick = () => { S.plan = !S.plan; update(); };
$("#resetCam").onclick = () => viewer.resetCamera();
const fmt = h => `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.round((h % 1) * 60)).padStart(2, "0")}`;
let tTimer = 0;
$("#timeRange").oninput = ev => { S.hours = +ev.target.value; $("#timeLbl").textContent = fmt(S.hours);
  clearTimeout(tTimer); tTimer = setTimeout(() => viewer.set({ hours: S.hours }), 40); };
$("#notesBtn").onclick = () => $("#notes").classList.toggle("on");
document.addEventListener("keydown", ev => {
  if (ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT") { if (ev.key === "Escape") ev.target.blur(); return; }
  if (ev.key === "/") { ev.preventDefault(); $("#q").focus(); }
  if (ev.key === "Escape") S.sel ? select(null) : S.floor ? selectFloor(null) : clearFilters();
  if (ev.key === "[" || ev.key === "]") {
    const top = FLOORS.length - 1, i = S.floor ? FLOOR_IDX[S.floor] : ev.key === "]" ? -1 : top + 1, n = Math.max(0, Math.min(top, i + (ev.key === "]" ? 1 : -1)));
    selectFloor(Object.keys(FLOOR_IDX).find(k => FLOOR_IDX[k] === n));
  }
});
setInterval(() => { drift(); viewer.repaint(); renderFloorNav();
  if (S.sel && isZone(byId.get(S.sel))) { const k = $("#detail .kpi .v"); if (k) k.innerHTML = sim.get(S.sel).temp.toFixed(1) + " <small>°F</small>"; } }, 3000);
update();
// impact(src, ids): colour the twin by what a shutdown of `src` takes out (agent tours); impact(null) clears it.
function impact(src, ids = []) {
  IMPACT.src = src; IMPACT.ids = new Set(ids); S.color = src ? "impact" : "status"; update();
}
window.__twin = { S, viewer, select, selectFloor, update, impact };
