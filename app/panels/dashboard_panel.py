"""Dashboard — clean starting screen with KPIs, quick nav, compact model status."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QGridLayout, QScrollArea
)
from PySide6.QtCore import Qt

from app.widgets import ModelStatusBadge
from models.registry import summary as registry_summary, MODEL_REGISTRY
from ui.components import KpiCard, QuickNavCard, StatusChip
from ui.theme import PALETTE


def _sep():
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{PALETTE.bg3};max-height:1px;")
    return f


class DashboardPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        body = QWidget()
        body.setStyleSheet(f"background:{PALETTE.bg1_alt};")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(32, 28, 32, 32)
        lay.setSpacing(24)

        # ── Header ────────────────────────────────────────
        hdr = QHBoxLayout()
        col = QVBoxLayout(); col.setSpacing(3)
        title = QLabel("RiskCalc")
        title.setStyleSheet(
            f"color:{PALETTE.txt0};font-size:28px;font-weight:700;"
            f"letter-spacing:-0.6px;background:transparent;")
        sub = QLabel("Market Risk & Pricing Engine")
        sub.setStyleSheet(f"color:{PALETTE.txt2};font-size:12px;background:transparent;")
        col.addWidget(title); col.addWidget(sub)
        hdr.addLayout(col); hdr.addStretch()

        data_chip = StatusChip("Approximation", text="⬤  Data: Demo / Manual")
        hdr.addWidget(data_chip, alignment=Qt.AlignTop)
        lay.addLayout(hdr)
        lay.addWidget(_sep())

        # ── KPI row ───────────────────────────────────────
        kpi_lbl = QLabel("KEY METRICS")
        kpi_lbl.setStyleSheet(
            f"color:{PALETTE.txt2};font-size:10px;font-weight:700;"
            f"letter-spacing:1px;background:transparent;")
        lay.addWidget(kpi_lbl)

        kpi_grid = QGridLayout(); kpi_grid.setSpacing(10)
        kpi_data = [
            ("Portfolio MV",  "—",   "",             PALETTE.txt0,  True),
            ("Daily P&L",     "—",   "",             PALETTE.txt0,  False),
            ("VaR 95% (1d)",  "—",   "Not computed", PALETTE.red,   False),
            ("ES 95% (1d)",   "—",   "Not computed", PALETTE.red,   False),
            ("DV01",          "—",   "",             PALETTE.txt0,  False),
            ("Vega",          "—",   "",             PALETTE.txt0,  False),
        ]
        self._kpi: dict = {}
        for i, (lbl, val, sub, col, hl) in enumerate(kpi_data):
            card = KpiCard(lbl, val, sub, col, hl)
            self._kpi[lbl] = card
            kpi_grid.addWidget(card, i // 3, i % 3)
        lay.addLayout(kpi_grid)
        lay.addWidget(_sep())

        # ── Quick navigation ──────────────────────────────
        nav_lbl = QLabel("QUICK ACCESS")
        nav_lbl.setStyleSheet(
            f"color:{PALETTE.txt2};font-size:10px;font-weight:700;"
            f"letter-spacing:1px;background:transparent;")
        lay.addWidget(nav_lbl)

        nav_grid = QGridLayout(); nav_grid.setSpacing(8)
        nav_items = [
            ("Market",      "market",    "Yield Curves · Vol Surface · FX"),
            ("Pricing",     "pricing",   "Bonds · Options · IRS · Exotics"),
            ("Portfolio",   "portfolio", "Positions · Exposure · Attribution"),
            ("Risk",        "risk",      "VaR · Stress Testing · Greeks"),
            ("Analytics",   "analytics", "Trees · MC · Heston/SABR · GARCH"),
            ("Settings",    "settings",  "Theme · Data sources · About"),
        ]
        for i, (nm, key, hint) in enumerate(nav_items):
            card = QuickNavCard(nm, hint, on_click=lambda k=key: self._navigate(k))
            nav_grid.addWidget(card, i // 3, i % 3)
        lay.addLayout(nav_grid)
        lay.addWidget(_sep())

        # ── Compact model status ──────────────────────────
        ms_hdr = QHBoxLayout()
        ms_title = QLabel("MODEL VALIDATION STATUS")
        ms_title.setStyleSheet(
            f"color:{PALETTE.txt2};font-size:10px;font-weight:700;"
            f"letter-spacing:1px;background:transparent;")
        ms_hdr.addWidget(ms_title)
        ms_hdr.addStretch()

        # Summary counts
        counts = registry_summary()
        summary_parts = []
        for status, count in counts.items():
            if count > 0:
                summary_parts.append(f"{count} {status.value.lower()}")
        summary_str = "  ·  ".join(summary_parts)
        ms_summary = QLabel(summary_str)
        ms_summary.setStyleSheet(f"color:{PALETTE.txt2};font-size:10px;background:transparent;")
        ms_hdr.addWidget(ms_summary)
        lay.addLayout(ms_hdr)

        # Compact status grid — show only non-validated entries as warning
        ms_frame = QFrame()
        ms_frame.setStyleSheet(
            f"QFrame{{background:{PALETTE.bg2_alt};border:1px solid {PALETTE.bg3};border-radius:8px;}}")
        ms_lay = QVBoxLayout(ms_frame)
        ms_lay.setContentsMargins(14, 10, 14, 10)
        ms_lay.setSpacing(0)

        # Group by domain
        domain_entries: dict[str, list] = {}
        for model_id, info in MODEL_REGISTRY.items():
            domain = info["domain"]
            domain_entries.setdefault(domain, []).append((info["name"], info["status"], info["notes"]))

        first_domain = True
        for domain, entries in sorted(domain_entries.items()):
            if not first_domain:
                div = QFrame(); div.setFrameShape(QFrame.HLine)
                div.setStyleSheet(f"color:{PALETTE.bg3};max-height:1px;margin:4px 0;")
                ms_lay.addWidget(div)
            first_domain = False

            dom_lbl = QLabel(domain.upper())
            dom_lbl.setStyleSheet(
                f"color:{PALETTE.txt2};font-size:9px;font-weight:700;"
                f"letter-spacing:0.8px;background:transparent;margin-top:4px;")
            ms_lay.addWidget(dom_lbl)

            for name, status, notes in entries:
                row = QHBoxLayout(); row.setSpacing(8)
                nm = QLabel(name)
                nm.setStyleSheet(
                    f"color:{PALETTE.txt1};font-size:11px;background:transparent;")
                nm.setFixedWidth(220)
                badge = ModelStatusBadge(status)
                nt = QLabel(notes)
                nt.setStyleSheet(
                    f"color:{PALETTE.txt2};font-size:10px;background:transparent;")
                nt.setWordWrap(True)
                row.addWidget(nm)
                row.addWidget(badge)
                row.addWidget(nt, 1)
                ms_lay.addLayout(row)

        lay.addWidget(ms_frame)
        lay.addStretch()

        scroll.setWidget(body)
        outer.addWidget(scroll)

    def _navigate(self, key: str):
        w = self
        while w is not None:
            if hasattr(w, "sidebar") and hasattr(w.sidebar, "select_key"):
                w.sidebar.select_key(key)
                break
            w = w.parent()
