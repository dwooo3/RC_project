# RiskCalc UI/UX Redesign Specification

Date: 2026-06-03
Repository: `dwooo3/RC_project`
Purpose: detailed UI/UX redesign instruction based on the actual current workspace code.

This file is a practical implementation brief for another AI agent or developer. It should be used together with `AUDIT.md`.

---

## 0. Target Product Vision

RiskCalc must not look like a collection of PySide calculators.

Target product feel:

```text
Bloomberg Next Generation + ChatGPT Desktop + Linear + Apple Quant
```

The application should feel like a unified market risk and pricing terminal:

1. Clean shell.
2. Workflow-oriented navigation.
3. Large readable KPIs.
4. Minimal borders.
5. Strong hierarchy.
6. Context-aware model validation.
7. Clear distinction between production-ready, approximation, prototype and placeholder models.

The orange accent must remain.

---

## 1. Current UI State — Summary

The current application has already moved from a 30+ item sidebar to a better 7-section structure:

```text
Dashboard
Market
Pricing
Portfolio
Risk
Analytics
Settings
```

This structure is correct and should be preserved.

However, the actual workspaces still have issues:

1. Dashboard still contains too much technical model validation content.
2. Pricing landing page has too many module cards.
3. Risk workspace duplicates Portfolio and XVA logic from other sections.
4. Market workspace is just a plain tab widget without a landing overview.
5. Portfolio screen still uses an old split-panel calculator layout.
6. Analytics workspace is closer to the target but still lacks standardized module pages.
7. The same card and workspace code is duplicated across Pricing, Risk and Analytics.
8. Too many borders and separators remain.
9. No unified context panel exists.
10. No unified module header exists.

---

## 2. Global Navigation Rules

### Keep top-level sidebar exactly as:

```text
Dashboard
Market
Pricing
Portfolio
Risk
Analytics
Settings
```

Do not add individual instruments to the left sidebar.

### Sidebar behavior

- Sidebar should be persistent.
- Workspace should change on click.
- Do not open separate windows for normal workflows.
- Use lazy loading of panels.
- Active sidebar item should have subtle orange accent.
- Remove placeholder square icons.

### Recommended sidebar layout

```text
RiskCalc
Pricing & Risk Engine

Dashboard
Market
Pricing
Portfolio
Risk
Analytics
Settings

Demo market data · v1.0
```

---

## 3. Design System

Create these files:

```text
app/ui/theme.py
app/ui/components.py
app/ui/layouts.py
```

Do not hardcode colors independently in every panel.

### 3.1 Theme tokens

Dark theme:

```python
DARK = {
    "bg_root": "#0D0D0D",
    "bg_sidebar": "#171717",
    "bg_panel": "#141416",
    "bg_card": "#202020",
    "bg_card_hover": "#242428",
    "border": "#2A2A2A",
    "border_soft": "#222222",
    "text_primary": "#F5F5F5",
    "text_secondary": "#A0A0A8",
    "text_muted": "#606068",
    "accent": "#D97757",
    "accent_bg": "#2A1F19",
    "green": "#30D158",
    "red": "#FF453A",
    "amber": "#FFD60A",
}
```

Light theme:

```python
LIGHT = {
    "bg_root": "#FAFAFA",
    "bg_sidebar": "#FFFFFF",
    "bg_panel": "#F5F5F5",
    "bg_card": "#FFFFFF",
    "bg_card_hover": "#F1F1F1",
    "border": "#E5E5E5",
    "border_soft": "#EEEEEE",
    "text_primary": "#111111",
    "text_secondary": "#555555",
    "text_muted": "#888888",
    "accent": "#D97757",
    "accent_bg": "#FFF1EA",
    "green": "#248A3D",
    "red": "#D70015",
    "amber": "#B25000",
}
```

### 3.2 Typography

Use consistent sizes:

```text
Application title:      22-24px, 700
Workspace title:        26-30px, 700
Section title:          10-11px, uppercase, letter spacing
Card title:             13-15px, 600
KPI value:              28-40px, 700
KPI label:              10-11px, uppercase
Body text:              13px
Secondary text:         11-12px
Table text:             12px
```

### 3.3 Border discipline

Current design has too many visible lines.

Rules:

1. One card = one border maximum.
2. Avoid borders around every internal group.
3. Prefer whitespace over separators.
4. Use separators only between major zones.
5. Avoid nested `QFrame` borders.
6. Tables may have row separation but should not look like Excel 2005.

### 3.4 Standard components

Create reusable components:

```text
SectionHeader
KpiCard
WorkspaceCard
StatusChip
ModelStatusChip
WarningBanner
ContextPanel
MetricGrid
ModernTable
TabHeader
BreadcrumbBar
```

Current code duplicates `_ModuleCard` in Pricing, Risk and Analytics. Replace this duplication with one `WorkspaceCard` component.

---

## 4. Standard Workspace Layout

Every workspace should follow this pattern.

```text
Workspace Header
  Title
  Subtitle
  Right-side chips: Data source, valuation date, model status if applicable

Workspace Body
  Landing card grid OR active module page

Module Page
  Breadcrumb row
  Header row with model status
  Left: Inputs
  Center: Results / charts
  Right: Context panel
  Bottom: Internal tabs
```

### Required module page skeleton

```text
[Back] Pricing > Bond Pricing                         [Status: Approximation]

┌ Inputs ───────────────┐  ┌ Results ───────────────┐  ┌ Context ─────────────┐
│ Instrument             │  │ Clean Price             │  │ Data source           │
│ Dates                  │  │ Dirty Price             │  │ Curve                 │
│ Coupon                 │  │ YTM                     │  │ Conventions           │
│ Curve                  │  │ DV01                    │  │ Validation notes      │
└───────────────────────┘  └───────────────────────┘  └──────────────────────┘

Tabs:
Pricing | Cashflows | Sensitivities | Scenario | Validation
```

---

## 5. Dashboard Redesign

### Current issue

Dashboard currently includes:

- KPI row;
- Quick Access;
- compact model validation status.

The validation status block must be removed from the dashboard. Full validation belongs in:

```text
Risk -> Model Validation
```

### Target Dashboard

```text
Header
  RiskCalc
  Market Risk & Pricing Engine
  [Demo Data] [MOEX ISS Pending] [Theme Toggle]

Top KPI row
  Portfolio MV
  Daily P&L
  VaR 95%
  ES 95%
  DV01
  Vega

Main grid
  P&L chart
  Exposure by asset class
  Yield curve snapshot
  Vol surface snapshot

Recent Work
  Last opened modules / last calculations

System Status
  Market data
  Yield curves
  Vol surface
  Model validation summary
```

### Important rule

The dashboard should show only summary validation counts, not a full table.

Example:

```text
Models: 0 validated · 18 approximations · 9 prototypes · 2 placeholders
```

Clicking this chip opens:

```text
Risk -> Model Validation
```

---

## 6. Market Workspace Redesign

### Current state

`MarketWorkspace` is currently just a `QTabWidget` with:

```text
Yield Curves
Vol Surface
Implied Vol
FX Forward & Options
```

This is too flat and inconsistent with Pricing/Risk/Analytics.

### Target structure

Market should have a landing page with cards:

```text
Yield Curves
Vol Surface
FX Market
Credit Curves
Market Data Monitor
```

### Required Market modules

#### Yield Curves

Internal tabs:

```text
Overview
Curve Builder
Zero / Par / Forward
Scenario
Validation
```

Main KPIs:

```text
1Y rate
5Y rate
10Y rate
Curve slope 10Y-2Y
Curve source
Valuation date
```

#### Vol Surface

Internal tabs:

```text
Surface
Smile
Term Structure
Calibration
Validation
```

Main KPIs:

```text
ATM vol
25D risk reversal
25D butterfly
Surface date
Calibration RMSE
```

#### FX Market

Do not expose this as `FX Forward & Options` inside Market. Market should contain market data only.

Internal tabs:

```text
Spot
Forward Points
FX Curves
Vols
Validation
```

FX option pricing belongs in Pricing.

---

## 7. Pricing Workspace Redesign

### Current state

`PricingWorkspace` has 17 module cards:

```text
Vanilla Options
Bond Pricing
IRS / OIS
Cap / Floor / Swptn
FX Forward & Options
Barrier Options
Asian Options
Digital / Touch
Lookback Options
Multi-Asset
Variance Swaps
Credit / CDS
XVA
Structured Products
Futures & Forwards
IR Derivatives
Commodity Deriv.
```

This is too much for one landing page and mixes core, exotic, XVA, analytics and market modules.

### Target hierarchy

Pricing landing page should have grouped sections, not one flat grid.

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

Experimental
  Commodity Derivatives
```

### Remove from Pricing landing

Move XVA out of Pricing. XVA should live under Risk.

Move IR Derivatives into Rates & Credit, but avoid duplicate card if Cap/Floor/Swaption already exists.

### Required landing page layout

```text
Pricing
Price instruments using validated and prototype models

[Search modules...]

Core Pricing
  [Bond Pricing] [IRS / OIS] [FX Options] [Vanilla Options]

Rates & Credit
  [Cap/Floor/Swaption] [Credit/CDS] [Futures & Forwards]

Structured & Exotic
  [Barrier] [Asian] [Digital] [Lookback] [Multi-Asset] [Variance Swap] [Structured]
```

### Module card rules

Each card must show:

```text
Module Name
Short description
Status chip
Primary model
```

Example:

```text
Bond Pricing                         [Approximation]
Fixed-rate bonds, clean/dirty, DV01
Model: Fixed Bond
```

---

## 8. Bond Module Detailed Design

Bond is the most important Pricing module to redesign first.

### Internal tabs

```text
Pricing
Cashflows
Sensitivities
Scenario
Validation
```

### Pricing tab

Layout:

```text
Left Inputs
  Instrument
  Face value
  Coupon
  Frequency
  Maturity date / T
  Settlement date
  Curve
  Clean / Dirty mode

Center Results
  Clean Price
  Dirty Price
  Accrued Interest
  YTM
  Z-spread
  Modified Duration
  DV01
  Convexity

Right Context
  Curve source
  Valuation date
  Day count
  Compounding
  Model status
  Known limitations
```

### Cashflows tab

Show table:

```text
Payment Date | Year Fraction | Coupon | Principal | Discount Factor | PV
```

### Sensitivities tab

Show:

```text
DV01 by tenor
Parallel DV01
Key-rate DV01
Duration
Convexity
```

### Scenario tab

Show curve shocks:

```text
-200bp
-100bp
-50bp
+50bp
+100bp
+200bp
Steepener
Flattener
```

### Validation tab

Show:

```text
Model status
Tests passed / missing
Known limitations
Required production fixes
```

---

## 9. IRS / OIS Module Detailed Design

### Internal tabs

```text
Pricing
Cashflows
Sensitivities
Curve Risk
Validation
```

### Pricing tab

Inputs:

```text
Notional
Pay / Receive fixed
Fixed rate
Start date
Maturity date
Fixed leg frequency
Float leg frequency
Discount curve
Projection curve
```

Results:

```text
NPV
Fair swap rate
Fixed leg PV
Floating leg PV
Annuity
DV01
```

Context:

```text
Single-curve or dual-curve
Curve sources
Day count
Fixing lag
Model status
```

### Critical UX rule

If model remains single-curve, UI must show a warning:

```text
Approximation: single-curve IRS. No OIS discounting / projection curve split.
```

---

## 10. FX Options Module Design

Do not combine FX market data and FX option pricing in one unclear screen.

### Internal tabs

```text
Pricing
Greeks
Smile
Scenario
Validation
```

### Pricing inputs

```text
Spot
Strike
Domestic rate
Foreign rate
Volatility
Maturity
Option type
Notional
```

### Results

```text
Premium
Delta spot
Delta forward
Gamma
Vega
Theta
Rho domestic
Rho foreign
```

### Context

```text
Currency pair
Premium currency
Vol source
Smile status
Model: Garman-Kohlhagen
```

---

## 11. Risk Workspace Redesign

### Current state

Risk workspace has these cards:

```text
VaR & CVaR
Historical VaR
Stress Testing
Greeks Ladder
P&L Attribution
XVA
Portfolio
```

This overlaps with Portfolio and Pricing.

### Target Risk sections

```text
Market Risk
  VaR / ES
  Stress Testing
  Backtesting

Risk Explain
  Greeks Ladder
  P&L Attribution

Counterparty Risk
  XVA

Governance
  Model Validation
```

### Remove from Risk landing

Remove generic `Portfolio` card from Risk. Portfolio has its own top-level section.

### Add to Risk landing

Add `Model Validation` card.

### VaR module internal tabs

```text
Overview
Historical
Parametric
Monte Carlo
EVT
Backtesting
Validation
```

### VaR overview KPIs

```text
VaR 95%
VaR 99%
ES 95%
ES 99%
Exceptions
Backtest zone
Observation count
Horizon
```

### UX rule

If VaR is generated from synthetic/demo returns, show a red or amber warning:

```text
Demo calculation: generated returns, not real P&L history.
```

---

## 12. Portfolio Workspace Redesign

### Current state

Portfolio currently uses an old left-input/right-results split layout. It has a modal `Add Position` dialog and aggregates mixed Greeks directly.

### Target structure

Portfolio should be its own workspace with internal tabs:

```text
Positions
Exposure
Risk
Scenario P&L
Attribution
Validation
```

### Main Portfolio screen

Top KPI row:

```text
Market Value
Daily P&L
Positions
DV01
Vega
Delta
```

Main area:

```text
Positions table
Exposure chart
Risk factor exposure table
```

### Position management

Avoid modal-only workflow. Provide inline position editor or right-side drawer.

Position drawer:

```text
Instrument
Description
Quantity
Currency
Book
Pricing parameters
Validation status
```

### Important UX rule

Do not show raw aggregate Delta/Gamma/Vega across asset classes as if they are directly comparable.

Instead show:

```text
Risk factor exposures
  Equity spot delta
  FX spot delta
  Rate DV01
  Credit CS01
  Vol Vega
```

---

## 13. Analytics Workspace Redesign

### Current state

Analytics has a landing page with cards:

```text
Binomial Trees
Monte Carlo Lab
Heston / SABR
Short Rate Models
Real Options
GARCH / EWMA
```

This is close to target.

### Target structure

Keep Analytics as Model Lab.

Group modules:

```text
Numerical Methods
  Trees
  Monte Carlo

Volatility Models
  Heston / SABR
  GARCH / EWMA

Rates Models
  Short Rate Models

Corporate Finance
  Real Options
```

### Each Analytics module must show

```text
Model assumptions
Inputs
Outputs
Benchmark comparison
Validation status
Known limitations
```

### Monte Carlo Lab tabs

```text
Setup
Paths
Convergence
Greeks
Validation
```

### Tree Models tabs

```text
Pricing
Convergence
Exercise Boundary
Greeks
Validation
```

---

## 14. Settings Workspace

Settings should include:

```text
Appearance
Data Sources
Model Governance
Defaults
About
```

### Appearance

```text
Theme: Dark / Light
Accent: Orange fixed
Density: Comfortable / Compact
```

### Data Sources

```text
Manual
CSV
MOEX ISS pending
Yahoo pending
```

### Model Governance

```text
Allow prototype models: Yes/No
Show validation warnings: Yes/No
Block broken models: Yes/No
```

---

## 15. Model Validation UI

Create a dedicated screen:

```text
Risk -> Model Validation
```

### Layout

Top KPI cards:

```text
Validated
Approximations
Prototypes
Placeholders
Broken
```

Table:

```text
Model | Domain | Status | Production Allowed | Tests | Notes | Module Path
```

Filters:

```text
All
Production allowed
Needs validation
Broken / Placeholder
```

Clicking a model opens right-side details panel.

---

## 16. Tables

### Current problem

Tables are dense and visually old.

### Target table rules

- Use muted header.
- Avoid vertical grid lines.
- Use alternating row background very subtly.
- Use right alignment for numbers.
- Use status chips instead of raw text where applicable.
- Use `—` for missing values.
- Do not show huge precision by default.

### Numeric formatting

```text
Price:          2 decimals
Rates:          2-4 decimals or percent
DV01/CS01:      2 decimals
Greeks:         4 decimals
Large money:    compact notation, e.g. 125.4m
```

---

## 17. Charts

### Required charts by workspace

Dashboard:

```text
P&L trend
Exposure allocation
Yield curve mini-chart
Vol surface mini-chart
```

Market:

```text
Zero curve
Forward curve
Vol smile
Vol term structure
```

Pricing:

```text
Cashflow PV profile
Scenario P&L
Sensitivity ladder
```

Portfolio:

```text
Exposure by factor
P&L attribution
Risk contribution
```

Risk:

```text
P&L distribution
VaR threshold
Exceptions over time
Stress scenario waterfall
```

Analytics:

```text
MC convergence
Path sample
Tree convergence
Vol forecast
```

---

## 18. Error and Warning UX

### Required banners

Use consistent banners:

```text
Info
Warning
Error
Success
```

Examples:

```text
Warning: This model is marked Prototype. Do not use for production pricing.
Warning: Market data is demo/manual. No valuation date source is attached.
Error: Correlation matrix is not positive definite.
Error: Pricing failed for 3 positions.
```

### Do not silently swallow exceptions

Current workspace factories catch exceptions and return `None`. Instead:

1. Log the exception.
2. Show a fallback error panel.
3. Include module name and traceback in debug mode.

---

## 19. Current Workspace-Specific Issues

### Pricing Workspace

Issues:

1. Too many cards in a flat list.
2. XVA belongs to Risk, not Pricing.
3. Commodity derivatives are placeholder-like and should be under Experimental.
4. Duplicate concept: `Cap/Floor/Swptn` and `IR Derivatives` overlap.
5. No search/filter.
6. No grouping.
7. No module detail preview.

Required changes:

1. Group cards.
2. Add search.
3. Add model status and production gate.
4. Add primary/secondary modules.
5. Move XVA out.

### Market Workspace

Issues:

1. Just a plain tab widget.
2. FX pricing module appears inside Market.
3. No market data status.
4. No valuation date.
5. No source indicators.

Required changes:

1. Convert to landing page.
2. Separate FX market data from FX pricing.
3. Add Market Data Monitor.
4. Add valuation date/source chips.

### Risk Workspace

Issues:

1. Portfolio appears inside Risk despite being top-level.
2. No Model Validation card.
3. VaR and Historical VaR are separate cards but should be one VaR workspace with internal tabs.
4. XVA is correctly risk-related but also appears in Pricing. Remove duplication.

Required changes:

1. Consolidate VaR modules.
2. Add Backtesting and Model Validation as first-class modules.
3. Remove Portfolio card.
4. Keep XVA only in Risk.

### Portfolio Panel

Issues:

1. Old split layout.
2. Add position only via modal.
3. Mixed Greeks aggregation.
4. Chart scales Greeks artificially (`Gamma ×100`, `Theta ×10`, `DV01 ×100`). This is visually misleading.
5. Positions table is cramped.

Required changes:

1. Convert to full workspace with internal tabs.
2. Use right-side position drawer.
3. Replace mixed Greeks chart with risk factor exposure chart.
4. Add pricing error/status per position.
5. Add currency and book filters.

### Analytics Workspace

Issues:

1. Mostly good structure.
2. Needs grouping.
3. Real Options is placeholder but not clearly marked.
4. No standardized module layout.

Required changes:

1. Group into Numerical Methods, Volatility Models, Rates Models, Corporate Finance.
2. Add validation warnings.
3. Add benchmarking panels.

---

## 20. Implementation Plan

### Phase 1 — Shared UI foundation

Create:

```text
app/ui/theme.py
app/ui/components.py
app/ui/layouts.py
```

Move colors out of panels.

### Phase 2 — Dashboard

1. Remove full validation table.
2. Add compact validation chip.
3. Add Recent Work.
4. Add Market Data Status.

### Phase 3 — Workspace landing pages

Refactor:

```text
PricingWorkspace
RiskWorkspace
AnalyticsWorkspace
MarketWorkspace
```

Use shared `WorkspaceLanding` and `WorkspaceCard`.

### Phase 4 — Portfolio redesign

Convert `PortfolioPanel` to:

```text
PortfolioWorkspace
  Positions
  Exposure
  Risk
  Scenario P&L
  Attribution
  Validation
```

### Phase 5 — Core pricing screens

Redesign first:

```text
BondPanel
IRSPanel
FXPanel
OptionPanel
VarPanel
```

### Phase 6 — Model Validation screen

Create:

```text
app/panels/model_validation_panel.py
```

Add it under Risk workspace.

### Phase 7 — Light theme

Ensure every component uses theme tokens.

---

## 21. Acceptance Criteria

The redesign is acceptable when:

1. Sidebar has only 7 sections.
2. Dashboard has no full model registry table.
3. Pricing cards are grouped and searchable.
4. Market is no longer just a plain tab widget.
5. Risk contains Model Validation.
6. Portfolio no longer shows misleading mixed-Greeks chart.
7. All module screens use consistent header, input, result, context and internal tabs.
8. No panel hardcodes its own colors outside theme tokens.
9. Prototype/Placeholder models show visible warnings.
10. Light and dark themes both work.

---

## 22. Final Design Direction

Do not chase decorative UI first.

The visual improvement will come from:

1. Stronger hierarchy.
2. Fewer borders.
3. Better workspace structure.
4. Larger KPIs.
5. Clear context panels.
6. Proper internal tabs.
7. Consistent components.

The final UI should look calm, modern and institutional, not flashy.

Target phrase:

```text
Professional risk terminal with Apple-level clarity and Bloomberg-level structure.
```
