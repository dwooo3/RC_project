"""Variance & Vol swap panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
import numpy as np
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget

class VarSwapPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Variance & Vol Products","Variance Swap · Vol Swap · Gamma Swap · Corridor Var Swap"))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.spot=make_spin(0.01,1e9,100,1,2); self.sigma=make_pct(0.20,0.01,5)
        self.T=make_spin(0.01,10,1,0.25,2,"yr"); self.r=make_pct(0.05); self.q=make_pct(0)
        self.notional=make_spin(1e3,1e12,1e6,1e5,0)
        self.realized=make_pct(0.22,0.01,5)
        self.L=make_spin(0.01,1e9,80,1,2); self.U=make_spin(0.01,1e9,120,1,2)
        self.prod=make_combo(["Variance Swap","Vol Swap (MC)","Gamma Swap","Corridor Var Swap","Conditional Var Swap"])
        f.add_group("Parameters",[
            FieldRow("Spot (S)",self.spot),FieldRow("Implied vol (σ)",self.sigma),
            FieldRow("Maturity (T)",self.T),FieldRow("Rate (r)",self.r),FieldRow("Div (q)",self.q),
            FieldRow("Notional",self.notional),FieldRow("Realized vol",self.realized,"For P&L calc"),
            FieldRow("Lower L",self.L,"Corridor lower"),FieldRow("Upper U",self.U,"Corridor upper"),
            FieldRow("Product",self.prod),
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
        self.grid=ResultsGrid(["Var Strike","Vol Strike","P&L (long)","Std RV","Corridor","Fraction in"],cols=3,highlight="Var Strike")
        rl.addWidget(self.grid); self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        S=self.spot.value(); sig=self.sigma.value()/100; T=self.T.value()
        r=self.r.value()/100; q=self.q.value()/100; N=self.notional.value()
        rv=self.realized.value()/100; prod=self.prod.currentText()
        try:
            if "Variance" in prod:
                var_k=sig**2
                from instruments.variance_swaps import variance_swap_pnl
                pnl=variance_swap_pnl(rv**2,var_k,N)
                self.grid.set("Var Strike",var_k,color="#d97757")
                self.grid.set("Vol Strike",sig,sub=f"{sig*100:.2f}%")
                self.grid.set("P&L (long)",pnl["pnl"])
            elif "Vol Swap" in prod:
                from instruments.variance_swaps import vol_swap_mc
                res=vol_swap_mc(S,r,q,sig,T,n_sims=30000)
                self.grid.set("Vol Strike",res["vol_strike"],color="#d97757",sub=f"{res['vol_strike']*100:.2f}%")
                self.grid.set("Std RV",res["std_realized_vol"])
                pnl=(rv-res["vol_strike"])*N/2/sig
                self.grid.set("P&L (long)",pnl)
            elif "Gamma" in prod:
                from instruments.variance_swaps import gamma_swap_fair_strike
                res=gamma_swap_fair_strike(S,r,q,sig,T)
                self.grid.set("Var Strike",res["gamma_strike"],color="#d97757")
                self.grid.set("Vol Strike",res["vol_equiv"],sub=f"{res['vol_equiv']*100:.2f}%")
            elif "Corridor" in prod:
                from instruments.variance_swaps import corridor_variance_swap
                res=corridor_variance_swap(S,r,q,sig,T,self.L.value(),self.U.value(),n_sims=30000)
                self.grid.set("Corridor",res["corridor_var_strike"],color="#d97757")
                self.grid.set("Vol Strike",res["corridor_vol"],sub=f"{res['corridor_vol']*100:.2f}%")
                self.grid.set("Fraction in",res["pct_time_in"],sub=f"{res['pct_time_in']*100:.1f}%")
            elif "Conditional" in prod:
                from instruments.variance_swaps import conditional_variance_swap
                res=conditional_variance_swap(S,r,q,sig,T,self.L.value(),self.U.value(),n_sims=30000)
                self.grid.set("Corridor",res["conditional_var_strike"],color="#d97757")
                self.grid.set("Vol Strike",res["conditional_vol"],sub=f"{res['conditional_vol']*100:.2f}%")
            # payoff vs realized vol
            rvs=np.linspace(0.01,0.60,100)
            k=sig**2; payoffs=[(v**2-k)*N/1000 for v in rvs]
            self.chart.plot_payoff(rvs*100,payoffs,"Var Swap P&L vs Realized Vol",rv*100)
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
