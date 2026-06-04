"""Theme ownership for RiskCalc UI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    bg0: str = "#0f0f11"
    bg1: str = "#1a1a1e"
    bg1_alt: str = "#141416"
    bg2: str = "#242428"
    bg2_alt: str = "#1e1e22"
    bg3: str = "#2e2e33"
    bg4: str = "#38383d"
    bg5: str = "#4a4a52"
    txt0: str = "#f0f0f2"
    txt1: str = "#a0a0a8"
    txt2: str = "#606068"
    accent: str = "#d97757"
    accent_hi: str = "#e08464"
    accent_lo: str = "#d06a44"
    green: str = "#30d158"
    red: str = "#ff453a"
    red_text: str = "#ff6b5a"
    amber: str = "#ffd60a"
    white: str = "#ffffff"
    status_valid_bg: str = "#182a1c"
    status_valid_border: str = "#246030"
    status_approx_bg: str = "#2a2518"
    status_approx_border: str = "#604820"
    status_prototype_bg: str = "#242430"
    status_prototype_text: str = "#a0a0f0"
    status_prototype_border: str = "#404060"
    status_placeholder_bg: str = "#2a2020"
    status_placeholder_border: str = "#6a3020"
    status_broken_bg: str = "#2a1a18"
    status_broken_border: str = "#6a2820"


PALETTE = ThemePalette()


def color(name: str) -> str:
    """Return a named theme color."""
    return getattr(PALETTE, name)


def status_style(status_value: str) -> tuple[str, str]:
    """Return stylesheet fragment and display text for model status."""
    styles = {
        "Validated": (
            f"background:{PALETTE.status_valid_bg};color:{PALETTE.green};"
            f"border:1px solid {PALETTE.status_valid_border};",
            "✓ Validated",
        ),
        "Approximation": (
            f"background:{PALETTE.status_approx_bg};color:{PALETTE.amber};"
            f"border:1px solid {PALETTE.status_approx_border};",
            "~ Approximation",
        ),
        "Prototype": (
            f"background:{PALETTE.status_prototype_bg};color:{PALETTE.status_prototype_text};"
            f"border:1px solid {PALETTE.status_prototype_border};",
            "⚗ Prototype",
        ),
        "Placeholder": (
            f"background:{PALETTE.status_placeholder_bg};color:{PALETTE.accent};"
            f"border:1px solid {PALETTE.status_placeholder_border};",
            "◌ Placeholder",
        ),
        "Broken": (
            f"background:{PALETTE.status_broken_bg};color:{PALETTE.red};"
            f"border:1px solid {PALETTE.status_broken_border};",
            "✕ Broken",
        ),
    }
    return styles.get(status_value, ("", status_value))


def value_color(value) -> str:
    """Color convention for numeric KPI/metric values."""
    if isinstance(value, (int, float)):
        if value > 0:
            return PALETTE.green
        if value < 0:
            return PALETTE.red
    return PALETTE.txt0


# Compatibility: app.styles remains the historical stylesheet module. New UI code
# should import theme tokens from ui.theme instead of defining local palettes.
try:
    from app.styles import APP_STYLE, LIGHT_STYLE
except Exception:  # pragma: no cover - allows docs/static imports without Qt app context
    APP_STYLE = ""
    LIGHT_STYLE = ""
