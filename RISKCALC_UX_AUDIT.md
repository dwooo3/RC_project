# RiskCalc UX Audit

Date: 2026-06-04

Reference documents:

- `PRODUCT_ARCHITECTURE.md`
- `UI_REDESIGN.md`
- `PRODUCT_READINESS_AUDIT.md`

Current code references:

- `app/main_window.py`
- `app/panels/dashboard_panel.py`
- `app/panels/market_workspace.py`
- `app/panels/pricing_workspace.py`
- `app/panels/portfolio_panel.py`
- `app/panels/risk_workspace.py`
- `app/panels/analytics_workspace.py`
- `ui/components.py`
- `ui/theme.py`
- `services/pricing_service.py`
- `services/risk_service.py`
- `services/portfolio_service.py`
- `services/market_data_service.py`
- `services/governance_service.py`

Target users:

- Market Risk Manager
- Quant Analyst
- Trader

Scope:

- This is a workflow and product-UX audit.
- This is not a visual redesign.
- This audit focuses on information architecture, navigation, task completion, workstation efficiency, and fit against the target architecture in `PRODUCT_ARCHITECTURE.md`.

External benchmark references:

- Bloomberg Portfolio Analytics: https://www.bloomberg.com/professional/products/bloomberg-terminal/portfolio-analytics/
- Bloomberg MAC3 risk factor framework: https://www.bloomberg.com/professional/products/risk/mac3/
- Nasdaq Calypso solutions: https://www.nasdaq.com/solutions/fintech/nasdaq-calypso
- Numerix Oneview for Market Risk: https://www.numerix.com/oneview-market-risk

## Executive Summary

RiskCalc has the right strategic direction: it is moving from a calculator collection toward a market-risk and pricing workstation. The top-level navigation now matches most of the target product layers:

```text
Dashboard
Market
Pricing
Portfolio
Risk
Analytics
Settings
```

This is directionally correct, but the product is not yet workflow-efficient for a Market Risk Manager, Quant Analyst, or Trader. The main UX issue is not aesthetic. The main issue is that the UI still exposes implementation modules instead of complete business workflows.

Current UX maturity:

```text
Advanced Prototype UI shell
```

Not yet:

```text
Professional risk workstation
```

The strongest parts are:

- top-level product sections exist;
- lazy-loaded workspaces exist;
- Pricing, Risk, and Analytics have landing-card navigation;
- selected high-value panels have started to route through services;
- warnings and governance metadata are beginning to surface in workflows;
- a shared UI foundation exists under `ui/`.

The weakest parts are:

- Market is still a plain tab widget, not a market-data control center;
- Portfolio is not yet experienced as the center of the product;
- Risk still duplicates Portfolio and does not lead with portfolio VaR, stress, backtesting, and limits;
- Pricing is a flat catalog of instruments, not a grouped trader workflow;
- Governance is not a first-class navigation area;
- many panels still call engines directly, which creates inconsistent warnings, model status, and market-data context;
- there is no persistent workspace context: portfolio, valuation date, market-data snapshot, selected curve, model status, and calculation state are not consistently visible across screens.

Product classification from a UX standpoint:

```text
Advanced Prototype
```

RiskCalc is not a Prototype anymore because the shell, workspaces, services, model governance, portfolio objects, market-data snapshots, and workflow concepts exist. It is not yet a Professional Workstation because daily workflows still require too much manual navigation, too much mental stitching, and too much awareness of internal models.

## 1. Information Architecture Review

### Target Information Architecture

`PRODUCT_ARCHITECTURE.md` defines RiskCalc as a workflow-first market risk terminal. The user should think in this order:

```text
Load positions
Check market data
Value portfolio
Explain P&L
Compute VaR
Run stress
Review model status
Export report
```

The target product layers are:

```text
Dashboard
Market Data
Pricing
Portfolio
Risk
Model Governance
Analytics Lab
```

### Current Information Architecture

Current top-level navigation in `app/main_window.py`:

```text
Dashboard
Market
Pricing
Portfolio
Risk
Analytics
Settings
```

Assessment:

- The top-level structure is mostly correct.
- The missing top-level concept is Governance.
- Settings is present, but Governance is more important for the target product than generic Settings.
- Current Pricing and Risk still expose modules more than workflows.
- Market does not yet communicate ownership of market-data snapshots.
- Portfolio exists as a section, but it is not yet the central starting point for risk workflows.

### Good IA Decisions

- Individual instruments are not in the global sidebar.
- Dashboard, Market, Pricing, Portfolio, Risk, Analytics, and Settings are stable top-level sections.
- Pricing and Risk use landing cards instead of a 30-item sidebar.
- Analytics is separated from production pricing/risk conceptually.

### IA Gaps

#### Governance Is Hidden

`PRODUCT_ARCHITECTURE.md` says Governance owns:

```text
Model Registry
Validation
Audit Trail
Model Status
Production Gating
```

Current navigation does not expose Governance as a first-class section. This is a major gap for:

- Market Risk Manager: needs to see model production readiness quickly.
- Quant Analyst: needs model validation and assumptions.
- Trader: needs to know whether a price is validated, approximate, prototype, or blocked.

#### Market Data Is Too Flat

`app/panels/market_workspace.py` currently opens a `QTabWidget` with:

```text
Yield Curves
Vol Surface
Implied Vol
FX Forward & Options
```

This creates three issues:

- no landing overview;
- no data status monitor;
- FX option pricing appears inside Market through `FX Forward & Options`, violating the target distinction between market data and pricing.

#### Pricing Is Too Instrument-Catalog Driven

`app/panels/pricing_workspace.py` currently exposes 17 pricing modules in one grid:

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

This is useful for discovery but inefficient for repeat professional workflows. Traders usually need:

- core products first;
- recent modules;
- linked market data;
- model status;
- scenario and save-to-portfolio actions.

#### Risk Contains Portfolio Duplication

`app/panels/risk_workspace.py` includes:

```text
VaR & CVaR
Historical VaR
Stress Testing
Greeks Ladder
P&L Attribution
XVA
Portfolio
```

The generic Portfolio card should not live inside Risk. Risk should consume Portfolio, not duplicate it as a module.

#### Dashboard Is Not Yet a Control Tower

The target dashboard should summarize:

```text
Portfolio Summary
Market Summary
Risk Summary
Model Summary
System Status
```

Current dashboard still depends on direct registry concepts and is not clearly a daily operating console for risk or trading. It should not become a dense model-validation screen; it should show actionable status and route users into workflows.

## 2. Navigation Review

### Current Navigation Strengths

`app/main_window.py` provides:

- persistent left sidebar;
- lazy-loaded sections;
- clear seven-section product shell;
- keyboard shortcuts `Ctrl+1` through `Ctrl+7`;
- status bar with section and data status;
- stable app title and subtitle.

These are good workstation foundations.

### Navigation Weaknesses

#### Placeholder Icons

The sidebar still uses placeholder square icons in `NAV_ITEMS`, although buttons display only text. This is low-risk, but it reflects unfinished navigation semantics.

#### Governance Is Missing From Main Navigation

Model governance is a product layer, not a setting. It should eventually become:

```text
Governance
```

or a clearly visible workspace under Risk with strong cross-links from every calculation result.

#### Module Return Path Is Local Only

Pricing and Risk module wrappers provide a back button:

```text
← Pricing
← Risk
```

This is fine for simple navigation, but professional workflows need task-chain navigation:

```text
Pricing result -> Add to Portfolio
Portfolio -> Run VaR
Risk result -> Stress
Stress -> Export report
Result -> Model details
```

Current navigation mostly returns to landing pages rather than moving forward through the workflow.

#### Market Uses Tabs Instead Of Workspace Navigation

Market has tabs with no overview and no clear state transfer into pricing. A user cannot easily answer:

- Which curve am I using?
- Is the curve validated?
- Which snapshot is active?
- Is the FX rate manual, demo, CSV, or external?
- Which pricing screens are consuming this snapshot?

#### Analytics And Production Are Still Visually Similar

The architecture separates Analytics Lab from production workflows, but the UI does not strongly signal that a panel is research-only. Users can still experience research models as just another module card unless governance status is consistently shown and enforced.

### Navigation Recommendations

1. Keep the seven-section sidebar until service migration is stable.
2. Add Governance as an eighth section after core workflows are service-only.
3. Add a persistent workspace context strip:

```text
Portfolio: Main Portfolio
Valuation date: 2026-06-04
Market data: DEMO / snapshot id
Model mode: Demo / Production
Warnings: count
```

4. Add workflow transitions:

```text
Price -> Add to Portfolio
Portfolio -> Run Risk
Risk -> Run Stress
Stress -> P&L Explain
Any result -> Model details
Any result -> Export
```

5. Move Market from tab-only to landing overview with market-data status cards.

## 3. Workflow Review

## 3.1 Market Risk Manager Workflow

Target workflow:

```text
Dashboard
Portfolio
Risk
Stress
Backtesting
Report
```

### Current Fit

Current RiskCalc supports pieces of this workflow:

- Portfolio section exists.
- Risk section exists.
- VaR panels exist.
- Stress panel exists.
- P&L Attribution panel exists.
- PortfolioService has scenario and risk-factor concepts.

### Current Breaks

The Market Risk Manager still cannot complete a professional daily workflow efficiently:

1. There is no obvious daily checklist.
2. Portfolio loading and portfolio validation are immature.
3. VaR is still presented as method modules, not portfolio risk.
4. Backtesting is not prominent enough.
5. Limit monitoring is absent.
6. Reporting/export is absent.
7. Model status is not consistently attached to every result in the UI.
8. Market-data snapshot status is not consistently visible.

### Risk Manager UX Assessment

```text
Current state: usable demonstration workflow
Target state: daily risk control workflow
Gap: high
```

### Recommended Risk Manager Workflow

```text
Dashboard
  Today status
  Portfolio MV
  P&L
  VaR/ES
  Stress worst loss
  Data/model warnings

Portfolio
  Positions
  Exposure
  Scenario P&L
  Attribution

Risk
  VaR / ES
  Stress
  Backtesting
  Limits

Governance
  Model warnings
  Audit trail
```

## 3.2 Quant Analyst Workflow

Target workflow:

```text
Market Data
Pricing
Analytics Lab
Model Governance
```

### Current Fit

RiskCalc is relatively strong for Quant Analysts because it has:

- many pricing models;
- multiple risk models;
- Analytics workspace;
- model registry;
- governance status metadata;
- tests and audits.

### Current Breaks

1. Analytics Lab is not physically and visually separated enough from production.
2. Model comparison and benchmark workflows are not first-class.
3. Validation evidence is not visible in the UI.
4. Research outputs do not have experiment metadata.
5. Calibration workflows are not cohesive.
6. Model limitations appear inconsistently.

### Quant Analyst UX Assessment

```text
Current state: strong research sandbox
Target state: governed model lab and validation workstation
Gap: medium
```

### Recommended Quant Workflow

```text
Analytics Lab
  Select model family
  Run experiment
  Compare benchmark
  Inspect convergence
  Save experiment metadata

Governance
  Review model status
  Link validation evidence
  Promote or keep research-only

Pricing/Risk
  Consume only approved service paths
```

## 3.3 Trader Workflow

Target workflow:

```text
Market
Pricing
Scenario
Export / Save
```

### Current Fit

Current Pricing is discoverable and includes many products. Bond, VaR, historical VaR, and stress panels have begun to surface service warnings.

### Current Breaks

1. Pricing landing is too broad and flat.
2. Market data is not selected and locked before pricing.
3. Pricing modules do not consistently show:
   - active curve;
   - valuation date;
   - data source;
   - model status;
   - known limitations;
   - save-to-portfolio action.
4. FX options appear both as market and pricing concepts.
5. Scenario analysis is not consistently part of every pricing module.
6. Pricing result history is absent.

### Trader UX Assessment

```text
Current state: multi-product calculator suite
Target state: pricing ticket and scenario workstation
Gap: high
```

### Recommended Trader Workflow

```text
Market
  Confirm snapshot
  Select curve / vol / FX source

Pricing
  Choose product group
  Enter trade terms
  Price
  Review sensitivities
  Run scenarios
  Save to Portfolio
  Export ticket
```

## 4. Desktop Workstation Review

### Workstation Strengths

RiskCalc has several desktop-workstation qualities:

- persistent navigation;
- dense PySide layout;
- lazy-loaded panels;
- keyboard shortcuts;
- tabular data views;
- chart widgets;
- service warnings in migrated panels;
- compact result grids.

These are appropriate for professional users. A market-risk workstation should be dense, not a marketing site.

### Workstation Weaknesses

#### No Global Context

Professional users need to know, at all times:

```text
Portfolio
Book
Valuation date
Market-data snapshot
Source
Model mode
Warnings
Calculation timestamp
```

Current status bar only says:

```text
Data: Demo / Manual · MOEX ISS: pending
```

That is not enough for reproducible risk work.

#### No Multi-Panel Workflow Memory

The app does not preserve visible task context across modules. Example:

```text
Yield curve selected in Market
-> Bond pricing should use it
-> Result should save to Portfolio
-> Portfolio should run scenario
```

Currently these steps are fragmented.

#### Too Many Calculator Forms

Many panels still act as isolated calculator forms. This slows traders and risk managers because they must re-enter assumptions and infer whether calculations are using the same data.

#### Limited Result Auditability

Professional users need calculation IDs, timestamps, inputs, model version, market-data snapshot ID, and warnings. The service layer is moving there, but the UI does not yet expose this consistently.

#### No Workspace Search Or Command Access

Bloomberg-style users are trained to jump quickly. RiskCalc does not need Bloomberg commands, but it should eventually support fast module search:

```text
Bond
VaR
Stress
Curve
Model Registry
```

### Desktop Workstation Recommendations

1. Add global context strip before visual redesign.
2. Add consistent result metadata block to service-backed panels.
3. Add workspace search / quick switcher.
4. Add recent calculations.
5. Add save-to-portfolio and export actions.
6. Add model details link from every warning/status chip.
7. Add keyboard shortcuts for calculate, reset, export, and module search.

## 5. Bloomberg Comparison

Bloomberg is a broad market data and analytics terminal. Its strength is not only screens; it is the speed of moving between market data, security analytics, portfolio analytics, risk factors, news, charts, and export workflows. Bloomberg's portfolio analytics and multi-asset risk tools emphasize portfolio reporting, attribution, risk decomposition, and factor-based views.

### Where RiskCalc Is Directionally Similar

- Persistent workstation shell.
- Market, pricing, portfolio, and risk concepts.
- Dense analytics-oriented screens.
- Model status and calculation transparency can become a differentiator.
- Risk factor architecture is emerging.

### Where RiskCalc Should Not Copy Bloomberg

- Do not attempt broad market-data coverage.
- Do not implement command-code complexity too early.
- Do not become a news/security master terminal.
- Do not optimize for breadth before workflow reliability.

### Bloomberg Gap

RiskCalc currently lacks:

- fast cross-screen search;
- integrated market data context;
- portfolio risk decomposition as a default view;
- historical data depth;
- reporting/export workflow;
- persistent result history;
- real-time or near-real-time data state.

### Practical Lesson For RiskCalc

RiskCalc should borrow the idea of fast task switching and always-visible data context, not Bloomberg's breadth. The right UX target is:

```text
Transparent risk workflow with fast navigation and clear data/model provenance.
```

## 6. Calypso Comparison

Nasdaq Calypso is positioned as a front-to-back capital markets platform covering trading, risk, collateral, post-trade, data, reporting, and regulatory workflows. Its UX strength comes from operational continuity: trade capture, valuation, risk, collateral, limits, lifecycle events, and reporting all belong to one platform context.

### Where RiskCalc Is Directionally Similar

- Portfolio is becoming the central object.
- Services are becoming canonical workflow entry points.
- Governance and production gating exist conceptually.
- Market data, pricing, risk, and portfolio are being separated.

### Where RiskCalc Should Not Copy Calypso

- Do not try to become full front-to-back processing.
- Do not implement trade lifecycle operations before analytics workflows mature.
- Do not add collateral, settlement, confirmations, and regulatory reporting too early.

### Calypso Gap

RiskCalc currently lacks:

- trade lifecycle state;
- books and hierarchy;
- operational controls;
- limits and approvals;
- audit trail;
- role-based workflows;
- report generation;
- persistent trade and position storage.

### Practical Lesson For RiskCalc

The UX should make workflow state explicit:

```text
Position source
Book
Valuation date
Market data snapshot
Calculation status
Approval/model status
Report status
```

RiskCalc should not become a Calypso replacement, but it should adopt the discipline that risk workflows operate on controlled data objects, not ad hoc form inputs.

## 7. Numerix Comparison

Numerix Oneview is positioned around cross-asset pricing and market-risk analytics, including what-if analysis, VaR, Monte Carlo, stress testing, XVA, and cloud-scale computation. Its closest relevance to RiskCalc is the combination of pricing analytics and risk analytics around consistent model and market-data infrastructure.

### Where RiskCalc Is Directionally Similar

- Cross-asset pricing ambitions.
- VaR, ES, stress, scenario, XVA, and analytics-lab concepts.
- Model governance and limitations are visible architecture concerns.
- PortfolioService, RiskService, PricingService, and MarketDataService are converging toward a platform approach.

### Where RiskCalc Should Not Copy Numerix

- Do not pretend to have production-grade cross-asset valuation coverage yet.
- Do not hide model limitations behind polished workflow.
- Do not build cloud-scale UX before local correctness and service boundaries mature.

### Numerix Gap

RiskCalc currently lacks:

- robust cross-asset pricing coverage;
- full scenario repricing;
- scalable Monte Carlo infrastructure;
- valuation controls;
- enterprise market data ingestion;
- XVA workflow maturity;
- real-time/on-demand portfolio analytics.

### Practical Lesson For RiskCalc

RiskCalc's near-term UX should emphasize:

```text
What is calculated
Using which model
Using which data
With which limitations
At what portfolio scope
```

This transparency can be a product advantage while the analytics mature.

## 8. Top 20 UX Issues

### 1. Governance Is Not A First-Class Workspace

Severity: P1

Affected users:

- Market Risk Manager
- Quant Analyst
- Trader

Evidence:

- `PRODUCT_ARCHITECTURE.md` defines Model Governance as a target product layer.
- `app/main_window.py` has no Governance sidebar entry.

Why it matters:

- Model status is central to trust.
- Prototype and approximation warnings should be easy to investigate.

Recommended action:

- Add Governance as a top-level workspace after service migration stabilizes.
- Until then, add strong links from all model status chips to a model detail view.

### 2. Market Workspace Is A Plain Tab Container

Severity: P1

Affected users:

- Trader
- Quant Analyst
- Market Risk Manager

Evidence:

- `app/panels/market_workspace.py` directly creates a `QTabWidget`.

Why it matters:

- Market data should be a controlled platform, not a set of unrelated tabs.

Recommended action:

- Add Market landing overview:
  - snapshot status;
  - source status;
  - yield curves;
  - vol surfaces;
  - FX;
  - credit curves;
  - validation warnings.

### 3. FX Pricing Appears Inside Market

Severity: P1

Affected users:

- Trader
- Quant Analyst

Evidence:

- `MarketWorkspace` includes `FXPanel` labeled `FX Forward & Options`.

Why it matters:

- Market should own FX data, not FX option valuation.
- This creates mental and architectural coupling.

Recommended action:

- Split FX Market from FX Pricing.
- Market should show spot, forwards, FX curves, vols, and validation.
- Pricing should own FX forwards/options.

### 4. Pricing Landing Is Too Flat

Severity: P1

Affected users:

- Trader
- Quant Analyst

Evidence:

- `PRICING_MODULES` in `app/panels/pricing_workspace.py` contains 17 flat module cards.

Why it matters:

- Frequent workflows are buried among long-tail products.
- Core rates/FX/bond workflows should be faster to access.

Recommended action:

- Group modules:
  - Core Pricing;
  - Rates & Credit;
  - Structured & Exotic;
  - Experimental.

### 5. XVA Is In Pricing

Severity: P1

Affected users:

- Trader
- Market Risk Manager

Evidence:

- `PricingWorkspace` includes `XVA`.
- `UI_REDESIGN.md` says XVA should move out of Pricing.

Why it matters:

- XVA is valuation adjustment and counterparty-risk workflow, not a basic pricing ticket.

Recommended action:

- Move XVA to Risk / Counterparty Risk.
- Keep pricing links only where XVA is explicitly part of trade valuation.

### 6. Risk Workspace Duplicates Portfolio

Severity: P1

Affected users:

- Market Risk Manager

Evidence:

- `RISK_MODULES` includes `Portfolio`.

Why it matters:

- Portfolio should be the center; Risk should consume it.
- Duplicating Portfolio under Risk blurs ownership.

Recommended action:

- Remove generic Portfolio card from Risk.
- Add direct workflow action:

```text
Run risk on active portfolio
```

### 7. Portfolio Still Feels Like A Calculator Panel

Severity: P1

Affected users:

- Market Risk Manager
- Trader

Evidence:

- `app/panels/portfolio_panel.py` uses left controls, modal Add Position, result grid, and old table layout.

Why it matters:

- Portfolio should be the main operating object, not a side calculator.

Recommended action:

- Add portfolio tabs:
  - Positions;
  - Exposure;
  - Risk;
  - Scenario P&L;
  - Attribution;
  - Validation.

### 8. Modal-Only Position Entry Slows Workflow

Severity: P2

Affected users:

- Trader
- Market Risk Manager

Evidence:

- `AddPositionDialog` is the primary position-entry path.

Why it matters:

- Modals hide context and slow repeated position entry.

Recommended action:

- Add inline position editor or right-side drawer.
- Keep modal as a backward-compatible shortcut.

### 9. Raw Greeks Still Appear As Primary Portfolio Outputs

Severity: P1

Affected users:

- Market Risk Manager

Evidence:

- `PortfolioPanel` result grid includes Delta, Gamma, Vega, Theta, DV01, CS01, Rho.

Why it matters:

- Raw Greeks across products and asset classes can be misleading.
- The architecture already introduced risk factor exposure buckets.

Recommended action:

- Lead with risk-factor exposures:
  - Rates DV01;
  - FX delta;
  - Equity delta;
  - Credit CS01;
  - Vol vega.

### 10. No Persistent Market-Data Snapshot Context

Severity: P0 for production readiness, P1 for current UX

Affected users:

- All users

Evidence:

- Status bar says `Data: Demo / Manual · MOEX ISS: pending`.
- Service results support market-data metadata, but UI does not show it globally.

Why it matters:

- Risk and pricing workflows must be reproducible.

Recommended action:

- Add a persistent context strip showing:
  - source;
  - valuation date;
  - snapshot ID;
  - version;
  - warnings;
  - active curve/vol/FX source.

### 11. Result Metadata Is Inconsistent

Severity: P1

Affected users:

- All users

Evidence:

- Services return structured warnings and metadata.
- Only migrated panels consistently display warnings.

Why it matters:

- Users cannot always tell whether a number is validated, approximate, demo, or prototype.

Recommended action:

- Standardize a result footer or context panel:
  - model ID;
  - model status;
  - limitations;
  - market-data snapshot;
  - calculation timestamp;
  - warnings/errors.

### 12. Many Panels Still Bypass Service Workflows

Severity: P1

Affected users:

- All users

Evidence:

- Static import scan shows many `app/panels/*` files still import `models.*`, `instruments.*`, `risk.*`, or `curves.*`.

Why it matters:

- Direct engine calls bypass governance, market-data ownership, and consistent warnings.

Recommended action:

- Continue UI-to-service migration by workflow priority:
  1. option, FX, IRS, rates;
  2. portfolio;
  3. market data panels;
  4. exotics and analytics lab.

### 13. Warning UX Is Not Yet System-Wide

Severity: P1

Affected users:

- All users

Evidence:

- `UI_REDESIGN.md` requires consistent error and warning UX.
- Migrated panels use Banner, but many panels still handle exceptions locally.

Why it matters:

- In risk systems, warnings are part of the result, not decoration.

Recommended action:

- Standardize WarningBanner usage across all production panels.
- Separate:
  - validation warnings;
  - demo-data warnings;
  - model governance warnings;
  - calculation errors.

### 14. Dashboard Does Not Yet Drive Daily Work

Severity: P1

Affected users:

- Market Risk Manager
- Trader

Evidence:

- Dashboard exists, but the target daily workflow is not yet clear from the shell.

Why it matters:

- A risk manager should start the day from Dashboard and immediately know what needs action.

Recommended action:

- Dashboard should show:
  - portfolio MV;
  - daily P&L;
  - VaR/ES;
  - worst stress;
  - data status;
  - model status;
  - blocked warnings;
  - last calculation timestamp.

### 15. No Clear Save-To-Portfolio Workflow From Pricing

Severity: P1

Affected users:

- Trader
- Market Risk Manager

Evidence:

- Pricing modules are opened as standalone panels.
- PortfolioService exists but pricing-to-portfolio workflow is not obvious.

Why it matters:

- Traders need to price a trade and push it into portfolio analysis.

Recommended action:

- Add result action:

```text
Add to Portfolio
```

or

```text
Create Position From Trade
```

### 16. Scenario Workflow Is Fragmented

Severity: P1

Affected users:

- Trader
- Market Risk Manager

Evidence:

- Scenario Engine Foundation exists architecturally.
- UI scenario access remains panel-specific.

Why it matters:

- Users need consistent scenario shocks across pricing, portfolio, risk, and P&L explain.

Recommended action:

- Add a shared scenario selector:
  - parallel curve shift;
  - steepener;
  - flattener;
  - FX shock;
  - equity shock;
  - volatility shock.

### 17. Backtesting Is Not Prominent Enough

Severity: P1

Affected users:

- Market Risk Manager
- Quant Analyst

Evidence:

- Risk landing emphasizes VaR, Historical VaR, and Stress, but backtesting is buried in module descriptions.

Why it matters:

- VaR without backtesting is incomplete for risk management.

Recommended action:

- Add Backtesting as a visible Risk workflow card or top-level tab inside VaR.

### 18. Analytics Lab Does Not Strongly Signal Research Mode

Severity: P1

Affected users:

- Quant Analyst
- Trader
- Market Risk Manager

Evidence:

- Analytics workspace exists and governance flags exist, but visual/workflow separation is not yet strong enough.

Why it matters:

- Research models must not be mistaken for production workflows.

Recommended action:

- Add persistent `Research / Not production` status in Analytics panels.
- Require explicit opt-in when sending lab output to production-like workflows.

### 19. No Export Or Report Workflow

Severity: P1

Affected users:

- Market Risk Manager
- Trader
- Quant Analyst

Evidence:

- Target workflows include report/export.
- Current app does not expose a coherent export path.

Why it matters:

- Professional users need to move results into memos, limits packs, or trade tickets.

Recommended action:

- Add export after workflow foundations:
  - pricing ticket;
  - portfolio risk report;
  - stress report;
  - model validation summary.

### 20. No Unified Search / Command Palette

Severity: P2

Affected users:

- Power users

Evidence:

- Navigation is sidebar and landing-card driven only.

Why it matters:

- Desktop workstation users need fast access to repeated workflows.

Recommended action:

- Add quick switcher:

```text
Ctrl+K
Search: Bond, VaR, Stress, Curve, Model Registry, Portfolio
```

This should be added after information architecture stabilizes.

## 9. Recommended UX Roadmap

### Phase UX-1: Workflow Integrity Before Visual Redesign

Goal:

```text
Make every production workflow service-backed and metadata-aware.
```

Tasks:

1. Add global context strip.
2. Standardize result metadata display.
3. Continue UI-to-service migration for core production panels.
4. Add model status drilldown.
5. Remove direct market-data construction from UI.

### Phase UX-2: Information Architecture Cleanup

Goal:

```text
Make product sections match business ownership.
```

Tasks:

1. Redesign Market as a market-data workspace, not tabs.
2. Group Pricing modules.
3. Remove XVA from Pricing.
4. Remove Portfolio card from Risk.
5. Add visible Backtesting and Model Validation entry points.
6. Prepare Governance workspace.

### Phase UX-3: Portfolio-Centered Workflows

Goal:

```text
Make Portfolio the default operating object.
```

Tasks:

1. Add Portfolio tabs:
   - Positions;
   - Exposure;
   - Risk;
   - Scenario P&L;
   - Attribution;
   - Validation.
2. Replace raw Greek summary with factor exposures.
3. Add save-to-portfolio from pricing.
4. Add run-risk-from-portfolio action.
5. Add scenario-to-P&L Explain workflow.

### Phase UX-4: Professional Workstation Efficiency

Goal:

```text
Reduce clicks and repeated data entry.
```

Tasks:

1. Add quick switcher.
2. Add recent calculations.
3. Add calculation history.
4. Add export/report workflow.
5. Add keyboard shortcuts for core operations.
6. Add persistent selected market-data snapshot.

### Phase UX-5: Visual Redesign

Goal:

```text
Apply the UI redesign spec after architecture and workflow ownership are clean.
```

Tasks:

1. Apply unified workspace headers.
2. Apply grouped cards.
3. Use shared components from `ui/components.py`.
4. Remove duplicated card implementations.
5. Reduce borders and nested frames.
6. Standardize charts and tables.

## 10. Final UX Assessment

RiskCalc is currently a strong technical product with an improving shell, but the user experience still reflects its origin as a set of pricing and risk calculators. The correct next UX move is not visual polish. The correct move is workflow consolidation.

Current UX product class:

```text
Advanced Prototype
```

Target next class:

```text
Professional Workstation Foundation
```

The highest-impact UX changes are:

1. Add persistent portfolio / market-data / model context.
2. Make Portfolio the main risk operating object.
3. Turn Market into a market-data control center.
4. Group Pricing by user workflow.
5. Make Governance visible.
6. Make every result explain its model, data, assumptions, warnings, and timestamp.

Until those are done, visual redesign should remain secondary.
