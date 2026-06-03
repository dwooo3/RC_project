"""Digital / Touch options panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
import numpy as np
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget

class DigitalPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Digital & Touch Options","Cash-or-Nothing · Asset-or-Nothing · One-Touch · No-Touch · Double No-Touch · Supershare"))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.spot=make_spin(0.01,1e9,100,1,2); self.strike=make_spin(0.01,1e9,100,1,2)
        self.expiry=make_spin(0.001,50,0.5,0.01,3,"yr"); self.rate=make_pct(0.05)
        self.sigma=make_pct(0.20,0.01,5); self.div=make_pct(0.00)
        self.opt=make_combo(["Call","Put"])
        self.dtype=make_combo(["Cash-or-Nothing","Asset-or-Nothing","One-Touch","No-Touch","Double No-Touch","Supershare"])
        self.cash=make_spin(0,1e9,1,0.1,4); self.barrier=make_spin(0.01,1e9,110,1,2)
        self.lower=make_spin(0.01,1e9,90,1,2); self.upper=make_spin(0.01,1e9,110,1,2)
        self.direction=make_combo(["Up","Down"])
        f.add_group("Market Parameters",[
            FieldRow("Spot (S)",self.spot),FieldRow("Strike (K)",self.strike),
            FieldRow("Expiry (T)",self.expiry),FieldRow("Risk-free rate",self.rate),
            FieldRow("Volatility (σ)",self.sigma),FieldRow("Dividend (q)",self.div),
        ])
        f.add_group("Digital Settings",[
            FieldRow("Option type",self.opt),FieldRow("Digital type",self.dtype),
            FieldRow("Cash amount",self.cash),FieldRow("Barrier",self.barrier),
            FieldRow("Lower barrier",self.lower),FieldRow("Upper barrier",self.upper),
            FieldRow("Direction",self.direction),
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
        self.grid=ResultsGrid(["Price","Delta","Gamma","Vega","Theta","Prob ITM"],cols=3,highlight="Price")
        rl.addWidget(self.grid); self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900])
        root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        S=self.spot.value(); K=self.strike.value(); T=self.expiry.value()
        r=self.rate.value()/100; sig=self.sigma.value()/100; q=self.div.value()/100
        opt=self.opt.currentText().lower(); dt=self.dtype.currentText()
        try:
            if dt=="Cash-or-Nothing":
                from instruments.digital import cash_or_nothing
                res=cash_or_nothing(S,K,T,r,sig,q,opt,self.cash.value())
            elif dt=="Asset-or-Nothing":
                from instruments.digital import asset_or_nothing
                res=asset_or_nothing(S,K,T,r,sig,q,opt)
            elif dt=="One-Touch":
                from instruments.digital import one_touch
                res=one_touch(S,self.barrier.value(),T,r,sig,q,self.direction.currentText().lower(),"expiry",self.cash.value())
            elif dt=="No-Touch":
                from instruments.digital import no_touch
                res=no_touch(S,self.barrier.value(),T,r,sig,q,self.direction.currentText().lower(),self.cash.value())
            elif dt=="Double No-Touch":
                from instruments.digital import double_no_touch
                res=double_no_touch(S,self.lower.value(),self.upper.value(),T,r,sig,q,self.cash.value(),n_sims=50000)
            else:
                from instruments.digital import supershare
                res=supershare(S,self.lower.value(),self.upper.value(),T,r,sig,q)
            price=res.get("price",0)
            self.grid.set("Price",price,color="#d97757")
            self.grid.set("Delta",res.get("delta",0)); self.grid.set("Gamma",res.get("gamma",0))
            self.grid.set("Vega",res.get("vega",0)); self.grid.set("Theta",res.get("theta",0))
            # payoff diagram
            spots=np.linspace(S*0.6,S*1.4,300)
            c=self.cash.value()
            if "Cash" in dt:
                payoffs = [c if (s > K if opt=="call" else s < K) else 0 for s in spots]
                bars = [K]
                self.chart.plot_payoff(spots, payoffs, dt, S, bars)
            elif "Asset" in dt:
                payoffs = [s if (s > K if opt=="call" else s < K) else 0 for s in spots]
                bars = [K]
                self.chart.plot_payoff(spots, payoffs, dt, S, bars)
            elif "Double" in dt:
                payoffs = [c if self.lower.value() < s < self.upper.value() else 0 for s in spots]
                self.chart.plot_payoff(spots, payoffs, dt, S,
                                       [self.lower.value(), self.upper.value()])
            else:
                # Touch/No-Touch: path-dependent — show probability instead
                from scipy.stats import norm as _norm
                H = self.barrier.value()
                direction = self.direction.currentText().lower()
                mu_ann = (r - q - 0.5*sig**2)
                probs = []
                for s in spots:
                    if T <= 0 or sig <= 0:
                        probs.append(0.0)
                        continue
                    d = (np.log(H/s) + mu_ann*T) / (sig*np.sqrt(T))
                    d2 = (np.log(H/s) - mu_ann*T) / (sig*np.sqrt(T))
                    lam = mu_ann / sig**2
                    from scipy.stats import norm as N_
                    if direction == "up":
                        p = (N_.cdf(-d) + (H/s)**(2*lam)*N_.cdf(-d2))
                    else:
                        p = (N_.cdf(d) + (H/s)**(2*lam)*N_.cdf(d2))
                    probs.append(float(np.clip(p, 0, 1)))
                self.chart.plot_payoff(spots, probs, f"{dt} — Hit Probability", S, [H])
                self.chart._finish(self.chart.ax,
                    f"{dt}: Path-Dependent — Terminal Payoff Chart N/A",
                    "Spot at t=0", "Approx. Hit Probability")
                self.banner.show_ok(
                    "Touch/No-Touch are path-dependent. Chart shows approximate "
                    "hit probability (continuous barrier, flat vol).")
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
