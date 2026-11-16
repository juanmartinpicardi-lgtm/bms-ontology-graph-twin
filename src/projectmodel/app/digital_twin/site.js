// The site around the building (Realistic mode): a painted ground plan, trees, parked cars, street lights and a
// few neighbouring blocks. Everything is procedural; nothing here is data.
import * as THREE from "three";
import { W, DEP } from "./data.js";

const SIZE = 420, PX = 4096, S = PX / SIZE;           // ground texture covers SIZE metres
const toPx = v => (v + SIZE / 2) * S;

function groundTexture() {
  const c = document.createElement("canvas"); c.width = c.height = PX; const g = c.getContext("2d");
  const fillNoise = (x, y, w, h, base, amp, n) => { g.fillStyle = base; g.fillRect(x, y, w, h);
    for (let i = 0; i < n; i++) { const v = (Math.random() - .5) * amp; g.fillStyle = v > 0 ? `rgba(255,255,255,${v})` : `rgba(0,0,0,${-v})`;
      g.fillRect(x + Math.random() * w, y + Math.random() * h, 3, 3); } };
  fillNoise(0, 0, PX, PX, "#5d7346", .18, 260000);                                  // lawn
  for (let i = 0; i < 300; i++) { g.fillStyle = `rgba(40,60,25,${Math.random() * .12})`; g.beginPath(); g.arc(Math.random() * PX, Math.random() * PX, 20 + Math.random() * 120, 0, 7); g.fill(); }
  const rect = (x0, z0, x1, z1, col, amp = .08) => fillNoise(toPx(x0), toPx(z0), (x1 - x0) * S, (z1 - z0) * S, col, amp, (x1 - x0) * (z1 - z0) * 2);
  // roads: a main street to the south and one to the west
  rect(-SIZE / 2, 62, SIZE / 2, 78, "#3a3c3f", .1); rect(-92, -SIZE / 2, -78, SIZE / 2, "#3a3c3f", .1);
  g.strokeStyle = "rgba(240,220,120,.85)"; g.lineWidth = .25 * S; g.setLineDash([3 * S, 3 * S]);
  g.beginPath(); g.moveTo(0, toPx(70)); g.lineTo(PX, toPx(70)); g.stroke(); g.beginPath(); g.moveTo(toPx(-85), 0); g.lineTo(toPx(-85), PX); g.stroke(); g.setLineDash([]);
  // sidewalks
  rect(-SIZE / 2, 58, SIZE / 2, 62, "#b9b5ac", .06); rect(-78, -SIZE / 2, -74, SIZE / 2, "#b9b5ac", .06);
  // plaza around the building, entry walk to the street
  rect(-W / 2 - 7, -DEP / 2 - 6, W / 2 + 7, DEP / 2 + 9, "#c4c0b6", .07);
  g.strokeStyle = "rgba(0,0,0,.07)"; g.lineWidth = 2;
  for (let x = -W / 2 - 7; x < W / 2 + 7; x += 1.5) { g.beginPath(); g.moveTo(toPx(x), toPx(-DEP / 2 - 6)); g.lineTo(toPx(x), toPx(DEP / 2 + 9)); g.stroke(); }
  rect(-10, DEP / 2 + 9, -2, 58, "#c4c0b6", .07);
  // parking lot east, with stalls
  rect(W / 2 + 14, -DEP / 2 - 4, W / 2 + 74, DEP / 2 + 26, "#45474a", .1);
  g.strokeStyle = "rgba(255,255,255,.8)"; g.lineWidth = .15 * S;
  for (const row of [-DEP / 2 + 1, -DEP / 2 + 6.2, 4, 9.2, 20, 25.2]) for (let x = W / 2 + 18; x <= W / 2 + 70; x += 2.6) {
    g.beginPath(); g.moveTo(toPx(x), toPx(row)); g.lineTo(toPx(x), toPx(row + 5)); g.stroke(); }
  rect(W / 2 + 7, 2, W / 2 + 14, 8, "#45474a", .1); // drive aisle from the plaza
  // planting beds around the plaza
  for (const [x0, z0, x1, z1] of [[-W / 2 - 7, DEP / 2 + 9, -12, DEP / 2 + 16], [0, DEP / 2 + 9, W / 2 + 7, DEP / 2 + 16]]) rect(x0, z0, x1, z1, "#4a5a35", .25);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 16;
  return t;
}

export function buildSite() {
  const site = new THREE.Group();
  // ground with a hole for the basement, so peeling floors reveals the plant room
  const shape = new THREE.Shape([new THREE.Vector2(-SIZE / 2, -SIZE / 2), new THREE.Vector2(SIZE / 2, -SIZE / 2), new THREE.Vector2(SIZE / 2, SIZE / 2), new THREE.Vector2(-SIZE / 2, SIZE / 2)]);
  shape.holes.push(new THREE.Path([new THREE.Vector2(-W / 2, -DEP / 2), new THREE.Vector2(-W / 2, DEP / 2), new THREE.Vector2(W / 2, DEP / 2), new THREE.Vector2(W / 2, -DEP / 2)]));
  const gg = new THREE.ShapeGeometry(shape);
  const uv = gg.attributes.uv, p = gg.attributes.position;
  for (let i = 0; i < uv.count; i++) uv.setXY(i, (p.getX(i) + SIZE / 2) / SIZE, (p.getY(i) + SIZE / 2) / SIZE);
  const ground = new THREE.Mesh(gg, new THREE.MeshStandardMaterial({ map: groundTexture(), roughness: .95 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -.02; ground.receiveShadow = true;
  // Rotating -90° about X maps local +Y to world -Z; with the canvas's flipY that keeps north (−z) at the top row.
  site.add(ground);

  // trees: trunk + two foliage clusters, instanced, varied size and colour
  const rnd = (a, b) => a + Math.random() * (b - a);
  const spots = [];
  for (let x = -SIZE / 2 + 10; x < SIZE / 2; x += 11) { spots.push([x + rnd(-2, 2), 56]); spots.push([x + rnd(-2, 2), 81]); }
  for (let z = -SIZE / 2 + 10; z < SIZE / 2; z += 11) { spots.push([-72, z + rnd(-2, 2)]); spots.push([-96, z + rnd(-2, 2)]); }
  for (let i = 0; i < 26; i++) spots.push([rnd(-W / 2 - 4, -14), rnd(DEP / 2 + 10, DEP / 2 + 15)], [rnd(2, W / 2 + 4), rnd(DEP / 2 + 10, DEP / 2 + 15)]);
  for (let i = 0; i < 70; i++) { const a = Math.random() * Math.PI * 2, r = rnd(70, 190); spots.push([Math.cos(a) * r, Math.sin(a) * r - 60]); }
  const ok = ([x, z]) => !(Math.abs(x) < W / 2 + 8 && z > -DEP / 2 - 7 && z < DEP / 2 + 9) && !(x > W / 2 + 12 && x < W / 2 + 76 && z > -DEP / 2 - 6 && z < DEP / 2 + 28)
    && !(z > 60 && z < 80) && !(x > -94 && x < -76) && Math.hypot(x - 160, z + 120) > 40;
  const trees = spots.filter(ok);
  const trunk = new THREE.InstancedMesh(new THREE.CylinderGeometry(.18, .28, 1, 8).translate(0, .5, 0), new THREE.MeshStandardMaterial({ color: 0x4b3a2a, roughness: 1 }), trees.length);
  // foliage: a lumpy sphere (low-frequency noise on the radius) reads as a canopy rather than a gem
  const leafGeo = new THREE.IcosahedronGeometry(1, 5), pos = leafGeo.attributes.position;
  const seeds = Array.from({ length: 6 }, () => new THREE.Vector3().randomDirection());
  for (let i = 0; i < pos.count; i++) {
    const v = new THREE.Vector3().fromBufferAttribute(pos, i).normalize();
    let r = 1; seeds.forEach((s, k) => r += Math.max(0, v.dot(s)) ** 3 * (k % 2 ? .16 : -.1));
    r += Math.sin(v.x * 9) * Math.sin(v.y * 11) * Math.sin(v.z * 7) * .05; v.multiplyScalar(r); pos.setXYZ(i, v.x, v.y, v.z);
  }
  leafGeo.computeVertexNormals();
  const leafTex = (() => { const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d");
    g.fillStyle = "#808080"; g.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 5000; i++) { g.fillStyle = `rgba(${Math.random() > .5 ? "255,255,255" : "0,0,0"},${Math.random() * .35})`; g.beginPath(); g.arc(Math.random() * 256, Math.random() * 256, 1 + Math.random() * 3, 0, 7); g.fill(); }
    const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(3, 3); return t; })();
  const leaves = new THREE.InstancedMesh(leafGeo, new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: .95, bumpMap: leafTex, bumpScale: 2.5 }), trees.length * 2);
  const o = new THREE.Object3D(), col = new THREE.Color();
  trees.forEach(([x, z], i) => {
    const s = rnd(.8, 1.4), h = rnd(3, 5) * s;
    o.position.set(x, 0, z); o.scale.set(s, h, s); o.rotation.set(0, 0, 0); o.updateMatrix(); trunk.setMatrixAt(i, o.matrix);
    for (let k = 0; k < 2; k++) {
      o.position.set(x + rnd(-.6, .6) * s, h + (k ? 1.6 : .6) * s, z + rnd(-.6, .6) * s); const r = (k ? 1.7 : 2.4) * s;
      o.scale.set(r, r * rnd(.85, 1.1), r); o.rotation.y = Math.random() * 6; o.updateMatrix(); leaves.setMatrixAt(i * 2 + k, o.matrix);
      leaves.setColorAt(i * 2 + k, col.setHSL(rnd(.2, .29), rnd(.3, .48), rnd(.18, .28)));
    }
  });
  // Everything that is not the building or its ground sits in `extras`, so it can be switched off.
  const extras = new THREE.Group(); site.add(extras);
  trunk.castShadow = leaves.castShadow = true; leaves.receiveShadow = true; extras.add(trunk, leaves);

  // parked cars
  const cars = [];
  for (const [row, ry] of [[-DEP / 2 + 3.5, 0], [-DEP / 2 + 8.7, 0], [6.5, 0], [11.7, 0], [22.5, 0], [27.7, 0]])
    for (let x = W / 2 + 19.3; x <= W / 2 + 69; x += 2.6) if (Math.random() < .72) cars.push([x, row - 1, ry]);
  for (let i = 0; i < 9; i++) cars.push([rnd(-SIZE / 2, SIZE / 2), i % 2 ? 66.5 : 73.5, Math.PI / 2]);
  const bodyG = new THREE.BoxGeometry(1.8, .7, 4.3).translate(0, .55, 0), cabG = new THREE.BoxGeometry(1.6, .55, 2.2).translate(0, 1.15, -.2);
  const body = new THREE.InstancedMesh(bodyG, new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: .25, metalness: .6, clearcoat: 1 }), cars.length);
  const cab = new THREE.InstancedMesh(cabG, new THREE.MeshPhysicalMaterial({ color: 0x1a2128, roughness: .05, metalness: .5, clearcoat: 1 }), cars.length);
  const palette = [0xe8e8e8, 0x1c1c1c, 0x8a8f96, 0x2e4a6b, 0x8c2a24, 0xd0d3d6, 0x3b3f44];
  cars.forEach(([x, z, ry], i) => { o.position.set(x, 0, z); o.scale.set(1, 1, 1); o.rotation.set(0, ry, 0); o.updateMatrix();
    body.setMatrixAt(i, o.matrix); cab.setMatrixAt(i, o.matrix); body.setColorAt(i, col.setHex(palette[i % palette.length])); });
  body.castShadow = cab.castShadow = true; extras.add(body, cab);

  // street and plaza lights (their heads glow at night)
  const lamps = [];
  for (let x = -SIZE / 2 + 15; x < SIZE / 2; x += 30) lamps.push([x, 60.5]);
  for (const [x, z] of [[-W / 2 - 5, -DEP / 2 - 4], [W / 2 + 5, -DEP / 2 - 4], [-W / 2 - 5, DEP / 2 + 7], [W / 2 + 5, DEP / 2 + 7]]) lamps.push([x, z]);
  for (let x = W / 2 + 20; x < W / 2 + 72; x += 16) lamps.push([x, 17]);
  const pole = new THREE.InstancedMesh(new THREE.CylinderGeometry(.07, .1, 6, 8).translate(0, 3, 0), new THREE.MeshStandardMaterial({ color: 0x2a2d31, metalness: .7, roughness: .4 }), lamps.length);
  const headMat = new THREE.MeshStandardMaterial({ color: 0x222222, emissive: 0xffd9a0, emissiveIntensity: 0 });
  const head = new THREE.InstancedMesh(new THREE.BoxGeometry(.8, .15, .35).translate(.3, 6, 0), headMat, lamps.length);
  lamps.forEach(([x, z], i) => { o.position.set(x, 0, z); o.scale.set(1, 1, 1); o.rotation.set(0, 0, 0); o.updateMatrix(); pole.setMatrixAt(i, o.matrix); head.setMatrixAt(i, o.matrix); });
  pole.castShadow = true; extras.add(pole, head);

  // neighbouring blocks (context), simple massing with glass and stone
  const ctx = new THREE.Group();
  const glass = new THREE.MeshPhysicalMaterial({ color: 0x6d8494, roughness: .08, metalness: .5, envMapIntensity: 1.6, clearcoat: 1 });
  const stone = new THREE.MeshStandardMaterial({ color: 0xbdb7aa, roughness: .9 });
  const bandTex = (() => { const c = document.createElement("canvas"); c.width = 64; c.height = 256; const g = c.getContext("2d");
    for (let y = 0; y < 256; y += 32) { g.fillStyle = "#e9e6df"; g.fillRect(0, y, 64, 9); g.fillStyle = "#3d4b55"; g.fillRect(0, y + 9, 64, 23); }
    const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; return t; })();
  for (const [x, z, w, d, h, kind] of [[-150, -40, 50, 34, 38, "glass"], [-140, 120, 44, 40, 22, "band"], [40, 125, 70, 36, 18, "band"],
    [170, -110, 40, 40, 64, "glass"], [140, 130, 46, 30, 30, "glass"], [-40, -130, 80, 30, 26, "band"], [80, -150, 40, 30, 46, "glass"]]) {
    const m = kind === "glass" ? glass : new THREE.MeshStandardMaterial({ map: (() => { const t = bandTex.clone(); t.needsUpdate = true; t.repeat.set(w / 6, h / 14); return t; })(), roughness: .6 });
    const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); b.position.set(x, h / 2, z); b.castShadow = b.receiveShadow = true; ctx.add(b);
    const cap = new THREE.Mesh(new THREE.BoxGeometry(w + .6, .8, d + .6), stone); cap.position.set(x, h + .4, z); ctx.add(cap);
  }
  extras.add(ctx);
  return { site, lampHeads: headMat, extras };
}
