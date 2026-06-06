"""Phase 0 — light theme tokens and base primitives.

Guards the design-migration foundation: the active palette is LIGHT, both
palettes expose the same token surface, light values are actually light with
readable contrast, and the card elevation helper applies a shadow effect.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dataclasses
import warnings
import pytest

warnings.filterwarnings("ignore")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.theme import DARK, LIGHT, PALETTE, ThemePalette, status_style, value_color

# New design tokens introduced in Phase 0 that screens will rely on.
NEW_TOKENS = [
    "bg_window", "bg_card", "bg_field", "bg_footer", "card_border",
    "txt_table", "txt_nav", "accent_pressed", "accent_on",
    "positive", "positive_soft", "warn_text", "warn_dot", "warn_soft",
    "scroll_track", "scroll_thumb", "shadow_color", "shadow_alpha",
]


def _luminance(hex_color: str) -> float:
    """Relative luminance for an #rrggbb color (used only for solid hex tokens)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_active_palette_is_light():
    assert PALETTE is LIGHT


def test_both_palettes_share_token_surface():
    dark_fields = {f.name for f in dataclasses.fields(DARK)}
    light_fields = {f.name for f in dataclasses.fields(LIGHT)}
    assert dark_fields == light_fields
    for token in NEW_TOKENS:
        assert hasattr(LIGHT, token) and hasattr(DARK, token), token


def test_light_surfaces_are_light_and_text_is_dark():
    assert LIGHT.bg_card == "#FFFFFF"
    assert LIGHT.bg_window == "#FBFBFD"
    # primary text far darker than the card it sits on
    assert _luminance(LIGHT.txt0) < 0.2
    assert _luminance(LIGHT.bg_card) > 0.9


def test_primary_text_contrast_meets_aa():
    # WCAG AA for normal text is 4.5:1
    assert _contrast(LIGHT.txt0, LIGHT.bg_card) >= 4.5
    assert _contrast(LIGHT.txt1, LIGHT.bg_card) >= 4.5


def test_dark_palette_unchanged():
    # DARK must still equal the historical values (no accidental drift).
    assert DARK.bg_card == "#212123"
    assert DARK.txt0 == "#F2F4F7"
    assert DARK.accent == "#D97757"


def test_accent_is_terracotta_in_both():
    assert LIGHT.accent == "#D9633F"
    assert DARK.accent == "#D97757"


def test_status_and_value_helpers_resolve():
    for st in ("Validated", "Approximation", "Prototype", "Placeholder", "Broken"):
        style, text = status_style(st)
        assert style and text
    assert value_color(1.0) == PALETTE.green
    assert value_color(-1.0) == PALETTE.red
    assert value_color("n/a") == PALETTE.txt0


def test_workstation_style_builds_from_light():
    from ui.theme import WORKSTATION_STYLE
    assert PALETTE.accent in WORKSTATION_STYLE
    assert PALETTE.bg_card in WORKSTATION_STYLE


def test_card_shadow_applies_effect():
    from PySide6.QtWidgets import QApplication, QFrame
    from ui.components import card_shadow
    _ = QApplication.instance() or QApplication([])
    frame = QFrame()
    effect = card_shadow(frame)
    assert frame.graphicsEffect() is effect
    assert effect.blurRadius() > 0


def test_workspace_card_uses_light_surface():
    from PySide6.QtWidgets import QApplication
    from ui.components import WorkspaceCard
    _ = QApplication.instance() or QApplication([])
    card = WorkspaceCard(elevated=True)
    assert PALETTE.bg_card in card.styleSheet()
    assert card.graphicsEffect() is not None
