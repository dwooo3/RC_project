"""Multi-asset options panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
import numpy as np
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget

class MultiAssetPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Multi-Asset Options","Exchange · Spread · Basket · Rainbow · Quanto · Himalaya"))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.S1=make_spin(0.01,1e9,100,1,2); self.S2=make_spin(0.01,1e9,80,1,2)
        self.K=make_spin(0,1e9,15,1,2)
        self.T=make_spin(0.001,50,0.5,0.01,3,"yr"); self.r=make_pct(0.05)
        self.sig1=make_pct(0.20,0.01,5); self.sig2=make_pct(0.25,0.01,5)
        self.rho=make_pct(-0.30,-1,1); self.q1=make_pct(0); self.q2=make_pct(0)
        self.opt=make_combo(["Call","Put"])
        self.prod=make_combo(["Exchange (Margrabe)","Spread (Kirk)","Spread (MC)","Basket (MC)","Best-of-2 (Stulz)","Quanto"])
        self.rho_sfx=make_pct(-0.30,-1,1); self.sig_fx=make_pct(0.10,0.001,5)
        f.add_group("Asset 1",[FieldRow("Spot S1",self.S1),FieldRow("Vol σ1",self.sig1),FieldRow("Div q1",self.q1)])
        f.add_group("Asset 2",[FieldRow("Spot S2",self.S2),FieldRow("Vol σ2",self.sig2),FieldRow("Div q2",self.q2)])
        f.add_group("Common",[
            FieldRow("Strike K",self.K),FieldRow("Expiry T",self.T),FieldRow("Rate r",self.r),
            FieldRow("Correlation ρ",self.rho),FieldRow("Option type",self.opt),FieldRow("Product",self.prod),
        ])
        f.add_group("Quanto (if applicable)",[FieldRow("FX vol",self.sig_fx),FieldRow("ρ(S,FX)",self.rho_sfx)])
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
        self.grid=ResultsGrid(["Price","Delta S1","Delta S2","Sigma eff","Std Error","Product"],cols=3,highlight="Price")
        rl.addWidget(self.grid); self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        S1=self.S1.value(); S2=self.S2.value(); K=self.K.value()
        T=self.T.value(); r=self.r.value()/100
        s1=self.sig1.value()/100; s2=self.sig2.value()/100
        rho=self.rho.value()/100; q1=self.q1.value()/100; q2=self.q2.value()/100
        opt=self.opt.currentText().lower(); prod=self.prod.currentText()
        try:
            if "Exchange" in prod:
                from instruments.multi_asset import exchange_option
                res=exchange_option(S1,S2,T,r,s1,s2,rho,q1,q2)
                self.grid.set("Price",res["price"],color="#d97757")
                self.grid.set("Delta S1",res["delta1"]); self.grid.set("Delta S2",res["delta2"])
                self.grid.set("Sigma eff",res["sigma_eff"])
            elif "Spread (Kirk)" in prod:
                from instruments.multi_asset import spread_option_kirk
                res=spread_option_kirk(S1,S2,K,T,r,s1,s2,rho,q1,q2)
                self.grid.set("Price",res["price"],color="#d97757"); self.grid.set("Sigma eff",res["sigma_eff"])
            elif "Spread (MC)" in prod:
                from instruments.multi_asset import spread_option_mc
                res=spread_option_mc(S1,S2,K,T,r,s1,s2,rho,q1,q2,n_sims=50000)
                self.grid.set("Price",res["price"],color="#d97757"); self.grid.set("Std Error",res["stderr"])
            elif "Basket" in prod:
                from instruments.multi_asset import basket_option
                corr=np.array([[1,rho],[rho,1]])
                res=basket_option([S1,S2],[0.5,0.5],K,T,r,[s1,s2],corr,[q1,q2],opt)
                self.grid.set("Price",res["price"],color="#d97757"); self.grid.set("Std Error",res.get("stderr",0))
            elif "Best-of" in prod:
                from instruments.multi_asset import best_of_assets_cash
                corr=np.array([[1,rho],[rho,1]])
                res=best_of_assets_cash([S1,S2],K,T,r,[s1,s2],corr,[q1,q2])
                self.grid.set("Price",res["price"],color="#d97757")
            elif "Quanto" in prod:
                from instruments.multi_asset import quanto_option
                res=quanto_option(S1,K,T,r,q1,s1,self.sig_fx.value()/100,self.rho_sfx.value()/100,q2,opt)
                self.grid.set("Price",res["price"],color="#d97757"); self.grid.set("Delta S1",res["delta"])
            self.grid.set("Product",prod[:16])
            self.chart.clear()
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
