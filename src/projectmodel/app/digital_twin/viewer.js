// The 3D viewer. Two looks over the same scene:
//   analysis  – dark, schematic, everything coloured by data, floors can be stacked or exploded
//   realistic – the building as built: curtain wall, site, sky and sun by time of day, furniture, interior lights
// Both peel floors (floors above lift away), show what feeds the selected asset as animated flow lines, and float
// alarm beacons over anything that is not normal.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { Sky } from "three/addons/objects/Sky.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { GTAOPass } from "three/addons/postprocessing/GTAOPass.js";
import { OutlinePass } from "three/addons/postprocessing/OutlinePass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { W, DEP, FH, FLOORS, FLOOR_IDX, elevation, floorById, equip, byId, sim, isZone, colorOf, chainUp, C, pos } from "./data.js";
import { baseMaterials, flowTex } from "./materials.js";
import { buildBuilding } from "./building.js";
import { buildSite } from "./site.js";

const WHITE = new THREE.Color(0xffffff);

export function createViewer(host, cb) {
  const V = { mode: "analysis", color: "status", match: () => true, sel: null, floor: null, exploded: false, hours: 15.5,
    cut: null, overlay: false, systems: true, labels: true, hq: true, hover: null };

  // ---------- renderer and post ----------
  const renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap; renderer.localClippingEnabled = true;
  host.appendChild(renderer.domElement);
  const labels = new CSS2DRenderer(); Object.assign(labels.domElement.style, { position: "absolute", inset: 0, pointerEvents: "none" });
  host.appendChild(labels.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, .3, 3000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = .07; controls.maxPolarAngle = Math.PI * .495; controls.minDistance = 6; controls.maxDistance = 600;
  controls.addEventListener("start", () => { V.camGoal = null; });

  const rt = new THREE.WebGLRenderTarget(1, 1, { samples: 4, type: THREE.HalfFloatType });
  const composer = new EffectComposer(renderer, rt);
  composer.addPass(new RenderPass(scene, camera));
  let gtao = null;
  try { gtao = new GTAOPass(scene, camera, 1, 1); gtao.output = GTAOPass.OUTPUT.Default; gtao.blendIntensity = .9;
    gtao.updateGtaoMaterial({ radius: .6, distanceExponent: 1.4, thickness: 1, scale: 1.1, samples: 12 }); composer.addPass(gtao); } catch (err) { gtao = null; }
  const outline = new OutlinePass(new THREE.Vector2(1, 1), scene, camera);
  Object.assign(outline, { edgeStrength: 5, edgeGlow: .6, edgeThickness: 1.6, pulsePeriod: 2.4 });
  outline.visibleEdgeColor.set("#7cc4ff"); outline.hiddenEdgeColor.set("#2a5f8f"); composer.addPass(outline);
  const hoverPass = new OutlinePass(new THREE.Vector2(1, 1), scene, camera);
  Object.assign(hoverPass, { edgeStrength: 3, edgeGlow: 0, edgeThickness: 1 });
  hoverPass.visibleEdgeColor.set("#ffffff"); hoverPass.hiddenEdgeColor.set("#555555"); composer.addPass(hoverPass);
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), .25, .5, .92); composer.addPass(bloom);
  composer.addPass(new OutputPass());

  // ---------- lights, environments, sky ----------
  const pmrem = new THREE.PMREMGenerator(renderer);
  const roomEnv = pmrem.fromScene(new RoomEnvironment(), .04).texture;
  const hemi = new THREE.HemisphereLight(0xdfeaff, 0x3a3d40, .9); scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xffffff, 2.2); sun.castShadow = true;
  sun.shadow.mapSize.set(4096, 4096); Object.assign(sun.shadow.camera, { left: -95, right: 95, top: 95, bottom: -95, near: 1, far: 500 });
  sun.shadow.bias = -.0003; sun.shadow.normalBias = .03; scene.add(sun, sun.target);
  const sky = new Sky(); sky.scale.setScalar(4000);
  Object.assign(sky.material.uniforms, {}); sky.material.uniforms.turbidity.value = 4; sky.material.uniforms.rayleigh.value = 1.6;
  sky.material.uniforms.mieCoefficient.value = .004; sky.material.uniforms.mieDirectionalG.value = .85;
  const skyScene = new THREE.Scene(); const skyForEnv = new Sky(); skyForEnv.scale.setScalar(4000); skyScene.add(skyForEnv);
  ["turbidity", "rayleigh", "mieCoefficient", "mieDirectionalG"].forEach(k => skyForEnv.material.uniforms[k].value = sky.material.uniforms[k].value);
  let skyEnv = null;
  const LIGHT = document.documentElement.dataset.theme === "light" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: light)").matches);
  const grid = new THREE.GridHelper(400, 100, LIGHT ? 0xc9ced4 : 0x23262b, LIGHT ? 0xe1e4e8 : 0x16181b); grid.position.y = -6.4; scene.add(grid);

  // ---------- content ----------
  const base = baseMaterials();
  const B = buildBuilding(base);
  for (const fl of B.floors.values()) {
    scene.add(fl.group);
    fl.y = fl.ty = 0; fl.op = fl.top = 1;
    for (const m of fl.allMats) { m.userData.baseOpacity ??= m.opacity; m.userData.baseTransparent ??= m.transparent; m.userData.baseDepthWrite = m.depthWrite; }
    const div = document.createElement("div"); div.className = "flabel"; div.onclick = () => cb.onFloor?.(V.floor === fl.id ? null : fl.id);
    fl.labelEl = div; const lab = new CSS2DObject(div); lab.position.set(-W / 2 - 4, 1, DEP / 2); fl.group.add(lab); fl.label = lab;
  }
  const { site, lampHeads, extras } = buildSite(); scene.add(site);

  // beacons over anything not normal; rebuilt when statuses change
  const beacons = new Map();
  function syncBeacons() {
    for (const e of equip) {
      const s = sim.get(e.id), want = s.status !== "normal";
      let b = beacons.get(e.id);
      if (want && !b) {
        const el = document.createElement("div"); el.className = "beacon"; el.onclick = ev => { ev.stopPropagation(); cb.onSelect?.(e.id); };
        el.onmouseenter = () => cb.onHover?.(e.id, el.getBoundingClientRect()); el.onmouseleave = () => cb.onHover?.(null);
        b = new CSS2DObject(el); const p = anchorLocal(e.id); b.position.copy(p); b.position.y += 1.2;
        B.floors.get(e.floor).group.add(b); beacons.set(e.id, b);
      }
      if (!want && b) { b.parent.remove(b); b.element.remove(); beacons.delete(e.id); }
      if (b) { b.element.dataset.status = s.status; b.element.title = e.label; }
    }
  }
  function anchorLocal(id) {
    const z = B.zones.get(id); if (z) return new THREE.Vector3(z.floorMesh.position.x, 2.6, z.floorMesh.position.z);
    const q = B.equip.get(id); return new THREE.Vector3(q.group.position.x, q.top, q.group.position.z);
  }
  const anchorWorld = id => { const fl = B.floors.get(byId.get(id).floor); return anchorLocal(id).add(new THREE.Vector3(0, fl.group.position.y, 0)); };

  // flow lines along the feeds chain of the selection
  const chain = new THREE.Group(); scene.add(chain);
  const chainMarks = [];
  const VIA = { airRef: 0x4da3e8, chilledWaterRef: 0x5fd0ff, hotWaterRef: 0xff8a4c };
  function drawChain() {
    chain.children.forEach(o => { o.geometry.dispose(); o.material.map?.dispose?.(); });
    chain.clear(); chainMarks.forEach(m => { m.parent?.remove(m); m.element.remove(); }); chainMarks.length = 0;
    if (!V.sel) return;
    const seen = new Set();
    for (const c of chainUp(V.sel)) {
      const a = anchorWorld(c.from), b = anchorWorld(c.id), mid = a.clone().lerp(b, .5);
      mid.y = Math.max(a.y, b.y) + 6; mid.x += (a.x - b.x) * .1 + 8;
      const curve = new THREE.CatmullRomCurve3([a, a.clone().lerp(mid, .5).setY(mid.y * .8 + a.y * .2), mid, b.clone().lerp(mid, .5).setY(mid.y * .8 + b.y * .2), b]);
      const len = curve.getLength(), tex = flowTex.clone(); tex.needsUpdate = true; tex.repeat.set(len / 3, 1);
      const m = new THREE.MeshBasicMaterial({ color: new THREE.Color(VIA[c.via] || 0xffffff).multiplyScalar(.85), map: tex, transparent: true, opacity: .95, depthTest: false });
      const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 80, .22, 8), m); tube.renderOrder = 20; chain.add(tube);
      if (!seen.has(c.id)) { seen.add(c.id);
        const el = document.createElement("div"); el.className = "chainlabel"; el.innerHTML = `<i style="background:#${(VIA[c.via] || 0xffffff).toString(16).padStart(6, "0")}"></i>${byId.get(c.id).label}`;
        el.onclick = () => cb.onSelect?.(c.id); const lab = new CSS2DObject(el); lab.position.copy(b); lab.position.y += 1.4; scene.add(lab); chainMarks.push(lab);
        const dot = new THREE.Mesh(new THREE.SphereGeometry(.45, 20, 14), new THREE.MeshBasicMaterial({ color: VIA[c.via] || 0xffffff, depthTest: false }));
        dot.position.copy(b); dot.renderOrder = 21; chain.add(dot);
      }
    }
  }

  // ---------- picking ----------
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  const visibleDeep = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
  function pick(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    for (const h of ray.intersectObjects(B.hits, false)) {
      const o = h.object, fid = o.userData.floor || byId.get(o.userData.id)?.floor, fl = B.floors.get(fid);
      if (!fl || fl.op < .5 || !fl.group.visible) continue;
      if (!o.userData.hitbox && !visibleDeep(o)) continue;
      if (o.userData.hitbox && !visibleDeep(o.parent)) continue;
      if (V.cut && h.point.x > V.cut.constant) continue;
      if (o.userData.facade) return { floor: o.userData.floor };
      if (o.userData.id) { if (o === B.zones.get(o.userData.id)?.vol && V.mode !== "analysis") continue; return { id: o.userData.id }; }
      return { floor: o.userData.floor };
    }
    return null;
  }
  let downAt = null;
  const el = renderer.domElement;
  el.addEventListener("pointerdown", ev => downAt = [ev.clientX, ev.clientY]);
  el.addEventListener("pointerup", ev => {
    if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 5) return; downAt = null;
    const h = pick(ev);
    if (!h) { if (V.sel) cb.onSelect?.(null); return; }
    if (h.id) cb.onSelect?.(h.id);
    else if (h.floor && (h.floor !== V.floor || V.sel)) cb.onFloor?.(h.floor);
  });
  let hoverRaf = 0;
  el.addEventListener("pointermove", ev => { cancelAnimationFrame(hoverRaf); hoverRaf = requestAnimationFrame(() => {
    const h = pick(ev); el.style.cursor = h ? "pointer" : "";
    const key = h ? (h.id || "f:" + h.floor) : null;
    if (key !== V.hover) { V.hover = key; hoverPass.selectedObjects = h ? hoverObjects(h) : []; }
    cb.onHover?.(h?.id || (h?.floor ? "floor:" + h.floor : null), { left: ev.clientX, top: ev.clientY });
  }); });
  el.addEventListener("pointerleave", () => { V.hover = null; hoverPass.selectedObjects = []; cb.onHover?.(null); });
  function hoverObjects(h) {
    if (h.id) { const z = B.zones.get(h.id); return z ? [z.floorMesh, z.vav] : [B.equip.get(h.id).group]; }
    const fl = B.floors.get(h.floor); const objs = []; fl.group.traverse(o => { if (o.userData.facade || o.userData.layer === "slab") objs.push(o); });
    return objs;
  }

  // ---------- state application ----------
  function isNight() { return sunElevation(V.hours) < 2; }
  function sunElevation(h) { return Math.sin((h - 6) / 13 * Math.PI) * 64 - 4; }
  function applyEnvironment() {
    const real = V.mode === "realistic";
    if (real) {
      const elev = sunElevation(V.hours), az = 100 + (V.hours - 6) / 13 * 160;
      const phi = THREE.MathUtils.degToRad(90 - elev), theta = THREE.MathUtils.degToRad(az);
      const dir = new THREE.Vector3().setFromSphericalCoords(1, phi, theta);
      sky.material.uniforms.sunPosition.value.copy(dir); skyForEnv.material.uniforms.sunPosition.value.copy(dir);
      if (!sky.parent) scene.add(sky);
      skyEnv?.dispose(); skyEnv = pmrem.fromScene(skyScene).texture;
      const day = THREE.MathUtils.clamp((elev + 4) / 18, 0, 1);
      scene.environment = skyEnv; scene.background = null; scene.environmentIntensity = .12 + .5 * day;
      sun.position.copy(dir).multiplyScalar(220); sun.intensity = 4.2 * day; sun.color.setHSL(.09, .7 * (1 - day) + .12, .5 + .42 * day);
      hemi.intensity = .12 + .38 * day; hemi.color.set(day > .3 ? 0xd6e4f5 : 0x5b6b94); hemi.groundColor.set(0x4a4436);
      renderer.toneMappingExposure = .42 + .3 * (1 - day);
      scene.fog = new THREE.Fog(day > .3 ? 0xc6d3df : 0x1a2233, 260, 900);
      bloom.strength = .12 + .55 * (1 - day); bloom.threshold = day > .3 ? .95 : .6;
      const lit = THREE.MathUtils.clamp(1.6 - day * 1.5, .25, 1.6);
      for (const fl of B.floors.values()) fl.M.light.emissiveIntensity = lit * 2.2;
      interiorGlow(1 - day);
      lampHeads.emissiveIntensity = day < .35 ? 6 : 0;
      grid.visible = false; site.visible = true;
    } else {
      if (sky.parent) scene.remove(sky);
      scene.environment = roomEnv; scene.environmentIntensity = .55; const bgc = new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue("--bg").trim() || "#1e1e1e"); scene.background = bgc; scene.fog = new THREE.Fog(bgc, 300, 700);
      sun.position.set(80, 160, 60); sun.intensity = 1.5; sun.color.set(0xffffff); hemi.intensity = .7; hemi.color.set(0xdfeaff);
      renderer.toneMappingExposure = .9; bloom.strength = .18; bloom.threshold = .97;
      for (const fl of B.floors.values()) fl.M.light.emissiveIntensity = 0;
      interiorGlow(0);
      grid.visible = true; site.visible = false;
    }
    if (gtao) gtao.enabled = V.hq && real;
  }
  // Lights in the ceiling don't light anything by themselves; at night interiors get a warm self-glow instead
  // (cheap stand-in for hundreds of real lights) and the curtain wall turns more transparent, as glass does after dark.
  const WARM = new THREE.Color(0xffe2b8);
  V.glow = 0;
  function interiorGlow(k) {
    V.glow = k;
    for (const fl of B.floors.values()) {
      const M = fl.M;
      for (const [key, s] of [["carpet", .12], ["partition", .2], ["desk", .22], ["deskWood", .16], ["chair", .05], ["plantFloor", .1], ["epoxy", .08], ["concrete", .05], ["lobby", .15]])
        M[key].emissive.copy(WARM).multiplyScalar(k * s);
      M.curtain.userData.baseOpacity = .58 - .3 * k; M.spandrel.emissive?.set(0);
      fl.lastOp = undefined;
    }
  }
  function floorBaseY(fid) {
    if (V.mode === "realistic") return elevation(fid);
    return elevation(fid) + FLOOR_IDX[fid] * (V.exploded ? 9 : 2.2);
  }
  function layout() {
    const real = V.mode === "realistic", fi = V.floor ? FLOOR_IDX[V.floor] : null;
    for (const fl of B.floors.values()) {
      const i = FLOOR_IDX[fl.id], above = fi != null && i > fi;
      // Analysis lifts the floors above out of the way; Realistic leaves them in place and fades them (dollhouse),
      // so flow lines to the roof still end where the roof really is.
      fl.ty = floorBaseY(fl.id) + (above && !real ? 34 + (i - fi) * 7 : 0);
      fl.top = fi == null ? 1 : fl.id === V.floor ? 1 : above ? (real ? 0 : .08) : (real ? 1 : .28);
      fl.labelEl.classList.toggle("on", fl.id === V.floor);
      // layers
      fl.group.traverse(o => {
        const L = o.userData.layer; if (!L) return;
        if (L === "facade") o.visible = real && fl.id !== V.floor;
        else if (L === "realistic") o.visible = real && !(fl.id === "RF" && false);
        else if (L === "furniture" || L === "lights") o.visible = real;
        else if (L === "analysis") o.visible = !real;
        else if (L === "systems") o.visible = V.systems;
        else if (L === "walls") { o.scale.y = !real ? .32 : fl.id === "B1" && V.floor === "B1" ? .26 : 1; }
      });
      fl.label.visible = V.labels;
    }
    const target = V.sel ? anchorWorld(V.sel).setY(floorBaseY(byId.get(V.sel).floor)) : null;
    if (V.sel && target) flyTo(target, real ? 62 : 70, .55);
    else if (V.floor) flyTo(new THREE.Vector3(0, floorBaseY(V.floor), 0), real ? 92 : 100, 1.0);
    else flyTo(null);
  }
  function flyTo(t, dist, steep = .62) {
    const aspectK = 1 / Math.min(1, camera.aspect / 1.55);
    if (!t) { const real = V.mode === "realistic";
      const ty = real ? 6 : (floorBaseY("RF") + floorBaseY("B1")) / 2, d = (real ? 112 : (V.exploded ? 140 : 108)) * aspectK;
      V.camGoal = { t: new THREE.Vector3(0, ty, 0), p: new THREE.Vector3(d * .62, ty + d * (real ? .2 : .5), d * .78) }; return; }
    const d = dist * aspectK;
    const dir = camera.position.clone().sub(controls.target); dir.y = 0; if (dir.lengthSq() < 1) dir.set(.6, 0, .8); dir.normalize();
    V.camGoal = { t: t.clone(), p: t.clone().add(dir.multiplyScalar(d * .62)).add(new THREE.Vector3(0, d * steep, 0)) };
  }
  function paint() {
    const real = V.mode === "realistic";
    for (const [id, z] of B.zones) {
      const e = byId.get(id), on = V.match(e), col = new THREE.Color(colorOf(e, V.color)), s = sim.get(id);
      const wantMap = real ? B.floors.get(z.floor).M.carpet.map : null;
      if (z.floorMat.map !== wantMap) { z.floorMat.map = wantMap; z.floorMat.needsUpdate = true; }
      if (!real) {
        z.floorMat.color.copy(on ? col : new THREE.Color(LIGHT ? 0xd5d9de : 0x2a2d31)); z.floorMat.emissive.copy(on ? col : new THREE.Color(0)).multiplyScalar(.28);
        z.volMat.color.copy(col); z.volMat.opacity = on ? (s.status === "normal" && V.color === "status" ? .1 : .3) : .02;
      } else {
        const tint = V.overlay && on; z.floorMat.color.copy(tint ? WHITE.clone().lerp(col, .75) : WHITE);
        z.floorMat.emissive.copy(tint ? col : WARM).multiplyScalar(tint ? .22 + V.glow * .2 : V.glow * .12);
      }
      const vb = z.vav.children[0]; if (vb) vb.material.color.set(!real && on ? col : 0xc7ccd0);
    }
    for (const [id, q] of B.equip) {
      const e = byId.get(id), on = V.match(e), col = new THREE.Color(colorOf(e, V.color));
      for (const m of q.tint) {
        if (real) { m.color.setHex(m.userData.orig); m.emissive?.set(0); }
        else { m.color.copy(on ? col : new THREE.Color(LIGHT ? 0xc3c8ce : 0x34373c)); m.emissive?.copy(on ? col : new THREE.Color(0)).multiplyScalar(.15); }
      }
    }
    for (const fl of B.floors.values()) {
      const list = equip.filter(e => e.floor === fl.id), al = list.filter(e => sim.get(e.id).status === "alarm").length;
      const f = floorById(fl.id), n = list.filter(V.match).length;
      fl.labelEl.innerHTML = `<b>${fl.id}</b> ${f.name} <span class="n">${n}</span>${al ? ` <span class="a">● ${al}</span>` : ""}`;
    }
    syncBeacons();
    outline.selectedObjects = V.sel ? (B.zones.get(V.sel) ? [B.zones.get(V.sel).floorMesh, B.zones.get(V.sel).vav] : [B.equip.get(V.sel).group]) : [];
    drawChain();
  }
  const cutPlane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0), cutList = [cutPlane];
  function applyCut() {
    for (const fl of B.floors.values()) for (const m of fl.allMats) { const want = V.cut ? cutList : null;
      if ((m.clippingPlanes?.length || 0) !== (want?.length || 0)) { m.clippingPlanes = want; m.needsUpdate = true; } }
  }

  // ---------- loop ----------
  const clock = new THREE.Clock();
  let moving = true;
  function frame() {
    requestAnimationFrame(frame);
    const dt = Math.min(clock.getDelta(), .05), t = clock.elapsedTime;
    moving = false;
    for (const fl of B.floors.values()) {
      if (Math.abs(fl.group.position.y - fl.ty) > .01 || Math.abs(fl.op - fl.top) > .004) moving = true;
      fl.group.position.y += (fl.ty - fl.group.position.y) * Math.min(1, dt * 5);
      fl.op += (fl.top - fl.op) * Math.min(1, dt * 5);
      if (fl.lastOp === undefined || Math.abs(fl.op - fl.lastOp) > .002) {
        fl.lastOp = fl.op;
        for (const m of fl.allMats) {
          const bo = m.userData.baseOpacity ?? 1, bt = m.userData.baseTransparent;
          m.opacity = bo * fl.op; const tr = bt || fl.op < .995;
          if (m.transparent !== tr) { m.transparent = tr; m.needsUpdate = true; }
          m.depthWrite = bt ? m.userData.baseDepthWrite : fl.op > .9;
        }
      }
      fl.group.visible = fl.op > .02;
      fl.label.visible = V.labels && fl.op > .3;
    }
    // CSS2D objects ignore their parents' visibility, so beacons on faded floors are hidden here
    for (const [id, b] of beacons) b.visible = B.floors.get(byId.get(id).floor).op > .3 || id === V.sel;
    for (const q of B.equip.values()) {
      if (!B.floors.get(q.floor).group.visible) continue;
      const s = sim.get(q.id).speed ?? 1;
      for (const [part, axis, speed] of q.spin) part.rotation[axis] += dt * speed * s;
    }
    if (moving && V.sel) drawChain();
    for (const o of chain.children) if (o.material.map) o.material.map.offset.x -= dt * .9;
    if (V.camGoal) {
      const k = Math.min(1, dt * 3.2);
      controls.target.lerp(V.camGoal.t, k); camera.position.lerp(V.camGoal.p, k);
      if (camera.position.distanceTo(V.camGoal.p) < .2) V.camGoal = null;
    }
    controls.update();
    composer.render(); labels.render(scene, camera);
  }
  for (const [id, q] of B.equip) q.id = id;

  function resize() {
    const w = host.clientWidth, h = host.clientHeight; if (!w || !h) return;
    renderer.setSize(w, h); labels.setSize(w, h); composer.setSize(w, h);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    outline.resolution.set(w, h); hoverPass.resolution.set(w, h); if (gtao) gtao.setSize(w * renderer.getPixelRatio(), h * renderer.getPixelRatio());
  }
  new ResizeObserver(resize).observe(host); resize();
  applyEnvironment(); layout(); paint();
  for (const fl of B.floors.values()) fl.group.position.y = fl.ty;
  V.camGoal = null; flyTo(null); camera.position.copy(V.camGoal.p); controls.target.copy(V.camGoal.t); V.camGoal = null;
  frame();

  return {
    set(opts) {
      const prev = { ...V }; Object.assign(V, opts);
      if ("cut" in opts) { V.cut = opts.cut == null ? null : cutPlane; cutPlane.constant = opts.cut ?? 0; }
      if ("mode" in opts || "hours" in opts || "hq" in opts) applyEnvironment();
      if ("cut" in opts) applyCut();
      if ("surroundings" in opts) extras.visible = !!opts.surroundings;  // trees, cars, lights, neighbours
      if (["mode", "floor", "sel", "exploded", "systems", "labels"].some(k => k in opts && opts[k] !== prev[k])) layout();
      paint();
    },
    repaint: paint,
    resetCamera() { layout(); if (!V.floor && !V.sel) flyTo(null); },
    project(id) { const p = anchorWorld(id).project(camera), r = renderer.domElement.getBoundingClientRect();
      return { left: r.left + (p.x + 1) / 2 * r.width, top: r.top + (1 - p.y) / 2 * r.height }; },
    get state() { return V; },
    debug: { B, scene, camera, controls, renderer },
  };
}
