// Model for the twin: the project's equipment, points and relations (the knowledge graph), its levels and rooms
// (from the graph when the documents gave them, else inferred), the layout (generated) and values and alarms
// (simulated). Plan coordinates are metres from the building's north-west corner.

export const D = window.TWIN;  // set by the page (twin_view.py)
export const REAL = !!D.rooms;  // levels and rooms come from the graph (a building added from its documents)
export const FH = 4.2, BH = 4.8;                        // floor-to-floor, basement height
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
// Footprint: Alpha's generated block, or for a real building the plans' proportions at a size that gives its
// busiest floor about 50 m² a room (rooms are laid out on a grid, not traced from the drawings).
function footprint() {
  if (!REAL) return [72, 40];
  const per = Object.values(D.rooms).map(r => r.length), n = Math.max(12, ...per, 0);
  const aspect = clamp(D.aspect || .6, .4, .85), area = n * 50 + 260;
  const w = clamp(Math.sqrt(area / aspect), 50, 120);
  return [Math.round(w), Math.round(clamp(w * aspect, 30, 64))];
}
export const [W, DEP] = footprint();
export const CORE = { x0: W - 10.5, x1: W - 1, z0: DEP / 2 - 7, z1: DEP / 2 + 7 };
export const SHAFT = { x: W - 3.2, z: DEP / 2 - 5.2 };   // riser shaft inside the core

// Levels, top to bottom (as the floor list reads); index 0 is the lowest.
export const FLOORS = D.levels.slice().reverse().map(l => ({ ...l, long: l.long || l.name }));
export const FLOOR_IDX = Object.fromEntries(D.levels.map((l, i) => [l.id, i]));
export const floorById = id => FLOORS.find(f => f.id === id);
export const isBasement = id => /^B\d*$/.test(id) || floorById(id)?.kind === "plant";
const GROUND = D.levels.findIndex(l => !isBasement(l.id));
export const GROUND_ID = D.levels[GROUND].id, TOP_ID = D.levels[D.levels.length - 1].id, BOTTOM_ID = D.levels[0].id;
export const heightOf = id => isBasement(id) ? BH : floorById(id).kind === "roof" ? 0 : FH;
export const elevation = id => { const i = FLOOR_IDX[id];                   // slab top, real building
  return i < GROUND ? -(GROUND - i) * BH : (i - GROUND) * FH; };

export const equip = D.equip;
export const byId = new Map(equip.map(e => [e.id, e]));
export const up = new Map(), down = new Map(), parts = new Map();
const push = (m, k, v) => (m.get(k) || m.set(k, []).get(k)).push(v);
for (const r of D.rels) if (r.r === "feeds") { push(up, r.d, { id: r.s, via: r.via }); push(down, r.s, { id: r.d, via: r.via }); }
for (const e of equip) if (e.parent) push(parts, e.parent, e.id);
export const isZone = e => e.type.startsWith("VAV") || e.type === "Fan coil";   // terminals: they make a zone
for (const e of equip) e.label = e.label || (isZone(e) ? "Zone " + e.name.split(" ")[1] : e.name);
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
  Meter: [.7, .5, 1.1], "Unit heater": [.9, .7, .8], "Mini-split": [1.1, .32, .4], "Hydronic specialty": [1.0, 1.0, 1.7],
  "Fan coil": [1.3, .7, .4] };
const GROUP = { Chiller: "Chiller room", Boiler: "Boiler room", Pump: "Pump room", "Heat exchanger": "Heat exchanger room",
  Meter: "Utility meters", System: "Plant controls", AHU: "Air handling", "Fan VFD": "Air handling",
  "Exhaust fan": "Exhaust fans", "Cooling tower": "Cooling towers", "Hydronic specialty": "Pump room" };

function plantFloor(fid, list, outdoor) {
  const groups = new Map();
  for (const e of list) push(groups, GROUP[e.type] || "Plant", e);
  const order = outdoor ? ["Air handling", "Plant controls", "Exhaust fans", "Cooling towers"]
    : ["Chiller room", "Boiler room", "Pump room", "Heat exchanger room", "Plant controls", "Utility meters"];
  const gs = [...order.filter(g => groups.has(g)), ...[...groups.keys()].filter(g => !order.includes(g))].map(g => [g, groups.get(g)]);
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

// ---------- a real building's floors: its own rooms, each unit in its room ----------
// Where a unit goes in its room: terminals and heaters hang in the ceiling, mini-splits on a wall, plant stands on
// the floor (on a housekeeping pad); everything on the roof stands on the roof.
export const MOUNT = { VAV: "ceiling", "VAV (dual duct)": "ceiling", "VAV (fan powered)": "ceiling", "Fan coil": "ceiling",
  "Unit heater": "ceiling", "Exhaust fan": "ceiling", "Mini-split": "wall" };
export const mountOf = e => floorById(e.floor).kind === "roof" ? "roof" : MOUNT[e.type] || "floor";
const USE = [[/mech|boiler|pump|chiller|plant|fan room|elec|electrical|machine|demarc|riser|it room|data room|server|telecom|gas stor/i, "plant"],
  [/stair|elev|corr|hall|vestib|air-?lock|shaft|lobby|entry/i, "circulation"],
  [/rest ?room|toilet|janitor|jan\.|shower|locker|men|women|storage|closet|stor\b|file/i, "service"],
  [/open|work area|lab|library|break|lounge|conference|training|meeting|classroom/i, "open"]];
const useOf = (name, items) => items.some(e => mountOf(e) === "floor") ? "plant" : (USE.find(([re]) => re.test(name || ""))?.[1] || "office");
const WEIGHT = { plant: 1.5, circulation: .7, service: .7, open: 1.6, office: 1 };

function realFloor(fid, spaces, list) {
  const rs = spaces.map(s => ({ ...s, items: [] })), byRoom = new Map(rs.map(r => [r.id, r]));
  let made = null;
  for (const e of list) {
    const r = byRoom.get(e.room);
    if (r) { r.items.push(e); continue; }
    if (isZone(e)) { const z = { id: "zone:" + e.id, num: "", name: "", label: "Zone " + e.label, xy: null, items: [e], made: true }; rs.push(z); continue; }
    if (!made) rs.push(made = { id: fid + ":plant", num: "", name: "Mechanical", label: "Mechanical room", xy: [0, 0], items: [], made: true });
    made.items.push(e);  // a unit on this floor with no room: the floor's mechanical room
  }
  if (!rs.length) rs.push({ id: fid + ":open", num: "", name: "Open plan", label: "Open plan", xy: [.5, .5], items: [] });
  for (const r of rs) {
    r.use = useOf(r.name, r.items);
    const plantArea = r.items.filter(e => mountOf(e) === "floor").reduce((a, e) => a + (SIZE[e.type][0] + 1.6) * (SIZE[e.type][1] + 1.8), 0);
    r.weight = WEIGHT[r.use] + plantArea / 22;
  }
  // Bands of two rows of rooms either side of a corridor, as many bands as keep rooms near square (Alpha's rule).
  const X0 = 1, X1 = CORE.x0 - 1.4, Z0 = 1, Z1 = DEP - 1, RW = X1 - X0, RD = Z1 - Z0, corr = 2.4, n = rs.length;
  let best;
  for (let k = 1; k <= 5; k++) {
    const cols = Math.ceil(n / (2 * k)), w = RW / cols, d = (RD - k * corr) / (2 * k), score = Math.abs(w / d - .9) + (d < 3.6 ? 9 : 0);
    if (!best || score < best.score) best = { k, cols, w, d, score };
  }
  // Rooms keep the plan's arrangement: north to south by where their number sits, then west to east in each row.
  const at = r => r.xy || [1, 1];
  rs.sort((a, b) => at(a)[1] - at(b)[1] || at(a)[0] - at(b)[0]);
  const rowsN = 2 * best.k, total = rs.reduce((a, r) => a + r.weight, 0), rows = Array.from({ length: rowsN }, () => []);
  let acc = 0;
  for (const r of rs) { const i = Math.min(rowsN - 1, Math.floor((acc + r.weight / 2) / total * rowsN)); rows[i].push(r); acc += r.weight; }
  const out = [], cs = [];
  rows.forEach((row, ri) => {
    const band = Math.floor(ri / 2), side = ri % 2, bz = Z0 + band * (2 * best.d + corr), z = bz + (side ? best.d + corr : 0);
    if (!side) cs.push({ x0: X0, x1: CORE.x0, z: bz + best.d + corr / 2 });
    row.sort((a, b) => at(a)[0] - at(b)[0]);
    const sum = row.reduce((a, r) => a + r.weight, 0);
    let x = X0;
    row.forEach((r, ci) => {
      const w = RW * r.weight / sum;
      const room = { id: fid + ":" + r.id, space: r.id, name: r.label, num: r.num, x, z, w, d: best.d, assets: r.items.map(e => e.id),
        kind: "room", use: r.use, made: !!r.made, file: r.file, ref: r.ref, status: r.status,
        corrSide: side ? "n" : "s", facade: { n: z <= Z0 + .01, s: z + best.d >= Z1 - .01, w: ci === 0 } };
      x += w; out.push(room); fit(fid, room);
    });
  });
  corridors.set(fid, cs);
  return out;
}
// Each unit's spot in its room: terminals spread along the ceiling, wall units on the corridor wall's opposite side,
// floor plant shelf-packed (scaled down if the room is small).
function fit(fid, room) {
  const items = room.assets.map(id => byId.get(id)), by = m => items.filter(e => mountOf(e) === m);
  const zones = items.filter(isZone), hung = by("ceiling").filter(e => !isZone(e)), wall = by("wall"), floor = by("floor");
  const near = room.corrSide === "s" ? room.z + room.d - .8 : room.z + .8, far = room.corrSide === "s" ? room.z + .5 : room.z + room.d - .5;
  zones.forEach((e, i) => pos.set(e.id, { floor: fid, x: room.x + room.w * (i + .5) / zones.length, z: near, w: room.w, d: room.d, room, mount: "ceiling", primary: i === 0 }));
  hung.forEach((e, i) => pos.set(e.id, { floor: fid, x: room.x + room.w * (i + .5) / hung.length, z: room.z + room.d / 2, w: SIZE[e.type][0], d: SIZE[e.type][1], s: .8, room, mount: "ceiling" }));
  wall.forEach((e, i) => pos.set(e.id, { floor: fid, x: room.x + room.w * (i + .5) / wall.length, z: far, w: SIZE[e.type][0], d: SIZE[e.type][1], room, mount: "wall", face: room.corrSide === "s" ? 0 : Math.PI }));
  if (!floor.length) return;
  const pad = .9, w = room.w; let cx = pad, cz = pad, rowH = 0; const placed = [];
  for (const e of floor) {
    const [l, dd] = SIZE[e.type];
    if (cx + l > w - pad + .01 && cx > pad) { cx = pad; cz += rowH + 1.2; rowH = 0; }
    placed.push([e, cx + l / 2, cz + dd / 2]); cx += l + 1.2; rowH = Math.max(rowH, dd);
  }
  const usedD = cz + rowH + pad, usedW = Math.max(...placed.map(([e, px]) => px + SIZE[e.type][0] / 2)) + pad;
  const s = Math.min(1, room.d / usedD, w / usedW), offZ = (room.d - usedD * s) / 2, offX = (w - usedW * s) / 2;
  for (const [e, px, pz] of placed) pos.set(e.id, { floor: fid, x: room.x + offX + px * s, z: room.z + offZ + pz * s, w: SIZE[e.type][0] * s, d: SIZE[e.type][1] * s, s, room, mount: "floor" });
}

for (const f of FLOORS) {
  const list = equip.filter(e => e.floor === f.id);
  rooms.set(f.id, f.kind === "roof" || (!REAL && f.kind === "plant") ? plantFloor(f.id, list, f.kind === "roof")
    : REAL ? realFloor(f.id, D.rooms[f.id] || [], list) : zoneFloor(f.id, list));
}
