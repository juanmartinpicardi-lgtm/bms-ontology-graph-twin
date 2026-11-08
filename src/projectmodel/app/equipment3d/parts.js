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

  // --- components ------------------------------------------------------------------------------------
  // Each builder returns a Group centred on its own origin; x is the airflow direction.

  // Filter media: a canvas-generated fibre texture (no asset file), tinted per filter.
  const FIBRE = (() => {
    const c = document.createElement("canvas");
    c.width = c.height = 256;
    const g = c.getContext("2d");
    g.fillStyle = "#cfcfcf";
    g.fillRect(0, 0, 256, 256);
    let seed = 7;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < 2600; i++) {
      const x = rnd() * 256, y = rnd() * 256, a = rnd() * Math.PI, l = 4 + rnd() * 14, v = 150 + rnd() * 105;
      g.strokeStyle = `rgba(${v},${v},${v},${0.25 + rnd() * 0.4})`;
      g.lineWidth = 0.6 + rnd();
      g.beginPath(); g.moveTo(x, y); g.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l); g.stroke();
    }
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  })();
  const media = (color, repeat) => {
    const map = FIBRE.clone();
    map.repeat.set(...repeat);
    map.needsUpdate = true;
    return new THREE.MeshStandardMaterial({ color, map, roughness: 0.95, metalness: 0, side: THREE.DoubleSide });
  };
  const C = {
    copper: new THREE.MeshStandardMaterial({ color: 0xc27a43, metalness: 0.9, roughness: 0.28 }),
    brass:  new THREE.MeshStandardMaterial({ color: 0xc9a443, metalness: 0.9, roughness: 0.3 }),
    fin:    new THREE.MeshStandardMaterial({ color: 0xc4c9cf, metalness: 0.85, roughness: 0.32 }),
    actuator: new THREE.MeshStandardMaterial({ color: 0x2b2d31, metalness: 0.2, roughness: 0.55 }),
    sensor: new THREE.MeshStandardMaterial({ color: 0xe9ebee, metalness: 0.05, roughness: 0.45 }),
    blade:  new THREE.MeshStandardMaterial({ color: 0xa7abb1, metalness: 0.75, roughness: 0.3 }),
    wheel:  new THREE.MeshStandardMaterial({ color: 0x23262a, metalness: 0.6, roughness: 0.4 }),
    screen: new THREE.MeshStandardMaterial({ color: 0x0b1a2a, emissive: 0x1c6fd1, emissiveIntensity: 0.6, roughness: 0.3 }),
    ghost:  new THREE.MeshStandardMaterial({ color: 0x9aa3ad, transparent: true, opacity: 0.28, depthWrite: false }),
  };
  const MEDIUM = { chilled_water: 0x2f80d8, hot_water: 0xd6493f, condenser_water: 0x2fb39c };

  function frameAround(g, w, h, d, t = 0.05) {  // rectangular frame in the y-z plane: h along y, d along z
    for (const s of [-1, 1]) {
      g.add(box(V(-w / 2, s * h / 2 - t / 2, -d / 2), V(w / 2, s * h / 2 + t / 2, d / 2), MAT.frame));
      g.add(box(V(-w / 2, -h / 2, s * d / 2 - t / 2), V(w / 2, h / 2, s * d / 2 + t / 2), MAT.frame));
    }
  }

  // Pleated panel filter: the media folds in a zigzag up the face (horizontal pleats), so the cut-away edge shows
  // the pleat profile. Frame top, bottom and back only: the front post is cut away with the casing.
  function pleatedFilter(h, d, { depth = 0.2, pitch = 0.09, color = 0xd9c07a } = {}) {
    const g = new THREE.Group(), n = Math.round(h / pitch) * 2, pos = [], uv = [], idx = [];
    for (let i = 0; i <= n; i++) {
      const y = -h / 2 + (i / n) * h, x = (i % 2 ? 1 : -1) * depth / 2;
      for (const z of [-d / 2, d / 2]) { pos.push(x, y, z); uv.push((z + d / 2) / d * 6, i / n * 8); }
      if (i) { const k = 2 * i; idx.push(k - 2, k, k - 1, k - 1, k, k + 1); }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    geo.setIndex(idx);
    geo.computeVertexNormals();
    g.add(mesh(geo, media(color, [1, 1])));
    const w = depth + 0.06, t = 0.05;
    for (const s of [-1, 1]) g.add(box(V(-w / 2, s * h / 2 - t / 2, -d / 2), V(w / 2, s * h / 2 + t / 2, d / 2), MAT.frame));
    g.add(box(V(-w / 2, -h / 2, -d / 2 - t / 2), V(w / 2, h / 2, -d / 2 + t / 2), MAT.frame));
    return g;
  }

  // Bag filter: a header frame with pockets reaching downstream (lathe profiles, flattened), stacked up the face
  // so their tapered profiles read from the cut-away side.
  function bagFilter(h, d, { length = 1.0, pockets = 6, color = 0xd98a35 } = {}) {
    const g = new THREE.Group(), pw = h / pockets;
    const prof = [];
    for (let i = 0; i <= 16; i++) {
      const u = i / 16, r = u < 0.92 ? 1 - 0.28 * u : (1 - 0.28 * 0.92) * Math.sqrt(Math.max(0, 1 - ((u - 0.92) / 0.08) ** 2));
      prof.push(new THREE.Vector2(Math.max(r, 0.001), u * length));
    }
    const geo = new THREE.LatheGeometry(prof, 24);
    const mat = media(color, [3, 2]);
    for (let i = 0; i < pockets; i++) {
      const p = mesh(geo, mat);
      p.rotation.z = -Math.PI / 2;               // lathe axis y -> +x (downstream)
      p.scale.set(pw / 2 * 0.84, 1, d / 2 * 0.96);  // flat and as wide as the unit
      p.position.set(0.04, -h / 2 + pw * (i + 0.5), 0);
      g.add(p);
    }
    frameAround(g, 0.08, h, d, 0.07);
    return g;
  }

  // Finned coil: a fin pack (instanced plates parallel to the airflow), copper U-bends and headers on the front
  // end, supply / return stubs coloured by medium. `stub` is where the pipes leave the unit (in coil coordinates).
  function coil(h, d, { thick = 0.34, medium = "chilled_water", pitch = 0.05 } = {}) {
    const g = new THREE.Group();
    const nf = Math.floor(d / pitch), fin = new THREE.BoxGeometry(thick, h, 0.01);
    const fins = new THREE.InstancedMesh(fin, C.fin, nf), m = new THREE.Matrix4();
    for (let i = 0; i < nf; i++) fins.setMatrixAt(i, m.makeTranslation(0, 0, -d / 2 + (i + 0.5) * pitch));
    fins.castShadow = fins.receiveShadow = true;
    g.add(fins);
    // tube sheet at both ends, U-bends on the front end
    for (const s of [-1, 1]) g.add(box(V(-thick / 2 - 0.02, -h / 2, s * d / 2 - 0.02), V(thick / 2 + 0.02, h / 2, s * d / 2 + 0.02), MAT.liner));
    const rows = Math.floor(h / 0.13), bend = new THREE.TorusGeometry(thick * 0.3, 0.017, 8, 16, Math.PI);
    const bends = new THREE.InstancedMesh(bend, C.copper, rows), q = new THREE.Quaternion().setFromEuler(new THREE.Euler(Math.PI / 2, 0, 0));
    for (let i = 0; i < rows; i++) bends.setMatrixAt(i, m.compose(V(0, -h / 2 + 0.09 + i * (h - 0.18) / (rows - 1), d / 2 + 0.02), q, V(1, 1, 1)));
    g.add(bends);
    const pipe = (a, b, r, mat) => {
      const len = a.distanceTo(b), c = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 16), mat);
      c.position.copy(a).add(b).multiplyScalar(0.5);
      c.quaternion.setFromUnitVectors(V(0, 1, 0), b.clone().sub(a).normalize());
      c.castShadow = true;
      return c;
    };
    const hz = d / 2 + 0.12, med = new THREE.MeshStandardMaterial({ color: MEDIUM[medium] ?? 0x888888, metalness: 0.2, roughness: 0.5 });
    const ends = {};
    for (const [k, x] of [["supply", -thick * 0.3], ["return", thick * 0.3]]) {
      g.add(pipe(V(x, -h / 2 + 0.05, hz), V(x, h / 2 - 0.05, hz), 0.04, C.copper));       // header
      const y = k === "supply" ? -h / 2 + 0.12 : -h / 2 + 0.32;
      g.add(pipe(V(x, y, hz), V(x, y, hz + 0.55), 0.05, med));                             // stub, insulated colour
      ends[k] = V(x, y, hz + 0.55);
    }
    g.userData.stubs = ends;
    g.userData.pipe = pipe;
    g.userData.medium = med;
    return g;
  }

  // Two-way valve with actuator; the indicator needle shows the command (0-1).
  function valve(command = 0.5, medMat) {
    const g = new THREE.Group();
    const body = new THREE.Mesh(new THREE.SphereGeometry(0.08, 20, 14), C.brass);
    body.scale.set(1.2, 1, 1);
    g.add(body);
    for (const s of [-1, 1]) {
      const f = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.055, 0.08, 16), medMat || C.brass);
      f.rotation.z = Math.PI / 2;
      f.position.x = s * 0.12;
      g.add(f);
    }
    g.add(new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.14, 10), MAT.trim).translateY(0.12));
    g.add(box(V(-0.11, 0.18, -0.08), V(0.11, 0.36, 0.08), C.actuator, 0.025));
    const needle = box(V(-0.006, 0, 0.081), V(0.006, 0.07, 0.086), new THREE.MeshStandardMaterial({ color: 0xf2b134, emissive: 0xf2b134, emissiveIntensity: 0.6 }));
    needle.position.set(0, 0.24, 0);
    needle.rotation.z = (0.5 - command) * Math.PI * 0.8;
    g.add(needle);
    g.userData.setCommand = c => { needle.rotation.z = (0.5 - c) * Math.PI * 0.8; };
    g.traverse(o => { if (o.isMesh) o.castShadow = true; });
    return g;
  }

  // Opposed-blade damper. Blades run along z (length `w`), stacked over `span` along the axis `stack` ("y" for a
  // damper across a horizontal duct, "x" for one across a vertical duct). `open` 0 = closed, 1 = fully open.
  function damper(w, span, { stack = "y", open = 0.5, chord = 0.17 } = {}) {
    const g = new THREE.Group(), n = Math.max(2, Math.round(span / (chord * 0.92)));
    const blades = [];
    for (let i = 0; i < n; i++) {
      const b = new THREE.Mesh(new THREE.BoxGeometry(stack === "y" ? 0.012 : chord, stack === "y" ? chord : 0.012, w), C.blade);
      const p = -span / 2 + (i + 0.5) * span / n;
      b.position[stack] = p;
      b.castShadow = true;
      g.add(b);
      blades.push(b);
    }
    const set = o => blades.forEach((b, i) => { b.rotation.z = (i % 2 ? 1 : -1) * o * Math.PI / 2 * (stack === "y" ? 1 : -1); });
    set(open);
    // frame
    const t = 0.05;
    if (stack === "y") frameAround(g, 0.08, span + t, w + t, t);
    else for (const s of [-1, 1]) {
      g.add(box(V(s * (span / 2 + t / 2) - t / 2, -0.04, -w / 2 - t), V(s * (span / 2 + t / 2) + t / 2, 0.04, w / 2 + t), MAT.frame));
      g.add(box(V(-span / 2, -0.04, s * (w / 2 + t / 2) - t / 2), V(span / 2, 0.04, s * (w / 2 + t / 2) + t / 2), MAT.frame));
    }
    g.userData.setOpen = set;
    return g;
  }

  // Housed centrifugal fan, shaft along z (across the unit, as in a DWDI AHU fan). The inlet ring glows with the
  // fan status: green running, red tripped, grey off. Returns {group, wheel, setStatus}.
  function fan({ r = 0.62, width = 0.8, housing = [1.7, 1.7, 1.3] } = {}) {
    const g = new THREE.Group(), [hw, hh, hd] = housing;
    // housing: front panel with a round inlet, back, sides
    const sh = new THREE.Shape();
    sh.moveTo(-hw / 2, -hh / 2); sh.lineTo(hw / 2, -hh / 2); sh.lineTo(hw / 2, hh / 2); sh.lineTo(-hw / 2, hh / 2); sh.closePath();
    const hole = new THREE.Path(); hole.absarc(0, 0, r * 1.02, 0, Math.PI * 2, true);
    sh.holes.push(hole);
    const panel = new THREE.ExtrudeGeometry(sh, { depth: 0.04, bevelEnabled: true, bevelSize: 0.012, bevelThickness: 0.012, bevelSegments: 2, curveSegments: 48 });
    g.add(mesh(panel, MAT.skin).translateZ(hd / 2 - 0.04));
    g.add(box(V(-hw / 2, -hh / 2, -hd / 2), V(hw / 2, hh / 2, -hd / 2 + 0.04), MAT.skin));
    for (const s of [-1, 1]) {
      g.add(box(V(s * hw / 2 - 0.02, -hh / 2, -hd / 2), V(s * hw / 2 + 0.02, hh / 2, hd / 2), MAT.skin));
      g.add(box(V(-hw / 2, s * hh / 2 - 0.02, -hd / 2), V(hw / 2, s * hh / 2 + 0.02, hd / 2), MAT.skin));
    }
    // inlet bell + status ring
    const bell = new THREE.Mesh(new THREE.TorusGeometry(r * 1.03, 0.045, 12, 64), MAT.trim);
    bell.position.z = hd / 2 + 0.01;
    g.add(bell);
    const glowMat = new THREE.MeshStandardMaterial({ color: 0x2fd36b, emissive: 0x2fd36b, emissiveIntensity: 2.2, roughness: 0.4 });
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r * 0.96, 0.018, 8, 64), glowMat);
    ring.position.z = hd / 2 + 0.02;
    g.add(ring);
    // wheel: back plate, shroud ring, hub, backward-curved blades (instanced)
    const wheel = new THREE.Group();
    wheel.add(new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.03, 48), C.wheel).rotateX(Math.PI / 2).translateY(-width / 2));
    wheel.add(new THREE.Mesh(new THREE.TorusGeometry(r * 0.9, 0.03, 8, 48), C.wheel).translateZ(width / 2));
    wheel.add(new THREE.Mesh(new THREE.CylinderGeometry(r * 0.2, r * 0.2, width, 24), MAT.trim).rotateX(Math.PI / 2));
    const nb = 28, blade = new THREE.BoxGeometry(r * 0.42, 0.012, width * 0.96);
    const bladeMat = new THREE.MeshStandardMaterial({ color: 0x3a3e44, emissive: 0x2fd36b, emissiveIntensity: 0.35, metalness: 0.6, roughness: 0.35 });
    const blades = new THREE.InstancedMesh(blade, bladeMat, nb), m = new THREE.Matrix4(), q = new THREE.Quaternion();
    for (let i = 0; i < nb; i++) {
      const a = (i / nb) * Math.PI * 2;
      q.setFromAxisAngle(V(0, 0, 1), a + 0.55);
      blades.setMatrixAt(i, m.compose(V(Math.cos(a) * r * 0.74, Math.sin(a) * r * 0.74, 0), q, V(1, 1, 1)));
    }
    wheel.add(blades);
    wheel.traverse(o => { if (o.isMesh) o.castShadow = true; });
    g.add(wheel);
    const STATUS = { on: 0x2fd36b, tripped: 0xf04438, off: 0x6b7178 };
    const setStatus = s => {
      const c = STATUS[s] ?? STATUS.off;
      glowMat.color.set(c); glowMat.emissive.set(c);
      glowMat.emissiveIntensity = s === "off" ? 0.1 : 2.2;
      bladeMat.emissive.set(c); bladeMat.emissiveIntensity = s === "off" ? 0 : 0.35;
    };
    return { group: g, wheel, setStatus };
  }

  function motor(len = 0.55, r = 0.2) {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 28), new THREE.MeshStandardMaterial({ color: 0x2f5d8c, metalness: 0.5, roughness: 0.45 })).rotateX(Math.PI / 2));
    for (let i = 0; i < 10; i++) {  // cooling fins
      const a = i / 10 * Math.PI * 2;
      g.add(box(V(Math.cos(a) * r - 0.01, Math.sin(a) * r - 0.01, -len / 2 + 0.05), V(Math.cos(a) * r + 0.01, Math.sin(a) * r + 0.01, len / 2 - 0.05), MAT.frame));
    }
    g.add(box(V(-r * 0.9, -r - 0.08, -len / 2), V(r * 0.9, -r, len / 2), MAT.frame));
    g.traverse(o => { if (o.isMesh) o.castShadow = true; });
    return g;
  }

  // VFD: a wall-mounted drive box with a lit display (the readout text is a label, added with the point labels).
  function vfd() {
    const g = new THREE.Group();
    g.add(box(V(-0.2, -0.3, -0.09), V(0.2, 0.3, 0.09), new THREE.MeshStandardMaterial({ color: 0xd8dade, metalness: 0.1, roughness: 0.5 }), 0.025));
    g.add(box(V(-0.13, 0.08, 0.088), V(0.13, 0.22, 0.096), C.screen));
    for (let i = 0; i < 3; i++) g.add(box(V(-0.12 + i * 0.09, -0.06, 0.088), V(-0.06 + i * 0.09, -0.02, 0.096), MAT.frame));
    g.traverse(o => { if (o.isMesh) o.castShadow = true; });
    return g;
  }

  // Sensor heads on a stalk; the probe goes the other way into the duct. `kind`: temperature, humidity, pressure,
  // flow, generic. Built pointing up (+y); the caller orients it to the mounting surface normal.
  function sensor(kind = "temperature", { ghost = false } = {}) {
    const g = new THREE.Group(), mat = ghost ? C.ghost : C.sensor;
    g.add(new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.16, 10), ghost ? C.ghost : MAT.trim).translateY(0.08));
    g.add(new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.3, 8), ghost ? C.ghost : MAT.trim).translateY(-0.15));
    if (kind === "humidity") {
      g.add(new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.075, 0.16, 20), mat).translateY(0.24));
      for (let i = 0; i < 4; i++) g.add(new THREE.Mesh(new THREE.TorusGeometry(0.077, 0.006, 6, 20), MAT.frame).rotateX(Math.PI / 2).translateZ(-0.19 - i * 0.03));
    } else {
      g.add(box(V(-0.1, 0.16, -0.075), V(0.1, 0.32, 0.075), mat, 0.03));
      const dial = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.03, 14), ghost ? C.ghost : MAT.frame);
      dial.rotation.x = Math.PI / 2;
      dial.position.set(0, 0.24, 0.08);
      g.add(dial);
    }
    if (kind === "pressure" && !ghost) {  // impulse tubes from the transmitter down to the duct
      const path = new THREE.CatmullRomCurve3([V(0.1, 0.22, 0), V(0.22, 0.2, 0), V(0.26, 0.02, 0), V(0.26, -0.06, 0)]);
      g.add(new THREE.Mesh(new THREE.TubeGeometry(path, 16, 0.01, 6), new THREE.MeshStandardMaterial({ color: 0x2f80d8, roughness: 0.6 })));
    }
    g.traverse(o => { if (o.isMesh) o.castShadow = !ghost; });
    return g;
  }

  // Flow measuring station: a grid of pitot tubes across the duct section (y-z plane).
  function flowStation(h, d) {
    const g = new THREE.Group();
    for (let i = 1; i < 5; i++) g.add(box(V(-0.012, -h / 2, -d / 2 + i * d / 5 - 0.012), V(0.012, h / 2, -d / 2 + i * d / 5 + 0.012), MAT.trim));
    for (let i = 1; i < 4; i++) g.add(box(V(-0.012, -h / 2 + i * h / 4 - 0.012, -d / 2), V(0.012, -h / 2 + i * h / 4 + 0.012, d / 2), MAT.trim));
    frameAround(g, 0.06, h, d, 0.04);
    return g;
  }

  return { V, MAT, C, MEDIUM, mesh, box, duct, joint, flow, pleatedFilter, bagFilter, coil, valve, damper, fan, motor,
           vfd, sensor, flowStation };
})();
