"""Lookback options panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
import numpy as np
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget

class LookbackPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Lookback Options","Fixed strike · Floating strike  —  Goldman-Sosin-Gatto closed-form + MC"))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.spot=make_spin(0.01,1e9,100,1,2); self.strike=make_spin(0.01,1e9,100,1,2)
        self.expiry=make_spin(0.001,50,0.5,0.01,3,"yr"); self.rate=make_pct(0.05)
        self.sigma=make_pct(0.20,0.01,5); self.div=make_pct(0.00)
        self.opt=make_combo(["Call","Put"]); self.style=make_combo(["Floating strike","Fixed strike"])
        self.s_ext=make_spin(0,1e9,0,1,2); self.method=make_combo(["Closed-form","Monte Carlo"])
        f.add_group("Market Parameters",[
            FieldRow("Spot (S)",self.spot),FieldRow("Strike (K)",self.strike,"Used for fixed-strike only"),
            FieldRow("Expiry (T)",self.expiry),FieldRow("Risk-free rate",self.rate),
            FieldRow("Volatility (σ)",self.sigma),FieldRow("Dividend (q)",self.div),
        ])
        f.add_group("Lookback Settings",[
            FieldRow("Option type",self.opt),FieldRow("Style",self.style),
            FieldRow("Running S_ext",self.s_ext,"0 = start fresh (S_ext=S)"),
            FieldRow("Method",self.method),
        ])
        ll.addWidget(f,1)
        bb=QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn=QPushButton("Calculate"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr=QPushButton("Clear"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn,1); bb.addWidget(self.clr); ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate); self.clr.clicked.connect(self.clear)
        right=QWidget(); right.setObjectName("results_panel")
        rl=QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr=QWidget(); hdr.setObjectName("results_header"); hl=QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10); lb=QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)
        self.grid=ResultsGrid(["Price","Vanilla BSM","Premium over Vanilla","Std Error","S extreme","Style"],cols=3,highlight="Price")
        rl.addWidget(self.grid); self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        S=self.spot.value(); K=self.strike.value(); T=self.expiry.value()
        r=self.rate.value()/100; sig=self.sigma.value()/100; q=self.div.value()/100
        opt=self.opt.currentText().lower(); stl=self.style.currentText()
        s_ext=self.s_ext.value() if self.s_ext.value()>0 else None
        try:
            if self.method.currentText()=="Monte Carlo":
                from instruments.lookback import lookback_mc
                res=lookback_mc(S,K,T,r,sig,q,opt,"floating" if "Float" in stl else "fixed",n_sims=50000)
                self.grid.set("Std Error",res["stderr"])
            elif "Float" in stl:
                from instruments.lookback import floating_lookback
                res=floating_lookback(S,T,r,sig,q,opt,S_min=s_ext if opt=="call" else None,S_max=s_ext if opt=="put" else None)
            else:
                from instruments.lookback import fixed_lookback
                res=fixed_lookback(S,K,T,r,sig,q,opt)
            price=res["price"]
            self.grid.set("Price",price,color="#d97757")
            from models.black_scholes import bsm as _b
            van=_b(S,K,T,r,sig,q,opt).price
            self.grid.set("Vanilla BSM",van)
            self.grid.set("Premium over Vanilla",price-van)
            self.grid.set("S extreme",res.get("S_extreme",0)); self.grid.set("Style",stl[:12])
            spots=np.linspace(S*0.6,S*1.4,200)
            if "Float" in stl and opt=="call":
                payoffs=[max(s-(S*0.85),0) for s in spots]
            elif "Float" in stl:
                payoffs=[max(S*1.15-s,0) for s in spots]
            else:
                payoffs=[max(s-K,0) if opt=="call" else max(K-s,0) for s in spots]
            self.chart.plot_payoff(spots,payoffs,f"Lookback {stl[:8]}",S)
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
