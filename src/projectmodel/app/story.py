"""A scroll-synced story: the layout of the Overview pages.

A column of section cards (text on the left, one simple visual on the right) with a navigation that stays centred
on screen beside them. The section nearest the middle of the screen is the active one: a highlight slides to its
name in the navigation, and clicking a name scrolls that section to the middle. Under about 900 px the navigation
is hidden and the cards stack.

A view builds a list of Section and calls story(). The small builders below (pills, tiles, steps...) make the
visuals, so every page draws from the same few shapes. Everything a builder is given is escaped unless the argument
is named *_html.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape as esc

import streamlit as st


@dataclass
class Go:
    """A link to another page of the app. page is relative to the app folder, as for st.page_link."""
    label: str
    page: str
    icon: str = "arrow_forward"
    query: dict = field(default_factory=dict)

    def attrs(self) -> str:
        return f'data-go="{esc(self.page)}" data-q="{esc(json.dumps(self.query))}"'


@dataclass
class Section:
    nav: str            # the short name in the navigation
    icon: str           # a Material Symbols name
    title: str
    body_html: str      # paragraphs, feature rows
    visual_html: str
    links: list[Go] = field(default_factory=list)


def icon(name: str) -> str:
    return f'<span class="ms" aria-hidden="true">{esc(name)}</span>'


def p(*paragraphs_html: str) -> str:
    return "".join(f"<p>{t}</p>" for t in paragraphs_html)


def features(rows: list[tuple[str, str, str]]) -> str:
    """Short rows under the text: icon, name, one line."""
    return '<ul class="feat">' + "".join(
        f"<li>{icon(i)}<span><b>{esc(h)}</b> {esc(t)}</span></li>" for i, h, t in rows) + "</ul>"


def pills(names: list[str], mark: str = "help") -> str:
    """A stack of point names, each with a small mark."""
    return '<div class="pills">' + "".join(
        f'<div class="pill rise" style="--i:{i}"><span class="dot">{icon(mark)}</span><code>{esc(n)}</code></div>'
        for i, n in enumerate(names)) + "</div>"


def tiles(items: list[tuple[str, str, str]], links: list[Go | None] | None = None) -> str:
    """A two-column grid of icon tiles: icon, name, one line. With links, a tile opens its page."""
    out = []
    for i, (ic, head, text) in enumerate(items):
        go = links[i] if links else None
        tag, attrs = ("button", f'type="button" {go.attrs()}') if go else ("div", "")
        out.append(f'<{tag} class="tile rise" style="--i:{i}" {attrs}>{icon(ic)}<b>{esc(head)}</b>'
                   f'<span>{esc(text)}</span></{tag}>')
    return f'<div class="tiles">{"".join(out)}</div>'


def steps(rows: list[tuple[str, str, str, Go | None]]) -> str:
    """A vertical walk: icon, name, what was found, and an optional page to open. The last row is the conclusion."""
    out = []
    for i, (ic, head, text_html, go) in enumerate(rows):
        last = " end" if i == len(rows) - 1 else ""
        link = f'<button type="button" class="mini" {go.attrs()} title="{esc(go.label)}">{icon(go.icon)}</button>' \
            if go else ""
        out.append(f'<li class="rise{last}" style="--i:{i}"><span class="bub">{icon(ic)}</span>'
                   f'<div><b>{esc(head)}</b><span>{text_html}</span></div>{link}</li>')
    return f'<ol class="walk">{"".join(out)}</ol>'


def bars(rows: list[tuple[str, str, int]], unit: str) -> str:
    """Horizontal bars, scaled to the largest: name, note, count."""
    top = max((n for _, _, n in rows), default=0) or 1
    out = [f'<div class="bar rise" style="--i:{i}"><div class="bar-h"><b>{esc(name)}</b><span>{n:,} {esc(unit)}</span>'
           f'</div><div class="bar-t"><i style="width:{max(100 * n / top, 1.5 if n else 0):.1f}%"></i></div>'
           f'<small>{esc(note)}</small></div>' for i, (name, note, n) in enumerate(rows)]
    return f'<div class="bars">{"".join(out)}</div>'


def stats(items: list[tuple[str, str]]) -> str:
    """A row of big numbers: value, label."""
    return '<div class="stats">' + "".join(
        f'<div class="stat rise" style="--i:{i}"><b>{esc(v)}</b><span>{esc(k)}</span></div>'
        for i, (v, k) in enumerate(items)) + "</div>"


def chips(items: list[str], start: int = 0) -> str:
    return '<div class="chips">' + "".join(
        f'<span class="chip rise" style="--i:{start + i}">{esc(t)}</span>' for i, t in enumerate(items)) + "</div>"


def record(title_html: str, rows: list[tuple[str, str]], foot: str = "") -> str:
    """A small card of field / value rows, values in the code font."""
    body = "".join(f'<div class="rise" style="--i:{i + 1}"><span>{esc(k)}</span><code>{esc(str(v))}</code></div>'
                   for i, (k, v) in enumerate(rows))
    return (f'<div class="rec"><header class="rise" style="--i:0">{title_html}</header>{body}'
            + (f"<footer>{esc(foot)}</footer>" if foot else "") + "</div>")


def glossary(terms: list[tuple[str, str]]) -> str:
    return '<dl class="gloss">' + "".join(
        f'<div class="rise" style="--i:{i}"><dt>{esc(t)}</dt><dd>{esc(d)}</dd></div>'
        for i, (t, d) in enumerate(terms)) + "</dl>"


def _html(sections: list[Section]) -> str:
    nav = "".join(f'<li><button type="button" data-i="{i}">{icon(s.icon)}<span>{esc(s.nav)}</span></button></li>'
                  for i, s in enumerate(sections))
    cards = []
    for i, s in enumerate(sections):
        links = "".join(f'<button type="button" class="go" {g.attrs()}>{esc(g.label)}{icon(g.icon)}</button>'
                        for g in s.links)
        cards.append(
            f'<section class="card" data-i="{i}" aria-labelledby="st-h-{i}"><div class="txt">'
            f'<span class="eyebrow">{i + 1:02d} · {esc(s.nav)}</span><h2 id="st-h-{i}">{esc(s.title)}</h2>'
            f'{s.body_html}' + (f'<div class="gos">{links}</div>' if links else "") +
            f'</div><div class="vis">{s.visual_html}</div></section>')
    return (f'<div class="grid"><nav class="side" aria-label="Sections"><ul><li class="glider" aria-hidden="true">'
            f'</li>{nav}</ul><div class="meter" aria-hidden="true"><i></i></div></nav>'
            f'<div class="panels">{"".join(cards)}</div></div>')


CSS = """
.story { --fg: var(--st-text-color, #16181d); --bg: var(--st-background-color, #fff);
  --acc: var(--st-primary-color, #1F7FCC);
  --muted: color-mix(in srgb, var(--fg) 64%, transparent); --line: color-mix(in srgb, var(--fg) 13%, transparent);
  --card: color-mix(in srgb, var(--fg) 3.5%, var(--bg)); --tint: color-mix(in srgb, var(--acc) 10%, var(--bg));
  --soft: color-mix(in srgb, var(--acc) 16%, var(--bg)); --ease: cubic-bezier(.19, 1, .22, 1);
  container-type: inline-size; color: var(--fg); font-family: var(--st-font, inherit); max-width: 1380px; margin: 0 auto; }
.story *, .story *::before, .story *::after { box-sizing: border-box; }
.story .ms { font-family: 'Material Symbols Rounded'; font-weight: 400; font-style: normal; font-size: 20px;
  line-height: 1; letter-spacing: normal; text-transform: none; white-space: nowrap; direction: ltr;
  -webkit-font-smoothing: antialiased; font-feature-settings: 'liga'; flex: none; }
.story code { font-family: var(--st-code-font, ui-monospace, monospace); font-size: .86em; }
.story button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; text-align: left; }
.story button:focus-visible { outline: 2px solid var(--acc); outline-offset: 2px; }

.grid { display: grid; grid-template-columns: 216px minmax(0, 1fr); gap: 44px; align-items: start; }

/* The navigation: as tall as the screen and stuck to it, so its list stays centred while the cards scroll by. */
.side { position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; justify-content: center;
  gap: 18px; }
.side ul { list-style: none; margin: 0; padding: 0; position: relative; }
.side li { margin: 0; padding: 0; }
.side button { display: flex; align-items: center; gap: 10px; width: 100%; height: 46px; padding: 0 14px;
  border-radius: 10px; font-size: .9rem; color: var(--muted); position: relative; z-index: 1;
  transition: color .25s; }
.side button:hover { color: var(--fg); }
.side button[aria-current="true"] { color: var(--fg); font-weight: 600; }
.side button .ms { font-size: 19px; opacity: 0; width: 0; transform: scale(.6);
  transition: opacity .25s, width .35s var(--ease), transform .35s var(--ease); }
.side button[aria-current="true"] .ms { opacity: 1; width: 20px; transform: none; color: var(--acc); }
.glider { position: absolute; left: 0; top: 0; width: 100%; height: 46px; border-radius: 10px;
  background: color-mix(in srgb, var(--fg) 7%, transparent); transition: transform .45s var(--ease); }
.meter { height: 2px; margin: 0 14px; border-radius: 2px; background: var(--line); overflow: hidden; }
.meter i { display: block; height: 100%; width: 100%; background: var(--acc); transform-origin: left;
  transform: scaleX(0); transition: transform .2s linear; }

.panels { display: flex; flex-direction: column; gap: 22px; padding: 4vh 0 22vh; }
.card { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 6fr); gap: 34px; padding: 26px;
  min-height: min(540px, 76vh); border-radius: 18px; background: var(--card); border: 1px solid transparent;
  transition: border-color .4s, opacity .4s; opacity: .62; }
.card.on { border-color: var(--line); opacity: 1; }
.txt { display: flex; flex-direction: column; align-items: flex-start; padding: 8px 0 8px 8px; }
.eyebrow { font-size: .74rem; letter-spacing: .08em; text-transform: uppercase; color: var(--acc); font-weight: 600; }
.txt h2 { font-size: clamp(1.45rem, 2.3cqw, 1.9rem); line-height: 1.16; letter-spacing: -.022em; font-weight: 600;
  margin: 12px 0 14px; padding: 0; text-wrap: balance; }
.txt p { margin: 0 0 10px; color: var(--muted); line-height: 1.55; font-size: .96rem; max-width: 34em; }
.txt p b, .txt p code { color: var(--fg); }
.feat { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 10px; }
.feat li { display: flex; gap: 10px; align-items: flex-start; font-size: .9rem; line-height: 1.45;
  color: var(--muted); margin: 0; }
.feat .ms { color: var(--acc); font-size: 18px; margin-top: 1px; }
.feat b { color: var(--fg); font-weight: 600; }
.gos { margin-top: auto; padding-top: 18px; display: flex; flex-wrap: wrap; gap: 8px; }
.story .go { display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 12px 0 14px;
  border-radius: 4px; border: 1px solid var(--line); font-size: .86rem; font-weight: 500;
  transition: border-color .2s, background .2s; }
.story .go:hover { border-color: var(--acc); background: var(--tint); }
.go .ms { font-size: 17px; transition: transform .3s var(--ease); }
.go:hover .ms { transform: translateX(3px); }

/* The visual: one tinted panel per card, its content centred. */
.vis { border-radius: 10px; min-height: 340px; padding: 26px; display: flex; align-items: center;
  justify-content: center; overflow: hidden;
  background: radial-gradient(120% 90% at 50% 100%, var(--soft), var(--tint) 62%); }
.vis > * { width: 100%; max-width: 430px; }
.rise { opacity: 0; transform: translateY(10px); }
.card.seen .rise { opacity: 1; transform: none;
  transition: opacity .5s calc(var(--i, 0) * 70ms + 80ms), transform .7s var(--ease) calc(var(--i, 0) * 70ms + 80ms); }
.box { background: var(--bg); border: 1px solid var(--line); border-radius: 10px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, .04), 0 8px 22px -14px rgba(0, 0, 0, .25); }

.pills { display: grid; gap: 12px; max-width: 300px !important; }
.pill { display: flex; align-items: center; gap: 12px; height: 54px; padding: 0 20px; border-radius: 10px;
  background: var(--bg); border: 1px solid var(--line); box-shadow: 0 8px 22px -14px rgba(0, 0, 0, .25); }
.pill code { font-size: .92rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dot { width: 22px; height: 22px; border-radius: 50%; border: 1.5px dashed var(--muted); display: grid;
  place-items: center; flex: none; }
.dot .ms { font-size: 13px; color: var(--muted); }

.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.story .tile { display: flex; flex-direction: column; gap: 4px; padding: 14px; border-radius: 10px;
  background: var(--bg); border: 1px solid var(--line); min-width: 0; }
.tile .ms { color: var(--acc); font-size: 22px; margin-bottom: 4px; }
.tile b { font-size: .88rem; font-weight: 600; line-height: 1.25; }
.tile span:last-child { font-size: .78rem; line-height: 1.4; color: var(--muted); }
.story button.tile { transition: border-color .2s, translate .3s var(--ease); }
.story button.tile:hover { border-color: var(--acc); translate: 0 -2px; }

.walk { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; position: relative; }
.walk::before { content: ""; position: absolute; left: 31px; top: 30px; bottom: 30px; width: 2px;
  background: repeating-linear-gradient(var(--acc) 0 4px, transparent 4px 9px); opacity: .55; }
.walk li { display: flex; align-items: center; gap: 12px; padding: 11px 12px; border-radius: 10px; margin: 0;
  background: var(--bg); border: 1px solid var(--line); position: relative; }
.walk .bub { width: 38px; height: 38px; border-radius: 50%; background: var(--tint); color: var(--acc);
  display: grid; place-items: center; flex: none; }
.walk div { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.walk b { font-size: .88rem; font-weight: 600; }
.walk div span { font-size: .78rem; line-height: 1.4; color: var(--muted); }
.walk li.end { border-color: var(--acc); }
.walk li.end .bub { background: var(--acc); color: var(--bg); }
.story .mini { width: 32px; height: 32px; border-radius: 4px; display: grid; place-items: center; flex: none;
  color: var(--muted); transition: background .2s, color .2s; }
.story .mini:hover { background: var(--tint); color: var(--acc); }

.bars { display: grid; gap: 14px; }
.bar { padding: 12px 14px; border-radius: 10px; background: var(--bg); border: 1px solid var(--line); }
.bar-h { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; font-size: .86rem; }
.bar-h b { font-weight: 600; }
.bar-h span { font-variant-numeric: tabular-nums; color: var(--muted); font-size: .8rem; white-space: nowrap; }
.bar-t { height: 6px; border-radius: 6px; background: color-mix(in srgb, var(--fg) 8%, transparent);
  margin: 8px 0 6px; overflow: hidden; }
.bar-t i { display: block; height: 100%; border-radius: 6px; background: var(--acc); transform-origin: left;
  transform: scaleX(0); }
.card.seen .bar-t i { transform: none; transition: transform 1.1s var(--ease) calc(var(--i, 0) * 70ms + 250ms); }
.bar small { font-size: .75rem; color: var(--muted); }

.stack { display: grid; gap: 12px; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.stat { padding: 14px 12px; border-radius: 10px; background: var(--bg); border: 1px solid var(--line);
  display: flex; flex-direction: column; gap: 2px; }
.stat b { font-size: 1.4rem; font-weight: 600; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.stat span { font-size: .75rem; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 7px; }
.chip { font-size: .78rem; padding: 5px 11px; border-radius: 4px; background: var(--bg);
  border: 1px solid var(--line); white-space: nowrap; }
.chip b { font-weight: 600; font-variant-numeric: tabular-nums; }
.cap { font-size: .74rem; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); font-weight: 600; }

.rec { background: var(--bg); border: 1px solid var(--line); border-radius: 10px; overflow: hidden;
  box-shadow: 0 10px 28px -18px rgba(0, 0, 0, .3); }
.rec header { padding: 14px 16px; border-bottom: 1px solid var(--line); display: flex; align-items: center;
  gap: 10px; flex-wrap: wrap; font-size: .9rem; }
.rec header .tag { margin-left: auto; font-size: .74rem; padding: 3px 9px; border-radius: 4px;
  background: var(--tint); color: var(--acc); font-weight: 600; }
.rec > div { display: flex; justify-content: space-between; gap: 16px; padding: 9px 16px; font-size: .82rem;
  border-bottom: 1px solid color-mix(in srgb, var(--fg) 6%, transparent); }
.rec > div:last-of-type { border-bottom: 0; }
.rec > div span { color: var(--muted); }
.rec > div code { text-align: right; overflow-wrap: anywhere; }
.rec footer { padding: 10px 16px; font-size: .75rem; color: var(--muted); border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--fg) 2.5%, transparent); }

.flow { display: grid; gap: 0; justify-items: center; }
.flow .srcs { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
.src { display: flex; align-items: center; gap: 7px; padding: 8px 12px; border-radius: 10px; font-size: .8rem;
  background: var(--bg); border: 1px solid var(--line); font-weight: 500; }
.src small { font-size: .68rem; padding: 1px 7px; border-radius: 4px; background: var(--tint); color: var(--acc);
  font-weight: 600; }
.src.later { border-style: dashed; color: var(--muted); }
.src.later small { background: color-mix(in srgb, var(--fg) 8%, transparent); color: var(--muted); }
.arrow { width: 2px; height: 34px; margin: 6px 0; position: relative;
  background: repeating-linear-gradient(var(--acc) 0 4px, transparent 4px 9px); }
.arrow::after { content: ""; position: absolute; left: -4px; bottom: -1px; width: 8px; height: 8px;
  border-right: 2px solid var(--acc); border-bottom: 2px solid var(--acc); transform: rotate(45deg); }
.flow .rec { width: 100%; }

.layers { display: grid; gap: 0; }
.layer { padding: 16px; border-radius: 10px; background: var(--bg); border: 1px solid var(--line);
  display: grid; gap: 10px; }
.layer.top { border-color: var(--acc); }
.layer h4 { margin: 0; padding: 0; font-size: .9rem; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.layer h4 .ms { color: var(--acc); }
.between { display: flex; justify-content: space-around; font-size: .74rem; color: var(--muted); padding: 9px 0; }
.between span { display: flex; align-items: center; gap: 4px; }
.between .ms { font-size: 16px; color: var(--acc); }

.gloss { margin: 0; display: grid; gap: 8px; max-width: 470px !important; }
.gloss > div { padding: 11px 14px; border-radius: 10px; background: var(--bg); border: 1px solid var(--line); }
.gloss dt { font-size: .86rem; font-weight: 600; }
.gloss dd { margin: 2px 0 0; font-size: .78rem; line-height: 1.45; color: var(--muted); }

.story svg { display: block; width: 100%; height: auto; overflow: visible; }
.story svg text { fill: var(--fg); font-size: 13px; font-family: inherit; }
.story svg .mono { font-family: var(--st-code-font, ui-monospace, monospace); font-size: 12.5px; }
.story svg .lbl { fill: var(--muted); font-size: 11px; }
.story svg .n { fill: var(--bg); stroke: var(--line); }
.story svg .n.a { fill: var(--acc); stroke: var(--acc); }
.story svg .n.a + text { fill: var(--bg); font-weight: 600; }
.story svg .n.d { stroke-dasharray: 4 4; stroke: var(--acc); }
.story svg .e { stroke: var(--acc); stroke-width: 1.5; fill: none; stroke-dasharray: 3 5; opacity: .8; }
.story svg .ring { stroke: var(--acc); stroke-width: 1.5; fill: none; stroke-dasharray: 3 6; opacity: .7; }
.story svg .runner { fill: var(--acc); }
.story svg .num { fill: var(--acc); }
.story svg .num + text { fill: var(--bg); font-weight: 600; font-size: 14px; }
.story svg .big { font-size: 14px; font-weight: 600; }

@container (max-width: 1080px) {
  .grid { gap: 24px; grid-template-columns: 190px minmax(0, 1fr); }
  .card { grid-template-columns: 1fr; gap: 20px; min-height: 0; }
  .txt { padding: 6px 6px 0; }
}
@container (max-width: 820px) {
  .grid { grid-template-columns: 1fr; }
  .side { display: none; }
  .card { opacity: 1; padding: 18px; }
  .panels { padding: 0 0 4vh; }
  .vis { padding: 18px; min-height: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .story *, .story *::before, .story *::after { transition: none !important; animation: none !important; }
  .rise { opacity: 1; transform: none; }
  .bar-t i { transform: none; }
  .story svg .runner { display: none; }
}
"""

JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  let root = parentElement.querySelector(".story");
  if (!root) {
    root = document.createElement("div");
    root.className = "story";
    parentElement.appendChild(root);
  }
  if (root._html !== data.html) {   // a rerun with the same content keeps the DOM, and the reader's place
    root.innerHTML = data.html;
    root._html = data.html;
  }
  if (root._off) root._off();

  const cards = [...root.querySelectorAll(".card")];
  const tabs = [...root.querySelectorAll(".side button")];
  const glider = root.querySelector(".glider");
  const meter = root.querySelector(".meter i");
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let active = -1, held = -1, release = 0, frame = 0;

  const show = (i) => {
    if (i === active || i < 0) return;
    active = i;
    cards.forEach((c, k) => c.classList.toggle("on", k === i));
    cards[i].classList.add("seen");
    tabs.forEach((t, k) => {
      if (k === i) t.setAttribute("aria-current", "true"); else t.removeAttribute("aria-current");
    });
    if (tabs[i]) glider.style.transform = `translateY(${tabs[i].parentElement.offsetTop}px)`;
  };

  // The active section is the one whose middle is nearest the middle of the screen.
  const measure = () => {
    frame = 0;
    const mid = innerHeight / 2;
    let best = 0, gap = Infinity;
    cards.forEach((c, k) => {
      const r = c.getBoundingClientRect();
      if (r.top < innerHeight * 0.92 && r.bottom > 0) c.classList.add("seen");
      const d = Math.abs(r.top + r.height / 2 - mid);
      if (d < gap) { gap = d; best = k; }
    });
    if (held < 0) show(best); else if (best === held) held = -1;
    const first = cards[0].getBoundingClientRect(), last = cards[cards.length - 1].getBoundingClientRect();
    const span = (last.top + last.height / 2) - (first.top + first.height / 2);
    const done = span > 0 ? (mid - (first.top + first.height / 2)) / span : 1;
    if (meter) meter.style.transform = `scaleX(${Math.min(1, Math.max(0, done))})`;
  };
  const onScroll = () => { if (!frame) frame = requestAnimationFrame(measure); };

  // Clicking a name selects it at once and scrolls its section to the middle; the sections passed on the way
  // don't steal the highlight.
  const go = (i) => {
    held = i;
    clearTimeout(release);
    release = setTimeout(() => { held = -1; onScroll(); }, 1400);
    show(i);
    cards[i].scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "center" });
  };

  const onClick = (e) => {
    const link = e.target.closest("[data-go]");
    if (link && root.contains(link)) {
      setTriggerValue("go", { page: link.dataset.go, query: JSON.parse(link.dataset.q || "{}"), at: Date.now() });
      return;
    }
    const tab = e.target.closest(".side button");
    if (tab) go(+tab.dataset.i);
  };
  const onKey = (e) => {
    const tab = e.target.closest && e.target.closest(".side button");
    if (!tab) return;
    const step = { ArrowDown: 1, ArrowUp: -1 }[e.key];
    const to = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : step ? +tab.dataset.i + step : -1;
    if (to < 0 || to >= tabs.length) return;
    e.preventDefault();
    tabs[to].focus();
    go(to);
  };

  root.addEventListener("click", onClick);
  root.addEventListener("keydown", onKey);
  document.addEventListener("scroll", onScroll, true);   // capture: Streamlit scrolls an inner element
  addEventListener("resize", onScroll);
  measure();

  root._off = () => {
    root.removeEventListener("click", onClick);
    root.removeEventListener("keydown", onKey);
    document.removeEventListener("scroll", onScroll, true);
    removeEventListener("resize", onScroll);
    clearTimeout(release);
    cancelAnimationFrame(frame);
  };
  return root._off;
}
"""

_component = st.components.v2.component("projectmodel.story", css=CSS, js=JS)


def story(sections: list[Section], key: str) -> None:
    """Draw the sections with their navigation. A click on a link inside opens that page of the app."""
    result = _component(data={"html": _html(sections)}, key=key, on_go_change=lambda: None)
    if go := result.go:
        st.switch_page(go["page"], query_params=go.get("query") or None)


def hero(title: str, lead_html: str) -> None:
    """The top of an Overview page: its claim, and one paragraph."""
    st.html("<style>.lead{font-size:1.3rem;line-height:1.5;opacity:.85;max-width:52rem;margin:0}</style>")
    st.title(title)
    st.html(f'<p class="lead">{lead_html}</p>')
