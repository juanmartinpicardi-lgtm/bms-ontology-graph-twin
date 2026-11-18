"""The app's typeface: Roobert (variable, weights 300-900), from Roobert.zip at the repo root.

Streamlit itself loads it from app/static/fonts (see .streamlit/config.toml). The standalone HTML views (3D viewers,
graph, sequences, tour...) run in iframes and are also saved as files, so they carry the font inline as a data URI:
each template has a `<!--__FONTS__-->` slot that `with_fonts` fills."""

import base64
from functools import lru_cache
from pathlib import Path

FAMILY = "Roobert"
FONT_FILE = Path(__file__).resolve().parent / "app" / "static" / "fonts" / "RoobertVF.woff2"
SLOT = "<!--__FONTS__-->"


@lru_cache(maxsize=1)
def font_face_css() -> str:
    data = base64.b64encode(FONT_FILE.read_bytes()).decode("ascii")
    return (f'@font-face {{ font-family: "{FAMILY}"; font-style: normal; font-weight: 300 900; font-display: swap; '
            f'src: url(data:font/woff2;base64,{data}) format("woff2"); }}')


def with_fonts(html: str) -> str:
    """Fill the template's font slot with the inline @font-face."""
    return html.replace(SLOT, f"<style>{font_face_css()}</style>", 1)
