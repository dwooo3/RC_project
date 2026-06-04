# RiskCalc Desktop Workstation Wireframes

Date: 2026-06-04

Companion specification:

- `DESIGN_SYSTEM.md`

Scope:

- Dashboard
- Portfolio Workspace
- Risk Workspace
- Pricing Workspace
- Market Data Workspace

Design target:

- dark theme;
- institutional desktop workstation;
- dense information;
- keyboard oriented;
- multi-panel layout;
- no consumer/mobile/dribbble patterns.

Notation:

```text
[KPI]      compact metric card
[TABLE]    dense sortable table
[CHART]    analytical chart
[CTX]      right context drawer
[CMD]      command/action control
[WARN]     warning/error area
[TAB]      internal workspace tab
```

## 1. Global Shell Wireframe

This shell wraps every screen.

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ RiskCalc  [Ctrl+K Search command or screen...]  Portfolio: Main  Book: Trading  Date: 2026-06-04          │
│ Snapshot: DEMO:snap_20260604:v3  Mode: Demo  Warnings: 4   [Run] [Save] [Export]                         │
├───────────────┬───────────────────────────────────────────────────────────────────────────────┬────────────┤
│ NAV           │ WORKSPACE HEADER                                                              │ CONTEXT    │
│               │ Title / subtitle                                      Scope chips / actions   │ DRAWER     │
│ Dashboard     ├───────────────────────────────────────────────────────────────────────────────┤            │
│ Portfolio     │ KPI STRIP                                                                      │ selected   │
│ Risk          ├───────────────────────────────────────────────────────────────────────────────┤ object,    │
│ Market Data   │                                                                               │ model,     │
│ Pricing       │ MAIN WORKSPACE                                                                 │ data,      │
│ Governance    │                                                                               │ warnings,  │
│ Analytics Lab │                                                                               │ audit      │
│               │                                                                               │            │
├───────────────┴───────────────────────────────────────────────────────────────────────────────┴────────────┤
│ Last run: VaR 99% · 2026-06-04 10:42:18 · calc_84219     Data: DEMO / stale 0d     F1 Help     Ctrl+L Log │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Persistent regions:

- sidebar navigation;
- command/context bar;
- workspace header;
- KPI strip;
- main split area;
- right context drawer;
- bottom audit/status bar.

## 2. Dashboard

### 2.1 Dashboard Purpose

Dashboard is the daily control tower. It should answer:

- Is the portfolio valued?
- Is market data current?
- What are VaR, ES, and worst stress?
- Are models/data valid?
- Which actions are required now?

### 2.2 Dashboard Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Dashboard                                                        Scope: Main Portfolio / Trading / DEMO   │
│ Market risk and pricing control tower                            [Refresh] [Run Daily Pack] [Export]      │
├────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [MV 124.8m RUB +0.4%] [Daily P&L +482k] [VaR 99% 3.8m] [ES 99% 5.1m] [Worst Stress -9.6m] [Warnings 4]   │
├──────────────────────────────┬──────────────────────────────────────────────┬──────────────────────────────┤
│ DAILY CHECKLIST              │ PORTFOLIO / RISK STATUS                     │ WARNINGS / REQUIRED ACTIONS   │
│                              │                                              │                              │
│ [x] Market data snapshot     │ ┌──────────────────────────────────────────┐ │ [WARN] Demo market data       │
│ [x] Portfolio loaded         │ │ [CHART] P&L and risk summary             │ │ [WARN] Bond approximation     │
│ [ ] Portfolio valued today   │ │ VaR / ES / Stress mini bars              │ │ [ERR ] Broken model blocked   │
│ [ ] VaR run today            │ └──────────────────────────────────────────┘ │ [WARN] IRS single curve        │
│ [ ] Stress pack run          │                                              │                              │
│ [ ] Export report            │ ┌──────────────────────────────────────────┐ │ [Open Warnings] [Governance]  │
│                              │ │ [TABLE] Recent calculations              │ │                              │
│ [Value Portfolio]            │ │ Time | Type | Status | Warnings | Link   │ │ MODEL STATUS                  │
│ [Run VaR]                    │ └──────────────────────────────────────────┘ │ Validated       8             │
│ [Run Stress]                 │                                              │ Approximation   6             │
│                              │                                              │ Prototype       9             │
├──────────────────────────────┴──────────────────────────────────────────────┴──────────────────────────────┤
│ ALERTS                                                                                                     │
│ [TABLE] Severity | Object | Message | Owner | Action | Link                                               │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Dashboard Panels

Left panel:

- daily workflow checklist;
- action buttons;
- active portfolio/book filters.

Center panel:

- portfolio and risk status;
- recent calculations;
- mini charts.

Right panel:

- warnings;
- model summary;
- data status.

Bottom panel:

- alert table with actionable rows.

### 2.4 Dashboard Keyboard Flow

```text
Ctrl+1  Open Dashboard
R       Refresh
D       Run daily pack
V       Value portfolio
Shift+V Run VaR
S       Run Stress
L       Open warning log
E       Export daily summary
Enter   Open selected alert/calculation
```

## 3. Portfolio Workspace

### 3.1 Portfolio Purpose

Portfolio is the operating object for production workflows. It owns positions, valuation, factor exposure, scenario P&L, attribution, and validation.

### 3.2 Portfolio Overview Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Portfolio / Overview                                      [Add Position] [Import] [Value] [Run Risk]      │
│ Main Portfolio · Trading book · 128 positions              Snapshot: DEMO:snap_20260604:v3                │
├────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [MV 124.8m] [P&L +482k] [Positions 128] [Rates DV01 42k] [FX Delta -1.2m] [Vol Vega 318k] [CS01 76k]     │
├──────────────────────────────┬─────────────────────────────────────────────────────────────┬───────────────┤
│ PORTFOLIO SCOPE              │ POSITIONS                                                   │ POSITION CTX  │
│                              │ [Search positions...] [Book: Trading v] [Product: All v]   │ pos_01842     │
│ Portfolio: Main              │ ┌─────────────────────────────────────────────────────────┐ │ IRS 5Y        │
│ Book: Trading                │ │ [TABLE] ID | Product | Qty | MV | P&L | Rates | FX | Vol│ │ MV 4.8m      │
│ Currency: RUB                │ │ pos_001 | Bond | 10m | 9.8m | +12k | 8.2k  | -  | -   │ │ DV01 8.2k    │
│ Valuation: 2026-06-04        │ │ pos_002 | IRS  | 20m | 4.8m | -31k | 11.4k | -  | -   │ │ Model: APPROX│
│ Snapshot: DEMO v3            │ │ pos_003 | FXO  |  5m | 1.1m | +22k | -     |1.2m|33k │ │              │
│                              │ └─────────────────────────────────────────────────────────┘ │ [WARN] single│
│ Filters                      │                                                             │ curve IRS     │
│ [Desk] [Trader] [Product]    │ EXPOSURE BY FACTOR                                           │              │
│                              │ ┌─────────────────────────────────────────────────────────┐ │ [Open Model] │
│ [Value Portfolio]            │ │ [CHART] Rates | FX | Equity | Credit | Volatility       │ │ [Price Pos]  │
│ [Scenario P&L]               │ └─────────────────────────────────────────────────────────┘ │ [Validate]   │
├──────────────────────────────┴─────────────────────────────────────────────────────────────┴───────────────┤
│ [TAB Positions] [TAB Valuation] [TAB Exposure] [TAB Scenario P&L] [TAB P&L Explain] [TAB Validation]      │
│ [TABLE] Factor | Bucket | Exposure | P&L Contribution | Limit | Utilization | Warning                    │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Portfolio Scenario P&L Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Portfolio / Scenario P&L                                      [Apply Scenario] [Save Scenario] [Export]  │
├──────────────────────────────┬─────────────────────────────────────────────────────────────┬───────────────┤
│ SCENARIO BUILDER             │ SCENARIO RESULTS                                            │ SCENARIO CTX  │
│ Type: Historical             │ [KPI Total P&L -9.6m] [Worst Book Rates] [Residual 0.2m]   │ Scenario ID   │
│ Scenario: 2020 Shock         │ ┌─────────────────────────────────────────────────────────┐ │ hist_2020_03  │
│ Curve: +150bp parallel       │ │ [CHART] P&L by risk factor waterfall                    │ │ Source: DEMO  │
│ FX: RUB -12%                 │ └─────────────────────────────────────────────────────────┘ │ Snapshot v3   │
│ Equity: -20%                 │ ┌─────────────────────────────────────────────────────────┐ │ Model warnings│
│ Vol: +8 vol pts              │ │ [TABLE] Book | Rates | FX | Equity | Credit | Vol | P&L │ │ 3 warnings   │
│ Credit: +90bp                │ └─────────────────────────────────────────────────────────┘ │              │
│                              │                                                             │ [Explain P&L] │
│ [Run] [Compare] [Reset]      │                                                             │ [Governance]  │
└──────────────────────────────┴─────────────────────────────────────────────────────────────┴───────────────┘
```

### 3.4 Portfolio Keyboard Flow

```text
Ctrl+2   Open Portfolio
N        Add position
I        Import positions
V        Value portfolio
Shift+V  Run portfolio VaR
S        Open Scenario P&L
A        Open P&L Explain
F        Focus position filter
Del      Remove selected position
Enter    Open selected position detail
Ctrl+E   Export portfolio report
```

## 4. Risk Workspace

### 4.1 Risk Purpose

Risk owns VaR, ES, stress, backtesting, limits, and contribution analysis for the active portfolio.

### 4.2 Risk Overview Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Risk / Overview                                       Portfolio: Main · Snapshot: DEMO v3                 │
│ Market risk, stress, backtesting, limits              [Run VaR] [Run Stress] [Backtest] [Export]          │
├────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [VaR 95% 2.4m] [VaR 99% 3.8m] [ES 99% 5.1m] [Worst Stress -9.6m] [Exceptions 2] [Limit Util 74%]          │
├──────────────────────────────┬─────────────────────────────────────────────────────────────┬───────────────┤
│ RISK CONTROLS                │ VAR / ES DISTRIBUTION                                      │ RISK CTX      │
│                              │ ┌─────────────────────────────────────────────────────────┐ │ Method: Hist  │
│ Scope: Main Portfolio        │ │ [CHART] Loss distribution with VaR/ES markers           │ │ Conf: 99%     │
│ Book: Trading                │ └─────────────────────────────────────────────────────────┘ │ Horizon: 10d  │
│ Method: Historical           │                                                             │ Obs: 1000     │
│ Confidence: 99%              │ COMPONENT CONTRIBUTION                                      │ Data: DEMO    │
│ Horizon: 10d                 │ ┌─────────────────────────────────────────────────────────┐ │ Model: APPROX │
│ Returns: P&L history         │ │ [TABLE] Factor | VaR contrib | ES contrib | % | Warning │ │              │
│                              │ └─────────────────────────────────────────────────────────┘ │ [WARN] demo   │
│ [Run VaR / ES]               │                                                             │ returns       │
│ [Compare Methods]            │ STRESS SUMMARY                                               │              │
│ [Backtest]                   │ ┌─────────────────────────────────────────────────────────┐ │ [Model Detail]│
│ [Limits]                     │ │ [TABLE] Scenario | P&L | Worst Book | Limit | Status    │ │ [Audit Trail] │
│                              │ └─────────────────────────────────────────────────────────┘ │              │
├──────────────────────────────┴─────────────────────────────────────────────────────────────┴───────────────┤
│ [TAB Overview] [TAB Historical] [TAB Parametric] [TAB Monte Carlo] [TAB Stress] [TAB Backtesting] [Limits]│
│ [TABLE] Run ID | Time | Method | VaR | ES | Exceptions | Warnings | Snapshot | Model                       │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Backtesting Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Risk / Backtesting                                                   [Run Backtest] [Export Exceptions]  │
├────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [Exceptions 2] [Expected 2.5] [Traffic Light Green] [Obs 1000] [Breach Rate 0.20%] [Data Quality Warning] │
├──────────────────────────────┬─────────────────────────────────────────────────────────────┬───────────────┤
│ BACKTEST CONTROLS            │ EXCEPTION TIMELINE                                          │ BACKTEST CTX  │
│ VaR run: var_84219           │ ┌─────────────────────────────────────────────────────────┐ │ Model: Hist   │
│ Portfolio: Main              │ │ [CHART] P&L vs VaR time series with breach markers      │ │ Snapshot v3   │
│ Window: 1000 obs             │ └─────────────────────────────────────────────────────────┘ │ Loss sign +   │
│ Confidence: 99%              │                                                             │ ES >= VaR yes │
│                              │ EXCEPTION DETAIL                                            │              │
│ [Run] [Compare]              │ ┌─────────────────────────────────────────────────────────┐ │ [Governance]  │
│                              │ │ [TABLE] Date | P&L | VaR | Excess | Drivers | Notes     │ │ [Audit Trail] │
│                              │ └─────────────────────────────────────────────────────────┘ │              │
└──────────────────────────────┴─────────────────────────────────────────────────────────────┴───────────────┘
```

### 4.4 Risk Keyboard Flow

```text
Ctrl+3  Open Risk
V       Run VaR / ES
S       Run Stress
B       Open Backtesting
L       Open Limits
C       Compare methods
X       Open Counterparty Risk / XVA
F       Focus risk filter
Ctrl+E  Export risk report
Enter   Open selected result
```

## 5. Pricing Workspace

### 5.1 Pricing Purpose

Pricing owns instrument valuation. It consumes active market data and governance state, then can save results into Portfolio.

### 5.2 Pricing Landing Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Pricing                                                        Snapshot: DEMO v3 · Mode: Demo             │
│ Price instruments using governed models                        [Search Module] [Recent] [Favorites]       │
├────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [WARN] Demo data active  [WARN] 6 approximation models available  [INFO] Production mode disabled         │
├────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ CORE PRICING                                                                                              │
│ ┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐     │
│ │ Bond Pricing         │ │ IRS / OIS             │ │ FX Forward & Options │ │ Vanilla Options      │     │
│ │ Fixed income         │ │ Rates swaps           │ │ GK / forwards        │ │ BSM / Greeks         │     │
│ │ [Approximation]      │ │ [Approximation]       │ │ [Validated]          │ │ [Validated]          │     │
│ └──────────────────────┘ └──────────────────────┘ └──────────────────────┘ └──────────────────────┘     │
│                                                                                                            │
│ RATES & CREDIT                                                                                             │
│ ┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐                               │
│ │ Cap/Floor/Swaption   │ │ Credit / CDS          │ │ Futures & Forwards   │                               │
│ │ [Prototype]          │ │ [Prototype]           │ │ [Approximation]      │                               │
│ └──────────────────────┘ └──────────────────────┘ └──────────────────────┘                               │
│                                                                                                            │
│ STRUCTURED & EXOTIC                                                                                        │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                      │
│ │ Barrier      │ │ Asian        │ │ Digital      │ │ Lookback     │ │ Structured   │                      │
│ │ [Prototype]  │ │ [Prototype]  │ │ [Prototype]  │ │ [Prototype]  │ │ [Prototype]  │                      │
│ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘                      │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Bond Pricing Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Pricing / Rates / Bond Pricing                                [Price] [Scenario] [Add to Portfolio]      │
│ Fixed-rate bond valuation                                      Model: fixed_bond [Approximation]          │
├──────────────────────────────┬─────────────────────────────────────────────────────────────┬───────────────┤
│ TRADE INPUTS                 │ RESULTS                                                     │ RESULT CTX    │
│ Face: 1,000,000              │ [Clean Price 98.42] [Dirty Price 99.11] [Accrued 0.69]      │ Calc ID       │
│ Coupon: 7.50%                │ [YTM 7.91%] [Mod Duration 4.12] [DV01 412.4] [Conv 23.1]   │ calc_91822    │
│ Frequency: Semiannual        │                                                             │ Snapshot v3   │
│ Issue: 2024-06-04            │ ┌─────────────────────────────────────────────────────────┐ │ Curve: RUB    │
│ Maturity: 2029-06-04         │ │ [CHART] Cashflow PV by payment date                     │ │ Source: DEMO  │
│ Settlement: 2026-06-04       │ └─────────────────────────────────────────────────────────┘ │ Day count     │
│ Day count: ACT/365F          │                                                             │ ACT/365F      │
│ Curve: RUB_GOVT              │ CASHFLOWS                                                   │              │
│ Clean/Dirty: Clean           │ ┌─────────────────────────────────────────────────────────┐ │ [WARN] approx │
│                              │ │ [TABLE] Date | YearFrac | Coupon | Principal | DF | PV  │ │ methodology   │
│ [Price] [Reset]              │ └─────────────────────────────────────────────────────────┘ │              │
│                              │                                                             │ [Model Detail]│
├──────────────────────────────┴─────────────────────────────────────────────────────────────┴───────────────┤
│ [TAB Pricing] [TAB Cashflows] [TAB Sensitivities] [TAB Scenario] [TAB Validation]                         │
│ [TABLE] Shock | Clean Price | Dirty Price | DV01 | P&L | Warning                                          │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.4 IRS Pricing Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Pricing / Rates / IRS-OIS                                      [Price] [Curve Risk] [Add to Portfolio]   │
├──────────────────────────────┬─────────────────────────────────────────────────────────────┬───────────────┤
│ SWAP INPUTS                  │ RESULTS                                                     │ MODEL / DATA  │
│ Notional: 100,000,000        │ [NPV 1.24m] [Fair Rate 7.42%] [Fixed PV -43.2m]             │ Model: IRS    │
│ Pay/Receive: Pay Fixed       │ [Float PV 44.4m] [Annuity 58.2m] [DV01 58.2k]              │ Status: Approx│
│ Fixed Rate: 7.25%            │                                                             │ Discount curve│
│ Start: 2026-06-06            │ ┌─────────────────────────────────────────────────────────┐ │ RUB_OIS       │
│ Maturity: 2031-06-06         │ │ [CHART] Leg PV and key-rate DV01                         │ │ Projection    │
│ Fixed Freq: Annual           │ └─────────────────────────────────────────────────────────┘ │ RUB_3M        │
│ Float Freq: Quarterly        │                                                             │              │
│ Discount Curve: RUB_OIS      │ LEG CASHFLOWS                                                │ [WARN] missing│
│ Projection Curve: RUB_3M     │ ┌─────────────────────────────────────────────────────────┐ │ fixings       │
│                              │ │ [TABLE] Leg | Date | YearFrac | Rate | Cashflow | PV     │ │              │
└──────────────────────────────┴─────────────────────────────────────────────────────────────┴───────────────┘
```

### 5.5 Pricing Keyboard Flow

```text
Ctrl+5  Open Pricing
F       Focus module search
P       Price / reprice
S       Run scenario
A       Add to portfolio
M       Open model detail
R       Reset inputs
Ctrl+S  Save pricing result
Ctrl+E  Export ticket
Enter   Open selected module / run focused form
```

## 6. Market Data Workspace

### 6.1 Market Data Purpose

Market Data owns snapshots, sources, yield curves, vol surfaces, FX data, credit curves, and validation.

It does not price instruments.

### 6.2 Market Data Overview Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Market Data / Overview                                  [Create Snapshot] [Import CSV] [Validate]         │
│ Active snapshot DEMO:snap_20260604:v3                   Sources: DEMO / MANUAL / CSV / MOEX pending       │
├────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [Snapshot v3] [Val Date 2026-06-04] [Source DEMO] [Curves 4] [Vol Surfaces 2] [FX Pairs 8] [Warnings 2]   │
├──────────────────────────────┬─────────────────────────────────────────────────────────────┬───────────────┤
│ SNAPSHOT / SOURCES           │ MARKET DATA SUMMARY                                         │ DATA CTX      │
│                              │ ┌─────────────────────────────────────────────────────────┐ │ Snapshot ID   │
│ Active: snap_20260604:v3     │ │ [CHART] Curve summary: RUB, USD, EUR                    │ │ snap_...:v3   │
│ Source: DEMO                 │ └─────────────────────────────────────────────────────────┘ │ Created       │
│ Quality: Demo                │                                                             │ 10:31:18      │
│                              │ ┌─────────────────────────────────────────────────────────┐ │ Source DEMO   │
│ SOURCES                      │ │ [TABLE] Object | Source | Version | Quality | Warnings   │ │ Quality Demo  │
│ [DEMO] healthy               │ │ RUB_GOVT | DEMO | v3 | warning | monotonic OK            │ │              │
│ [MANUAL] available           │ │ FX_USDRUB | CSV | v2 | ok | none                         │ │ [WARN] demo   │
│ [CSV] available              │ └─────────────────────────────────────────────────────────┘ │ data          │
│ [MOEX] interface             │                                                             │              │
│ [Bloomberg] disabled         │ VALIDATION                                                   │ [Validate]    │
│ [Reuters] disabled           │ ┌─────────────────────────────────────────────────────────┐ │ [Use Snapshot]│
│                              │ │ [TABLE] Check | Status | Detail | Affected Object        │ │              │
└──────────────────────────────┴─────────────────────────────────────────────────────────────┴───────────────┘
```

### 6.3 Yield Curves Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Market Data / Yield Curves                                  [Build Curve] [Validate] [Save Snapshot]      │
├──────────────────────────────┬─────────────────────────────────────────────────────────────┬───────────────┤
│ CURVE LIST / BUILDER         │ CURVE VIEW                                                  │ CURVE CTX     │
│ Curve: RUB_GOVT              │ [1Y 7.20%] [5Y 7.80%] [10Y 8.10%] [10Y-2Y 42bp]            │ Curve ID      │
│ Source: CSV                  │ ┌─────────────────────────────────────────────────────────┐ │ RUB_GOVT     │
│ Val Date: 2026-06-04         │ │ [CHART] Zero / discount / forward curve                 │ │ Source CSV   │
│ Interpolation: Linear DF     │ └─────────────────────────────────────────────────────────┘ │ Version v3    │
│                              │                                                             │ Monotonic yes │
│ TENOR INPUTS                 │ CURVE POINTS                                                 │ Positive DF   │
│ [TABLE] Tenor | Rate | Type  │ ┌─────────────────────────────────────────────────────────┐ │ yes          │
│ 1M | 6.95 | zero             │ │ [TABLE] Tenor | Zero | DF | Forward | Source | Warning  │ │              │
│ 3M | 7.05 | zero             │ └─────────────────────────────────────────────────────────┘ │ [Use Pricing] │
│ 1Y | 7.20 | zero             │                                                             │ [Audit]       │
└──────────────────────────────┴─────────────────────────────────────────────────────────────┴───────────────┘
```

### 6.4 Vol Surface Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Market Data / Vol Surface                                  [Calibrate] [Validate] [Save Snapshot]         │
├──────────────────────────────┬─────────────────────────────────────────────────────────────┬───────────────┤
│ SURFACE SETUP                │ VOL SURFACE                                                 │ SURFACE CTX   │
│ Asset: USDRUB                │ [ATM 14.2%] [25D RR -1.1] [25D BF 0.8] [RMSE 0.34]         │ Surface ID    │
│ Source: CSV                  │ ┌─────────────────────────────────────────────────────────┐ │ FXVOL_USDRUB │
│ Date: 2026-06-04             │ │ [CHART] Smile / term structure / surface                │ │ Source CSV   │
│ Interp: bilinear             │ └─────────────────────────────────────────────────────────┘ │ Status approx │
│                              │                                                             │              │
│ POINTS                       │ SURFACE POINTS                                               │ [WARN] sparse │
│ [TABLE] Tenor | Delta | Vol  │ ┌─────────────────────────────────────────────────────────┐ │ long tenor    │
│                              │ │ [TABLE] Tenor | Strike/Delta | Vol | Source | Warning   │ │              │
└──────────────────────────────┴─────────────────────────────────────────────────────────────┴───────────────┘
```

### 6.5 Market Data Keyboard Flow

```text
Ctrl+4  Open Market Data
N       Create snapshot
I       Import CSV
V       Validate active snapshot
C       Open Yield Curves
S       Open Snapshot Store
F       Focus source/filter
Ctrl+S  Save snapshot
Ctrl+E  Export market data
Enter   Open selected data object
```

## 7. Common Wireframe Rules

### 7.1 KPI Strip

KPI strip appears immediately under workspace header.

Rules:

- one row only;
- compact metrics;
- no decorative cards;
- every KPI can be opened for detail;
- warnings should be visible inline.

### 7.2 Context Drawer

Right drawer always reflects selected object:

- selected position;
- selected risk run;
- selected pricing result;
- selected market-data object;
- selected warning;
- selected model.

Required sections:

```text
Identity
Status
Source / Snapshot
Model / Governance
Warnings
Actions
Audit
```

### 7.3 Bottom Detail Tabs

Bottom tabs should hold secondary depth:

- validation;
- audit;
- history;
- sensitivity tables;
- scenario grids;
- raw input/output detail.

Do not put primary actions only in bottom tabs.

### 7.4 Warning Placement

Warnings appear in three places:

```text
Global context bar: count
Workspace header/KPI strip: current workflow warning
Context drawer: full detail and governance link
```

### 7.5 Dense Table Defaults

```text
Row height: 24-28 px
Header height: 28-32 px
Numeric columns right aligned
Identifier columns left aligned
Selected row opens context drawer
Filter row always keyboard reachable
```

## 8. Implementation Sequence For Wireframes

1. Implement global shell and context bar.
2. Implement Dashboard wireframe using existing services.
3. Implement Portfolio workspace tabs and factor exposure layout.
4. Implement Risk overview, VaR, stress, and backtesting layouts.
5. Implement Market Data overview and Yield Curve workspace.
6. Implement Pricing landing and Bond Pricing layout.
7. Extend Pricing to IRS and FX.
8. Add Governance and Analytics Lab after the five requested workspaces are stable.

## 9. Non-Goals

Do not implement:

- mobile layouts;
- consumer onboarding;
- decorative landing pages;
- marketing dashboards;
- animated hero screens;
- card-only product navigation;
- visual redesign before service-backed workflows are stable.

These wireframes are for a professional desktop workstation.
