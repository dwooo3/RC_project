"""Credit instruments panel: CDS, CVA, CDO."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
import numpy as np
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget

class CreditPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Credit Instruments","CDS · Binary CDS · CVA/DVA · CDO Tranche"))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.notional=make_spin(1e3,1e12,1e7,1e5,0); self.spread=make_pct(0.01,0,0.5)
        self.T=make_spin(0.1,50,5,0.5,2,"yr"); self.rate=make_pct(0.02)
        self.recovery=make_pct(0.40,0,1); self.freq=make_combo(["1","2","4","12"],"4")
        self.prod=make_combo(["CDS (buy protection)","CDS (sell protection)","Binary CDS","CVA","CDO Tranche"])
        self.K1=make_pct(0.03,0,1); self.K2=make_pct(0.07,0,1)
        self.n_names=make_spin(1,1000,100,10,0); self.rho_cdо=make_pct(0.30,0,1)
        f.add_group("Credit Parameters",[
            FieldRow("Notional",self.notional),FieldRow("CDS spread",self.spread),
            FieldRow("Maturity",self.T),FieldRow("Risk-free rate",self.rate),
            FieldRow("Recovery (R)",self.recovery),FieldRow("Freq / year",self.freq),
            FieldRow("Product",self.prod),
        ])
        f.add_group("CDO / CVA",[
            FieldRow("Attach. K1",self.K1),FieldRow("Detach. K2",self.K2),
            FieldRow("Pool names",self.n_names),FieldRow("Correlation ρ",self.rho_cdо),
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
        self.grid=ResultsGrid(["NPV / Price","Fair Spread","Hazard Rate","Default Prob","Risky DV01","Survival 1Y","Survival 5Y","Protection PV","Premium PV"],cols=3,highlight="NPV / Price")
        rl.addWidget(self.grid); self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        try:
            from instruments.credit import cds,cds_implied_hazard,default_digital,survival_prob
            prod=self.prod.currentText(); N=self.notional.value()
            sp=self.spread.value()/100; T=self.T.value(); r=self.rate.value()/100
            rec=self.recovery.value()/100; freq=int(self.freq.currentText())
            hazard=cds_implied_hazard(sp,T,freq,r,rec)
            if "Binary" in prod:
                from instruments.credit import default_digital
                res=default_digital(N,T,hazard,r)
                self.grid.set("NPV / Price",res["price"],color="#d97757")
                self.grid.set("Default Prob",res["pd"],sub=f"{res['pd']*100:.2f}%")
            elif "CVA" in prod:
                tenors=[0.5,1,2,3,5]; epe=[N*0.05*t for t in tenors]
                profile=list(zip(tenors,epe))
                from instruments.credit import cva
                res_cva=cva(profile,hazard,rec,r)
                self.grid.set("NPV / Price",res_cva["cva"],color="#ff3b30",sub="CVA")
            elif "CDO" in prod:
                from instruments.credit import cdo_lhp
                p_def=1-np.exp(-hazard*T)
                res=cdo_lhp(N,self.K1.value()/100,self.K2.value()/100,T,int(self.n_names.value()),p_def,self.rho_cdо.value()/100,r,rec)
                self.grid.set("NPV / Price",res["price"],color="#d97757")
                self.grid.set("Default Prob",res["expected_tranche_loss"])
            else:
                buy=(prod=="CDS (buy protection)")
                res=cds(N,sp,T,freq,hazard,r,rec,buy)
                self.grid.set("NPV / Price",res["npv"],color="#d97757")
                self.grid.set("Fair Spread",res["fair_spread"],sub=f"{res['fair_spread']*10000:.1f}bps")
                self.grid.set("Hazard Rate",hazard,sub=f"{hazard*100:.3f}%")
                self.grid.set("Default Prob",1-np.exp(-hazard*T),sub=f"{(1-np.exp(-hazard*T))*100:.2f}%")
                self.grid.set("Risky DV01",res["dv01"])
                self.grid.set("Protection PV",res["protection_pv"]); self.grid.set("Premium PV",res["premium_pv"])
            self.grid.set("Survival 1Y",np.exp(-hazard*1),sub=f"{np.exp(-hazard)*100:.2f}%")
            self.grid.set("Survival 5Y",np.exp(-hazard*5),sub=f"{np.exp(-hazard*5)*100:.2f}%")
            tenors_plt=np.linspace(0,T,100)
            surv=[np.exp(-hazard*t) for t in tenors_plt]
            self.chart.plot_survival_curve(tenors_plt,surv)
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
