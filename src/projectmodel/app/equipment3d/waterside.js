// Waterside equipment beyond the plant's chillers, boilers and pumps: cooling tower, heat exchanger, meter.
// build(payload, viewer) -> the model API (see plant.js). Part names match anchors.yaml.
//   Cooling tower: induced-draft cell, casing cut away to show the fill and the spray, basin, fan in a stack on top
//   (turns with the simulated speed), condenser water in at the top and out of the basin, isolation valve.
//   Heat exchanger: shell-and-tube shell, primary (steam or water) in through its control valve, hot water out.
//   Meter: a meter body on its line (pipe for water / gas / thermal, conduit for electricity) with a lit display.
const CoolingTower = (() => {
  const { V, MAT, C, box, flow } = Parts;
  const PANEL = new THREE.MeshStandardMaterial({ color: 0x7d8f9c, metalness: 0.4, roughness: 0.5 });
  const FILL = new THREE.MeshStandardMaterial({ color: 0xd8d2b8, roughness: 0.8 });

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, navLabel, pipe, onPipe, v } = K;
    const W = 2.4, Dd = 2.0, y0 = 0.5, H = 2.2, y1 = y0 + H;
    const streams = [];

    const cs = new THREE.Group();
    for (const [a, b] of [[V(-W / 2, y0, -Dd / 2), V(W / 2, y1, -Dd / 2 + 0.05)], [V(-W / 2, y0, -Dd / 2), V(-W / 2 + 0.05, y1, Dd / 2)],
                          [V(W / 2 - 0.05, y0, -Dd / 2), V(W / 2, y1, Dd / 2)], [V(-W / 2, y1 - 0.06, -Dd / 2), V(W / 2, y1, Dd / 2)]]) cs.add(box(a, b, PANEL, 0.01));
    for (const x of [-W / 2, W / 2]) for (const z of [-Dd / 2, Dd / 2]) cs.add(box(V(x - 0.05, 0, z - 0.05), V(x + 0.05, y0, z + 0.05), MAT.frame));
    // louvers on the lower front (air in)
    for (let i = 0; i < 5; i++) cs.add(box(V(-W / 2 + 0.05, y0 + 0.08 + i * 0.12, Dd / 2 - 0.08), V(W / 2 - 0.05, y0 + 0.1 + i * 0.12, Dd / 2 - 0.02), MAT.trim).rotateX(-0.4));
    add("casing", cs);
    const basin = box(V(-W / 2, y0, -Dd / 2), V(W / 2, y0 + 0.35, Dd / 2), MAT.skin, 0.02);
    add("basin", basin);
    const water = box(V(-W / 2 + 0.06, y0 + 0.3, -Dd / 2 + 0.06), V(W / 2 - 0.06, y0 + 0.31, Dd / 2 - 0.06), new THREE.MeshStandardMaterial({ color: 0x2fb39c, emissive: 0x2fb39c, emissiveIntensity: 0.25, transparent: true, opacity: 0.7 }));
    K.group.add(water);
    // fill: corrugated sheets
    const fill = new THREE.Group();
    for (let i = 0; i < 14; i++) fill.add(box(V(-W / 2 + 0.12 + i * (W - 0.24) / 13 - 0.008, y0 + 0.8, -Dd / 2 + 0.1), V(-W / 2 + 0.12 + i * (W - 0.24) / 13 + 0.008, y1 - 0.55, Dd / 2 - 0.1), FILL));
    add("fill", fill);
    // spray: falling drops (particles) from the distribution header to the basin
    const drops = [];
    for (let i = 0; i < 5; i++) {
      const x = -W / 2 + 0.35 + i * (W - 0.7) / 4;
      const pr = Parts.particles([V(x, y1 - 0.45, Dd / 2 - 0.05), V(x, y0 + 0.35, Dd / 2 - 0.05)], Parts.MEDIUM.condenser_water, { size: 0.02, spacing: 0.12 });
      K.group.add(pr.mesh);
      drops.push(pr);
    }
    // fan stack and fan on top
    const stack = new THREE.Group();
    stack.add(Parts.mesh(new THREE.CylinderGeometry(0.85, 0.95, 0.7, 40, 1, true), new THREE.MeshStandardMaterial({ color: 0x7d8f9c, metalness: 0.4, roughness: 0.5, side: THREE.DoubleSide })).translateY(y1 + 0.35));
    stack.add(Parts.mesh(new THREE.TorusGeometry(0.85, 0.03, 8, 40), MAT.trim).rotateX(Math.PI / 2).translateZ(-(y1 + 0.7)));
    K.group.add(stack);
    const fan = new THREE.Group();
    for (let i = 0; i < 6; i++) { const g = new THREE.Group(); g.add(box(V(0.08, -0.012, -0.1), V(0.78, 0.012, 0.1), MAT.frame)); g.rotation.y = i * Math.PI / 3; g.children[0].rotation.x = 0.25; fan.add(g); }
    fan.add(Parts.mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.12, 20), MAT.trim));
    fan.position.set(0, y1 + 0.3, 0);
    add("fan", fan);
    const mot = Parts.motor(0.4, 0.15);
    mot.rotation.x = Math.PI / 2;
    mot.position.set(0, y1 + 0.05, 0);
    K.group.add(mot);
    label("Fan", V(0, y1 + 1.2, 0.5));
    const out = flow([V(0, y1 + 0.8, 0.3), V(0, y1 + 2.2, 0.3)], viewer.theme().air.return, { size: 0.65, spacing: 0.32, groups: 2, gap: 0.12 });
    out.key = "return"; streams.push(out); K.group.add(out.mesh);
    const inn = flow([V(0, y0 + 0.4, Dd / 2 + 1.2), V(0, y0 + 0.4, Dd / 2 + 0.1)], viewer.theme().air.outside, { size: 0.55, spacing: 0.3, groups: 2, gap: 0.11, normal: V(1, 0, 0) });
    inn.key = "outside"; streams.push(inn); K.group.add(inn.mesh);

    // condenser water: entering (hot, from the chillers) at the top header, leaving from the basin
    const flows = [pipe("cw_entering_pipe", [V(W / 2 + 1.6, y1 - 0.4, 0), V(W / 2 - 0.1, y1 - 0.4, 0), V(-W / 2 + 0.2, y1 - 0.4, 0)], "condenser_water", { r: 0.09 }),
                   pipe("cw_leaving_pipe", [V(-W / 2, y0 + 0.15, 0.4), V(-W / 2 - 1.6, y0 + 0.15, 0.4), V(-W / 2 - 1.6, 0.25, 0.4)], "condenser_water", { r: 0.09 })];
    const iv = Parts.valve(0.8, new THREE.MeshStandardMaterial({ color: Parts.MEDIUM.condenser_water }));
    add("cw_entering_pipe.valve", onPipe("cw_entering_pipe", 0.22, iv));
    navLabel("CW from chillers", null, V(W / 2 + 1.4, y1 - 0.05, 0));
    navLabel("CW to chillers", null, V(-W / 2 - 1.4, y0 + 0.55, 0.4));

    const d = Parts.vfd();
    d.position.set(W / 2 + 0.6, 1.0, Dd / 2 - 0.2);
    add("fan.vfd", d);
    const pn = Plant.panel(0.5, 0.6, 0.2);
    pn.position.set(W / 2 + 0.6, 1.0, -0.3);
    add("control_panel", pn);

    return K.finish({
      pad: [V(-W / 2 - 1.8, 0, 0), V(W / 2 + 1.8, y1 + 2.4, 0)],
      update: (t, dt) => { streams.forEach(s => s.update(t, dt)); drops.forEach(p => p.update(t, dt)); fan.rotation.y -= dt * 8 * (fan.speed || 0); },
      setState: s => {
        const p = s.plant;
        if (!p) return;
        fan.speed = p.run ? p.speed / 100 : 0;
        pn.userData.lamp.userData.set(p.run);
        iv.userData.setCommand(p.run ? 1 : 0);
        drops.forEach(d => d.setSpeed(p.run ? 1.2 : 0));
        flows.forEach(f => f.setSpeed(p.run ? 0.8 : 0));
        streams.forEach(st => { st.setSpeed(p.run ? 1.2 * p.speed / 100 : 0); st.setActive(p.run); });
      },
      applyTheme: P => streams.forEach(st => st.setColor(P.air[st.key])),
    });
  }

  return { build };
})();

const HeatExchanger = (() => {
  const { V, MAT, C, box } = Parts;

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, navLabel, pipe, onPipe, v } = K;
    const X0 = -1.3, X1 = 1.3, yc = 1.0, R = 0.42, steam = v.primary === "steam";
    K.group.add(box(V(X0 - 0.2, 0, -0.6), V(X1 + 0.2, 0.1, 0.6), MAT.frame, 0.02));
    for (const x of [X0 + 0.35, X1 - 0.35]) K.group.add(box(V(x - 0.1, 0.1, -0.35), V(x + 0.1, yc - R + 0.05, 0.35), MAT.frame));
    const sh = new THREE.Group();
    sh.add(Plant.shell(X0, X1, yc, 0, R, MAT.skin, { cut: 0.8 }));
    for (const [x, s] of [[X0, -1], [X1, 1]]) sh.add(Plant.dish(x, yc, 0, R, s, MAT.skin));
    const tubes = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.02, 0.02, X1 - X0 - 0.1, 8), C.copper, 16), m = new THREE.Matrix4();
    const q = new THREE.Quaternion().setFromAxisAngle(V(0, 0, 1), Math.PI / 2);
    for (let i = 0; i < 16; i++) tubes.setMatrixAt(i, m.compose(V(0, yc - 0.22 + (i % 4) * 0.14, -0.21 + Math.floor(i / 4) * 0.14), q, V(1, 1, 1)));
    sh.add(tubes);
    add("shell", sh);
    label("Heat exchanger", V(0, yc + R + 0.4, 0.3));

    const prim = steam ? "steam" : "hot_water", pm = steam ? 0xd9dde2 : Parts.MEDIUM.hot_water;
    Parts.MEDIUM.steam = 0xd9dde2;
    const flows = [
      pipe("primary_in_pipe", [V(X0 + 0.4, yc + R - 0.02, 0), V(X0 + 0.4, 2.6, 0), V(X0 - 1.4, 2.6, 0)], prim, { r: 0.07, into: true }),
      pipe("primary_out_pipe", [V(X0 + 0.4, yc - R + 0.02, 0.15), V(X0 + 0.4, 0.3, 0.15), V(X0 - 1.4, 0.3, 0.15)], prim, { r: 0.05 }),
      pipe("hw_leaving_pipe", [V(X1 - 0.4, yc + R - 0.02, 0), V(X1 - 0.4, 2.3, 0), V(X1 + 1.5, 2.3, 0)], "hot_water", { r: 0.08 }),
      pipe("hw_entering_pipe", [V(X1 - 0.4, yc - R + 0.02, 0.15), V(X1 - 0.4, 0.35, 0.15), V(X1 + 1.5, 0.35, 0.15)], "hot_water", { r: 0.08, into: true }),
    ];
    const cv = Parts.valve(0.5, new THREE.MeshStandardMaterial({ color: pm }));
    add("primary_in_pipe.valve", onPipe("primary_in_pipe", 0.7, cv));
    navLabel(steam ? "Steam in" : "Primary in", null, V(X0 - 1.2, 2.95, 0));
    navLabel(steam ? "Condensate" : "Primary out", null, V(X0 - 1.2, 0.65, 0.15));
    navLabel("HW supply", null, V(X1 + 1.3, 2.65, 0));
    navLabel("HW return", null, V(X1 + 1.3, 0.7, 0.15));
    const pn = Plant.panel(0.5, 0.6, 0.2);
    pn.position.set(0, 0.5, 0.75);
    add("control_panel", pn);

    return K.finish({
      pad: [V(X0 - 1.6, 0, 0), V(X1 + 1.7, 3.0, 0)],
      setState: s => {
        const p = s.plant;
        if (!p) return;
        cv.userData.setCommand(p.firing / 100);
        pn.userData.lamp.userData.set(p.run);
        flows.forEach((f, i) => f.setSpeed(i < 2 ? 0.9 * p.firing / 100 : p.run ? 0.8 : 0.15));
      },
    });
  }

  return { build };
})();

const Meter = (() => {
  const { V, MAT, C, box } = Parts;
  const LINE = { electric: 0x3a3e44, gas: 0xe0b23a, water: 0x2f80d8, chilled_water: 0x2f80d8, hot_water: 0xd6493f };

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, pipe, v } = K;
    const kind = v.kind || "electric", yc = 1.2;
    Parts.MEDIUM[`meter_${kind}`] = LINE[kind] ?? 0x888888;
    const line = pipe("line", [V(-2.2, yc, 0), V(2.2, yc, 0)], `meter_${kind}`, { r: kind === "electric" ? 0.05 : 0.08 });
    const body = new THREE.Group();
    if (kind === "electric") {
      body.add(box(V(-0.35, -0.45, -0.15), V(0.35, 0.45, 0.15), new THREE.MeshStandardMaterial({ color: 0xc9ccd0, roughness: 0.5 }), 0.03));
      body.add(Parts.mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.12, 32), MAT.glass).rotateX(Math.PI / 2).translateY(0.08).translateZ(0.0));
    } else {
      body.add(Parts.mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.5, 28), new THREE.MeshStandardMaterial({ color: 0x2f5d8c, metalness: 0.4, roughness: 0.45 })).rotateZ(Math.PI / 2));
      body.add(box(V(-0.2, 0.15, -0.16), V(0.2, 0.5, 0.16), new THREE.MeshStandardMaterial({ color: 0xd8dade, roughness: 0.5 }), 0.02));
    }
    body.position.set(0, kind === "electric" ? yc + 0.6 : yc, 0);
    add("meter_body", body);
    const disp = box(V(-0.14, -0.06, 0), V(0.14, 0.06, 0.01), C.screen);
    disp.position.set(0, (kind === "electric" ? yc + 0.85 : yc + 0.36), kind === "electric" ? 0.16 : 0.17);
    add("display", disp);
    label({ electric: "Electric meter", gas: "Gas meter", water: "Water meter", chilled_water: "Thermal meter (CHW)", hot_water: "Thermal meter (HW)" }[kind] || "Meter", V(0, yc + 1.4, 0.3));
    return K.finish({
      pad: [V(-2.4, 0, 0), V(2.4, yc + 1.6, 0)],
      setState: s => { line.setSpeed(s.plant ? 0.4 + 0.8 * (s.plant.load || 0) : 0.4); },
    });
  }

  return { build };
})();
