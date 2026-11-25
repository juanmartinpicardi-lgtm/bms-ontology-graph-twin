// Zone units with their own controls: unit heater and ductless split. build(payload, viewer) -> the model API
// (see plant.js). Part names match anchors.yaml.
//   Unit heater: casing hung from the structure, fan at the back, heater (glowing electric elements, or a hot water
//   coil with its valve) and discharge louvers; a wall thermostat and a disconnect. Elements glow with the heat %.
//   Split system: indoor wall head with its cross-flow fan, refrigerant lines through the outside wall to the
//   condensing unit (fan and compressor), the vendor's BACnet gateway and the wired zone controller.
const UnitHeater = (() => {
  const { V, MAT, C, box, flow } = Parts;
  const WALL = new THREE.MeshStandardMaterial({ color: 0xc9ccd1, roughness: 0.85 });

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, navLabel, v } = K;
    const streams = [];
    const stream = (key, pts, opts) => { const f = flow(pts, viewer.theme().air[key], opts); f.key = key; streams.push(f); K.group.add(f.mesh); return f; };
    const yc = 2.5, L = 1.1, H = 0.62, D = 0.72, ya = yc - H / 2, yb = yc + H / 2;

    const cs = VAV.casing(0, L, ya, yb, D);
    add("casing", cs.group);
    for (const x of [0.15, L - 0.15]) K.group.add(box(V(x - 0.012, yb, -0.012), V(x + 0.012, yb + 0.9, 0.012), MAT.trim));
    // back guard over the fan inlet
    const guard = new THREE.Group();
    for (let i = 0; i < 5; i++) guard.add(box(V(-0.05, ya + 0.06 + i * 0.12, -D / 2 + 0.04), V(-0.02, ya + 0.09 + i * 0.12, D / 2 - 0.04), MAT.trim));
    K.group.add(guard);

    const f = Parts.fan({ r: 0.22, width: 0.18, housing: [0.5, 0.5, 0.26] });
    f.group.rotation.y = -Math.PI / 2;
    f.group.position.set(0.22, yc, 0);
    add("fan", f.group);

    // heater: electric elements (U-shaped rods that glow) or a hot water coil with its valve
    const glow = new THREE.MeshStandardMaterial({ color: 0x5a2a1e, emissive: 0xff5a1f, emissiveIntensity: 0, metalness: 0.4, roughness: 0.5 });
    const water = [];
    if (v.hot_water) {
      const k = Parts.coil(H - 0.14, D - 0.2, { medium: "hot_water", thick: 0.14, pitch: 0.04 });
      const kp = V(0.62, yc, -0.05);
      k.position.copy(kp);
      add("heater", k);
      const st = k.userData.stubs.supply.clone().add(kp);
      const vl = Parts.valve(0.5, k.userData.medium);
      vl.rotation.y = Math.PI / 2;
      vl.position.copy(st).add(V(0, 0, -0.2));
      add("heater.valve", vl);
      const ends = { supply: st, return: k.userData.stubs.return.clone().add(kp) };
      for (const [side, e] of Object.entries(ends)) {
        const run = [e.clone(), V(e.x, yb + 0.4 + (side === "return" ? 0.1 : 0), e.z), V(e.x, yb + 0.4 + (side === "return" ? 0.1 : 0), -1.4)];
        K.group.add(Parts.pipeRun(run, "hot_water", 0.03));
        const pr = Parts.particles(side === "supply" ? run.slice().reverse() : run, Parts.MEDIUM.hot_water, { size: 0.018, spacing: 0.09 });
        K.group.add(pr.mesh);
        water.push(pr);
      }
      navLabel("HW", null, V(st.x, yb + 0.7, -1.3));
    } else {
      const el = new THREE.Group();
      el.add(box(V(-0.04, -H / 2 + 0.06, -D / 2 + 0.06), V(0.04, -H / 2 + 0.09, D / 2 - 0.06), MAT.frame));
      el.add(box(V(-0.04, H / 2 - 0.09, -D / 2 + 0.06), V(0.04, H / 2 - 0.06, D / 2 - 0.06), MAT.frame));
      for (let i = 0; i < 6; i++) {
        const z = -D / 2 + 0.1 + i * (D - 0.2) / 5;
        const rod = Parts.mesh(new THREE.CylinderGeometry(0.014, 0.014, H - 0.16, 10), glow);
        rod.position.set(0, 0, z);
        el.add(rod);
        for (let j = 0; j < 4; j++) {  // fins on the element
          const fin = Parts.mesh(new THREE.TorusGeometry(0.03, 0.006, 6, 14), MAT.trim);
          fin.rotation.x = Math.PI / 2;
          fin.position.set(0, -H / 2 + 0.16 + j * (H - 0.32) / 3, z);
          el.add(fin);
        }
      }
      el.position.set(0.62, yc, 0);
      add("heater", el);
      add("heater.valve", new THREE.Group());  // electric: no valve (the anchor list stays complete)
      label("Electric heat", V(0.62, yb + 0.35, 0.35));
    }

    // discharge louvers, angled down
    const lv = new THREE.Group();
    lv.add(box(V(-0.03, ya, -D / 2), V(0.0, yb, D / 2), MAT.frame));
    for (let i = 0; i < 5; i++) {
      const b = box(V(-0.06, -0.012, -D / 2 + 0.04), V(0.1, 0.012, D / 2 - 0.04), C.blade);
      b.rotation.z = -0.5;
      b.position.set(0.04, ya + 0.08 + i * 0.11, 0);
      lv.add(b);
    }
    lv.position.set(L, 0, 0);
    add("louvers", lv);
    stream("return", [V(-1.4, yc, 0.15), V(0.05, yc, 0.15)], { size: 0.5, spacing: 0.3, groups: 2, gap: 0.11 });
    stream("supply", [V(0.3, yc, D / 2 - 0.08), V(L - 0.05, yc, D / 2 - 0.08)], { size: 0.45, spacing: 0.28, groups: 2, gap: 0.1 });
    stream("supply", [V(L + 0.15, yc - 0.1, 0.1), V(L + 1.0, yc - 0.7, 0.1), V(L + 1.5, 0.5, 0.1)], { size: 0.6, spacing: 0.3, groups: 2, gap: 0.12 });
    label("Room air", V(-0.9, yb + 0.3, 0.2));
    label("Warm air", V(L + 1.1, yc + 0.1, 0.3));

    // wall with the thermostat and the disconnect
    const zw = -1.5;
    K.group.add(box(V(-1.2, 0, zw - 0.08), V(2.6, 3.4, zw), WALL, 0.01));
    const ts = new THREE.Group();
    ts.add(box(V(-0.12, -0.16, 0), V(0.12, 0.16, 0.06), C.sensor, 0.03));
    ts.add(Parts.mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.02, 20), MAT.frame).rotateX(Math.PI / 2).translateY(0.065).translateZ(-0.0));
    ts.position.set(1.9, 1.5, zw);
    add("thermostat", ts);
    label("Thermostat", V(1.9, 1.9, zw + 0.1));
    const dc = new THREE.Group();
    dc.add(box(V(-0.15, -0.2, 0), V(0.15, 0.2, 0.14), new THREE.MeshStandardMaterial({ color: 0xc9ccd0, roughness: 0.5 }), 0.02));
    const lamp = Plant.lamp(0.03);
    lamp.position.set(0, 0.1, 0.15);
    dc.add(lamp);
    dc.position.set(-0.6, 1.6, zw);
    add("controller", dc);

    return K.finish({
      front: cs.front,
      pad: [V(-1.6, 0, 0), V(L + 1.6, yb + 1.0, 0)],
      update: (t, dt) => {
        streams.forEach(s => s.update(t, dt));
        water.forEach(w => w.update(t, dt));
        f.wheel.rotation.z -= dt * 8 * (f.speed || 0);
      },
      setState: s => {
        const u = s.unit;
        if (!u) return;
        f.speed = u.run ? 1 : 0;
        f.setStatus(u.run ? "on" : "off");
        lamp.userData.set(u.run);
        glow.emissiveIntensity = 2.4 * u.heat / 100;
        K.parts["heater.valve"]?.userData.setCommand?.(u.heat / 100);
        water.forEach(w => w.setSpeed(0.5 * u.heat / 100));
        streams.forEach(st => { st.setSpeed(u.run ? 1.1 : 0); st.setActive(u.run); });
      },
      applyTheme: P => streams.forEach(st => st.setColor(P.air[st.key])),
    });
  }

  return { build };
})();

const Split = (() => {
  const { V, MAT, C, box, flow } = Parts;
  const WHITE = new THREE.MeshStandardMaterial({ color: 0xeef0f2, metalness: 0.05, roughness: 0.35 });
  const WALL = new THREE.MeshStandardMaterial({ color: 0xc9ccd1, roughness: 0.85 });
  const INSUL = new THREE.MeshStandardMaterial({ color: 0x1d1f22, roughness: 0.8 });

  function crossFlow(len, r) {  // tangential fan wheel along x
    const g = new THREE.Group();
    for (let i = 0; i < 18; i++) {
      const a = i / 18 * Math.PI * 2;
      const b = box(V(-len / 2, -0.004, -0.02), V(len / 2, 0.004, 0.02), MAT.frame);
      b.position.set(0, Math.sin(a) * r, Math.cos(a) * r);
      b.rotation.x = a + 0.6;
      g.add(b);
    }
    for (const x of [-len / 2, 0, len / 2]) g.add(Parts.mesh(new THREE.CylinderGeometry(r, r, 0.01, 24), MAT.trim).rotateZ(Math.PI / 2).translateY(x));
    return g;
  }

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, v } = K;
    const streams = [];
    const stream = (key, pts, opts) => { const f = flow(pts, viewer.theme().air[key], opts); f.key = key; streams.push(f); K.group.add(f.mesh); return f; };
    const zw = -0.9, xOut = 1.6;

    // room: back wall, outside wall
    K.group.add(box(V(-2.4, 0, zw - 0.1), V(xOut, 3.0, zw), WALL, 0.01));
    K.group.add(box(V(xOut, 0, zw - 0.1), V(xOut + 0.18, 3.0, 1.1), WALL, 0.01));

    // indoor head: rounded white casing, front lower panel cut away to show the fan
    const yi = 2.35, hw = 1.0, hh = 0.32, hd = 0.26, zi = zw + hd / 2;
    const head = new THREE.Group();
    head.add(box(V(-hw / 2, -hh / 2 + 0.08, -hd / 2), V(hw / 2, hh / 2, hd / 2), WHITE, 0.05));
    head.add(box(V(-hw / 2, -hh / 2, -hd / 2), V(hw / 2, -hh / 2 + 0.09, -hd / 2 + 0.06), WHITE, 0.02));
    const vane = box(V(-hw / 2 + 0.05, -0.008, 0), V(hw / 2 - 0.05, 0.008, 0.1), WHITE);
    vane.position.set(0, -hh / 2 + 0.02, hd / 2 - 0.08);
    vane.rotation.x = 0.5;
    head.add(vane);
    const disp = Plant.lamp(0.012);
    disp.position.set(hw / 2 - 0.1, 0.0, hd / 2 + 0.005);
    head.add(disp);
    head.position.set(-0.4, yi, zi);
    add("indoor_unit", head);
    const cf = crossFlow(hw - 0.12, 0.05);
    cf.position.set(-0.4, yi - hh / 2 + 0.06, zi + 0.03);
    add("indoor_unit.fan", cf);
    label("Indoor unit", V(-0.4, yi + 0.45, zi + 0.2));
    const supply = stream("supply", [V(-0.4, yi - 0.25, zi + 0.25), V(-0.4, yi - 0.7, zi + 0.9), V(-0.4, 0.8, zi + 1.4)], { size: 0.6, spacing: 0.3, groups: 2, gap: 0.12, normal: V(1, 0, 0) });
    stream("return", [V(-0.4, yi + 0.9, zi + 0.35), V(-0.4, yi + 0.2, zi + 0.35)], { size: 0.5, spacing: 0.28, groups: 2, gap: 0.11, normal: V(1, 0, 0) });

    // refrigerant lines along the wall and through it
    const lines = new THREE.Group(), pts = [V(0.12, yi - 0.05, zw + 0.06), V(1.2, yi - 0.05, zw + 0.06), V(1.2, 0.6, zw + 0.06), V(xOut + 0.6, 0.6, zw + 0.06), V(xOut + 0.6, 0.6, -0.2)];
    for (const [dz, mat, r] of [[0, INSUL, 0.035], [0.08, C.copper, 0.02]]) {
      const run = pts.map(p => p.clone().add(V(0, 0, dz)));
      for (let i = 1; i < run.length; i++) {
        const a = run[i - 1], b = run[i];
        const c = Parts.mesh(new THREE.CylinderGeometry(r, r, a.distanceTo(b), 12), mat);
        c.position.copy(a).add(b).multiplyScalar(0.5);
        c.quaternion.setFromUnitVectors(V(0, 1, 0), b.clone().sub(a).normalize());
        lines.add(c);
      }
    }
    add("refrigerant_lines", lines);
    label("Refrigerant lines", V(1.0, 1.4, zw + 0.3));

    // outdoor condensing unit on a pad, side panel cut away to show the compressor
    const xo = xOut + 1.4, wo = 1.0, ho = 0.8, dO = 0.4;
    K.group.add(box(V(xo - 0.65, 0, -0.5), V(xo + 0.65, 0.1, 0.5), new THREE.MeshStandardMaterial({ color: 0x9a9da2, roughness: 0.9 }), 0.01));
    const ou = new THREE.Group();
    ou.add(box(V(-wo / 2, 0, -dO / 2), V(wo / 2, ho, -dO / 2 + 0.03), WHITE));
    ou.add(box(V(-wo / 2, ho - 0.03, -dO / 2), V(wo / 2, ho, dO / 2), WHITE));
    ou.add(box(V(-wo / 2, 0, -dO / 2), V(-wo / 2 + 0.03, ho, dO / 2), WHITE));
    const front = new THREE.Shape();
    front.moveTo(-wo / 2, 0); front.lineTo(wo / 2 - 0.3, 0); front.lineTo(wo / 2 - 0.3, ho); front.lineTo(-wo / 2, ho); front.closePath();
    const hole = new THREE.Path(); hole.absarc(-0.12, ho / 2, 0.3, 0, Math.PI * 2, true); front.holes.push(hole);
    ou.add(Parts.mesh(new THREE.ExtrudeGeometry(front, { depth: 0.02, bevelEnabled: false, curveSegments: 40 }), WHITE).translateZ(dO / 2 - 0.02));
    for (let i = 0; i < 4; i++) ou.add(Parts.mesh(new THREE.TorusGeometry(0.08 + i * 0.07, 0.006, 6, 32), MAT.frame).translateX(-0.12).translateY(ho / 2).translateZ(dO / 2 + 0.01));
    ou.position.set(xo, 0.1, 0);
    add("outdoor_unit", ou);
    const prop = new THREE.Group();
    for (let i = 0; i < 3; i++) {
      const b = box(V(0, -0.05, -0.005), V(0.26, 0.05, 0.005), MAT.frame);
      const g = new THREE.Group(); g.add(b); g.rotation.z = i * Math.PI * 2 / 3; prop.add(g);
    }
    prop.position.set(xo - 0.12, 0.1 + ho / 2, dO / 2 - 0.08);
    K.group.add(prop);
    const comp = new THREE.Group();
    comp.add(Parts.mesh(new THREE.CylinderGeometry(0.11, 0.11, 0.38, 24), new THREE.MeshStandardMaterial({ color: 0x2b2d31, metalness: 0.5, roughness: 0.4 })));
    comp.add(Parts.mesh(new THREE.SphereGeometry(0.11, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), new THREE.MeshStandardMaterial({ color: 0x2b2d31, metalness: 0.5, roughness: 0.4 })).translateY(0.19));
    comp.position.set(xo + wo / 2 - 0.16, 0.1 + 0.26, 0);
    add("outdoor_unit.compressor", comp);
    label("Outdoor unit", V(xo, ho + 0.45, 0.3));
    stream("outside", [V(xo - 0.12, 0.1 + ho / 2, dO / 2 + 0.1), V(xo - 0.12, 0.1 + ho / 2, dO / 2 + 1.2)], { size: 0.5, spacing: 0.28, groups: 2, gap: 0.1, normal: V(0, 1, 0) });

    // gateway and wired controller on the wall
    const gw = new THREE.Group();
    gw.add(box(V(-0.16, -0.11, 0), V(0.16, 0.11, 0.07), new THREE.MeshStandardMaterial({ color: 0xd3d6da, roughness: 0.5 }), 0.015));
    const gl = Plant.lamp(0.018); gl.position.set(0.1, 0.05, 0.08); gw.add(gl);
    gw.position.set(-1.7, 2.3, zw);
    add("gateway", gw);
    label("BACnet gateway", V(-1.7, 2.65, zw + 0.1));
    const ts = new THREE.Group();
    ts.add(box(V(-0.1, -0.14, 0), V(0.1, 0.14, 0.04), WHITE, 0.02));
    ts.add(box(V(-0.07, 0.0, 0.039), V(0.07, 0.09, 0.044), C.screen));
    ts.position.set(-1.2, 1.45, zw);
    add("zone_sensor", ts);
    label("Zone controller", V(-1.2, 1.8, zw + 0.1));

    return K.finish({
      pad: [V(-2.4, 0, 0), V(xo + 0.8, 3.0, 0)],
      update: (t, dt) => {
        streams.forEach(s => s.update(t, dt));
        cf.rotation.x -= dt * 14 * (cf.speed || 0);
        prop.rotation.z -= dt * 10 * (prop.speed || 0);
      },
      setState: s => {
        const u = s.unit;
        if (!u) return;
        cf.speed = u.run ? 1 : 0;
        prop.speed = u.run ? 1 : 0;
        disp.userData.set(u.run);
        gl.userData.set(true);
        supply.setColor(u.mode ? viewer.theme().air.supply : viewer.theme().air.return);
        streams.forEach(st => { st.setSpeed(u.run ? 1.0 : 0); st.setActive(u.run); });
      },
      applyTheme: P => streams.forEach(st => st.setColor(P.air[st.key])),
    });
  }

  return { build };
})();
