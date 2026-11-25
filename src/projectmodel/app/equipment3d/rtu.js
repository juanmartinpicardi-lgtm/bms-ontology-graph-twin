// Parametric packaged rooftop unit: build(payload, viewer) -> the model API (see plant.js). Part names match
// anchors.yaml. One casing on a roof curb, cut away at the front, sections in the air's order:
//   outside air hood -> economizer (outside damper, return from below) -> filter -> DX evaporator coil -> supply fan
//   -> heat section (gas tubes or electric elements, glowing with the heat %) -> supply down through the curb;
//   condensing section at the end: compressor, condenser coil, condenser fan on top. Zone sensor on a wall below.
const RTU = (() => {
  const { V, MAT, C, box, flow } = Parts;
  const DECK = new THREE.MeshStandardMaterial({ color: 0x9a9da2, metalness: 0.05, roughness: 0.9 });
  const WALL = new THREE.MeshStandardMaterial({ color: 0xc9ccd1, roughness: 0.85 });

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, navLabel, v } = K;
    const streams = [];
    const stream = (key, pts, opts) => { const f = flow(pts, viewer.theme().air[key], opts); f.key = key; streams.push(f); K.group.add(f.mesh); return f; };
    const yDeck = 1.5, ya = yDeck + 0.35, H = 1.3, yb = ya + H, yc = (ya + yb) / 2, D = 1.5, L = 4.6;

    K.group.add(box(V(-1.6, yDeck - 0.2, -1.4), V(L + 0.8, yDeck, 1.4), DECK, 0.02));
    K.group.add(box(V(0.05, yDeck, -D / 2 + 0.05), V(L - 1.25, ya, D / 2 - 0.05), MAT.frame, 0.01));  // curb
    const cs = VAV.casing(0, L, ya, yb, D);
    add("casing", cs.group);
    // partition between the air side and the condensing section
    K.group.add(box(V(L - 1.3, ya, -D / 2), V(L - 1.25, yb, D / 2 - 0.05), MAT.skin));

    // outside air hood with the economizer's outside damper in its face
    const hood = new THREE.Group();
    const hs = new THREE.Shape();
    hs.moveTo(0, 0); hs.lineTo(0, H * 0.8); hs.lineTo(-0.5, H * 0.8); hs.lineTo(-0.5, H * 0.35); hs.closePath();
    const hg = new THREE.ExtrudeGeometry(hs, { depth: D - 0.2, bevelEnabled: false });
    const hm = Parts.mesh(hg, MAT.skin);
    hm.position.set(0, ya + 0.1, -(D - 0.2) / 2);
    hood.add(hm);
    for (let i = 0; i < 4; i++) hood.add(box(V(-0.48, ya + 0.25 + i * 0.13, -D / 2 + 0.12), V(-0.36, ya + 0.27 + i * 0.13, D / 2 - 0.12), MAT.trim));
    add("outside_air_hood", hood);
    const eco = new THREE.Group();
    add("economizer", eco);
    const oa = Parts.damper(D - 0.3, H * 0.55, { stack: "y", open: 0.4 });
    oa.position.set(0.08, yc + 0.15, 0);
    add("economizer.oa_damper", oa);
    eco.position.set(0.5, yc, 0);
    stream("outside", [V(-1.4, yc + 0.15, 0.2), V(0.4, yc + 0.15, 0.2)], { size: 0.55, spacing: 0.34, groups: 2, gap: 0.12 });
    label("Outside air", V(-1.0, yb + 0.25, 0.3));

    // return and supply ducts down through the curb into the building
    const rg = new THREE.Group(), xr = 0.6, xs = L - 1.85, dw = 0.6;
    rg.add(Parts.duct(V(xr, 0.25, 0), V(xr, yDeck - 0.2, 0), dw, dw));
    add("return_duct", rg);
    K.paths.return_duct = { pts: [V(xr, 0.25, 0), V(xr, ya, 0)], r: dw / 2 };
    const sg = new THREE.Group();
    sg.add(Parts.duct(V(xs, yDeck - 0.2, 0), V(xs, 0.25, 0), dw, dw));
    add("supply_duct", sg);
    K.paths.supply_duct = { pts: [V(xs, ya, 0), V(xs, 0.25, 0)], r: dw / 2 };
    stream("return", [V(xr, 0.3, dw / 2 + 0.05), V(xr, ya + 0.3, dw / 2 + 0.05)], { size: 0.5, spacing: 0.3, groups: 2, gap: 0.11 });
    stream("mixed", [V(0.7, yc, 0.45), V(1.6, yc, 0.45)], { size: 0.5, spacing: 0.3, groups: 2, gap: 0.11 });
    stream("supply", [V(2.0, yc, 0.45), V(xs - 0.1, yc, 0.45)], { size: 0.5, spacing: 0.3, groups: 2, gap: 0.11 });
    stream("supply", [V(xs, ya - 0.1, dw / 2 + 0.05), V(xs, 0.3, dw / 2 + 0.05)], { size: 0.5, spacing: 0.3, groups: 2, gap: 0.11 });
    label("Return air", V(xr - 0.9, 0.9, 0.4));
    label("Supply air", V(xs + 0.9, 0.9, 0.4));

    // filter, evaporator coil
    const flt = Parts.pleatedFilter(H - 0.16, D - 0.16, { depth: 0.1, pitch: 0.06 });
    flt.position.set(1.15, yc, 0);
    add("filter", flt);
    const evap = Parts.coil(H - 0.16, D - 0.3, { medium: "chilled_water", thick: 0.22, pitch: 0.05 });
    evap.position.set(1.55, yc, -0.07);
    add("evaporator_coil", evap);
    label("DX coil", V(1.55, yb + 0.25, 0.3));

    // supply fan (and its drive on the casing front when the source has speed points)
    const f = Parts.fan({ r: 0.38, width: 0.5, housing: [0.95, 0.95, 0.85] });
    f.group.position.set(2.25, yc, -0.2);
    add("supply_fan", f.group);
    if (v.vfd) {
      const d = Parts.vfd();
      d.position.set(2.25, yb + 0.45, -D / 2 + 0.2);
      add("supply_fan.vfd", d);
    } else add("supply_fan.vfd", new THREE.Group());

    // heat section: gas heat exchanger tubes or electric elements, both glow with the heat %
    const glow = new THREE.MeshStandardMaterial({ color: 0x5a2a1e, emissive: 0xff5a1f, emissiveIntensity: 0, metalness: 0.5, roughness: 0.45 });
    const heat = new THREE.Group();
    for (let i = 0; i < 5; i++) {
      const z = -D / 2 + 0.25 + i * (D - 0.5) / 4;
      if (v.heat === "electric") heat.add(Parts.mesh(new THREE.CylinderGeometry(0.016, 0.016, H - 0.25, 10), glow).translateZ(z));
      else {
        const tube = new THREE.CatmullRomCurve3([V(-0.12, -H / 2 + 0.15, z), V(0.12, -H / 2 + 0.25, z), V(0.12, H / 2 - 0.2, z), V(-0.12, H / 2 - 0.15, z)]);
        heat.add(Parts.mesh(new THREE.TubeGeometry(tube, 24, 0.035, 10), glow));
      }
    }
    heat.position.set(xs - 0.45, yc, 0);
    add("heat_section", heat);
    label(v.heat === "electric" ? "Electric heat" : "Gas heat", V(xs - 0.45, yb + 0.25, 0.3));

    // condensing section: compressor inside, condenser coil on the end, fan on top
    const xc = L - 0.65;
    const comp = new THREE.Group();
    const cm = new THREE.MeshStandardMaterial({ color: 0x2b2d31, metalness: 0.5, roughness: 0.4 });
    comp.add(Parts.mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.55, 24), cm));
    comp.add(Parts.mesh(new THREE.SphereGeometry(0.17, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), cm).translateY(0.27));
    comp.position.set(xc - 0.2, ya + 0.35, 0.2);
    add("compressor", comp);
    const cl = Plant.lamp(0.035);
    cl.position.set(xc - 0.2, ya + 0.85, 0.2);
    K.group.add(cl);
    const cond = Parts.coil(H - 0.2, D - 0.2, { medium: "condenser_water", thick: 0.12, pitch: 0.05 });
    cond.position.set(L - 0.1, yc, 0);
    add("condenser_coil", cond);
    const cf = new THREE.Group();
    cf.add(Parts.mesh(new THREE.TorusGeometry(0.5, 0.03, 8, 40), MAT.frame).rotateX(Math.PI / 2));
    for (let i = 0; i < 5; i++) cf.add(Parts.mesh(new THREE.TorusGeometry(0.1 + i * 0.09, 0.006, 6, 32), MAT.trim).rotateX(Math.PI / 2));
    const prop = new THREE.Group();
    for (let i = 0; i < 4; i++) { const g = new THREE.Group(); g.add(box(V(0.05, -0.01, -0.07), V(0.45, 0.01, 0.07), MAT.frame)); g.rotation.y = i * Math.PI / 2; prop.add(g); }
    prop.position.y = -0.06;
    cf.add(prop);
    cf.position.set(xc, yb + 0.03, 0);
    add("condenser_fan", cf);
    label("Condensing section", V(xc, yb + 0.55, 0.3));

    // controls: panel on the casing front, zone sensor on a wall below the roof
    const ctl = Plant.panel(0.5, 0.6, 0.18);
    ctl.position.set(0.55, yb - 0.4, D / 2 + 0.1);
    add("controller", ctl);
    K.group.add(box(V(-1.5, 0, -1.2), V(-0.3, yDeck - 0.2, -1.12), WALL, 0.01));
    const ts = new THREE.Group();
    ts.add(box(V(-0.15, -0.19, 0), V(0.15, 0.19, 0.06), C.sensor, 0.03));
    ts.add(box(V(-0.1, 0.02, 0.059), V(0.1, 0.13, 0.064), C.screen));
    ts.position.set(-0.9, 0.85, -1.12);
    add("zone_sensor", ts);
    label("Zone", V(-0.9, 1.25, -1.0));
    for (const rel of (data.relations?.feeds || []).slice(0, 1)) navLabel(`Feeds ${rel.label}`, rel, V(xs + 0.9, 0.5, 0.4));

    return K.finish({
      front: cs.front,
      pad: [V(-1.6, 0, 0), V(L + 0.8, yb + 0.8, 0)],
      update: (t, dt) => {
        streams.forEach(s => s.update(t, dt));
        f.wheel.rotation.z -= dt * 7 * (f.speed || 0);
        prop.rotation.y -= dt * 10 * (prop.speed || 0);
      },
      setState: s => {
        const a = s.ahu;
        if (!a) return;
        const fs = a.fan.supply;
        f.speed = fs.run ? fs.speed / 100 : 0;
        f.setStatus(fs.run ? "on" : "off");
        oa.userData.setOpen(a.oa / 100);
        const dx = a.cool > 5;
        prop.speed = dx ? 1 : 0;
        cl.userData.set(dx);
        glow.emissiveIntensity = 2.4 * a.heat / 100;
        ctl.userData.lamp.userData.set(a.run);
        for (const st of streams) {
          const r = !a.run ? 0 : st.key === "outside" ? 1.2 * a.oa / 100 : st.key === "return" ? 1.2 * a.ra / 100 : 1.2 * fs.speed / 100;
          st.setSpeed(r);
          st.setActive(r > 0.01);
        }
      },
      applyTheme: P => streams.forEach(st => st.setColor(P.air[st.key])),
    });
  }

  return { build };
})();
