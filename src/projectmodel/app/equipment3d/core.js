// Scene, camera, lights, orbit controls, labels, theme and the animation loop.
// The modules in this folder are inlined into one <script type="module"> by equipment_view.render_html, after the
// three.js imports (THREE, OrbitControls, CSS2DRenderer, ...). Each module is one const, so they share one scope.
const Core = (() => {
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const theme = () => ({
    bg: css("--bg"), text: css("--text"), muted: css("--muted"),
    air: { outside: css("--air-outside"), return: css("--air-return"), mixed: css("--air-mixed"), supply: css("--air-supply") },
    shadow: parseFloat(css("--shadow")), bloom: parseFloat(css("--bloom")), exposure: parseFloat(css("--exposure")),
    dark: getComputedStyle(document.documentElement).colorScheme === "dark",
  });

  function createViewer(container, labelLayer) {
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    renderer.setClearColor(0x000000, 0);  // transparent: the page background shows through, exactly --bg
    renderer.setPixelRatio(Math.min(2, devicePixelRatio));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(renderer.domElement);

    const labels = new CSS2DRenderer({ element: labelLayer });
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 400);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI * 0.495;  // stay above the floor

    // Studio lighting: generated room environment (no asset file), one soft key light, a weak rim light.
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environmentIntensity = 0.32;
    const key = new THREE.DirectionalLight(0xffffff, 2.6);
    key.position.set(-5, 20, 6);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.radius = 6;
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.02;
    Object.assign(key.shadow.camera, { left: -16, right: 16, top: 12, bottom: -12, near: 1, far: 60 });
    scene.add(key, key.target);
    const rim = new THREE.DirectionalLight(0xbcd2ff, 0.6);
    rim.position.set(14, 8, -12);
    scene.add(rim);

    // Ground: shadow only, so it sits on the page background in either theme.
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(200, 200),
      new THREE.ShadowMaterial({ opacity: 0.4 }));
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.6, 0.45, 0.82);
    // Bloom adds light but must keep the canvas transparent, or it paints the page background black.
    Object.assign(bloom.blendMaterial, { blending: THREE.CustomBlending, blendSrc: THREE.OneFactor, blendDst: THREE.OneFactor,
                                         blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor });
    composer.addPass(bloom);
    composer.addPass(new OutputPass());

    const frameFns = [];
    let model = null, P = theme(), fly = null;

    function applyTheme() {
      P = theme();
      ground.material.opacity = P.shadow;
      bloom.strength = P.bloom;
      bloom.enabled = P.bloom > 0;  // bloom on a light page only greys it
      renderer.toneMappingExposure = P.exposure;
      model?.applyTheme?.(P);
    }

    function resize() {
      const w = container.clientWidth, h = container.clientHeight;
      renderer.setSize(w, h);
      composer.setSize(w, h);
      labels.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
    addEventListener("resize", resize);
    resize();

    // Camera presets, relative to the model's bounds. "hero" is the three-quarter view from the front and above.
    const DIRS = { hero: [-0.3, 0.36, 1], front: [0, 0.08, 1], top: [0, 1, 0.02], fit: [-0.3, 0.36, 1] };
    // Camera on `dir` from the bounds' centre, just far enough that every corner of the bounds is in view.
    function preset(name) {
      const box = model.bounds, c = box.getCenter(new THREE.Vector3());
      const dir = new THREE.Vector3(...(DIRS[name] || DIRS.hero)).normalize();
      const fwd = dir.clone().negate(), right = fwd.clone().cross(camera.up).normalize(), up = right.clone().cross(fwd);
      const tv = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)), th = tv * camera.aspect;
      const margin = name === "fit" ? 1.12 : 1.04;
      // Centre the bounds on screen: shift the target to the middle of the corners' extent across the view.
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      const corners = [];
      for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
        const d = new THREE.Vector3(x, y, z).sub(c);
        corners.push(d);
        x0 = Math.min(x0, d.dot(right)); x1 = Math.max(x1, d.dot(right));
        y0 = Math.min(y0, d.dot(up)); y1 = Math.max(y1, d.dot(up));
      }
      const target = c.clone().addScaledVector(right, (x0 + x1) / 2).addScaledVector(up, (y0 + y1) / 2);
      let dist = 0;
      for (const d0 of corners) {
        const d = d0.clone().add(c).sub(target);
        const f = d.dot(fwd);
        dist = Math.max(dist, f + Math.abs(d.dot(right)) * margin / th, f + Math.abs(d.dot(up)) * margin / tv);
      }
      return { pos: target.clone().addScaledVector(dir, dist), target };
    }
    let lastView = "hero", userMoved = false;
    controls.addEventListener("start", () => { userMoved = true; fly = null; });
    addEventListener("resize", () => { if (model && !userMoved) view(lastView, false); });
    function view(name, animate = true) {
      lastView = name;
      userMoved = false;
      const to = preset(name);
      if (!animate) {
        camera.position.copy(to.pos);
        controls.target.copy(to.target);
        controls.update();
        return;
      }
      fly = { from: camera.position.clone(), fromT: controls.target.clone(), to, t: 0 };
    }

    function setModel(m) {
      model = m;
      model.bounds ??= new THREE.Box3().setFromObject(model.group);
      const s = model.bounds.getSize(new THREE.Vector3()).length();
      controls.maxDistance = s * 2.5;
      controls.minDistance = 1.5;
      applyTheme();
    }

    const clock = new THREE.Clock();
    let running = true, raf = 0, frames = 0;
    function frame() {
      if (!running) return;
      raf = requestAnimationFrame(frame);
      frames++;
      const dt = Math.min(clock.getDelta(), 0.1), t = clock.elapsedTime;
      if (fly) {
        fly.t = Math.min(1, fly.t + dt / 0.8);
        const e = fly.t < 0.5 ? 4 * fly.t ** 3 : 1 - (-2 * fly.t + 2) ** 3 / 2;
        camera.position.lerpVectors(fly.from, fly.to.pos, e);
        controls.target.lerpVectors(fly.fromT, fly.to.target, e);
        if (fly.t === 1) fly = null;
      }
      controls.update();
      for (const f of frameFns) f(t, dt);
      model?.update?.(t, dt);
      composer.render();
      labels.render(scene, camera);
    }
    // Pause rendering when the tab is hidden.
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { running = false; cancelAnimationFrame(raf); }
      else if (!running) { running = true; clock.getDelta(); frame(); }
    });
    frame();

    return { scene, camera, renderer, controls, view, setModel, applyTheme, onFrame: f => frameFns.push(f),
             frames: () => frames,
             theme: () => P, label: (text, cls = "stream") => {
               const d = document.createElement("div");
               d.className = cls;
               d.textContent = text;
               return new CSS2DObject(d);
             } };
  }

  return { createViewer, theme };
})();
