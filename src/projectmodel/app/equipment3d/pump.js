// Parametric pump: build(payload, viewer) -> the model API (see plant.js). Part names match anchors.yaml.
//   End-suction pump on a base: volute cut away to show the impeller (it turns with the simulated speed), coupling,
//   motor; suction in from the left, discharge up and over. The VFD is drawn when the source has speed points.
//   Pipes are coloured by the medium (variant.medium, from the pump's or its system's name).
const Pump = (() => {
  const { V, MAT, C, box } = Parts;
  const SHORT = { chilled_water: "CHW", hot_water: "HW", condenser_water: "CW" };

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, navLabel, pipe, onPipe, sib, v } = K;
    const yc = 0.8, R = 0.46, med = v.medium || "water";

    K.group.add(box(V(-0.9, 0, -0.65), V(2.1, 0.14, 0.65), MAT.frame, 0.02));

    // volute and impeller
    const casing = new THREE.MeshStandardMaterial({ color: 0x2f5d8c, metalness: 0.45, roughness: 0.45 });
    const vo = new THREE.Group();
    vo.add(Plant.shell(-0.2, 0.2, yc, 0, R, casing, { cut: 1.0 }));
    for (const x of [-0.2, 0.2]) {
      const side = Parts.mesh(new THREE.CircleGeometry(R, 48), casing);
      side.rotation.y = x < 0 ? -Math.PI / 2 : Math.PI / 2;
      side.material = casing.clone();
      side.material.side = THREE.DoubleSide;
      side.position.set(x, yc, 0);
      if (x < 0) { side.material.transparent = true; side.material.opacity = 0.35; side.material.depthWrite = false; }
      vo.add(side);
    }
    vo.add(box(V(-0.22, 0.14, -0.3), V(0.22, yc - R + 0.08, 0.3), casing));  // foot
    const imp = new THREE.Group();
    imp.add(Parts.mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.3, 20), MAT.trim).rotateZ(Math.PI / 2));
    for (let i = 0; i < 6; i++) {
      const b = box(V(-0.12, 0.06, -0.015), V(0.12, R - 0.08, 0.015), C.blade);
      const g = new THREE.Group();
      g.add(b);
      g.rotation.x = i * Math.PI / 3;
      imp.add(g);
    }
    imp.position.set(0, yc, 0);
    vo.add(imp);
    add("volute", vo);
    label("Pump", V(0, yc + R + 0.35, 0.45));

    // bearing frame, coupling, motor
    const frame = Parts.mesh(new THREE.CylinderGeometry(0.13, 0.15, 0.4, 24), casing);
    frame.rotation.z = Math.PI / 2;
    frame.position.set(0.42, yc, 0);
    K.group.add(frame);
    const coupling = new THREE.Group();
    coupling.add(Parts.mesh(new THREE.CylinderGeometry(0.15, 0.15, 0.1, 24), MAT.trim));
    for (let i = 0; i < 4; i++) coupling.add(box(V(0.1, -0.06, -0.025), V(0.16, 0.06, 0.025), MAT.frame).rotateY(i * Math.PI / 2));
    coupling.rotation.z = Math.PI / 2;
    coupling.position.set(0.72, yc, 0);
    K.group.add(coupling);
    const mot = Parts.motor(1.0, 0.34);
    mot.rotation.y = Math.PI / 2;
    mot.position.set(1.35, yc, 0);
    add("motor", mot);
    const lmp = Plant.lamp(0.05);
    lmp.position.set(1.35, yc + 0.4, 0);
    K.group.add(lmp);
    label("Motor", V(1.35, yc + 0.85, 0));
    let rpm = 0;
    K.movers.push((t, dt) => { imp.rotation.x += dt * 16 * rpm; coupling.rotation.y += dt * 16 * rpm; });

    // VFD on a stand
    let vfdBox = null;
    if (v.vfd) {
      vfdBox = Parts.vfd();
      vfdBox.scale.setScalar(1.4);
      vfdBox.position.set(2.6, 1.35, 0.1);
      K.group.add(box(V(2.55, 0, 0), V(2.65, 0.95, 0.06), MAT.frame));
      add("vfd", vfdBox);
      label("VFD", V(2.6, 2.05, 0.1));
    }

    // suction in from the left, discharge up and over
    const flows = [pipe("suction_pipe", [V(-0.21, yc, 0), V(-2.2, yc, 0)], med, { r: 0.12, into: true }),
                   pipe("discharge_pipe", [V(0, yc + R - 0.02, 0), V(0, 2.55, 0), V(-2.2, 2.55, 0)], med, { r: 0.1 })];
    const vl = Parts.valve(1, MAT.flange);
    vl.scale.setScalar(1.5);
    add("discharge_pipe.valve", onPipe("discharge_pipe", 0.25, vl));
    const what = SHORT[med] || "Water", chiller = med !== "hot_water" && sib(/^CH[-_ ]?\d/i);
    navLabel(`${what} suction`, null, V(-2.0, yc + 0.4, 0));
    navLabel(chiller ? `${what} discharge · to ${chiller.label}` : `${what} discharge`, chiller || null, V(-1.9, 2.9, 0));

    return K.finish({
      pad: [V(-2.5, 0, 0), V(3.0, 3.2, 0)],
      setState: s => {
        const p = s.plant;
        if (!p) return;
        rpm = p.run ? p.speed / 100 : 0;
        lmp.userData.set(p.run);
        flows.forEach(f => f.setSpeed(p.run ? 0.3 + 1.0 * p.speed / 100 : 0));
        vl.userData.setCommand(p.run ? 1 : 0);
      },
    });
  }

  return { build };
})();
