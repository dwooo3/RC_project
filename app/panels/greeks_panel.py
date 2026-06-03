"""Greeks ladder panel."""
import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),"../.."))
import numpy as np
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QLabel,QSplitter,QTableWidget,QTableWidgetItem,QHeaderView
from PySide6.QtCore import Qt,QTimer
from app.widgets import ParamForm,FieldRow,ResultsGrid,SectionHeader,Banner,make_spin,make_pct,make_combo
from app.chart import ChartWidget

class GreeksPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self._db=QTimer(); self._db.setSingleShot(True); self._db.timeout.connect(self.calculate)
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sp=QSplitter(Qt.Horizontal); sp.setHandleWidth(1); sp.setStyleSheet("QSplitter::handle{background:#2e2e33;}")
        left=QWidget(); left.setObjectName("center_panel"); left.setMinimumWidth(330); left.setMaximumWidth(400)
        ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(SectionHeader("Greeks Ladder","Delta · Gamma · Vega across spot range  —  auto-updates on change"))
        self.banner=Banner(); ll.addWidget(self.banner)
        f=ParamForm()
        self.spot=make_spin(0.01,1e9,100,1,2); self.strike=make_spin(0.01,1e9,100,1,2)
        self.T=make_spin(0.001,50,0.5,0.01,3,"yr"); self.rate=make_pct(0.05)
        self.sigma=make_pct(0.20,0.01,5); self.div=make_pct(0); self.opt=make_combo(["Call","Put"])
        self.range=make_pct(30,5,90); self.steps=make_spin(5,100,21,2,0)
        f.add_group("Option Parameters",[
            FieldRow("Spot (S)",self.spot),FieldRow("Strike (K)",self.strike),
            FieldRow("Expiry (T)",self.T),FieldRow("Rate (r)",self.rate),
            FieldRow("Vol (σ)",self.sigma),FieldRow("Dividend",self.div),FieldRow("Type",self.opt),
        ])
        f.add_group("Ladder Settings",[FieldRow("Range ±%",self.range),FieldRow("Steps",self.steps)])
        ll.addWidget(f,1)
        bb=QHBoxLayout(); bb.setContentsMargins(16,12,16,14); bb.setSpacing(8)
        self.btn=QPushButton("Calculate"); self.btn.setObjectName("calc_btn"); self.btn.setFixedHeight(38)
        self.clr=QPushButton("Clear"); self.clr.setObjectName("clear_btn"); self.clr.setFixedHeight(38); self.clr.setFixedWidth(90)
        bb.addWidget(self.btn,1); bb.addWidget(self.clr); ll.addLayout(bb)
        self.btn.clicked.connect(self.calculate); self.clr.clicked.connect(self.clear)
        for w in [self.spot,self.strike,self.T,self.rate,self.sigma,self.div,self.range]:
            w.valueChanged.connect(lambda: self._db.start(400))
        for w in [self.opt]: w.currentIndexChanged.connect(lambda: self._db.start(400))
        right=QWidget(); right.setObjectName("results_panel")
        rl=QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        hdr=QWidget(); hdr.setObjectName("results_header"); hl=QHBoxLayout(hdr)
        hl.setContentsMargins(18,10,18,10); lb=QLabel("RESULTS"); lb.setObjectName("results_title_lbl")
        hl.addWidget(lb); rl.addWidget(hdr)
        self.table=QTableWidget(0,6)
        self.table.setHorizontalHeaderLabels(["Spot","Price","Delta","Gamma","Vega","Theta"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMaximumHeight(340); self.table.setAlternatingRowColors(True)
        rl.addWidget(self.table)
        self.chart=ChartWidget(); self.chart.clear(); rl.addWidget(self.chart,1)
        sp.addWidget(left); sp.addWidget(right); sp.setStretchFactor(0,0); sp.setStretchFactor(1,1); sp.setSizes([370,900]); root.addWidget(sp)

    def calculate(self):
        self.banner.clear()
        S=self.spot.value(); K=self.strike.value(); T=self.T.value()
        r=self.rate.value()/100; sig=self.sigma.value()/100; q=self.div.value()/100
        opt=self.opt.currentText().lower(); rng=self.range.value()/100; n=int(self.steps.value())
        try:
            from models.black_scholes import bsm as _b
            spots=np.linspace(S*(1-rng),S*(1+rng),n)
            prices=[]; deltas=[]; gammas=[]; vegas=[]; thetas=[]
            for s in spots:
                g=_b(s,K,T,r,sig,q,opt)
                prices.append(round(g.price,4)); deltas.append(round(g.delta,4))
                gammas.append(round(g.gamma,6)); vegas.append(round(g.vega,4)); thetas.append(round(g.theta,4))
            self.table.setRowCount(n)
            for i,(s,p,d,gm,ve,th) in enumerate(zip(spots,prices,deltas,gammas,vegas,thetas)):
                for j,v in enumerate([f"{s:.2f}",p,d,gm,ve,th]):
                    it=QTableWidgetItem(str(v)); it.setTextAlignment(Qt.AlignRight|Qt.AlignVCenter)
                    self.table.setItem(i,j,it)
            self.chart.plot_greeks_ladder(spots,prices,deltas,gammas,S,K)
        except Exception as e:
            self.banner.show_error(str(e))

    def clear(self):
        self.table.setRowCount(0); self.chart.clear(); self.banner.clear()
