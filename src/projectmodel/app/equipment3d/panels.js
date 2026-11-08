// Screen panels: header relations, the details panel (point provenance, unplaced points, fed-by / feeds lists) and
// the component + setpoint panels pinned to the bottom-left corner.
const Panels = (() => {
  const { esc, staticValue } = Labels;
  const TITLE = {
    supply_fan: "Supply fan", return_fan: "Return fan", cooling_coil: "Cooling coil", heating_coil: "Heating coil",
    mixing_box: "Economizer", relief_outlet: "Relief", supply_duct: "Supply air", return_duct: "Return air",
    outside_air_inlet: "Outside air", controller: "Controller", building_ref: "Building", bag_filter: "Filters",
    pre_filter: "Filters", zone_sensor: "Zone", damper: "Damper", flow_cross: "Airflow", reheat_coil: "Reheat",
    fan: "Fan", discharge_duct: "Discharge", inlet_duct: "Inlet", box: "Box",
  };
  const title = part => TITLE[part.split(".")[0]] || part.split(".")[0].replace(/_/g, " ");
  const isSetpoint = p => (p.cls || "").endsWith("_Setpoint");
  const valueChip = p => { const v = staticValue(p); return `<span class="pval ${v.state ? "st-" + v.state : ""}">${esc(v.text)}</span>`; };

  function create(data, { onSelectPoint, onOpenEquipment }) {
    const panel = document.getElementById("panel"), body = document.getElementById("panelBody");
    const pts = data.points, eq = data.equipment;
    const rel = data.relations || { fed_by: [], feeds: [] };

    // header: fed by / feeds / unplaced
    const sub = document.getElementById("eqRel");
    const fedBy = rel.fed_by.map(r => `<span class="nav" data-eq="${esc(r.id)}">${esc(r.label)}</span>`).join(", ");
    sub.innerHTML = [
      fedBy && `fed by ${fedBy}`,
      rel.feeds.length && `<span class="nav" data-show="feeds">feeds ${rel.feeds.length} ${rel.feeds[0]?.template === "vav" ? "VAVs" : "equipment"}</span>`,
      `<span class="nav" data-show="unplaced">${data.unplaced.length} unplaced</span>`,
    ].filter(Boolean).join(" · ");

    function open(html) { body.innerHTML = html; panel.style.display = "block"; body.scrollTop = 0; }
    function close() { panel.style.display = "none"; }
    document.getElementById("closePanel").onclick = close;

    const table = rows => `<table>${Object.entries(rows).filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(2)) : v)}</td></tr>`).join("")}</table>`;
    const pointRow = id => {
      const p = pts[id];
      return `<li><span class="nav" data-pt="${esc(id)}">${esc(p.label)}</span> <span class="muted">${esc(p.cls || "no class")} · ${(p.confidence ?? 0).toFixed(2)}</span></li>`;
    };

    function showPoint(id) {
      const p = pts[id];
      if (!p) return;
      const slot = (data.slots || []).find(s => s.role === p.role);
      let h = `<div class="muted" style="font-size:12px">${esc(eq.label)}${p.sub_equipment ? " › " + esc(p.sub_equipment.split("/").pop()) : ""}</div>`;
      h += `<h2>${esc(p.label)}</h2><span class="chip">${esc(p.cls || "no class")}</span>${valueChip(p)} <span class="badge">SIMULATED</span>`;
      h += `<h3>On the model</h3>` + table({ "slot role": p.role || "(unplaced)", part: p.part, "at": p.at,
                                              "slot classes": slot?.classes.join(", "), medium: slot?.medium });
      h += `<h3>Provenance of this point</h3>` + table({ method: p.prov.method, confidence: p.prov.confidence, status: p.prov.status,
            "source file": p.prov.source_file, "source row": p.prov.source_ref, revision: p.prov.revision,
            review: p.prov.review ? `${p.prov.review.action} by ${p.prov.review.by}` : undefined });
      if (p.via) h += `<h3>Placed on this equipment by</h3>` + table({ method: p.via.method, confidence: p.via.confidence,
            status: p.via.status, "source ref": p.via.source_ref });
      h += `<h3>Review</h3><div class="muted">` + (data.review_url
        ? `<a class="nav" href="${esc(data.review_url)}?point=${encodeURIComponent(id)}" target="_top">Review this point</a>`
        : `Open the review app and look up <code>${esc(id)}</code>.`) + `</div>`;
      open(h);
    }

    function showUnplaced() {
      let h = `<h2>Unplaced points</h2><div class="muted">Points on ${esc(eq.label)} that fit no slot of the ${esc(eq.template)} template.</div>`;
      h += data.unplaced.length ? `<ul class="nb">${data.unplaced.map(pointRow).join("")}</ul>` : `<p class="muted">None.</p>`;
      open(h);
    }

    function showFeeds(filter = "") {
      const f = filter.toLowerCase(), list = rel.feeds.filter(r => r.label.toLowerCase().includes(f));
      let h = `<h2>Feeds (${rel.feeds.length})</h2><input id="feedSearch" type="text" placeholder="Search…" value="${esc(filter)}" autocomplete="off">`;
      h += `<ul class="nb">${list.map(r => `<li><span class="nav" data-eq="${esc(r.id)}">${esc(r.label)}</span> <span class="muted">${esc(r.cls)}</span></li>`).join("")}</ul>`;
      if (rel.fed_by.length) h += `<h3>Fed by</h3><ul class="nb">${rel.fed_by.map(r => `<li><span class="nav" data-eq="${esc(r.id)}">${esc(r.label)}</span> <span class="muted">${esc(r.cls)}</span></li>`).join("")}</ul>`;
      open(h);
      const inp = document.getElementById("feedSearch");
      inp.focus();
      inp.setSelectionRange(filter.length, filter.length);
      inp.oninput = () => showFeeds(inp.value);
    }

    // Component panels: placed points (not setpoints) grouped by the part they sit on; setpoints in their own panel.
    const byComp = new Map(), setpoints = [];
    for (const [id, p] of Object.entries(pts)) {
      if (!p.part) continue;
      if (isSetpoint(p)) { setpoints.push(id); continue; }
      const t = title(p.part);
      if (!byComp.has(t)) byComp.set(t, []);
      byComp.get(t).push(id);
    }
    const order = ["Supply fan", "Return fan", "Economizer", "Relief", "Cooling coil", "Heating coil", "Outside air",
                   "Return air", "Supply air", "Building", "Airflow", "Damper", "Fan", "Reheat", "Discharge", "Zone",
                   "Controller"];
    const comps = [...byComp.keys()].sort((a, b) => ((order.indexOf(a) + 1) || 99) - ((order.indexOf(b) + 1) || 99));
    const row = id => `<tr class="crow" data-pt="${esc(id)}"><td>${esc(pts[id].label)}</td><td>${valueChip(pts[id])}</td></tr>`;
    const dock = document.getElementById("dock");
    dock.innerHTML =
      `<div class="card cpanel collapsed" id="compPanel"><div class="chead">Components <span class="muted">${comps.length}</span></div><div class="cbody">` +
      comps.map((c, i) => `<details ${i < 1 ? "open" : ""}><summary>${esc(c)} <span class="muted">${byComp.get(c).length}</span></summary>` +
                          `<table>${byComp.get(c).sort((a, b) => pts[a].label.localeCompare(pts[b].label)).map(row).join("")}</table></details>`).join("") +
      `</div></div>` +
      (setpoints.length ? `<div class="card cpanel collapsed" id="spPanel"><div class="chead">Setpoints <span class="muted">${setpoints.length}</span></div>` +
                          `<div class="cbody"><table>${setpoints.map(row).join("")}</table></div></div>` : "");
    for (const h of dock.querySelectorAll(".chead")) h.onclick = () => h.parentElement.classList.toggle("collapsed");

    // one click handler for every link in the page chrome
    document.addEventListener("click", e => {
      const t = e.target.closest("[data-pt], [data-eq], [data-show]");
      if (!t || !t.closest("#panel, #dock, #header, #labels")) return;
      if (t.dataset.pt) onSelectPoint(t.dataset.pt);
      else if (t.dataset.eq) onOpenEquipment(t.dataset.eq);
      else if (t.dataset.show === "feeds") showFeeds();
      else if (t.dataset.show === "unplaced") showUnplaced();
    });

    function highlight(id) {
      for (const r of dock.querySelectorAll(".crow")) r.classList.toggle("sel", r.dataset.pt === id);
    }
    function showEquipment(r, href) {
      open(`<h2>${esc(r.label)}</h2><span class="chip">${esc(r.cls)}</span>` +
           (href ? `<p><a class="nav" href="${esc(href)}">Open its 3D view</a></p>`
                 : `<p class="muted">${["ahu", "vav"].includes(r.template) ? "Its 3D page was not exported with this one (export with --all)." : "No 3D model for this equipment type yet."}</p>`) +
           `<div class="muted"><code>${esc(r.id)}</code></div>`);
    }
    return { showPoint, showFeeds, showUnplaced, showEquipment, highlight, close };
  }

  return { create };
})();
