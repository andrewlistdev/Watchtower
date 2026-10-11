"""Build the Watchtower logo assets (BRAND_GUIDE.md §3).

Writes:
  watchtower/brand_assets.py       path data used by the WatchtowerLogo component
  watchtower/static/brand/*.svg    standalone logo files for docs, slides, favicons

The wordmark is converted to outlines from the bundled Space Grotesk font, so the
SVG files render identically everywhere without the font installed. To swap in
designer artwork later, replace the files in static/brand and the constants in
brand_assets.py; the component reads only those.

Run from the repo root:  python scripts/build_brand_assets.py
Needs (dev only):        pip install fonttools brotli uharfbuzz
"""

from __future__ import annotations

import io
import textwrap
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "watchtower/static/fonts/space-grotesk-latin-600-normal.woff2"
OUT_DIR = ROOT / "watchtower/static/brand"
OUT_PY = ROOT / "watchtower/brand_assets.py"

# Palette (BRAND_GUIDE.md §5)
TEAL, CLOUD, MIDNIGHT, BLUE = "#35D0BA", "#F1F5F9", "#0B1220", "#1E4770"

# ---- The mark, on a 32 x 32 grid --------------------------------------------
# A fire-watch lookout: pointed roof with a beacon light, a lookout cabin with a
# viewing slot, and tall splayed legs with a cross-brace. One even-odd path, so it
# works in a single colour and never needs a background shape.
MARK = " ".join([
    "M5.6 9.4L16 1.2L26.4 9.4Z M16 4.6a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3Z",  # roof + beacon light
    "M7.8 10.6H24.2V16.6H7.8Z M10.4 12.6V14.6H21.6V12.6Z",                    # cabin + viewing slot
    "M10.2 17.8H21.8L25.8 30.8H6.2Z M16 20.2L19.5 25H12.5Z M11.9 26.6H20.1L21.4 30.8H10.6Z",  # legs + brace
])

# Small-size icon (16-24 px): same silhouette with the fine details removed and
# the openings enlarged so nothing closes up when pixels are scarce.
MARK_SMALL = " ".join([
    "M4.8 10L16 1L27.2 10Z",                                   # roof
    "M7 11.4H25V18.4H7Z M10 13.6V16.2H22V13.6Z",               # cabin + slot
    "M9.8 19.8H22.2L26.4 31H5.6Z M16 22.4L21.3 31H10.7Z",       # legs
])

WORD = "WATCHTOWER"
TRACKING_EM = 0.04  # restrained letter spacing


def wordmark() -> tuple[str, float, float]:
    """Outline WORD; returns (path, width, cap height) in font units, baseline at y=0."""
    font = TTFont(str(FONT))
    upem = font["head"].unitsPerEm
    cap = font["OS/2"].sCapHeight or font["head"].unitsPerEm * 0.7
    glyphset = font.getGlyphSet()

    # HarfBuzz reads plain sfnt, not woff2: re-save the font uncompressed in memory.
    buf = io.BytesIO()
    font.flavor = None
    font.save(buf)
    hb_font = hb.Font(hb.Face(hb.Blob(buf.getvalue())))
    hb_buf = hb.Buffer()
    hb_buf.add_str(WORD)
    hb_buf.guess_segment_properties()
    hb.shape(hb_font, hb_buf, {"kern": True})

    order = font.getGlyphOrder()
    pen = SVGPathPen(glyphset)
    x = 0.0
    track = TRACKING_EM * upem
    for info, pos in zip(hb_buf.glyph_infos, hb_buf.glyph_positions):
        name = order[info.codepoint]
        # Flip y so the outline is SVG-native (y down), baseline at 0.
        glyphset[name].draw(TransformPen(pen, (1, 0, 0, -1, x + pos.x_offset, -pos.y_offset)))
        x += pos.x_advance + track
    width = x - track
    return pen.getCommands(), width, float(cap)


def fmt(n: float) -> str:
    return f"{n:.2f}".rstrip("0").rstrip(".")


def build() -> None:
    word_path, word_w, cap = wordmark()

    # Horizontal lockup, in mark units (mark is 32 tall). Caps are 13 units tall
    # and centred on the cabin; 9 units of space between mark and wordmark.
    scale = 13.0 / cap
    gap = 9.0
    word_x = 32 + gap
    baseline = 16 + 13.0 / 2  # caps centred on the mark's vertical middle
    total_w = word_x + word_w * scale
    word_transform = f"translate({fmt(word_x)} {fmt(baseline)}) scale({scale:.6f})"

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def svg(view_w: float, body: str, title: str) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {fmt(view_w)} 32" '
                f'role="img" aria-label="{title}"><title>{title}</title>{body}</svg>\n')

    def lockup(mark_fill: str, word_fill: str) -> str:
        return (f'<path fill="{mark_fill}" fill-rule="evenodd" d="{MARK}"/>'
                f'<path fill="{word_fill}" transform="{word_transform}" d="{word_path}"/>')

    files = {
        "watchtower-logo-on-dark.svg": svg(total_w, lockup(TEAL, CLOUD), "Watchtower"),
        "watchtower-logo-on-light.svg": svg(total_w, lockup(BLUE, MIDNIGHT), "Watchtower"),
        "watchtower-logo-mono.svg": svg(total_w, lockup("currentColor", "currentColor"), "Watchtower"),
        "watchtower-mark.svg": svg(32, f'<path fill="{TEAL}" fill-rule="evenodd" d="{MARK}"/>', "Watchtower"),
        "watchtower-mark-mono.svg": svg(32, f'<path fill="currentColor" fill-rule="evenodd" d="{MARK}"/>', "Watchtower"),
        "watchtower-icon-small.svg": svg(32, f'<path fill="{TEAL}" fill-rule="evenodd" d="{MARK_SMALL}"/>', "Watchtower"),
        # Favicon / launcher: the small mark on a midnight tile so it reads on light and dark tabs.
        "favicon.svg": svg(32, f'<rect width="32" height="32" rx="7" fill="{MIDNIGHT}"/>'
                               f'<path fill="{TEAL}" fill-rule="evenodd" transform="translate(4 4) scale(.75)" d="{MARK_SMALL}"/>',
                           "Watchtower"),
    }
    for name, content in files.items():
        (OUT_DIR / name).write_text(content)

    OUT_PY.write_text(textwrap.dedent(f'''\
        """Generated by scripts/build_brand_assets.py. Do not edit by hand.

        Path data for the WatchtowerLogo component (templates/components.html).
        Replace with approved designer artwork by regenerating or editing these values.
        """

        MARK = "{MARK}"
        MARK_SMALL = "{MARK_SMALL}"
        WORDMARK = "{word_path}"
        WORDMARK_TRANSFORM = "{word_transform}"
        LOCKUP_WIDTH = {total_w:.2f}  # viewBox width of mark + wordmark; height is 32
        '''))
    print(f"Wrote {len(files)} SVGs to {OUT_DIR.relative_to(ROOT)} and {OUT_PY.relative_to(ROOT)}")
    print(f"Lockup viewBox: 0 0 {total_w:.1f} 32")


if __name__ == "__main__":
    build()
