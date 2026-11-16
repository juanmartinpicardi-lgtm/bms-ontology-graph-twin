"""A viewer page inside the app that can talk back: the page runs in its own frame (its own scripts and styles, as
the other 3D viewers do), receives data from the app without reloading, and sends clicks back to it.

The page's side of the conversation:
    parent.postMessage({pm: "ready"}, "*")                      once, when it can take data
    addEventListener("message", e => e.data.pm === "data" ...)  e.data.data is the `msg` given here
    parent.postMessage({pm: "event", value: {...}}, "*")        returned by frame() on the rerun it triggers

The frame is rebuilt only when `page_key` changes; a new `msg` is posted to the page that is already there, so the
viewer keeps its camera across reruns.
"""
from __future__ import annotations

import hashlib
import json

import streamlit as st

JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  let f = parentElement.querySelector("iframe");
  if (!f || f._key !== data.key) {
    if (f) { removeEventListener("message", f._onmsg); f.remove(); }
    f = document.createElement("iframe");
    f._key = data.key;
    f._ready = false;
    f.setAttribute("allow", "fullscreen");
    f.setAttribute("title", data.title || "Viewer");
    f.style.cssText = "width:100%;border:0;display:block;border-radius:10px";
    f.srcdoc = data.html;
    f._onmsg = (e) => {
      if (e.source !== f.contentWindow || !e.data || !e.data.pm) return;
      if (e.data.pm === "ready") {
        f._ready = true;
        if (f._msg !== undefined) f.contentWindow.postMessage({ pm: "data", data: f._msg }, "*");
      } else if (e.data.pm === "event") {
        f._emit(e.data.value);
      }
    };
    addEventListener("message", f._onmsg);
    parentElement.appendChild(f);
  }
  f._emit = (v) => setTriggerValue("event", { ...v, at: Date.now() });
  f.style.height = typeof data.height === "number" ? data.height + "px" : data.height;  // or a CSS length
  if (f._stamp !== data.stamp) {
    f._stamp = data.stamp;
    f._msg = data.msg;
    if (f._ready) f.contentWindow.postMessage({ pm: "data", data: f._msg }, "*");
  }
}
"""

_frame = st.components.v2.component("projectmodel.frame", js=JS)


def frame(html: str, msg, height: int | str, key: str, page_key: str = "", title: str = "") -> dict | None:
    """Show `html` in a frame and post `msg` to it. Returns the event the page sent, on the rerun it caused."""
    stamp = hashlib.md5(json.dumps(msg, sort_keys=True, default=str).encode()).hexdigest()
    page_key = page_key or hashlib.md5(html.encode()).hexdigest()
    result = _frame(data={"html": html, "key": page_key, "msg": msg, "stamp": stamp, "height": height, "title": title},
                    key=key, on_event_change=lambda: None)
    return result.event
