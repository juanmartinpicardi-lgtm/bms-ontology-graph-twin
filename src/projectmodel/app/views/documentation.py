"""Documentation: every document of the active project in one place, by category (library.py).

The files the guided setup read, the files added here, and the raw source data a Haystack site came from. Shown as a
list or as large tiles with a preview of each document; add more (the category is guessed from the name and can be
changed), and open, download, replace or delete each one. Replacing or deleting a file the setup read reads that step
again and re-publishes it, so the knowledge graph follows. Source data is read-only.
"""

import io
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import library  # noqa: E402
from projectmodel.app.shell import THEME, active_project, box, get_store, page_tools, theme  # noqa: E402
from projectmodel.projects import list_projects  # noqa: E402

C = THEME[theme()]
VIEWS = {"grid": ":material/grid_view: Tiles", "list": ":material/view_list: List"}
ORIGIN = {"setup": ("Read by the setup", "blue"), "library": ("Added here", "violet"), "source": ("Source data", "gray")}

store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)

st.html(f"""<style>
/* A tile: the preview on top (a fixed height, cropped from the top like a sheet), the name and the actions below */
[class*="st-key-box_doc_"] {{ padding: 10px 12px !important; gap: 6px !important; }}
.doc-thumb {{ height: 170px; border-radius: 4px; overflow: hidden; background: {C["card2"]};
  border: 1px solid {C["line"]}; display: flex; align-items: flex-start; justify-content: center; }}
.doc-thumb img {{ width: 100%; height: 100%; object-fit: cover; object-position: top; }}
.doc-thumb.icon {{ align-items: center; flex-direction: column; gap: 6px; color: {C["mute"]}; }}
.doc-thumb .ms {{ font-family: 'Material Symbols Rounded'; font-size: 54px; color: {C["accent"]}; line-height: 1; }}
.doc-thumb pre {{ margin: 0; padding: 10px; width: 100%; height: 100%; overflow: hidden; font-size: 10.5px;
  line-height: 1.35; color: {C["text2"]}; white-space: pre-wrap; word-break: break-all; text-align: left; }}
.doc-name {{ font-weight: 500; font-size: 14px; color: {C["text"]}; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }}
.doc-meta {{ font-size: 12px; color: {C["mute"]}; }}
.doc-cat {{ display: flex; align-items: center; gap: 8px; margin: 14px 0 4px; font-size: 13px; font-weight: 500;
  letter-spacing: 1px; text-transform: uppercase; color: {C["text2"]}; }}
.doc-cat .ms {{ font-family: 'Material Symbols Rounded'; font-size: 19px; color: {C["accent"]}; letter-spacing: 0;
  text-transform: none; }}
.doc-cat .n {{ font-size: 12px; color: {C["mute"]}; letter-spacing: .3px; }}
.st-key-doc_actions [data-testid^="stBaseButton-"], [class*="st-key-docact_"] [data-testid^="stBaseButton-"],
[class*="st-key-docact_"] [data-testid="stPopoverButton"] {{ min-height: 32px; padding: 0 8px; }}
</style>""")


def key_of(d: library.Doc) -> str:
    import hashlib
    return hashlib.sha1(d.id.encode()).hexdigest()[:10]


def human(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


@st.cache_data(show_spinner=False, max_entries=200)
def pdf_thumb(path: str, mtime: float) -> bytes | None:
    try:
        from projectmodel.intake import pdfdoc
        buf = io.BytesIO()
        pdfdoc.render(Path(path), 0, width=420).save(buf, "PNG", optimize=True)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 - a damaged or encrypted PDF: the icon instead
        return None


@st.cache_data(show_spinner=False, max_entries=30)
def pdf_page(path: str, mtime: float, page: int) -> bytes:
    from projectmodel.intake import pdfdoc
    buf = io.BytesIO()
    pdfdoc.render(Path(path), page, width=1600).save(buf, "PNG", optimize=True)
    return buf.getvalue()


@st.cache_data(show_spinner=False, max_entries=200)
def image_thumb(path: str, mtime: float) -> bytes | None:
    try:
        from PIL import Image
        im = Image.open(path)
        im.thumbnail((480, 480))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=80)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


def text_head(path: Path, n: int = 1600) -> str:
    try:
        with path.open("rb") as f:
            return f.read(n).decode("utf-8", "replace")
    except OSError:
        return ""


def thumb_html(d: library.Doc) -> str:
    """The tile's preview: page 1 of a PDF, the image itself, the first lines of a text file, else the type's icon."""
    import base64
    import html
    mtime = d.path.stat().st_mtime if d.path.exists() else 0
    data = mime = None
    if d.ext == "pdf":
        data, mime = pdf_thumb(str(d.path), mtime), "image/png"
    elif d.ext in library.IMAGES:
        data, mime = image_thumb(str(d.path), mtime), "image/jpeg"
    if data:
        return f'<div class="doc-thumb"><img alt="" src="data:{mime};base64,{base64.b64encode(data).decode()}"></div>'
    if d.ext in library.TEXT:
        return f'<div class="doc-thumb"><pre>{html.escape(text_head(d.path, 900))}</pre></div>'
    return (f'<div class="doc-thumb icon"><span class="ms" aria-hidden="true">{d.icon}</span>'
            f'<span>{html.escape(d.kind)}</span></div>')


def meta(d: library.Doc) -> str:
    when = time.strftime("%d %b %Y", time.localtime(d.added)) if d.added else ""
    pages = ""
    if d.ext == "pdf" and d.path.exists():
        try:
            from projectmodel.intake import pdfdoc
            pages = f" · {pdfdoc.page_count(d.path)} p."
        except Exception:  # noqa: BLE001
            pass
    return f"{d.kind} · {human(d.size)}{pages}" + (f" · {when}" if when else "")


@st.dialog("Document", width="large")
def preview(doc_id: str) -> None:
    d = library.find(project, doc_id)
    if not d or not d.path.exists():
        st.warning("This document is no longer here.")
        return
    st.markdown(f"**{d.name}**  \n:small[{d.category} · {meta(d)} · {ORIGIN[d.origin][0]}]")
    if d.note:
        st.caption(d.note)
    if d.ext == "pdf":
        from projectmodel.intake import pdfdoc
        n = pdfdoc.page_count(d.path)
        page = st.number_input(f"Page (of {n})", 1, n, 1, key=f"pv_page_{doc_id}") if n > 1 else 1
        st.image(pdf_page(str(d.path), d.path.stat().st_mtime, page - 1))
    elif d.ext in library.IMAGES:
        st.image(str(d.path))
    elif d.ext in ("csv", "tsv"):
        try:
            st.dataframe(pd.read_csv(d.path, sep="\t" if d.ext == "tsv" else ",", nrows=500), height=520)
        except Exception as e:  # noqa: BLE001
            st.code(text_head(d.path, 6000))
            st.caption(f"Could not read it as a table: {e}")
    elif d.ext in library.TEXT:
        st.code(text_head(d.path, 20000), language={"json": "json", "yaml": "yaml", "yml": "yaml", "md": "markdown",
                                                     "xml": "xml"}.get(d.ext))
    else:
        from projectmodel import fileread
        content = fileread.read(d.name, d.path.read_bytes())
        if content.text.strip():
            st.code(content.text[:20000], language=None, wrap_lines=True)
        else:
            st.info(content.note or f"No preview for {d.kind} files yet: download it to open it.",
                    icon=":material/visibility_off:")
    st.download_button("Download", d.path.read_bytes(), file_name=d.name, icon=":material/download:")
    interpret(d)


def interpret(d: library.Doc) -> None:
    """What the document is, read by a model from any format: a title, a summary, the equipment it names and what it
    can feed. Kept with the project so it is asked once per file."""
    from projectmodel import file_ai, fileread
    st.divider()
    got = library.get_digest(project, d)
    if not got:
        st.caption("Have the file read: what it is, its category, the equipment it names and what it can feed.")
        if not st.button("What is this document?", icon=":material/auto_awesome:", key=f"dig_{d.id}"):
            return
        content = fileread.read(d.name, d.path.read_bytes())
        if not content.readable:
            st.info(content.note or "Nothing readable in this file.", icon=":material/visibility_off:")
            return
        try:
            with st.spinner(f"Reading {d.name}…"):
                got = file_ai.digest(content, d.name, project, list(library.CATEGORIES), store=store)
        except Exception as e:  # noqa: BLE001 - AI off, or every model failed
            st.warning(f"Could not be read by a model: {e}", icon=":material/cloud_off:")
            return
        library.save_digest(project, d, got)
    st.markdown(f"**{got['title']}**")
    st.write(got["summary"])
    if got["equipment"]:
        st.caption("Equipment named: " + ", ".join(got["equipment"]))
    st.caption(f"Can feed: {', '.join(got['useful_for'])} · read by {got['model']} · ${got['cost_usd']:.3f}")
    if got["category"] != d.category:
        if d.origin == "library":
            st.button(f"Move to {got['category']}", icon=":material/drive_file_move:", key=f"mv_{d.id}",
                      on_click=library.set_category, args=(project, d.id, got["category"]))
        else:
            st.caption(f"Looks like {got['category']}.")


def do_delete(d: library.Doc) -> None:
    try:
        with st.spinner(f"Removing {d.name}…" + (" Reading the step again." if d.origin == "setup" else "")):
            library.delete(project, d, store)
        st.toast(f"{d.name} deleted", icon=":material/delete:")
    except ValueError as e:
        st.toast(str(e), icon=":material/lock:")


def actions(d: library.Doc, k: str, compact: bool) -> None:
    """Open, download, replace, change category, delete: icon buttons in a row."""
    with st.container(horizontal=True, gap="small", vertical_alignment="center", key=f"docact_{k}"):
        st.button("" if compact else "Open", icon=":material/visibility:", key=f"open_{k}", on_click=preview,
                  args=(d.id,), help="Preview", type="tertiary")
        if d.path.exists():
            st.download_button("", d.path.read_bytes(), file_name=d.name, icon=":material/download:",
                               key=f"dl_{k}", help="Download", type="tertiary", on_click="ignore")
        if not d.editable:
            st.button("", icon=":material/lock:", key=f"lock_{k}", disabled=True, type="tertiary",
                      help="Source data is read-only: the raw sources are never changed.")
            return
        with st.popover("", icon=":material/more_horiz:", help="Replace, move, delete"):
            st.markdown(f"**{d.name}**")
            new = st.file_uploader("Replace with a new version", key=f"rep_{k}_{st.session_state.get('doc_nonce', 0)}")
            if new is not None:
                with st.spinner("Replacing…" + (" Reading the step again." if d.origin == "setup" else "")):
                    library.replace(project, d, new.name, new.getvalue(), store)
                st.session_state["doc_nonce"] = st.session_state.get("doc_nonce", 0) + 1
                st.toast(f"{d.name} replaced by {new.name}", icon=":material/swap_horiz:")
                st.rerun()
            if d.origin == "setup":
                st.caption("Read by the guided setup: replacing or deleting it reads that step again and updates the "
                           "knowledge graph. Your answers are kept.")
            else:
                cats = list(library.CATEGORIES)
                cat = st.selectbox("Category", cats, index=cats.index(d.category) if d.category in cats else
                                   len(cats) - 1, key=f"cat_{k}")
                if cat != d.category:
                    library.set_category(project, d.id, cat)
                    st.rerun()
            sure = st.checkbox("Delete it for good: it cannot be undone", key=f"delok_{k}")
            with st.container(key=f"del_{k}"):
                st.button("Delete", icon=":material/delete:", key=f"delbtn_{k}", on_click=do_delete, args=(d,),
                          disabled=not sure, help="Removes the file from this project")


def tile(d: library.Doc, k: str) -> None:
    with box(f"doc_{k}"):
        st.html(thumb_html(d))
        st.html(f'<div class="doc-name" title="{d.name}">{d.name}</div><div class="doc-meta">{meta(d)}</div>')
        label, color = ORIGIN[d.origin]
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.badge(label, color=color)
            st.space("stretch")
        actions(d, k, compact=True)


def row(d: library.Doc, k: str) -> None:
    with st.container(horizontal=True, vertical_alignment="center", gap="medium", key=f"docrow_{k}"):
        st.markdown(f":material/{d.icon}:", width="content")
        st.markdown(f"**{d.name}**  \n:small[{meta(d)}]", width="stretch")
        label, color = ORIGIN[d.origin]
        st.badge(label, color=color, width="content")
        actions(d, k, compact=True)


def add_documents() -> None:
    with st.popover("Add documents", icon=":material/upload_file:", type="primary"):
        st.markdown("**Add documents to this project**")
        st.caption("Any file: PDF drawings and specs, spreadsheets, Word files, photos, exports. The category is "
                   "guessed from each file's name; change it after if needed.")
        cat = st.selectbox("Category", ["Guess from the name"] + list(library.CATEGORIES), key="doc_add_cat")
        ups = st.file_uploader("Files", accept_multiple_files=True, label_visibility="collapsed",
                               key=f"doc_add_{st.session_state.get('doc_nonce', 0)}")
        if ups and st.button("Add", type="primary", icon=":material/add:", key="doc_add_go"):
            for u in ups:
                library.add(project, u.name, u.getvalue(), None if cat == "Guess from the name" else cat)
            st.session_state["doc_nonce"] = st.session_state.get("doc_nonce", 0) + 1
            st.toast(f"{len(ups)} document{'s' if len(ups) > 1 else ''} added", icon=":material/check_circle:")
            st.rerun()


docs = library.documents(project)
s = library.summary(docs)
with page_tools():
    add_documents()

with box("docs", fit=True):
    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        st.html(f'<div class="box-title"><span class="ms">folder_open</span><span>Documentation</span></div>',
                width="content")
        st.caption(f"{s['count']} documents · {human(s['bytes'])} · {len(s['by_category'])} categories",
                   width="content")
        st.space("stretch")
        q = st.text_input("Find", key="doc_q", placeholder="Find a document…", icon=":material/search:",
                          label_visibility="collapsed", width=260)
        st.session_state.setdefault("doc_view", "grid")
        view = st.segmented_control("View", list(VIEWS), key="doc_view", format_func=VIEWS.get,
                                    label_visibility="collapsed") or "grid"
    cats = [c for c in library.CATEGORIES if s["by_category"].get(c)]
    pick = st.pills("Category", cats, selection_mode="multi", key="doc_cats", label_visibility="collapsed",
                    format_func=lambda c: f"{c} {s['by_category'][c]}")
    shown = [d for d in docs if (not pick or d.category in pick) and (not q or q.lower() in d.name.lower())]
    if not docs:
        st.info("No documents yet. Add the drawings, schedules, specifications and exports you have with **Add "
                "documents** at the top right, or start the building from its documents in **Add a building**.",
                icon=":material/folder_open:")
    elif not shown:
        st.info("No document matches. Clear the search or a category.", icon=":material/filter_alt_off:")
    for c in [c for c in library.CATEGORIES if any(d.category == c for d in shown)]:
        group = [d for d in shown if d.category == c]
        st.html(f'<div class="doc-cat"><span class="ms" aria-hidden="true">{library.CATEGORIES[c]}</span>{c}'
                f'<span class="n">{len(group)}</span></div>')
        if view == "grid":
            per = 5
            for start in range(0, len(group), per):
                cols = st.columns(per, gap="small")
                for col, d in zip(cols, group[start:start + per]):
                    with col:
                        tile(d, key_of(d))
        else:
            with st.container(border=True):
                for i, d in enumerate(group):
                    if i:
                        st.divider()
                    row(d, key_of(d))
