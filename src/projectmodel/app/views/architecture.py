"""Architecture: the app's parts and how data moves between them, on one screen.

One diagram: the flow left to right (inputs, readers, mapper, knowledge graph, review, views and agent), and under it
what serves every step (knowledge model, tribal knowledge, AI layer). Then the principles, where data lives and the
stack. The words come from agent/foundations.py, which the agent also reads, so the page and the agent agree.
"""

import sys
from html import escape
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.agent.foundations import ARCHITECTURE, PRINCIPLES, STACK, SUPPORT  # noqa: E402
from projectmodel.app.shell import THEME, theme  # noqa: E402
from projectmodel.app.story import hero  # noqa: E402

c = THEME[theme()]
dark = theme() == "dark"

WHERE = [  # (what, where)
    ("Raw sources, untouched", "data/raw/"),
    ("Knowledge graphs, LLM call log", "data/kg.sqlite"),
    ("Buildings in the guided setup", "data/intake/<building>/"),
    ("Documents added on a project", "data/library/<site>/"),
    ("Knowledge model", "knowledge_model/"),
    ("Prompts", "src/projectmodel/ai/prompts/"),
]

CSS = f"""<style>
.arch {{ --acc: {c["accent"]}; --fg: {c["text"]}; --mute: {c["mute"]}; --line: {c["line"]}; --card: {c["card"]};
  --soft: {c["card2"]}; --good: {c["good"]}; color: var(--fg); }}
.arch .ms {{ font-family: 'Material Symbols Rounded'; font-size: 22px; line-height: 1; font-feature-settings: 'liga';
  -webkit-font-smoothing: antialiased; }}
.arch .flow {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0; align-items: stretch;
  margin: 6px 0 0; }}
.arch .step {{ position: relative; display: flex; flex-direction: column; gap: 6px; background: var(--card);
  border: 1px solid var(--line); border-radius: 12px; padding: 14px 14px 12px; margin-right: 26px; }}
.arch .step:last-child {{ margin-right: 0; }}
.arch .step:not(:last-child)::after {{ content: ""; position: absolute; right: -24px; top: 34px; width: 20px;
  height: 2px; background: var(--acc); }}
.arch .step:not(:last-child)::before {{ content: ""; position: absolute; right: -25px; top: 30px; border: 5px solid
  transparent; border-left: 7px solid var(--acc); }}
.arch .n {{ font-size: 11px; font-weight: 700; color: var(--mute); letter-spacing: .06em; }}
.arch .step .ms {{ color: var(--acc); }}
.arch .hd {{ display: flex; align-items: center; gap: 8px; }}
.arch .hd b {{ font-size: 15px; }}
.arch .step p {{ margin: 0; font-size: 12.5px; line-height: 1.45; color: var(--fg); opacity: .88; flex: 1; }}
.arch code {{ font-family: var(--st-code-font, ui-monospace, monospace); font-size: 11px; color: var(--mute);
  background: var(--soft); border-radius: 4px; padding: 1px 5px; align-self: flex-start; }}
.arch .graph {{ border-color: var(--acc); box-shadow: 0 0 0 1px var(--acc) inset; }}
.arch .serve {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 30px;
  position: relative; }}
.arch .serve::before {{ content: "Serves every step"; position: absolute; top: -21px; left: 0; font-size: 11px;
  font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--mute); }}
.arch .sv {{ display: flex; gap: 12px; background: var(--soft); border: 1px dashed var(--line); border-radius: 12px;
  padding: 12px 14px; }}
.arch .sv .ms {{ color: var(--mute); }}
.arch .sv b {{ display: block; font-size: 14px; margin-bottom: 2px; }}
.arch .sv p {{ margin: 0 0 6px; font-size: 12.5px; line-height: 1.45; opacity: .88; }}
.arch .row3 {{ display: grid; grid-template-columns: 1.3fr 1fr 1fr; gap: 14px; margin-top: 18px; }}
.arch .box {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }}
.arch .box h4 {{ margin: 0 0 8px; font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  color: var(--mute); }}
.arch .pr {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; }}
.arch .pr div {{ display: flex; gap: 8px; font-size: 12.5px; line-height: 1.4; }}
.arch .pr .ms {{ color: var(--good); font-size: 20px; }}
.arch .where div {{ display: flex; justify-content: space-between; gap: 10px; font-size: 12.5px; padding: 3px 0;
  border-bottom: 1px solid var(--line); }}
.arch .where div:last-child {{ border: none; }}
.arch .chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.arch .chip {{ font-size: 12.5px; background: var(--soft); border: 1px solid var(--line); border-radius: 999px;
  padding: 2px 10px; }}
@media (max-width: 1100px) {{
  .arch .flow {{ grid-template-columns: repeat(3, minmax(0, 1fr)); row-gap: 14px; }}
  .arch .step:nth-child(3) {{ margin-right: 0; }} .arch .step:nth-child(3)::after, .arch .step:nth-child(3)::before
  {{ display: none; }}
  .arch .serve, .arch .row3 {{ grid-template-columns: 1fr; }} }}
</style>"""


def ms(name: str) -> str:
    return f'<span class="ms" aria-hidden="true">{escape(name)}</span>'


flow = "".join(
    f'<div class="step{" graph" if name == "Knowledge graph" else ""}"><span class="n">{i + 1:02d}</span>'
    f'<div class="hd">{ms(ic)}<b>{escape(name)}</b></div><p>{escape(text)}</p><code>{escape(where)}</code></div>'
    for i, (ic, name, text, where) in enumerate(ARCHITECTURE))
serve = "".join(f'<div class="sv">{ms(ic)}<div><b>{escape(name)}</b><p>{escape(text)}</p><code>{escape(where)}'
                f'</code></div></div>' for ic, name, text, where in SUPPORT)
principles = "".join(f'<div>{ms(ic)}<span><b>{escape(n)}.</b> {escape(t)}</span></div>' for ic, n, t in PRINCIPLES)
where = "".join(f"<div><span>{escape(w)}</span><code>{escape(p)}</code></div>" for w, p in WHERE)
stack = "".join(f'<span class="chip">{escape(s)}</span>' for s in STACK)

hero("Six steps in a line, three helpers underneath.",
     "Files come in on the left and are never changed. Each step hands the next one a simpler, more certain shape, "
     "until every page and the agent read one knowledge graph per building.")
st.html(CSS + f"""<div class="arch">
<div class="flow">{flow}</div>
<div class="serve">{serve}</div>
<div class="row3">
  <div class="box"><h4>Principles</h4><div class="pr">{principles}</div></div>
  <div class="box where"><h4>Where data lives</h4>{where}</div>
  <div class="box"><h4>Built with</h4><div class="chips">{stack}</div></div>
</div></div>""")
