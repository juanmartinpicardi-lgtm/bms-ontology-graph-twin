// Parametric chiller: build(payload, viewer) -> the model API (see plant.js). Part names match anchors.yaml.
//   water-cooled: shell-and-tube evaporator (front, low) and condenser (behind, higher), cut away to show the tube
//   bundles; compressor and motor on top; CHW nozzles on the left end, CW nozzles on the right end.
//   air-cooled (no condenser-water point): the condenser is a finned coil deck with fans.
const Chiller = (() => {
  const { V, MAT, C, box } = Parts;

  // Tube bundle inside a shell along x (instanced tubes), for the cut-away.
  function bundle(x0, x1, y, z, r) {
    const pos = [];
    for (let a = -r; a <= r; a += 0.085) for (let b = -r; b <= r; b += 0.085) if (a * a + b * b < r * r) pos.push([a, b]);
    const tube = new THREE.CylinderGeometry(0.018, 0.018, x1 - x0, 8);
    const inst = new THREE.InstancedMesh(tube, C.copper, pos.length), m = new THREE.Matrix4();
    const q = new THREE.Quaternion().setFromAxisAngle(V(0, 0, 1), Math.PI / 2);
    pos.forEach(([a, b], i) => inst.setMatrixAt(i, m.compose(V((x0 + x1) / 2, y + a, z + b), q, V(1, 1, 1))));
    return inst;
  }

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, navLabel, pipe, onPipe, sib, v } = K;
    const water = !v.air_cooled, X0 = -1.8, X1 = 1.8;
    const E = { y: 0.75, z: 0.35, r: 0.46 }, Cd = { y: 1.2, z: -0.65, r: 0.42 };

    // skid and saddles
    K.group.add(box(V(X0 - 0.1, 0, -1.25), V(X1 + 0.1, 0.12, 0.95), MAT.frame, 0.02));
    for (const x of [X0 + 0.45, X1 - 0.45]) {
      K.group.add(box(V(x - 0.12, 0.12, E.z - 0.42), V(x + 0.12, E.y - 0.3, E.z + 0.42), MAT.frame));
      if (water) K.group.add(box(V(x - 0.12, 0.12, Cd.z - 0.38), V(x + 0.12, Cd.y - 0.3, Cd.z + 0.38), MAT.frame));
    }

    // evaporator
    const ev = new THREE.Group();
    ev.add(Plant.shell(X0, X1, E.y, E.z, E.r, MAT.skin, { cut: 0.72 }));
    ev.add(bundle(X0 + 0.05, X1 - 0.05, E.y, E.z, E.r - 0.1));
    for (const [x, s] of [[X0, -1], [X1, 1]]) ev.add(Plant.dish(x, E.y, E.z, E.r, s, MAT.duct));
    add("evaporator", ev);
    label("Evaporator", V(0, E.y - E.r - 0.25, E.z + E.r + 0.2));

    // condenser
    if (water) {
      const cd = new THREE.Group();
      cd.add(Plant.shell(X0, X1, Cd.y, Cd.z, Cd.r, MAT.skin, { cut: 0.6 }));
      cd.add(bundle(X0 + 0.05, X1 - 0.05, Cd.y, Cd.z, Cd.r - 0.1));
      for (const [x, s] of [[X0, -1], [X1, 1]]) cd.add(Plant.dish(x, Cd.y, Cd.z, Cd.r, s, MAT.duct));
      add("condenser", cd);
    } else {
      const cd = new THREE.Group(), y0 = 1.35, y1 = 2.35, z0 = -1.25, z1 = -0.1;
      for (const z of [z0, z1 - 0.12]) cd.add(box(V(X0, y0, z), V(X1, y1, z + 0.12), C.fin));
      cd.add(box(V(X0, y1, z0), V(X1, y1 + 0.06, z1), MAT.skin));
      for (const x of [-1.2, 0, 1.2]) {
        const f = new THREE.Group();
        f.add(Parts.mesh(new THREE.TorusGeometry(0.45, 0.04, 8, 40), MAT.trim).rotateX(Math.PI / 2));
        const blades = new THREE.Group();
        for (let i = 0; i < 4; i++) blades.add(box(V(0, -0.01, -0.06), V(0.42, 0.01, 0.06), C.blade).rotateY(i * Math.PI / 2));
        f.add(blades);
        f.position.set(x, y1 + 0.1, (z0 + z1) / 2);
        f.userData.blades = blades;
        cd.add(f);
        K.movers.push((t, dt) => { blades.rotation.y += dt * 9 * (K.fanSpeed || 0); });
      }
      add("condenser", cd);
    }
    label(water ? "Condenser" : "Air-cooled condenser", water ? V(X1 - 0.3, Cd.y + Cd.r + 0.3, Cd.z) : V(0, 2.7, -0.7));

    // compressor and motor on top, suction from the evaporator, discharge to the condenser
    const yc = water ? 2.1 : 1.6, zc = water ? -0.15 : E.z;
    const cp = new THREE.Group();
    cp.add(Plant.shell(-0.9, 0.2, yc, zc, 0.33, new THREE.MeshStandardMaterial({ color: 0x3d6f9e, metalness: 0.5, roughness: 0.4 })));
    cp.add(Plant.dish(-0.9, yc, zc, 0.33, -1, new THREE.MeshStandardMaterial({ color: 0x3d6f9e, metalness: 0.5, roughness: 0.4 })));
    const mot = Parts.motor(0.9, 0.28);
    mot.rotation.y = Math.PI / 2;
    mot.position.set(0.75, yc, zc);
    cp.add(mot);
    const coupling = new THREE.Group();
    coupling.add(Parts.mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.08, 24), MAT.trim));
    for (let i = 0; i < 4; i++) coupling.add(box(V(0.1, -0.05, -0.02), V(0.14, 0.05, 0.02), MAT.frame).rotateY(i * Math.PI / 2));
    coupling.rotation.z = Math.PI / 2;
    coupling.position.set(0.25, yc, zc);
    cp.add(coupling);
    K.movers.push((t, dt) => { coupling.rotation.y += dt * 14 * (K.running ? 1 : 0); });
    add("compressor", cp);
    const gas = new THREE.MeshStandardMaterial({ color: 0x9aa0a8, metalness: 0.6, roughness: 0.4 });
    const tube = (pts, r) => K.group.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 24, r, 12), gas));
    tube([V(-0.5, E.y + E.r - 0.05, E.z), V(-0.6, yc - 0.45, E.z), V(-0.6, yc - 0.2, zc)], 0.11);
    if (water) tube([V(-0.2, yc + 0.2, zc), V(-0.1, yc + 0.5, zc - 0.3), V(0.2, Cd.y + Cd.r - 0.05, Cd.z)], 0.09);
    label("Compressor", V(-0.35, yc + 0.6, zc));

    // control panel at the front right
    const pn = Plant.panel(0.6, 0.85, 0.25);
    pn.position.set(X1 + 0.55, 0.65, 0.7);
    K.group.add(box(V(X1 + 0.35, 0, 0.55), V(X1 + 0.75, 0.22, 0.85), MAT.frame));
    add("control_panel", pn);

    // pipe stubs: CHW on the left end (leaving on top), CW on the right end
    const xl = X0 - 0.16, xr = X1 + 0.16, top = 3.1;
    const chwPump = sib(/CHW|PCH|SCH/i), cwPump = sib(/^C(ond)?W|CWP/i);
    const flows = {
      chw: [pipe("chw_leaving_pipe", [V(xl, E.y + 0.2, E.z), V(-2.55, E.y + 0.2, E.z), V(-2.55, top, E.z)], "chilled_water"),
            pipe("chw_entering_pipe", [V(xl, E.y - 0.22, E.z), V(-3.25, E.y - 0.22, E.z), V(-3.25, top, E.z)], "chilled_water", { into: true })],
      cw: [],
    };
    navLabel("CHW supply · to building", null, V(-2.55, top + 0.3, E.z));
    navLabel(chwPump ? `CHW return · ${chwPump.label}` : "CHW return", chwPump, V(-3.4, top + 0.65, E.z));
    if (water) {
      flows.cw.push(pipe("cw_entering_pipe", [V(xr, Cd.y - 0.2, Cd.z), V(3.25, Cd.y - 0.2, Cd.z), V(3.25, top, Cd.z)], "condenser_water", { into: true }),
                    pipe("cw_leaving_pipe", [V(xr, Cd.y + 0.2, Cd.z), V(2.6, Cd.y + 0.2, Cd.z), V(2.6, top, Cd.z)], "condenser_water"));
      navLabel(cwPump ? `CW from tower · ${cwPump.label}` : "CW from tower", cwPump, V(3.35, top + 0.65, Cd.z));
      navLabel("CW to tower", null, V(2.55, top + 0.3, Cd.z));
    }
    // isolation valves on the entering pipes
    const iso = (pipeName, part) => {
      const vl = Parts.valve(1, MAT.flange);
      vl.scale.setScalar(1.5);
      add(part, onPipe(pipeName, 0.22, vl));
      return vl;
    };
    const valves = [iso("chw_entering_pipe", "chw_entering_pipe.valve")];
    if (water) valves.push(iso("cw_entering_pipe", "cw_entering_pipe.valve"));

    return K.finish({
      pad: [V(-3.6, top + 0.9, 0), V(3.6, 0, 0)],
      setState: s => {
        const p = s.plant;
        if (!p) return;
        K.running = p.run;
        K.fanSpeed = p.run ? 0.4 + 0.6 * p.plr : 0;
        pn.userData.lamp.userData.set(p.run);
        flows.chw.forEach(f => f.setSpeed(p.run ? 0.9 : 0));
        flows.cw.forEach(f => f.setSpeed(p.run ? 1.0 : 0));
        valves.forEach(vl => vl.userData.setCommand(p.run ? 1 : 0));
      },
    });
  }

  return { build };
})();
