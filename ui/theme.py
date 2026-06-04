"""Theme ownership for RiskCalc workstation UI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    bg0: str = "#0B0D10"
    bg1: str = "#111418"
    bg1_alt: str = "#14171C"
    bg2: str = "#1D2229"
    bg2_alt: str = "#181C22"
    bg3: str = "#2A313A"
    bg4: str = "#38404A"
    bg5: str = "#505A66"
    bg_topbar: str = "#0F1216"
    bg_workspace: str = "#14171C"
    bg_panel: str = "#181C22"
    bg_panel_elevated: str = "#1D2229"
    bg_table_header: str = "#202630"
    bg_table_row: str = "#15191F"
    bg_table_row_alt: str = "#181D24"
    bg_selected: str = "#2A211B"
    bg_warning: str = "#2A2115"
    bg_error: str = "#2A1518"
    bg_success: str = "#14231B"
    border_strong: str = "#38404A"
    border_default: str = "#2A313A"
    border_soft: str = "#20262E"
    divider: str = "#252C34"
    txt0: str = "#F2F4F7"
    txt1: str = "#B8C0CC"
    txt2: str = "#7C8796"
    text_disabled: str = "#505A66"
    accent: str = "#D97757"
    accent_hi: str = "#E08464"
    accent_lo: str = "#D06A44"
    accent_soft: str = "#3A251C"
    green: str = "#30D158"
    red: str = "#FF453A"
    red_text: str = "#FF6B5A"
    amber: str = "#FFD60A"
    blue: str = "#5AA9E6"
    cyan: str = "#4DD0E1"
    purple: str = "#B39DDB"
    white: str = "#FFFFFF"
    status_valid_bg: str = "#14231B"
    status_valid_border: str = "#246030"
    status_approx_bg: str = "#2A2115"
    status_approx_border: str = "#604820"
    status_prototype_bg: str = "#242430"
    status_prototype_text: str = "#B39DDB"
    status_prototype_border: str = "#404060"
    status_placeholder_bg: str = "#20262E"
    status_placeholder_border: str = "#505A66"
    status_broken_bg: str = "#2A1518"
    status_broken_border: str = "#6A2820"


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
            "VALIDATED",
        ),
        "Approximation": (
            f"background:{PALETTE.status_approx_bg};color:{PALETTE.amber};"
            f"border:1px solid {PALETTE.status_approx_border};",
            "APPROX",
        ),
        "Prototype": (
            f"background:{PALETTE.status_prototype_bg};color:{PALETTE.status_prototype_text};"
            f"border:1px solid {PALETTE.status_prototype_border};",
            "PROTOTYPE",
        ),
        "Placeholder": (
            f"background:{PALETTE.status_placeholder_bg};color:{PALETTE.accent};"
            f"border:1px solid {PALETTE.status_placeholder_border};",
            "PLACEHOLDER",
        ),
        "Broken": (
            f"background:{PALETTE.status_broken_bg};color:{PALETTE.red};"
            f"border:1px solid {PALETTE.status_broken_border};",
            "BROKEN",
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


# Compatibility: app.styles remains the historical stylesheet module for legacy
# calculators. New workstation UI should import tokens from ui.theme.
try:
    from app.styles import APP_STYLE, LIGHT_STYLE
except Exception:  # pragma: no cover - allows docs/static imports without Qt app context
    APP_STYLE = ""
    LIGHT_STYLE = ""


WORKSTATION_STYLE = f"""
* {{
    font-family: "Inter", ".AppleSystemUIFont", "Segoe UI", Arial;
    font-size: 12px;
    color: {PALETTE.txt0};
}}
QWidget {{
    background-color: {PALETTE.bg0};
}}
QMainWindow {{
    background-color: {PALETTE.bg0};
}}
QFrame#workstation_panel,
QFrame#workspace_card,
QFrame#metric_card {{
    background-color: {PALETTE.bg_panel};
    border: 1px solid {PALETTE.border_soft};
    border-radius: 4px;
}}
QFrame#metric_card_highlight {{
    background-color: {PALETTE.accent_soft};
    border: 1px solid {PALETTE.accent_lo};
    border-radius: 4px;
}}
QLabel#metric_name {{
    color: {PALETTE.txt2};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.4px;
}}
QLabel#metric_value {{
    color: {PALETTE.txt0};
    font-size: 17px;
    font-weight: 700;
}}
QLabel#metric_sub {{
    color: {PALETTE.txt2};
    font-size: 10px;
}}
QPushButton {{
    background-color: {PALETTE.bg_panel_elevated};
    border: 1px solid {PALETTE.border_soft};
    border-radius: 4px;
    color: {PALETTE.txt1};
    min-height: 24px;
    padding: 2px 9px;
}}
QPushButton:hover {{
    border-color: {PALETTE.border_strong};
    color: {PALETTE.txt0};
}}
QPushButton#primary_action {{
    background-color: {PALETTE.accent_soft};
    border-color: {PALETTE.accent};
    color: {PALETTE.accent};
    font-weight: 700;
}}
QLineEdit, QComboBox {{
    background-color: {PALETTE.bg_panel_elevated};
    border: 1px solid {PALETTE.border_soft};
    border-radius: 4px;
    min-height: 24px;
    padding: 2px 7px;
    color: {PALETTE.txt0};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {PALETTE.accent};
}}
QTableWidget {{
    background-color: {PALETTE.bg_table_row};
    alternate-background-color: {PALETTE.bg_table_row_alt};
    border: 1px solid {PALETTE.border_soft};
    gridline-color: {PALETTE.bg_table_row_alt};
    selection-background-color: {PALETTE.bg_selected};
    selection-color: {PALETTE.txt0};
    font-size: 11px;
}}
QHeaderView::section {{
    background-color: {PALETTE.bg_table_header};
    color: {PALETTE.txt2};
    border: none;
    border-right: 1px solid {PALETTE.border_soft};
    border-bottom: 1px solid {PALETTE.border_soft};
    padding: 3px 6px;
    font-size: 10px;
    font-weight: 700;
}}
QTabWidget::pane {{
    border: none;
}}
QTabBar::tab {{
    background: {PALETTE.bg_workspace};
    color: {PALETTE.txt2};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 4px 9px;
    margin-right: 4px;
    min-height: 18px;
}}
QTabBar::tab:selected {{
    background: {PALETTE.bg_panel};
    color: {PALETTE.accent};
    border-bottom: 2px solid {PALETTE.accent};
}}
"""
