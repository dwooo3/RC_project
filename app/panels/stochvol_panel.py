"""Heston & SABR stochastic vol panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
import numpy as np
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter,QTabWidget
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget

class StochVolPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Stochastic Volatility","Heston (semi-analytical)  ·  SABR  ·  Implied Vol"))
        self.banner=Banner(); ll.addWidget(self.banner)
        tabs=QTabWidget()
        # Heston
        hw=QWidget(); hf=ParamForm()
        self.h_S=make_spin(0.01,1e9,100,1,2); self.h_K=make_spin(0.01,1e9,100,1,2)
        self.h_T=make_spin(0.001,50,0.5,0.01,3,"yr"); self.h_r=make_pct(0.05); self.h_q=make_pct(0)
        self.h_v0=make_spin(0.0001,2,0.04,0.001,4); self.h_kappa=make_spin(0.01,20,2.0,0.1,2)
        self.h_theta=make_spin(0.0001,2,0.04,0.001,4); self.h_xi=make_spin(0.001,5,0.3,0.01,3)
        self.h_rho=make_pct(-0.70,-1,1); self.h_opt=make_combo(["Call","Put"])
        hf.add_group("Market",[FieldRow("Spot",self.h_S),FieldRow("Strike",self.h_K),FieldRow("Expiry",self.h_T),FieldRow("Rate",self.h_r),FieldRow("Div",self.h_q)])
        hf.add_group("Heston Params",[FieldRow("v0 (init var)",self.h_v0),FieldRow("κ (mean-rev)",self.h_kappa),FieldRow("θ (long var)",self.h_theta),FieldRow("ξ (vol-of-vol)",self.h_xi),FieldRow("ρ (corr)",self.h_rho),FieldRow("Type",self.h_opt)])
        hvl=QVBoxLayout(hw); hvl.setContentsMargins(0,0,0,0); hvl.addWidget(hf); tabs.addTab(hw,"Heston")
        # SABR
        sw=QWidget(); sf=ParamForm()
        self.s_F=make_spin(0.01,1e9,100,1,2); self.s_K=make_spin(0.01,1e9,100,1,2)
        self.s_T=make_spin(0.001,50,0.5,0.01,3,"yr"); self.s_r=make_pct(0.05)
        self.s_alpha=make_spin(0.001,5,0.15,0.01,4); self.s_beta=make_spin(0,1,0.5,0.05,2)
        self.s_nu=make_spin(0.001,5,0.4,0.01,3); self.s_rho=make_pct(-0.30,-1,1)
        self.s_opt=make_combo(["Call","Put"])
        sf.add_group("Market",[FieldRow("Forward F",self.s_F),FieldRow("Strike K",self.s_K),FieldRow("Expiry T",self.s_T),FieldRow("Rate r",self.s_r)])
        sf.add_group("SABR Params",[FieldRow("α (level)",self.s_alpha),FieldRow("β (CEV exp)",self.s_beta),FieldRow("ν (vol-of-vol)",self.s_nu),FieldRow("ρ (correlation)",self.s_rho),FieldRow("Type",self.s_opt)])
        svl=QVBoxLayout(sw); svl.setContentsMargins(0,0,0,0); svl.addWidget(sf); tabs.addTab(sw,"SABR")
        # Implied Vol
        iw=QWidget(); ivf=ParamForm()
        self.i_mkt=make_spin(0.0001,1e6,5.0,0.01,4); self.i_S=make_spin(0.01,1e9,100,1,2)
        self.i_K=make_spin(0.01,1e9,100,1,2); self.i_T=make_spin(0.001,50,0.5,0.01,3,"yr")
        self.i_r=make_pct(0.05); self.i_q=make_pct(0); self.i_opt=make_combo(["Call","Put"])
        self.i_model=make_combo(["BSM","Black-76","Garman-Kohlhagen"])
        ivf.add_group("Market Price",[FieldRow("Market price",self.i_mkt),FieldRow("Spot S",self.i_S),FieldRow("Strike K",self.i_K),FieldRow("Expiry T",self.i_T),FieldRow("Rate r",self.i_r),FieldRow("Div/r_f q",self.i_q),FieldRow("Type",self.i_opt),FieldRow("Model",self.i_model)])
        ivl=QVBoxLayout(iw); ivl.setContentsMargins(0,0,0,0); ivl.addWidget(ivf); tabs.addTab(iw,"Implied Vol")
        ll.addWidget(tabs,1)
        bb=QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn=QPushButton("Calculate"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr=QPushButton("Clear"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn,1); bb.addWidget(self.clr); ll.addLayout(bb)
        self.btn.clicked.connect(lambda: self._calc(tabs.currentIndex())); self.clr.clicked.connect(self.clear)
        right=QWidget(); right.setObjectName("results_panel")
        rl=QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr=QWidget(); hdr.setObjectName("results_header"); hl=QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10); lb=QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)
        self.grid=ResultsGrid(["Price","Implied Vol","Delta","BSM Price","Feller OK","Model"],cols=3,highlight="Price")
        rl.addWidget(self.grid); self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)
        self._tabs=tabs

    def _calc(self,tab):
        self.banner.clear()
        try:
            if tab==0:
                from models.heston import heston_price
                res=heston_price(self.h_S.value(),self.h_K.value(),self.h_T.value(),self.h_r.value()/100,self.h_q.value()/100,self.h_v0.value(),self.h_kappa.value(),self.h_theta.value(),self.h_xi.value(),self.h_rho.value()/100,self.h_opt.currentText().lower())
                self.grid.set("Price",res["price"],color="#d97757")
                iv=res.get("implied_vol",float("nan"))
                if iv==iv: self.grid.set("Implied Vol",iv,sub=f"{iv*100:.2f}%")
                self.grid.set("Delta",res.get("delta",0))
                feller=2*self.h_kappa.value()*self.h_theta.value()>self.h_xi.value()**2
                self.grid.set("Feller OK","Yes" if feller else "NO",color="#30d158" if feller else "#ff3b30")
                self.grid.set("Model","Heston")
                from models.black_scholes import bsm as _b
                self.grid.set("BSM Price",_b(self.h_S.value(),self.h_K.value(),self.h_T.value(),self.h_r.value()/100,self.h_v0.value()**0.5,self.h_q.value()/100,self.h_opt.currentText().lower()).price)
                # smile
                strikes=np.linspace(self.h_S.value()*0.7,self.h_S.value()*1.3,15)
                vols=[]
                from models.implied_vol import implied_vol_bsm
                for k in strikes:
                    pr=heston_price(self.h_S.value(),k,self.h_T.value(),self.h_r.value()/100,self.h_q.value()/100,self.h_v0.value(),self.h_kappa.value(),self.h_theta.value(),self.h_xi.value(),self.h_rho.value()/100,self.h_opt.currentText().lower())["price"]
                    iv2=implied_vol_bsm(pr,self.h_S.value(),k,self.h_T.value(),self.h_r.value()/100,self.h_q.value()/100,self.h_opt.currentText().lower())
                    vols.append(iv2 if iv2==iv2 else 0.20)
                self.chart.plot_vol_smile(strikes,vols,self.h_S.value())
            elif tab==1:
                from models.heston import sabr_price
                res=sabr_price(self.s_F.value(),self.s_K.value(),self.s_T.value(),self.s_r.value()/100,self.s_alpha.value(),self.s_beta.value(),self.s_rho.value()/100,self.s_nu.value(),self.s_opt.currentText().lower())
                self.grid.set("Price",res["price"],color="#d97757")
                self.grid.set("Implied Vol",res["implied_vol"],sub=f"{res['implied_vol']*100:.2f}%")
                self.grid.set("Delta",res["delta"]); self.grid.set("Model","SABR")
                # smile
                strikes=np.linspace(self.s_F.value()*0.7,self.s_F.value()*1.3,20)
                from models.heston import sabr_vol
                vols=[sabr_vol(self.s_F.value(),k,self.s_T.value(),self.s_alpha.value(),self.s_beta.value(),self.s_rho.value()/100,self.s_nu.value()) for k in strikes]
                self.chart.plot_vol_smile(strikes,vols,self.s_F.value())
            else:
                m=self.i_model.currentText(); opt=self.i_opt.currentText().lower()
                mkt=self.i_mkt.value(); S=self.i_S.value(); K=self.i_K.value()
                T=self.i_T.value(); r=self.i_r.value()/100; q=self.i_q.value()/100
                if m=="BSM":
                    from models.implied_vol import implied_vol_bsm
                    iv=implied_vol_bsm(mkt,S,K,T,r,q,opt)
                elif m=="Black-76":
                    from models.implied_vol import implied_vol_black76
                    iv=implied_vol_black76(mkt,S,K,T,r,opt)
                else:
                    from models.implied_vol import implied_vol_gk
                    iv=implied_vol_gk(mkt,S,K,T,r,q,opt)
                self.grid.set("Implied Vol",iv,sub=f"{iv*100:.2f}%" if iv==iv else "N/A",color="#d97757")
                self.grid.set("Model",m)
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
