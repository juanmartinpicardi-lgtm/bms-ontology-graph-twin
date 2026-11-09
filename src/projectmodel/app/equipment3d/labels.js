// Point labels: one pin per anchor (a dot on the part, a leader line and a card). Several points at one anchor stack
// in one card. Detail follows distance: names only when zoomed out, value when at overview, class and confidence
// when close or hovered. Cards are pushed apart in screen space so they never overlap.
const Labels = (() => {
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // A value chip, refreshed in place by the page (`.pval[data-v]`); `v` is {text, state} from sim.js.
  const chip = (id, v) => `<span class="pval sim ${v?.state ? "st-" + v.state : ""}" data-v="${esc(id)}" ` +
    `title="Simulated value; unit inferred from the class">${esc(v?.text ?? "—")}</span>`;

  function create(viewer, model, data, { onSelect, value = () => null } = {}) {
    const pins = [], byPoint = new Map();
    // Group placed points by their (possibly sub-equipment-shifted) anchor.
    const groups = new Map();
    for (const [id, p] of Object.entries(data.points)) {
      if (!p.part) continue;
      const key = `${p.part}@${p.at ?? ""}`;
      if (!groups.has(key)) groups.set(key, { part: p.part, at: p.at, ids: [] });
      groups.get(key).ids.push(id);
    }
    // Ghost pins: required slots with nothing in them. At an anchor other points share (a pump's missing command on
    // the motor that has its status), a muted row in that card instead.
    const ghostRow = role => `<div class="prow"><span class="pname">${esc(role.replace(/_/g, " "))}</span><span class="pval muted">expected, not found</span></div>`;
    for (const s of data.slots || []) {
      if (s.required && !s.points.length) {
        const key = `${s.anchor.part}@${s.anchor.at ?? ""}`;
        if (!groups.has(key)) groups.set(key, { part: s.anchor.part, at: s.anchor.at, ids: [], ghost: s.role });
        else (groups.get(key).missing ??= []).push(s.role);
      }
    }
    for (const [key, g] of groups) {
      const pos = model.pinPoint(g.part, g.at);
      if (!pos) continue;
      g.ids.sort((a, b) => data.points[a].label.localeCompare(data.points[b].label));
      const el = document.createElement("div");
      el.className = "pin" + (g.ghost ? " ghost" : "");
      el.innerHTML = `<span class="dot"></span><svg class="leader"><line x1="0" y1="0" x2="0" y2="0"/></svg><div class="pcard"></div>`;
      const card = el.querySelector(".pcard"), line = el.querySelector("line");
      card.innerHTML = g.ghost
        ? ghostRow(g.ghost)
        : g.ids.map(id => {
            const p = data.points[id];
            return `<div class="prow" data-id="${esc(id)}"><span class="sdot s-${esc(p.status)}" title="${esc(p.status)}"></span>` +
                   `<span class="pname">${esc(p.label)}</span>${chip(id, value(id))}` +
                   `<span class="pcls">${esc(p.cls)} · ${(p.confidence ?? 0).toFixed(2)}</span></div>`;
          }).join("") + (g.missing || []).map(ghostRow).join("");
      const obj = new CSS2DObject(el);
      obj.position.copy(pos);
      viewer.scene.add(obj);
      const pin = { key, el, card, line, obj, pos, ids: g.ids, ghost: !!g.ghost, w: 0, h: 0, mode: "" };
      pins.push(pin);
      for (const id of g.ids) byPoint.set(id, pin);
      card.addEventListener("mouseenter", () => { pin.hover = true; });
      card.addEventListener("mouseleave", () => { pin.hover = false; });
      card.addEventListener("click", e => {
        const row = e.target.closest(".prow");
        if (row?.dataset.id) onSelect?.(row.dataset.id);
      });
    }

    // One "no point in source" chip under the filter bank when the export has no point for any filter (Alpha).
    const fixed = [];  // chips that stay put; cards avoid them
    const filters = ["pre_filter", "bag_filter"].filter(f => model.parts[f]);
    if (filters.length && !Object.values(data.points).some(p => filters.includes(p.part))) {
      const el = document.createElement("div");
      el.className = "nopoint";
      el.textContent = "filters · no point in source";
      const o = new CSS2DObject(el), c = new THREE.Vector3();
      for (const f of filters) c.add(model.pinPoint(f, null));
      o.position.copy(c.divideScalar(filters.length)).setY(0.05);  // on the floor, under the casing
      viewer.scene.add(o);
      fixed.push({ el, pos: o.position });
    }

    const v3 = new THREE.Vector3();
    let selected = null, frame = 0;
    function layout() {
      if (frame++ % 2) return;  // every other frame is plenty
      const cam = viewer.camera, W = innerWidth, H = innerHeight, hero = model.heroDistance || 25;
      const placed = [];
      for (const f of fixed) {
        v3.copy(f.pos).project(cam);
        const w = f.el.offsetWidth, h = f.el.offsetHeight, x = (v3.x + 1) / 2 * W - w / 2, y = (1 - v3.y) / 2 * H - h / 2;
        if (v3.z <= 1) placed.push({ x, y, w, h });
      }
      // screen chrome (details panel, component dock) and the model's own labels (air streams, links) are taken
      for (const el of [...["panel", "dock", "tools"].map(id => document.getElementById(id)),
                        ...viewer.labelLayer.querySelectorAll(".stream, .morechip")]) {
        const r = el?.getBoundingClientRect();
        if (r?.width) placed.push({ x: r.left, y: r.top, w: r.width, h: r.height });
      }
      const vis = [];
      for (const p of pins) {
        v3.copy(p.pos).project(cam);
        if (v3.z > 1) continue;  // behind the camera (CSS2DRenderer hides it)
        const d = cam.position.distanceTo(p.pos);
        const mode = p.hover || selected === p || d < hero * 0.45 ? "near" : d > hero * 1.35 ? "far" : "mid";
        if (mode !== p.mode) { p.el.dataset.mode = p.mode = mode; p.w = 0; }
        if (!p.w) { p.w = p.card.offsetWidth; p.h = p.card.offsetHeight; }
        vis.push({ p, sx: (v3.x + 1) / 2 * W, sy: (1 - v3.y) / 2 * H });
      }
      vis.sort((a, b) => a.sy - b.sy || a.sx - b.sx);
      const free = (x, y, w, h) => x > 4 && y > 60 && x + w < W - 4 && y + h < H - 4 &&
        !placed.some(r => x < r.x + r.w + 6 && x + w + 6 > r.x && y < r.y + r.h + 4 && y + h + 4 > r.y);
      for (const { p, sx, sy } of vis) {
        const { w, h } = p, cands = [];
        for (const k of [0, 1, 2, 3, 4]) {
          const up = 22 + k * (h + 8), down = 18 + k * (h + 8);
          cands.push([14, -up - h], [-w - 14, -up - h], [14, down], [-w - 14, down]);
        }
        let [dx, dy] = cands.find(([dx, dy]) => free(sx + dx, sy + dy, w, h)) || cands[0];
        placed.push({ x: sx + dx, y: sy + dy, w, h });
        p.card.style.transform = `translate(${dx}px, ${dy}px)`;
        // leader to the nearest corner of the card
        const lx = dx < 0 ? dx + w : dx, ly = dy < 0 ? dy + h : dy;
        p.line.setAttribute("x2", lx); p.line.setAttribute("y2", ly);
      }
    }

    function select(id) {
      const pin = byPoint.get(id);
      for (const p of pins) p.el.classList.toggle("selected", p === pin);
      for (const r of document.querySelectorAll(".prow.sel")) r.classList.remove("sel");
      pin?.card.querySelector(`[data-id="${CSS.escape(id)}"]`)?.classList.add("sel");
      selected = pin || null;
      return pin;
    }
    function setVisible(on) { for (const p of pins) p.obj.visible = on; }

    // values changed: cards may change width, so measure again on the next layout
    const remeasure = () => { for (const p of pins) p.w = 0; };
    return { pins, layout, select, setVisible, remeasure, pinOf: id => byPoint.get(id) };
  }

  return { create, esc, chip };
})();
