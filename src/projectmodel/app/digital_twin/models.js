// Procedural equipment models, one per type, built at real-world size (metres) from primitives. Each model's
// origin is the centre of its footprint at floor level, length along x. userData.tint lists the body meshes that
// take the data colour in Analysis mode; userData.spin lists parts that rotate (fans), with their axis.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

// Box with UVs scaled to world size, so a texture tiles once per `tile` metres whatever the box size.
export function boxGeo(w, h, d, tile = 4) {
  const g = new THREE.BoxGeometry(w, h, d), uv = g.attributes.uv, n = g.attributes.normal;
  for (let i = 0; i < uv.count; i++) {
    const ax = Math.abs(n.getX(i)), ay = Math.abs(n.getY(i));
    const [su, sv] = ax > .5 ? [d, h] : ay > .5 ? [w, d] : [w, h];
    uv.setXY(i, uv.getX(i) * su / tile, uv.getY(i) * sv / tile);
  }
  return g;
}
const mesh = (g, m, x = 0, y = 0, z = 0) => { const o = new THREE.Mesh(g, m); o.position.set(x, y, z); o.castShadow = o.receiveShadow = true; return o; };
const box = (p, w, h, d, m, x, y, z) => { const o = mesh(boxGeo(w, h, d, 2), m, x, y, z); p.add(o); return o; };
const rbox = (p, w, h, d, r, m, x, y, z) => { const o = mesh(new RoundedBoxGeometry(w, h, d, 3, r), m, x, y, z); p.add(o); return o; };
function cyl(p, r, h, m, axis, x, y, z, seg = 24, r2 = r, open = false) {
  const o = mesh(new THREE.CylinderGeometry(r2, r, h, seg, 1, open), m, x, y, z);
  if (axis === "x") o.rotation.z = Math.PI / 2; else if (axis === "z") o.rotation.x = Math.PI / 2;
  p.add(o); return o;
}
// Flanged pipe stub between two points (straight runs only), with a flange at the start.
function pipe(p, a, b, r, m, flangeM) {
  const va = new THREE.Vector3(...a), vb = new THREE.Vector3(...b), len = va.distanceTo(vb);
  const o = mesh(new THREE.CylinderGeometry(r, r, len, 16), m);
  o.position.copy(va).lerp(vb, .5); o.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), vb.clone().sub(va).normalize());
  p.add(o);
  if (flangeM) { const f = mesh(new THREE.CylinderGeometry(r * 1.6, r * 1.6, .05, 18), flangeM); f.position.copy(va); f.quaternion.copy(o.quaternion); p.add(f); }
  return o;
}
function blades(n, r, w, m, axis) {
  const g = new THREE.Group();
  for (let i = 0; i < n; i++) {
    const b = mesh(new THREE.BoxGeometry(r, .03, w), m); b.position.x = r / 2; b.rotation.x = .35;
    const arm = new THREE.Group(); arm.rotation.y = i / n * Math.PI * 2; arm.add(b); g.add(arm);
  }
  const hub = mesh(new THREE.CylinderGeometry(r * .16, r * .16, .12, 16), m); g.add(hub);
  if (axis === "x") g.rotation.z = Math.PI / 2; else if (axis === "z") g.rotation.x = Math.PI / 2;
  return g;
}
const own = (m) => m.clone();
function handles(p, M, x0, x1, y, z, n) { for (let i = 0; i < n; i++) cyl(p, .02, .18, M.steel, "y", x0 + (x1 - x0) * (i + .5) / n, y, z, 8); }

// ---------------------------------------------------------------- AHU
function ahu(M, e) {
  const g = new THREE.Group(), body = own(M.casing), tint = [];
  const L = 8.6, D = 3.0, H = 2.6, base = .22;
  box(g, L + .2, base, D + .1, M.black, 0, base / 2, 0);
  const secs = [["mix", 1.7], ["filter", 1.1], ["coil", 1.4], ["fan", 2.6], ["disch", 1.6]];
  let x = -L / 2;
  for (const [k, w] of secs) {
    const s = rbox(g, w - .05, H, D, .06, body, x + w / 2, base + H / 2, 0); tint.push(s);
    // access door with hinges and handles on the service side
    if (k !== "disch") { box(g, w * .62, H * .78, .03, M.darkMetal, x + w / 2, base + H * .48, D / 2 + .01);
      handles(g, M, x + w / 2 + w * .22, x + w / 2 + w * .22, base + H * .5, D / 2 + .05, 1); }
    if (k === "fan") { // inspection window with the fan wheel turning behind it
      const win = new THREE.Mesh(new THREE.CircleGeometry(.55, 32), M.black); win.position.set(x + w / 2, base + H * .55, D / 2 + .035); g.add(win);
      const ring = mesh(new THREE.TorusGeometry(.56, .04, 8, 40), M.steel, x + w / 2, base + H * .55, D / 2 + .04); g.add(ring);
      const fan = blades(7, .5, .16, M.steel, "z"); fan.position.set(x + w / 2, base + H * .55, D / 2 + .05); g.add(fan);
      g.userData.spin = [[fan, "y", 9]];
    }
    if (k === "coil") { // CHW and HW coil connections with control valves, dropping into the roof
      for (const [dz, m, xx] of [[-.15, M.pipeCHW, -.25], [.15, M.pipeHW, .25]]) {
        pipe(g, [x + w / 2 + xx, base + .6, D / 2 + .35], [x + w / 2 + xx, -1.2, D / 2 + .35], .07, m);
        pipe(g, [x + w / 2 + xx, base + .6, D / 2], [x + w / 2 + xx, base + .6, D / 2 + .45], .07, m, M.steel);
        box(g, .18, .18, .18, M.yellow, x + w / 2 + xx, base + 1.05, D / 2 + .35); cyl(g, .07, .22, M.black, "y", x + w / 2 + xx, base + 1.25, D / 2 + .35, 12);
      }
    }
    x += w;
  }
  // outdoor air hood with louvers on the mixing end
  const hood = box(g, .55, H * .8, D * .9, M.louver, -L / 2 - .3, base + H * .45, 0); hood.rotation.z = -.08;
  box(g, .8, .06, D * .95, body, -L / 2 - .33, base + H * .88, 0);
  // supply and return ducts down into the roof
  box(g, 1.3, 1.4, 1.6, M.duct, L / 2 - .9, -.4, 0);
  box(g, 1.1, 1.2, 1.3, M.duct, -L / 2 + 1.0, -.4, 0);
  // roof curb
  box(g, L + .4, .25, D + .3, M.darkMetal, 0, -.1, 0);
  g.userData.tint = tint;
  return g;
}

// ---------------------------------------------------------------- Chiller
function chiller(M, e) {
  const g = new THREE.Group(), body = own(M.casingBlue), L = 5.4, tint = [];
  // saddles
  for (const sx of [-1.8, 1.8]) box(g, .3, .55, 2.0, M.black, sx, .27, 0);
  const evap = cyl(g, .5, L, M.insulation, "x", 0, .9, -.5, 32);
  const cond = cyl(g, .46, L, body, "x", 0, .9, .52, 32); tint.push(cond);
  // water boxes and flanged nozzles at each end
  for (const sx of [-1, 1]) {
    cyl(g, .56, .22, body, "x", sx * (L / 2 + .1), .9, -.5, 32); cyl(g, .52, .22, body, "x", sx * (L / 2 + .1), .9, .52, 32);
    for (let i = 0; i < 6; i++) { const a = i / 6 * Math.PI * 2; cyl(g, .03, .26, M.steel, "x", sx * (L / 2 + .1), .9 + Math.sin(a) * .5, -.5 + Math.cos(a) * .5, 6); }
  }
  pipe(g, [L / 2 + .2, 1.1, -.5], [L / 2 + .7, 1.1, -.5], .16, M.pipeCHW, M.steel); pipe(g, [L / 2 + .7, 1.1, -.5], [L / 2 + .7, 3.9, -.5], .16, M.pipeCHW);
  pipe(g, [L / 2 + .2, .7, -.5], [L / 2 + 1.05, .7, -.5], .16, M.pipeCHW, M.steel); pipe(g, [L / 2 + 1.05, .7, -.5], [L / 2 + 1.05, 3.9, -.5], .16, M.pipeCHW);
  pipe(g, [-L / 2 - .2, 1.1, .52], [-L / 2 - .7, 1.1, .52], .15, M.pipeCW, M.steel); pipe(g, [-L / 2 - .7, 1.1, .52], [-L / 2 - .7, 3.9, .52], .15, M.pipeCW);
  // compressor and motor on top, discharge line to the condenser
  const comp = cyl(g, .42, 1.9, body, "x", -.4, 1.85, 0, 28); tint.push(comp);
  cyl(g, .36, 1.2, M.casingBlue, "x", 1.2, 1.85, 0, 28); cyl(g, .38, .08, M.steel, "x", .56, 1.85, 0, 28);
  for (let i = 0; i < 8; i++) cyl(g, .37, .025, M.darkMetal, "x", .8 + i * .1, 1.85, 0, 24);
  const arc = mesh(new THREE.TorusGeometry(.4, .09, 10, 20, Math.PI), M.steel, -1.4, 1.75, .25); arc.rotation.y = Math.PI / 2; g.add(arc);
  // control panel with a lit screen
  box(g, .7, 1.4, .35, M.darkMetal, -L / 2 + .7, 1.3, -1.05);
  box(g, .4, .28, .02, M.screen, -L / 2 + .7, 1.6, -.87);
  box(g, .04, .04, .02, M.led, -L / 2 + .5, 1.3, -.87);
  g.userData.tint = tint;
  return g;
}

// ---------------------------------------------------------------- Boiler
function boiler(M, e) {
  const g = new THREE.Group(), body = own(M.casingRed), tint = [];
  box(g, 3.3, .14, 1.8, M.black, 0, .07, 0);
  tint.push(rbox(g, 2.6, 1.9, 1.5, .12, body, .2, 1.1, 0));
  box(g, 2.6, .05, 1.5, M.darkMetal, .2, 2.06, 0);
  // burner and blower at the front
  cyl(g, .38, .5, M.steel, "x", -1.35, 1.1, 0, 28); cyl(g, .28, .45, M.casingBlue, "z", -1.55, .55, .35, 24);
  box(g, .35, .35, .35, M.casingBlue, -1.62, .55, .0);
  // flue with an elbow up to the ceiling
  cyl(g, .22, .8, M.steel, "y", 1.1, 2.4, 0, 20); const elb = mesh(new THREE.TorusGeometry(.35, .22, 12, 16, Math.PI / 2), M.steel, 1.45, 2.8, 0); elb.rotation.z = Math.PI / 2 * 2; g.add(elb);
  // control panel, gauges, HW connections
  box(g, .5, .7, .14, M.darkMetal, -.6, 1.6, .82); box(g, .3, .18, .02, M.screen, -.6, 1.75, .9);
  for (const dx of [.2, .5]) cyl(g, .06, .04, M.steel, "z", dx, 1.7, .78, 16);
  pipe(g, [.6, 2.05, -.3], [.6, 4.4, -.3], .11, M.pipeHW, M.steel); pipe(g, [-.2, 2.05, -.3], [-.2, 4.4, -.3], .11, M.pipeHW, M.steel);
  g.userData.tint = tint;
  return g;
}

// ---------------------------------------------------------------- Pump
function pump(M, e) {
  const g = new THREE.Group(), body = own(M.casingBlue), tint = [];
  const pm = /HHWP/.test(e.name) ? M.pipeHW : /CWP/.test(e.name) && !/CHW/.test(e.name) && !/PCHWP/.test(e.name) ? M.pipeCW : M.pipeCHW;
  box(g, 1.8, .12, .7, M.steel, 0, .06, 0); box(g, 1.9, .1, .8, M.concrete, 0, -.01, 0);
  const motor = cyl(g, .26, .75, body, "x", -.45, .42, 0, 28); tint.push(motor);
  for (let i = 0; i < 7; i++) cyl(g, .28, .02, body, "x", -.75 + i * .09, .42, 0, 24);
  cyl(g, .24, .14, M.darkMetal, "x", -.89, .42, 0, 24);
  box(g, .32, .3, .32, M.yellow, .1, .42, 0);
  const vol = cyl(g, .32, .26, body, "x", .5, .45, 0, 28); tint.push(vol);
  pipe(g, [.5, .7, 0], [.5, 4.2, 0], .1, pm, M.steel); pipe(g, [.68, .45, 0], [1.2, .45, 0], .1, pm, M.steel); pipe(g, [1.2, .45, 0], [1.2, 4.2, 0], .1, pm);
  g.userData.tint = tint;
  return g;
}

// ---------------------------------------------------------------- Heat exchanger (plate and frame)
function hx(M, e) {
  const g = new THREE.Group(), body = own(M.casingBlue), tint = [];
  tint.push(box(g, .22, 1.9, .9, body, -1.0, 1.0, 0)); box(g, .18, 1.7, .8, body, .75, .95, 0);
  box(g, 2.4, .1, .12, M.steel, -.1, 1.95, 0); box(g, 2.4, .1, .12, M.steel, -.1, .12, 0); box(g, .12, 2.0, .12, M.steel, 1.15, 1.0, 0);
  const pack = new THREE.Group(); g.add(pack);
  for (let i = 0; i < 26; i++) { const p = mesh(new THREE.BoxGeometry(.03, 1.55, .78), i % 2 ? M.steel : M.darkMetal, -.84 + i * .061, .97, 0); pack.add(p); }
  for (const [y, z] of [[1.75, .38], [1.75, -.38], [.25, .38], [.25, -.38]]) cyl(g, .025, 2.0, M.steel, "x", -.1, y, z, 8);
  pipe(g, [-1.1, 1.55, .2], [-1.6, 1.55, .2], .1, M.pipeHW, M.steel); pipe(g, [-1.6, 1.55, .2], [-1.6, 4.4, .2], .1, M.pipeHW);
  pipe(g, [-1.1, .45, -.2], [-1.9, .45, -.2], .1, M.pipeHW, M.steel); pipe(g, [-1.9, .45, -.2], [-1.9, 4.4, -.2], .1, M.pipeHW);
  g.userData.tint = tint;
  return g;
}

// ---------------------------------------------------------------- Cooling tower
function tower(M, e) {
  const g = new THREE.Group(), body = own(M.casing), tint = [];
  const S = 4.0, H = 3.4;
  box(g, S + .2, .5, S + .2, M.darkMetal, 0, .25, 0);
  tint.push(box(g, S, H, S, body, 0, .5 + H / 2, 0));
  for (const [x, z, ry] of [[0, S / 2 + .02, 0], [0, -S / 2 - .02, 0]]) { const l = box(g, S * .9, H * .55, .05, M.louver, x, 1.3, z); l.rotation.y = ry; }
  for (const x of [S / 2 + .02, -S / 2 - .02]) box(g, .05, H * .55, S * .9, M.louver, x, 1.3, 0);
  box(g, S + .1, .12, S + .1, M.steel, 0, .5 + H, 0);
  const stack = mesh(new THREE.CylinderGeometry(1.7, 1.55, 1.0, 40, 1, true), body, 0, H + 1.05, 0); stack.material.side = THREE.DoubleSide; g.add(stack); tint.push(stack);
  const rim = mesh(new THREE.TorusGeometry(1.7, .05, 8, 48), M.steel, 0, H + 1.55, 0); rim.rotation.x = Math.PI / 2; g.add(rim);
  const fan = blades(6, 1.5, .4, M.darkMetal, "y"); fan.position.set(0, H + .9, 0); g.add(fan);
  const guard = mesh(new THREE.CircleGeometry(1.68, 40), new THREE.MeshStandardMaterial({ color: 0x222, wireframe: true }), 0, H + 1.5, 0); guard.rotation.x = -Math.PI / 2; g.add(guard);
  // ladder
  for (const dz of [-.22, .22]) cyl(g, .025, H + .4, M.yellow, "y", S / 2 + .25, .5 + H / 2, dz + 1.2, 8);
  for (let i = 0; i < 12; i++) cyl(g, .018, .44, M.yellow, "z", S / 2 + .25, .7 + i * .3, 1.2, 6);
  pipe(g, [-S / 2, .9, 0], [-S / 2 - .8, .9, 0], .17, M.pipeCW, M.steel); pipe(g, [-S / 2 - .8, .9, 0], [-S / 2 - .8, -.6, 0], .17, M.pipeCW);
  g.userData.spin = [[fan, "y", 5]];
  g.userData.tint = tint;
  return g;
}

// ---------------------------------------------------------------- Exhaust fan (roof mushroom)
function exfan(M, e) {
  const g = new THREE.Group(), body = own(M.casing), tint = [];
  box(g, 1.0, .4, 1.0, M.darkMetal, 0, .2, 0);
  tint.push(cyl(g, .45, .5, body, "y", 0, .65, 0, 32));
  const hood = mesh(new THREE.SphereGeometry(.78, 36, 12, 0, Math.PI * 2, 0, Math.PI * .32), body, 0, .62, 0); hood.scale.y = 1.25; g.add(hood); tint.push(hood);
  cyl(g, .7, .18, M.black, "y", 0, .82, 0, 32, .7, true);
  const fan = blades(8, .38, .1, M.darkMetal, "y"); fan.position.y = .92; g.add(fan);
  g.userData.spin = [[fan, "y", 10]];
  g.userData.tint = tint;
  return g;
}

// ---------------------------------------------------------------- Control cabinets, VFDs, meters
function cabinets(M, e, n = 3) {
  const g = new THREE.Group(), body = own(M.partition), tint = [];
  const w = 2.6 / n;
  for (let i = 0; i < n; i++) {
    const x = -1.3 + w * (i + .5);
    tint.push(box(g, w - .03, 2.0, .6, body, x, 1.0, 0)); box(g, w - .14, 1.8, .02, M.casing, x, 1.0, .31);
    cyl(g, .02, .14, M.black, "y", x + w * .3, 1.1, .34, 8);
    box(g, .04, .04, .02, i === 1 && (e.conf ?? 1) < .8 ? M.yellow : M.led, x - w * .3, 1.75, .33);
  }
  box(g, .5, .3, .02, M.screen, -1.3 + w / 2, 1.45, .33);
  box(g, 2.65, .1, .65, M.darkMetal, 0, 2.05, 0);
  g.userData.tint = tint; return g;
}
function vfd(M, e) {
  const g = new THREE.Group(), body = own(M.casingBlue);
  const b = box(g, .8, 1.3, .4, body, 0, 1.0, 0); box(g, .3, .2, .02, M.screen, 0, 1.35, .21);
  for (const x of [-.3, .3]) box(g, .06, .4, .06, M.steel, x, .2, 0);
  for (let i = 0; i < 6; i++) box(g, .6, .02, .02, M.darkMetal, 0, .6 + i * .07, .21);
  g.userData.tint = [b]; return g;
}
function meter(M, e) {
  const g = new THREE.Group(), tint = [];
  if (/Elec/.test(e.name)) {
    const body = own(M.partition); tint.push(box(g, .7, 1.0, .3, body, 0, 1.1, 0));
    cyl(g, .16, .12, M.glassPartition, "z", 0, 1.25, .18, 24); box(g, .2, .08, .02, M.screen, 0, .9, .16);
    for (let i = 0; i < 3; i++) pipe(g, [-.2 + i * .2, 1.6, 0], [-.2 + i * .2, 3.6, 0], .03, M.darkMetal);
  } else {
    const water = /Water/.test(e.name), pm = water ? M.pipeCHW : M.yellow, body = own(water ? M.casingBlue : M.yellow);
    pipe(g, [-.6, .6, 0], [.6, .6, 0], .08, pm); pipe(g, [-.6, .6, 0], [-.6, 3.6, 0], .08, pm);
    tint.push(cyl(g, .16, .3, body, "y", 0, .78, 0, 20)); cyl(g, .13, .04, M.glassPartition, "y", 0, .95, 0, 20);
    box(g, .1, .55, .1, M.steel, 0, .28, 0);
  }
  g.userData.tint = tint; return g;
}
function systemModel(M, e) {
  if (/Plant$/.test(e.name)) return cabinets(M, e, 4);
  return cabinets(M, e, 2);
}

const BUILD = { AHU: ahu, Chiller: chiller, Boiler: boiler, Pump: pump, "Heat exchanger": hx, "Cooling tower": tower,
  "Exhaust fan": exfan, System: systemModel, "Fan VFD": vfd, Meter: meter };
export function buildEquipment(M, e) {
  const g = (BUILD[e.type] || cabinets)(M, e);
  g.userData.spin = g.userData.spin || []; g.userData.tint = g.userData.tint || [];
  return g;
}

// ---------------------------------------------------------------- VAV box (ceiling), as seen when the ceiling is open
export function vavBox(M, dual) {
  const g = new THREE.Group(), body = own(M.duct);
  const b = box(g, 1.0, .38, .55, body, 0, 0, 0);
  cyl(g, .14, .5, M.duct, "x", -.75, 0, dual ? -.14 : 0, 16); if (dual) cyl(g, .14, .5, M.duct, "x", -.75, 0, .14, 16);
  box(g, .22, .16, .1, M.black, -.2, .2, .3);           // damper actuator
  if (!dual) { box(g, .1, .32, .5, M.pipeHW, .45, 0, 0); } // reheat coil
  g.userData.tint = [b];
  return g;
}
