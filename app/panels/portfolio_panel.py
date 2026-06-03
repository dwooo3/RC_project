"""Portfolio manager panel."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QDialog,
    QFormLayout, QDialogButtonBox, QComboBox, QDoubleSpinBox, QLineEdit
)
from PySide6.QtCore import Qt
from app.widgets import ParamForm, FieldRow, ResultsGrid, SectionHeader, Banner, make_spin, make_pct, make_combo
from app.chart import ChartWidget
from risk.portfolio import Portfolio, Position


class AddPositionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Position")
        self.setMinimumWidth(400)
        form = QFormLayout(self)

        self.id_edit   = QLineEdit("pos_1")
        self.desc_edit = QLineEdit("ATM Call S=100")
        self.inst      = QComboBox(); self.inst.addItems(["call","put","bond","irs","cds","equity","fx_forward","future"])
        self.qty       = QDoubleSpinBox(); self.qty.setRange(-1e9,1e9); self.qty.setValue(1); self.qty.setDecimals(4)
        self.S_spin    = QDoubleSpinBox(); self.S_spin.setRange(0,1e9); self.S_spin.setValue(100); self.S_spin.setDecimals(4)
        self.K_spin    = QDoubleSpinBox(); self.K_spin.setRange(0,1e9); self.K_spin.setValue(100); self.K_spin.setDecimals(4)
        self.T_spin    = QDoubleSpinBox(); self.T_spin.setRange(0.001,50); self.T_spin.setValue(0.5); self.T_spin.setDecimals(4)
        self.r_spin    = QDoubleSpinBox(); self.r_spin.setRange(-1,5); self.r_spin.setValue(0.05); self.r_spin.setDecimals(4)
        self.sig_spin  = QDoubleSpinBox(); self.sig_spin.setRange(0.001,10); self.sig_spin.setValue(0.20); self.sig_spin.setDecimals(4)
        self.ccy       = QComboBox(); self.ccy.addItems(["RUB","USD","EUR","CNY"])
        self.book_edit = QLineEdit("Trading")

        form.addRow("ID:",         self.id_edit)
        form.addRow("Description:",self.desc_edit)
        form.addRow("Instrument:", self.inst)
        form.addRow("Quantity:",   self.qty)
        form.addRow("Spot S:",     self.S_spin)
        form.addRow("Strike K:",   self.K_spin)
        form.addRow("Expiry T:",   self.T_spin)
        form.addRow("Rate r:",     self.r_spin)
        form.addRow("Vol σ:",      self.sig_spin)
        form.addRow("Currency:",   self.ccy)
        form.addRow("Book:",       self.book_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def get_position(self) -> Position:
        inst = self.inst.currentText()
        params = dict(S=self.S_spin.value(), K=self.K_spin.value(),
                      T=self.T_spin.value(), r=self.r_spin.value(),
                      sigma=self.sig_spin.value(), opt=inst,
                      face=self.S_spin.value()*100, coupon=0.05, freq=2,
                      notional=self.S_spin.value()*1000, spread=0.01, recovery=0.4,
                      fixed_rate=self.r_spin.value()+0.005, pay_fixed=True)
        return Position(
            id=self.id_edit.text() or f"pos_{id(self)}",
            instrument=inst, description=self.desc_edit.text(),
            quantity=self.qty.value(), params=params,
            currency=self.ccy.currentText(), book=self.book_edit.text(),
        )


class PortfolioPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._portfolio = Portfolio("Main Portfolio")
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp = QSplitter(Qt.Horizontal); sp.setHandleWidth(1)
        sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        # Left: controls
        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(330); left.setMaximumWidth(420)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Portfolio Manager", "Positions · Aggregated Risk · Scenario P&L"))
        self.banner = Banner(); ll.addWidget(self.banner)

        # Scenario inputs
        f = ParamForm()
        self.dS    = make_spin(-1e6, 1e6, 1.0, 0.5, 2)
        self.dVol  = make_pct(0.01, -5, 5)
        self.dr    = make_pct(0.001, -1, 1)
        self.dSp   = make_pct(0.001, -1, 1)
        f.add_group("Scenario P&L Inputs", [
            FieldRow("ΔS (spot move)",   self.dS),
            FieldRow("Δσ (vol move)",    self.dVol),
            FieldRow("Δr (rate move)",   self.dr),
            FieldRow("ΔSpread",          self.dSp),
        ])
        ll.addWidget(f, 1)

        btn_bar = QWidget(); btn_bar.setStyleSheet("background:#1c1c1e;border-top:1px solid #2c2c2e;")
        br = QHBoxLayout(btn_bar); br.setContentsMargins(12,10,12,12); br.setSpacing(8)
        self.btn_add    = QPushButton("+ Add Position");  self.btn_add.setObjectName("calc_btn");  self.btn_add.setFixedHeight(36)
        self.btn_price  = QPushButton("Price All");       self.btn_price.setObjectName("clear_btn"); self.btn_price.setFixedHeight(36)
        self.btn_remove = QPushButton("Remove");          self.btn_remove.setObjectName("clear_btn"); self.btn_remove.setFixedHeight(36)
        br.addWidget(self.btn_add, 1); br.addWidget(self.btn_price); br.addWidget(self.btn_remove)
        ll.addWidget(btn_bar)
        self.btn_add.clicked.connect(self._add_position)
        self.btn_price.clicked.connect(self._price_all)
        self.btn_remove.clicked.connect(self._remove_selected)

        # Right: results
        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10); lb = QLabel("PORTFOLIO RISK"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)

        # Aggregated Greeks
        self.grid = ResultsGrid(["Market Value","Delta","Gamma","Vega","Theta","DV01",
                                  "CS01","Rho","Scenario P&L","Positions"],
                                 cols=3, highlight="Market Value")
        rl.addWidget(self.grid)

        # Positions table
        self.pos_tbl = QTableWidget(0, 10)
        self.pos_tbl.setHorizontalHeaderLabels([
            "ID","Instrument","Qty","Price","MV","Delta","Gamma","Vega","DV01","Ccy"])
        self.pos_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pos_tbl.setMaximumHeight(260); self.pos_tbl.setAlternatingRowColors(True)
        self.pos_tbl.setSelectionBehavior(QTableWidget.SelectRows)
        rl.addWidget(self.pos_tbl)

        self.chart = ChartWidget(); self.chart.clear(); rl.addWidget(self.chart, 1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([380,920])
        root.addWidget(sp)

    def _add_position(self):
        dlg = AddPositionDialog(self)
        if dlg.exec():
            pos = dlg.get_position()
            self._portfolio.add(pos)
            self._price_all()

    def _remove_selected(self):
        rows = self.pos_tbl.selectedItems()
        if rows:
            row = self.pos_tbl.currentRow()
            pid = self.pos_tbl.item(row, 0)
            if pid:
                self._portfolio.remove(pid.text())
                self._price_all()

    def _price_all(self):
        self.banner.clear()
        try:
            self._portfolio.price_all()
            agg = self._portfolio.aggregate()

            self.grid.set("Market Value", agg["market_value"], color="#d97757")
            self.grid.set("Delta",    agg["delta"])
            self.grid.set("Gamma",    agg["gamma"])
            self.grid.set("Vega",     agg["vega"])
            self.grid.set("Theta",    agg["theta"])
            self.grid.set("DV01",     agg["dv01"])
            self.grid.set("CS01",     agg["cs01"])
            self.grid.set("Rho",      agg["rho"])
            self.grid.set("Positions",agg["n_positions"])

            # Scenario P&L
            sc = self._portfolio.scenario_pnl(
                dS=self.dS.value(), dVol=self.dVol.value()/100,
                dr=self.dr.value()/100, dSpread=self.dSp.value()/100)
            self.grid.set("Scenario P&L", sc["pnl"],
                          color="#30d158" if sc["pnl"]>=0 else "#ff3b30")

            # Positions table
            rows = self._portfolio.positions_table()
            self.pos_tbl.setRowCount(len(rows))
            for i, r in enumerate(rows):
                for j, val in enumerate([r["id"], r["instrument"], r["quantity"],
                                          r["price"], r["market_value"], r["delta"],
                                          r["gamma"], r["vega"], r["dv01"], r["currency"]]):
                    it = QTableWidgetItem(str(val) if not isinstance(val,float) else f"{val:.4f}")
                    it.setTextAlignment(Qt.AlignRight|Qt.AlignVCenter)
                    self.pos_tbl.setItem(i, j, it)

            # Greek composition chart
            labels = ["Delta","Gamma\n×100","Vega","Theta\n×10","DV01\n×100"]
            vals   = [agg["delta"], agg["gamma"]*100, agg["vega"],
                      agg["theta"]*10, agg["dv01"]*100]
            self.chart.plot_stress(labels, vals)
            self.chart._finish(self.chart.ax, "Portfolio Greeks Composition")

        except Exception as e:
            self.banner.show_error(str(e))
