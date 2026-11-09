// Parametric fan coil unit: build(payload, viewer) -> the model API (see plant.js). Part names match anchors.yaml.
//   Horizontal ceiling unit: return grille -> filter -> fan -> coil(s) -> discharge grille; zone thermostat on a wall.
//   4-pipe: a cooling and a heating coil, each with its valve; 2-pipe: one coil, for the valve the source has.
const FCU = (() => {
  const { V, MAT, C, box, flow } = Parts;

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, navLabel, v } = K;
    const yc = 2.4, BH = 0.62, D = 1.1, ya = yc - BH / 2, yb = yc + BH / 2;
    const coils = [v.cooling_coil && ["cooling_coil", "chilled_water"], v.heating_coil && ["heating_coil", "hot_water"]].filter(Boolean);
    const BL = 1.25 + 0.3 * coils.length;
    const streams = [];
    const stream = (key, pts, opts) => { const f = flow(pts, viewer.theme().air[key], opts); f.key = key; streams.push(f); K.group.add(f.mesh); return f; };

    const cs = VAV.casing(0, BL, ya, yb, D);
    add("casing", cs.group);
    for (const x of [0.2, BL - 0.2]) K.group.add(Parts.mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.5, 8), MAT.trim).translateX(x).translateY(yb + 0.25).translateZ(-D / 2 + 0.15));

    // return grille on the inlet end, then a panel filter
    const rg = new THREE.Group();
    rg.add(box(V(-0.06, ya, -D / 2), V(0, yb, D / 2), MAT.frame));
    for (let i = 0; i < 5; i++) rg.add(box(V(-0.1, ya + 0.08 + i * 0.11, -D / 2 + 0.05), V(-0.06, ya + 0.12 + i * 0.11, D / 2 - 0.05), MAT.trim));
    add("return_grille", rg);
    const flt = Parts.pleatedFilter(BH - 0.12, D - 0.12, { depth: 0.08, pitch: 0.05 });
    flt.position.set(0.18, yc, 0);
    add("filter", flt);
    stream("return", [V(-1.4, yc, 0.2), V(0.1, yc, 0.2)], { size: 0.5, spacing: 0.32, groups: 2, gap: 0.11 });
    label("Return air", V(-0.9, yb + 0.3, 0.3));

    // fan
    const f = Parts.fan({ r: 0.2, width: 0.32, housing: [0.52, 0.5, 0.48] });
    f.group.position.set(0.62, yc, -0.18);
    add("fan", f.group);

    // coil(s), each with its valve and pipes down and out towards the viewer
    const water = [];
    coils.forEach(([name, medium], i) => {
      const k = Parts.coil(BH - 0.14, D - 0.3, { medium, thick: 0.14, pitch: 0.04 });
      const kp = V(1.1 + 0.3 * i, yc, -0.1);
      k.position.copy(kp);
      add(name, k);
      const st = k.userData.stubs.supply.clone().add(kp);
      const vl = Parts.valve(0.5, k.userData.medium);
      vl.rotation.y = Math.PI / 2;
      vl.position.copy(st).add(V(0, 0, -0.2));
      add(`${name}.valve`, vl);
      const ends = { supply: st, return: k.userData.stubs.return.clone().add(kp) }, zOut = 1.5 + 0.25 * i;
      for (const [side, e] of Object.entries(ends)) {
        const y = ya - 0.3 - (side === "return" ? 0.1 : 0) - 0.22 * i;
        const run = [e.clone(), V(e.x, y, e.z), V(e.x, y, zOut)];
        K.group.add(Parts.pipeRun(run, medium, 0.03));
        const pr = Parts.particles(side === "supply" ? run.slice().reverse() : run, Parts.MEDIUM[medium], { size: 0.018, spacing: 0.09 });
        K.group.add(pr.mesh);
        water.push({ pr, name });
      }
      navLabel(medium === "hot_water" ? "HW" : "CHW", null, V(st.x + 0.15 * i, ya - 0.55 - 0.22 * i, zOut + 0.25));
    });
    if (v.two_pipe && coils.length === 1) label("2-pipe", V(1.1, yb + 0.3, 0.3));

    // controller on top
    const ctl = new THREE.Group();
    ctl.add(box(V(-0.2, -0.08, -0.14), V(0.2, 0.08, 0.14), new THREE.MeshStandardMaterial({ color: 0xd3d6da, roughness: 0.5 }), 0.025));
    ctl.add(box(V(-0.12, 0.079, -0.05), V(0.12, 0.085, 0.07), C.screen));
    ctl.position.set(0.5, yb + 0.08, 0.2);
    add("controller", ctl);

    // discharge: short duct, then a ceiling grille
    const dEnd = BL + 0.9, dw = 0.8, dh = 0.4;
    const dg = new THREE.Group();
    dg.add(Parts.duct(V(BL, yc, 0), V(dEnd, yc, 0), dw, dh, { capB: true }));
    const gr = new THREE.Group();
    gr.add(box(V(-0.35, -0.03, -0.42), V(0.35, 0.03, 0.42), MAT.trim, 0.01));
    for (let i = 0; i < 5; i++) gr.add(box(V(-0.3 + i * 0.13, -0.06, -0.38), V(-0.26 + i * 0.13, -0.03, 0.38), MAT.frame));
    gr.position.set(dEnd - 0.4, yc - dh / 2 - 0.03, 0);
    dg.add(gr);
    add("discharge_grille", dg);
    stream("supply", [V(0.9, yc, 0.42), V(dEnd - 0.4, yc, 0.42)], { size: 0.5, spacing: 0.3, groups: 2, gap: 0.11 });
    stream("supply", [V(dEnd - 0.4, yc - 0.35, 0.5), V(dEnd - 0.4, yc - 1.3, 0.5)], { size: 0.55, spacing: 0.28, groups: 2, gap: 0.11 });
    label("Supply Air", V(dEnd - 0.3, yb + 0.35, 0.3));

    // zone wall with the thermostat
    const wx0 = dEnd + 0.4, wx1 = wx0 + 1.4, zw = -0.6;
    K.group.add(box(V(wx0, 0, zw - 0.08), V(wx1, 2.0, zw), new THREE.MeshStandardMaterial({ color: 0xc9ccd1, roughness: 0.85 }), 0.01));
    const ts = new THREE.Group();
    ts.add(box(V(-0.15, -0.19, 0), V(0.15, 0.19, 0.06), C.sensor, 0.03));
    ts.add(box(V(-0.1, 0.02, 0.059), V(0.1, 0.13, 0.064), C.screen));
    ts.position.set((wx0 + wx1) / 2, 1.25, zw);
    add("zone_sensor", ts);
    label("Zone", V((wx0 + wx1) / 2, 2.25, zw));

    return K.finish({
      front: cs.front,
      pad: [V(-1.6, 0, 0), V(-0.5, yb + 0.6, 0)],
      update: (t, dt) => {
        streams.forEach(s => s.update(t, dt));
        water.forEach(w => w.pr.update(t, dt));
        f.wheel.rotation.z -= dt * 7 * (f.speed || 0);
      },
      setState: s => {
        const u = s.fcu;
        if (!u) return;
        f.speed = u.run ? 1 : 0;
        f.setStatus(u.run ? "on" : "off");
        const cmd = { cooling_coil: u.cool, heating_coil: u.heat };
        for (const [name] of coils) K.parts[`${name}.valve`].userData.setCommand(cmd[name] / 100);
        water.forEach(w => w.pr.setSpeed(0.5 * cmd[w.name] / 100));
        streams.forEach(st => { st.setSpeed(u.run ? 1.2 : 0); st.setActive(u.run); });
      },
      applyTheme: P => streams.forEach(st => st.setColor(P.air[st.key])),
    });
  }

  return { build };
})();
