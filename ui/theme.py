"""Theme ownership for RiskCalc workstation UI.

Two palettes share one set of token names so screens never branch on theme:
``DARK`` keeps the historical values, ``LIGHT`` is the new macOS-2026 design
language (source of truth: design/pricing_v6_light.svg). ``PALETTE`` is the
active palette — currently ``LIGHT``. Token *names* are stable across themes;
only their values differ, which keeps the diff across ui/ and app/panels small.
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ThemePalette:
    # Defaults below are the DARK palette (DARK = ThemePalette()).
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
    # --- new design tokens (v6) ; defaults = dark ---
    bg_window: str = "#1B1B1D"          # window surface under the cards
    bg_card: str = "#212123"            # card surface (sidebar / valuation / params)
    bg_field: str = "#1D2229"           # input field surface
    bg_footer: str = "#1C1C1E"          # fixed footer surface
    card_border: str = "rgba(255,255,255,0.06)"
    txt_table: str = "#C9C9CE"          # tabular data
    txt_nav: str = "#C9C9CE"            # sidebar item label
    accent_pressed: str = "#C4502E"
    accent_on: str = "#FFFFFF"          # text/icon on accent fill
    positive: str = "#3FB984"
    positive_soft: str = "rgba(63,185,132,0.14)"
    warn_text: str = "#E0B341"
    warn_dot: str = "#E0B341"
    warn_soft: str = "rgba(224,179,65,0.14)"
    scroll_track: str = "rgba(255,255,255,0.04)"
    scroll_thumb: str = "rgba(255,255,255,0.18)"
    shadow_color: str = "#000000"
    shadow_alpha: int = 100             # 0..255 for QGraphicsDropShadowEffect


DARK = ThemePalette()

LIGHT = replace(
    DARK,
    bg0="#E1E6EF",
    bg1="#EBEEF4",
    bg1_alt="#E5E9F1",
    bg2="#F3F5F9",
    bg2_alt="#F5F7FA",
    bg3="#E2E6EE",
    bg4="#CAD2DE",
    bg5="#AEB8C6",
    bg_topbar="#FBFBFD",
    bg_workspace="#EBEEF4",
    bg_panel="#FFFFFF",
    bg_panel_elevated="#F3F5F9",
    bg_table_header="#F5F7FA",
    bg_table_row="#FFFFFF",
    bg_table_row_alt="#F7F9FC",
    bg_selected="#FBEEE8",
    bg_warning="#FBF3DE",
    bg_error="#FCE9E7",
    bg_success="#E4F4EC",
    border_strong="rgba(42,47,58,0.18)",
    border_default="rgba(42,47,58,0.12)",
    border_soft="rgba(42,47,58,0.08)",
    divider="rgba(42,47,58,0.08)",
    txt0="#1C2026",
    txt1="#4A5260",
    txt2="#8A91A0",
    text_disabled="#B0B6C0",
    accent="#D9633F",
    accent_hi="#E0805C",
    accent_lo="#C4502E",
    accent_soft="rgba(217,99,63,0.12)",
    green="#0E8A5A",
    red="#D23B30",
    red_text="#C4332A",
    amber="#9A7300",
    blue="#3E7BD6",
    cyan="#1796A6",
    purple="#7A5CC0",
    status_valid_bg="rgba(18,160,106,0.14)",
    status_valid_border="rgba(14,138,90,0.45)",
    status_approx_bg="rgba(224,168,0,0.16)",
    status_approx_border="rgba(181,134,11,0.45)",
    status_prototype_bg="rgba(122,92,192,0.14)",
    status_prototype_text="#6A4FB0",
    status_prototype_border="rgba(122,92,192,0.40)",
    status_placeholder_bg="rgba(42,47,58,0.06)",
    status_placeholder_border="rgba(42,47,58,0.30)",
    status_broken_bg="rgba(210,59,48,0.14)",
    status_broken_border="rgba(210,59,48,0.45)",
    # new design tokens
    bg_window="#FBFBFD",
    bg_card="#FFFFFF",
    bg_field="#F3F5F9",
    bg_footer="#F5F7FA",
    card_border="rgba(42,47,58,0.08)",
    txt_table="#3A414C",
    txt_nav="#4A5260",
    accent_pressed="#C4502E",
    accent_on="#FFFFFF",
    positive="#0E8A5A",
    positive_soft="rgba(18,160,106,0.14)",
    warn_text="#9A7300",
    warn_dot="#B5860B",
    warn_soft="rgba(224,168,0,0.16)",
    scroll_track="rgba(42,47,58,0.06)",
    scroll_thumb="rgba(42,47,58,0.22)",
    shadow_color="#5A6378",
    shadow_alpha=46,
)

# Active palette. v1 of the design migration ships light as the single theme;
# a runtime theme switch (ThemeManager + themeChanged) is a separate future task.
PALETTE = LIGHT


def color(name: str) -> str:
    """Return a named theme color from the active palette."""
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
            f"background:{PALETTE.status_approx_bg};color:{PALETTE.warn_text};"
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
    font-family: "SF Pro Text", "Inter", ".AppleSystemUIFont", "Segoe UI", Arial;
    font-size: 12px;
    color: {PALETTE.txt0};
}}
QWidget {{
    background-color: {PALETTE.bg_workspace};
}}
QMainWindow {{
    background-color: {PALETTE.bg_workspace};
}}
QFrame#workstation_panel,
QFrame#workspace_card,
QFrame#metric_card {{
    background-color: {PALETTE.bg_card};
    border: 1px solid {PALETTE.card_border};
    border-radius: 14px;
}}
QFrame#metric_card_highlight {{
    background-color: {PALETTE.accent_soft};
    border: 1px solid {PALETTE.accent_lo};
    border-radius: 14px;
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
    background-color: {PALETTE.bg_field};
    border: 1px solid {PALETTE.card_border};
    border-radius: 9px;
    color: {PALETTE.txt1};
    min-height: 26px;
    padding: 2px 11px;
}}
QPushButton:hover {{
    border-color: {PALETTE.border_strong};
    color: {PALETTE.txt0};
}}
QPushButton#primary_action {{
    background-color: {PALETTE.accent};
    border: 1px solid {PALETTE.accent};
    color: {PALETTE.accent_on};
    font-weight: 700;
}}
QPushButton#primary_action:hover {{
    background-color: {PALETTE.accent_hi};
    border-color: {PALETTE.accent_hi};
}}
QPushButton#primary_action:pressed {{
    background-color: {PALETTE.accent_pressed};
    border-color: {PALETTE.accent_pressed};
}}
QLineEdit, QComboBox {{
    background-color: {PALETTE.bg_field};
    border: 1px solid {PALETTE.card_border};
    border-radius: 9px;
    min-height: 26px;
    padding: 2px 9px;
    color: {PALETTE.txt0};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {PALETTE.accent};
}}
QLineEdit:hover, QComboBox:hover {{
    border-color: {PALETTE.border_strong};
}}
QLineEdit[invalid="true"], QComboBox[invalid="true"] {{
    border-color: {PALETTE.red};
}}
QTableWidget {{
    background-color: {PALETTE.bg_card};
    alternate-background-color: {PALETTE.bg_table_row_alt};
    border: none;
    gridline-color: {PALETTE.divider};
    selection-background-color: {PALETTE.bg_selected};
    selection-color: {PALETTE.txt0};
    font-size: 11px;
}}
QHeaderView::section {{
    background-color: {PALETTE.bg_table_header};
    color: {PALETTE.txt2};
    border: none;
    border-bottom: 1px solid {PALETTE.divider};
    padding: 3px 6px;
    font-size: 10px;
    font-weight: 700;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {PALETTE.scroll_thumb};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
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
    background: {PALETTE.bg_card};
    color: {PALETTE.accent};
    border-bottom: 2px solid {PALETTE.accent};
}}
"""
