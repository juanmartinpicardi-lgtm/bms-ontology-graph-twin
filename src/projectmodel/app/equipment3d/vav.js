// Parametric VAV terminal: build(payload, viewer) -> {group, parts, paths, update, applyTheme, ...}, like AHU.build.
// Part names match knowledge_model/templates/anchors.yaml. Topology from payload.variant:
//   round inlet (flow cross, butterfly damper) -> box [series fan] [reheat coil] -> discharge duct -> diffuser;
//   zone thermostat on a wall stub. Dual duct: two inlets (cold deck = inlet_duct, hot deck = inlet_duct_2), each
//   with its own flow cross and damper, keyed "flow_cross@hot" etc. (the payload tags DD points with their deck).
const VAV = (() => {
  const { V, MAT, C, box, duct, joint, flow } = Parts;
  const ROOM = new THREE.MeshStandardMaterial({ color: 0xc9ccd1, metalness: 0, roughness: 0.85 });
  const INNER = new THREE.MeshStandardMaterial({ color: 0xa4a8ae, metalness: 0.35, roughness: 0.55, side: THREE.BackSide });

  // Round duct along x, cut away on the front-top quarter (towards the hero camera) so the damper and flow cross
  // inside show. Around the axis, angle 0 is +z and negative angles go up.
  function roundDuct(x0, x1, y, r) {
    const g = new THREE.Group(), len = x1 - x0, mid = -0.5, cut = 1.15;
    for (const [rr, mat] of [[r, MAT.duct], [r - 0.025, INNER]]) {
      const m = Parts.mesh(new THREE.CylinderGeometry(rr, rr, len, 48, 1, true, mid + cut, Math.PI * 2 - 2 * cut), mat);
      m.rotation.z = -Math.PI / 2;
      m.position.set((x0 + x1) / 2, y, 0);
      g.add(m);
    }
    for (const s of [-1, 1]) {  // bright strips on the cut edges show the wall
      const a = mid + s * cut, yy = y - r * Math.sin(a), zz = r * Math.cos(a);
      g.add(box(V(x0, yy - 0.014, zz - 0.014), V(x1, yy + 0.014, zz + 0.014), MAT.trim));
    }
    for (const x of [x0, x1]) {
      const ring = Parts.mesh(new THREE.TorusGeometry(r + 0.012, 0.022, 8, 48), MAT.flange);
      ring.rotation.y = Math.PI / 2;
      ring.position.set(x, y, 0);
      g.add(ring);
    }
    return g;
  }

  // Butterfly damper on a vertical shaft, actuator on top of the duct. open 0 = closed, 1 = fully open.
  function butterfly(r, open = 0.5) {
    const g = new THREE.Group(), leaf = new THREE.Group();
    const disk = Parts.mesh(new THREE.CylinderGeometry(r - 0.03, r - 0.03, 0.016, 40), C.blade);
    disk.rotation.z = Math.PI / 2;  // disk normal along x: closed
    leaf.add(disk);
    leaf.rotation.y = open * Math.PI / 2;
    g.add(leaf);
    g.add(Parts.mesh(new THREE.CylinderGeometry(0.014, 0.014, 2 * r + 0.16, 10), MAT.trim));
    g.add(box(V(-0.11, r + 0.06, -0.09), V(0.11, r + 0.24, 0.09), C.actuator, 0.025));
    g.userData.setOpen = o => { leaf.rotation.y = o * Math.PI / 2; };
    return g;
  }

  // Flow cross: two perforated tubes across the duct section with a hub, impulse tubes out the top.
  function flowCross(r) {
    const g = new THREE.Group(), m = MAT.trim;
    g.add(Parts.mesh(new THREE.CylinderGeometry(0.016, 0.016, 2 * r - 0.04, 10), m));
    g.add(Parts.mesh(new THREE.CylinderGeometry(0.016, 0.016, 2 * r - 0.04, 10), m).rotateX(Math.PI / 2));
    g.add(Parts.mesh(new THREE.SphereGeometry(0.035, 14, 10), m));
    const blue = new THREE.MeshStandardMaterial({ color: 0x2f80d8, roughness: 0.6 });
    for (const dx of [-0.04, 0.04]) g.add(Parts.mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.3, 8), blue).translateX(dx).translateY(r + 0.1));
    return g;
  }

  // Box casing from x0 to x1, front wall cut away (a translucent front for the toggle).
  function casing(x0, x1, ya, yb, d) {
    const g = new THREE.Group(), t = 0.05, zf = d / 2, zb = -d / 2;
    for (const [a, b] of [
      [V(x0, ya, zb), V(x1, ya + t, zf)], [V(x0, yb - t, zb), V(x1, yb, zf)], [V(x0, ya, zb), V(x1, yb, zb + t)],
      [V(x0, ya, zb), V(x0 + t, yb, zf)], [V(x1 - t, ya, zb), V(x1, yb, zf)],
    ]) g.add(box(a, b, MAT.skin, 0.015));
    for (const [a, b] of [
      [V(x0 + t, ya + t, zb + t), V(x1 - t, yb - t, zb + t + 0.02)], [V(x0 + t, ya + t, zb + t), V(x1 - t, ya + t + 0.02, zf - 0.01)],
      [V(x0 + t, yb - t - 0.02, zb + t), V(x1 - t, yb - t, zf - 0.01)],
    ]) { const m = box(a, b, MAT.liner); m.castShadow = false; g.add(m); }
    const e = 0.01;
    for (const [a, b] of [
      [V(x0 - e, yb - t - e, zf - 0.03), V(x1 + e, yb + e, zf + e)], [V(x0 - e, ya - e, zf - 0.03), V(x1 + e, ya + t + e, zf + e)],
      [V(x0 - e, ya, zf - 0.03), V(x0 + t + e, yb, zf + e)], [V(x1 - t - e, ya, zf - 0.03), V(x1 + e, yb, zf + e)],
    ]) g.add(box(a, b, MAT.trim, 0.008));
    g.children.forEach(m => { if (m.position.y > yb - t) m.castShadow = false; });  // keep the inside lit
    const front = box(V(x0, ya, zf - t), V(x1, yb, zf), MAT.glass);
    front.castShadow = false;
    front.visible = false;
    g.add(front);
    return { group: g, front };
  }

  function build(data, viewer) {
    const v = data.variant || {};
    const group = new THREE.Group(), parts = {}, paths = {}, flows = [], water = [];
    let fan = null;
    const add = (name, obj) => { obj.name = name; parts[name] = obj; group.add(obj); return obj; };
    const label = (text, p, cls) => { const l = viewer.label(text, cls); l.position.copy(p); group.add(l); return l; };
    const stream = (key, pts, opts) => { const f = flow(pts, viewer.theme().air[key], opts); f.key = key; flows.push(f); group.add(f.mesh); return f; };
    const navLabel = (text, rel, p) => { const l = label(text, p, rel ? "stream nav" : "stream"); if (rel) l.element.dataset.eq = rel.id; return l; };

    const yc = 2.3, D = 1.3;
    const dd = !!v.dual_duct, r = dd ? 0.3 : 0.36, BH = dd ? 1.6 : 1.1;
    const fanLen = v.fan_powered ? 1.0 : 0, BL = 1.5 + fanLen + (v.reheat ? 0.45 : 0);
    const ya = yc - BH / 2, yb = yc + BH / 2;
    const ahu = (data.relations?.fed_by || []).find(r => r.template === "ahu");
    const plant = (data.relations?.fed_by || []).find(r => r.template !== "ahu");

    // --- inlets: flow cross, then damper, then the box -------------------------------------------------
    const x0 = -2.4, xFlow = -1.75, xDmp = -0.7;
    const decks = dd ? [["cold", yc + 0.42, "inlet_duct", "supply"], ["hot", yc - 0.42, "inlet_duct_2", "return"]]
                     : [[null, yc, "inlet_duct", "supply"]];
    for (const [deck, y, name, air] of decks) {
      add(name, roundDuct(x0, 0, y, r));
      const key = n => deck ? `${n}@${deck}` : n;
      const fc = flowCross(r);
      fc.position.set(xFlow, y, 0);
      add(key("flow_cross"), fc);
      const dm = butterfly(r, 0.55);
      dm.position.set(xDmp, y, 0);
      add(key("damper"), dm);
      stream(air, [V(x0 - 1.2, y, 0), V(0.3, y, 0)], { size: dd ? 0.55 : 0.65, spacing: 0.36, groups: 2, gap: 0.12 }).tag = deck || "primary";
      const what = deck ? `${deck === "cold" ? "Cold" : "Hot"} deck` : "Primary air";
      navLabel(ahu ? `${what} · from ${ahu.label}` : what, ahu, V(x0 - 0.3, y + r + 0.32, 0));
    }
    // aliases so un-decked anchors (and ghosts) resolve on a dual-duct box
    if (dd) for (const n of ["flow_cross", "damper"]) parts[n] = parts[`${n}@cold`];

    // --- box -------------------------------------------------------------------------------------------
    const cs = casing(0, BL, ya, yb, D);
    add("box", cs.group);
    for (const x of [0.25, BL - 0.25]) group.add(Parts.mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.9, 8), MAT.trim).translateX(x).translateY(yb + 0.45).translateZ(-D / 2 + 0.15));
    const ctl = new THREE.Group();
    ctl.add(box(V(-0.22, -0.09, -0.16), V(0.22, 0.09, 0.16), new THREE.MeshStandardMaterial({ color: 0xd3d6da, roughness: 0.5 }), 0.025));
    ctl.add(box(V(-0.14, 0.089, -0.06), V(0.14, 0.095, 0.08), C.screen));
    ctl.position.set(0.4, yb + 0.09, 0.2);
    add("controller", ctl);
    let xIn = 0.15;
    if (v.fan_powered) {
      const fx = 0.2 + fanLen / 2;
      const f = Parts.fan({ r: 0.28, width: 0.4, housing: [0.8, 0.8, 0.7] });
      f.group.position.set(fx, yc, -0.1);
      fan = f;
      add("fan", f.group);
      // plenum inlet on the roof: induced room air drawn in over the fan
      const gr = new THREE.Group();
      gr.add(box(V(-0.38, 0, -0.4), V(0.38, 0.05, 0.4), MAT.frame));
      for (let i = 0; i < 6; i++) gr.add(box(V(-0.34 + i * 0.13, 0.05, -0.36), V(-0.3 + i * 0.13, 0.08, 0.36), MAT.trim));
      gr.position.set(fx, yb, 0);
      group.add(gr);
      stream("return", [V(fx, yb + 1.2, 0.48), V(fx, yb + 0.15, 0.48)], { size: 0.5, spacing: 0.3, groups: 2, gap: 0.11 }).tag = "induced";
      xIn = 0.2 + fanLen;
    }
    if (v.reheat) {
      const k = Parts.coil(BH - 0.2, D - 0.35, { medium: "hot_water", thick: 0.2, pitch: 0.04 });
      const kp = V(BL - 0.3, yc, -0.1);
      k.position.copy(kp);
      add("reheat_coil", k);
      const st = k.userData.stubs.supply.clone().add(kp);
      const vl = Parts.valve(0.5, k.userData.medium);
      vl.rotation.y = Math.PI / 2;
      vl.position.copy(st).add(V(0, 0, -0.2));
      add("reheat_coil.valve", vl);
      // plant connection: hot water pipes down under the box and out towards the viewer, particles while open
      const zOut = 1.7, ends = { supply: st, return: k.userData.stubs.return.clone().add(kp) };
      for (const [side, e] of Object.entries(ends)) {
        const y = ya - 0.35 - (side === "return" ? 0.12 : 0);
        const run = [e.clone(), V(e.x, y, e.z), V(e.x, y, zOut)];
        group.add(Parts.pipeRun(run, "hot_water", 0.035));
        const pr = Parts.particles(side === "supply" ? run.slice().reverse() : run, Parts.MEDIUM.hot_water, { size: 0.02, spacing: 0.1 });
        group.add(pr.mesh);
        water.push(pr);
      }
      navLabel(plant ? `HW · ${plant.label}` : "HW", plant, V(st.x, ya - 0.6, zOut + 0.3));
    }
    stream("supply", [V(xIn, yc, 0.42), V(BL - (v.reheat ? 0.5 : 0.1), yc, 0.42)], { size: 0.55, spacing: 0.32, groups: 2, gap: 0.11 });

    // --- discharge duct, diffuser, zone -----------------------------------------------------------------
    const dw = 0.9, dh = 0.55, dEnd = BL + 1.7, xd = dEnd + 0.3;
    const dis = new THREE.Group();
    add("discharge_duct", dis);
    dis.add(duct(V(BL, yc, 0), V(dEnd, yc, 0), dw, dh));
    dis.add(joint(V(xd, yc, 0), 0.6, dh, dw));
    dis.add(duct(V(xd, yc - dh / 2, 0), V(xd, yc - 0.85, 0), 0.6, dw));
    const dif = new THREE.Group();
    dif.add(box(V(-0.55, -0.03, -0.6), V(0.55, 0.03, 0.6), MAT.trim, 0.01));
    for (const s of [0.42, 0.3, 0.18]) dif.add(box(V(-s, -0.05, -s), V(s, -0.03, s), MAT.frame).translateY(-0.002 * s));
    dif.position.set(xd, yc - 0.88, 0);
    dis.add(dif);
    paths.discharge_duct = { pts: [V(BL, yc, 0), V(dEnd, yc, 0)], off: [dh / 2], size: [dh, dw] };
    stream("supply", [V(BL + 0.15, yc, dw / 2 + 0.02), V(dEnd - 0.1, yc, dw / 2 + 0.02)], { size: 0.6, spacing: 0.36, groups: 2, gap: 0.12 });
    stream("supply", [V(xd, yc - 1.0, 0.65), V(xd, yc - 1.9, 0.65)], { size: 0.6, spacing: 0.3, groups: 2, gap: 0.12 });
    label("Supply Air", V(BL + 1.1, yc + 0.75, dw / 2));

    const wx0 = xd + 0.75, wx1 = wx0 + 1.6, zw = -0.6;
    const wall = box(V(wx0, 0, zw - 0.08), V(wx1, 2.0, zw), ROOM, 0.01);
    wall.castShadow = true;
    group.add(wall);
    const ts = new THREE.Group();
    ts.add(box(V(-0.15, -0.19, 0), V(0.15, 0.19, 0.06), C.sensor, 0.03));
    ts.add(box(V(-0.1, 0.02, 0.059), V(0.1, 0.13, 0.064), C.screen));
    ts.position.set((wx0 + wx1) / 2, 1.25, zw);
    add("zone_sensor", ts);
    label("Zone", V((wx0 + wx1) / 2, 2.25, zw));

    // --- sensors on duct runs (discharge temperature) ------------------------------------------------------
    function anchor(part, a) {
      const path = paths[part];
      if (!path || a == null) {
        const o = parts[part];
        return o ? { p: o.getWorldPosition(V(0, 0, 0)), n: V(0, 1, 0) } : null;
      }
      const [p0, p1] = path.pts, c = p0.clone().lerp(p1, a), n = V(0, 1, 0);
      return { p: c.clone().addScaledVector(n, path.off[0]), n, center: c, path, seg: 0 };
    }
    for (const slot of data.slots || []) {
      const a = slot.anchor;
      if (!paths[a.part] || a.at == null || !(slot.points.length || slot.required)) continue;
      const pts = slot.points.map(id => data.points[id]).filter(Boolean);
      const cls = (pts.length ? pts.map(p => p.cls) : slot.classes).find(c => c && c.endsWith("_Sensor")) || "";
      const kind = cls.includes("Humidity") ? "humidity" : cls.includes("Pressure") ? "pressure" : "temperature";
      const sg = Parts.sensor(kind, { ghost: !pts.length });
      sg.position.copy(anchor(a.part, a.at).p);
      sg.name = `sensor:${slot.role}`;
      group.add(sg);
    }

    // --- ghosts: required parts with no point in the source --------------------------------------------------
    const ghosts = new Set((data.slots || []).filter(s => s.required && !s.points.length).map(s => s.anchor.part));
    for (const name of Object.keys(parts)) {
      if (!ghosts.has(name.split("@")[0])) continue;
      parts[name].traverse(o => { if (o.isMesh) { o.material = C.ghost; o.castShadow = false; } });
    }

    group.updateMatrixWorld(true);
    // Where a pin's dot sits: on the sensor head for a duct anchor, else on the front of the part (its deck's,
    // for a dual-duct damper or flow cross).
    function pinPoint(part, a) {
      if (paths[part] && a != null) return anchor(part, a).p.add(V(0, 0.36, 0));
      const o = parts[a && parts[`${part}@${a}`] ? `${part}@${a}` : part];
      if (!o) return null;
      const b = new THREE.Box3().setFromObject(o), c = b.getCenter(V(0, 0, 0));
      return V(c.x, c.y, b.max.z);
    }

    group.traverse(o => { if (o.isMesh && !o.isInstancedMesh && o.material !== MAT.glass && o.material !== C.ghost) o.castShadow = o.castShadow ?? true; });
    const bounds = new THREE.Box3().setFromObject(group);
    bounds.expandByPoint(V(x0 - 1.4, 0, 0)).expandByPoint(V(x0 - 0.3, yb + 0.9, 0));

    return {
      group, parts, paths, bounds, anchor, pinPoint, ghosts: [...ghosts],
      update: (t, dt) => {
        flows.forEach(f => f.update(t, dt));
        water.forEach(w => w.update(t, dt));
        if (fan) fan.wheel.rotation.z -= dt * 7 * (fan.speed || 0);
      },
      // Move with the simulated state: damper(s), reheat valve and water, terminal fan, air streams by damper %.
      setState: s => {
        const st = s.vav;
        if (!st) return;
        const open = (name, pct) => parts[name]?.userData.setOpen?.(pct / 100);
        if (dd) { open("damper@cold", st.deck.cold.damper); open("damper@hot", st.deck.hot.damper); }
        else open("damper", st.damper);
        parts["reheat_coil.valve"]?.userData.setCommand?.(st.reheat / 100);
        for (const w of water) w.setSpeed(0.5 * st.reheat / 100);
        if (fan) { fan.speed = st.run ? 1 : 0; fan.setStatus(st.run ? "on" : "off"); }
        const pct = { primary: st.damper, cold: st.deck.cold.damper, hot: st.deck.hot.damper, induced: st.run && fan ? 60 : 0 };
        const out = dd ? (st.deck.cold.damper + st.deck.hot.damper) / 2 : st.damper;
        for (const f of flows) {
          const r = 1.4 * (pct[f.tag] ?? out) / 100;
          f.setSpeed(r);
          f.setActive(r > 0.01);
        }
      },
      applyTheme: P => flows.forEach(f => f.setColor(P.air[f.key])),
      setFrontWall: on => { cs.front.visible = on; },
    };
  }

  return { build, casing };
})();
