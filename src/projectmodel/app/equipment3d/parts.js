// Shared parts, drawn in code: panels, ducts, flanges and flow arrows. Units are metres; x runs with the
// air through the unit, y is up, z points at the viewer (the cut-away side).
const Parts = (() => {
  const V = (x, y, z) => new THREE.Vector3(x, y, z);

  // Sheet-metal finishes. Casing skin darker than its liner, so the cut-away reads as a box with depth.
  const MAT = {
    skin:  new THREE.MeshStandardMaterial({ color: 0x45484d, metalness: 0.6, roughness: 0.45 }),
    liner: new THREE.MeshStandardMaterial({ color: 0x80838a, metalness: 0.3, roughness: 0.6 }),
    trim:  new THREE.MeshStandardMaterial({ color: 0xb4b7bb, metalness: 0.7, roughness: 0.32 }),
    frame: new THREE.MeshStandardMaterial({ color: 0x2c2e32, metalness: 0.5, roughness: 0.5 }),
    seam:  new THREE.MeshStandardMaterial({ color: 0x303236, metalness: 0.3, roughness: 0.7 }),
    duct:  new THREE.MeshStandardMaterial({ color: 0x80838a, metalness: 0.55, roughness: 0.42 }),
    ductIn: new THREE.MeshStandardMaterial({ color: 0x5d6065, metalness: 0.4, roughness: 0.6, side: THREE.DoubleSide }),
    flange: new THREE.MeshStandardMaterial({ color: 0x74777c, metalness: 0.6, roughness: 0.38 }),
    glass: new THREE.MeshPhysicalMaterial({ color: 0x9aa3ad, metalness: 0.1, roughness: 0.15, transparent: true,
                                            opacity: 0.18, depthWrite: false, side: THREE.DoubleSide }),
  };

  function mesh(geo, mat, { cast = true, receive = true } = {}) {
    const m = new THREE.Mesh(geo, mat);
    m.castShadow = cast;
    m.receiveShadow = receive;
    return m;
  }

  // Axis-aligned box from its min and max corners; rounded edges when `r` > 0 (bevelled panels).
  function box(min, max, mat, r = 0) {
    const s = max.clone().sub(min);
    const geo = r > 0 ? new RoundedBoxGeometry(s.x, s.y, s.z, 2, Math.min(r, s.x / 2, s.y / 2, s.z / 2))
                      : new THREE.BoxGeometry(s.x, s.y, s.z);
    const m = mesh(geo, mat);
    m.position.copy(min).add(max).multiplyScalar(0.5);
    return m;
  }

  // Rectangular duct between two points on one axis. `w` is its size on the first other axis (z for a horizontal
  // duct, x for a vertical one), `h` on the second (y, or z). Open ends show the wall thickness; flanges at both.
  function duct(a, b, w, h, { t = 0.04, flanges = true, capA = false, capB = false, name } = {}) {
    const g = new THREE.Group();
    g.name = name || "";
    const d = b.clone().sub(a), axis = Math.abs(d.x) > 1e-6 ? "x" : Math.abs(d.y) > 1e-6 ? "y" : "z";
    const [u, v] = { x: ["z", "y"], y: ["x", "z"], z: ["x", "y"] }[axis];
    const lo = a[axis] < b[axis] ? a : b, hi = a[axis] < b[axis] ? b : a;
    const c = a.clone().add(b).multiplyScalar(0.5);
    const wall = (du, dv, su, sv, mat) => {
      const min = c.clone(), max = c.clone();
      min[axis] = lo[axis]; max[axis] = hi[axis];
      min[u] += du - su / 2; max[u] += du + su / 2;
      min[v] += dv - sv / 2; max[v] += dv + sv / 2;
      return box(min, max, mat);
    };
    for (const s of [-1, 1]) {
      g.add(wall(s * (w / 2 - t / 2), 0, t, h, MAT.duct));
      g.add(wall(0, s * (h / 2 - t / 2), w - 2 * t, t, MAT.duct));
    }
    const ring = (p) => {
      const f = 0.05, k = 0.035;
      for (const s of [-1, 1]) {
        for (const [du, dv, su, sv] of [[s * (w / 2 + f / 2), 0, f, h + 2 * f], [0, s * (h / 2 + f / 2), w, f]]) {
          const min = p.clone(), max = p.clone();
          min[axis] -= k / 2; max[axis] += k / 2;
          min[u] += du - su / 2; max[u] += du + su / 2;
          min[v] += dv - sv / 2; max[v] += dv + sv / 2;
          g.add(box(min, max, MAT.flange));
        }
      }
    };
    if (flanges) { ring(lo); ring(hi); }
    const cap = p => {
      const min = p.clone(), max = p.clone();
      min[axis] -= t / 2; max[axis] += t / 2;
      min[u] -= w / 2; max[u] += w / 2;
      min[v] -= h / 2; max[v] += h / 2;
      g.add(box(min, max, MAT.duct));
    };
    if (capA) cap(a);
    if (capB) cap(b);
    return g;
  }

  // Closed box where ducts meet (a mitred elbow or tee seen from outside).
  function joint(center, sx, sy, sz, name) {
    const m = box(center.clone().sub(V(sx / 2, sy / 2, sz / 2)), center.clone().add(V(sx / 2, sy / 2, sz / 2)), MAT.duct, 0.03);
    m.name = name || "";
    return m;
  }

  // Flow arrows: chevrons that scroll along a polyline, lying in the plane whose normal is `normal`.
  const CHEVRON = (() => {
    const s = new THREE.Shape();
    s.moveTo(-0.07, 0.16); s.lineTo(0.09, 0); s.lineTo(-0.07, -0.16);
    s.lineTo(-0.15, -0.16); s.lineTo(0.01, 0); s.lineTo(-0.15, 0.16); s.closePath();
    return new THREE.ExtrudeGeometry(s, { depth: 0.012, bevelEnabled: false });
  })();

  function flow(points, color, { normal = V(0, 0, 1), spacing = 0.42, speed = 0.9, size = 1, groups = 3, gap = 0.16 } = {}) {
    const pts = points.map(p => p.clone()), seg = [];
    let L = 0;
    for (let i = 1; i < pts.length; i++) {
      const len = pts[i].distanceTo(pts[i - 1]);
      seg.push({ a: pts[i - 1], dir: pts[i].clone().sub(pts[i - 1]).normalize(), s0: L, len });
      L += len;
    }
    // Chevrons come in small trains (">>>" as in BAS graphics), one train every `spacing * groups + gap`.
    const pitch = groups * gap + spacing;
    const trains = Math.max(1, Math.floor(L / pitch)), count = trains * groups;
    const mat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 1.15, roughness: 0.5,
                                                 metalness: 0, transparent: true });
    const inst = new THREE.InstancedMesh(CHEVRON, mat, count);
    inst.frustumCulled = false;
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = V(1, 1, 1), basis = new THREE.Matrix4();
    let rate = speed;
    function at(s) {
      s = ((s % L) + L) % L;
      const k = seg.find(k => s <= k.s0 + k.len) || seg[seg.length - 1];
      return { p: k.a.clone().addScaledVector(k.dir, s - k.s0), dir: k.dir };
    }
    let phase = 0;
    function update(t, dt) {
      phase += dt * rate;
      for (let i = 0; i < count; i++) {
        const train = Math.floor(i / groups), j = i % groups;
        const s = train * (L / trains) + j * gap + phase;
        const { p, dir } = at(s);
        const y = normal.clone().cross(dir).normalize();
        basis.makeBasis(dir, y, normal);
        q.setFromRotationMatrix(basis);
        const u = ((s % L) + L) % L, fade = Math.min(1, u / 0.35, (L - u) / 0.35);
        sc.setScalar(size * Math.max(0.001, fade));
        m.compose(p, q, sc);
        inst.setMatrixAt(i, m);
      }
      inst.instanceMatrix.needsUpdate = true;
    }
    update(0, 0);
    return { mesh: inst, update, setColor: c => { mat.color.set(c); mat.emissive.set(c); },
             setSpeed: r => { rate = r; } };
  }

  return { V, MAT, mesh, box, duct, joint, flow };
})();
