// Parametric boiler: build(payload, viewer) -> the model API (see plant.js). Part names match anchors.yaml.
//   Packaged fire-tube boiler: casing cut away to show the furnace tube and the flame (its size follows the firing
//   rate), burner and blower on the left end, flue stack on the right, HW nozzles on top.
const Boiler = (() => {
  const { V, MAT, C, box } = Parts;

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, navLabel, pipe } = K;
    const X0 = -1.4, X1 = 1.4, yc = 1.05, R = 0.72;

    K.group.add(box(V(X0 - 0.75, 0, -0.8), V(X1 + 0.2, 0.12, 0.8), MAT.frame, 0.02));
    for (const x of [X0 + 0.4, X1 - 0.4]) K.group.add(box(V(x - 0.14, 0.12, -0.5), V(x + 0.14, yc - R + 0.15, 0.5), MAT.frame));

    // casing (red jacket), refractory-lined furnace tube, fire tubes
    const jacket = new THREE.MeshStandardMaterial({ color: 0xa33a2c, metalness: 0.35, roughness: 0.45 });
    const cs = new THREE.Group();
    cs.add(Plant.shell(X0, X1, yc, 0, R, jacket, { cut: 0.7 }));
    for (const [x, s] of [[X0, -1], [X1, 1]]) cs.add(Plant.dish(x, yc, 0, R, s, MAT.skin));
    const refr = new THREE.MeshStandardMaterial({ color: 0x5a4a42, roughness: 0.9, side: THREE.DoubleSide });
    cs.add(Plant.shell(X0 + 0.05, X1 - 0.1, yc - 0.12, 0, 0.3, refr, { cut: 1.1, inner: refr }));
    const tubes = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.03, 0.03, X1 - X0 - 0.1, 8), MAT.trim, 14), m = new THREE.Matrix4();
    const q = new THREE.Quaternion().setFromAxisAngle(V(0, 0, 1), Math.PI / 2);
    for (let i = 0; i < 14; i++) {
      const a = Math.PI * (0.15 + 0.7 * (i % 7) / 6), rr = i < 7 ? 0.45 : 0.56;
      tubes.setMatrixAt(i, m.compose(V(0, yc + 0.05 + rr * Math.sin(a) * 0.6, -rr * Math.cos(a) * 0.9), q, V(1, 1, 1)));
    }
    cs.add(tubes);
    add("casing", cs);

    // flame in the furnace tube: two nested cones, scaled by the firing rate, flickering
    const flame = new THREE.Group(), hot = [];
    for (const [r, len, col, op] of [[0.22, 1.5, 0xff7a1a, 0.55], [0.12, 1.0, 0xffd27a, 0.85]]) {
      const mat = new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 2.4, transparent: true, opacity: op, depthWrite: false });
      const c = new THREE.Mesh(new THREE.ConeGeometry(r, len, 24, 1, true), mat);
      c.rotation.z = -Math.PI / 2;
      c.position.x = len / 2;
      flame.add(c);
      hot.push(mat);
    }
    flame.position.set(X0 + 0.02, yc - 0.12, 0);
    K.group.add(flame);
    let firing = 0;
    K.movers.push(t => {
      const f = firing / 100, k = f > 0 ? 0.35 + 0.65 * f : 0;
      flame.visible = k > 0;
      flame.scale.set(k * (1 + 0.06 * Math.sin(t * 23)), 0.8 + 0.4 * k + 0.05 * Math.sin(t * 17), 0.8 + 0.4 * k + 0.05 * Math.sin(t * 19));
    });

    // burner and blower on the left end
    const bn = new THREE.Group();
    bn.add(box(V(X0 - 0.7, yc - 0.35, -0.35), V(X0 - 0.2, yc + 0.35, 0.35), new THREE.MeshStandardMaterial({ color: 0xc9cdd2, metalness: 0.3, roughness: 0.45 }), 0.04));
    const throat = Parts.mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.3, 28), MAT.duct);
    throat.rotation.z = Math.PI / 2;
    throat.position.set(X0 - 0.12, yc - 0.12, 0);
    bn.add(throat);
    const blower = Parts.motor(0.4, 0.15);
    blower.position.set(X0 - 0.45, yc + 0.52, 0);
    bn.add(blower);
    const port = Parts.mesh(new THREE.CircleGeometry(0.07, 20), new THREE.MeshStandardMaterial({ color: 0xff8a2a, emissive: 0xff8a2a, emissiveIntensity: 0 }));
    port.position.set(X0 - 0.45, yc, 0.355);
    bn.add(port);
    add("burner", bn);
    label("Burner", V(X0 - 0.45, yc + 0.95, 0));

    // flue stack from the rear top
    const fl = new THREE.Group();
    fl.add(Parts.mesh(new THREE.CylinderGeometry(0.2, 0.2, 2.9, 28), MAT.duct).translateX(X1 - 0.25).translateY(yc + R + 1.35));
    fl.add(Parts.mesh(new THREE.CylinderGeometry(0.26, 0.26, 0.08, 28), MAT.flange).translateX(X1 - 0.25).translateY(yc + R - 0.05));
    fl.add(Parts.mesh(new THREE.ConeGeometry(0.34, 0.22, 28), MAT.frame).translateX(X1 - 0.25).translateY(yc + R + 2.95));
    add("flue", fl);
    label("Flue", V(X1 - 0.25, yc + R + 3.35, 0));

    // control panel on the front of the skid
    const pn = Plant.panel(0.55, 0.75, 0.22);
    pn.position.set(0.2, 0.55, 0.92);
    K.group.add(box(V(-0.05, 0, 0.8), V(0.45, 0.18, 1.04), MAT.frame));
    add("control_panel", pn);

    // HW nozzles on top: leaving to the left, entering (return) from the right
    const ytop = yc + R - 0.02;
    const flows = [pipe("hw_leaving_pipe", [V(-0.35, ytop, 0), V(-0.35, 2.85, 0), V(-2.5, 2.85, 0)], "hot_water", { r: 0.08 }),
                   pipe("hw_entering_pipe", [V(0.55, ytop, 0), V(0.55, 2.45, 0), V(2.6, 2.45, 0)], "hot_water", { r: 0.08, into: true })];
    const pump = K.sib(/HW|HHW|P[-_ ]?\d/i);
    navLabel("HW supply · to building", null, V(-2.3, 3.2, 0));
    navLabel(pump ? `HW return · ${pump.label}` : "HW return", pump, V(2.45, 2.8, 0));

    return K.finish({
      pad: [V(-2.9, 0, 0), V(2.9, 4.6, 0)],
      setState: s => {
        const p = s.plant;
        if (!p) return;
        firing = p.run ? p.firing : 0;
        port.material.emissiveIntensity = firing ? 0.6 + firing / 60 : 0;
        hot.forEach(mt => { mt.emissiveIntensity = 1.2 + 2 * firing / 100; });
        pn.userData.lamp.userData.set(p.run);
        flows.forEach(f => f.setSpeed(p.run ? 0.8 : 0.15));  // the loop keeps moving through an idle boiler, slowly
      },
    });
  }

  return { build };
})();
