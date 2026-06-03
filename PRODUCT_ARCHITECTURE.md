# PRODUCT_ARCHITECTURE.md

# RiskCalc Product Architecture

**Version:** 1.0  
**Target architecture:** RiskCalc 2.0  
**Prepared for:** RiskCalc / RC_project  
**Repository:** `dwooo3/RC_project`  
**Date:** 2026-06-03  
**Status:** Proposed target architecture and migration blueprint  
**Audience:** Founder / Product Owner / Lead Architect / Quant Developer / AI Coding Agent

---

## Table of Contents

1. Executive Summary  
2. Current State Assessment  
3. Product Vision  
4. Strategic Positioning  
5. User Personas  
6. Core User Workflows  
7. Target Product Layers  
8. Domain Model  
9. Target System Architecture  
10. Application Services  
11. Market Data Platform  
12. Pricing Platform  
13. Portfolio Platform  
14. Risk Platform  
15. Model Governance Platform  
16. Analytics Lab  
17. UI / UX Architecture  
18. Data Architecture  
19. Model Lifecycle and Validation  
20. Target Repository Structure  
21. Dependency Rules  
22. Module Ownership Matrix  
23. Current Anti-Patterns  
24. Delete / Move / Merge Decisions  
25. Refactor Strategy  
26. Testing Strategy  
27. CI/CD and Release Management  
28. Security, Auditability and Reproducibility  
29. Comparison with Bloomberg, Calypso, Murex, Numerix and OpenGamma  
30. Roadmap v1.0 to v3.0  
31. Migration Plan  
32. Production Readiness Criteria  
33. Appendix A — Current Repository Snapshot  
34. Appendix B — Target Screen Map  
35. Appendix C — AI Agent Implementation Instructions  

---

# 1. Executive Summary

RiskCalc is currently a strong quantitative prototype with a modernizing PySide UI shell, multiple pricing models, risk models, instrument panels, a model registry, and early tests. It is already more than a simple calculator collection, but it is not yet a coherent product architecture.

The most important architectural conclusion is this:

```text
RiskCalc is currently organized around models and panels.
RiskCalc 2.0 must be organized around market-risk workflows.
```

A user in a bank does not think:

```text
Open BondPanel
Open HestonPanel
Open VarPanel
```

A real user thinks:

```text
Load positions
Check market data
Revalue portfolio
Explain P&L
Compute VaR
Run stress
Review model status
Export report
```

Therefore, RiskCalc must evolve from:

```text
Models + Panels + Widgets
```

into:

```text
Market Data Platform
+ Pricing Platform
+ Portfolio Platform
+ Risk Platform
+ Model Governance Platform
+ Analytics Lab
+ Workflow UI
```

The target product is not a clone of Bloomberg, Calypso, Murex or Numerix. The correct target is a focused market-risk and pricing workstation for bank-style analytics, with transparent model governance and enough structure to support future productionization.

This document defines the long-term architecture, migration path, module ownership, data flow, target folder structure, workflow design, and deletion/refactoring decisions.

---

# 2. Current State Assessment

## 2.1 Current repository structure

The uploaded project archive contains approximately:

```text
91 project files
85 Python files
44 app/UI-related files
15 instrument files
9 model files
6 risk files
3 curve files
5 tests
```

The current high-level structure is:

```text
app/
models/
instruments/
risk/
curves/
tests/
main.py
run_app.py
```

This structure is understandable for a prototype, but it does not yet express the true business domains of a risk terminal.

## 2.2 Current strengths

RiskCalc already has several strong components:

1. **Workflow shell has started to emerge.**  
   The UI has moved toward high-level sections: Dashboard, Market, Pricing, Portfolio, Risk, Analytics, Settings.

2. **Models are separated from many panels.**  
   There is an attempt to isolate models under `models/`, instruments under `instruments/`, risk under `risk/`, and curves under `curves/`.

3. **Model registry exists.**  
   `models/registry.py` is an important foundation for model governance.

4. **Testing exists.**  
   There are tests for Black-Scholes, Monte Carlo, trees and VaR. Coverage is not enough, but the testing habit already exists.

5. **The project is extensible.**  
   Adding new panels and models is easy. That is good for research, but dangerous if not governed.

## 2.3 Current weaknesses

The weaknesses are structural:

1. **Two architectures coexist.**  
   There is a new top-level workspace shell, but under it still lives the old calculator-panel architecture.

2. **UI is too thick.**  
   Many panels mix UI, business logic, formatting and pricing calls.

3. **No application service layer exists.**  
   UI calls model functions directly.

4. **Market data is not a real domain layer.**  
   Curves, volatility surfaces, FX data and Russian market data are not yet governed by source, date, convention, or validation status.

5. **Portfolio is not yet the center of the product.**  
   In a market risk system, Portfolio should be the central object. Currently Pricing and individual panels dominate.

6. **Risk aggregation mixes units.**  
   Raw Greeks are aggregated across asset classes without a proper factor exposure model.

7. **Fixed income methodology is too simplified.**  
   Bonds, FRNs, IRS and curves need conventions, schedules, calendars, settlement dates and dual-curve logic.

8. **Governance is incomplete.**  
   The registry exists, but production gating, audit trail, model versioning and validation workflow are not implemented.

---

# 3. Product Vision

## 3.1 One-sentence product definition

RiskCalc is a market risk and pricing workstation for transparent valuation, portfolio analytics, VaR/stress measurement, model governance and research-grade quantitative analytics.

## 3.2 What RiskCalc should become

RiskCalc should become:

```text
A workflow-first market risk terminal.
```

It should serve the following activities:

- market data review;
- curve and volatility construction;
- instrument pricing;
- portfolio valuation;
- sensitivity aggregation;
- VaR and ES calculation;
- stress testing;
- backtesting;
- P&L explain;
- model status review;
- audit and reproducibility of calculations;
- research model comparison.

## 3.3 What RiskCalc should not become

RiskCalc should not become:

1. A random collection of pricing calculators.
2. A clone of Bloomberg terminal.
3. A trading execution system.
4. A full core banking system.
5. A position-keeping golden source.
6. A regulatory reporting factory in v1.
7. A black-box quant library without model governance.

## 3.4 Product design principle

The primary object should be:

```text
Portfolio and workflow
```

not:

```text
Panel and model
```

---

# 4. Strategic Positioning

## 4.1 Position against Bloomberg

Bloomberg is a market data and analytics terminal. It is broad, data-rich and workflow-rich.

RiskCalc should not compete with Bloomberg on breadth. It should focus on transparent, inspectable, customizable analytics.

Borrow from Bloomberg:

- market overview panels;
- curve screens;
- instrument analytics;
- risk summary;
- fast keyboard-like navigation.

Do not copy:

- cluttered command-line UI;
- excessive density;
- dependency on proprietary data.

## 4.2 Position against Calypso / Murex

Calypso and Murex are front-to-back trading and risk platforms. They handle trade capture, confirmations, accounting, settlement, P&L, risk and regulatory processes.

RiskCalc should not try to become a full transaction lifecycle system.

Borrow from Calypso/Murex:

- book/portfolio hierarchy;
- instrument taxonomy;
- risk factor mapping;
- valuation date concept;
- model governance;
- audit trail.

Do not copy:

- heavy enterprise complexity;
- deep operational workflows;
- difficult configuration UX.

## 4.3 Position against Numerix

Numerix is a derivatives pricing and risk analytics library/platform, especially for complex products.

RiskCalc can borrow the idea of a structured pricing library with model transparency.

Do not attempt full Numerix-level exotic coverage before basic FI, curves, VaR, portfolio and governance are robust.

## 4.4 Position against OpenGamma

OpenGamma is a good conceptual reference for market risk analytics, curve building and explainable risk.

Borrow:

- curve-centric architecture;
- market data snapshots;
- risk factor explain;
- scenario framework;
- analytics-first design.

---

# 5. User Personas

## 5.1 Market Risk Manager

### Primary objective

Understand portfolio risk and explain changes.

### Main questions

```text
What is my VaR?
What changed since yesterday?
Which risk factors drive P&L?
Are limits breached?
What happens under stress?
Which models are not validated?
```

### Main workflow

```text
Dashboard
↓
Portfolio
↓
Risk
↓
Stress
↓
Backtesting
↓
Report
```

### Required screens

- Portfolio Summary
- Exposure
- VaR / ES
- Stress Testing
- Backtesting
- P&L Explain
- Model Status

## 5.2 Quantitative Analyst

### Primary objective

Develop, validate and compare pricing/risk models.

### Main questions

```text
Does the model match benchmark?
Does MC converge?
Does tree converge to BSM?
How stable is calibration?
What are the model limitations?
```

### Main workflow

```text
Market Data
↓
Pricing
↓
Analytics Lab
↓
Model Governance
```

### Required screens

- Curve Builder
- Vol Surface
- Model Lab
- Pricing Validation
- Benchmarking
- Model Registry

## 5.3 Trader / Structurer

### Primary objective

Price trades and understand sensitivities.

### Main questions

```text
What is the fair value?
What is the DV01 / Vega / Delta?
How does price change under market shocks?
What is the break-even?
```

### Main workflow

```text
Market
↓
Pricing
↓
Scenario
↓
Export / Save
```

### Required screens

- Bond Pricing
- IRS/OIS Pricing
- FX Options
- Vanilla/Exotic Options
- Structured Products
- Scenario Analysis

## 5.4 Model Validation Team

### Primary objective

Control model use and validation status.

### Main questions

```text
Which models are used?
Which are validated?
Which are prototypes?
Which tests exist?
Which models are blocked for production?
```

### Main workflow

```text
Model Registry
↓
Model Detail
↓
Validation Tests
↓
Audit Trail
```

### Required screens

- Model Registry
- Validation Matrix
- Test Coverage
- Model Detail
- Audit Trail

---

# 6. Core User Workflows

## 6.1 Daily market risk workflow

```text
Open Dashboard
↓
Check data status
↓
Open Portfolio
↓
Load / review positions
↓
Check market value and P&L
↓
Open Risk
↓
Run VaR / ES
↓
Run Stress
↓
Review exceptions / backtesting
↓
Export report
```

## 6.2 Pricing workflow

```text
Open Market Data
↓
Select curve / vol / FX data
↓
Open Pricing
↓
Select instrument
↓
Enter trade terms
↓
Calculate price
↓
Review sensitivities
↓
Run scenarios
↓
Save result to portfolio or export
```

## 6.3 Curve construction workflow

```text
Open Market Data
↓
Select Yield Curves
↓
Choose source / valuation date
↓
Build curve
↓
Validate discount factors and forwards
↓
Save curve snapshot
↓
Use in pricing
```

## 6.4 VaR workflow

```text
Open Portfolio
↓
Confirm positions and market data
↓
Open Risk -> VaR
↓
Select method
↓
Select horizon and confidence
↓
Run calculation
↓
Review distribution and ES
↓
Review component contribution
↓
Run backtest
```

## 6.5 Model validation workflow

```text
Open Governance -> Model Registry
↓
Filter non-production models
↓
Open model detail
↓
Review assumptions
↓
Run benchmark tests
↓
Review limitations
↓
Approve / downgrade / disable
```

---

# 7. Target Product Layers

## 7.1 Layer overview

The target architecture contains seven product layers:

```text
1. Dashboard
2. Market Data
3. Pricing
4. Portfolio
5. Risk
6. Model Governance
7. Analytics Lab
```

These layers are product concepts, not necessarily exact Python packages. However, the target repository should reflect them.

## 7.2 Layer 1 — Dashboard

Dashboard is a starting screen.

It should not contain:

- pricing forms;
- model parameters;
- full validation tables;
- long diagnostics;
- instrument calculators.

It should contain:

```text
Portfolio Summary
Market Summary
Risk Summary
Model Summary
System Status
```

Dashboard cards:

```text
Portfolio MV
Daily P&L
VaR 95%
ES 95%
DV01
Vega
Data Status
Model Status
```

## 7.3 Layer 2 — Market Data

Market Data owns:

```text
Yield Curves
Volatility Surfaces
FX Market
Credit Curves
Market Data Monitor
```

Market Data does not price trades. It provides validated inputs.

## 7.4 Layer 3 — Pricing

Pricing owns instrument valuation.

Groups:

```text
Rates
FX
Equity
Credit
Structured
```

Pricing must consume market data snapshots, not hardcoded assumptions.

## 7.5 Layer 4 — Portfolio

Portfolio is the center.

It owns:

```text
Positions
Books
Exposure
Performance
Scenario P&L
Attribution
```

All risk calculations should run on a portfolio, even if the portfolio has one position.

## 7.6 Layer 5 — Risk

Risk owns:

```text
VaR
ES
Stress
Backtesting
Capital
Limit Monitoring
```

Risk consumes portfolio, positions, market data and model outputs.

## 7.7 Layer 6 — Model Governance

Governance owns:

```text
Model Registry
Validation
Audit Trail
Model Status
Production Gating
```

This layer decides what can be used in production.

## 7.8 Layer 7 — Analytics Lab

Analytics Lab owns research:

```text
Numerical Methods
Stochastic Models
Rates Models
Experimental Models
```

This layer is allowed to contain prototypes, but those prototypes must not silently appear in production workflows.

---

# 8. Domain Model

## 8.1 Core entities

RiskCalc needs explicit domain entities:

```text
MarketDataSnapshot
YieldCurve
VolSurface
FXCurve
CreditCurve
Instrument
Trade
Position
Book
Portfolio
PricingResult
RiskFactor
RiskFactorExposure
Scenario
RiskResult
ModelDefinition
ModelValidationStatus
AuditEvent
```

## 8.2 MarketDataSnapshot

Represents a consistent set of market data for a valuation date.

Fields:

```python
valuation_date
source
created_at
curves
vol_surfaces
fx_rates
credit_spreads
metadata
```

## 8.3 Instrument

Represents static product definition.

Examples:

```text
Bond
FRN
IRS
FXForward
EuropeanOption
BarrierOption
CDS
Autocall
```

## 8.4 Trade

Represents a deal with quantity, direction, counterparty, book and dates.

A trade is not the same as an instrument.

## 8.5 Position

Represents current holding or exposure.

Fields:

```text
position_id
instrument
quantity
market_value
currency
book
valuation_status
```

## 8.6 Portfolio

A collection of positions.

Fields:

```text
portfolio_id
name
books
positions
valuation_date
base_currency
```

## 8.7 PricingResult

Pricing should return a structured object:

```text
price
clean_price
dirty_price
market_value
currency
greeks
cashflows
model_used
model_version
market_data_snapshot
warnings
errors
```

## 8.8 RiskFactorExposure

This is critical.

Do not aggregate raw Greeks across asset classes.

Use:

```python
factor_name: str
factor_type: str
currency: str
bump_size: float
sensitivity: float
unit: str
```

Examples:

```text
MOEX Index spot delta
USD/RUB FX delta
OFZ 5Y DV01
RUONIA 1Y DV01
Issuer spread CS01
Vol surface ATM Vega
```

## 8.9 Scenario

A scenario is a set of risk factor shocks.

Fields:

```text
scenario_id
name
type
source
date
factor_shocks
severity
description
```

## 8.10 ModelDefinition

A governed model definition:

```text
model_id
name
domain
version
status
owner
production_allowed
limitations
tests
references
last_validated
```

---

# 9. Target System Architecture

## 9.1 Target dependency direction

Allowed dependency direction:

```text
UI
↓
Application Services
↓
Domain Services
↓
Domain Models
↓
Market Data / Pricing / Risk Engines
```

Forbidden:

```text
UI -> random model function
UI -> raw numpy logic
Pricing -> UI
Risk -> UI
Models -> app panels
```

## 9.2 Target architecture diagram

```text
┌────────────────────────────────────────────────────────────┐
│                         UI Layer                           │
│ Dashboard | Market | Pricing | Portfolio | Risk | Governance│
└───────────────────────────┬────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────┐
│                   Application Services                      │
│ PricingService | PortfolioService | RiskService | DataService│
└───────────────────────────┬────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────┐
│                      Domain Layer                           │
│ Instrument | Position | Portfolio | Scenario | ModelDefinition│
└───────────────┬───────────────────────┬────────────────────┘
                │                       │
┌───────────────▼──────────────┐ ┌──────▼─────────────────────┐
│      Market Data Layer        │ │      Analytics Engines      │
│ Curves | Vols | FX | Credit   │ │ Pricing | Risk | Simulation │
└───────────────────────────────┘ └────────────────────────────┘
```

## 9.3 Why services are mandatory

Services prevent UI panels from becoming business logic containers.

Examples:

```python
BondPanel -> BondPricingService -> BondPricer
VarPanel -> VaRService -> VaREngine
PortfolioPanel -> PortfolioService -> PortfolioRepository
```

---

# 10. Application Services

## 10.1 Service layer responsibilities

Application services should:

- validate inputs;
- fetch market data snapshots;
- call pricing/risk engines;
- enrich results with model metadata;
- handle warnings and errors;
- return UI-ready structured results.

They should not:

- render widgets;
- know PySide classes;
- contain visual formatting;
- silently swallow exceptions.

## 10.2 Required services

```text
MarketDataService
CurveService
VolSurfaceService
PricingService
BondPricingService
IRSPricingService
OptionPricingService
PortfolioService
RiskService
VaRService
StressService
BacktestingService
ModelRegistryService
AuditService
ExportService
```

## 10.3 Example BondPricingService

```python
class BondPricingService:
    def price(request: BondPricingRequest) -> BondPricingResult:
        validate_request(request)
        curve = market_data_service.get_curve(request.curve_id)
        model = registry.get("fixed_bond")
        result = bond_engine.price(request.instrument, curve)
        return enrich_with_model_status(result, model)
```

## 10.4 Example VaRService

```python
class VaRService:
    def calculate(request: VaRRequest) -> VaRResult:
        portfolio = portfolio_service.get(request.portfolio_id)
        returns = market_data_service.get_returns(request.risk_factors)
        model = registry.get(request.method)
        return var_engine.calculate(portfolio, returns, request)
```

---

# 11. Market Data Platform

## 11.1 Purpose

Market Data is the foundation. Every pricing and risk result must be linked to a market data snapshot.

## 11.2 Current issue

Market data is currently scattered:

```text
curves/
risk/vol_surface.py
curves/russia.py
manual defaults
panel inputs
```

This creates inconsistent pricing and risk results.

## 11.3 Target market data structure

```text
market/
  curves/
    yield_curve.py
    curve_builder.py
    interpolation.py
    validation.py
  vols/
    surface.py
    smile.py
    calibration.py
  fx/
    spot.py
    forwards.py
    fx_curve.py
  credit/
    spreads.py
    hazard_curve.py
  providers/
    manual.py
    csv.py
    moex_iss.py
```

## 11.4 MarketDataSnapshot

Every calculation should include:

```text
valuation_date
source
curve ids
vol ids
fx rates
credit spreads
data quality status
```

## 11.5 Yield curve rules

There must be one and only one `YieldCurve` implementation.

The current duplication must be removed.

Target:

```text
market/curves/yield_curve.py
```

Supported interpolation:

```text
linear zero
linear discount factor
log-linear discount factor
PCHIP zero
PCHIP discount factor
```

Validation:

```text
positive discount factors
monotonic discount factors
reasonable forwards
no NaN
no infinite rates
```

## 11.6 Russian market data

Russian-specific data should be a provider or adapter, not a separate inconsistent curve implementation.

Target:

```text
market/providers/moex_iss.py
market/russia/ofz.py
market/russia/ruonia.py
```

OFZ and RUONIA must include:

```text
source
valuation date
rate type
day count
compounding
calendar
```

---

# 12. Pricing Platform

## 12.1 Purpose

Pricing converts instruments and market data into valuations, cashflows and sensitivities.

## 12.2 Pricing groups

```text
pricing/rates/
pricing/fx/
pricing/equity/
pricing/credit/
pricing/structured/
```

## 12.3 Rates pricing

Must include:

```text
Bond
FRN
IRS
OIS
Basis Swap
Cap/Floor
Swaption
```

## 12.4 Bond pricing requirements

Production bond pricing requires:

```text
settlement date
maturity date
coupon schedule
business day convention
day count
clean price
dirty price
accrued interest
yield
duration
convexity
DV01
key-rate DV01
```

## 12.5 FRN requirements

FRN pricing requires:

```text
current reset coupon
future projected coupons
spread
discount curve
projection curve
reset dates
fixing lag
```

## 12.6 IRS/OIS requirements

IRS pricing requires:

```text
fixed leg schedule
floating leg schedule
discount curve
projection curve
day count
notional
pay/receive direction
fair rate
NPV
DV01
```

Single-curve IRS is allowed only as an approximation with a visible warning.

## 12.7 Equity/FX option pricing

Closed-form models are acceptable for vanilla instruments, but must be governed.

Required output:

```text
price
delta
gamma
vega
theta
rho
model status
warnings
```

## 12.8 Exotic pricing

Exotics should be separated into production and research models.

Prototype exotic models must show visible warnings.

## 12.9 PricingResult contract

Every pricing module should return:

```python
@dataclass
class PricingResult:
    price: float
    currency: str
    market_value: float
    cashflows: list
    sensitivities: list[RiskFactorExposure]
    model_id: str
    model_version: str
    market_data_snapshot_id: str
    warnings: list[str]
    errors: list[str]
```

---

# 13. Portfolio Platform

## 13.1 Purpose

Portfolio is the central business object.

Pricing and risk should feed into Portfolio.

## 13.2 Current issue

Portfolio currently behaves like a panel with scenario inputs and a table. It is not yet a domain platform.

## 13.3 Target portfolio modules

```text
Positions
Books
Exposure
Performance
Scenario P&L
Attribution
Validation
```

## 13.4 Book hierarchy

Target:

```text
Portfolio
  Trading Book
    Desk
      Strategy
        Position
  Banking Book
    Portfolio
      Position
  Watchlist
```

## 13.5 Position model

A position should contain:

```text
position_id
instrument_id
quantity
direction
book
currency
market_value
pricing_status
risk_status
last_priced_at
```

## 13.6 Exposure aggregation

Do not aggregate:

```text
delta + bond duration proxy + fx delta
```

Instead aggregate risk factors:

```text
Equity spot exposure
FX spot exposure
Rate DV01 by curve and tenor
Credit CS01 by issuer/curve
Vol Vega by surface bucket
```

## 13.7 P&L explain

P&L explain should include:

```text
Delta P&L
Gamma P&L
Vega P&L
Theta P&L
Rate P&L
Credit P&L
FX P&L
Residual / unexplained
```

## 13.8 Scenario P&L

Scenario P&L should support:

```text
full repricing
Greeks approximation
hybrid method
```

Full repricing must be the preferred target.

---

# 14. Risk Platform

## 14.1 Purpose

Risk measures portfolio loss distribution and stress exposure.

## 14.2 Risk modules

```text
VaR / ES
Stress Testing
Backtesting
P&L Attribution
Limit Monitoring
Capital
```

## 14.3 VaR platform

VaR should be one workspace with internal methods:

```text
Historical
Weighted Historical
Filtered Historical
Parametric
Monte Carlo
EVT
```

Historical VaR should not be a separate top-level module.

## 14.4 ES requirements

ES must be shown alongside VaR.

Rule:

```text
ES should be greater than or equal to VaR for the same confidence and loss convention.
```

## 14.5 Backtesting

Required tests:

```text
Kupiec POF
Christoffersen independence
Traffic light
Exception timeline
Average exceedance
```

## 14.6 Stress testing

Stress scenarios should be structured:

```text
Historical
Hypothetical
Regulatory
Reverse Stress
Custom
```

Each scenario must define risk factor shocks.

## 14.7 Capital

Capital is not mandatory for v1, but should be a planned module:

```text
Economic Capital
Regulatory Capital
Stress Capital
```

---

# 15. Model Governance Platform

## 15.1 Purpose

Model governance controls which models can be used, where, and with what warnings.

## 15.2 Current foundation

The existing `models/registry.py` is a good start.

## 15.3 Target governance package

```text
governance/
  registry/
  validation/
  audit/
  approvals/
```

## 15.4 Model statuses

Use:

```text
Validated
Approximation
Prototype
Placeholder
Broken
Disabled
Deprecated
```

## 15.5 Production gating

Rules:

```text
Validated      -> production allowed
Approximation  -> allowed with warning
Prototype      -> blocked by default, allowed in Analytics Lab
Placeholder    -> blocked
Broken         -> blocked
Disabled       -> blocked
Deprecated     -> warning or blocked
```

## 15.6 ModelDefinition

```python
@dataclass
class ModelDefinition:
    model_id: str
    name: str
    domain: str
    version: str
    status: str
    owner: str
    production_allowed: bool
    limitations: list[str]
    tests: list[str]
    references: list[str]
    last_validated: date | None
```

## 15.7 Audit trail

Every calculation should be auditable:

```text
who ran it
when
inputs
model version
market data snapshot
output
warnings
errors
```

---

# 16. Analytics Lab

## 16.1 Purpose

Analytics Lab is the research area.

It is not a production pricing area.

## 16.2 Modules

```text
Numerical Methods
  Binomial
  Trinomial
  Monte Carlo
  LSM

Stochastic Models
  Heston
  SABR
  GARCH

Rates Models
  Hull-White
  Vasicek
  CIR

Research
  Experimental Models
```

## 16.3 Rules

Prototype models belong here until validated.

Analytics Lab may expose:

```text
convergence diagnostics
path visualizations
calibration errors
benchmark comparison
```

It should not feed production portfolios unless explicitly approved.

---

# 17. UI / UX Architecture

## 17.1 UI principle

UI must reflect workflows, not implementation files.

## 17.2 Top-level navigation

Keep:

```text
Dashboard
Market
Pricing
Portfolio
Risk
Governance
Analytics
Settings
```

The current system has Model Governance hidden in Risk; long-term it deserves its own section or a Governance tab.

## 17.3 Dashboard

Dashboard contains:

```text
Portfolio Summary
Market Summary
Risk Summary
Model Summary
System Status
```

No full model registry table.

## 17.4 Market workspace

Target:

```text
Yield Curves
Vol Surfaces
FX Market
Credit Curves
Market Data Monitor
```

No pricing modules in Market.

## 17.5 Pricing workspace

Target groups:

```text
Rates
FX
Equity
Credit
Structured
```

Remove XVA from Pricing.

## 17.6 Portfolio workspace

Target tabs:

```text
Positions
Exposure
Performance
Scenario P&L
Attribution
Validation
```

## 17.7 Risk workspace

Target groups:

```text
VaR / ES
Stress
Backtesting
Limit Monitoring
Capital
```

Remove Portfolio card from Risk.

## 17.8 Governance workspace

Target:

```text
Model Registry
Validation
Audit Trail
Approvals
```

## 17.9 Analytics workspace

Target:

```text
Numerical Methods
Stochastic Models
Rates Models
Research
```

---

# 18. Data Architecture

## 18.1 Required data categories

```text
Market data
Reference data
Trade data
Position data
Model metadata
Calculation results
Audit events
Reports
```

## 18.2 Market data

Must include:

```text
source
valuation date
timestamp
quality status
curve/vol identifiers
```

## 18.3 Position data

Can initially be in memory, then SQLite/PostgreSQL later.

Required fields:

```text
position id
instrument type
quantity
book
currency
parameters
created date
last valuation date
```

## 18.4 Calculation result storage

Every result should be optionally storable:

```text
calculation id
request
response
model metadata
market data snapshot
timestamp
```

## 18.5 Future database

Target database for v2+:

```text
PostgreSQL
```

Candidate schema:

```text
market_data_snapshots
yield_curves
vol_surfaces
fx_rates
instruments
trades
positions
portfolios
pricing_results
risk_results
model_registry
audit_events
```

---

# 19. Target Repository Structure

Recommended target:

```text
riskcalc/
  app/
    main_window.py
    routes.py

  ui/
    theme.py
    components.py
    layouts.py
    charts.py

  domain/
    instruments.py
    positions.py
    portfolios.py
    risk_factors.py
    scenarios.py

  market/
    curves/
    vols/
    fx/
    credit/
    providers/

  pricing/
    rates/
    fx/
    equity/
    credit/
    structured/

  portfolio/
    services.py
    analytics.py
    attribution.py

  risk/
    var/
    stress/
    backtesting/
    capital/

  governance/
    registry/
    validation/
    audit/

  analytics/
    numerical/
    stochastic/
    rates/

  services/
    market_data_service.py
    pricing_service.py
    portfolio_service.py
    risk_service.py
    governance_service.py

  tests/
```

---

# 20. Dependency Rules

## 20.1 Allowed

```text
ui -> services
services -> domain
services -> pricing/risk/market/governance
pricing -> market/domain/governance
risk -> portfolio/market/domain/governance
portfolio -> domain/pricing
governance -> metadata/tests/audit
```

## 20.2 Forbidden

```text
pricing -> ui
risk -> ui
market -> ui
domain -> ui
models -> panels
panels -> raw engines directly
```

## 20.3 Import rule

A PySide widget should not import:

```text
numpy-heavy model logic
pricing internals
risk internals
```

directly. It should call a service.

---

# 21. Module Ownership Matrix

| Domain | Owner Layer | Current Location | Target Location |
|---|---|---|---|
| YieldCurve | Market Data | `curves/`, `instruments/fixed_income.py` | `market/curves/` |
| Vol Surface | Market Data | `risk/vol_surface.py` | `market/vols/` |
| FX rates | Market Data | `instruments/fx.py`, panels | `market/fx/` |
| Bond pricing | Pricing | `instruments/fixed_income.py` | `pricing/rates/bond.py` |
| IRS pricing | Pricing | `instruments/fixed_income.py` | `pricing/rates/irs.py` |
| Option pricing | Pricing | `models/black_scholes.py` | `pricing/equity/vanilla.py` |
| VaR | Risk | `risk/var.py`, `risk/historical_var.py` | `risk/var/` |
| Stress | Risk | `risk/stress.py` | `risk/stress/` |
| Portfolio | Portfolio | `risk/portfolio.py` | `portfolio/` |
| Model Registry | Governance | `models/registry.py` | `governance/registry/` |
| Analytics models | Analytics Lab | `models/` | `analytics/` or governed pricing/risk |

---

# 22. Current Anti-Patterns

## 22.1 Duplicate YieldCurve

There are multiple curve concepts. This is P0.

Target: one curve model.

## 22.2 Thick UI panels

Panels contain workflow, model calls, formatting and business logic.

Target: thin UI + service layer.

## 22.3 Flat module grids

Pricing has too many cards in one flat grid.

Target: grouped domain navigation.

## 22.4 Mixed risk aggregation

Portfolio aggregates raw Greeks.

Target: factor exposure aggregation.

## 22.5 Silent exception handling

Some workspace factories catch exceptions and return nothing.

Target: visible error panel + logging.

## 22.6 Demo data not clearly isolated

Hardcoded market data can look real.

Target: demo/manual/prod data flags.

---

# 23. Delete / Move / Merge Decisions

## 23.1 Delete or hide as separate cards

```text
IR Derivatives
Historical VaR
Portfolio inside Risk
FX Forward & Options inside Market
XVA inside Pricing
```

## 23.2 Move

```text
XVA -> Risk / Counterparty Risk
FX Forward & Options -> Pricing / FX
Vol Surface -> Market Data / Vols
Model Registry -> Governance
```

## 23.3 Merge

```text
Historical VaR -> VaR workspace tab
IR Derivatives -> Rates pricing group
Cap/Floor/Swaption -> Rates derivatives
```

## 23.4 Keep but reorganize

```text
Bond
IRS
FX
Option
VaR
Stress
Portfolio
Analytics Lab
```

---

# 24. Refactor Strategy

## 24.1 Refactor principle

Do not rewrite everything at once.

Use strangler pattern:

```text
old panel remains
new service introduced
panel calls service
domain object introduced
old logic moved out
tests added
panel redesigned
```

## 24.2 Refactor sequence

1. Create domain objects.
2. Create service layer.
3. Move curve logic to market layer.
4. Refactor bond pricing.
5. Refactor portfolio aggregation.
6. Refactor VaR.
7. Add governance checks.
8. Redesign UI.
9. Add persistence.
10. Add reporting.

## 24.3 First service to build

Build `MarketDataService` first.

Without it, pricing and risk will remain inconsistent.

## 24.4 First model to refactor

Refactor YieldCurve first.

It is used by fixed income, market data and risk.

## 24.5 First UI to refactor

Refactor Portfolio.

Portfolio is the center of the product.

---

# 25. Testing Strategy

## 25.1 Test categories

```text
unit tests
model benchmark tests
integration tests
workflow tests
UI smoke tests
regression tests
```

## 25.2 Required test modules

```text
test_yield_curve.py
test_market_data_snapshot.py
test_bond_pricing.py
test_irs_pricing.py
test_black_scholes.py
test_trees.py
test_monte_carlo.py
test_var.py
test_historical_var.py
test_stress.py
test_portfolio.py
test_governance.py
```

## 25.3 Quant validation tests

Examples:

```text
BSM known values
put-call parity
Black-76 parity
Bachelier ATM value
CRR convergence to BSM
MC convergence to BSM
Par bond near par
Par swap NPV near zero
ES >= VaR
Kupiec edge cases
```

## 25.4 UI smoke tests

At minimum:

```text
app starts
each workspace opens
each module landing renders
theme toggle works
no module silently fails
```

---

# 26. CI/CD and Release Management

## 26.1 GitHub Actions

Add CI:

```yaml
name: tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest -q
```

## 26.2 Versioning

Use semantic-ish versions:

```text
0.1 research prototype
0.5 workflow prototype
1.0 demo workstation
1.5 professional workstation
2.0 institutional platform candidate
```

## 26.3 Release notes

Every release should include:

```text
new features
model changes
validation status
known limitations
breaking changes
```

---

# 27. Security, Auditability and Reproducibility

## 27.1 Auditability

Every calculation should be reproducible.

Store:

```text
input parameters
model id
model version
market data snapshot
timestamp
result
warnings
errors
```

## 27.2 Reproducibility

A result should be rerunnable from the stored request.

## 27.3 Data source transparency

Every market input should show:

```text
manual
demo
CSV
MOEX ISS
external API
```

## 27.4 Production warning

If data is demo/manual, the UI must show:

```text
Demo / Manual market data. Not production valuation.
```

---

# 28. Comparison with Market Systems

## 28.1 Bloomberg

Borrow:

```text
market overview
fast navigation
curve screens
security analytics style
```

Avoid:

```text
excessive clutter
terminal-command dependence
```

## 28.2 Calypso

Borrow:

```text
book hierarchy
trade/position separation
risk reports
valuation date
```

Avoid:

```text
enterprise complexity
heavy configuration
```

## 28.3 Murex

Borrow:

```text
front-to-risk workflow
trade valuation architecture
scenario risk
```

Avoid:

```text
monolithic architecture
opaque setup
```

## 28.4 Numerix

Borrow:

```text
derivatives model library
structured product analytics
scenario pricing
```

Avoid:

```text
black-box model dependency
```

## 28.5 OpenGamma

Borrow:

```text
curve-centric analytics
risk factor explain
market data snapshots
```

---

# 29. Roadmap

## 29.1 Version 0.5 — Stabilized prototype

Goals:

```text
remove duplicate YieldCurve
add services layer skeleton
fix P0 model bugs
add model warnings
improve tests
```

## 29.2 Version 1.0 — Demo workstation

Goals:

```text
workflow UI
Portfolio center
Market Data snapshots
Pricing services
VaR service
Stress service
Model Governance screen
```

## 29.3 Version 1.5 — Professional workstation

Goals:

```text
position persistence
report export
more robust FI
dual-curve IRS
real OFZ/RUONIA data provider
audit trail
CI/CD
```

## 29.4 Version 2.0 — Institutional platform candidate

Goals:

```text
multi-portfolio support
role-based workflows
economic capital
limit monitoring
backtesting dashboard
model approval workflow
database backend
```

## 29.5 Version 3.0 — Platform

Goals:

```text
multi-user
API layer
scheduled batch risk
external data providers
reporting engine
governance workflow
```

---

# 30. Migration Plan

## Phase 1 — Architecture foundation

Deliverables:

```text
domain objects
service layer
single YieldCurve
market data snapshot
governance model definition
```

## Phase 2 — Risk and portfolio foundation

Deliverables:

```text
PortfolioService
RiskFactorExposure
VaRService
StressService
Portfolio workspace redesign
```

## Phase 3 — Pricing refactor

Deliverables:

```text
BondPricingService
IRSPricingService
OptionPricingService
PricingResult contract
```

## Phase 4 — Governance

Deliverables:

```text
Model Registry screen
production gating
audit events
model warnings
```

## Phase 5 — UI redesign

Deliverables:

```text
shared components
workspace layout
dashboard redesign
light/dark themes
```

## Phase 6 — Persistence

Deliverables:

```text
SQLite prototype
PostgreSQL target
market data snapshots
saved portfolios
saved results
```

---

# 31. Production Readiness Criteria

RiskCalc is demo-ready when:

```text
P0 bugs fixed
CI tests pass
UI opens all workspaces
demo data clearly marked
model statuses visible
portfolio risk aggregation no longer mixes raw Greeks
```

RiskCalc is professional-workstation-ready when:

```text
market data snapshots exist
pricing services exist
portfolio service exists
VaR/stress services exist
governance screen exists
audit trail exists
```

RiskCalc is production-candidate when:

```text
fixed income conventions are real
IRS is dual-curve
FRN uses reset/projection logic
market data has source and valuation date
models have validation status and tests
calculation results are reproducible
```

---

# 32. Appendix A — Current Repository Snapshot

Current Python file groups include:

```text
app/
tests/
models/
instruments/
risk/
curves/
```

Key current files:

- `run_app.py`
- `generate_docs.py`
- `main.py`
- `app/main_window.py`
- `app/chart.py`
- `app/widgets.py`
- `app/styles.py`
- `tests/test_black_scholes.py`
- `tests/test_monte_carlo.py`
- `tests/__init__.py`
- `tests/test_trees.py`
- `tests/test_var.py`
- `models/black_scholes.py`
- `models/registry.py`
- `models/__init__.py`
- `models/monte_carlo.py`
- `models/implied_vol.py`
- `models/short_rate.py`
- `models/heston.py`
- `models/garch.py`
- `models/trees.py`
- `instruments/vanilla.py`
- `instruments/exotic.py`
- `instruments/fixed_income.py`
- `instruments/asian.py`
- `instruments/barrier.py`
- `instruments/__init__.py`
- `instruments/variance_swaps.py`
- `instruments/multi_asset.py`
- `instruments/lookback.py`
- `instruments/fx.py`
- `instruments/credit.py`
- `instruments/digital.py`
- `risk/vol_surface.py`
- `risk/__init__.py`
- `risk/stress.py`
- `risk/var.py`
- `risk/portfolio.py`
- `risk/historical_var.py`
- `curves/russia.py`
- `curves/__init__.py`
- `curves/yield_curve.py`
- `app/panels/lookback_panel.py`
- `app/panels/pnl_panel.py`
- `app/panels/shortrate_panel.py`
- `app/panels/bond_panel.py`
- `app/panels/exotic_panel.py`
- `app/panels/montecarlo_panel.py`
- `app/panels/capfloor_panel.py`
- `app/panels/stochvol_panel.py`
- `app/panels/histvar_panel.py`
- `app/panels/pricing_workspace.py`
- `app/panels/structured_panel.py`
- `app/panels/commodity_panel.py`
- `app/panels/xva_panel.py`
- `app/panels/asian_panel.py`
- `app/panels/analytics_workspace.py`
- `app/panels/risk_workspace.py`
- `app/panels/__init__.py`
- `app/panels/var_panel.py`
- `app/panels/rates_panel.py`
- `app/panels/portfolio_panel.py`
- `app/panels/market_workspace.py`
- `app/panels/dashboard_panel.py`
- `app/panels/credit_panel.py`
- `app/panels/settings_panel.py`
- `app/panels/multiasset_panel.py`
- `app/panels/realoptions_panel.py`
- `app/panels/varswap_panel.py`
- `app/panels/stress_panel.py`
- `app/panels/futures_panel.py`
- `app/panels/yield_curve_panel.py`
- `app/panels/greeks_panel.py`
- `app/panels/irderiv_panel.py`
- `app/panels/volsurface_panel.py`
- `app/panels/irs_panel.py`
- `app/panels/digital_panel.py`
- `app/panels/binomial_panel.py`
- `app/panels/fx_panel.py`
- `app/panels/option_panel.py`
- `app/panels/impliedvol_panel.py`
- `app/panels/barrier_panel.py`
- `instruments/structured/__init__.py`
- `instruments/structured/cln_ftd.py`
- `instruments/structured/phoenix.py`

---

# 33. Appendix B — Target Screen Map

```text
Dashboard
  Overview

Market
  Yield Curves
    Overview
    Curve Builder
    Zero / Par / Forward
    Scenarios
    Validation
  Vol Surfaces
  FX Market
  Credit Curves
  Data Monitor

Pricing
  Rates
    Bond
    FRN
    IRS / OIS
    Cap / Floor / Swaption
  FX
    FX Forward
    FX Option
  Equity
    Vanilla
    Barrier
    Asian
    Digital
    Lookback
    Basket
  Credit
    CDS
    CLN
  Structured
    Autocall
    Phoenix
    Custom Payoff

Portfolio
  Positions
  Exposure
  Performance
  Scenario P&L
  Attribution
  Validation

Risk
  VaR / ES
  Stress
  Backtesting
  Limit Monitoring
  Capital

Governance
  Model Registry
  Validation
  Audit Trail
  Approvals

Analytics
  Numerical Methods
  Stochastic Models
  Rates Models
  Research

Settings
  Appearance
  Data Sources
  Governance Rules
  Defaults
  About
```

---

# 34. Appendix C — AI Agent Implementation Instructions

Any AI coding agent modifying RiskCalc should follow these rules:

1. Do not add more top-level sidebar items.
2. Do not create new panels without assigning them to a product layer.
3. Do not call pricing/risk models directly from UI.
4. Do not duplicate YieldCurve or market data logic.
5. Do not add hardcoded market data without demo/source flags.
6. Do not aggregate raw Greeks across asset classes.
7. Do not silently swallow exceptions.
8. Add tests for every model change.
9. Add model registry metadata for every model.
10. Keep UI components shared and theme-driven.
11. Move research/prototype models to Analytics Lab.
12. Keep Portfolio central.
13. Keep Risk workflow portfolio-based.
14. Keep Pricing instrument-based.
15. Keep Market Data separate from Pricing.

---

# 35. Final Architecture Statement

RiskCalc should be rebuilt around this principle:

```text
Market data feeds pricing.
Pricing feeds portfolio.
Portfolio feeds risk.
Risk feeds governance and reporting.
Analytics Lab feeds future models.
Governance controls what can be trusted.
```

The current project is a strong base. The next stage is not cosmetic redesign. The next stage is architectural replatforming from calculator panels into a workflow-first market risk workstation.


# 36. Implementation Epics

## Epic A — Single Market Data Core

Create a single market data foundation. This epic must remove duplicate curve logic and make all pricing/risk engines consume a consistent market data snapshot.

Tasks:
- create `domain/market_data.py`;
- create `MarketDataSnapshot`;
- migrate `curves/yield_curve.py` into `market/curves/`;
- delete or deprecate `YieldCurve` inside `instruments/fixed_income.py`;
- create curve validation;
- expose source and valuation date in UI.

Definition of done:
- all FI pricing uses the same curve class;
- every curve has label, valuation date, compounding and interpolation method;
- demo curves are marked as demo.


# 37. Implementation Epic B — Portfolio as Center

## Epic B — Portfolio as Center

Portfolio must become the main business object.

Tasks:
- move `risk/portfolio.py` to `portfolio/`;
- split `Position`, `Portfolio`, `PortfolioService`;
- add `RiskFactorExposure`;
- replace raw Greek aggregation;
- redesign Portfolio screen around positions, exposure and P&L.

Definition of done:
- positions can be priced;
- position-level errors are visible;
- exposures are grouped by factor type;
- charts do not multiply Greeks artificially.


# 38. Implementation Epic C — Risk Service Layer

## Epic C — Risk Service Layer

VaR and stress calculations must be services over a portfolio.

Tasks:
- consolidate `risk/var.py` and `risk/historical_var.py`;
- create `VaRRequest` and `VaRResult`;
- create `StressRequest` and `StressResult`;
- add portfolio-level risk runs;
- add backtesting service.

Definition of done:
- VaR methods share one loss convention;
- ES is consistently calculated;
- backtesting works on a VaR series;
- stress uses factor shocks.


# 39. Implementation Epic D — Governance

## Epic D — Governance

The registry must become an active governance layer.

Tasks:
- move registry to `governance/registry`;
- add `production_allowed`;
- add model version;
- add owner;
- add last validation date;
- add UI screen for model registry;
- block broken/placeholder models outside Analytics Lab.

Definition of done:
- every calculation exposes model status;
- prototype models show warnings;
- broken models are blocked;
- audit trail records model id and version.


# 40. Implementation Epic E — UI Shell

## Epic E — UI Shell

The UI should become a thin workflow surface.

Tasks:
- create shared UI components;
- remove duplicated `_ModuleCard`;
- implement workspace landing component;
- remove full validation from dashboard;
- group pricing modules;
- add model warnings and data status chips.

Definition of done:
- no panel hardcodes full design system;
- light and dark theme use the same tokens;
- dashboard is clean and executive;
- workspaces are grouped by business domain.


# 41. RiskCalc 2.0 North-Star Workflow

The final north-star workflow is:

```text
1. User opens Dashboard.
2. User confirms market data status.
3. User opens Portfolio.
4. User loads or reviews positions.
5. System prices portfolio using governed models.
6. User opens Risk.
7. System calculates VaR, ES and stress.
8. User opens Model Governance if warnings exist.
9. User exports or saves a report.
```

Everything in the product must support this workflow.


# 42. Architectural Risks

## Main architectural risks

1. Continuing to add panels instead of services.
2. Continuing to add models without governance.
3. Making UI beautiful before fixing data/model boundaries.
4. Treating demo market data as real.
5. Keeping fixed income as simplified formulas.
6. Aggregating Greeks without risk factor mapping.
7. Allowing research models to leak into production workflows.

Mitigation:
- enforce service layer;
- enforce model registry;
- enforce tests;
- enforce data snapshots;
- enforce product-layer ownership.


# 43. Final Roadmap Table

| Release | Theme | Main Outcome |
|---|---|---|
| 0.5 | Stabilization | Existing prototype stops producing misleading results |
| 1.0 | Workflow Demo | RiskCalc becomes coherent demo workstation |
| 1.5 | Professionalization | Market data, portfolio, risk and governance mature |
| 2.0 | Institutional Candidate | Audit, persistence, validation and reporting exist |
| 3.0 | Platform | Multi-user, API, batch risk and external integrations |
