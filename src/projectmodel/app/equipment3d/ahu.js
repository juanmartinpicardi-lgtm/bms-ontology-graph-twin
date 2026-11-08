// Parametric AHU: build(payload, viewer) -> {group, parts: {name: Object3D}, paths, update, applyTheme, ...}.
// Part names match knowledge_model/templates/anchors.yaml. Topology from payload.variant:
//   OA inlet -> mixing box <- return duct (over the top, return fan inline) -> relief outlet;
//   filters -> coils -> supply fan -> supply duct -> riser -> branch manifold -> downstream VAVs.
const AHU = (() => {
  const { V, MAT, box, duct, joint, flow } = Parts;

  // Sensor model from the point class: the first *_Sensor class among a slot's points (or its first class).
  function sensorKind(classes) {
    const c = classes.find(c => c && c.endsWith("_Sensor"));
    if (!c) return null;
    for (const [k, word] of [["humidity", "Humidity"], ["pressure", "Pressure"], ["flow", "Flow"], ["temperature", "Temperature"]])
      if (c.includes(word)) return k;
    return null;  // frequency, power, speed: read on the VFD, no sensor head
  }

  function build(data, viewer) {
    const v = data.variant || {};
    const group = new THREE.Group(), parts = {}, paths = {}, flows = [], labels = [];
    const add = (name, obj) => { obj.name = name; parts[name] = obj; group.add(obj); return obj; };
    const marker = (name, p) => { const o = new THREE.Object3D(); o.position.copy(p); return add(name, o); };
    const label = (text, p, cls) => { const l = viewer.label(text, cls); l.position.copy(p); group.add(l); labels.push(l); return l; };
    const stream = (key, pts, opts) => { const f = flow(pts, viewer.theme().air[key], opts); f.key = key; flows.push(f); group.add(f.mesh); return f; };

    // --- casing ----------------------------------------------------------------------------------
    const y0 = 0.3, H = 2.6, D = 2.4, t = 0.08, zf = D / 2, zb = -D / 2;
    const sections = [
      ["mixing_box", v.mixing_box ? 2.3 : 1.0],
      ["pre_filter", 0.75],
      ["bag_filter", 1.5],
      ["cooling_coil", 1.0],
      ...(v.heating_coil ? [["heating_coil", 0.8]] : []),
      ["supply_fan", 2.6],
      ["discharge", 0.9],
    ];
    const at = {};
    let L = 0;
    for (const [name, w] of sections) { at[name] = [L, L + w]; L += w; }
    const casing = new THREE.Group();
    add("casing", casing);
    const top = y0 + H;
    // plinth
    casing.add(box(V(0.12, 0, zb + 0.12), V(L - 0.12, y0, zf - 0.12), MAT.frame, 0.02));
    // skin (outer walls), front wall removed
    for (const [a, b] of [
      [V(0, y0, zb), V(L, y0 + t, zf)],          // floor
      [V(0, top - t, zb), V(L, top, zf)],        // roof
      [V(0, y0, zb), V(L, top, zb + t)],         // back
      [V(0, y0, zb), V(t, top, zf)],             // left end
      [V(L - t, y0, zb), V(L, top, zf)],         // right end
    ]) casing.add(box(a, b, MAT.skin, 0.02));
    // Cut-away illustration: the roof and its liner don't shadow the inside, so the components stay lit.
    casing.children.forEach(m => { if (m.position.y > top - t) m.castShadow = false; });
    // liner: the inside faces, lighter than the skin
    const li = 0.02;
    for (const [a, b] of [
      [V(t, y0 + t, zb + t), V(L - t, top - t, zb + t + li)],
      [V(t, y0 + t, zb + t), V(L - t, y0 + t + li, zf - 0.01)],
      [V(t, top - t - li, zb + t), V(L - t, top - t, zf - 0.01)],
      [V(t, y0 + t, zb + t), V(t + li, top - t, zf - 0.01)],
      [V(L - t - li, y0 + t, zb + t), V(L - t, top - t, zf - 0.01)],
    ]) { const m = box(a, b, MAT.liner); m.castShadow = false; casing.add(m); }
    // bright trims on the cut edges show the wall thickness
    const e = 0.012;
    for (const [a, b] of [
      [V(-e, top - t - e, zf - 0.03), V(L + e, top + e, zf + e)],
      [V(-e, y0 - e, zf - 0.03), V(L + e, y0 + t + e, zf + e)],
      [V(-e, y0, zf - 0.03), V(t + e, top, zf + e)],
      [V(L - t - e, y0, zf - 0.03), V(L + e, top, zf + e)],
    ]) casing.add(box(a, b, MAT.trim, 0.01));
    // section frames inside, and roof seams outside, at every section boundary
    for (const [, [x]] of Object.entries(at).slice(1)) {
      casing.add(box(V(x - 0.04, y0 + t, zb + t), V(x + 0.04, top - t, zb + t + 0.14), MAT.frame));
      casing.add(box(V(x - 0.04, top - t - 0.12, zb + t), V(x + 0.04, top - t, zf - 0.02), MAT.frame));
      casing.add(box(V(x - 0.04, y0 + t, zb + t), V(x + 0.04, y0 + t + 0.12, zf - 0.02), MAT.frame));
      casing.add(box(V(x - 0.014, top, zb + 0.02), V(x + 0.014, top + 0.008, zf - 0.02), MAT.seam));
    }
    // front wall: hidden (cut away); the toggle shows it translucent
    const front = box(V(0, y0, zf - t), V(L, top, zf), MAT.glass);
    front.castShadow = false;
    front.visible = false;
    casing.add(front);
    for (const [name, [a, b]] of Object.entries(at)) if (name !== "discharge") marker(name, V((a + b) / 2, y0 + H / 2, 0));

    // --- internals ----------------------------------------------------------------------------------
    const yc = y0 + H / 2, hIn = H - 2 * t - 0.12, dIn = D - 2 * t - 0.1, zc = (zb + t + zf) / 2 - 0.03;
    const mid = name => (at[name][0] + at[name][1]) / 2;
    const place = (name, obj, p) => { obj.position.copy(p).sub(parts[name].position); parts[name].add(obj); return obj; };
    const slotPoints = role => (data.slots || []).find(s => s.role === role)?.points || [];
    const spinners = [];

    place("pre_filter", Parts.pleatedFilter(hIn, dIn), V(mid("pre_filter"), yc, zc));
    place("bag_filter", Parts.bagFilter(hIn, dIn, { length: at.bag_filter[1] - at.bag_filter[0] - 0.4 }),
          V(at.bag_filter[0] + 0.15, yc, zc));
    for (const [c, medium] of [["cooling_coil", "chilled_water"], ["heating_coil", "hot_water"]]) {
      if (!parts[c]) continue;
      const k = Parts.coil(hIn - 0.1, dIn - 0.2, { medium });
      const kp = V(mid(c), yc, zc - 0.1);
      place(c, k, kp);
      // valve + actuator on the supply stub, where the pipe leaves the cut-away front
      const st = k.userData.stubs.supply.clone().add(kp);
      const vl = Parts.valve(0.5, k.userData.medium);
      vl.rotation.y = Math.PI / 2;
      vl.position.copy(st).add(V(0, 0, -0.2));
      add(`${c}.valve`, vl);
    }
    {
      const x = mid("supply_fan") - 0.25;
      const f = Parts.fan({ r: 0.66, width: 0.9, housing: [1.75, 1.9, 1.5] });
      place("supply_fan", f.group, V(x, yc + 0.02, zc - 0.2));
      f.setStatus("on");  // static until the simulator (E4) drives it from Fan_Status
      spinners.push(f.wheel);
      place("supply_fan", Parts.motor(), V(at.supply_fan[1] - 0.42, y0 + t + 0.3, zc + 0.25));
      const d = Parts.vfd();
      d.position.set(mid("discharge"), y0 + 1.25, zb + t + 0.11);
      add("supply_fan.vfd", d);
    }
    if (v.mixing_box) {
      const oa = Parts.damper(1.5, 1.2, { stack: "y", open: 0.6 });
      oa.position.set(t + 0.1, y0 + 1.1, 0);
      add("mixing_box.oa_damper", oa);
    }
    const ctl = new THREE.Group();
    ctl.add(box(V(-0.3, -0.35, -0.1), V(0.3, 0.35, 0.1), new THREE.MeshStandardMaterial({ color: 0xd3d6da, roughness: 0.5 }), 0.03));
    ctl.add(box(V(-0.2, 0.12, 0.098), V(0.2, 0.26, 0.104), Parts.C.screen));
    ctl.position.set(mid("mixing_box") + 0.6, y0 + 1.5, zb + t + 0.12);
    add("controller", ctl);

    // --- ductwork ------------------------------------------------------------------------------------
    const yOA = y0 + 1.1, zFace = 0.78;
    // outside air inlet, left
    add("outside_air_inlet", duct(V(-3.2, yOA, 0), V(0, yOA, 0), 1.5, 1.2));
    paths.outside_air_inlet = { pts: [V(-3.2, yOA, 0), V(0, yOA, 0)], off: [0.6], size: [1.2, 1.5] };
    paths.mixing_box = { pts: [V(at.mixing_box[0], top, 0), V(at.mixing_box[1], top, 0)], off: [0] };
    stream("outside", [V(-4.6, yOA, zFace), V(-0.25, yOA, zFace)]);
    label("Fresh Air", V(-4.0, yOA + 0.95, zFace));

    // return duct over the top, into the mixing box roof
    const yR = top + 1.75, rx = v.mixing_box ? mid("mixing_box") - 0.4 : null;
    const retEnd = L - 0.2;
    if (v.mixing_box) {
      const ret = new THREE.Group();
      add("return_duct", ret);
      ret.add(duct(V(rx, top, 0), V(rx, yR - 0.5, 0), 1.2, 1.5, { flanges: true }));
      ret.add(joint(V(rx, yR, 0), 1.2, 1.0, 1.5));
      let x0 = rx + 0.6;
      if (v.return_fan) {
        const fx = L * 0.62, rf = Parts.fan({ r: 0.5, width: 0.7, housing: [1.5, 1.44, 1.9] });
        rf.group.position.set(fx, yR, 0);
        rf.setStatus("on");
        spinners.push(rf.wheel);
        add("return_fan", rf.group);
        const d = Parts.vfd();
        d.position.set(fx + 1.25, yR - 0.05, 0.75 + 0.1);
        add("return_fan.vfd", d);
        ret.add(duct(V(x0, yR, 0), V(fx - 0.75, yR, 0), 1.5, 1.0));
        x0 = fx + 0.75;
      }
      ret.add(duct(V(x0, yR, 0), V(retEnd, yR, 0), 1.5, 1.0));
      paths.return_duct = { pts: [V(retEnd, yR, 0), V(rx, yR, 0), V(rx, top, 0)], off: [0.5, 0.75] };
      stream("return", [V(retEnd + 1.1, yR, zFace), V(rx + 0.5, yR, zFace)]);
      stream("return", [V(rx, yR - 0.55, 0.78), V(rx, top + 0.25, 0.78)], { spacing: 0.3, groups: 2 });
      label("Return Air", V(retEnd + 0.7, yR + 0.85, zFace));
      const ra = Parts.damper(1.5, 1.1, { stack: "x", open: 0.4 });
      ra.position.set(rx, top - t - 0.08, 0);
      add("mixing_box.ra_damper", ra);
      marker("building_ref", V(retEnd - 0.5, yR + 0.5, 0));
      if (v.relief_outlet) {
        const xr = rx + 2.0, yt = yR + 1.9;
        const rel = new THREE.Group();
        add("relief_outlet", rel);
        rel.add(duct(V(xr, yR + 0.5, 0), V(xr, yt, 0), 1.0, 1.2));
        const rd = Parts.damper(1.2, 0.9, { stack: "x", open: 0.3 });
        rd.position.set(xr, yt - 0.35, 0);
        add("relief_outlet.damper", rd);
        stream("return", [V(xr, yR + 0.6, 0.64), V(xr, yt + 1.1, 0.64)], { spacing: 0.3, groups: 2 });
        label("Relief Air", V(xr + 0.95, yt + 0.5, 0.6));
      }
    }

    // inside the unit: mixed air up to the cooling coil, supply air after it
    const yIn = y0 + H * 0.55, zIn = 0.8, xc = at.cooling_coil[0];
    stream("mixed", [V(0.35, yIn, zIn), V(xc - 0.1, yIn, zIn)], { size: 0.85 });
    stream("supply", [V(at.cooling_coil[1] + 0.1, yIn, zIn), V(L - 0.2, yIn, zIn)], { size: 0.85 });

    // supply duct, riser and branch manifold to the downstream VAVs
    const yS = y0 + 1.5, sx1 = L + 1.9, rxc = sx1 + 0.6;
    const feeds = data.relations?.feeds || [];
    const n = Math.min(6, Math.max(1, feeds.length));
    const lvl = i => y0 + 0.75 + i * 0.85;
    const riserTop = Math.max(yS + 0.9, lvl(n - 1) + 0.6);
    const sup = new THREE.Group();
    add("supply_duct", sup);
    sup.add(duct(V(L, yS, 0), V(sx1, yS, 0), 1.4, 1.1));
    sup.add(duct(V(rxc, y0, 0), V(rxc, riserTop, 0), 1.2, 1.4, { capA: true, capB: true }));
    paths.supply_duct = { pts: [V(L, yS, 0), V(sx1, yS, 0)], off: [0.55], size: [1.1, 1.4] };
    stream("supply", [V(L + 0.2, yS, 0.72), V(sx1 - 0.15, yS, 0.72)]);
    stream("supply", [V(rxc, y0 + 0.3, 0.72), V(rxc, riserTop - 0.25, 0.72)], { spacing: 0.35, groups: 2 });
    label("Supply Air", V(L + 0.9, yS - 1.2, 0.72));
    const bx0 = rxc + 0.6, bx1 = bx0 + 1.7;
    for (let i = 0; i < n; i++) {
      const y = lvl(i), f = feeds[i];
      sup.add(duct(V(bx0, y, 0), V(bx1, y, 0), 0.8, 0.5));
      const vav = box(V(bx1, y - 0.32, -0.5), V(bx1 + 0.9, y + 0.32, 0.5), MAT.duct, 0.03);
      sup.add(vav);
      sup.add(duct(V(bx1 + 0.9, y, 0), V(bx1 + 1.4, y, 0), 0.7, 0.4));
      stream("supply", [V(bx0 + 0.1, y, 0.42), V(bx1 - 0.1, y, 0.42)], { size: 0.6, spacing: 0.4, groups: 2, gap: 0.12 });
      stream("supply", [V(bx1 + 1.55, y, 0), V(bx1 + 2.5, y, 0)], { size: 0.8, spacing: 0.3, groups: 3 });
      label(f ? f.label.split("/").pop() : "VAV", V(bx1 + 3.1, y, 0), "stream vav");
    }

    // --- anchors and sensors ------------------------------------------------------------------------------
    // anchor(part, at) -> {p, n}: the mounting point on the part's surface and the outward normal. Along a duct
    // `at` is 0-1 of its centreline; sensors sit on top of horizontal runs and on the front of vertical ones.
    // Parts inside the casing mount on the roof above them.
    function anchor(part, a) {
      const path = paths[part];
      if (path && a != null) {
        const pts = path.pts, lens = pts.slice(1).map((q, i) => q.distanceTo(pts[i]));
        let s = a * lens.reduce((x, y) => x + y, 0), i = 0;
        while (i < lens.length - 1 && s > lens[i]) s -= lens[i++];
        const d = pts[i + 1].clone().sub(pts[i]).normalize(), c = pts[i].clone().addScaledVector(d, s);
        const n = Math.abs(d.y) > 0.5 ? V(0, 0, 1) : V(0, 1, 0);
        return { p: c.addScaledVector(n, path.off[i]), n, center: pts[i].clone().addScaledVector(d, s), path, seg: i };
      }
      const o = parts[part];
      if (!o) return null;
      const p = o.getWorldPosition(V(0, 0, 0));
      if (p.x > 0 && p.x < L && p.y < top) return { p: V(p.x, top, Math.min(p.z, 0.5)), n: V(0, 1, 0) };
      return { p, n: V(0, 1, 0) };
    }
    group.updateMatrixWorld(true);
    const mounted = new Map(), sensors = [];
    for (const slot of data.slots || []) {
      const pts = slot.points.map(id => data.points[id]).filter(Boolean);
      const kind = sensorKind(pts.length ? pts.map(p => p.cls) : slot.required ? slot.classes : []);
      if (!kind) continue;
      const key = `${slot.anchor.part}@${slot.anchor.at ?? ""}`;
      if (mounted.has(key)) continue;
      const a = anchor(slot.anchor.part, slot.anchor.at);
      if (!a) continue;
      const ghost = !pts.length;
      const sg = Parts.sensor(kind, { ghost });
      sg.position.copy(a.p);
      sg.quaternion.setFromUnitVectors(V(0, 1, 0), a.n);
      sg.name = `sensor:${slot.role}`;
      group.add(sg);
      if (kind === "flow" && a.center && a.path.size) {
        const fs = Parts.flowStation(a.path.size[0] - 0.1, a.path.size[1] - 0.1);
        fs.position.copy(a.center);
        group.add(fs);
      }
      mounted.set(key, sg);
      sensors.push({ role: slot.role, kind, ghost, object: sg });
    }

    group.traverse(o => { if (o.isMesh && !o.isInstancedMesh && o.material !== MAT.glass) o.castShadow = o.castShadow ?? true; });
    const bounds = new THREE.Box3().setFromObject(group);
    bounds.expandByPoint(V(-4.8, 0, 0)).expandByPoint(V(bx1 + 3.9, 0, 0));

    return {
      group, parts, paths, bounds, anchor, sensors,
      update: (t, dt) => {
        flows.forEach(f => f.update(t, dt));
        for (const w of spinners) w.rotation.z -= dt * 4.5;  // nominal speed until E4 drives it
      },
      applyTheme: P => flows.forEach(f => f.setColor(P.air[f.key])),
      setFrontWall: on => { front.visible = on; },
    };
  }

  return { build };
})();
