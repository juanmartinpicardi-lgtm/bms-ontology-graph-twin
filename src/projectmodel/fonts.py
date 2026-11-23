"""The app's typeface: Roobert (variable, weights 300-900), from Roobert.zip at the repo root.

Streamlit itself loads it from app/static/fonts (see .streamlit/config.toml). The standalone HTML views (3D viewers,
graph, sequences, tour...) run in iframes and are also saved as files: each template has a `<!--__FONTS__-->` slot
that `with_fonts` fills. Inside the running app the slot links the font Streamlit already serves, so the browser
fetches it once for every view; a saved file (scripts/export_*.py) carries it inline as a data URI, so it opens
anywhere."""

import base64
from functools import lru_cache
from pathlib import Path

FAMILY = "Roobert"
FONT_FILE = Path(__file__).resolve().parent / "app" / "static" / "fonts" / "RoobertVF.woff2"
# Relative, as in .streamlit/config.toml: an iframe's srcdoc page resolves it against the app page's own address
STATIC_URL = "app/static/fonts/RoobertVF.woff2"
SLOT = "<!--__FONTS__-->"


def _face(src: str) -> str:
    return (f'@font-face {{ font-family: "{FAMILY}"; font-style: normal; font-weight: 300 900; font-display: swap; '
            f'src: url({src}) format("woff2"); }}')


@lru_cache(maxsize=1)
def font_face_css() -> str:
    """The inline @font-face (about 160 KB), for pages saved as files."""
    return _face("data:font/woff2;base64," + base64.b64encode(FONT_FILE.read_bytes()).decode("ascii"))


def _in_app() -> bool:
    try:
        from streamlit import runtime
        return runtime.exists()
    except Exception:  # streamlit missing or not running: a script writing a file
        return False


def with_fonts(html: str, inline: bool | None = None) -> str:
    """Fill the template's font slot: linked to the app's static font when running in the app, else inline."""
    css = font_face_css() if (not _in_app() if inline is None else inline) else _face(STATIC_URL)
    return html.replace(SLOT, f"<style>{css}</style>", 1)
