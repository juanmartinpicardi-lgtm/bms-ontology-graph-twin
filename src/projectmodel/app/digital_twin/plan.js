// 2D floor plan, docked next to the 3D view. Pan by dragging, zoom with the wheel. Generated layout, not drawings.
import { W, DEP, CORE, FLOORS, equip, byId, rooms, pos, sim, isZone, colorOf, C, servedBy } from "./data.js";

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export function createPlan(host, cb) {
  const P = { vb: null, floor: null, dragged: false };
  function render(S) {
    const fid = S.floor || (S.sel && byId.get(S.sel).floor) || "L1", f = FLOORS.find(x => x.id === fid);
    const list = equip.filter(e => e.floor === fid), zones = list.filter(isZone), served = [...new Set(zones.map(servedBy).filter(Boolean))];
    if (!P.vb || P.floor !== fid) P.vb = [-2, -4, W + 4, DEP + 6];
    P.floor = fid;
    const zoom = (W + 4) / P.vb[2], o = [];
    o.push(`<div class="planhead"><div class="seg">${FLOORS.slice().reverse().map(x => `<button data-f="${x.id}" class="${x.id === fid ? "on" : ""}">${x.id}</button>`).join("")}</div>
      <div class="ph"><b>${f.long}</b><span>${list.length} assets${served.length ? ` · served by ${served.join(", ")}` : ""}${S.filtersOn ? ` · ${list.filter(S.match).length} match` : ""}</span></div></div>`);
    o.push(`<svg viewBox="${P.vb.join(" ")}" xmlns="http://www.w3.org/2000/svg"><defs>
      <pattern id="hatch" width="1" height="1" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="1" stroke="#3b4048" stroke-width=".25"/></pattern></defs>
      <rect x="0" y="0" width="${W}" height="${DEP}" fill="#15171a" stroke="#4a5059" stroke-width=".35"/>
      <rect x="${CORE.x0}" y="${CORE.z0}" width="${CORE.x1 - CORE.x0}" height="${CORE.z1 - CORE.z0}" fill="url(#hatch)" stroke="#4a5059" stroke-width=".2"/>
      <text x="${(CORE.x0 + CORE.x1) / 2}" y="${(CORE.z0 + CORE.z1) / 2}" font-size="1.1" fill="#7A8087" text-anchor="middle">core · risers</text>`);
    for (const r of rooms.get(fid)) {
      if (r.kind !== "zone") {
        o.push(`<rect x="${r.x + .15}" y="${r.z + .15}" width="${r.w - .3}" height="${r.d - .3}" rx=".3" fill="#1b1e22" stroke="#454b53" stroke-width=".18" ${r.kind === "area" ? `stroke-dasharray=".6 .4"` : ""}/>
          <text x="${r.x + .7}" y="${r.z + 1.5}" font-size="1" fill="#9AA0A6">${esc(r.name)}</text>`);
        for (const id of r.assets) {
          const p = pos.get(id), e = byId.get(id), on = S.match(e), sel = id === S.sel, st = sim.get(id).status;
          o.push(`<g class="room" data-id="${id}" opacity="${on ? 1 : .25}"><rect class="bg" x="${p.x - p.w / 2}" y="${p.z - p.d / 2}" width="${p.w}" height="${p.d}" rx=".25"
            fill="${on ? colorOf(e, S.color) : "#2a2d31"}" ${sel ? `stroke="#fff" stroke-width=".4"` : ""}/>
            <text x="${p.x}" y="${p.z + .3}" font-size="${Math.max(.45, Math.min(.9, p.w / 5))}" text-anchor="middle">${esc(e.name)}</text>
            ${st !== "normal" ? `<circle cx="${p.x + p.w / 2}" cy="${p.z - p.d / 2}" r=".45" fill="${C[st]}" stroke="#1E1E1E" stroke-width=".15"/>` : ""}</g>`);
        }
      } else {
        const id = r.assets[0], e = byId.get(id), on = S.match(e), sel = id === S.sel, s = sim.get(id), fs = Math.min(r.w, r.d) * .2;
        o.push(`<g class="room" data-id="${id}" opacity="${on ? 1 : .22}"><rect class="bg" x="${r.x + .1}" y="${r.z + .1}" width="${r.w - .2}" height="${r.d - .2}" rx=".25"
          fill="${on ? colorOf(e, S.color) : "#2a2d31"}" ${sel ? `stroke="#fff" stroke-width=".45"` : ""}/>
          <text x="${r.x + r.w / 2}" y="${r.z + r.d / 2 + (zoom > 1.6 ? -fs * .2 : fs * .35)}" font-size="${fs}" text-anchor="middle">${esc(e.name.split(" ")[1].split("-").pop())}</text>
          ${zoom > 1.6 ? `<text x="${r.x + r.w / 2}" y="${r.z + r.d / 2 + fs}" font-size="${fs * .7}" text-anchor="middle">${s.temp.toFixed(1)}°</text>` : ""}
          ${s.status !== "normal" ? `<circle cx="${r.x + r.w - .8}" cy="${r.z + .8}" r=".42" fill="${C[s.status]}" stroke="#1E1E1E" stroke-width=".15"/>` : ""}</g>`);
      }
    }
    o.push(`<text x="0" y="-1.2" font-size="1.1" fill="#6B7177">N ↑ · generated layout, not to scale</text></svg>`);
    host.innerHTML = o.join("");
    host.querySelectorAll("[data-f]").forEach(b => b.onclick = () => cb.onFloor(b.dataset.f));
    const svg = host.querySelector("svg");
    svg.querySelectorAll(".room").forEach(g => {
      g.onclick = ev => { ev.stopPropagation(); if (!P.dragged) cb.onSelect(g.dataset.id); };
      g.onmousemove = ev => cb.onHover(g.dataset.id, { left: ev.clientX, top: ev.clientY });
      g.onmouseleave = () => cb.onHover(null);
    });
    svg.onwheel = ev => { ev.preventDefault(); const r = svg.getBoundingClientRect(), k = ev.deltaY > 0 ? 1.12 : 1 / 1.12;
      const [x, y, w, h] = P.vb, sc = Math.max(w / r.width, h / r.height);
      const mx = x + (ev.clientX - r.left - (r.width - w / sc) / 2) * sc, my = y + (ev.clientY - r.top - (r.height - h / sc) / 2) * sc;
      const nw = Math.max(8, Math.min(140, w * k)), nh = h * nw / w;
      P.vb = [mx - (mx - x) * nw / w, my - (my - y) * nh / h, nw, nh]; render(S); };
    let st = null;
    svg.onpointerdown = ev => { st = [ev.clientX, ev.clientY, ...P.vb]; P.dragged = false; };
    svg.onpointermove = ev => { if (!st) return; const r = svg.getBoundingClientRect(), sc = Math.max(st[4] / r.width, st[5] / r.height);
      const dx = (ev.clientX - st[0]) * sc, dy = (ev.clientY - st[1]) * sc; if (Math.hypot(dx, dy) > .3) P.dragged = true;
      P.vb = [st[2] - dx, st[3] - dy, st[4], st[5]]; svg.setAttribute("viewBox", P.vb.join(" ")); };
    svg.onpointerup = () => { const was = P.dragged; st = null; if (was) { render(S); setTimeout(() => P.dragged = false, 0); } };
    svg.onclick = () => { if (!P.dragged && S.sel) cb.onSelect(null); };
  }
  return { render, fit() { P.vb = null; } };
}
