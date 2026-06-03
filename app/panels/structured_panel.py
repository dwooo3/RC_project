"""Structured notes panel: Phoenix, CLN, FTD, PPN, WBRC."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QSplitter, QTabWidget
)
from PySide6.QtCore import Qt
from app.widgets import ParamForm, FieldRow, ResultsGrid, SectionHeader, Banner, make_spin, make_pct, make_combo
from app.chart import ChartWidget


class StructuredPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp = QSplitter(Qt.Horizontal); sp.setHandleWidth(1)
        sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")

        left = QWidget(); left.setObjectName("center_panel")
        left.setMinimumWidth(350); left.setMaximumWidth(430)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Structured Notes",
                 "Phoenix · PPN · Reverse Convert · CLN · FTD · Worst-of",
                 status=ModelStatus.PROTOTYPE))
        self.banner = Banner(); ll.addWidget(self.banner)

        self.tabs = QTabWidget()

        # ── Phoenix ──────────────────────────────────────
        ph_w = QWidget(); pf = ParamForm()
        self.ph_S=make_spin(0.01,1e9,100,1,2); self.ph_r=make_pct(0.15)
        self.ph_q=make_pct(0); self.ph_sigma=make_pct(0.30,0.01,5)
        self.ph_T=make_spin(0.5,10,3,0.5,1,"yr")
        self.ph_ac=make_pct(1.00,0.5,2.0)    # autocall barrier
        self.ph_cpn=make_pct(0.70,0.1,1.0)   # coupon barrier
        self.ph_ki=make_pct(0.65,0.1,1.0)    # knock-in barrier
        self.ph_rate=make_pct(0.12,0,1.0)    # annual coupon rate
        self.ph_mem=make_combo(["Yes (Memory coupon)","No"])
        self.ph_obs=make_spin(1,24,6,1,0)    # observation dates per year
        pf.add_group("Underlying",[FieldRow("Spot S0",self.ph_S),FieldRow("Rate r",self.ph_r),
                                    FieldRow("Div q",self.ph_q),FieldRow("Vol σ",self.ph_sigma),
                                    FieldRow("Maturity T",self.ph_T)])
        pf.add_group("Phoenix Structure",[
            FieldRow("Autocall barrier",self.ph_ac,"% of S0"),
            FieldRow("Coupon barrier",self.ph_cpn,"% of S0"),
            FieldRow("KI barrier",self.ph_ki,"Capital at risk level"),
            FieldRow("Annual coupon",self.ph_rate),
            FieldRow("Memory coupon",self.ph_mem),
            FieldRow("Obs. per year",self.ph_obs),
        ])
        pvl=QVBoxLayout(ph_w); pvl.setContentsMargins(0,0,0,0); pvl.addWidget(pf)
        self.tabs.addTab(ph_w,"Phoenix / Autocall")

        # ── PPN ──────────────────────────────────────────
        ppn_w = QWidget(); ppnf = ParamForm()
        self.ppn_S=make_spin(0.01,1e9,100,1,2); self.ppn_r=make_pct(0.12)
        self.ppn_sigma=make_pct(0.25,0.01,5); self.ppn_T=make_spin(0.5,10,3,0.5,1,"yr")
        self.ppn_part=make_pct(1.0,0.1,5.0); self.ppn_cap=make_pct(0.50,0.01,5.0)
        self.ppn_floor=make_pct(0.0,-0.5,0.5); self.ppn_face=make_spin(1,1e9,1000,100,0)
        ppnf.add_group("Structure",[
            FieldRow("Spot S0",self.ppn_S),FieldRow("Rate r",self.ppn_r),
            FieldRow("Vol σ",self.ppn_sigma),FieldRow("Maturity T",self.ppn_T),
            FieldRow("Face value",self.ppn_face),FieldRow("Participation",self.ppn_part),
            FieldRow("Return cap",self.ppn_cap),FieldRow("Floor return",self.ppn_floor),
        ])
        pvl2=QVBoxLayout(ppn_w); pvl2.setContentsMargins(0,0,0,0); pvl2.addWidget(ppnf)
        self.tabs.addTab(ppn_w,"PPN / Capital Protect")

        # ── Reverse Convertible ───────────────────────────
        rc_w = QWidget(); rcf = ParamForm()
        self.rc_S=make_spin(0.01,1e9,100,1,2); self.rc_r=make_pct(0.12)
        self.rc_sigma=make_pct(0.30,0.01,5); self.rc_T=make_spin(0.1,5,1,0.25,2,"yr")
        self.rc_ki=make_pct(0.70,0.1,1.0); self.rc_cpn=make_pct(0.15,0,1.0)
        rcf.add_group("Reverse Convertible",[
            FieldRow("Spot S0",self.rc_S),FieldRow("Rate r",self.rc_r),
            FieldRow("Vol σ",self.rc_sigma),FieldRow("Maturity",self.rc_T),
            FieldRow("KI barrier",self.rc_ki,"Continuous monitoring"),
            FieldRow("Annual coupon",self.rc_cpn),
        ])
        rvl=QVBoxLayout(rc_w); rvl.setContentsMargins(0,0,0,0); rvl.addWidget(rcf)
        self.tabs.addTab(rc_w,"Reverse Convertible")

        # ── CLN ──────────────────────────────────────────
        cln_w = QWidget(); clf = ParamForm()
        self.cln_face=make_spin(1,1e9,1000,100,0); self.cln_cpn=make_pct(0.18,0,1)
        self.cln_T=make_spin(0.5,30,5,0.5,1,"yr"); self.cln_r=make_pct(0.12)
        self.cln_freq=make_combo(["4","2","1"]); self.cln_haz=make_pct(0.03,0,1)
        self.cln_rec=make_pct(0.40,0,1); self.cln_ref_haz=make_pct(0.05,0,1)
        clf.add_group("CLN Parameters",[
            FieldRow("Face value",self.cln_face),FieldRow("Coupon rate",self.cln_cpn),
            FieldRow("Maturity",self.cln_T),FieldRow("Risk-free rate",self.cln_r),
            FieldRow("Freq/year",self.cln_freq),
            FieldRow("Issuer hazard",self.cln_haz),FieldRow("Issuer recovery",self.cln_rec),
            FieldRow("Ref. hazard",self.cln_ref_haz,"Reference entity hazard rate"),
        ])
        cvl=QVBoxLayout(cln_w); cvl.setContentsMargins(0,0,0,0); cvl.addWidget(clf)
        self.tabs.addTab(cln_w,"CLN")

        # ── FTD ──────────────────────────────────────────
        ftd_w = QWidget(); ftdf = ParamForm()
        self.ftd_face=make_spin(1,1e9,1000,100,0); self.ftd_cpn=make_pct(0.20,0,1)
        self.ftd_T=make_spin(0.5,10,5,0.5,1,"yr"); self.ftd_r=make_pct(0.12)
        self.ftd_freq=make_combo(["4","2","1"]); self.ftd_rec=make_pct(0.40,0,1)
        self.ftd_rho=make_pct(0.30,0,1)
        self.ftd_h1=make_pct(0.03,0,1); self.ftd_h2=make_pct(0.04,0,1)
        self.ftd_h3=make_pct(0.05,0,1); self.ftd_h4=make_pct(0.06,0,1); self.ftd_h5=make_pct(0.07,0,1)
        ftdf.add_group("FTD Basket",[
            FieldRow("Face value",self.ftd_face),FieldRow("Coupon rate",self.ftd_cpn),
            FieldRow("Maturity",self.ftd_T),FieldRow("Rate",self.ftd_r),
            FieldRow("Recovery",self.ftd_rec),FieldRow("Correlation ρ",self.ftd_rho),
        ])
        ftdf.add_group("Hazard rates (5 names)",[
            FieldRow("Name 1 λ",self.ftd_h1),FieldRow("Name 2 λ",self.ftd_h2),
            FieldRow("Name 3 λ",self.ftd_h3),FieldRow("Name 4 λ",self.ftd_h4),
            FieldRow("Name 5 λ",self.ftd_h5),
        ])
        fvl=QVBoxLayout(ftd_w); fvl.setContentsMargins(0,0,0,0); fvl.addWidget(ftdf)
        self.tabs.addTab(ftd_w,"FTD Basket")

        ll.addWidget(self.tabs, 1)
        bb = QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn = QPushButton("Price Note"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr = QPushButton("Clear");     self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn,1); bb.addWidget(self.clr); ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate); self.clr.clicked.connect(self.clear)

        right = QWidget(); right.setObjectName("results_panel")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr = QWidget(); hdr.setObjectName("results_header"); hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10); lb = QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)
        self.grid = ResultsGrid(["Fair Value (%)","Coupon Yield","Autocall Prob",
                                  "Capital Loss Prob","Fair Spread bps","Default Prob",
                                  "ZCB Cost","Option Budget","Std Error"],
                                 cols=3, highlight="Fair Value (%)")
        rl.addWidget(self.grid)
        self.chart = ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([400,900])
        root.addWidget(sp)

    def calculate(self):
        self.banner.clear(); self.grid.clear_all()
        tab = self.tabs.currentIndex()
        try:
            if tab == 0:   self._calc_phoenix()
            elif tab == 1: self._calc_ppn()
            elif tab == 2: self._calc_rc()
            elif tab == 3: self._calc_cln()
            elif tab == 4: self._calc_ftd()
        except Exception as e:
            self.banner.show_error(str(e))

    def _calc_phoenix(self):
        from instruments.structured.phoenix import phoenix
        S=self.ph_S.value(); r=self.ph_r.value()/100; q=self.ph_q.value()/100
        sig=self.ph_sigma.value()/100; T=self.ph_T.value()
        n_obs=int(self.ph_obs.value())
        obs_dates=[T*i/n_obs for i in range(1,n_obs+1)]
        mem="Yes" in self.ph_mem.currentText()
        res=phoenix(S,r,q,sig,T,obs_dates,
                    self.ph_ac.value()/100, self.ph_cpn.value()/100,
                    self.ph_ki.value()/100, self.ph_rate.value()/100,
                    mem, n_sims=30_000)
        self.grid.set("Fair Value (%)",res["price"]*100,color="#d97757",sub=f"{res['price']*100:.2f}%")
        self.grid.set("Autocall Prob",res["autocall_prob"],sub=f"{res['autocall_prob']*100:.1f}%")
        self.grid.set("Coupon Yield",self.ph_rate.value()/100)
        self.grid.set("Fair Spread bps",res["fair_spread_bps"],sub="to be at par")
        self.grid.set("Std Error",res["stderr"])
        # payoff chart
        spots=np.linspace(S*0.4,S*1.5,100)
        payoffs=[1.0 if s>=self.ph_ac.value()/100*S else
                 (1.0 if s>=self.ph_ki.value()/100*S else s/S)
                 for s in spots]
        self.chart.plot_payoff(spots,payoffs,"Phoenix payoff at maturity",S,
                               [self.ph_ki.value()/100*S, self.ph_cpn.value()/100*S, self.ph_ac.value()/100*S])

    def _calc_ppn(self):
        from instruments.structured.phoenix import ppn
        res=ppn(self.ppn_face.value(),self.ppn_r.value()/100,
                self.ppn_sigma.value()/100,self.ppn_T.value(),
                self.ppn_part.value()/100,self.ppn_cap.value()/100,
                self.ppn_floor.value()/100, self.ppn_S.value(), n_sims=30_000)
        fv_pct=res["price"]/self.ppn_face.value()*100
        self.grid.set("Fair Value (%)",fv_pct,color="#d97757",sub=f"{fv_pct:.2f}%")
        self.grid.set("ZCB Cost",res["zcb_cost"])
        self.grid.set("Option Budget",res["option_budget"])
        self.grid.set("Coupon Yield",res["effective_participation"])
        self.grid.set("Std Error",res["stderr"])
        S=self.ppn_S.value(); S0=S; face=self.ppn_face.value()
        spots=np.linspace(S0*0.5,S0*2.0,100); ep=res["effective_participation"]
        cap=self.ppn_cap.value()/100; floor=self.ppn_floor.value()/100
        payoffs=[face+face*ep*min(max(s/S0-1,floor),cap) for s in spots]
        self.chart.plot_payoff(spots,payoffs,"PPN payoff",S0)

    def _calc_rc(self):
        from instruments.structured.phoenix import reverse_convertible
        res=reverse_convertible(self.rc_S.value(),self.rc_r.value()/100,0.0,
                                self.rc_sigma.value()/100,self.rc_T.value(),
                                self.rc_ki.value()/100, self.rc_cpn.value()/100, n_sims=30_000)
        self.grid.set("Fair Value (%)",res["price"]*100,color="#d97757",sub=f"{res['price']*100:.2f}%")
        self.grid.set("Autocall Prob",res["ki_prob"],sub=f"{res['ki_prob']*100:.1f}% KI hit")
        self.grid.set("Capital Loss Prob",res["capital_loss_prob"],sub=f"{res['capital_loss_prob']*100:.1f}%")
        self.grid.set("Coupon Yield",self.rc_cpn.value()/100)
        S=self.rc_S.value(); ki=self.rc_ki.value()/100*S
        spots=np.linspace(S*0.3,S*1.5,100)
        payoffs=[s/S+self.rc_cpn.value()/100*self.rc_T.value() if s<S else 1+self.rc_cpn.value()/100*self.rc_T.value() for s in spots]
        self.chart.plot_payoff(spots,payoffs,"Reverse Convertible",S,[ki])

    def _calc_cln(self):
        from instruments.structured.cln_ftd import cln
        res=cln(self.cln_face.value(),self.cln_cpn.value()/100,
                self.cln_T.value(),int(self.cln_freq.currentText()),
                self.cln_r.value()/100,self.cln_haz.value()/100,
                self.cln_rec.value()/100,self.cln_ref_haz.value()/100)
        fv_pct=res["price"]/self.cln_face.value()*100
        self.grid.set("Fair Value (%)",fv_pct,color="#d97757",sub=f"{fv_pct:.2f}%")
        self.grid.set("Default Prob",res["default_prob"],sub=f"{res['default_prob']*100:.2f}%")
        if res["fair_spread"] and res["fair_spread"]==res["fair_spread"]:
            self.grid.set("Fair Spread bps",res["fair_spread_bps"],sub="above risk-free")
        self.chart.clear()

    def _calc_ftd(self):
        from instruments.structured.cln_ftd import ftd_basket
        hazards=[self.ftd_h1.value()/100,self.ftd_h2.value()/100,
                 self.ftd_h3.value()/100,self.ftd_h4.value()/100,self.ftd_h5.value()/100]
        res=ftd_basket(self.ftd_face.value(),self.ftd_cpn.value()/100,
                       self.ftd_T.value(),int(self.ftd_freq.currentText()),
                       self.ftd_r.value()/100,hazards,
                       self.ftd_rec.value()/100,self.ftd_rho.value()/100,n_sims=30_000)
        fv_pct=res["price"]/self.ftd_face.value()*100
        self.grid.set("Fair Value (%)",fv_pct,color="#d97757",sub=f"{fv_pct:.2f}%")
        self.grid.set("Default Prob",res["default_prob"],sub=f"{res['default_prob']*100:.1f}% FTD")
        if res["fair_spread"]==res["fair_spread"]:
            self.grid.set("Fair Spread bps",res["fair_spread_bps"])
        self.grid.set("Std Error",res["stderr"])
        # Correlation sensitivity
        rhos=np.linspace(0,0.9,20); prices=[]
        from instruments.structured.cln_ftd import ftd_basket as _ftd
        for rho in rhos:
            r2=_ftd(self.ftd_face.value(),self.ftd_cpn.value()/100,
                    self.ftd_T.value(),int(self.ftd_freq.currentText()),
                    self.ftd_r.value()/100,hazards,self.ftd_rec.value()/100,rho,n_sims=5000)
            prices.append(r2["price"]/self.ftd_face.value()*100)
        self.chart.plot_payoff(rhos*100,prices,"FTD Value vs Correlation",self.ftd_rho.value())
        self.chart._finish(self.chart.ax,"FTD Sensitivity to Correlation","Correlation (%)","Value (% face)")

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
