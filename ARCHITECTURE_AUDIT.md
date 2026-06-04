# Architecture Audit

Date: 2026-06-04

Scope:

- Current repository state after service-boundary, market-data, portfolio, VaR/ES, and fixed-income pricing-wrapper work.
- Target architecture from `PRODUCT_ARCHITECTURE.md`.
- No production code changes are included in this audit.

## 1. Current Implemented Architecture

The repository is now a hybrid of the original calculator/prototype architecture and the emerging RiskCalc 2.0 service/domain architecture.

Implemented top-level architecture:

- `domain/` contains early domain contracts:
  - `MarketDataSnapshot` and `MarketDataSource` in `domain/market_data.py:13`.
  - `Position` and `Portfolio` in `domain/portfolio.py:8`.
  - `RiskFactorExposure` and canonical exposure buckets in `domain/risk_factors.py:7`.
  - Generic `PricingResult`, `BondPricingRequest`, and `BondPricingResult` in `domain/results.py:9`.
- `services/` contains application-service facades:
  - `MarketDataService` creates demo/manual snapshots and curves in `services/market_data_service.py:10`.
  - `PricingService` wraps selected pricing engines with governance, warnings, errors, and market-data metadata in `services/pricing_service.py:23`.
  - `RiskService` wraps selected VaR/ES/stress functions in `services/risk_service.py:12`.
  - `PortfolioService` owns portfolio pricing, exposure buckets, and first-order scenario P&L in `services/portfolio_service.py:20`.
  - `GovernanceService` normalizes `models.registry` entries in `services/governance_service.py:13`.
- `models/`, `instruments/`, `risk/`, and `curves/` still contain most quantitative engines and remain callable directly.
- `app/panels/` still contains thick UI panels with many direct imports from `models/`, `instruments/`, `risk/`, and `curves/`.
- `risk/portfolio.py` is a backward-compatible facade over `PortfolioService` in `risk/portfolio.py:1`.
- Tests now cover service boundaries, market-data foundation, portfolio service, VaR conventions, fixed-income pricing wrapper, and selected model baselines.

Current dependency direction for migrated paths:

```text
domain <- services <- selected tests / risk.portfolio facade
services -> models / instruments / risk / curves
MarketDataService -> curves.yield_curve / curves.russia
PricingService -> instruments.vanilla / instruments.fixed_income / instruments.fx
RiskService -> risk.var / risk.stress
PortfolioService -> PricingService / MarketDataService / selected raw credit engine
UI panels -> still often call raw engines directly
```

## 2. Target Architecture From PRODUCT_ARCHITECTURE.md

The target architecture is workflow-first and portfolio-centered. `PRODUCT_ARCHITECTURE.md` states the required product shift:

```text
Market Data Platform
+ Pricing Platform
+ Portfolio Platform
+ Risk Platform
+ Model Governance Platform
+ Analytics Lab
+ Workflow UI
```

Target dependency rules:

- UI depends on services, not raw quant functions.
- Services depend on domain contracts and quantitative engines.
- Pricing and risk results are linked to market-data snapshots.
- Portfolio is the central object for valuation, exposures, VaR, stress, P&L explain, and scenario P&L.
- Market data owns source, date, quality, curves, volatility surfaces, FX rates, and credit spreads.
- Pricing consumes market data and model registry status.
- Risk consumes portfolio, market data, pricing, and governed models.
- Prototype/broken models remain available in Analytics Lab, not silent production workflows.
- Model registry is the source of truth for model status, limitations, and production eligibility.

`PRODUCT_ARCHITECTURE.md` also gives the desired fixed-income service pattern:

```text
BondPricingService.price(request)
  -> validate_request
  -> market_data_service.get_curve(request.curve_id)
  -> registry.get("fixed_bond")
  -> bond_engine.price(...)
  -> enrich_with_model_status
```

The current `PricingService.price_bond()` now follows this pattern partially through `MarketDataService.get_curve()` and `GovernanceService`, but still wraps the legacy `fixed_bond()` engine.

## 3. Gap Analysis

### Implemented Correctly

- A real domain/service split now exists.
- `MarketDataSnapshot` makes DEMO/MANUAL/MOEX/CSV source categories explicit in `domain/market_data.py:13`.
- `YieldCurve` has canonical ownership in `curves/yield_curve.py:70` and validates tenor/rate shape, finite nodes, positive discount factors, and node-level monotonic discount factors in `curves/yield_curve.py:99`.
- `PricingService._result()` attaches `model_id`, `model_status`, warnings, errors, `market_data_snapshot_id`, source, and quality in `services/pricing_service.py:49`.
- `PricingService.price_bond()` has a safe service boundary, `BondPricingRequest`, `BondPricingResult`, market-data routing, governance metadata, and explicit approximation warnings in `services/pricing_service.py:121`.
- VaR/ES conventions were consolidated around positive losses in `risk/var.py:50`, with shared validation for confidence, horizon, finite inputs, and ES >= VaR behavior.
- `PortfolioService` is now the main owner of portfolio valuation state and exposure aggregation in `services/portfolio_service.py:20`.
- `risk.portfolio.Portfolio` preserves the old import path while delegating to `PortfolioService` in `risk/portfolio.py:1`.

### Still Incomplete

- UI panels still bypass services directly. Examples:
  - `app/panels/bond_panel.py` imports `fixed_bond` directly.
  - `app/panels/var_panel.py` imports `historical_var`, `parametric_var`, `montecarlo_var`, and `evt_var` directly.
  - `app/panels/rates_panel.py` imports `fixed_bond`, `irs`, `cap_floor`, `collar`, and `swaption` directly.
  - `app/panels/option_panel.py` imports `instruments.vanilla` and `models.implied_vol` directly.
- `RiskService._result()` does not yet include `market_data_source` or `market_data_quality`, unlike `PricingService._result()`; see `services/risk_service.py:32`.
- `PortfolioService.price_all()` silently catches all pricing exceptions and replaces valuation with NaN without preserving errors or warnings; see `services/portfolio_service.py:48`.
- Bond and IRS portfolio paths still construct or pass curves directly instead of using `MarketDataSnapshot` IDs; see `services/portfolio_service.py:118` and `services/portfolio_service.py:145`.
- Credit pricing inside `PortfolioService` still calls `instruments.credit` directly instead of `PricingService`; see `services/portfolio_service.py:130`.
- Market data service is still labelled a skeleton in `services/market_data_service.py:1` and only creates demo/manual curves; it has no external loaders, no snapshot validation method, no volatility/FX/credit loaders, and no persistence.
- `YieldCurve.rate()` still clips interpolated rates silently in `curves/yield_curve.py:138`, which conflicts with production validation requirements.
- Fixed-income analytics remain legacy approximations. `BondPricingResult` explicitly reports clean price equal to dirty price and accrued interest equal to zero via `services/pricing_service.py:159`.
- Monte Carlo full repricing VaR still swallows pricing failures by appending zero P&L in `risk/historical_var.py:169`.

## 4. Service Layer Maturity

Maturity: 5/10.

Implemented:

- `PricingService` is the most mature service. It wraps vanilla option, bond, IRS, FX forward, and FX option paths with model governance and structured dict results in `services/pricing_service.py:90`.
- `price_bond()` is now a useful fixed-income boundary and explicitly refuses to imply production readiness through audit warnings in `services/pricing_service.py:15`.
- `RiskService` provides historical VaR, parametric VaR, ES wrapper, and option stress wrapper in `services/risk_service.py:71`.
- `PortfolioService` coordinates position pricing, exposures, aggregation, and scenario P&L in `services/portfolio_service.py:93`.
- `GovernanceService` converts registry entries into `ModelDefinition` and derives warnings in `services/governance_service.py:16`.

Incomplete skeletons / temporary service code:

- `services/__init__.py` still describes the service layer as a skeleton.
- `services/market_data_service.py:1` still describes MarketDataService as a skeleton.
- `RiskService` lacks portfolio-level VaR, stress, P&L explain, backtesting, MC VaR, EVT VaR, and market-data source fields.
- `PricingService` is still a facade over old function signatures, not a complete pricing platform with request/result objects for every product.
- `PortfolioService` has temporary first-order scenario P&L and unit aggregation; it is not yet a full P&L explain engine.

Architectural risks:

- Service methods mostly return dicts rather than mandatory typed result contracts.
- Service wrappers catch exceptions and return structured errors, but downstream code sometimes discards those errors.
- UI has not been migrated to service entry points, so the service layer is canonical only for tests and selected compatibility paths.

## 5. Domain Layer Maturity

Maturity: 4/10.

Implemented:

- Domain contracts exist for market data, portfolio, risk factors, model governance, and partial pricing results.
- `MarketDataSnapshot` includes valuation date, source, quality, curves, vol surfaces, FX rates, credit spreads, and metadata in `domain/market_data.py:20`.
- `Position` includes valuation fields and risk fields in `domain/portfolio.py:8`.
- `RiskFactorExposure` has bucket, factor, currency, bump size, sensitivity, and unit in `domain/risk_factors.py:10`.
- `BondPricingRequest` and `BondPricingResult` are explicit fixed-income DTOs in `domain/results.py:25`.

Incomplete:

- `Position.params` is still an untyped dict in `domain/portfolio.py:16`, so instrument schemas are not enforced.
- `Portfolio` has no portfolio ID, base currency, valuation date, owner/book hierarchy, scenario context, or audit metadata.
- `PricingResult` is generic but not widely used by `PricingService`, which still returns dicts.
- There are no domain contracts for option requests, IRS requests, FX requests, risk requests, VaR results, stress results, scenario P&L, P&L explain, model usage audit, or market-data validation reports.
- `RiskFactorBucket` does not include commodity or inflation and allows `"Unclassified"` only via a loose `str` fallback.

## 6. Market Data Maturity

Maturity: 5/10.

Implemented:

- Market-data source metadata exists with `DEMO`, `MANUAL`, `MOEX`, and `CSV` in `domain/market_data.py:13`.
- `MarketDataService.demo_snapshot()` creates one coherent demo snapshot with flat, OFZ, RUONIA, CBR key-rate, and corporate demo curves in `services/market_data_service.py:13`.
- `MarketDataService.get_curve()` centralizes curve lookup from a snapshot in `services/market_data_service.py:127`.
- `YieldCurve.validate()` rejects NaN/inf tenors, NaN/inf zero rates, non-positive tenors, duplicate tenors, non-positive node discount factors, and node-level non-monotonic discount factors in `curves/yield_curve.py:99`.

Incomplete:

- No snapshot-level validator exists for curves, volatility surfaces, FX rates, or credit spreads.
- No production source adapters exist for MOEX or CSV.
- No immutable snapshot repository, hash, timestamp lineage, or audit trail exists.
- `MarketDataService` still uses `curves.russia` demo constants directly in `services/market_data_service.py:5`.
- `YieldCurve.rate()` silently clips interpolated/extrapolated rates in `curves/yield_curve.py:138`; this can mask invalid market data.
- Dense-grid validation of interpolated/extrapolated discount factors is not implemented.
- Vol surfaces remain in `risk/vol_surface.py`, not a market-data-owned service.

## 7. Portfolio Layer Maturity

Maturity: 5/10.

Implemented:

- Portfolio has moved into `domain/portfolio.py` and `services/portfolio_service.py`.
- Backward compatibility is preserved through `risk/portfolio.py`.
- `PortfolioService` owns `price_all()`, `aggregate()`, `positions_table()`, exposure buckets, and first-order `scenario_pnl()` in `services/portfolio_service.py:183`.
- Exposure buckets include Rates, FX, Equity, Credit, and Volatility in `services/portfolio_service.py:11`.

Incomplete:

- `price_all()` silently suppresses exceptions and loses diagnostics in `services/portfolio_service.py:48`.
- Bond and IRS positions still use direct curve objects or ad hoc flat curves rather than market-data snapshot IDs in `services/portfolio_service.py:118` and `services/portfolio_service.py:145`.
- Credit instruments bypass `PricingService` in `services/portfolio_service.py:130`.
- Portfolio aggregation still exposes raw Greek totals for backward compatibility in `services/portfolio_service.py:188`.
- Scenario P&L is first-order and unit-mixed; it is not full scenario repricing.
- No portfolio import/export, position validation, portfolio valuation result, audit trail, or market-data snapshot binding exists.

## 8. Risk Layer Maturity

Maturity: 5/10.

Implemented:

- Historical, weighted historical, parametric, and Monte Carlo VaR share the positive-loss VaR/ES helper in `risk/var.py:50`.
- Input validation for confidence, horizon, finite one-dimensional arrays, and weights exists in `risk/var.py:21`.
- `RiskService` provides governed wrappers for historical VaR, parametric VaR, ES, and option stress in `services/risk_service.py:71`.
- Existing VaR tests cover known arrays, weighted VaR, ES >= VaR, horizon scaling, invalid confidence, and NaN/empty inputs.

Incomplete:

- RiskService does not yet route portfolio-level risk by default.
- `RiskService.expected_shortfall()` mutates the returned dict from VaR wrappers rather than returning a distinct typed ES result in `services/risk_service.py:107`.
- Stress testing is still option-specific, not portfolio-level; see `services/risk_service.py:125`.
- MC full repricing still treats failed repricing scenarios as zero P&L in `risk/historical_var.py:169`.
- EVT VaR and backtesting are not exposed by `RiskService`.
- Risk results lack market-data source/quality fields.
- Risk factor aggregation is only partially connected to risk calculations.

## 9. Pricing Layer Maturity

Maturity: 5/10.

Implemented:

- `PricingService` is a canonical service entry point for selected instruments.
- Model governance is attached through `GovernanceService` in `services/pricing_service.py:59`.
- Market-data snapshot ID, source, and quality are included in pricing service results in `services/pricing_service.py:63`.
- Fixed-income bond service boundary is explicit and warns about approximation limitations in `services/pricing_service.py:15`.
- Legacy engines remain unchanged, preserving backward compatibility.

Incomplete:

- Most UI pricing panels still call raw engines directly instead of `PricingService`.
- Fixed-income engines remain simplified:
  - Bond clean/dirty/accrued are not real; the service currently reports clean equal to dirty and accrued equal to zero.
  - IRS is single-curve and lacks schedule/day-count/fixing conventions.
  - FRN remains prototype and is not safely routed through service.
- `PricingService.price_irs()` does not yet attach IRS-specific audit warnings comparable to bond warnings.
- No typed request/result contracts exist for option, IRS, FX, credit, structured, exotic, or rates derivative pricing.
- There is no product-level pricing engine registry separate from model registry.

## 10. Governance Maturity

Maturity: 6/10.

Implemented:

- `models/registry.py` is the central model inventory and includes statuses such as `Validated`, `Approximation`, `Prototype`, `Placeholder`, and `Broken`.
- `GovernanceService.get_model()` maps registry entries into domain `ModelDefinition` in `services/governance_service.py:16`.
- `GovernanceService.warnings_for_model()` surfaces model limitations and flags non-production models in `services/governance_service.py:40`.
- `PricingService` and `RiskService` call `GovernanceService` for migrated paths.

Incomplete:

- Registry usage is not enforced globally; UI and raw engine calls can bypass it.
- `Approximation` is currently treated as production allowed in `services/governance_service.py:7`; this is acceptable for demo workflows but too permissive for production gates.
- There is no model usage audit trail, validation evidence store, approval workflow, owner enforcement, or runtime production-mode gate.
- No test ensures every UI workflow reaches models through `GovernanceService`.
- Unknown models become `Placeholder` through `models/registry.py`, but direct raw calls do not trigger that governance path.

## 10.1 Analytics Lab Separation

Analytics Lab separation is now documented in `ANALYTICS_LAB_ARCHITECTURE.md`.

Production workflow ownership is restricted to governed service paths for Bond,
VaR, Stress, IRS, and FX. Research ownership is assigned to Heston, SABR, GARCH,
and experimental Monte Carlo models.

The active boundary is enforced through model governance flags:

- `workflow_layer`
- `analytics_lab_only`
- `production_allowed`

Pricing and risk service results expose these flags so research models cannot
enter production workflows silently. If a research model is requested through a
service path, the service result must carry warnings.

## 11. Remaining Architectural Violations

P0 - Dangerous:

- `PortfolioService.price_all()` silently swallows all exceptions and sets NaN without preserving errors or warnings. File: `services/portfolio_service.py:48`.
- MC full repricing VaR silently replaces failed repricing with zero P&L. File: `risk/historical_var.py:169`.
- UI production workflows can still bypass governance and service boundaries by importing raw pricing/risk functions directly. Examples include `app/panels/bond_panel.py`, `app/panels/var_panel.py`, and `app/panels/rates_panel.py`.

P1 - Should be fixed:

- Bond and IRS portfolio paths bypass `MarketDataSnapshot` ownership by passing direct curve objects. File: `services/portfolio_service.py:118`, `services/portfolio_service.py:145`.
- Credit pricing bypasses `PricingService`. File: `services/portfolio_service.py:130`.
- `YieldCurve.rate()` silently clips rates. File: `curves/yield_curve.py:138`.
- `RiskService` lacks market-data source/quality metadata parity with `PricingService`. File: `services/risk_service.py:32`.
- `PricingService.price_irs()` lacks explicit audit warnings for single-curve/no-schedule limitations. File: `services/pricing_service.py:211`.
- `Position.params` remains untyped and unvalidated. File: `domain/portfolio.py:16`.

P2 - Cleanup:

- `services/market_data_service.py` and `services/__init__.py` still describe services as skeletons.
- `PricingService` uses typed bond DTOs but generic dict outputs for most other instruments.
- `RiskService.expected_shortfall()` mutates a VaR result instead of returning a dedicated ES result.
- `PortfolioService.aggregate()` still returns raw Greek totals alongside bucketed exposures.
- Volatility surfaces live under `risk/`, not market data.

P3 - Cosmetic:

- Some docstrings still describe prototype or skeleton state even where implementation has advanced.
- Result field names are inconsistent across services: pricing results include source/quality, risk results do not.
- Tests still use path insertion boilerplate in several files.

## 12. Recommended Next 5 Implementation Tasks

1. Fix silent exception handling in portfolio and MC repricing risk.
   - Files: `services/portfolio_service.py`, `risk/historical_var.py`, `tests/test_portfolio_service.py`, `tests/test_var.py`.
   - Goal: preserve errors/warnings in portfolio position state and report MC repricing failure counts instead of zero P&L.

2. Bring `RiskService` result contract to parity with `PricingService`.
   - Files: `services/risk_service.py`, `domain/results.py`, `tests/test_service_boundaries.py`, `tests/test_var.py`.
   - Goal: add source/quality metadata, typed VaR/ES/stress result contracts, and avoid mutating VaR result dicts for ES.

3. Route portfolio bond and IRS pricing through snapshot-based `MarketDataService` paths.
   - Files: `services/portfolio_service.py`, `services/pricing_service.py`, `services/market_data_service.py`, `tests/test_portfolio_service.py`, `tests/test_fixed_income_pricing_service.py`.
   - Goal: remove direct curve passing from normal portfolio workflows while preserving compatibility for legacy params.

4. Add explicit IRS service boundary warnings and a typed IRS request/result.
   - Files: `domain/results.py`, `services/pricing_service.py`, `instruments/fixed_income.py`, `tests/`.
   - Goal: match the bond wrapper standard without rewriting schedules/day-count yet.

5. Start UI-to-service migration with the highest-risk panels first.
   - Files: `app/panels/bond_panel.py`, `app/panels/var_panel.py`, `app/panels/rates_panel.py`, `app/panels/portfolio_panel.py`, service tests.
   - Goal: remove direct UI-to-engine coupling from fixed income and VaR paths while preserving current screens.
