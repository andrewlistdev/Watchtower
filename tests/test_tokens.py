"""WCAG 2.2 AA contrast checks on the real token values in static/tokens.css (BRAND_GUIDE.md §5, §12).

Text pairs need 4.5:1; UI component boundaries, focus indicators and status dots need 3:1.
Mixed backgrounds (badges, notices) are computed the same way the CSS color-mix() does.
"""

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent / "watchtower/static/tokens.css").read_text()


def block(selector_regex: str) -> dict[str, str]:
    m = re.search(selector_regex + r"\s*\{(.*?)\n\}", CSS, re.S | re.M)
    assert m, selector_regex
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", m.group(1)))


PALETTE = block(r"^:root")  # first :root block holds the raw --wt-* values
THEMES = {
    "dark": block(r':root,\s*\[data-theme="dark"\]'),
    "light": block(r'\[data-theme="light"\]'),
}


def resolve(theme: str, name: str) -> str:
    value = THEMES[theme].get(name) or PALETTE[name]
    while value.startswith("var("):
        ref = value[4:-1].strip()
        value = THEMES[theme].get(ref) or PALETTE[ref]
    return value.strip()


def rgb(hex_: str) -> tuple[float, float, float]:
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def luminance(c) -> float:
    def ch(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(fg, bg, pct: float):
    return tuple(f * pct + b * (1 - pct) for f, b in zip(fg, bg))


def c(theme, name):
    return rgb(resolve(theme, name))


TEXT_PAIRS = [
    ("--text", "--bg"), ("--text", "--surface"), ("--text", "--raised"),
    ("--text-muted", "--bg"), ("--text-muted", "--surface"), ("--text-muted", "--raised"),
    ("--link", "--surface"), ("--link", "--bg"),
    ("--accent-ink", "--accent"), ("--support-ink", "--support"),
    ("--status-error", "--surface"),          # inline field errors
]
UI_PAIRS = [
    ("--control-border", "--control-bg"), ("--control-border", "--surface"),
    ("--focus", "--bg"), ("--focus", "--surface"),
    ("--accent-border", "--surface"),        # primary button edge
    ("--status-escalated", "--surface"),     # handoff window
]
TONES = ["unassigned", "routed", "acknowledged", "escalated", "resolved", "error", "info"]


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("fg,bg", TEXT_PAIRS)
def test_text_contrast(theme, fg, bg):
    ratio = contrast(c(theme, fg), c(theme, bg))
    assert ratio >= 4.5, f"{theme}: {fg} on {bg} is {ratio:.2f}:1"


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("fg,bg", UI_PAIRS)
def test_ui_contrast(theme, fg, bg):
    ratio = contrast(c(theme, fg), c(theme, bg))
    assert ratio >= 3.0, f"{theme}: {fg} against {bg} is {ratio:.2f}:1"


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("tone", TONES)
def test_status_dots_and_badge_text(theme, tone):
    surface = c(theme, "--surface")
    tone_c = c(theme, f"--status-{tone}")
    assert contrast(tone_c, surface) >= 3.0, f"{theme}: {tone} dot is {contrast(tone_c, surface):.2f}:1"
    badge_bg = mix(tone_c, surface, 0.14)
    notice_bg = mix(tone_c, surface, 0.10)
    assert contrast(c(theme, "--text"), badge_bg) >= 4.5
    assert contrast(c(theme, "--text"), notice_bg) >= 4.5


def test_dark_is_default_and_palette_matches_guide():
    assert PALETTE["--wt-midnight"] == "#0B1220"
    assert PALETTE["--wt-teal"] == "#35D0BA"
    assert resolve("dark", "--bg") == "#0B1220" and resolve("dark", "--accent") == "#35D0BA"


def test_match_my_system_uses_the_light_values():
    system = block(r'\[data-theme="system"\]')
    assert system == THEMES["light"]
