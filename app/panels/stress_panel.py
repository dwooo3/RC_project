"""Stress testing panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
import numpy as np
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter,QTableWidget,QTableWidgetItem,QHeaderView
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,ModelStatus,make_spin,make_pct,make_combo
from app.chart import ChartWidget
from services.market_data_service import MarketDataService
from services.risk_service import RiskService

class StressPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.market_data=MarketDataService()
        self.risk_service=RiskService(market_data=self.market_data)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Stress Testing",
            "14 historical scenarios  ·  Reverse stress test  ·  Rate shock (bonds)",
                 status=ModelStatus.APPROXIMATION))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.spot=make_spin(0.01,1e9,100,1,2); self.strike=make_spin(0.01,1e9,100,1,2)
        self.T=make_spin(0.001,50,0.5,0.01,3,"yr"); self.rate=make_pct(0.05)
        self.sigma=make_pct(0.20,0.01,5); self.div=make_pct(0); self.opt=make_combo(["Call","Put"])
        self.position=make_spin(-1e9,1e9,1,1,0); self.target_loss=make_pct(50,1,100)
        f.add_group("Option Parameters",[
            FieldRow("Spot (S)",self.spot),FieldRow("Strike (K)",self.strike),
            FieldRow("Expiry (T)",self.T),FieldRow("Rate (r)",self.rate),
            FieldRow("Vol (σ)",self.sigma),FieldRow("Dividend",self.div),
            FieldRow("Type",self.opt),FieldRow("Position (qty)",self.position),
        ])
        f.add_group("Reverse Stress",[FieldRow("Target loss %",self.target_loss)])
        ll.addWidget(f,1)
        bb=QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn=QPushButton("Run Stress Test"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr=QPushButton("Clear"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn,1); bb.addWidget(self.clr); ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate); self.clr.clicked.connect(self.clear)
        right=QWidget(); right.setObjectName("results_panel")
        rl=QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr=QWidget(); hdr.setObjectName("results_header"); hl=QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10); lb=QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)
        self.grid=ResultsGrid(["Base Price","Worst P&L","Best P&L","Max Loss Scenario","Reverse Spot Δ","Reverse Vol Δ"],cols=3,highlight="Base Price")
        rl.addWidget(self.grid)
        self.table=QTableWidget(0,6)
        self.table.setHorizontalHeaderLabels(["Scenario","Spot Δ","Vol Δ","Base","Stressed","P&L"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMaximumHeight(280); self.table.setAlternatingRowColors(True)
        rl.addWidget(self.table)
        self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            S=self.spot.value(); K=self.strike.value(); T=self.T.value()
            r=self.rate.value()/100; sig=self.sigma.value()/100; q=self.div.value()/100
            opt=self.opt.currentText().lower(); pos=int(self.position.value())
            snapshot=self.market_data.demo_snapshot()
            service_res=self.risk_service.stress_option(S,K,T,r,sig,q,opt,position=pos,snapshot=snapshot)
            if service_res["errors"]:
                raise ValueError("; ".join(service_res["errors"]))
            if service_res["warnings"]:
                self.banner.show_error("Warnings: " + " ".join(service_res["warnings"][:3]))
            results=service_res["raw"] or []
            self.table.setRowCount(len(results))
            scenarios=[]; pnls=[]
            for i,res in enumerate(results):
                self.table.setItem(i,0,QTableWidgetItem(res["scenario"][:26]))
                self.table.setItem(i,1,QTableWidgetItem(res["spot_shock"]))
                self.table.setItem(i,2,QTableWidgetItem(res["vol_shock"]))
                self.table.setItem(i,3,QTableWidgetItem(str(res["base_price"])))
                self.table.setItem(i,4,QTableWidgetItem(str(res["stressed_price"])))
                self.table.setItem(i,5,QTableWidgetItem(str(res["pnl"])))
                scenarios.append(res["scenario"][:22]); pnls.append(res["pnl"])
            base=results[0]["base_price"] if results else 0
            self.grid.set("Base Price",base,color="#d97757")
            self.grid.set("Worst P&L",min(pnls),color="#ff3b30")
            self.grid.set("Best P&L",max(pnls),color="#30d158")
            worst_idx=pnls.index(min(pnls))
            self.grid.set("Max Loss Scenario",results[worst_idx]["scenario"][:14])
            # Reverse stress
            tl=base*(self.target_loss.value()/100)
            rv_res=self.risk_service.reverse_stress_option(S,K,T,r,sig,q,opt,target_loss=tl,snapshot=snapshot)
            if rv_res["errors"]:
                raise ValueError("; ".join(rv_res["errors"]))
            rv=rv_res["raw"] or {}
            self.grid.set("Reverse Spot Δ",rv["spot_shock"],sub=f"{rv['spot_shock']*100:+.1f}%")
            self.grid.set("Reverse Vol Δ",rv["vol_shock"],sub=f"{rv['vol_shock']*100:+.1f}%")
            self.chart.plot_stress(scenarios,pnls)
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear(); self.table.setRowCount(0)
