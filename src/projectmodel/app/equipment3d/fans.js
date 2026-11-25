// Parametric exhaust fan: build(payload, viewer) -> the model API (see plant.js). Part names match anchors.yaml.
//   Roof (variant.roof): exhaust duct up through the roof deck into a curb, backdraft damper in the duct, an upblast
//   centrifugal fan in a cut-away windband, motor beside it, starter / disconnect and (with speed points) a VFD.
//   Inline (variant.inline): horizontal duct with an inline centrifugal fan in a cut-away casing, damper downstream.
//   The wheel turns with the simulated fan, the inlet ring glows with its status, chevrons show the exhaust air.
const ExhaustFan = (() => {
  const { V, MAT, C, box, flow } = Parts;
  const DECK = new THREE.MeshStandardMaterial({ color: 0x9a9da2, metalness: 0.05, roughness: 0.9 });
  const BAND = new THREE.MeshStandardMaterial({ color: 0x6f747b, metalness: 0.6, roughness: 0.4, side: THREE.DoubleSide });

  // Open vertical cylinder from y0 to y1, its front (towards +z, the hero camera) cut away.
  function band(r, y0, y1, cut = 0.9) {
    const g = new THREE.Group();
    const m = Parts.mesh(new THREE.CylinderGeometry(r, r, y1 - y0, 56, 1, true, cut, Math.PI * 2 - 2 * cut), BAND);
    m.position.y = (y0 + y1) / 2;
    g.add(m);
    for (const y of [y0, y1]) {
      const rim = Parts.mesh(new THREE.TorusGeometry(r, 0.025, 8, 56, Math.PI * 2 - 2 * cut), MAT.trim);
      rim.rotation.x = Math.PI / 2;
      rim.rotation.z = -Math.PI / 2 + cut;
      rim.position.y = y;
      g.add(rim);
    }
    return g;
  }

  // Starter / disconnect: a grey box with a rotary handle and a status lamp.
  function starter() {
    const g = new THREE.Group();
    g.add(box(V(-0.18, -0.24, -0.08), V(0.18, 0.24, 0.08), new THREE.MeshStandardMaterial({ color: 0xc9ccd0, roughness: 0.5 }), 0.02));
    const h = Parts.mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.04, 16), new THREE.MeshStandardMaterial({ color: 0xd23b2f, roughness: 0.5 }));
    h.rotation.x = Math.PI / 2;
    h.position.set(0, -0.05, 0.1);
    g.add(h);
    const l = Plant.lamp(0.03);
    l.position.set(0, 0.14, 0.1);
    g.add(l);
    g.userData.lamp = l;
    return g;
  }

  function stand(x, z, y1) {  // unistrut stand for a drive or starter on the roof
    const g = new THREE.Group();
    for (const dx of [-0.16, 0.16]) g.add(box(V(x + dx - 0.02, 1.4, z - 0.02), V(x + dx + 0.02, y1, z + 0.02), MAT.frame));
    return g;
  }

  function build(data, viewer) {
    const K = Plant.kit(data, viewer), { add, label, v } = K;
    const streams = [];
    const stream = (key, pts, opts) => { const f = flow(pts, viewer.theme().air[key], opts); f.key = key; streams.push(f); K.group.add(f.mesh); return f; };
    let fan, damper, lampOf = [], extra = {};

    if (v.inline) {
      // --- inline: duct along x through a fan casing ---------------------------------------------------
      const yc = 2.2, dw = 0.7, dh = 0.6, x0 = -2.6, x1 = 2.6, cx0 = -0.6, cx1 = 0.6, CH = 1.05, CD = 1.05;
      const dg = new THREE.Group();
      dg.add(Parts.duct(V(x0, yc, 0), V(cx0, yc, 0), dw, dh));
      dg.add(Parts.duct(V(cx1, yc, 0), V(x1, yc, 0), dw, dh));
      add("duct", dg);
      K.paths.duct = { pts: [V(x0, yc, 0), V(x1, yc, 0)], r: dh / 2 };
      const cs = VAV.casing(cx0, cx1, yc - CH / 2, yc + CH / 2, CD);
      add("housing", cs.group);
      extra.front = cs.front;
      const f = Parts.fan({ r: 0.34, width: 0.36, housing: [0.86, 0.86, 0.6] });
      f.group.rotation.y = -Math.PI / 2;  // shaft along x, inlet facing the incoming air
      f.group.position.set(0, yc, 0);
      add("fan", f.group);
      fan = f;
      const mot = Parts.motor(0.42, 0.15);
      mot.rotation.y = Math.PI / 2;
      mot.position.set(0, yc + CH / 2 + 0.2, -0.15);
      K.group.add(mot);
      // hangers to the structure above
      for (const x of [x0 + 0.3, cx0 - 0.3, cx1 + 0.3, x1 - 0.3]) K.group.add(box(V(x - 0.012, yc + dh / 2, -0.012), V(x + 0.012, yc + 1.3, 0.012), MAT.trim));
      const dm = Parts.damper(dw - 0.06, dh - 0.06, { stack: "y", open: 0.8 });
      dm.position.set(1.5, yc, 0);
      add("damper", dm);
      damper = dm;
      add("curb", new THREE.Group());  // no curb indoors: an empty part keeps the anchor list honest
      stream("return", [V(x0 - 1.0, yc, dw / 2 + 0.05), V(x1 + 0.4, yc, dw / 2 + 0.05)], { size: 0.6, spacing: 0.36, groups: 2, gap: 0.12 });
      label("Exhaust air", V(x0 + 0.2, yc + 0.75, 0.3));
      label("To outside", V(x1 + 0.2, yc + 0.75, 0.3));
      // drive and starter on the wall behind
      const wall = box(V(-1.8, 0.2, -1.0), V(1.8, 1.9, -0.92), new THREE.MeshStandardMaterial({ color: 0xc9ccd1, roughness: 0.85 }), 0.01);
      K.group.add(wall);
      const st = starter();
      st.position.set(-0.9, 1.15, -0.84);
      add("controller", st);
      lampOf.push(st.userData.lamp);
      if (v.vfd) {
        const d = Parts.vfd();
        d.position.set(0.6, 1.15, -0.82);
        add("fan.vfd", d);
      }
      label("Exhaust fan (inline)", V(0, yc + CH / 2 + 0.75, 0.3));
      extra.pad = [V(x0 - 1.0, 0, 0), V(x1 + 0.6, yc + 1.4, 0)];
    } else {
      // --- roof: duct up through the deck into the curb, upblast fan on top ----------------------------
      const yDeck = 1.4, yCurb = 2.0, dw = 0.85;
      const deck = box(V(-2.6, yDeck - 0.22, -1.8), V(2.6, yDeck, 1.8), DECK, 0.02);
      deck.receiveShadow = true;
      K.group.add(deck);
      const dg = new THREE.Group();
      dg.add(Parts.duct(V(0, 0.15, 0), V(0, yDeck - 0.22, 0), dw, dw));
      add("duct", dg);
      K.paths.duct = { pts: [V(0, 0.15, 0), V(0, yCurb, 0)], r: dw / 2 };
      const curb = new THREE.Group();
      curb.add(box(V(-0.62, yDeck, -0.62), V(0.62, yCurb, 0.62), MAT.skin, 0.02));
      curb.add(box(V(-0.7, yCurb - 0.04, -0.7), V(0.7, yCurb, 0.7), MAT.trim, 0.01));
      add("curb", curb);
      const dm = Parts.damper(dw - 0.08, dw - 0.08, { stack: "x", open: 0.8 });
      dm.position.set(0, 0.85, 0);
      add("damper", dm);
      damper = dm;
      // fan: shaft vertical, inlet facing down into the curb
      const f = Parts.fan({ r: 0.42, width: 0.32, housing: [1.0, 1.0, 0.5] });
      f.group.rotation.x = Math.PI / 2;
      f.group.position.set(0, yCurb + 0.32, 0);
      add("fan", f.group);
      fan = f;
      const housing = band(0.78, yCurb + 0.02, yCurb + 1.05);
      add("housing", housing);
      // motor beside the windband on a bracket
      const mot = Parts.motor(0.45, 0.16);
      mot.rotation.x = Math.PI / 2;
      mot.position.set(0.98, yCurb + 0.5, -0.1);
      K.group.add(mot);
      K.group.add(box(V(0.76, yCurb + 0.28, -0.25), V(0.98, yCurb + 0.32, 0.05), MAT.frame));
      stream("return", [V(0, 0.2, dw / 2 + 0.05), V(0, yCurb + 0.2, dw / 2 + 0.05)], { size: 0.55, spacing: 0.3, groups: 2, gap: 0.11, normal: V(0, 0, 1) });
      stream("return", [V(0, yCurb + 0.7, 0.55), V(0, yCurb + 2.3, 0.55)], { size: 0.65, spacing: 0.32, groups: 2, gap: 0.12, normal: V(0, 0, 1) });
      label("Exhaust air", V(0.75, 0.6, 0.6));
      label("Discharge", V(0, yCurb + 2.55, 0.5));
      // starter and drive on stands on the roof
      K.group.add(stand(-1.7, -0.9, 2.2));
      const st = starter();
      st.position.set(-1.7, 2.1, -0.82);
      add("controller", st);
      lampOf.push(st.userData.lamp);
      if (v.vfd) {
        K.group.add(stand(1.7, -0.9, 2.4));
        const d = Parts.vfd();
        d.position.set(1.7, 2.2, -0.82);
        add("fan.vfd", d);
      }
      label("Exhaust fan (roof)", V(-0.9, yCurb + 1.45, 0.4));
      extra.pad = [V(-2.6, 0, 0), V(2.6, yCurb + 2.6, 0)];
    }

    // Nothing drawn for an optional part with no point (a VFD the source doesn't have): give the anchor a stand-in so
    // the anchor list stays complete, without geometry.
    for (const name of ["fan.vfd"]) if (!K.parts[name]) add(name, new THREE.Group());

    return K.finish({
      front: extra.front,
      pad: extra.pad,
      update: (t, dt) => {
        streams.forEach(s => s.update(t, dt));
        fan.wheel.rotation.z -= dt * 9 * (fan.speed || 0);
      },
      setState: s => {
        const f = s.ahu?.fan?.exhaust;
        if (!f) return;
        fan.speed = f.run ? f.speed / 100 : 0;
        fan.setStatus(f.run ? "on" : "off");
        damper.userData.setOpen(f.run ? 0.9 : 0.05);
        lampOf.forEach(l => l.userData.set(f.run));
        streams.forEach(st => { st.setSpeed(f.run ? 1.3 * f.speed / 100 : 0); st.setActive(f.run); });
      },
      applyTheme: P => streams.forEach(st => st.setColor(P.air[st.key])),
    });
  }

  return { build };
})();
