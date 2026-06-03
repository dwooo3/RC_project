"""IRS / OIS / Basis Swap panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget
import numpy as np

class IRSPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Interest Rate Swaps","IRS · OIS · Basis Swap  —  NPV · Fair Rate · DV01"))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.notional=make_spin(1e3,1e12,1e7,1e5,0)
        self.fixed=make_pct(0.04); self.T=make_spin(0.1,50,5,0.5,2,"yr")
        self.rate=make_pct(0.035); self.freq=make_combo(["1","2","4","12"],"4")
        self.direction=make_combo(["Pay fixed","Receive fixed"])
        self.prod=make_combo(["IRS (Fixed vs Float)","OIS","Basis Swap"])
        self.spread=make_pct(0.005,0,0.1)
        f.add_group("Swap Parameters",[
            FieldRow("Notional",self.notional),FieldRow("Fixed rate",self.fixed),
            FieldRow("Maturity",self.T),FieldRow("Discount rate",self.rate),
            FieldRow("Freq / year",self.freq),FieldRow("Direction",self.direction),
            FieldRow("Product",self.prod),FieldRow("Basis spread",self.spread,"For Basis Swap"),
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
        self.grid=ResultsGrid(["NPV","Fair Rate","Fixed Leg PV","Float Leg PV","DV01","Duration","Annuity","BPV","Break-even"],cols=3,highlight="NPV")
        rl.addWidget(self.grid); self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            from instruments.fixed_income import irs,ois,basis_swap,YieldCurve
            curve=YieldCurve.flat(self.rate.value()/100)
            prod=self.prod.currentText(); pay=self.direction.currentText()=="Pay fixed"
            if "OIS" in prod:
                res=ois(self.notional.value(),self.fixed.value()/100,self.T.value(),curve)
                self.grid.set("NPV",res["npv"],color="#d97757")
                self.grid.set("Fair Rate",res["fair_ois_rate"],sub=f"{res['fair_ois_rate']*100:.3f}%")
                self.grid.set("DV01",res["dv01"])
            elif "Basis" in prod:
                curve2=YieldCurve.flat(self.rate.value()/100+self.spread.value()/100)
                res=basis_swap(self.notional.value(),self.spread.value()/100,self.T.value(),int(self.freq.currentText()),curve,curve2)
                self.grid.set("NPV",res["npv"],color="#d97757")
                self.grid.set("Fair Rate",res["fair_spread"],sub=f"{res['fair_spread']*10000:.1f}bps")
            else:
                res=irs(self.notional.value(),self.fixed.value()/100,self.T.value(),int(self.freq.currentText()),curve,pay)
                self.grid.set("NPV",res["npv"],color="#d97757")
                self.grid.set("Fair Rate",res["fair_rate"],sub=f"{res['fair_rate']*100:.3f}%")
                self.grid.set("Fixed Leg PV",res["fixed_pv"]); self.grid.set("Float Leg PV",res["float_pv"])
                self.grid.set("DV01",res["dv01"]); self.grid.set("Duration",res.get("duration",0))
                self.grid.set("Annuity",res.get("annuity",0)); self.grid.set("BPV",res["dv01"])
                self.grid.set("Break-even",res["fair_rate"],sub="fixed rate")
            # NPV vs rate chart
            rates=np.linspace(max(0.001,self.rate.value()/100-0.04),self.rate.value()/100+0.04,60)
            npvs=[]
            for r2 in rates:
                c2=YieldCurve.flat(r2)
                r2_res=irs(self.notional.value(),self.fixed.value()/100,self.T.value(),int(self.freq.currentText()),c2,pay)
                npvs.append(r2_res["npv"])
            self.chart.plot_payoff(rates*100,npvs,"IRS NPV",self.rate.value(),[self.fixed.value()])
            self.chart._finish(self.chart.ax,"NPV vs Discount Rate","Rate (%)","NPV")
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
