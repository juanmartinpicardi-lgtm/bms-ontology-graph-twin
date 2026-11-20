// On-screen controls shared by the 3D viewers (graph3d.html, equipment3d.html): zoom in / out, fit, auto-rotate,
// fullscreen and a help card, plus keyboard shortcuts. Inlined by viz.render_html and equipment_view.render_html.
// The viewer supplies the actions; this file only draws the buttons and routes the keys. Colours are the page tokens.
const ViewerControls = (() => {
  const ICONS = {  // 24px Material-style paths
    plus: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z",
    minus: "M19 13H5v-2h14z",
    fit: "M3 5v4h2V5h4V3H5c-1.1 0-2 .9-2 2zm2 10H3v4c0 1.1.9 2 2 2h4v-2H5v-4zm14 4h-4v2h4c1.1 0 2-.9 2-2v-4h-2v4zm0-16h-4v2h4v4h2V5c0-1.1-.9-2-2-2z",
    rotate: "M12 6v3l4-4-4-4v3c-4.42 0-8 3.58-8 8 0 1.57.46 3.03 1.24 4.26L6.7 14.8A5.87 5.87 0 0 1 6 12c0-3.31 2.69-6 6-6zm6.76 1.74L17.3 9.2c.44.84.7 1.79.7 2.8 0 3.31-2.69 6-6 6v-3l-4 4 4 4v-3c4.42 0 8-3.58 8-8 0-1.57-.46-3.03-1.24-4.26z",
    full: "M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z",
    exitfull: "M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z",
    help: "M11 18h2v-2h-2v2zm1-16C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-14c-2.21 0-4 1.79-4 4h2c0-1.1.9-2 2-2s2 .9 2 2c0 2-3 1.75-3 5h2c0-2.25 3-2.5 3-5 0-2.21-1.79-4-4-4z",
  };
  const svg = name => `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="${ICONS[name]}"/></svg>`;
  const CSS = `
    #vc { position: absolute; right: 12px; bottom: 12px; z-index: 5; display: flex; flex-direction: column; gap: 6px; }
    #vc .grp { display: flex; flex-direction: column; background: var(--panel); border: 1px solid var(--line);
      border-radius: 10px; overflow: hidden; backdrop-filter: blur(6px); box-shadow: 0 2px 10px rgba(0,0,0,.08); }
    #vc button { width: 34px; height: 34px; display: grid; place-items: center; padding: 0; border: none; border-radius: 0;
      background: transparent; color: var(--text); cursor: pointer; transition: background .15s, color .15s; }
    #vc .grp button + button { border-top: 1px solid var(--line); }
    #vc button:hover { background: var(--chip); color: var(--accent); }
    #vc button[aria-pressed="true"] { color: var(--accent); }
    #vc svg { fill: currentColor; }
    #vcHelp { position: absolute; right: 56px; bottom: 12px; z-index: 6; width: 290px; padding: 12px 14px; display: none;
      background: var(--panel); border: 1px solid var(--line); border-radius: 10px; backdrop-filter: blur(6px);
      font-size: 12px; box-shadow: 0 4px 18px rgba(0,0,0,.12); }
    #vcHelp.open { display: block; animation: vcIn .16s ease-out; }
    #vcHelp h4 { margin: 0 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
    #vcHelp h4 + table { margin-bottom: 10px; }
    #vcHelp table { width: 100%; border-collapse: collapse; }
    #vcHelp td { padding: 2px 0; vertical-align: top; }
    #vcHelp td:first-child { color: var(--muted); width: 46%; padding-right: 8px; }
    #vcHelp kbd { font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; padding: 0 5px; border-radius: 4px;
      border: 1px solid var(--line); background: var(--chip); color: var(--text); }
    @keyframes vcIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
    @media (max-width: 760px) { #vc { bottom: 64px; } #vcHelp { right: 12px; bottom: 120px; } }
  `;

  // opts: { zoom(f), fit(), rotate(on), keys: [[key, label, fn]], gestures: [[gesture, effect]] }
  function mount(opts) {
    const style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
    const fs = document.fullscreenEnabled;
    const root = document.createElement("div");
    root.id = "vc";
    root.innerHTML = `
      <div class="grp">
        <button data-a="in" title="Zoom in (+)" aria-label="Zoom in">${svg("plus")}</button>
        <button data-a="out" title="Zoom out (−)" aria-label="Zoom out">${svg("minus")}</button>
      </div>
      <div class="grp">
        <button data-a="fit" title="Fit to view (F)" aria-label="Fit to view">${svg("fit")}</button>
        ${opts.rotate ? `<button data-a="rotate" title="Auto-rotate (R)" aria-label="Auto-rotate" aria-pressed="false">${svg("rotate")}</button>` : ""}
        ${fs ? `<button data-a="full" title="Full screen" aria-label="Full screen">${svg("full")}</button>` : ""}
        <button data-a="help" title="Controls and shortcuts (?)" aria-label="Help" aria-pressed="false">${svg("help")}</button>
      </div>`;
    document.body.appendChild(root);

    const rows = list => list.map(([a, b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join("");
    const keys = [["+ / −", "Zoom in / out", null], ["F", "Fit to view", null],
                  ...(opts.rotate ? [["R", "Auto-rotate on / off", null]] : []),
                  ...(opts.keys || []), ["?", "This help", null]];
    const help = document.createElement("div");
    help.id = "vcHelp";
    help.innerHTML = `<h4>Mouse and touch</h4><table>${rows(opts.gestures || [])}</table>`
      + `<h4>Keys</h4><table>${rows(keys.map(([k, l]) => [k.split(" / ").map(x => `<kbd>${x}</kbd>`).join(" "), l]))}</table>`;
    document.body.appendChild(help);

    let rotating = false;
    const rotateBtn = root.querySelector('[data-a="rotate"]'), helpBtn = root.querySelector('[data-a="help"]');
    const listeners = [];
    function setRotate(on) {
      if (!opts.rotate) return;
      rotating = on;
      rotateBtn.setAttribute("aria-pressed", on);
      opts.rotate(on);
      listeners.forEach(fn => fn(on));
    }
    function toggleHelp(on = !help.classList.contains("open")) {
      help.classList.toggle("open", on);
      helpBtn.setAttribute("aria-pressed", on);
    }
    function toggleFull() {
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen?.().catch(() => {});
    }
    document.addEventListener("fullscreenchange", () => {
      const b = root.querySelector('[data-a="full"]');
      if (b) b.innerHTML = svg(document.fullscreenElement ? "exitfull" : "full");
    });
    const actions = { in: () => opts.zoom(0.7), out: () => opts.zoom(1 / 0.7), fit: () => opts.fit(),
                      rotate: () => setRotate(!rotating), full: toggleFull, help: () => toggleHelp() };
    root.addEventListener("click", e => { const b = e.target.closest("button"); if (b) actions[b.dataset.a](); });

    const typing = e => /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName);
    document.addEventListener("keydown", e => {
      if (typing(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key;
      const own = { "+": actions.in, "=": actions.in, "-": actions.out, "_": actions.out, f: actions.fit, F: actions.fit,
                    r: actions.rotate, R: actions.rotate, "?": actions.help };
      const extra = (opts.keys || []).find(([key]) => key.split(" / ").some(x => x.toLowerCase() === k.toLowerCase()
                                                                                || (x === "Esc" && k === "Escape")));
      if (k === "Escape" && help.classList.contains("open")) { toggleHelp(false); e.preventDefault(); return; }
      const fn = own[k] || extra?.[2];
      if (fn) { e.preventDefault(); fn(e); }
    });
    // Any drag or wheel by the user stops the auto-rotation, so the scene never fights the hand.
    const stop = () => { if (rotating) setRotate(false); };
    for (const ev of ["pointerdown", "wheel"]) (opts.surface || document).addEventListener(ev, stop, { passive: true });
    return { setRotate, toggleHelp, onRotate: fn => listeners.push(fn), rotating: () => rotating };
  }

  return { mount };
})();
