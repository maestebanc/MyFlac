"""Tonos de los temas claro y oscuro."""
import re

import pytest

style = pytest.importorskip("myflac.ui.style")

ALL_VARIANTS = [("light", v) for v in style.LIGHT_VARIANTS] + [("dark", v) for v in style.DARK_VARIANTS]
DEFAULTS = {"light": style.DEFAULT_LIGHT_VARIANT, "dark": style.DEFAULT_DARK_VARIANT}


def _luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("mode,variant", ALL_VARIANTS)
def test_variant_replaces_every_base_color(mode, variant):
    css = style.theme_css(mode, variant)
    colors = style.variants_for(mode)[variant]
    assert f"@define-color window_bg_color {colors['window']};" in css
    assert f"@define-color view_bg_color {colors['view']};" in css
    assert f"@define-color window_fg_color {colors['fg']};" in css
    if mode == "dark":
        assert f"@define-color card_bg_color {colors['card']};" in css
        assert f"@define-color popover_bg_color {colors['popover']};" in css
        assert f"@define-color dialog_bg_color {colors['dialog']};" in css
    if variant != DEFAULTS[mode]:
        default = style.variants_for(mode)[DEFAULTS[mode]]
        leftovers = {c for role, c in default.items() if role != "backdrop"} & set(re.findall(r"#[0-9a-f]{6}", css))
        assert not leftovers  # Ningún resto del tono por defecto (barra, popovers...)


@pytest.mark.parametrize("mode,variant", ALL_VARIANTS)
def test_text_contrast_is_comfortable(mode, variant):
    colors = style.variants_for(mode)[variant]
    for background in ("window", "view"):
        assert _contrast(colors["fg"], colors[background]) >= 7.0  # WCAG AAA


def test_backdrop_follows_active_tones(monkeypatch):
    from myflac.ui import backdrop

    monkeypatch.setitem(style._variants, "light", "paper")
    assert style.light_base_rgb() == (0xE6, 0xE0, 0xD6)
    assert backdrop.scrim_color(None, dark=False, intensity=42) == "rgba(230, 224, 214, 0.62)"
    monkeypatch.setitem(style._variants, "dark", "oled")
    assert backdrop.scrim_color(None, dark=True, intensity=42) == "rgba(2, 2, 2, 0.58)"
