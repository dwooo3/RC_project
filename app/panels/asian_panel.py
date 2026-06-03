"""Asian options panel."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
import numpy as np
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm, FieldRow, ResultsGrid, SectionHeader, Banner, make_spin, make_pct, make_combo
from app.chart import ChartWidget

class AsianPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp = QSplitter(Qt.Horizontal); sp.setHandleWidth(1)
        sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Asian Options", "Geometric (exact)  ·  Arithmetic (MC + control variate)"))
        self.banner = Banner(); ll.addWidget(self.banner)
        f = ParamForm()
        self.spot    = make_spin(0.01,1e9,100,1,2)
        self.strike  = make_spin(0.01,1e9,100,1,2)
        self.expiry  = make_spin(0.001,50,0.5,0.01,3,"yr")
        self.rate    = make_pct(0.05)
        self.sigma   = make_pct(0.20,0.01,5)
        self.div     = make_pct(0.00)
        self.opt     = make_combo(["Call","Put"])
        self.style   = make_combo(["Arithmetic (MC)","Geometric (exact, continuous)","Geometric (exact, discrete)"])
        self.avg     = make_combo(["Fixed strike","Floating strike"])
        self.fixings = make_spin(1,365,12,1,0)
        self.sims    = make_spin(1000,500000,50000,5000,0)
        f.add_group("Market Parameters",[
            FieldRow("Spot (S)",self.spot), FieldRow("Strike (K)",self.strike),
            FieldRow("Expiry (T)",self.expiry), FieldRow("Risk-free rate",self.rate),
            FieldRow("Volatility (σ)",self.sigma), FieldRow("Dividend (q)",self.div),
        ])
        f.add_group("Asian Settings",[
            FieldRow("Option type",self.opt), FieldRow("Averaging",self.style),
            FieldRow("Strike type",self.avg), FieldRow("Fixings (n)",self.fixings),
            FieldRow("MC simulations",self.sims),
        ])
        ll.addWidget(f,1)
        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Calculate"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr = QPushButton("Clear"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn,1); bb.addWidget(self.clr); ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate); self.clr.clicked.connect(self.clear)

        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr=QWidget(); hdr.setObjectName("results_header"); hl=QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10); lbl=QLabel("RESULTS"); lbl.setObjectName("results_title_lbl")
        hl.addWidget(lbl); rl.addWidget(hdr)
        self.grid = ResultsGrid(["Price","Std Error","Vanilla BSM","Geometric","Discount","Fixings"],cols=3,highlight="Price")
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900])
        root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        S=self.spot.value(); K=self.strike.value(); T=self.expiry.value()
        r=self.rate.value()/100; sig=self.sigma.value()/100; q=self.div.value()/100
        opt=self.opt.currentText().lower()[0:3]; n=int(self.fixings.value())
        avg="fixed" if "Fixed" in self.avg.currentText() else "floating"
        try:
            stl = self.style.currentText()
            if "Arithmetic" in stl:
                from instruments.asian import arithmetic_asian
                res=arithmetic_asian(S,K,T,r,sig,q,n,opt,n_sims=int(self.sims.value()),averaging=avg)
                self.grid.set("Price",res["price"],color="#d97757"); self.grid.set("Std Error",res["stderr"])
            elif "continuous" in stl:
                from instruments.asian import geometric_asian_continuous
                res=geometric_asian_continuous(S,K,T,r,sig,q,opt)
                self.grid.set("Price",res["price"],color="#d97757"); self.grid.set("Geometric",res["price"])
            else:
                from instruments.asian import geometric_asian_discrete
                res=geometric_asian_discrete(S,K,T,r,sig,q,n,opt)
                self.grid.set("Price",res["price"],color="#d97757"); self.grid.set("Geometric",res["price"])
            from models.black_scholes import bsm as _b
            self.grid.set("Vanilla BSM",_b(S,K,T,r,sig,q,opt).price)
            self.grid.set("Fixings",n); self.grid.set("Discount",round(pow(2.718281828,-r*T),6))
            spots=np.linspace(S*0.6,S*1.4,200)
            payoffs=[max(s-K,0) if opt=="cal" else max(K-s,0) for s in spots]
            self.chart.plot_payoff(spots,payoffs,"Asian payoff (avg≈S_T)",S,[K])
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
