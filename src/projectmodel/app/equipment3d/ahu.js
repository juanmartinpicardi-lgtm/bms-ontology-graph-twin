// Parametric AHU: build(payload, viewer) -> {group, parts: {name: Object3D}, paths, update, applyTheme, ...}.
// Part names match knowledge_model/templates/anchors.yaml. Topology from payload.variant:
//   OA inlet -> mixing box <- return duct (over the top, return fan inline) -> relief outlet;
//   filters -> coils -> supply fan -> supply duct -> riser -> branch manifold -> downstream VAVs.
const AHU = (() => {
  const { V, MAT, box, duct, joint, flow } = Parts;

  // Internals drawn as simple blocks for now; E2(b) replaces them with filters, coils, fan and dampers.
  const BLOCK = {
    pre_filter:   new THREE.MeshStandardMaterial({ color: 0xc9a65a, roughness: 0.85, metalness: 0 }),
    bag_filter:   new THREE.MeshStandardMaterial({ color: 0xc7792e, roughness: 0.8, metalness: 0 }),
    cooling_coil: new THREE.MeshStandardMaterial({ color: 0xb9bdc2, roughness: 0.35, metalness: 0.8 }),
    heating_coil: new THREE.MeshStandardMaterial({ color: 0xc9b9ad, roughness: 0.35, metalness: 0.8 }),
    copper:       new THREE.MeshStandardMaterial({ color: 0xb87333, roughness: 0.3, metalness: 0.9 }),
    fan:          new THREE.MeshStandardMaterial({ color: 0x3b3e43, roughness: 0.45, metalness: 0.6 }),
  };

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

    // --- internals (blocks until E2(b)) ------------------------------------------------------------
    const yin = y0 + t + 0.15, yout = top - t - 0.15, zin = zb + t + 0.15, zout = zf - 0.25;
    const slab = (name, x0, x1, mat) => parts[name].add(
      box(V(x0, yin, zin), V(x1, yout, zout), mat, 0.02).translateX(-parts[name].position.x)
        .translateY(-parts[name].position.y));
    if (parts.pre_filter) slab("pre_filter", at.pre_filter[0] + 0.25, at.pre_filter[0] + 0.45, BLOCK.pre_filter);
    if (parts.bag_filter) slab("bag_filter", at.bag_filter[0] + 0.2, at.bag_filter[1] - 0.25, BLOCK.bag_filter);
    for (const c of ["cooling_coil", "heating_coil"]) {
      if (!parts[c]) continue;
      const [a, b] = at[c], x = (a + b) / 2;
      slab(c, x - 0.18, x + 0.18, BLOCK[c]);
      // valve body on the coil's pipe stub, outside the back wall
      const valve = new THREE.Group();
      valve.add(box(V(-0.12, -0.12, -0.12), V(0.12, 0.12, 0.12), BLOCK.copper, 0.03));
      valve.add(box(V(-0.08, 0.12, -0.08), V(0.08, 0.36, 0.08), MAT.frame, 0.02));
      valve.position.set(x + 0.25, y0 + 0.75, zf - 0.45);
      add(`${c}.valve`, valve);
    }
    {
      const [a, b] = at.supply_fan, x = (a + b) / 2, yc = y0 + H / 2;
      const fan = parts.supply_fan;
      const housing = box(V(x - 0.9, yc - 0.95, zin + 0.05), V(x + 0.6, yc + 0.95, zout - 0.1), BLOCK.fan, 0.04);
      fan.add(housing.translateX(-fan.position.x).translateY(-fan.position.y));
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.72, 0.72, 0.3, 40), MAT.trim);
      wheel.rotation.x = Math.PI / 2;
      wheel.position.set(x - 0.15 - fan.position.x, yc - fan.position.y, zout - 0.05);
      wheel.castShadow = true;
      fan.add(wheel);
      marker("supply_fan.vfd", V(b - 0.3, y0 + 0.5, zf - 0.4));
    }
    const mx = (at.mixing_box[0] + at.mixing_box[1]) / 2;
    marker("mixing_box.oa_damper", V(t + 0.1, y0 + 1.1, 0));
    marker("controller", V(0.6, top + 0.3, zf - 0.5));

    // --- ductwork ------------------------------------------------------------------------------------
    const yOA = y0 + 1.1, zFace = 0.78;
    // outside air inlet, left
    add("outside_air_inlet", duct(V(-3.2, yOA, 0), V(0, yOA, 0), 1.5, 1.2));
    paths.outside_air_inlet = [V(-3.2, yOA, 0), V(0, yOA, 0)];
    stream("outside", [V(-4.6, yOA, zFace), V(-0.25, yOA, zFace)]);
    label("Fresh Air", V(-4.0, yOA + 0.95, zFace));

    // return duct over the top, into the mixing box roof
    const yR = top + 1.75, rx = v.mixing_box ? mx - 0.4 : null;
    const retEnd = L - 0.2;
    if (v.mixing_box) {
      const ret = new THREE.Group();
      add("return_duct", ret);
      ret.add(duct(V(rx, top, 0), V(rx, yR - 0.5, 0), 1.2, 1.5, { flanges: true }));
      ret.add(joint(V(rx, yR, 0), 1.2, 1.0, 1.5));
      let x0 = rx + 0.6;
      if (v.return_fan) {
        const fx = L * 0.62, rf = new THREE.Group();
        rf.add(box(V(-0.75, -0.72, -0.95), V(0.75, 0.72, 0.95), MAT.skin, 0.05));
        rf.add(box(V(-0.77, -0.6, 0.6), V(0.77, 0.6, 0.97), MAT.trim, 0.03));
        rf.position.set(fx, yR, 0);
        add("return_fan", rf);
        marker("return_fan.vfd", V(fx + 0.4, yR - 0.5, 1.0));
        ret.add(duct(V(x0, yR, 0), V(fx - 0.75, yR, 0), 1.5, 1.0));
        x0 = fx + 0.75;
      }
      ret.add(duct(V(x0, yR, 0), V(retEnd, yR, 0), 1.5, 1.0));
      paths.return_duct = [V(retEnd, yR, 0), V(rx, yR, 0), V(rx, top, 0)];
      stream("return", [V(retEnd + 1.1, yR, zFace), V(rx + 0.5, yR, zFace)]);
      stream("return", [V(rx, yR - 0.55, 0.78), V(rx, top + 0.25, 0.78)], { spacing: 0.3, groups: 2 });
      label("Return Air", V(retEnd + 0.7, yR + 0.85, zFace));
      marker("mixing_box.ra_damper", V(rx, top - 0.2, 0));
      marker("building_ref", V(retEnd + 0.3, yR + 0.9, 0));
      if (v.relief_outlet) {
        const xr = rx + 2.0, yt = yR + 1.9;
        const rel = new THREE.Group();
        add("relief_outlet", rel);
        rel.add(duct(V(xr, yR + 0.5, 0), V(xr, yt, 0), 1.0, 1.2));
        marker("relief_outlet.damper", V(xr, yt - 0.35, 0));
        stream("return", [V(xr, yR + 0.6, 0.64), V(xr, yt + 1.1, 0.64)], { spacing: 0.3, groups: 2 });
        label("Relief Air", V(xr + 0.95, yt + 0.5, 0.6));
      }
    }

    // inside the unit: mixed air up to the cooling coil, supply air after it
    const yIn = y0 + H * 0.55, zIn = 0.45, xc = at.cooling_coil[0];
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
    paths.supply_duct = [V(L, yS, 0), V(sx1, yS, 0), V(rxc, yS, 0), V(rxc, riserTop, 0)];
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

    group.traverse(o => { if (o.isMesh && !o.isInstancedMesh && o.material !== MAT.glass) o.castShadow = o.castShadow ?? true; });
    const bounds = new THREE.Box3().setFromObject(group);
    bounds.expandByPoint(V(-4.8, 0, 0)).expandByPoint(V(bx1 + 3.9, 0, 0));

    return {
      group, parts, paths, bounds,
      update: (t, dt) => flows.forEach(f => f.update(t, dt)),
      applyTheme: P => flows.forEach(f => f.setColor(P.air[f.key])),
      setFrontWall: on => { front.visible = on; },
    };
  }

  return { build };
})();
