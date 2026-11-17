// Model for the twin: the project's equipment, points and relations (the knowledge graph), floors (inferred) and rooms (generated),
// values and alarms (simulated). Plan coordinates are metres from the building's north-west corner.

export const D = window.TWIN;  // set by the page (twin_view.py)
export const W = 72, DEP = 40, FH = 4.2, BH = 4.8;      // footprint, floor-to-floor, basement height
export const CORE = { x0: W - 10.5, x1: W - 1, z0: DEP / 2 - 7, z1: DEP / 2 + 7 };
export const SHAFT = { x: W - 3.2, z: DEP / 2 - 5.2 };   // riser shaft inside the core

export const FLOORS = [
  { id: "RF", name: "Roof", long: "Roof & penthouse", kind: "roof" },
  ...["L4", "L3", "L2", "L1"].map(id => ({ id, name: "Level " + id[1], kind: "zones",
    long: `Level ${id[1]}` + (D.floors[id] ? ` · ${D.floors[id]} zones` : "") })),
  { id: "B1", name: "Basement", long: "Basement plant", kind: "plant" },
];
export const FLOOR_IDX = { B1: 0, L1: 1, L2: 2, L3: 3, L4: 4, RF: 5 };
export const floorById = id => FLOORS.find(f => f.id === id);
export const elevation = id => id === "B1" ? -BH : (FLOOR_IDX[id] - 1) * FH;   // slab top, real building

export const equip = D.equip;
export const byId = new Map(equip.map(e => [e.id, e]));
export const up = new Map(), down = new Map(), parts = new Map();
const push = (m, k, v) => (m.get(k) || m.set(k, []).get(k)).push(v);
for (const r of D.rels) if (r.r === "feeds") { push(up, r.d, { id: r.s, via: r.via }); push(down, r.s, { id: r.d, via: r.via }); }
for (const e of equip) if (e.parent) push(parts, e.parent, e.id);
export const isZone = e => e.type.startsWith("VAV");
for (const e of equip) e.label = isZone(e) ? "Zone " + e.name.split(" ")[1] : e.name;
export function servedBy(e) {
  const a = (up.get(e.id) || []).find(u => byId.get(u.id)?.type === "AHU");
  return a ? byId.get(a.id).name : (e.parent && byId.get(e.parent)?.type === "AHU" ? byId.get(e.parent).name : "");
}
export function chainUp(id, depth = 0, seen = new Set()) {
  if (depth > 4) return [];
  const out = [];
  for (const u of up.get(id) || []) {
    if (seen.has(u.id)) continue; seen.add(u.id);
    out.push({ ...u, depth, from: id }); out.push(...chainUp(u.id, depth + 1, seen));
  }
  return out;
}

// ---------- simulation (deterministic seed, small live drift) ----------
export function rng(seed) { let h = 2166136261; for (const c of String(seed)) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => { h ^= h << 13; h ^= h >>> 17; h ^= h << 5; return ((h >>> 0) % 100000) / 100000; }; }
export const sim = new Map();
for (const e of equip) {
  const r = rng(e.id), s = { status: "normal", note: "" };
  if (isZone(e)) { s.sp = 72; s.temp = 72 + (r() - .5) * 3.2; s.flow = Math.round(250 + r() * 700); s.damper = Math.round(20 + r() * 60);
    if (r() < .06) s.temp = 74.4 + r() * 1.4; }
  else { s.load = Math.round(30 + r() * 55); s.speed = .4 + r() * .6; }
  sim.set(e.id, s);
}
const force = (name, f) => { const e = equip.find(x => x.name === name); if (e) Object.assign(sim.get(e.id), f); };
force("VAV 1-2-81", { temp: 78.4, damper: 100, flow: 1180 });
force("DD 1-5-7", { temp: 67.1 });
force("CH-2", { status: "warning", note: "Chilled water supply 47.8 °F, setpoint 44 °F" });
force("HHWP-3", { status: "offline", note: "No data for 3 h (simulated comms loss)", speed: 0 });
force("EF-3", { status: "alarm", note: "Fan commanded on, status off", speed: 0 });
export function refreshStatus() {
  for (const e of equip) {
    if (!isZone(e)) continue;
    const s = sim.get(e.id), d = Math.abs(s.temp - s.sp);
    s.status = d > 4 ? "alarm" : d > 2.2 ? "warning" : "normal";
    s.note = s.status === "normal" ? "" : `Zone ${s.temp.toFixed(1)} °F vs setpoint ${s.sp} °F` + (s.damper >= 100 ? ", damper 100 % open" : "");
  }
}
refreshStatus();
export function drift() {
  for (const e of equip) if (isZone(e)) { const s = sim.get(e.id); s.temp += (Math.random() - .5) * .12 + (72 + (s.temp > 76 ? 6.4 : 0) - s.temp) * .01; }
  refreshStatus();
}
export function pointValue(e, p) {
  const r = rng(e.id + p.n), s = sim.get(e.id);
  if (p.k === "Bool") return r() > .3 ? "On" : "Off";
  if (/Zone_Air_Temperature_Sensor/.test(p.c) && s.temp) return s.temp.toFixed(1) + " °F";
  if (/Setpoint/.test(p.c) && p.u === "°F") return (70 + Math.round(r() * 4)) + " °F";
  if (p.u === "°F") return (44 + r() * 90).toFixed(1) + " °F";
  if (p.u === "%") return Math.round(r() * 100) + " %";
  if (p.u === "cfm") return Math.round(150 + r() * 1100) + " cfm";
  if (p.u) return (r() * 100).toFixed(1) + " " + p.u;
  return (r() * 100).toFixed(1);
}

// ---------- colours ----------
export const C = { normal: "#3FB27F", warning: "#E3A33B", alarm: "#E5534B", offline: "#7A8087",
  Airside: "#4DA3E8", Waterside: "#2BB5A8", Metering: "#A98BE8",
  confirmed: "#3FB27F", proposed: "#E3A33B", rejected: "#E5534B" };
export function tempColor(t) {
  const stops = [[-4, [58, 123, 213]], [-1.8, [43, 181, 168]], [0, [63, 178, 127]], [1.8, [227, 163, 59]], [4, [229, 83, 75]]];
  const d = Math.max(-4, Math.min(4, t - 72));
  for (let i = 1; i < stops.length; i++) if (d <= stops[i][0]) {
    const [a, ca] = stops[i - 1], [b, cb] = stops[i], k = (d - a) / (b - a);
    return "#" + ca.map((v, j) => Math.round(v + (cb[j] - v) * k).toString(16).padStart(2, "0")).join("");
  }
  return "#E5534B";
}
// Impact view (agent tours): the equipment taken out, and everything that loses service because of it.
export const IMPACT = { src: null, ids: new Set() };
export function colorOf(e, mode) {
  const s = sim.get(e.id);
  if (mode === "impact") return e.id === IMPACT.src ? C.warning : IMPACT.ids.has(e.id) ? C.alarm : "#5A6068";
  if (mode === "temp") return isZone(e) ? tempColor(s.temp) : "#5A6068";
  if (mode === "system") return C[e.sys];
  if (mode === "mapping") return C[e.status];
  return C[s.status];
}

// ---------- generated layout ----------
export const rooms = new Map();   // floor -> [{id, name, x, z, w, d, assets, kind}]
export const pos = new Map();     // asset -> {floor, x, z, w, d, rot}
export const corridors = new Map(); // floor -> [{x0, x1, z}]  corridor centre lines

function zoneFloor(fid, list) {
  list.sort((a, b) => +a.name.split("-").pop() - +b.name.split("-").pop());
  const X0 = 1, X1 = CORE.x0 - 1.4, Z0 = 1, Z1 = DEP - 1, RW = X1 - X0, RD = Z1 - Z0, corr = 2.4, n = list.length;
  let best;
  for (let k = 1; k <= 5; k++) {
    const cols = Math.ceil(n / (2 * k)), w = RW / cols, d = (RD - k * corr) / (2 * k), score = Math.abs(w / d - .9) + (d < 3.2 ? 9 : 0);
    if (!best || score < best.score) best = { k, cols, w, d, score };
  }
  const out = [], cs = []; let i = 0;
  for (let band = 0; band < best.k; band++) {
    const bz = Z0 + band * (2 * best.d + corr);
    cs.push({ x0: X0, x1: CORE.x0, z: bz + best.d + corr / 2 });
    for (let side = 0; side < 2; side++) for (let c = 0; c < best.cols && i < n; c++, i++) {
      const z = bz + (side ? best.d + corr : 0), e = list[i];
      const room = { id: fid + ":" + e.id, name: e.label, x: X0 + c * best.w, z, w: best.w, d: best.d, assets: [e.id], kind: "zone",
        corrSide: side ? "n" : "s", facade: { n: z <= Z0 + .01, s: z + best.d >= Z1 - .01, w: c === 0 } };
      out.push(room); pos.set(e.id, { floor: fid, x: room.x + room.w / 2, z: room.z + room.d / 2, w: room.w, d: room.d, room });
    }
  }
  // spare cells at the end of the last row stay open-plan
  corridors.set(fid, cs);
  return out;
}

export const SIZE = { AHU: [8.6, 3.2, 2.9], "Fan VFD": [.9, .5, 1.7], "Exhaust fan": [1.5, 1.5, 1.4], "Cooling tower": [4.2, 4.2, 4.4],
  System: [2.6, .7, 2.1], Chiller: [5.6, 2.1, 2.5], Boiler: [3.2, 1.7, 2.3], Pump: [1.8, .8, 1.0], "Heat exchanger": [2.4, .9, 2.0],
  Meter: [.7, .5, 1.1] };
const GROUP = { Chiller: "Chiller room", Boiler: "Boiler room", Pump: "Pump room", "Heat exchanger": "Heat exchanger room",
  Meter: "Utility meters", System: "Plant controls", AHU: "Air handling", "Fan VFD": "Air handling",
  "Exhaust fan": "Exhaust fans", "Cooling tower": "Cooling towers" };

function plantFloor(fid, list, outdoor) {
  const groups = new Map();
  for (const e of list) push(groups, GROUP[e.type] || "Plant", e);
  const order = outdoor ? ["Air handling", "Plant controls", "Exhaust fans", "Cooling towers"]
    : ["Chiller room", "Boiler room", "Pump room", "Heat exchanger room", "Plant controls", "Utility meters"];
  const gs = order.filter(g => groups.has(g)).map(g => [g, groups.get(g)]);
  const X0 = 1, X1 = CORE.x0 - 1.4, corr = 3, rowD = (DEP - 2 - corr) / 2;
  const need = gs.map(([, a]) => a.reduce((s, e) => s + (SIZE[e.type][0] + 1.6) * (SIZE[e.type][1] + 1.8), 0));
  const half = need.reduce((a, b) => a + b, 0) / 2;
  let acc = 0; const rowOf = need.map(n => { const r = acc + n / 2 > half ? 1 : 0; acc += n; return r; });
  const out = [], tot = [0, 0];
  need.forEach((n, i) => tot[rowOf[i]] += n);
  const x = [X0, X0];
  gs.forEach(([g, a], i) => {
    const row = rowOf[i], w = (X1 - X0) * need[i] / tot[row], z = 1 + row * (rowD + corr);
    const room = { id: fid + ":" + g, name: g, x: x[row], z, w, d: rowD, assets: a.map(e => e.id), kind: outdoor ? "area" : "plant" };
    x[row] += w; out.push(room);
    // shelf-pack items in rows, scale down if the room is too small
    const pad = 1.2; let cx = pad, cz = pad, rowH = 0; const placed = [];
    for (const e of a) {
      const [l, dd] = SIZE[e.type];
      if (cx + l > w - pad + .01 && cx > pad) { cx = pad; cz += rowH + 1.4; rowH = 0; }
      placed.push([e, cx + l / 2, cz + dd / 2]); cx += l + 1.4; rowH = Math.max(rowH, dd);
    }
    const usedD = cz + rowH + pad, s = Math.min(1, rowD / usedD);
    const offZ = (rowD - usedD * s) / 2;
    for (const [e, px, pz] of placed) pos.set(e.id, { floor: fid, x: room.x + px, z: z + offZ + pz * s, w: SIZE[e.type][0] * s, d: SIZE[e.type][1] * s, s, room });
  });
  corridors.set(fid, [{ x0: X0, x1: CORE.x0, z: 1 + rowD + corr / 2 }]);
  return out;
}
for (const f of FLOORS) {
  const list = equip.filter(e => e.floor === f.id);
  rooms.set(f.id, f.kind === "zones" ? zoneFloor(f.id, list) : plantFloor(f.id, list, f.kind === "roof"));
}
