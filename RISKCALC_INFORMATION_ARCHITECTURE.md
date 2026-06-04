# RiskCalc Information Architecture

Date: 2026-06-04

Status: Product specification

References:

- `PRODUCT_ARCHITECTURE.md`
- `UI_REDESIGN.md`
- `RISKCALC_UX_AUDIT.md`
- `PRODUCT_READINESS_AUDIT.md`

Target users:

- Market Risk Manager
- Quant Analyst
- Trader

Principle:

```text
RiskCalc must be organized around market-risk workflows, not implementation modules.
```

The ideal information architecture uses seven product layers:

```text
Layer 1: Dashboard
Layer 2: Portfolio
Layer 3: Risk
Layer 4: Market Data
Layer 5: Pricing
Layer 6: Governance
Layer 7: Analytics Lab
```

This order is intentional. Portfolio and Risk are promoted above Market Data and Pricing because the professional workstation should start from portfolio state and risk control, not from isolated calculators.

## 1. Global IA Model

### Primary Navigation

The left sidebar should contain only product layers:

```text
Dashboard
Portfolio
Risk
Market Data
Pricing
Governance
Analytics Lab
```

Optional secondary utility items may live below a separator:

```text
Settings
Help
```

Do not place individual instruments, models, or research methods in the primary sidebar.

### Global Context Bar

Every layer should share a persistent context bar:

```text
Portfolio: Main Portfolio
Book: Trading
Valuation Date: 2026-06-04
Market Data: DEMO / snapshot id / version
Mode: Demo | Production | Research
Warnings: count
Last Calculation: timestamp
```

The context bar is not a visual decoration. It is a product control surface. It tells the user which controlled objects are active across Portfolio, Risk, Market Data, Pricing, and Governance.

### Global Command Model

Every major workflow should be reachable through:

- sidebar layer navigation;
- layer landing cards;
- workflow actions;
- command palette;
- keyboard shortcuts.

Global shortcuts:

```text
Ctrl+1  Dashboard
Ctrl+2  Portfolio
Ctrl+3  Risk
Ctrl+4  Market Data
Ctrl+5  Pricing
Ctrl+6  Governance
Ctrl+7  Analytics Lab
Ctrl+K  Command palette
Ctrl+R  Run current calculation
Ctrl+S  Save current result / position / snapshot
Ctrl+E  Export current result
Ctrl+L  Open warnings / validation log
Esc     Close drawer / dialog / transient panel
```

### Cross-Layer Workflow Links

The IA must support these forward transitions:

```text
Dashboard -> Portfolio
Dashboard -> Risk
Dashboard -> Governance
Portfolio -> Risk
Portfolio -> Scenario P&L
Portfolio -> P&L Explain
Risk -> Backtesting
Risk -> Governance
Market Data -> Pricing
Pricing -> Portfolio
Pricing -> Scenario
Pricing -> Governance
Governance -> Analytics Lab
Analytics Lab -> Governance
```

## 2. Layer 1: Dashboard

### Product Role

Dashboard is the daily operating console. It answers:

```text
Is the portfolio ready?
Is market data ready?
Is risk ready?
Are there model or data warnings?
What changed since the last run?
Where should I go next?
```

Dashboard must not contain pricing forms, model parameters, full validation tables, or long diagnostics.

### User Goals

Market Risk Manager:

- check daily risk status;
- detect VaR, stress, data, or model issues;
- navigate to the next required control task.

Trader:

- see whether portfolio and market data are current;
- jump to pricing or scenario workflows.

Quant Analyst:

- see model warnings and validation gaps;
- jump to Governance or Analytics Lab.

### Screens

#### 1.1 Today Overview

Primary dashboard screen.

Sections:

- Portfolio Summary
- Risk Summary
- Market Data Status
- Model Status
- Alerts / Required Actions
- Recent Calculations

#### 1.2 Alerts

Focused list of blocked, warning, and stale states.

Alert types:

- stale market data;
- demo data in production mode;
- failed calculation;
- broken or placeholder model;
- VaR exception;
- stress breach;
- unvalidated model usage;
- missing portfolio valuation.

#### 1.3 Recent Activity

Chronological calculation and workflow history.

Activity types:

- portfolio valuation;
- VaR / ES run;
- stress run;
- pricing result;
- scenario P&L;
- P&L explain;
- market-data snapshot creation;
- governance status change.

### Navigation

Dashboard should use cards as workflow entry points:

```text
Portfolio Summary -> Portfolio / Positions
Risk Summary -> Risk / VaR Overview
Worst Stress -> Risk / Stress
Data Status -> Market Data / Monitor
Model Warnings -> Governance / Model Registry
Recent Pricing -> Pricing / Result Detail
```

Dashboard should never open raw model panels directly.

### Actions

Primary actions:

- Refresh Status
- Value Portfolio
- Run VaR
- Run Stress
- Open Warnings
- Export Daily Summary

Secondary actions:

- Change active portfolio;
- Change valuation date;
- Select market-data snapshot;
- Open recent calculation;
- Open model warning detail.

### Widgets

KPI cards:

- Market Value
- Daily P&L
- VaR 95%
- ES 95%
- Worst Stress Loss
- Positions
- Rate DV01
- Vol Vega

Status widgets:

- MarketDataStatusChip
- ModelStatusSummary
- WarningBanner
- WorkflowChecklist
- RecentCalculationList
- DataFreshnessIndicator

Tables:

- Alerts Table
- Recent Runs Table

Charts:

- Daily P&L sparkline
- Risk summary bar
- Stress loss mini chart

### Shortcuts

```text
Ctrl+1        Open Dashboard
R             Refresh dashboard
V             Value active portfolio
Shift+V       Run VaR
Shift+S       Run Stress
L             Open warning log
E             Export daily summary
Enter         Open selected alert or card
```

## 3. Layer 2: Portfolio

### Product Role

Portfolio is the center of RiskCalc. All production risk workflows should operate on a portfolio, even if the portfolio has one position.

Portfolio owns:

```text
Positions
Books
Valuation
Exposure
Performance
Scenario P&L
Attribution
Validation
```

### User Goals

Market Risk Manager:

- confirm positions and valuation;
- understand risk factor exposure;
- run portfolio-level risk and stress;
- explain P&L changes.

Trader:

- save priced trades into a portfolio;
- inspect position-level sensitivities;
- run scenario P&L.

Quant Analyst:

- inspect whether position data maps correctly to models;
- validate exposure aggregation methodology.

### Screens

#### 2.1 Portfolio Overview

The default Portfolio screen.

Sections:

- KPI row;
- positions summary;
- exposure summary;
- risk summary;
- validation summary.

#### 2.2 Positions

Position management and inspection.

Subviews:

- Positions Table
- Position Detail Drawer
- Add Position
- Import Positions
- Position Validation

#### 2.3 Books

Book hierarchy and filters.

Subsections:

- Book Tree
- Desk / Strategy / Trader filters
- Currency filters
- Product filters

#### 2.4 Valuation

Portfolio valuation run and results.

Subsections:

- valuation inputs;
- model coverage;
- market-data snapshot;
- valuation results;
- valuation warnings.

#### 2.5 Exposure

Risk-factor exposure view.

Groups:

- Rates
- FX
- Equity
- Credit
- Volatility

#### 2.6 Scenario P&L

Portfolio scenario workflow.

Scenario types:

- historical;
- hypothetical;
- regulatory;
- custom.

Supported shocks:

- parallel curve shift;
- steepener;
- flattener;
- FX shock;
- equity shock;
- volatility shock;
- credit spread shock.

#### 2.7 P&L Explain

Attribution workflow.

Components:

- Delta P&L
- Gamma P&L
- Vega P&L
- Theta P&L
- Rate P&L
- FX P&L
- Credit P&L
- Residual

#### 2.8 Validation

Portfolio data and calculation readiness.

Checks:

- missing pricing parameters;
- unsupported instrument types;
- stale market data;
- model governance warnings;
- invalid market-data snapshot;
- inconsistent currencies;
- failed position valuation.

### Navigation

Portfolio uses internal tabs:

```text
Overview
Positions
Books
Valuation
Exposure
Scenario P&L
P&L Explain
Validation
```

Forward links:

```text
Position -> Pricing module
Position -> Model detail
Exposure bucket -> Risk factor detail
Valuation result -> Run VaR
Scenario result -> P&L Explain
Validation warning -> Governance / Model detail
```

### Actions

Primary actions:

- Add Position
- Import Positions
- Value Portfolio
- Run VaR
- Run Stress
- Run Scenario P&L
- Explain P&L
- Export Portfolio Report

Position actions:

- edit position;
- duplicate position;
- remove position;
- price position;
- validate position;
- open model details.

Exposure actions:

- bucket by factor;
- bucket by book;
- bucket by currency;
- bucket by product;
- drill into contribution.

### Widgets

KPI cards:

- Market Value
- Daily P&L
- Positions
- Rate DV01
- FX Delta
- Equity Delta
- Credit CS01
- Vol Vega

Tables:

- Positions Table
- Valuation Results Table
- Exposure Table
- Scenario Results Table
- P&L Explain Table
- Validation Issues Table

Charts:

- Exposure by risk factor;
- Exposure by book;
- Scenario P&L waterfall;
- P&L explain waterfall;
- Contribution heatmap.

Controls:

- Portfolio selector;
- Book filter;
- Valuation date selector;
- Market-data snapshot selector;
- Position drawer;
- Scenario selector;
- WarningBanner.

### Shortcuts

```text
Ctrl+2        Open Portfolio
N             Add position
I             Import positions
V             Value portfolio
Shift+V       Run VaR on portfolio
Shift+S       Run stress on portfolio
P             Open Scenario P&L
A             Open P&L Explain
F             Focus portfolio filter
Del           Remove selected position
Enter         Open selected position detail
Ctrl+E        Export portfolio report
```

## 4. Layer 3: Risk

### Product Role

Risk owns portfolio-level risk measurement and risk control. It consumes Portfolio, Market Data, Pricing outputs, and Governance status.

Risk owns:

```text
VaR
ES
Stress
Backtesting
Limit Monitoring
Capital
Risk Explain
Counterparty Risk
```

Risk should not duplicate Portfolio as a generic module. Portfolio is the input object; Risk is the measurement and control layer.

### User Goals

Market Risk Manager:

- calculate VaR and ES;
- identify risk drivers;
- run stress scenarios;
- review exceptions and backtesting;
- monitor limits.

Trader:

- understand scenario and stress impact on active positions;
- check sensitivities and risk contribution before trade save.

Quant Analyst:

- validate risk methodology;
- compare historical, parametric, Monte Carlo, and EVT approaches;
- inspect numerical stability and assumptions.

### Screens

#### 3.1 Risk Overview

Risk control dashboard for the active portfolio.

Sections:

- VaR / ES summary;
- stress summary;
- exceptions;
- limit utilization;
- model/data warnings;
- recent risk runs.

#### 3.2 VaR / ES

Main VaR workflow.

Internal tabs:

- Overview
- Historical
- Parametric
- Monte Carlo
- EVT
- Component VaR
- Validation

#### 3.3 Stress Testing

Stress workflow.

Scenario groups:

- historical scenarios;
- hypothetical shocks;
- regulatory scenarios;
- custom scenarios.

#### 3.4 Backtesting

VaR exception analysis.

Views:

- exception timeline;
- traffic-light zone;
- observed vs predicted losses;
- breach detail;
- data quality checks.

#### 3.5 Limits

Limit monitoring and breach analysis.

Limit types:

- VaR;
- ES;
- DV01;
- CS01;
- Vega;
- stress loss;
- concentration.

#### 3.6 Capital

Future capital/risk-weighting workspace.

Initial scope:

- placeholder for regulatory capital calculations;
- clear status as not implemented until service support exists.

#### 3.7 Risk Explain

Risk factor and P&L contribution analysis.

Subsections:

- factor contributions;
- book contributions;
- product contributions;
- P&L attribution link.

#### 3.8 Counterparty Risk

XVA and exposure workflow.

Subsections:

- exposure profile;
- CVA;
- DVA;
- FVA;
- counterparty limits;
- model limitations.

### Navigation

Risk uses grouped landing sections:

```text
Market Risk
  VaR / ES
  Stress Testing
  Backtesting
  Limits

Risk Explain
  Factor Contribution
  P&L Attribution

Counterparty Risk
  XVA
  Exposure Profile

Capital
  Capital Overview
```

Forward links:

```text
Risk Overview -> VaR detail
VaR result -> Backtesting
VaR component -> Portfolio exposure
Stress scenario -> Scenario P&L
Limit breach -> Portfolio positions
Model warning -> Governance
XVA result -> Pricing / counterparty model detail
```

### Actions

Primary actions:

- Run VaR / ES
- Run Stress
- Run Backtest
- Refresh Limits
- Export Risk Report
- Open Breach Detail

Method actions:

- choose VaR method;
- set confidence level;
- set horizon;
- select returns source;
- choose portfolio scope;
- compare methods;
- validate input series.

Stress actions:

- apply scenario;
- create custom shock;
- save scenario;
- compare scenario set;
- export stress pack.

### Widgets

KPI cards:

- VaR 95%
- VaR 99%
- ES 95%
- ES 99%
- Worst Stress Loss
- Exceptions
- Backtest Zone
- Limit Utilization

Tables:

- VaR Method Comparison
- Risk Factor Contribution
- Stress Scenario Results
- Backtesting Exceptions
- Limit Breaches
- XVA Result Table

Charts:

- Loss distribution;
- VaR/ES tail chart;
- historical P&L timeline;
- exception timeline;
- stress waterfall;
- limit utilization bars;
- factor contribution treemap.

Controls:

- portfolio selector;
- book filter;
- method selector;
- confidence control;
- horizon control;
- scenario selector;
- returns source selector;
- warning banner.

### Shortcuts

```text
Ctrl+3        Open Risk
V             Run VaR / ES
S             Run Stress
B             Open Backtesting
L             Open Limits
C             Compare VaR methods
X             Open XVA / Counterparty Risk
F             Focus risk filter
Ctrl+E        Export risk report
Enter         Open selected risk result
```

## 5. Layer 4: Market Data

### Product Role

Market Data owns the inputs used by Portfolio, Pricing, and Risk. It does not price instruments.

Market Data owns:

```text
MarketDataSnapshot
Yield Curves
Volatility Surfaces
FX Market
Credit Curves
Market Data Monitor
Source and validation metadata
```

### User Goals

Market Risk Manager:

- confirm data freshness and source quality;
- verify active snapshot before risk runs.

Trader:

- select curve, vol, FX, and credit data before pricing;
- understand whether pricing uses demo, manual, CSV, or external data.

Quant Analyst:

- build curves;
- inspect interpolation and validation;
- calibrate surfaces;
- compare data sources.

### Screens

#### 4.1 Market Data Overview

Landing view and data control center.

Sections:

- active snapshot;
- data source status;
- curve summary;
- vol surface summary;
- FX summary;
- credit summary;
- validation warnings.

#### 4.2 Snapshot Store

Snapshot versioning and selection.

Subsections:

- snapshot list;
- snapshot detail;
- version history;
- source metadata;
- validation status;
- compare snapshots.

#### 4.3 Yield Curves

Curve workspace.

Tabs:

- Overview
- Curve Builder
- Zero / Par / Forward
- Scenario
- Validation

#### 4.4 Vol Surfaces

Volatility surface workspace.

Tabs:

- Surface
- Smile
- Term Structure
- Calibration
- Validation

#### 4.5 FX Market

FX data workspace, not FX option pricing.

Tabs:

- Spot
- Forward Points
- FX Curves
- Vols
- Validation

#### 4.6 Credit Curves

Credit market-data workspace.

Tabs:

- Credit Spreads
- Hazard Curves
- Survival Curves
- Recovery Assumptions
- Validation

#### 4.7 Data Sources

Source management.

Sources:

- DEMO
- MANUAL
- CSV
- MOEX
- Bloomberg interface
- Reuters interface

Bloomberg and Reuters should be shown as interface-ready or disabled until implemented.

### Navigation

Market Data landing cards:

```text
Snapshot Store
Yield Curves
Vol Surfaces
FX Market
Credit Curves
Data Sources
Market Data Monitor
```

Forward links:

```text
Curve -> Pricing / Bond
Curve -> Pricing / IRS
Vol Surface -> Pricing / Options
FX Snapshot -> Pricing / FX
Credit Curve -> Pricing / CDS
Snapshot Warning -> Governance / Data audit
Snapshot -> Portfolio valuation
```

### Actions

Primary actions:

- Create Snapshot
- Select Active Snapshot
- Validate Snapshot
- Import CSV
- Build Curve
- Calibrate Surface
- Compare Snapshots
- Export Market Data

Curve actions:

- add tenor/rate;
- bootstrap curve;
- inspect discount factors;
- inspect forward rates;
- apply curve shock;
- save curve to snapshot.

Vol actions:

- load vol points;
- calibrate surface;
- inspect smile;
- inspect term structure;
- save surface to snapshot.

FX actions:

- update spot;
- update forward points;
- update FX vols;
- validate cross rates;
- save FX set to snapshot.

### Widgets

KPI cards:

- Active Snapshot
- Valuation Date
- Source
- Snapshot Version
- Data Quality
- Curve Count
- Surface Count
- FX Pair Count
- Credit Curve Count

Tables:

- Snapshot Table
- Curve Tenor Table
- Vol Surface Points
- FX Rates Table
- Credit Spread Table
- Validation Issues Table

Charts:

- zero curve chart;
- discount factor chart;
- forward curve chart;
- vol smile chart;
- vol surface chart;
- FX forward points chart;
- credit spread curve chart.

Controls:

- source selector;
- valuation date picker;
- snapshot selector;
- import panel;
- curve builder form;
- validation banner;
- source status chips.

### Shortcuts

```text
Ctrl+4        Open Market Data
N             Create snapshot
I             Import CSV
V             Validate active snapshot
C             Open Yield Curves
S             Open Snapshot Store
F             Focus data source filter
Ctrl+S        Save snapshot
Ctrl+E        Export market data
Enter         Open selected snapshot / curve / surface
```

## 6. Layer 5: Pricing

### Product Role

Pricing owns instrument valuation. It consumes MarketDataSnapshot and Governance metadata and can create Portfolio positions.

Pricing should not construct market data directly. Pricing should not silently use prototype or broken models.

### User Goals

Trader:

- price trades quickly;
- inspect sensitivities;
- run scenarios;
- save pricing result to portfolio;
- export a trade ticket.

Quant Analyst:

- inspect model assumptions;
- compare pricing methods;
- validate model limitations.

Market Risk Manager:

- understand position valuation method and model status.

### Screens

#### 5.1 Pricing Overview

Grouped product landing page.

Groups:

```text
Core Pricing
  Bonds
  IRS / OIS
  FX Forwards & Options
  Vanilla Options

Rates & Credit
  Cap / Floor / Swaption
  Credit / CDS
  Futures & Forwards

Structured & Exotic
  Barrier Options
  Asian Options
  Digital / Touch
  Lookback Options
  Multi-Asset
  Variance Swaps
  Structured Products

Experimental / Restricted
  Commodity Derivatives
```

#### 5.2 Bond Pricing

Tabs:

- Pricing
- Cashflows
- Sensitivities
- Scenario
- Validation

Required context:

- curve source;
- valuation date;
- day count;
- settlement date;
- model status;
- limitations.

#### 5.3 IRS / OIS Pricing

Tabs:

- Pricing
- Cashflows
- Sensitivities
- Curve Risk
- Validation

Required warnings:

- single-curve approximation if dual-curve is unavailable;
- missing fixings;
- missing calendars.

#### 5.4 FX Forwards & Options

Tabs:

- Pricing
- Greeks
- Smile
- Scenario
- Validation

Must consume FX market data from Market Data.

#### 5.5 Vanilla Options

Tabs:

- Pricing
- Greeks
- Scenario
- Implied Vol
- Validation

#### 5.6 Structured & Exotic Pricing

Generic structure for long-tail products.

Tabs:

- Pricing
- Path / Payoff
- Sensitivities
- Scenario
- Validation

Research-only or prototype models must show prominent governance warnings.

#### 5.7 Pricing Result Detail

Reusable result screen.

Sections:

- input summary;
- output metrics;
- sensitivities;
- scenarios;
- model metadata;
- market-data metadata;
- warnings/errors;
- audit trail.

### Navigation

Pricing landing should support:

- grouped cards;
- search;
- recent pricing;
- favorites;
- active market-data snapshot display.

Forward links:

```text
Market Data -> Pricing
Pricing result -> Add to Portfolio
Pricing result -> Scenario
Pricing result -> Model detail
Pricing result -> Export ticket
Pricing model warning -> Governance
Pricing method comparison -> Analytics Lab
```

### Actions

Primary actions:

- Price
- Reprice
- Run Scenario
- Save To Portfolio
- Export Pricing Ticket
- Open Model Detail

Input actions:

- select product;
- select market-data snapshot;
- choose model if multiple governed models exist;
- reset inputs;
- load recent trade;
- duplicate result.

Result actions:

- view clean/dirty/accrued breakdown;
- view Greeks/sensitivities;
- view cashflows;
- view scenario matrix;
- view validation notes;
- compare models where allowed.

### Widgets

KPI cards:

- Price / NPV
- Clean Price
- Dirty Price
- Accrued Interest
- Fair Rate
- Premium
- DV01
- Delta
- Vega
- Convexity

Controls:

- product selector;
- model selector;
- trade input form;
- market-data snapshot selector;
- curve selector;
- scenario selector;
- model status chip;
- warning banner.

Tables:

- Cashflows Table
- Sensitivities Table
- Scenario Matrix
- Model Limitations Table

Charts:

- payoff chart;
- price sensitivity chart;
- cashflow PV chart;
- scenario P&L chart;
- convergence chart for applicable models.

### Shortcuts

```text
Ctrl+5        Open Pricing
P             Price / reprice
S             Run scenario
A             Add result to portfolio
M             Open model detail
F             Focus pricing module search
R             Reset inputs
Ctrl+S        Save pricing result
Ctrl+E        Export ticket
Enter         Run focused form / open selected module
```

## 7. Layer 6: Governance

### Product Role

Governance owns model trust, validation, audit trail, and production gating.

Governance decides whether a model can be used in production workflows.

Governance owns:

```text
Model Registry
Validation
Audit Trail
Approvals
Model Status
Production Gating
```

### User Goals

Market Risk Manager:

- know which models are validated or blocked;
- see risk of using approximations or prototype models;
- review model warnings behind portfolio/risk numbers.

Quant Analyst:

- inspect model assumptions;
- attach validation evidence;
- promote models from research to production.

Trader:

- understand whether a price is validated, approximate, prototype, placeholder, or broken.

### Screens

#### 6.1 Governance Overview

Summary of model and calculation trust.

Sections:

- model status counts;
- blocked models;
- prototype usage;
- approximation usage;
- recent governance warnings;
- validation backlog.

#### 6.2 Model Registry

Canonical list of models.

Columns:

- model ID;
- name;
- version;
- owner;
- status;
- validation date;
- production allowed;
- analytics-lab only;
- limitations.

#### 6.3 Model Detail

Full model metadata page.

Sections:

- model identity;
- version;
- owner;
- status;
- limitations;
- documentation link;
- validation tests;
- usage history;
- dependent workflows.

#### 6.4 Validation Matrix

Validation coverage by model and workflow.

Rows:

- model;
- pricing/risk workflow;
- test coverage;
- benchmark status;
- documentation status;
- approval status.

#### 6.5 Audit Trail

Calculation and model usage history.

Records:

- calculation ID;
- timestamp;
- user/session;
- model ID;
- model status at run time;
- market-data snapshot ID;
- portfolio ID;
- warnings/errors.

#### 6.6 Approvals

Model lifecycle workflow.

States:

- Draft
- Prototype
- Approximation
- Validated
- Deprecated
- Broken
- Blocked

### Navigation

Governance landing cards:

```text
Model Registry
Validation Matrix
Audit Trail
Approvals
Production Gating
Documentation
```

Forward links:

```text
Model -> Pricing workflows using it
Model -> Risk workflows using it
Model -> Analytics experiments
Audit record -> Calculation result
Validation gap -> Test evidence
Prototype model -> Analytics Lab
Broken model -> Blocked workflows
```

### Actions

Primary actions:

- Open Model Detail
- Filter Non-Production Models
- Review Validation Gaps
- Export Model Inventory
- Export Audit Trail
- Change Model Status

Governance actions:

- approve model;
- downgrade model;
- block model;
- mark as analytics-lab only;
- attach documentation;
- attach validation evidence;
- review model usage.

### Widgets

KPI cards:

- Validated Models
- Approximation Models
- Prototype Models
- Placeholder Models
- Broken Models
- Models Used Today
- Blocked Calculations

Tables:

- Model Registry Table
- Validation Matrix
- Audit Trail Table
- Approval Queue
- Model Usage Table

Controls:

- model status filter;
- owner filter;
- workflow filter;
- production allowed toggle;
- analytics-lab only toggle;
- date range filter;
- warning banner.

Charts:

- model status distribution;
- validation coverage;
- usage by model;
- warnings over time.

### Shortcuts

```text
Ctrl+6        Open Governance
M             Open Model Registry
V             Open Validation Matrix
A             Open Audit Trail
P             Open Approvals
F             Focus governance filter
B             Filter blocked/broken models
Ctrl+E        Export governance report
Enter         Open selected model / audit record
```

## 8. Layer 7: Analytics Lab

### Product Role

Analytics Lab owns research and experimentation. It is allowed to contain prototypes, but those prototypes must not silently enter production workflows.

Analytics Lab owns:

```text
Numerical Methods
Stochastic Models
Rates Models
Experimental Monte Carlo
Research Notebooks
Benchmarking
Model Experiments
```

### User Goals

Quant Analyst:

- develop and test models;
- inspect convergence and calibration;
- compare model outputs with benchmarks;
- prepare models for governance review.

Trader:

- explore advanced analytics with clear research-only labeling;
- compare candidate models without assuming production approval.

Market Risk Manager:

- understand which research models are not approved for production workflows.

### Screens

#### 7.1 Analytics Lab Overview

Research landing page.

Groups:

```text
Numerical Methods
  Trees
  Monte Carlo

Volatility Models
  Heston / SABR
  GARCH / EWMA

Rates Models
  Short Rate Models

Experimental
  Experimental Monte Carlo
  Research Notebooks
```

#### 7.2 Numerical Methods

Method experimentation.

Tabs:

- Setup
- Convergence
- Paths / Lattice
- Greeks
- Validation

#### 7.3 Stochastic Volatility

Heston, SABR, and volatility research.

Tabs:

- Setup
- Calibration
- Surface Fit
- Scenario
- Validation

#### 7.4 Rates Models

Short-rate and rates research.

Tabs:

- Setup
- Curve Fit
- Paths
- Instrument Tests
- Validation

#### 7.5 Monte Carlo Lab

Experimental simulation environment.

Tabs:

- Setup
- Paths
- Distribution
- Convergence
- Greeks
- Validation

#### 7.6 Experiment Detail

Single experiment record.

Sections:

- inputs;
- outputs;
- random seed;
- model version;
- market-data snapshot;
- benchmark comparison;
- limitations;
- governance status.

#### 7.7 Research Notebooks

Notebook and research artifact index.

Records:

- notebook/report title;
- model family;
- owner;
- status;
- linked validation evidence;
- promotion readiness.

### Navigation

Analytics Lab landing cards:

```text
Trees
Monte Carlo Lab
Heston / SABR
GARCH / EWMA
Short Rate Models
Research Notebooks
Benchmarking
```

Forward links:

```text
Experiment -> Governance / Model Detail
Benchmark result -> Validation Matrix
Research model -> Production promotion checklist
Analytics output -> Pricing comparison, only with explicit research mode
```

Analytics Lab must never route silently into production Pricing, Portfolio, or Risk flows.

### Actions

Primary actions:

- Run Experiment
- Compare Benchmark
- Save Experiment
- Export Research Result
- Open Governance Review

Research actions:

- choose model;
- configure parameters;
- set random seed;
- run convergence test;
- calibrate model;
- compare against baseline model;
- mark promotion candidate;
- attach validation evidence.

### Widgets

KPI cards:

- Experiment Result
- Benchmark Error
- Calibration RMSE
- Convergence Error
- Runtime
- Simulation Paths
- Model Status

Tables:

- Experiment History
- Parameter Table
- Benchmark Comparison
- Calibration Results
- Validation Checklist

Charts:

- convergence chart;
- path chart;
- distribution chart;
- calibration fit;
- surface comparison;
- exercise boundary;
- benchmark error chart.

Controls:

- model family selector;
- parameter form;
- seed input;
- run control;
- benchmark selector;
- research-mode warning banner;
- governance status chip.

### Shortcuts

```text
Ctrl+7        Open Analytics Lab
R             Run experiment
C             Compare benchmark
S             Save experiment
M             Open model detail
G             Send to Governance review
F             Focus experiment search
Ctrl+E        Export research result
Enter         Open selected experiment/module
```

## 9. Cross-Layer Object Ownership

### Portfolio Owns

```text
Portfolio
Book
Position
Position validation
Portfolio valuation result
Portfolio risk-factor exposure
Scenario P&L result
P&L explain result
```

### Risk Owns

```text
VaR result
ES result
Stress result
Backtest result
Limit result
Risk contribution
Counterparty risk result
```

### Market Data Owns

```text
MarketDataSnapshot
YieldCurve
VolSurface
FX data
CreditCurve
Source metadata
Data validation result
```

### Pricing Owns

```text
Pricing request
Pricing result
Instrument valuation
Sensitivities
Cashflows
Pricing scenario result
Trade-to-position handoff
```

### Governance Owns

```text
Model registry entry
Model status
Validation evidence
Production gating
Audit event
Approval state
Model limitation
```

### Analytics Lab Owns

```text
Experiment
Research model run
Benchmark comparison
Calibration result
Research artifact
Promotion candidate
```

## 10. Cross-Layer Workflow Specifications

### Daily Risk Workflow

```text
Dashboard
-> Portfolio / Overview
-> Portfolio / Valuation
-> Risk / VaR ES
-> Risk / Stress
-> Risk / Backtesting
-> Governance / Warnings
-> Export Risk Report
```

Required shortcuts:

```text
Ctrl+1 -> Ctrl+2 -> Shift+V -> Ctrl+3 -> V -> S -> B -> Ctrl+E
```

### Trader Pricing Workflow

```text
Market Data / Snapshot
-> Pricing / Product
-> Pricing / Result
-> Pricing / Scenario
-> Portfolio / Add Position
-> Export Ticket
```

Required shortcuts:

```text
Ctrl+4 -> S -> Ctrl+5 -> P -> S -> A -> Ctrl+E
```

### Quant Validation Workflow

```text
Analytics Lab / Experiment
-> Analytics Lab / Benchmark
-> Governance / Model Detail
-> Governance / Validation Matrix
-> Pricing or Risk comparison
```

Required shortcuts:

```text
Ctrl+7 -> R -> C -> G -> Ctrl+6 -> V
```

## 11. Implementation Notes

### IA Migration Priorities

1. Add global context bar.
2. Promote Governance to a first-class layer.
3. Reorder navigation to:

```text
Dashboard
Portfolio
Risk
Market Data
Pricing
Governance
Analytics Lab
```

4. Convert Market Data from tab widget to landing workspace.
5. Group Pricing modules.
6. Remove generic Portfolio from Risk.
7. Add Portfolio tabs around positions, exposure, risk, scenario P&L, attribution, and validation.
8. Standardize result metadata and warning panels.
9. Add cross-layer workflow actions:
   - Price -> Add to Portfolio;
   - Portfolio -> Run Risk;
   - Risk -> Governance;
   - Analytics Lab -> Governance.

### Do Not Do Yet

Do not start visual redesign before these IA changes are in place.

Do not add new visual complexity to compensate for missing architecture.

Do not expose research models in production workflows without explicit Analytics Lab mode.

Do not keep FX option pricing inside Market Data.

Do not keep XVA as a generic Pricing card.

## 12. Success Criteria

The ideal IA is achieved when:

- A Market Risk Manager can complete daily risk workflow from Dashboard to report without opening raw pricing modules.
- A Trader can price, run scenario, save to portfolio, and export a ticket using a consistent market-data snapshot.
- A Quant Analyst can run experiments and send evidence to Governance without research models entering production silently.
- Every production result shows model status, market-data snapshot, valuation date, warnings, and calculation timestamp.
- Portfolio is the default object for production risk workflows.
- Market Data owns data, Pricing owns valuation, Risk owns measurement, Governance owns trust, and Analytics Lab owns research.
