// The building: one THREE.Group per floor (so floors can stack, explode and peel independently), each holding its
// slab, core, rooms, furniture, equipment, ducts/pipes and facade. Every object is tagged with a layer so the
// viewer can switch between Analysis (schematic, data-coloured) and Realistic (facade, furniture, daylight).
import * as THREE from "three";
import { W, DEP, FH, BH, CORE, SHAFT, FLOORS, equip, byId, rooms, pos, corridors, isZone, rng, REAL, heightOf, isBasement, GROUND_ID } from "./data.js";
import { boxGeo, buildEquipment, vavBox } from "./models.js";
import { matsFor } from "./materials.js";

const px = x => x - W / 2, pz = z => z - DEP / 2;
const UNIT = new THREE.BoxGeometry(1, 1, 1);
UNIT.translate(0, .5, 0); // instanced unit boxes sit on their base

// Collects instances per (geometry, material) and turns them into InstancedMeshes.
class Inst {
  constructor() { this.sets = new Map(); }
  add(key, geo, mat, x, y, z, sx = 1, sy = 1, sz = 1, ry = 0) {
    let s = this.sets.get(key); if (!s) this.sets.set(key, s = { geo, mat, m: [] });
    const o = new THREE.Object3D(); o.position.set(x, y, z); o.scale.set(sx, sy, sz); o.rotation.y = ry; o.updateMatrix();
    s.m.push(o.matrix.clone());
  }
  build(shadow = true) {
    const out = {};
    for (const [k, s] of this.sets) {
      const im = new THREE.InstancedMesh(s.geo, s.mat, s.m.length);
      s.m.forEach((m, i) => im.setMatrixAt(i, m)); im.castShadow = shadow; im.receiveShadow = true; out[k] = im;
    }
    return out;
  }
}
function mesh(geo, mat, x, y, z, layer, shadow = true) {
  const o = new THREE.Mesh(geo, mat); o.position.set(x, y, z); o.castShadow = shadow; o.receiveShadow = true;
  o.userData.layer = layer; return o;
}
function pipeRun(group, pts, r, mat, layer) {
  for (let i = 1; i < pts.length; i++) {
    const a = new THREE.Vector3(...pts[i - 1]), b = new THREE.Vector3(...pts[i]), len = a.distanceTo(b);
    const o = mesh(new THREE.CylinderGeometry(r, r, len, 14), mat, 0, 0, 0, layer);
    o.position.copy(a).lerp(b, .5); o.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize()); group.add(o);
    if (i < pts.length - 1) { const j = mesh(new THREE.SphereGeometry(r * 1.05, 14, 10), mat, ...pts[i], layer); group.add(j); }
  }
}

// ---------------------------------------------------------------- per-floor builders
function furnish(I, M, room, y0) {
  const r = rng(room.id), area = room.w * room.d, x0 = px(room.x), z0 = pz(room.z);
  const facadeZ = room.corrSide === "s" ? z0 + .9 : z0 + room.d - .9;            // desks face away from the corridor
  const desk = (x, z, ry) => {
    I.add("deskTop", UNIT, M.desk, x, y0 + .72, z, 1.5, .04, .75, ry);
    I.add("deskLeg", UNIT, M.darkMetal, x, y0, z, 1.4, .72, .05, ry);
    const back = ry ? -1 : 1, cz = z + Math.cos(ry) * .62 * back, cx = x + Math.sin(ry) * .62 * back;
    I.add("chairSeat", UNIT, M.chair, cx, y0 + .44, cz, .5, .07, .5, ry);
    I.add("chairBack", UNIT, M.chair, cx + Math.sin(ry) * .24 * back, y0 + .5, cz + Math.cos(ry) * .24 * back, .48, .52, .06, ry);
    I.add("chairBase", UNIT, M.black, cx, y0, cz, .08, .44, .08, ry);
    I.add("monitor", UNIT, M.monitor, x - Math.cos(ry) * .25, y0 + .82, z - Math.cos(ry) * .2 * back, .56, .34, .03, ry);
  };
  if (area < 22) desk(x0 + room.w / 2, facadeZ + (room.corrSide === "s" ? .5 : -.5), room.corrSide === "s" ? 0 : Math.PI);
  else if (r() < .25) {
    const L = Math.min(room.w, room.d) * .6, cx = x0 + room.w / 2, cz = z0 + room.d / 2;
    I.add("table", UNIT, M.deskWood, cx, y0 + .72, cz, L * 1.4, .05, L * .55);
    I.add("tableBase", UNIT, M.darkMetal, cx, y0, cz, L * 1.1, .72, .12);
    const n = Math.max(2, Math.floor(L * 1.4 / .8));
    for (let i = 0; i < n; i++) for (const s of [-1, 1]) {
      const x = cx - L * .7 + (i + .5) * L * 1.4 / n, z = cz + s * (L * .275 + .35);
      I.add("chairSeat", UNIT, M.chair, x, y0 + .44, z, .48, .07, .48);
      I.add("chairBack", UNIT, M.chair, x, y0 + .5, z + s * .23, .46, .5, .06);
      I.add("chairBase", UNIT, M.black, x, y0, z, .08, .44, .08);
    }
    I.add("screen", UNIT, M.screen, cx, y0 + 1.1, z0 + (room.corrSide === "s" ? .12 : room.d - .12), Math.min(2.2, room.w * .5), 1.2, .05);
  } else {
    const cols = Math.max(1, Math.floor((room.w - 1.4) / 1.7)), rowsN = Math.max(1, Math.floor((room.d - 1.6) / 3.0));
    for (let c = 0; c < cols; c++) for (let rr = 0; rr < rowsN; rr++) {
      const x = x0 + .7 + (c + .5) * (room.w - 1.4) / cols, z = z0 + .8 + (rr + .5) * (room.d - 1.6) / rowsN;
      desk(x, z - .4, Math.PI); desk(x, z + .4, 0);
    }
  }
  const pcx = x0 + room.w - .5, pcz = room.corrSide === "s" ? z0 + .5 : z0 + room.d - .5;
  I.add("pot", UNIT, M.pot, pcx, y0, pcz, .38, .42, .38);
  I.add("leaf", new THREE.IcosahedronGeometry(.42, 1), M.plant, pcx, y0 + .85, pcz, 1, 1.25, 1);
  for (let x = x0 + 1.2; x < x0 + room.w - .6; x += 2.4) for (let z = z0 + 1.2; z < z0 + room.d - .6; z += 2.4)
    I.add("light", UNIT, M.light, x, y0 + 2.86, z, 1.2, .03, .6);
}
function walls(I, M, room, h, plant, lastCol, block = false) {
  const x0 = px(room.x), z0 = pz(room.z), t = .1;
  const solid = plant || block ? "block" : "wall", glass = plant ? "block" : block ? "blockDoor" : "glass";
  const wallZ = (z, kind) => {
    if (kind === "glass" || plant) { const door = x0 + room.w * .72;
      I.add(kind === "glass" ? "glass" : "block", UNIT, kind === "glass" ? M.glassPartition : M.partition, (x0 + door - .55) / 2, 0, z, door - .55 - x0, h, t);
      I.add(kind === "glass" ? "glass" : "block", UNIT, kind === "glass" ? M.glassPartition : M.partition, (door + .55 + x0 + room.w) / 2, 0, z, x0 + room.w - door - .55, h, t);
      I.add("frame", UNIT, M.darkMetal, door, h - .15, z, 1.2, .15, t * 1.4);
      I.add("doorLeaf", UNIT, plant || block ? M.steel : M.deskWood, door - .5 + .45 * .5, 0, z + .45 * .5, .05, h - .2, .9 * .5 + .02, -1.0);
    } else if (kind === "blockDoor") { // a plant room's corridor wall: block with a steel door
      const door = x0 + room.w * .72;
      I.add("block", UNIT, M.partition, (x0 + door - .55) / 2, 0, z, door - .55 - x0, h, t);
      I.add("block", UNIT, M.partition, (door + .55 + x0 + room.w) / 2, 0, z, x0 + room.w - door - .55, h, t);
      I.add("doorLeaf", UNIT, M.steel, door, 0, z, 1.1, h - .2, .06);
    } else I.add(kind, UNIT, M.partition, x0 + room.w / 2, 0, z, room.w, h, t);
  };
  const corrS = plant ? room.z < DEP / 2 : room.corrSide === "s";
  if (!room.facade?.n && !plant) { if (room.corrSide === "n") wallZ(z0, glass); }
  if (plant && !corrS && room.z > 1.1) wallZ(z0, glass);
  if (!room.facade?.s || plant) { if (!(plant && room.z + room.d > DEP - 1.1)) wallZ(z0 + room.d, corrS ? glass : solid); }
  if (!(room.facade?.w || room.x < 1.1)) I.add(solid, UNIT, M.partition, x0, 0, z0 + room.d / 2, t, h, room.d);
  if (lastCol) I.add(solid, UNIT, M.partition, x0 + room.w, 0, z0 + room.d / 2, t, h, room.d);
}

function core(group, M, h, fid) {
  const cw = CORE.x1 - CORE.x0 - 4.2, cx = px(CORE.x0 + cw / 2), cz = pz((CORE.z0 + CORE.z1) / 2), cd = CORE.z1 - CORE.z0;
  const c = mesh(boxGeo(cw, h - .02, cd, 3), M.concrete, cx, (h - .02) / 2, cz, "core"); c.userData.coreOf = fid; group.add(c);
  for (let i = 0; i < 3; i++) group.add(mesh(new THREE.BoxGeometry(.04, 2.3, 1.1), M.steel, px(CORE.x0) - .03, 1.15, cz - 3 + i * 1.6, "core"));
  // shaft walls (open towards the viewer so the risers show)
  group.add(mesh(boxGeo(4.2, h - .02, .2, 3), M.concrete, px(CORE.x1 - 2.1), (h - .02) / 2, pz(CORE.z0) + .1, "core"));
  group.add(mesh(boxGeo(.2, h - .02, cd, 3), M.concrete, px(CORE.x1) - .1, (h - .02) / 2, cz, "core"));
}
function risers(group, M, h, withDuct) {
  const sx = px(SHAFT.x), sz = pz(SHAFT.z);
  for (const [dx, dz, m, r] of [[-1.2, 0, M.pipeCHW, .16], [-.8, 0, M.pipeCHW, .16], [-1.2, .6, M.pipeHW, .12], [-.8, .6, M.pipeHW, .12], [-1.0, 1.2, M.pipeCW, .16]])
    group.add(mesh(new THREE.CylinderGeometry(r, r, h, 14), m, sx + dx, h / 2, sz + dz, "systems"));
  if (withDuct) group.add(mesh(boxGeo(1.4, h, 1.2, 2), M.duct, sx + .6, h / 2, sz + 2.4, "systems"));
}

// ---------------------------------------------------------------- facade
function facade(group, M, I, h, ground) {
  const vision = h - .95, step = 1.5;
  for (const [x, z, len, ry] of [[0, -DEP / 2, W, 0], [0, DEP / 2, W, 0], [-W / 2, 0, DEP, Math.PI / 2], [W / 2, 0, DEP, Math.PI / 2]]) {
    const g = mesh(new THREE.BoxGeometry(len, vision, .03), M.curtain, x, vision / 2, z, "facade", false); g.rotation.y = ry; g.userData.facade = true; group.add(g);
    const s = mesh(new THREE.BoxGeometry(len + .16, .95, .06), M.spandrel, x * (1 + .08 / Math.abs(x || 1) * (x ? 1 : 0)), vision + .475, z + Math.sign(z) * .06, "facade");
    if (ry) { s.rotation.y = ry; s.position.x = x + Math.sign(x) * .06; s.position.z = 0; }
    s.userData.facade = true; group.add(s);
    const n = Math.round(len / step);
    for (let i = 0; i <= n; i++) {
      const t = -len / 2 + i * len / n, fin = i % 4 === 0;
      const mx = ry ? x + Math.sign(x) * (fin ? .32 : .09) : t, mz = ry ? t : z + Math.sign(z) * (fin ? .32 : .09);
      I.add(fin ? "fin" : "mullion", UNIT, fin ? M.darkMetal : M.mullion, mx, 0, mz, ry ? (fin ? .6 : .18) : .07, h, ry ? .07 : (fin ? .6 : .18));
    }
    for (const yy of [0, vision]) I.add("transom", UNIT, M.mullion, ry ? x + Math.sign(x) * .09 : x, yy, ry ? 0 : z + Math.sign(z) * .09, ry ? .16 : len, .07, ry ? len : .16);
  }
  if (ground) { // entrance canopy and revolving door on the south side
    group.add(mesh(boxGeo(12, .35, 4.5, 2), M.darkMetal, -6, 3.6, DEP / 2 + 2.3, "facade"));
    for (const dx of [-11.5, -.5]) group.add(mesh(new THREE.CylinderGeometry(.14, .14, 3.6, 16), M.steel, dx, 1.8, DEP / 2 + 4.2, "facade"));
    const door = mesh(new THREE.CylinderGeometry(1.3, 1.3, 2.6, 32, 1, true), M.glassPartition, -6, 1.3, DEP / 2 + .2, "facade", false); group.add(door);
    group.add(mesh(new THREE.CylinderGeometry(1.35, 1.35, .25, 32), M.darkMetal, -6, 2.72, DEP / 2 + .2, "facade"));
  }
}

// A piece of equipment at (x, y, z) on its floor, with an invisible hitbox for picking.
function addEquip(group, M, fl, out, fid, e, x, y, z, s = 1, opts = {}) {
  const m = buildEquipment(M, e, opts.indoor);
  m.scale.setScalar(s); m.rotation.y = opts.ry || 0; m.position.set(x, 0, z);
  if (opts.hang != null) { const bb0 = new THREE.Box3().setFromObject(m); y = opts.hang - bb0.max.y; } // under the slab above
  m.position.y = y;
  m.traverse(o => { o.userData.layer = o.userData.layer || "equip"; if (o.material && !fl.mats.includes(o.material) && !fl.extraMats.includes(o.material)) fl.extraMats.push(o.material); });
  group.add(m);
  const bb = new THREE.Box3().setFromObject(m), size = bb.getSize(new THREE.Vector3()), ctr = bb.getCenter(new THREE.Vector3());
  const hit = new THREE.Mesh(new THREE.BoxGeometry(size.x + .2, size.y + .2, size.z + .2), new THREE.MeshBasicMaterial({ visible: false }));
  hit.position.copy(ctr); hit.userData = { id: e.id, hitbox: true }; group.add(hit); out.hits.push(hit);
  const tintMats = m.userData.tint.map(t => t.material);
  tintMats.forEach(tm => { tm.userData.orig = tm.color.getHex(); });
  out.equip.set(e.id, { floor: fid, group: m, tint: tintMats, spin: m.userData.spin, hit, top: bb.max.y });
  return m;
}

// ---------------------------------------------------------------- a real building's floor: its own rooms
// Every room from the plans is built: walls, floor finish, furniture by what the room is for. A room a terminal
// serves is that terminal's zone (coloured by data); plant rooms get block walls, epoxy and pads; each unit is
// mounted where its kind goes (data.js MOUNT).
function realRooms(group, M, I, FI, fl, out, f, h) {
  const list = rooms.get(f.id), maxX = Math.max(...list.map(r => r.x + r.w));
  for (const room of list) {
    const items = room.assets.map(id => byId.get(id)), zones = items.filter(isZone), prim = zones[0];
    const plant = room.use === "plant", cx = px(room.x + room.w / 2), cz = pz(room.z + room.d / 2);
    walls(I, M, room, plant ? h - .3 : 2.85, false, room.x + room.w >= maxX - .01, plant);
    if (room.use === "office" || room.use === "open") furnish(FI, M, room, 0);
    else for (let x = px(room.x) + 1.2; x < px(room.x) + room.w - .6; x += 2.4) FI.add("light", UNIT, M.light, x, 2.86, cz, 1.2, .03, .6);
    const zm = (plant ? M.epoxy : M.carpet).clone(); zm.userData.zone = !!prim; fl.extraMats.push(zm);
    const zf = mesh(new THREE.BoxGeometry(room.w - .12, .05, room.d - .12), zm, cx, .035, cz, "zone", false);
    zf.userData = { ...zf.userData, floor: f.id, roomName: room.name, ...(prim ? { id: prim.id } : {}) };
    group.add(zf); out.hits.push(zf);
    let vol = null, vm = null;
    if (prim) {
      vm = M.volume.clone(); fl.extraMats.push(vm);
      vol = mesh(new THREE.BoxGeometry(room.w - .4, 2.6, room.d - .4), vm, cx, 1.36, cz, "analysis", false);
      vol.userData = { ...vol.userData, id: prim.id }; vol.renderOrder = 2; group.add(vol); out.hits.push(vol);
    } else out.plain.push({ floor: f.id, mat: zm, plant });
    for (const e of items) {
      const p = pos.get(e.id);
      if (isZone(e)) { // terminal in the ceiling on the corridor side, with its branch duct to the corridor main
        const cc = corridors.get(f.id).reduce((a, c) => Math.abs(c.z - p.z) < Math.abs(a - p.z) ? c.z : a, 1e9);
        const v = vavBox(M, e.type === "VAV (dual duct)", e.type); v.position.set(px(p.x), h - .62, pz(p.z));
        v.rotation.y = room.corrSide === "s" ? Math.PI / 2 : -Math.PI / 2;
        v.traverse(o => { o.userData.layer = "systems"; if (o.isMesh) o.userData.id = e.id; if (o.material && !fl.mats.includes(o.material)) fl.extraMats.push(o.material); });
        group.add(v); out.hits.push(v.children[0]);
        group.add(mesh(new THREE.BoxGeometry(.35, .3, Math.abs(cc - p.z) || .1), M.duct, px(p.x), h - .55, pz((cc + p.z) / 2), "systems"));
        out.zones.set(e.id, { floor: f.id, floorMat: zm, volMat: vm, floorMesh: zf, vol, vav: v, room, shared: e !== prim });
      } else if (p.mount === "floor") {
        group.add(mesh(boxGeo(p.w + .4, .12, p.d + .4, 2), M.concrete, px(p.x), .06, pz(p.z), "realistic"));
        addEquip(group, M, fl, out, f.id, e, px(p.x), .12, pz(p.z), p.s || 1);
      } else if (p.mount === "wall") addEquip(group, M, fl, out, f.id, e, px(p.x), 2.2, pz(p.z), 1, { ry: p.face });
      else addEquip(group, M, fl, out, f.id, e, px(p.x), 0, pz(p.z), p.s || 1, { hang: h - .3, indoor: true });
    }
  }
  for (const c of corridors.get(f.id)) // supply main along each corridor, from the shaft
    group.add(mesh(boxGeo(SHAFT.x - c.x0 - 1, .5, 1.0, 2), M.duct, px((c.x0 + 1 + SHAFT.x) / 2), h - .55, pz(c.z), "systems"));
  if (isBasement(f.id)) for (const [x, z, w, d] of [[0, -DEP / 2 - .2, W + .8, .4], [0, DEP / 2 + .2, W + .8, .4], [-W / 2 - .2, 0, .4, DEP], [W / 2 + .2, 0, .4, DEP]])
    group.add(mesh(boxGeo(w, h, d, 3), M.concrete, x, h / 2 - .4, z, "realistic"));
}

// ---------------------------------------------------------------- the whole building
export function buildBuilding(base) {
  const out = { floors: new Map(), zones: new Map(), equip: new Map(), hits: [], plain: [] };
  for (const f of FLOORS) {
    const M = matsFor(base), group = new THREE.Group(), I = new Inst(), FI = new Inst();
    const h = heightOf(f.id), fl = { id: f.id, group, mats: Object.values(M), extraMats: [], label: null };
    group.userData.floor = f.id;
    // slab
    const slab = mesh(boxGeo(W, .4, DEP, 4), f.kind === "roof" ? M.roof : M.slab, 0, -.2, 0, "slab");
    slab.userData.floor = f.id; group.add(slab); out.hits.push(slab);
    if (f.kind !== "roof") group.add(mesh(boxGeo(W, .02, DEP, 4), f.kind === "plant" ? M.plantFloor : M.carpet, 0, .01, 0, "realistic"));

    if (f.kind === "zones" && REAL) realRooms(group, M, I, FI, fl, out, f, h);
    if (f.kind === "zones" && !REAL) {
      const list = rooms.get(f.id), maxX = Math.max(...list.map(r => r.x + r.w));
      for (const room of list) {
        const id = room.assets[0], e = byId.get(id);
        const zm = M.carpet.clone(); zm.userData.zone = true; fl.extraMats.push(zm);
        const zf = mesh(new THREE.BoxGeometry(room.w - .12, .05, room.d - .12), zm, px(room.x + room.w / 2), .035, pz(room.z + room.d / 2), "zone", false);
        zf.userData = { ...zf.userData, id }; group.add(zf); out.hits.push(zf);
        const vm = M.volume.clone(); fl.extraMats.push(vm);
        const vol = mesh(new THREE.BoxGeometry(room.w - .4, 2.6, room.d - .4), vm, px(room.x + room.w / 2), 1.36, pz(room.z + room.d / 2), "analysis", false);
        vol.userData = { ...vol.userData, id }; vol.renderOrder = 2; group.add(vol); out.hits.push(vol);
        // VAV box in the ceiling, on the corridor side, with its branch duct
        const vz = room.corrSide === "s" ? room.z + room.d - .7 : room.z + .7, cz = corridors.get(f.id).reduce((a, c) => Math.abs(c.z - vz) < Math.abs(a - vz) ? c.z : a, 1e9);
        const v = vavBox(M, e.type !== "VAV"); v.position.set(px(room.x + room.w / 2), h - .62, pz(vz)); v.rotation.y = room.corrSide === "s" ? Math.PI / 2 : -Math.PI / 2;
        v.traverse(o => { o.userData.layer = "systems"; if (o.material && !fl.mats.includes(o.material)) fl.extraMats.push(o.material); });
        group.add(v);
        group.add(mesh(new THREE.BoxGeometry(.35, .3, Math.abs(cz - vz)), M.duct, px(room.x + room.w / 2), h - .55, pz((cz + vz) / 2), "systems"));
        walls(I, M, room, 2.85, false, room.x + room.w >= maxX - .01);
        furnish(FI, M, room, 0);
        out.zones.set(id, { floor: f.id, floorMat: zm, volMat: vm, floorMesh: zf, vol, vav: v, room });
      }
      for (const c of corridors.get(f.id)) // supply main along each corridor, from the shaft
        group.add(mesh(boxGeo(SHAFT.x - c.x0 - 1, .5, 1.0, 2), M.duct, px((c.x0 + 1 + SHAFT.x) / 2), h - .55, pz(c.z), "systems"));
    }
    if (f.kind === "plant" || f.kind === "roof") {
      const list = rooms.get(f.id), maxX = Math.max(...list.map(r => r.x + r.w));
      for (const room of list) {
        if (room.kind === "plant") {
          walls(I, M, room, BH - .3, true, room.x + room.w >= maxX - .01);
          const ep = mesh(boxGeo(room.w - .3, .03, room.d - .3, 4), M.epoxy, px(room.x + room.w / 2), .03, pz(room.z + room.d / 2), "realistic"); group.add(ep);
          // housekeeping pads under the equipment
          for (const id of room.assets) { const p = pos.get(id); group.add(mesh(boxGeo(p.w + .4, .12, p.d + .4, 2), M.concrete, px(p.x), .06, pz(p.z), "realistic")); }
        } else if (room.name === "Cooling towers" || room.name === "Air handling") {
          // louvered mechanical screen around rooftop equipment
          const sh = room.name === "Cooling towers" ? 3.2 : 2.4;
          for (const [x, z, w, d] of [[room.x + room.w / 2, room.z, room.w, .12], [room.x + room.w / 2, room.z + room.d, room.w, .12], [room.x, room.z + room.d / 2, .12, room.d]])
            group.add(mesh(boxGeo(w, sh, d, 2), M.louver, px(x), sh / 2, pz(z), "realistic"));
        }
        for (const id of room.assets) {
          const p = pos.get(id);
          addEquip(group, M, fl, out, f.id, byId.get(id), px(p.x), f.kind === "plant" ? .12 : .28, pz(p.z), p.s || 1);
        }
      }
      if (f.kind === "plant") { // headers along the corridor, branches to every piece of plant
        const c = corridors.get(f.id)[0], yH = BH - .55;
        pipeRun(group, [[px(c.x0 + 1), yH, pz(c.z) - .3], [px(SHAFT.x) - 1.2, yH, pz(c.z) - .3], [px(SHAFT.x) - 1.2, yH, pz(SHAFT.z)]], .16, M.pipeCHW, "systems");
        pipeRun(group, [[px(c.x0 + 1), yH - .4, pz(c.z) + .3], [px(SHAFT.x) - .8, yH - .4, pz(c.z) + .3], [px(SHAFT.x) - .8, yH - .4, pz(SHAFT.z) + .6]], .12, M.pipeHW, "systems");
        for (const e of equip.filter(x => x.floor === "B1" && ["Chiller", "Boiler", "Pump", "Heat exchanger"].includes(x.type))) {
          const p = pos.get(e.id), hw = e.type === "Boiler" || e.type === "Heat exchanger" || /HHWP/.test(e.name);
          const y = hw ? yH - .4 : yH, zc = pz(c.z) + (hw ? .3 : -.3);
          pipeRun(group, [[px(p.x), y, pz(p.z)], [px(p.x), y, zc]], hw ? .1 : .13, hw ? M.pipeHW : M.pipeCHW, "systems");
        }
        // retaining walls of the basement (seen in cutaway and section)
        for (const [x, z, w, d] of [[0, -DEP / 2 - .2, W + .8, .4], [0, DEP / 2 + .2, W + .8, .4], [-W / 2 - .2, 0, .4, DEP], [W / 2 + .2, 0, .4, DEP]])
          group.add(mesh(boxGeo(w, BH, d, 3), M.concrete, x, BH / 2 - .4, z, "realistic"));
      }
      if (f.kind === "roof") { // parapet, coping, elevator overrun
        for (const [x, z, w, d] of [[0, -DEP / 2 + .15, W, .3], [0, DEP / 2 - .15, W, .3], [-W / 2 + .15, 0, .3, DEP], [W / 2 - .15, 0, .3, DEP]]) {
          group.add(mesh(boxGeo(w, 1.1, d, 2), M.spandrel, x, .55, z, "realistic"));
          group.add(mesh(boxGeo(w + .1, .08, d + .2, 2), M.mullion, x, 1.12, z, "realistic"));
        }
        const cw = CORE.x1 - CORE.x0;
        group.add(mesh(boxGeo(cw, 3.4, CORE.z1 - CORE.z0, 2), M.spandrel, px(CORE.x0 + cw / 2), 1.7, pz((CORE.z0 + CORE.z1) / 2), "realistic"));
        group.add(mesh(boxGeo(cw + .2, .15, CORE.z1 - CORE.z0 + .2, 2), M.mullion, px(CORE.x0 + cw / 2), 3.45, pz((CORE.z0 + CORE.z1) / 2), "realistic"));
        for (let i = 0; i < 5; i++) group.add(mesh(new THREE.CylinderGeometry(.04, .04, 1.4, 6), M.steel, -W / 2 + 6 + i * 14, .7, DEP / 2 - 1.5, "realistic"));
      }
    }
    if (f.kind !== "roof") { core(group, M, h, f.id); risers(group, M, h, f.kind === "zones"); }
    if (f.kind === "zones" && !(REAL && isBasement(f.id))) facade(group, M, I, h, f.id === GROUND_ID);

    const built = { ...I.build(), ...FI.build() };
    for (const [k, im] of Object.entries(built)) {
      im.userData.layer = ["mullion", "fin", "transom"].includes(k) ? "facade" : ["wall", "glass", "frame", "doorLeaf", "block"].includes(k) ? "walls"
        : k === "light" ? "lights" : "furniture";
      if (k === "glass") im.castShadow = false;
      group.add(im);
    }
    group.traverse(o => { if (o.isMesh && o.userData.facade) { o.userData.floor = f.id; out.hits.push(o); } });
    fl.allMats = [...new Set([...fl.mats, ...fl.extraMats])];
    fl.M = M;
    out.floors.set(f.id, fl);
  }
  return out;
}
