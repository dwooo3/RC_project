"""Cap / Floor / Swaption panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget
import numpy as np

class CapFloorPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Cap / Floor / Swaption","Black-76 pricing  —  Caplets · Floorlets · Collar · Payer/Receiver Swaption"))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.notional=make_spin(1e3,1e12,1e7,1e5,0); self.strike=make_pct(0.05,0,0.5)
        self.T=make_spin(0.1,50,5,0.5,2,"yr"); self.rate=make_pct(0.04)
        self.vol=make_pct(0.20,0.001,5); self.freq=make_combo(["1","2","4","12"],"4")
        self.prod=make_combo(["Cap","Floor","Collar (±2%)","Payer Swaption","Receiver Swaption"])
        self.t_opt=make_spin(0.1,20,1,0.25,2,"yr"); self.t_swap=make_spin(0.5,50,5,0.5,2,"yr")
        f.add_group("Instrument",[FieldRow("Product",self.prod)])
        f.add_group("Parameters",[
            FieldRow("Notional",self.notional),FieldRow("Strike rate",self.strike),
            FieldRow("Maturity",self.T),FieldRow("Discount rate",self.rate),
            FieldRow("Black-76 vol",self.vol),FieldRow("Freq / year",self.freq),
        ])
        f.add_group("Swaption Only",[FieldRow("Option expiry",self.t_opt),FieldRow("Swap tenor",self.t_swap)])
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
        self.grid=ResultsGrid(["Price","Cap","Floor","Fwd Swap Rate","Annuity","DV01","Caplets","Vega","N Periods"],cols=3,highlight="Price")
        rl.addWidget(self.grid); self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            from instruments.fixed_income import cap_floor,collar,swaption,YieldCurve
            curve=YieldCurve.flat(self.rate.value()/100)
            K=self.strike.value()/100; v=self.vol.value()/100; T=self.T.value()
            N=self.notional.value(); freq=int(self.freq.currentText()); prod=self.prod.currentText()
            if prod=="Cap":
                res=cap_floor(N,K,T,freq,curve,v,"cap")
                self.grid.set("Price",res["price"],color="#d97757"); self.grid.set("Cap",res["price"])
                self.grid.set("Caplets",res["n_caplets"])
            elif prod=="Floor":
                res=cap_floor(N,K,T,freq,curve,v,"floor")
                self.grid.set("Price",res["price"],color="#d97757"); self.grid.set("Floor",res["price"])
            elif "Collar" in prod:
                res=collar(N,K*1.02,K*0.98,T,freq,curve,v)
                self.grid.set("Price",res["price"],color="#d97757")
                self.grid.set("Cap",res["cap"]); self.grid.set("Floor",res["floor"])
            elif "Payer" in prod or "Receiver" in prod:
                opt_type="payer" if "Payer" in prod else "receiver"
                res=swaption(N,K,self.t_opt.value(),self.t_swap.value(),freq,curve,v,opt_type)
                self.grid.set("Price",res["price"],color="#d97757")
                self.grid.set("Fwd Swap Rate",res["fwd_swap_rate"],sub=f"{res['fwd_swap_rate']*100:.3f}%")
                self.grid.set("Annuity",res["annuity"]); self.grid.set("Vega",res["vega"])
            # price vs strike chart
            strikes=np.linspace(K*0.5,K*1.5,40)
            prices=[]
            for k2 in strikes:
                if "Cap" in prod or "Floor" in prod or "Collar" in prod:
                    r2=cap_floor(N,k2,T,freq,curve,v,"cap" if "Cap" in prod else "floor")
                    prices.append(r2["price"])
                else:
                    r2=swaption(N,k2,self.t_opt.value(),self.t_swap.value(),freq,curve,v,"payer")
                    prices.append(r2["price"])
            self.chart.plot_payoff(strikes*100,prices,prod,K*100)
            self.chart._finish(self.chart.ax,"Price vs Strike","Strike (%)","Price")
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
