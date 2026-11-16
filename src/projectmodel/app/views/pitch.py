"""The pitch: one screen, one message. An agent can only run a building it can read, so the graph comes first.
A quiet graph assembles itself in the background while the message appears line by line. The numbers come from the
latest score report on Alpha, so the page never claims more than was measured."""

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import box  # noqa: E402

REPORT = ROOT / "reports/score_v1.json"


def alpha() -> dict:
    try:
        return next(r for r in json.loads(REPORT.read_text()) if r["project"] == "alpha/names_paths")
    except (OSError, ValueError, StopIteration, KeyError):
        return {}


r = alpha()
NUMBERS = [  # (value, what it is) — measured on Alpha, names and folders only, no tags
    (f"{r.get('points', 1842):,}", "points read from names and folders alone"),
    (f"{r.get('H1_grouped_right_pct', 100):.0f}%", "on the right equipment"),
    (f"{r.get('H2_exact_pct', 82.3):.0f}%", "given the exact class"),
    (f"{r.get('llm_calls', 0)}", "LLM calls: rules and templates first"),
]

PAGE = """<!doctype html><html data-theme="__THEME__"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root { --bg:#FBFCFD; --fg:#14171C; --mute:#5F6670; --acc:#1F7FCC; --node:31,127,204; --line:16,24,40; }
[data-theme=dark] { --bg:#0E1013; --fg:#ECEEF1; --mute:#9AA0A6; --acc:#4DA3E8; --node:77,163,232; --line:255,255,255; }
* { box-sizing:border-box; margin:0; }
html, body { height:100%; background:var(--bg); color:var(--fg); overflow:hidden;
  font-family:"Source Sans 3","Source Sans Pro",-apple-system,"Segoe UI",sans-serif; }
canvas { position:fixed; inset:0; width:100%; height:100%; }
.veil { position:fixed; inset:0; pointer-events:none;
  background:radial-gradient(ellipse 60% 55% at 50% 50%, var(--bg) 25%, transparent 100%); opacity:.92; }
main { position:relative; height:100%; display:grid; place-items:center; padding:24px; text-align:center; }
.scene { grid-area:1/1; max-width:920px; opacity:0; transform:translateY(14px); pointer-events:none;
  transition:opacity .9s ease, transform .9s cubic-bezier(.2,.7,.2,1); }
.scene.on { opacity:1; transform:none; pointer-events:auto; }
.scene.off { opacity:0; transform:translateY(-10px); }
.kick { font-size:13px; letter-spacing:.16em; text-transform:uppercase; color:var(--acc); font-weight:600;
  margin-bottom:18px; }
h1 { font-size:clamp(30px, 5.2vw, 64px); line-height:1.06; letter-spacing:-.025em; font-weight:700; }
h1 em { font-style:normal; color:var(--acc); }
p.sub { margin-top:18px; font-size:clamp(16px, 1.7vw, 21px); line-height:1.45; color:var(--mute); }
.line { display:block; opacity:0; transform:translateY(8px); transition:opacity .8s ease, transform .8s ease; }
.on .line { opacity:1; transform:none; }
.on .line:nth-child(2) { transition-delay:.55s; } .on .line:nth-child(3) { transition-delay:1.1s; }
.on .line:nth-child(4) { transition-delay:1.65s; }
.nums { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:14px; margin-top:30px; }
.num { padding:16px 12px; border-radius:14px; border:1px solid rgba(var(--line),.10);
  background:color-mix(in srgb, var(--bg) 80%, transparent); backdrop-filter:blur(4px); }
.num b { display:block; font-size:clamp(24px, 3vw, 36px); letter-spacing:-.02em; }
.num span { font-size:13px; color:var(--mute); }
.trio { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:14px; margin-top:28px; text-align:left; }
.trio div { padding:14px 16px; border-radius:14px; border:1px solid rgba(var(--line),.10);
  background:color-mix(in srgb, var(--bg) 80%, transparent); }
.trio b { display:block; margin-bottom:4px; } .trio span { font-size:14px; color:var(--mute); line-height:1.4; }
nav { position:fixed; left:0; right:0; bottom:18px; display:flex; justify-content:center; gap:8px; align-items:center; }
nav i { width:7px; height:7px; border-radius:9px; background:rgba(var(--line),.22); cursor:pointer;
  transition:width .4s, background .4s; }
nav i.on { width:22px; background:var(--acc); }
nav button { margin-left:10px; border:1px solid rgba(var(--line),.16); background:transparent; color:var(--mute);
  border-radius:20px; padding:3px 12px; font:inherit; font-size:13px; cursor:pointer; }
@media (max-width:640px) { .nums, .trio { grid-template-columns:1fr 1fr; } .trio div:last-child { grid-column:span 2; } }
@media (prefers-reduced-motion:reduce) { .scene, .line { transition:none; } }
</style></head><body>
<canvas id="g"></canvas><div class="veil"></div>
<main>
 <section class="scene"><div class="kick">The autonomous building</div>
  <h1><span class="line">Agents will run buildings.</span><span class="line">But an agent can't run</span>
  <span class="line">a building it <em>can't read.</em></span></h1></section>
 <section class="scene"><div class="kick">The problem</div>
  <h1><span class="line">Today a building's truth is scattered.</span></h1>
  <p class="sub"><span class="line">Cryptic point names. Controller folders. Drawings and schedules.</span>
  <span class="line">And what the engineer who commissioned it never wrote down.</span></p></section>
 <section class="scene"><div class="kick">The foundation</div>
  <h1><span class="line">So we build the <em>graph</em> first.</span></h1>
  <p class="sub"><span class="line">Every point, every piece of equipment, every link between them,</span>
  <span class="line">each with its source, its method and its confidence. Reviewed by a person.</span></p></section>
 <section class="scene"><div class="kick">Measured, not claimed · site Alpha</div>
  <h1><span class="line">From raw names to a graph.</span></h1>
  <div class="nums line">__NUMBERS__</div></section>
 <section class="scene"><div class="kick">Why it matters</div>
  <h1><span class="line">The graph keeps the agents <em>honest.</em></span></h1>
  <div class="trio line">
   <div><b>Grounded</b><span>An agent acts on what the building is, not on what it guesses.</span></div>
   <div><b>Traceable</b><span>Every answer points back to a document, a row, a person.</span></div>
   <div><b>Compounding</b><span>Each building teaches the model; the next one maps faster.</span></div></div></section>
 <section class="scene"><div class="kick">Project Model</div>
  <h1 style="font-size:clamp(38px,7vw,88px)"><span class="line">First the graph.</span>
  <span class="line"><em>Then the agents.</em></span></h1>
  <p class="sub"><span class="line">Built from the first export, so the twin is right from day one.</span></p></section>
</main>
<nav id="dots"></nav>
<script>
const scenes = [...document.querySelectorAll(".scene")], dots = document.getElementById("dots");
const HOLD = [5200, 6000, 6000, 7000, 7000];  // the last scene stays
let at = -1, timer = null;
scenes.forEach((_, i) => { const d = document.createElement("i"); d.onclick = () => go(i); dots.appendChild(d); });
const replay = document.createElement("button"); replay.textContent = "Replay"; replay.onclick = () => go(0);
dots.appendChild(replay);
function go(i) {
  clearTimeout(timer);
  scenes.forEach((s, k) => { s.classList.toggle("on", k === i); s.classList.toggle("off", k !== i && k === at); });
  [...dots.children].forEach((d, k) => d.classList.toggle("on", k === i));
  at = i; grow(i);
  if (i < scenes.length - 1) timer = setTimeout(() => go(i + 1), HOLD[i]);
}
addEventListener("keydown", e => {
  if (e.key === "ArrowRight" || e.key === " ") go(Math.min(at + 1, scenes.length - 1));
  if (e.key === "ArrowLeft") go(Math.max(at - 1, 0));
});

// The background: a graph assembling itself. Few nodes at first, scattered; as the story goes on more nodes appear and
// links form, until the whole graph is connected. Slow drift, low contrast: it should never pull the eye.
const cv = document.getElementById("g"), cx = cv.getContext("2d");
const css = getComputedStyle(document.documentElement);
const NODE = css.getPropertyValue("--node").trim(), LINE = css.getPropertyValue("--line").trim();
let W, H, nodes = [], target = 0.2;
function size() { const r = devicePixelRatio || 1; W = innerWidth; H = innerHeight;
  cv.width = W * r; cv.height = H * r; cx.setTransform(r, 0, 0, r, 0, 0); }
size(); addEventListener("resize", size);
const N = Math.round(Math.min(150, Math.max(60, innerWidth * innerHeight / 9000)));
for (let i = 0; i < N; i++) nodes.push({ x: Math.random(), y: Math.random(), vx: (Math.random() - .5) * 1.4e-4,
  vy: (Math.random() - .5) * 1.4e-4, r: Math.random() < .12 ? 3.4 : 1.8, born: Math.random(), a: 0 });
function grow(i) { target = 0.2 + 0.8 * i / (scenes.length - 1); }
let share = 0.2;
function frame() {
  share += (target - share) * 0.015;
  cx.clearRect(0, 0, W, H);
  const live = nodes.filter(n => n.born <= share);
  const reach = 70 + 90 * share;
  for (const n of nodes) {
    n.x += n.vx; n.y += n.vy;
    if (n.x < 0 || n.x > 1) n.vx *= -1; if (n.y < 0 || n.y > 1) n.vy *= -1;
    n.a += ((n.born <= share ? 1 : 0) - n.a) * 0.03;
  }
  cx.lineWidth = 1;
  for (let i = 0; i < live.length; i++) for (let j = i + 1; j < live.length; j++) {
    const a = live[i], b = live[j], dx = (a.x - b.x) * W, dy = (a.y - b.y) * H, d = Math.hypot(dx, dy);
    if (d < reach) { cx.strokeStyle = `rgba(${LINE},${0.10 * (1 - d / reach) * Math.min(a.a, b.a)})`;
      cx.beginPath(); cx.moveTo(a.x * W, a.y * H); cx.lineTo(b.x * W, b.y * H); cx.stroke(); }
  }
  for (const n of nodes) if (n.a > 0.01) {
    cx.fillStyle = `rgba(${NODE},${(n.r > 3 ? 0.42 : 0.28) * n.a})`;
    cx.beginPath(); cx.arc(n.x * W, n.y * H, n.r, 0, 6.283); cx.fill();
  }
  requestAnimationFrame(frame);
}
if (matchMedia("(prefers-reduced-motion: reduce)").matches) { nodes.forEach(n => { n.vx = n.vy = 0; }); }
frame(); go(0);
</script></body></html>"""

nums = "".join(f"<div class='num'><b>{v}</b><span>{t}</span></div>" for v, t in NUMBERS)
with box("pitch", fit=True):
    st.iframe(PAGE.replace("__THEME__", "light" if st.context.theme.type == "light" else "dark")
              .replace("__NUMBERS__", nums), height=640)
    c = st.columns([1, 1, 1, 3])
    c[0].page_link("views/why.py", label="Why it matters", icon=":material/bolt:")
    c[1].page_link("views/how.py", label="How it works", icon=":material/schema:")
    c[2].page_link("views/add_building.py", label="Add a building", icon=":material/add_business:")
