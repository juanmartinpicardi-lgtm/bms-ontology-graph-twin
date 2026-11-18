"""The pitch: one line. First the graph, then the agents.
Behind it, in 3D, an agent troubleshoots a warm room by walking the graph, hop by hop, to the root cause: the
reason the graph comes first. The scenario is illustrative (a typical VAV → AHU → chilled water chain, like
Alpha's); the page says so."""

import streamlit as st

from projectmodel.app.shell import box

PAGE = """<!doctype html><html data-theme="__THEME__"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;700;800&display=swap">
<style>
/* Design language as in the app: #1E1E1E page, #303030 cards, cyan accent (blue in light), Geist. */
:root { --bg:#F0F0F0; --fg:#303030; --mute:#606060; --acc:#1792E5; --card:#FFFFFF; --cardline:rgba(0,0,0,.08);
  --ink:48,48,48; --blue:23,146,229; --red:#EE3124; --amber:#C98A12; --green:#007000; }
[data-theme=dark] { --bg:#1E1E1E; --fg:#F0F0F0; --mute:#B0B0B0; --acc:#64C3FF; --card:#303030;
  --cardline:rgba(255,255,255,.06); --ink:255,255,255; --blue:100,195,255; --red:#FF644C; --amber:#F2B134;
  --green:#68D560; }
* { box-sizing:border-box; margin:0; }
html, body { height:100%; background:var(--bg); color:var(--fg); overflow:hidden;
  font-family:"Geist",-apple-system,"Segoe UI",sans-serif; font-weight:500; }
canvas { position:fixed; inset:0; width:100%; height:100%; }
header { position:absolute; left:0; right:0; top:9%; text-align:center; padding:0 24px; z-index:2; }
h1 { font-size:clamp(34px, 6vw, 78px); line-height:1.04; letter-spacing:-.03em; font-weight:800;
  opacity:0; transform:translateY(10px); animation:in 1s .2s cubic-bezier(.2,.7,.2,1) forwards; }
h1 em { font-style:normal; color:var(--acc); }
p.sub { max-width:760px; margin:18px auto 0; font-size:clamp(15px, 1.6vw, 20px); line-height:1.45; color:var(--mute);
  opacity:0; animation:in 1s .9s ease forwards; }
@keyframes in { to { opacity:1; transform:none; } }
.card { position:absolute; z-index:1; width:200px; padding:9px 12px; border-radius:10px; background:var(--card);
  border:1px solid var(--cardline); box-shadow:0 4px 10px rgba(0,0,0,.25); font-size:13px; line-height:1.35;
  opacity:0; transform:translate(-50%, 6px); transition:opacity .6s ease, transform .6s ease; pointer-events:none; }
.card.on { opacity:1; transform:translate(-50%, 0); }
.card b { display:block; font-size:14px; } .card span { color:var(--mute); }
.pill { display:inline-block; margin-top:5px; padding:1px 8px; border-radius:20px; font-size:11px; font-weight:600;
  letter-spacing:.03em; color:#fff; border-radius:4px; }
.ask { position:absolute; z-index:1; padding:7px 14px; border-radius:20px; font-size:14px; color:var(--fg);
  background:var(--card); border:1px solid var(--cardline); transform:translate(-50%, -100%);
  opacity:0; transition:opacity .6s ease; white-space:nowrap; }
.ask.on { opacity:1; } .ask i { font-style:normal; color:var(--acc); font-weight:600; margin-right:6px; }
.foot { position:absolute; left:0; right:0; bottom:16px; text-align:center; font-size:13px; color:var(--mute);
  opacity:0; transition:opacity .8s ease; z-index:1; }
.foot.on { opacity:1; } .foot b { color:var(--fg); }
@media (max-width:760px) { .card { width:150px; font-size:12px; } .ask { font-size:12px; } }
</style></head><body>
<canvas id="g"></canvas>
<header>
  <h1>First the graph. <em>Then the agents.</em></h1>
  <p class="sub">We build the building's graph from what every project already produces: floor plans, equipment
  schedules, sequences of operation, controls submittals and BMS exports. Every fact traced to its source.</p>
</header>
<div class="ask" id="ask"><i>Agent</i>Why is Zone 2-14 too warm?</div>
<div id="cards"></div>
<div class="foot" id="foot"><b>Root cause in four hops</b>, every step read from the graph and cited to its source
 · illustrative scenario</div>
<script>
const css = getComputedStyle(document.documentElement), C = k => css.getPropertyValue(k).trim();
const INK = C("--ink"), BLUE = C("--blue"), BG = C("--bg");
const TONE = { symptom: C("--red"), normal: C("--green"), suspect: C("--amber"), root: C("--red") };
const WORD = { symptom: "symptom", normal: "normal", suspect: "suspect", root: "root cause" };
// The walk, in 3D: each hop follows one link in the graph, checks what the node's points say, and moves on.
// `near` are the node's neighbours in the graph (its points, its siblings), labelled so the walk reads as one path
// through many.
const TRACE = [
  { p: [-1, .22, .25], title: "Zone 2-14", says: "78 °F, setpoint 72 °F", tone: "symptom",
    near: ["Zone temp", "Zone setpoint", "Occupancy", "Zone 2-12"] },
  { p: [-.5, -.18, -.3], title: "VAV-2-14", says: "Damper 100% open, airflow at max", tone: "normal",
    rel: "served by", near: ["Damper cmd", "Airflow", "Reheat valve", "VAV-2-12"] },
  { p: [0, .22, .3], title: "AHU-2", says: "Discharge air 63 °F (55 °F set) · cooling valve 100%", tone: "suspect",
    rel: "fed by", near: ["Discharge air temp", "Cooling valve", "Supply fan", "Mixed air temp", "VAV-3-02"] },
  { p: [.5, -.18, -.25], title: "Chilled water plant", says: "Supply 52 °F, setpoint 44 °F", tone: "suspect",
    rel: "fed by", near: ["CHW supply temp", "CHW return temp", "CHWP-1", "AHU-1", "AHU-3"] },
  { p: [1, .22, .2], title: "Chiller 2", says: "Off since 06:12 · lead chiller, no standby started", tone: "root",
    rel: "has part", near: ["Chiller 1", "Run status", "Alarm", "Enable cmd"] },
];
// Seeded, so the picture is the same on every load.
let seed = 11; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const CTX = [], LINKS = [];
TRACE.forEach((t, i) => t.near.forEach((name, k) => {
  const a = k / t.near.length * 6.283 + rnd() * .6, b = (rnd() - .5) * 2.2, r = .2 + rnd() * .08;
  CTX.push({ p: [t.p[0] + Math.cos(a) * Math.cos(b) * r * .9, t.p[1] + Math.sin(b) * r,
                 t.p[2] + Math.sin(a) * Math.cos(b) * r], name, of: i, r: 3.2 });
  LINKS.push([TRACE[i], CTX[CTX.length - 1]]);
}));
for (let k = 0; k < 90; k++) CTX.push({ p: [(rnd() - .5) * 3, (rnd() - .5) * 1.3, (rnd() - .5) * 1.6], of: -1,
  r: 1.8 });
for (let i = 0; i < CTX.length; i++) for (let j = i + 1; j < CTX.length; j++) {
  const a = CTX[i].p, b = CTX[j].p;
  if (Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) < .3 && rnd() < .35) LINKS.push([CTX[i], CTX[j]]);
}

const cv = document.getElementById("g"), cx = cv.getContext("2d");
let W, H;
function size() { const r = devicePixelRatio || 1; W = innerWidth; H = innerHeight;
  cv.width = W * r; cv.height = H * r; cx.setTransform(r, 0, 0, r, 0, 0); }
size(); addEventListener("resize", size);

// The camera: looks at `focus`, turns slowly round it (yaw), zooms in on the node the agent is checking and pulls
// back to the whole path once the root cause is found.
const cam = { f: [...TRACE[0].p], z: 1.7, yaw: 0 };
function project(p) {
  const x0 = p[0] - cam.f[0], y0 = p[1] - cam.f[1], z0 = p[2] - cam.f[2];
  const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), x1 = x0 * cy + z0 * sy, z1 = -x0 * sy + z0 * cy;
  const PITCH = .28, cp = Math.cos(PITCH), sp = Math.sin(PITCH), y2 = y0 * cp - z1 * sp, z2 = y0 * sp + z1 * cp;
  const den = 3.2 + z2 * cam.z, persp = 3.2 / Math.max(.9, den), S = Math.min(W * .38, H * .62) * cam.z;
  // behind or right at the camera: not drawn
  return { x: W / 2 + x1 * S * persp, y: H * .66 + y2 * S * persp, k: persp * cam.z, d: z2, off: den < .9 };
}

const cards = TRACE.map(t => {
  const d = document.createElement("div"); d.className = "card";
  d.innerHTML = `<b>${t.title}</b><span>${t.says}</span><br><span class="pill" style="background:${TONE[t.tone]}">`
    + `${WORD[t.tone]}</span>`;
  document.getElementById("cards").appendChild(d); return d;
});
const ask = document.getElementById("ask"), foot = document.getElementById("foot");

// One run, in ms: the question, one hop every STEP, pull back and hold on the root cause, fade, start over.
const START = 2200, STEP = 2600, HOP = 1100, HOLD = 6500, FADE = 900;
const LAST = START + STEP * (TRACE.length - 1), RUN = LAST + HOLD + FADE;
const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
const t0 = performance.now();
const ease = k => k < .5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
const lerp = (a, b, k) => a + (b - a) * k;

function frame(now) {
  try { draw(now); } finally { if (!still) requestAnimationFrame(frame); }   // one bad frame never stops it
}
function draw(now) {
  const t = still ? LAST + HOLD - 1 : (now - t0) % RUN;
  if (t < 50) { cam.f = [...TRACE[0].p]; cam.z = 1.7; }   // a new run starts close on the zone
  const fade = t > RUN - FADE ? 1 - (t - (RUN - FADE)) / FADE : 1;
  const reached = t < START ? -1 : Math.min(TRACE.length - 1, Math.floor((t - START) / STEP));
  const into = t < START ? 0 : t - START - STEP * reached;
  const wide = t > LAST + 1400;                             // root cause found: show the whole path
  // Camera targets: the agent itself while it moves, the node while it checks, everything at the end.
  let target = TRACE[Math.max(0, reached)].p, zoom = 1.75;
  if (reached >= 1 && into < HOP) {
    const a = TRACE[reached - 1].p, b = TRACE[reached].p, k = ease(into / HOP);
    target = [lerp(a[0], b[0], k), lerp(a[1], b[1], k), lerp(a[2], b[2], k)]; zoom = 1.55;
  }
  if (wide || still) { target = [0, 0, 0]; zoom = .95; }
  const sp = still ? 1 : .035;
  cam.f = cam.f.map((v, i) => v + (target[i] - v) * sp); cam.z += (zoom - cam.z) * sp * .8;
  cam.yaw = still ? -.2 : Math.sin(now / 1000 * .16) * .5;

  cx.clearRect(0, 0, W, H);
  const P = new Map(); const pr = n => { if (!P.has(n)) P.set(n, project(n.p)); return P.get(n); };
  // Context links and nodes, farther ones fainter.
  cx.lineWidth = 1;
  for (const [a, b] of LINKS) {
    const A = pr(a), B = pr(b);
    if (A.off || B.off) continue;
    const depth = Math.min(1, Math.max(.25, (A.k + B.k) / 2 * .7));
    cx.strokeStyle = `rgba(${INK},${(a.title ? .2 : .09) * depth})`;
    cx.beginPath(); cx.moveTo(A.x, A.y); cx.lineTo(B.x, B.y); cx.stroke();
  }
  const ctx = CTX.map(n => [n, pr(n)]).sort((a, b) => b[1].d - a[1].d);
  cx.textAlign = "left";
  for (const [n, q] of ctx) {
    if (q.off) continue;
    const near = n.of >= 0, depth = Math.min(1, Math.max(.2, q.k * .7));
    cx.fillStyle = `rgba(${BLUE},${(near ? .6 : .25) * depth})`;
    cx.beginPath(); cx.arc(q.x, q.y, n.r * Math.min(2, q.k), 0, 6.283); cx.fill();
    if (n.name) {
      const active = n.of === reached && !wide;
      cx.font = `${Math.round(Math.max(10, Math.min(14, 9 * q.k)))}px Geist, -apple-system, sans-serif`;
      cx.fillStyle = `rgba(${INK},${(active ? .8 : .4) * depth * fade})`;
      cx.fillText(n.name, q.x + 7, q.y + 4);
    }
  }
  // The links of the walk, with their names.
  cx.textAlign = "center";
  for (let i = 1; i < TRACE.length; i++) {
    const A = pr(TRACE[i - 1]), B = pr(TRACE[i]);
    const done = i < reached || (i === reached && into >= HOP);
    cx.strokeStyle = done ? `rgba(${BLUE},${.85 * fade})` : `rgba(${INK},.25)`;
    cx.lineWidth = done ? 2.5 : 1.4; cx.setLineDash(done ? [] : [4, 5]);
    cx.beginPath(); cx.moveTo(A.x, A.y); cx.lineTo(B.x, B.y); cx.stroke(); cx.setLineDash([]);
    cx.font = "600 12px Geist, -apple-system, sans-serif";
    cx.fillStyle = `rgba(${INK},${done ? .8 * fade : .45})`;
    cx.fillText(TRACE[i].rel, (A.x + B.x) / 2, (A.y + B.y) / 2 - 9);
  }
  // The agent moving along the hop it is on.
  if (reached >= 1 && into < HOP && fade === 1) {
    const A = pr(TRACE[reached - 1]), B = pr(TRACE[reached]), k = ease(into / HOP);
    const x = lerp(A.x, B.x, k), y = lerp(A.y, B.y, k);
    cx.strokeStyle = `rgba(${BLUE},.9)`; cx.lineWidth = 2.5;
    cx.beginPath(); cx.moveTo(A.x, A.y); cx.lineTo(x, y); cx.stroke();
    cx.fillStyle = `rgba(${BLUE},.18)`; cx.beginPath(); cx.arc(x, y, 15, 0, 6.283); cx.fill();
    cx.fillStyle = `rgba(${BLUE},1)`; cx.beginPath(); cx.arc(x, y, 6, 0, 6.283); cx.fill();
  }
  // The nodes of the walk: grey until checked, then the colour of what was found; labelled.
  const pulse = (now / 1000 * 1.2) % 1;
  TRACE.forEach((n, i) => {
    const q = pr(n), lit = i < reached || (i === reached && (i === 0 || into >= HOP)), r = 8 + 2 * q.k;
    const col = lit ? TONE[n.tone] : `rgba(${INK},.38)`;
    if (lit && (n.tone === "symptom" || n.tone === "root")) {
      cx.strokeStyle = col; cx.globalAlpha = (1 - pulse) * .6 * fade; cx.lineWidth = 2;
      cx.beginPath(); cx.arc(q.x, q.y, r + 2 + pulse * 20, 0, 6.283); cx.stroke();
    }
    cx.globalAlpha = lit ? fade : 1;
    cx.fillStyle = col; cx.beginPath(); cx.arc(q.x, q.y, r, 0, 6.283); cx.fill();
    cx.fillStyle = BG; cx.beginPath(); cx.arc(q.x, q.y, r * .38, 0, 6.283); cx.fill();
    cx.globalAlpha = 1;
    const card = cards[i], below = i % 2 === 0, show = lit && fade > .5 && (wide || i === reached || i === 0
      || i === reached - 1) && q.x > 90 && q.x < W - 90;
    if (!show) {   // no card: the node's name next to it
      cx.font = "600 13px Geist, -apple-system, sans-serif"; cx.textAlign = "center";
      cx.fillStyle = `rgba(${INK},${.7 * fade})`; cx.fillText(n.title, q.x, q.y + (below ? r + 18 : -r - 9));
    }
    card.style.left = q.x + "px"; card.style.top = (below ? q.y + r + 10 : q.y - r - 10 - card.offsetHeight) + "px";
    card.classList.toggle("on", show);
  });
  const q0 = pr(TRACE[0]);
  ask.style.left = Math.min(W - 160, Math.max(160, q0.x)) + "px"; ask.style.top = (q0.y - 22) + "px";
  ask.classList.toggle("on", t > 500 && reached < 2 && fade > .5);
  foot.classList.toggle("on", wide && fade > .5);
}
requestAnimationFrame(frame);
</script></body></html>"""

with box("pitch", fit=True):
    st.iframe(PAGE.replace("__THEME__", "light" if st.context.theme.type == "light" else "dark"), height=640)
    c = st.columns([1, 1, 1, 3])
    c[0].page_link("views/why.py", label="Why it matters", icon=":material/bolt:")
    c[1].page_link("views/how.py", label="How it works", icon=":material/schema:")
    c[2].page_link("views/add_building.py", label="Add a building", icon=":material/add_business:")
