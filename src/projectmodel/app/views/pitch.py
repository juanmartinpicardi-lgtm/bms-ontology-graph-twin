"""The pitch: one line. First the graph, then the agents.
Behind it, an agent troubleshoots a warm room by walking the graph, hop by hop, to the root cause: the reason the
graph comes first. The scenario is illustrative (a typical VAV → AHU → chilled water chain, like Alpha's); the page
says so."""

import streamlit as st

from projectmodel.app.shell import box

PAGE = """<!doctype html><html data-theme="__THEME__"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root { --bg:#FBFCFD; --fg:#14171C; --mute:#5F6670; --acc:#1F7FCC; --card:#FFFFFF; --cardline:rgba(16,24,40,.12);
  --ink:16,24,40; --blue:31,127,204; --red:#D14343; --amber:#C98A12; --green:#2E9E6A; }
[data-theme=dark] { --bg:#0E1013; --fg:#ECEEF1; --mute:#9AA0A6; --acc:#4DA3E8; --card:#171A1F;
  --cardline:rgba(255,255,255,.12); --ink:255,255,255; --blue:77,163,232; --red:#F06A6A; --amber:#E8B04A;
  --green:#4CC38A; }
* { box-sizing:border-box; margin:0; }
html, body { height:100%; background:var(--bg); color:var(--fg); overflow:hidden;
  font-family:"Source Sans 3","Source Sans Pro",-apple-system,"Segoe UI",sans-serif; }
canvas { position:fixed; inset:0; width:100%; height:100%; }
header { position:absolute; left:0; right:0; top:9%; text-align:center; padding:0 24px; z-index:2; }
h1 { font-size:clamp(34px, 6vw, 78px); line-height:1.04; letter-spacing:-.03em; font-weight:700;
  opacity:0; transform:translateY(10px); animation:in 1s .2s cubic-bezier(.2,.7,.2,1) forwards; }
h1 em { font-style:normal; color:var(--acc); }
p.sub { max-width:760px; margin:18px auto 0; font-size:clamp(15px, 1.6vw, 20px); line-height:1.45; color:var(--mute);
  opacity:0; animation:in 1s .9s ease forwards; }
@keyframes in { to { opacity:1; transform:none; } }
.card { position:absolute; z-index:1; width:200px; padding:9px 12px; border-radius:12px; background:var(--card);
  border:1px solid var(--cardline); box-shadow:0 4px 18px rgba(0,0,0,.06); font-size:13px; line-height:1.35;
  opacity:0; transform:translate(-50%, 6px); transition:opacity .6s ease, transform .6s ease; pointer-events:none; }
.card.on { opacity:1; transform:translate(-50%, 0); }
.card b { display:block; font-size:14px; } .card span { color:var(--mute); }
.pill { display:inline-block; margin-top:5px; padding:1px 8px; border-radius:20px; font-size:11px; font-weight:600;
  letter-spacing:.03em; color:#fff; }
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
const INK = C("--ink"), BLUE = C("--blue");
const TONE = { symptom: C("--red"), normal: C("--green"), suspect: C("--amber"), root: C("--red") };
const WORD = { symptom: "symptom", normal: "normal", suspect: "suspect", root: "root cause" };
// The walk: each hop follows one link in the graph, checks what the node's points say, and moves on.
const TRACE = [
  { x: .12, y: .76, title: "Zone 2-14", says: "78 °F, setpoint 72 °F", tone: "symptom" },
  { x: .31, y: .60, title: "VAV-2-14", says: "Damper 100% open, airflow at max", tone: "normal", rel: "served by" },
  { x: .50, y: .77, title: "AHU-2", says: "Discharge air 63 °F (55 °F set) · cooling valve 100%", tone: "suspect",
    rel: "fed by" },
  { x: .69, y: .60, title: "Chilled water plant", says: "Supply 52 °F, setpoint 44 °F", tone: "suspect",
    rel: "fed by" },
  { x: .88, y: .76, title: "Chiller 2", says: "Off since 06:12 · lead chiller, no standby started", tone: "root",
    rel: "has part" },
];
// The rest of the graph around the walk: siblings and points of each node, so the walk reads as one path through
// many. Seeded, so the picture is the same on every load.
let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const CTX = [], LINKS = [];
TRACE.forEach((t, i) => {
  const n = i === 2 ? 9 : 6;
  for (let k = 0; k < n; k++) {
    const a = rnd() * 6.283, r = .05 + rnd() * .07;
    CTX.push({ x: t.x + Math.cos(a) * r, y: t.y + Math.sin(a) * r * 1.5, r: rnd() < .3 ? 4 : 2.6, of: i });
    LINKS.push([i, CTX.length - 1]);
  }
});
for (let k = 0; k < 70; k++) CTX.push({ x: rnd(), y: .42 + rnd() * .56, r: 1.8, of: -1 });
for (let i = 0; i < CTX.length; i++) for (let j = i + 1; j < CTX.length; j++) {
  const a = CTX[i], b = CTX[j];
  if (Math.hypot(a.x - b.x, (a.y - b.y) * .6) < .055 && rnd() < .5) LINKS.push([-1, i, j]);
}

const cv = document.getElementById("g"), cx = cv.getContext("2d");
let W, H;
function size() { const r = devicePixelRatio || 1; W = innerWidth; H = innerHeight;
  cv.width = W * r; cv.height = H * r; cx.setTransform(r, 0, 0, r, 0, 0); }
size(); addEventListener("resize", size);
const P = n => [n.x * W, n.y * H];

const cards = TRACE.map(t => {
  const d = document.createElement("div"); d.className = "card";
  d.innerHTML = `<b>${t.title}</b><span>${t.says}</span><br><span class="pill" style="background:${TONE[t.tone]}">`
    + `${WORD[t.tone]}</span>`;
  document.getElementById("cards").appendChild(d); return d;
});
const ask = document.getElementById("ask"), foot = document.getElementById("foot");

// Timeline of one run, in ms: the question, then one hop every STEP, hold on the root cause, fade, start over.
const START = 1800, STEP = 2300, HOP = 1000, HOLD = 5500, FADE = 900;
const RUN = START + STEP * (TRACE.length - 1) + HOLD + FADE;
const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
let t0 = performance.now();

function frame(now) {
  let t = still ? RUN - FADE - 1 : (now - t0) % RUN;
  const fade = t > RUN - FADE ? 1 - (t - (RUN - FADE)) / FADE : 1;
  const reached = t < START ? -1 : Math.min(TRACE.length - 1, Math.floor((t - START) / STEP));
  const into = t < START ? 0 : (t - START) % STEP;   // time since the last hop started
  cx.clearRect(0, 0, W, H);
  const breathe = now / 1000;

  // The graph: links and nodes, quiet but readable.
  cx.lineWidth = 1;
  for (const l of LINKS) {
    const [a, b] = l[0] === -1 ? [CTX[l[1]], CTX[l[2]]] : [TRACE[l[0]], CTX[l[1]]];
    const [ax, ay] = P(a), [bx, by] = P(b);
    cx.strokeStyle = `rgba(${INK},${l[0] === -1 ? .07 : .14})`;
    cx.beginPath(); cx.moveTo(ax, ay); cx.lineTo(bx, by); cx.stroke();
  }
  for (const n of CTX) {
    const [x, y] = P(n), dy = Math.sin(breathe * .6 + n.x * 9) * 1.2;
    cx.fillStyle = `rgba(${BLUE},${n.of >= 0 ? .45 : .22})`;
    cx.beginPath(); cx.arc(x, y + dy, n.r, 0, 6.283); cx.fill();
  }
  // The links of the walk, with their names.
  cx.font = "12px Source Sans 3, -apple-system, sans-serif"; cx.textAlign = "center";
  for (let i = 1; i < TRACE.length; i++) {
    const [ax, ay] = P(TRACE[i - 1]), [bx, by] = P(TRACE[i]);
    const done = i <= reached && !(i === reached && into < HOP);
    cx.strokeStyle = done ? `rgba(${BLUE},${.85 * fade})` : `rgba(${INK},.22)`;
    cx.lineWidth = done ? 2.5 : 1.4;
    cx.setLineDash(done ? [] : [4, 5]);
    cx.beginPath(); cx.moveTo(ax, ay); cx.lineTo(bx, by); cx.stroke();
    cx.setLineDash([]);
    cx.fillStyle = `rgba(${INK},${done ? .75 * fade : .4})`;
    cx.fillText(TRACE[i].rel, (ax + bx) / 2, (ay + by) / 2 - 8);
  }
  // The agent moving along the hop it is on.
  if (reached >= 1 && into < HOP && fade === 1) {
    const [ax, ay] = P(TRACE[reached - 1]), [bx, by] = P(TRACE[reached]);
    const k = into / HOP, e = k < .5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
    const x = ax + (bx - ax) * e, y = ay + (by - ay) * e;
    cx.strokeStyle = `rgba(${BLUE},.9)`; cx.lineWidth = 2.5;
    cx.beginPath(); cx.moveTo(ax, ay); cx.lineTo(x, y); cx.stroke();
    cx.fillStyle = `rgba(${BLUE},1)`; cx.beginPath(); cx.arc(x, y, 6, 0, 6.283); cx.fill();
    cx.fillStyle = `rgba(${BLUE},.18)`; cx.beginPath(); cx.arc(x, y, 14, 0, 6.283); cx.fill();
  }
  // The nodes of the walk: grey until checked, then the colour of what was found.
  TRACE.forEach((n, i) => {
    const [x, y] = P(n), lit = i < reached || (i === reached && (i === 0 || into >= HOP));
    const col = lit ? TONE[n.tone] : `rgba(${INK},.35)`;
    if (lit && (n.tone === "symptom" || n.tone === "root")) {
      const pulse = (breathe * 1.2) % 1;
      cx.strokeStyle = col; cx.globalAlpha = (1 - pulse) * .6 * fade; cx.lineWidth = 2;
      cx.beginPath(); cx.arc(x, y, 11 + pulse * 18, 0, 6.283); cx.stroke(); cx.globalAlpha = 1;
    }
    cx.globalAlpha = lit ? fade : 1;
    cx.fillStyle = col; cx.beginPath(); cx.arc(x, y, 9, 0, 6.283); cx.fill();
    cx.fillStyle = C("--bg"); cx.beginPath(); cx.arc(x, y, 3.5, 0, 6.283); cx.fill();
    cx.globalAlpha = 1;
    const card = cards[i], below = n.y > .7;  // cards away from the links between nodes
    card.style.left = x + "px"; card.style.top = (below ? y + 20 : y - 20 - card.offsetHeight) + "px";
    card.classList.toggle("on", lit && fade > .5);
  });
  const [qx, qy] = P(TRACE[0]);
  ask.style.left = Math.max(110, qx) + "px"; ask.style.top = (qy - 22) + "px";
  ask.classList.toggle("on", t > 500 && fade > .5);
  foot.classList.toggle("on", reached === TRACE.length - 1 && into >= HOP && fade > .5);
  if (!still) requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
</script></body></html>"""

with box("pitch", fit=True):
    st.iframe(PAGE.replace("__THEME__", "light" if st.context.theme.type == "light" else "dark"), height=640)
    c = st.columns([1, 1, 1, 3])
    c[0].page_link("views/why.py", label="Why it matters", icon=":material/bolt:")
    c[1].page_link("views/how.py", label="How it works", icon=":material/schema:")
    c[2].page_link("views/add_building.py", label="Add a building", icon=":material/add_business:")
