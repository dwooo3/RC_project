"""Qt stylesheet — dark macOS / Claude-style."""

# ── Palette ───────────────────────────────────────────────────────────────
# bg0   = #0f0f11  window root (near-black)
# bg1   = #1a1a1e  sidebar / main surface
# bg2   = #242428  cards, elevated surfaces
# bg3   = #2e2e33  inputs, raised widgets
# bg4   = #38383d  borders, dividers
# txt0  = #f0f0f2  primary text
# txt1  = #a0a0a8  secondary text
# txt2  = #606068  muted / headers
# accent= #d97757  Claude orange (primary accent)
# green = #30d158
# red   = #ff453a
# ─────────────────────────────────────────────────────────────────────────

APP_STYLE = """
/* ── Global ──────────────────────────────────────────────── */
* {
    font-family: ".AppleSystemUIFont", "Helvetica Neue", Arial;
    font-size: 13px;
    color: #f0f0f2;
}

QWidget     { background-color: #0f0f11; }
QMainWindow { background-color: #0f0f11; }

/* ── Sidebar ──────────────────────────────────────────────── */
#sidebar {
    background-color: #1a1a1e;
    border-right: 1px solid #2e2e33;
    min-width: 220px;
    max-width: 220px;
}

/* ── Center panel (left — inputs) ─────────────────────────── */
#center_panel {
    background-color: #1a1a1e;
    border-right: 1px solid #2e2e33;
}

#panel_title {
    font-size: 20px;
    font-weight: 700;
    color: #f0f0f2;
    letter-spacing: -0.4px;
}

#panel_subtitle {
    font-size: 11px;
    color: #606068;
    font-weight: 400;
    letter-spacing: 0.1px;
}

/* ── Results panel (right) ────────────────────────────────── */
#results_panel {
    background-color: #141416;
    border-left: 1px solid #2e2e33;
}

#results_header {
    background-color: #1a1a1e;
    border-bottom: 1px solid #2e2e33;
}

#results_title_lbl {
    font-size: 10px;
    font-weight: 700;
    color: #606068;
    letter-spacing: 1.2px;
}

/* ── Form controls ────────────────────────────────────────── */
QLabel#field_label {
    color: #a0a0a8;
    font-size: 12px;
    font-weight: 500;
}

QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {
    background-color: #242428;
    border: 1px solid #2e2e33;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 13px;
    color: #f0f0f2;
    min-height: 28px;
    selection-background-color: #d97757;
    selection-color: #ffffff;
}

QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QLineEdit:focus {
    border: 1.5px solid #d97757;
    background-color: #2a2a2e;
    outline: none;
}

QDoubleSpinBox:hover:!focus, QSpinBox:hover:!focus,
QComboBox:hover:!focus, QLineEdit:hover:!focus {
    border-color: #4a4a52;
    background-color: #28282c;
}

QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button,       QSpinBox::down-button {
    width: 18px; border: none; background: transparent;
}
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover,
QSpinBox::up-button:hover,       QSpinBox::down-button:hover {
    background: #38383d; border-radius: 3px;
}
QDoubleSpinBox::up-arrow   { image: none; width: 0; }
QDoubleSpinBox::down-arrow { image: none; width: 0; }
QSpinBox::up-arrow         { image: none; width: 0; }
QSpinBox::down-arrow       { image: none; width: 0; }

QComboBox { padding-right: 28px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; width: 0; }

QComboBox QAbstractItemView {
    background-color: #242428;
    border: 1px solid #38383d;
    border-radius: 8px;
    selection-background-color: #d97757;
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}
QComboBox QAbstractItemView::item {
    padding: 6px 12px;
    border-radius: 5px;
    min-height: 24px;
    color: #f0f0f2;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #38383d;
}

/* ── Buttons ──────────────────────────────────────────────── */
QPushButton#calc_btn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #e08464, stop:1 #d06a44);
    color: #ffffff;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    padding: 9px 0px;
    letter-spacing: 0.1px;
}
QPushButton#calc_btn:hover   {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #e88e6e, stop:1 #d8744e);
}
QPushButton#calc_btn:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #c86040, stop:1 #c06038);
}

QPushButton#clear_btn {
    background-color: #242428;
    color: #a0a0a8;
    border: 1px solid #2e2e33;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    padding: 9px 0px;
}
QPushButton#clear_btn:hover   { background-color: #2e2e33; color: #f0f0f2; }
QPushButton#clear_btn:pressed { background-color: #38383d; }

/* Secondary button (secondary action, e.g. Stress Test) */
QPushButton#sec_btn {
    background-color: #242428;
    color: #d97757;
    border: 1px solid #d97757;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    padding: 9px 0px;
}
QPushButton#sec_btn:hover   { background-color: #2e2020; }
QPushButton#sec_btn:pressed { background-color: #3a2020; }

/* ── Metric cards ─────────────────────────────────────────── */
QFrame#metric_card {
    background-color: #1e1e22;
    border: 1px solid #2e2e33;
    border-radius: 8px;
}
QFrame#metric_card_highlight {
    background-color: #241f1a;
    border: 1.5px solid #d97757;
    border-radius: 8px;
}

QLabel#metric_name {
    font-size: 9px;
    font-weight: 700;
    color: #606068;
    letter-spacing: 1px;
}
QLabel#metric_value {
    font-size: 18px;
    font-weight: 700;
    color: #f0f0f2;
    letter-spacing: -0.5px;
}
QLabel#metric_sub {
    font-size: 10px;
    color: #606068;
    font-weight: 400;
}

/* ── Group Box ────────────────────────────────────────────── */
QGroupBox {
    font-size: 10px;
    font-weight: 700;
    color: #606068;
    letter-spacing: 0.8px;
    border: 1px solid #2e2e33;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 10px;
    background: #1a1a1e;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    background: #1a1a1e;
    text-transform: uppercase;
}

/* ── Tab bar ──────────────────────────────────────────────── */
QTabWidget::pane   { border: none; background: transparent; }
QTabWidget::tab-bar { alignment: left; }
QTabBar { background: transparent; padding: 6px 8px 0 8px; }
QTabBar::tab {
    background: #242428;
    border-radius: 6px;
    padding: 5px 14px;
    margin: 0 2px 2px 2px;
    font-size: 12px;
    font-weight: 500;
    color: #a0a0a8;
    min-width: 60px;
}
QTabBar::tab:selected      { background: #d97757; color: #ffffff; font-weight: 600; }
QTabBar::tab:hover:!selected { background: #2e2e33; color: #f0f0f2; }

/* ── Table ────────────────────────────────────────────────── */
QTableWidget {
    background-color: #1a1a1e;
    border: 1px solid #2e2e33;
    border-radius: 6px;
    gridline-color: #242428;
    font-size: 12px;
    alternate-background-color: #1e1e22;
    outline: none;
    color: #f0f0f2;
}
QTableWidget::item { padding: 5px 10px; color: #f0f0f2; }
QTableWidget::item:selected {
    background-color: #3a2a20;
    color: #d97757;
}
QHeaderView::section {
    background-color: #242428;
    border: none;
    border-bottom: 1px solid #2e2e33;
    border-right: 1px solid #2e2e33;
    padding: 6px 10px;
    font-size: 10px;
    font-weight: 700;
    color: #606068;
    letter-spacing: 0.6px;
}

/* ── Scroll bars ──────────────────────────────────────────── */
QScrollBar:vertical {
    background: transparent; width: 5px; margin: 2px 0;
}
QScrollBar::handle:vertical {
    background: #38383d; border-radius: 2.5px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #4a4a52; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 0; }
QScrollArea { border: none; background: transparent; }

/* ── Status bar ───────────────────────────────────────────── */
QStatusBar {
    background: #1a1a1e;
    color: #606068;
    font-size: 11px;
    border-top: 1px solid #2e2e33;
    padding: 2px 10px;
}
QStatusBar::item { border: none; }

/* ── Banners ──────────────────────────────────────────────── */
QLabel#banner_error {
    background: #2a1a18;
    border: 1px solid #6a2820;
    border-radius: 6px;
    color: #ff6b5a;
    padding: 8px 14px;
    font-size: 12px;
}
QLabel#banner_ok {
    background: #182a1c;
    border: 1px solid #246030;
    border-radius: 6px;
    color: #30d158;
    padding: 8px 14px;
    font-size: 12px;
}

/* ── Tooltip ──────────────────────────────────────────────── */
QToolTip {
    background-color: #2e2e33;
    color: #f0f0f2;
    border: 1px solid #38383d;
    border-radius: 5px;
    padding: 4px 8px;
    font-size: 11px;
}

/* ── Separators ───────────────────────────────────────────── */
QFrame[frameShape="4"] { color: #2e2e33; max-height: 1px; }
QFrame[frameShape="5"] { color: #2e2e33; max-width:  1px; }

/* ── Splitter ─────────────────────────────────────────────── */
QSplitter::handle { background: #2e2e33; }
"""

# ── Light theme ───────────────────────────────────────────────────────────────
LIGHT_STYLE = """
* {
    font-family: ".AppleSystemUIFont", "Helvetica Neue", Arial;
    font-size: 13px;
    color: #111111;
}

QWidget     { background-color: #fafafa; }
QMainWindow { background-color: #fafafa; }

#sidebar {
    background-color: #ffffff;
    border-right: 1px solid #e5e5e5;
    min-width: 200px;
    max-width: 200px;
}

#center_panel {
    background-color: #ffffff;
    border-right: 1px solid #e5e5e5;
}

#panel_title   { font-size: 20px; font-weight: 700; color: #111111; }
#panel_subtitle { font-size: 11px; color: #8a8a8a; }

#results_panel  { background-color: #f5f5f5; border-left: 1px solid #e5e5e5; }
#results_header { background-color: #ffffff;  border-bottom: 1px solid #e5e5e5; }
#results_title_lbl { font-size: 10px; font-weight: 700; color: #8a8a8a; letter-spacing: 1.2px; }

QLabel#field_label { color: #555555; font-size: 12px; font-weight: 500; }

QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {
    background-color: #ffffff;
    border: 1px solid #d4d4d4;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 13px;
    color: #111111;
    min-height: 28px;
}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QLineEdit:focus {
    border: 1.5px solid #d97757;
}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button { width: 18px; border: none; background: transparent; }
QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow,
QSpinBox::up-arrow, QSpinBox::down-arrow { image: none; width: 0; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; width: 0; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #d4d4d4;
    border-radius: 8px;
    selection-background-color: #d97757;
    selection-color: #ffffff;
    outline: none;
}

QPushButton#calc_btn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e08464, stop:1 #d06a44);
    color: #ffffff; border: none; border-radius: 8px;
    font-size: 13px; font-weight: 600; padding: 9px 0px;
}
QPushButton#calc_btn:hover  { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #e88e6e,stop:1 #d8744e); }
QPushButton#calc_btn:pressed { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #c86040,stop:1 #c06038); }

QPushButton#clear_btn {
    background-color: #f0f0f0; color: #555555;
    border: 1px solid #d4d4d4; border-radius: 8px; font-size: 13px; padding: 9px 0px;
}
QPushButton#clear_btn:hover { background-color: #e5e5e5; color: #111111; }

QPushButton#sec_btn {
    background-color: #fff5f0; color: #d97757;
    border: 1px solid #d97757; border-radius: 8px; font-size: 13px; font-weight: 600; padding: 9px 0px;
}

QFrame#metric_card {
    background-color: #ffffff; border: 1px solid #e5e5e5; border-radius: 8px;
}
QFrame#metric_card_highlight {
    background-color: #fff5f0; border: 1.5px solid #d97757; border-radius: 8px;
}
QLabel#metric_name  { font-size: 9px; font-weight: 700; color: #8a8a8a; letter-spacing: 1px; }
QLabel#metric_value { font-size: 18px; font-weight: 700; color: #111111; }
QLabel#metric_sub   { font-size: 10px; color: #8a8a8a; }

QGroupBox {
    font-size: 10px; font-weight: 700; color: #8a8a8a; letter-spacing: 0.8px;
    border: 1px solid #e5e5e5; border-radius: 8px; margin-top: 14px; padding-top: 10px;
    background: #ffffff;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; background: #ffffff; }

QTabWidget::pane { border: none; background: transparent; }
QTabBar { background: transparent; padding: 6px 8px 0 8px; }
QTabBar::tab {
    background: #f0f0f0; border-radius: 6px; padding: 5px 14px;
    margin: 0 2px 2px 2px; font-size: 12px; color: #555555;
}
QTabBar::tab:selected { background: #d97757; color: #ffffff; font-weight: 600; }
QTabBar::tab:hover:!selected { background: #e5e5e5; color: #111111; }

QTableWidget {
    background-color: #ffffff; border: 1px solid #e5e5e5; border-radius: 6px;
    gridline-color: #f0f0f0; font-size: 12px; alternate-background-color: #fafafa;
    color: #111111;
}
QTableWidget::item { padding: 5px 10px; color: #111111; }
QTableWidget::item:selected { background-color: #fff5f0; color: #d97757; }
QHeaderView::section {
    background-color: #f5f5f5; border: none; border-bottom: 1px solid #e5e5e5;
    border-right: 1px solid #e5e5e5; padding: 6px 10px; font-size: 10px;
    font-weight: 700; color: #8a8a8a; letter-spacing: 0.6px;
}

QScrollBar:vertical { background: transparent; width: 5px; margin: 2px 0; }
QScrollBar::handle:vertical { background: #d4d4d4; border-radius: 2.5px; min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #aaaaaa; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 0; }
QScrollArea { border: none; background: transparent; }

QStatusBar {
    background: #ffffff; color: #8a8a8a; font-size: 11px;
    border-top: 1px solid #e5e5e5; padding: 2px 10px;
}
QStatusBar::item { border: none; }

QLabel#banner_error {
    background: #fff0ee; border: 1px solid #d93025; border-radius: 6px;
    color: #d93025; padding: 8px 14px; font-size: 12px;
}
QLabel#banner_ok {
    background: #eefff2; border: 1px solid #168a3a; border-radius: 6px;
    color: #168a3a; padding: 8px 14px; font-size: 12px;
}

QToolTip {
    background-color: #ffffff; color: #111111; border: 1px solid #d4d4d4;
    border-radius: 5px; padding: 4px 8px; font-size: 11px;
}

QFrame[frameShape="4"] { color: #e5e5e5; max-height: 1px; }
QFrame[frameShape="5"] { color: #e5e5e5; max-width:  1px; }
QSplitter::handle { background: #e5e5e5; }
"""
