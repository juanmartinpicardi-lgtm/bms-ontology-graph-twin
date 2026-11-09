// Shared kit for the waterside and terminal models (FCU, chiller, boiler, pump): pipe runs with water particles that
// double as anchor paths, sensors on pipes, valves along a pipe, ghosts for required slots with no point, pin
// positions, and the model API the page expects (same as AHU.build / VAV.build).
const Plant = (() => {
  const { V, MAT, C, box } = Parts;
  const INNER = new THREE.MeshStandardMaterial({ color: 0x8a8e95, metalness: 0.35, roughness: 0.55, side: THREE.BackSide });

  // Cylinder along x. With `cut` > 0 the front-top (towards the hero camera) is cut away and the inside shows.
  function shell(x0, x1, y, z, r, mat = MAT.skin, { cut = 0, inner = INNER } = {}) {
    const g = new THREE.Group(), len = x1 - x0, mid = -0.5;
    const layers = cut ? [[r, mat], [r - 0.03, inner]] : [[r, mat]];
    for (const [rr, m] of layers) {
      const geo = cut ? new THREE.CylinderGeometry(rr, rr, len, 56, 1, true, mid + cut, Math.PI * 2 - 2 * cut)
                      : new THREE.CylinderGeometry(rr, rr, len, 56);
      const c = Parts.mesh(geo, m);
      c.rotation.z = -Math.PI / 2;
      c.position.set((x0 + x1) / 2, y, z);
      g.add(c);
    }
    if (cut) for (const s of [-1, 1]) {  // bright edge strips on the cut
      const a = mid + s * cut;
      g.add(box(V(x0, y - r * Math.sin(a) - 0.015, z + r * Math.cos(a) - 0.015), V(x1, y - r * Math.sin(a) + 0.015, z + r * Math.cos(a) + 0.015), MAT.trim));
    }
    for (const x of [x0, x1]) {
      const ring = Parts.mesh(new THREE.TorusGeometry(r + 0.01, 0.03, 8, 56), MAT.flange);
      ring.rotation.y = Math.PI / 2;
      ring.position.set(x, y, z);
      g.add(ring);
    }
    return g;
  }

  // Dished end (water box) on a shell end: s = -1 faces -x, +1 faces +x.
  function dish(x, y, z, r, s, mat = MAT.skin) {
    const d = Parts.mesh(new THREE.SphereGeometry(r, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), mat);
    d.scale.set(1, 0.35, 1);
    d.rotation.z = -s * Math.PI / 2;
    d.position.set(x, y, z);
    return d;
  }

  // Status lamp: green running, grey off.
  function lamp(r = 0.05) {
    const mat = new THREE.MeshStandardMaterial({ color: 0x6b7178, emissive: 0x6b7178, emissiveIntensity: 0.1, roughness: 0.4 });
    const m = Parts.mesh(new THREE.SphereGeometry(r, 16, 12), mat);
    m.userData.set = on => { const c = on ? 0x2fd36b : 0x6b7178; mat.color.set(c); mat.emissive.set(c); mat.emissiveIntensity = on ? 2 : 0.1; };
    return m;
  }

  // Control panel: a cabinet with a lit screen and a status lamp.
  function panel(w = 0.6, h = 0.8, d = 0.25) {
    const g = new THREE.Group();
    g.add(box(V(-w / 2, -h / 2, -d / 2), V(w / 2, h / 2, d / 2), new THREE.MeshStandardMaterial({ color: 0xd3d6da, roughness: 0.5 }), 0.03));
    g.add(box(V(-w * 0.32, h * 0.08, d / 2 - 0.005), V(w * 0.32, h * 0.36, d / 2 + 0.005), C.screen));
    const l = lamp(0.035);
    l.position.set(w * 0.3, -h * 0.25, d / 2 + 0.02);
    g.add(l);
    g.userData.lamp = l;
    return g;
  }

  // Point and tangent at `at` (0-1) along a polyline.
  function along(pts, at) {
    const lens = pts.slice(1).map((p, i) => p.distanceTo(pts[i])), L = lens.reduce((a, b) => a + b, 0);
    let s = Math.min(1, Math.max(0, at)) * L;
    for (let i = 0; i < lens.length; i++) {
      if (s <= lens[i] || i === lens.length - 1) {
        const dir = pts[i + 1].clone().sub(pts[i]).normalize();
        return { p: pts[i].clone().addScaledVector(dir, Math.min(s, lens[i])), dir };
      }
      s -= lens[i];
    }
  }

  function kit(data, viewer) {
    const group = new THREE.Group(), parts = {}, paths = {}, water = [], movers = [];
    const add = (name, obj) => { obj.name = name; parts[name] = obj; group.add(obj); return obj; };
    const label = (text, p, cls) => { const l = viewer.label(text, cls); l.position.copy(p); group.add(l); return l; };
    const navLabel = (text, rel, p) => { const l = label(text, p, rel ? "stream nav" : "stream"); if (rel) l.element.dataset.eq = rel.id; return l; };
    const sib = re => (data.relations?.with || []).find(r => re.test(r.label));

    // A pipe from the unit outwards (`pts[0]` at the unit); `into` runs the water towards the unit.
    function pipe(name, pts, medium, { r = 0.09, into = false } = {}) {
      const g = Parts.pipeRun(pts, medium, r);
      for (const p of [pts[0], pts[pts.length - 1]]) {  // flanges at the ends
        const d = along(pts, p === pts[0] ? 0 : 1).dir;
        const f = Parts.mesh(new THREE.CylinderGeometry(r * 1.45, r * 1.45, 0.05, 24), MAT.flange);
        f.quaternion.setFromUnitVectors(V(0, 1, 0), d);
        f.position.copy(p);
        g.add(f);
      }
      if (name) add(name, g); else group.add(g);
      const pr = Parts.particles(into ? pts.slice().reverse() : pts, Parts.MEDIUM[medium] ?? 0x9aa3ad, { size: r * 0.42, spacing: r * 1.7 });
      group.add(pr.mesh);
      water.push(pr);
      if (name) paths[name] = { pts, r };
      return pr;
    }
    // Put an object on a pipe at `at`, its x axis along the pipe (a valve body).
    function onPipe(pipeName, at, obj) {
      const { p, dir } = along(paths[pipeName].pts, at);
      obj.quaternion.setFromUnitVectors(V(1, 0, 0), dir);
      if (Math.abs(dir.y) > 0.7) obj.rotateX(Math.PI / 2);  // on a riser: the actuator faces the viewer
      obj.position.copy(p);
      return obj;
    }
    function anchor(part, at) {
      const path = paths[part];
      if (path && at != null) {
        const { p, dir } = along(path.pts, at), n = Math.abs(dir.y) > 0.7 ? V(0, 0, 1) : V(0, 1, 0);
        return { p: p.clone().addScaledVector(n, path.r), n, center: p };
      }
      const o = parts[part];
      return o ? { p: o.getWorldPosition(V(0, 0, 0)), n: V(0, 1, 0) } : null;
    }

    function finish({ update, setState, applyTheme, front, pad = [] } = {}) {
      // sensors on pipe anchors (a ghost where a required slot has no point)
      for (const slot of data.slots || []) {
        const a = slot.anchor;
        if (!paths[a.part] || a.at == null || !(slot.points.length || slot.required)) continue;
        const pts = slot.points.map(id => data.points[id]).filter(Boolean);
        const cls = (pts.length ? pts.map(p => p.cls) : slot.classes).find(c => c && c.endsWith("_Sensor")) || "";
        if (!cls && pts.length) continue;  // setpoints only: they stack on the sensor's card
        const kind = cls.includes("Pressure") ? "pressure" : cls.includes("Flow") ? "flow" : "temperature";
        const sg = Parts.sensor(kind, { ghost: !pts.length });
        const an = anchor(a.part, a.at);
        sg.quaternion.setFromUnitVectors(V(0, 1, 0), an.n);
        sg.position.copy(an.p);
        sg.name = `sensor:${slot.role}`;
        group.add(sg);
      }
      // ghosts: required parts (not pipes) with no point in the source. A part other points sit on (a pump motor
      // with a status but no command) stays solid; the missing slot still gets its ghost card.
      const used = new Set(Object.values(data.points).map(p => p.part).filter(Boolean));
      const ghosts = new Set((data.slots || []).filter(s => s.required && !s.points.length).map(s => s.anchor.part));
      for (const name of ghosts) {
        if (paths[name] || !parts[name] || used.has(name)) continue;
        parts[name].traverse(o => { if (o.isMesh) { o.material = C.ghost; o.castShadow = false; } });
      }
      group.updateMatrixWorld(true);
      function pinPoint(part, at) {
        if (paths[part] && at != null) { const an = anchor(part, at); return an.p.addScaledVector(an.n, 0.36); }
        const o = parts[part];
        if (!o) return null;
        const b = new THREE.Box3().setFromObject(o), c = b.getCenter(V(0, 0, 0));
        return V(c.x, c.y, b.max.z);
      }
      group.traverse(o => { if (o.isMesh && !o.isInstancedMesh && o.material !== MAT.glass && o.material !== C.ghost && !o.material.transparent) o.castShadow = true; });
      const bounds = new THREE.Box3().setFromObject(group);
      for (const p of pad) bounds.expandByPoint(p);
      return {
        group, parts, paths, bounds, anchor, pinPoint, ghosts: [...ghosts],
        update: (t, dt) => { water.forEach(w => w.update(t, dt)); movers.forEach(f => f(t, dt)); update?.(t, dt); },
        setState: s => setState?.(s),
        applyTheme: P => applyTheme?.(P),
        setFrontWall: on => { if (front) front.visible = on; },
      };
    }
    return { group, parts, paths, add, label, navLabel, sib, pipe, onPipe, anchor, finish, movers, water, v: data.variant || {} };
  }

  return { kit, shell, dish, lamp, panel, along, INNER };
})();
