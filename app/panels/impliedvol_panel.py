"""Implied volatility solver panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
import numpy as np
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter,QTableWidget,QTableWidgetItem,QHeaderView
from PySide6.QtCore import Qt
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget

class ImpliedVolPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Implied Volatility","Newton-Raphson + Brent solver  ·  BSM · Black-76 · Garman-Kohlhagen"))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.mkt=make_spin(0.0001,1e9,5.0,0.01,4); self.spot=make_spin(0.01,1e9,100,1,2)
        self.strike=make_spin(0.01,1e9,100,1,2); self.T=make_spin(0.001,50,0.5,0.01,3,"yr")
        self.rate=make_pct(0.05); self.div=make_pct(0.00); self.opt=make_combo(["Call","Put"])
        self.model=make_combo(["BSM","Black-76","Garman-Kohlhagen"])
        f.add_group("Single Option",[
            FieldRow("Market price",self.mkt),FieldRow("Spot (S)",self.spot),
            FieldRow("Strike (K)",self.strike),FieldRow("Expiry (T)",self.T),
            FieldRow("Rate (r)",self.rate),FieldRow("Div / r_f",self.div),
            FieldRow("Type",self.opt),FieldRow("Model",self.model),
        ])
        ll.addWidget(f,1)
        bb=QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn=QPushButton("Calculate IV"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr=QPushButton("Clear"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn,1); bb.addWidget(self.clr); ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate); self.clr.clicked.connect(self.clear)
        right=QWidget(); right.setObjectName("results_panel")
        rl=QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr=QWidget(); hdr.setObjectName("results_header"); hl=QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10); lb=QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)
        self.grid=ResultsGrid(["Implied Vol","Market Price","Model Price","Moneyness","Time Value","Delta"],cols=3,highlight="Implied Vol")
        rl.addWidget(self.grid)
        # Smile builder table
        smile_lbl=QLabel("  Vol Smile Builder (enter market prices by strike)")
        smile_lbl.setStyleSheet("font-size:11px;font-weight:600;color:#6e6e73;padding:8px 18px 4px;")
        rl.addWidget(smile_lbl)
        self.smile_table=QTableWidget(5,3)
        self.smile_table.setHorizontalHeaderLabels(["Strike","Mkt Price","Implied Vol"])
        self.smile_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i,k in enumerate([85,90,95,100,105,110,115]):
            if i<5:
                self.smile_table.setItem(i,0,QTableWidgetItem(str(k)))
                self.smile_table.setItem(i,1,QTableWidgetItem(""))
                self.smile_table.setItem(i,2,QTableWidgetItem("—"))
        self.smile_table.setMaximumHeight(180); self.smile_table.setAlternatingRowColors(True)
        rl.addWidget(self.smile_table)
        self.btn_smile=QPushButton("Build Vol Smile")
        self.btn_smile.setObjectName("calc_btn"); self.btn_smile.setFixedHeight(34)
        self.btn_smile.setStyleSheet("margin:6px 18px;font-size:12px;")
        self.btn_smile.clicked.connect(self.build_smile)
        rl.addWidget(self.btn_smile)
        self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        mkt=self.mkt.value(); S=self.spot.value(); K=self.strike.value()
        T=self.T.value(); r=self.rate.value()/100; q=self.div.value()/100
        opt=self.opt.currentText().lower(); m=self.model.currentText()
        try:
            if m=="BSM":
                from models.implied_vol import implied_vol_bsm
                iv=implied_vol_bsm(mkt,S,K,T,r,q,opt)
            elif m=="Black-76":
                from models.implied_vol import implied_vol_black76
                iv=implied_vol_black76(mkt,S,K,T,r,opt)
            else:
                from models.implied_vol import implied_vol_gk
                iv=implied_vol_gk(mkt,S,K,T,r,q,opt)
            if iv!=iv: self.banner.show_error("No solution found — check inputs"); return
            from models.black_scholes import bsm as _b
            g=_b(S,K,T,r,iv,q,opt)
            intrinsic=max(S-K,0) if opt=="call" else max(K-S,0)
            self.grid.set("Implied Vol",iv,sub=f"{iv*100:.3f}%",color="#d97757")
            self.grid.set("Market Price",mkt); self.grid.set("Model Price",g.price)
            self.grid.set("Moneyness",S/K,sub="S/K"); self.grid.set("Time Value",mkt-intrinsic)
            self.grid.set("Delta",g.delta)
            # plot BSM price vs vol
            vols=np.linspace(max(iv-0.15,0.01),iv+0.15,80)
            prices=[_b(S,K,T,r,v,q,opt).price for v in vols]
            self.chart.plot_payoff(vols*100,prices,"BSM Price vs Vol",iv*100)
            self.chart.ax.axhline(mkt,color="#ff9f0a",lw=1.2,ls="--",label=f"Mkt={mkt:.4f}")
            self.chart.ax.legend(fontsize=8)
            self.chart._finish(self.chart.ax,"Price vs Volatility","Vol (%)","Price")
        except Exception as e:
            self.banner.show_error(str(e))

    def build_smile(self):
        self.banner.clear()
        S=self.spot.value(); T=self.T.value(); r=self.rate.value()/100
        q=self.div.value()/100; opt=self.opt.currentText().lower()
        strikes=[]; ivs=[]
        from models.implied_vol import implied_vol_bsm
        for row in range(self.smile_table.rowCount()):
            ki=self.smile_table.item(row,0); pi=self.smile_table.item(row,1)
            if not ki or not pi or not pi.text().strip(): continue
            try:
                k=float(ki.text()); p=float(pi.text())
                iv=implied_vol_bsm(p,S,k,T,r,q,opt)
                self.smile_table.setItem(row,2,QTableWidgetItem(f"{iv*100:.3f}%" if iv==iv else "N/A"))
                if iv==iv: strikes.append(k); ivs.append(iv)
            except: pass
        if len(strikes)>=2:
            F=S*np.exp((r-q)*T)
            self.chart.plot_vol_smile(strikes,ivs,F)

    def clear(self):
        self.grid.clear_all(); self.chart.clear(); self.banner.clear()
