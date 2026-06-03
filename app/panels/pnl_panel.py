"""P&L Attribution panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget
import numpy as np

class PnLPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("P&L Attribution","Delta · Gamma · Vega · Theta · Rho · Vanna · Volga explain"))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.spot=make_spin(0.01,1e9,100,1,2); self.strike=make_spin(0.01,1e9,100,1,2)
        self.T=make_spin(0.001,50,0.5,0.01,3,"yr"); self.rate=make_pct(0.05)
        self.sigma=make_pct(0.20,0.01,5); self.div=make_pct(0); self.opt=make_combo(["Call","Put"])
        self.dS=make_spin(-1e6,1e6,2,0.1,2); self.dVol=make_pct(0.02,-5,5)
        self.dt=make_spin(0,365,1,0.5,1,"days"); self.dr=make_pct(0.001,-1,1)
        f.add_group("Option (t=0)",[
            FieldRow("Spot S",self.spot),FieldRow("Strike K",self.strike),
            FieldRow("Expiry T",self.T),FieldRow("Rate r",self.rate),
            FieldRow("Vol σ",self.sigma),FieldRow("Dividend",self.div),FieldRow("Type",self.opt),
        ])
        f.add_group("Market Moves",[
            FieldRow("ΔS (spot move)",self.dS,"Absolute move"),
            FieldRow("Δσ (vol move)",self.dVol,"Absolute move"),
            FieldRow("Δt (days)",self.dt,"Time elapsed"),
            FieldRow("Δr (rate move)",self.dr,"Absolute move"),
        ])
        ll.addWidget(f,1)
        bb=QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn=QPushButton("Explain P&L"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr=QPushButton("Clear"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn,1); bb.addWidget(self.clr); ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate); self.clr.clicked.connect(self.clear)
        right=QWidget(); right.setObjectName("results_panel")
        rl=QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr=QWidget(); hdr.setObjectName("results_header"); hl=QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10); lb=QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)
        self.grid=ResultsGrid(["Delta P&L","Gamma P&L","Vega P&L","Theta P&L","Rho P&L","Vanna P&L","Volga P&L","Total (2nd)","Actual P&L","Unexplained"],cols=3,highlight="Total (2nd)")
        rl.addWidget(self.grid); self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            from models.black_scholes import bsm as _b
            from risk.stress import pnl_explain
            S=self.spot.value(); K=self.strike.value(); T=self.T.value()
            r=self.rate.value()/100; sig=self.sigma.value()/100; q=self.div.value()/100
            opt=self.opt.currentText().lower()
            dS=self.dS.value(); dv=self.dVol.value()/100; dt=self.dt.value(); dr=self.dr.value()/100
            g=_b(S,K,T,r,sig,q,opt)
            res=pnl_explain(g,dS,dv,dt,dr)
            # actual P&L
            S2=S+dS; sig2=max(sig+dv,0.001); T2=max(T-dt/365,1e-5); r2=r+dr
            g2=_b(S2,K,T2,r2,sig2,q,opt)
            actual=g2.price-g.price
            unexplained=actual-res["total_2nd_order"]
            for k,v in res.items():
                nice=k.replace("_"," ").title()
                if nice in self.grid._cards: self.grid.set(nice,v)
            self.grid.set("Delta P&L",res["delta"]); self.grid.set("Gamma P&L",res["gamma"])
            self.grid.set("Vega P&L",res["vega"]); self.grid.set("Theta P&L",res["theta"])
            self.grid.set("Rho P&L",res["rho"]); self.grid.set("Vanna P&L",res["vanna"])
            self.grid.set("Volga P&L",res["volga"]); self.grid.set("Total (2nd)",res["total_2nd_order"])
            self.grid.set("Actual P&L",actual,color="#d97757"); self.grid.set("Unexplained",unexplained)
            # bar chart of attribution
            labels=["Delta","Gamma","Vega","Theta","Rho","Vanna","Volga"]
            vals=[res["delta"],res["gamma"],res["vega"],res["theta"],res["rho"],res["vanna"],res["volga"]]
            self.chart.plot_stress(labels,vals)
            self.chart._finish(self.chart.ax,"P&L Attribution","","P&L")
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
