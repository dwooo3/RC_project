# Product Readiness Audit

Date: 2026-06-04

Reference:

- `PRODUCT_ARCHITECTURE.md`
- Current repository state after Market Data Platform, Portfolio Center, Governance v2, Analytics Lab separation, and UI Service Migration Wave 1.

Scoring:

- 0 = absent
- 5 = usable prototype foundation
- 10 = production-ready target architecture

## Executive Summary

RiskCalc has moved beyond a pure calculator prototype. It now has recognizable domain contracts, service entry points, market-data snapshots, portfolio-centered valuation/risk results, model governance metadata, and a separated Analytics Lab boundary.

It is not production-ready. The main blockers are fixed-income methodology, incomplete portfolio-level risk workflows, remaining direct UI-to-engine coupling outside Wave 1 panels, lack of real market-data ingestion, limited audit/reproducibility, and incomplete validation/gating of production workflows.

Overall readiness score: 5/10.

## 1. Architecture

Score: 6/10.

Current state:

- `domain/` and `services/` now exist as explicit architectural layers.
- `MarketDataService`, `PricingService`, `RiskService`, `PortfolioService`, and `GovernanceService` are active entry points.
- `PRODUCT_ARCHITECTURE.md` target of Market Data + Pricing + Portfolio + Risk + Governance + Analytics Lab is partially implemented.
- `ANALYTICS_LAB_ARCHITECTURE.md` defines production vs research ownership.

Risks:

- The repository still uses legacy top-level engine folders: `models/`, `instruments/`, `risk/`, `curves/`.
- Many UI panels outside Wave 1 can still call engines directly.
- Services still wrap legacy dict-returning engines rather than owning full typed request/result workflows.

Missing functionality:

- Target `market/`, `pricing/`, `portfolio/`, `risk/`, `governance/`, `analytics/` physical module split.
- Complete dependency enforcement tests.
- Production workflow orchestrator for load market data -> value portfolio -> calculate risk -> export report.

Next actions:

- Add static dependency tests for UI -> services only.
- Continue UI-to-service migration for rates, IRS, FX, option, portfolio, and market panels.
- Introduce typed request/result contracts per service method before moving folders.

## 2. Market Data

Score: 6/10.

Current state:

- `MarketDataSnapshot` supports source, valuation date, quality, versioning, timestamps, curves, FX rates, vol surfaces, credit curves, credit spreads, source details, and metadata.
- `MarketDataStore` provides in-memory snapshot versioning and lookup.
- `MarketDataService` owns demo, manual, and CSV snapshot factories.
- Provider interfaces exist for MOEX, Bloomberg, and Reuters, intentionally not implemented.

Risks:

- Market data is still mostly demo/manual.
- No real CSV parser is implemented; CSV snapshot factory expects already parsed data.
- MOEX/Bloomberg/Reuters are interface stubs only.
- `YieldCurve.rate()` still clips interpolated rates, which can hide invalid curves.

Missing functionality:

- Snapshot-level validation across curves, FX, vol, and credit data.
- Persistent store with immutable snapshot history.
- Real CSV loader and MOEX adapter.
- Dense-grid validation for interpolated/extrapolated discount factors and forwards.

Next actions:

- Implement `MarketDataService.validate_snapshot()`.
- Add real CSV import for curves, FX, vol, and credit spreads.
- Add strict vs demo validation policy.
- Remove or gate silent curve clipping.

## 3. Pricing

Score: 5/10.

Current state:

- `PricingService` wraps vanilla options, fixed bonds, IRS, FX forwards, and FX options.
- Service results expose governance metadata, warnings, errors, and market-data metadata.
- PricingService enforces model governance before calculation and blocks Placeholder/Broken models.
- `price_bond()` uses `BondPricingRequest` / `BondPricingResult` and clearly marks the calculation as approximation/demo.

Risks:

- Fixed-income engines are not production methodology.
- IRS lacks dual-curve discounting/projection, fixing schedules, calendars, and day-count conventions.
- PricingService still returns dicts for most products.
- Many product panels still bypass PricingService.

Missing functionality:

- Typed request/result contracts for IRS, FX, options, credit, structured products, and exotics.
- Production fixed-income schedule/day-count/accrued interest engine.
- Pricing model selection policy tied to governance.
- Consistent market-data snapshot requirement for all pricing workflows.

Next actions:

- Add `IRSPricingRequest` / `IRSPricingResult` with explicit approximation warnings.
- Migrate `rates_panel.py`, `irs_panel.py`, `fx_panel.py`, and `option_panel.py` to services.
- Implement real fixed-income schedule, settlement, clean/dirty, accrued, duration, convexity, and DV01 methodology.

## 4. Portfolio

Score: 6/10.

Current state:

- `Portfolio` is now a domain object with ID, base currency, valuation date, market-data snapshot ID, owner, metadata, and timestamps.
- `Position` has inferred `PositionType`, model metadata, market-data snapshot ID, warnings, and errors.
- `PortfolioService` owns valuation, exposure aggregation, and scenario P&L.
- `PortfolioValuationResult` and `PortfolioRiskResult` exist.
- `risk.portfolio` remains a backward-compatible facade.

Risks:

- `Position.params` is still untyped and unvalidated.
- Bond/IRS portfolio paths can still use direct curve objects.
- Credit pricing still bypasses PricingService.
- Scenario P&L is first-order and unit-mixed, not full repricing.

Missing functionality:

- Position schemas by product type.
- Portfolio import/export.
- Portfolio-level market-data binding and reproducibility.
- Full scenario repricing and P&L explain.
- Portfolio-level VaR integration through `RiskService`.

Next actions:

- Add typed position specs for equity, option, bond, IRS, FX, and credit.
- Route bond/IRS portfolio positions through snapshot IDs.
- Move credit pricing behind PricingService.
- Add portfolio-level risk service methods.

## 5. Risk

Score: 5/10.

Current state:

- VaR/ES loss convention is consolidated: positive losses, positive VaR, ES >= VaR.
- Historical, weighted historical, parametric, Monte Carlo, EVT, P&L-based historical, age-weighted, stress, and reverse stress are available through RiskService.
- Risk results expose governance and market-data metadata.
- RiskService enforces model governance before calculation and blocks Placeholder/Broken models.

Risks:

- RiskService is still mostly single-series or option-stress oriented, not portfolio-centered.
- Full-repricing MC VaR still has unresolved failure-handling risk in legacy functions.
- Backtesting is not exposed as a governed service path.
- Stress is not yet portfolio-level.

Missing functionality:

- Portfolio VaR as the default workflow.
- Backtesting service result contract.
- Scenario P&L integration with PortfolioService.
- Component VaR and risk factor aggregation through `RiskFactorExposure`.
- Data-source gating for synthetic/demo returns.

Next actions:

- Add `PortfolioRiskRequest` and `PortfolioRiskResult` integration in RiskService.
- Expose backtesting through RiskService.
- Fix MC full repricing failure policy.
- Route stress testing through portfolio scenarios rather than option-only shocks.

## 6. Governance

Score: 7/10.

Current state:

- `ModelRegistryEntry` exists with model ID, version, owner, status, validation date, limitations, and documentation link.
- Statuses include Validated, Approximation, Prototype, Placeholder, and Broken.
- PricingService and RiskService consume GovernanceService.
- PricingService and RiskService now enforce GovernanceService before running calculations.
- Service results expose model metadata and production flags.
- Prototype/research models generate warnings.
- Analytics Lab separation adds `workflow_layer`, `analytics_lab_only`, and `production_allowed`.
- Analytics Lab models are blocked in production service paths unless `allow_analytics_lab=True` is explicitly set.

Risks:

- Owners, versions, documentation links, and validation dates are sparse.
- Direct raw engine calls can bypass governance outside service-migrated workflows.
- Approximation models may still be production-allowed for demo workflow continuity.
- Governance enforcement is currently strongest in PricingService and RiskService; raw engine modules remain callable by legacy code.

Missing functionality:

- Validation evidence repository.
- Model approval workflow.
- Audit trail of model usage per calculation.
- Global dependency enforcement proving all production UI paths route through governed services.

Next actions:

- Require owner/version/documentation for production models.
- Add model usage audit records to pricing/risk/portfolio results.
- Add tests proving raw UI-to-engine paths cannot enter production workflows.
- Extend governance enforcement to remaining service surfaces and UI migration smoke tests.

## 7. Analytics

Score: 6/10.

Current state:

- Analytics Lab ownership is documented.
- Research models include Heston, SABR, GARCH, short-rate models, and experimental Monte Carlo.
- Governance flags mark research models as Analytics Lab only and not production allowed.
- Research models can remain callable in lab panels without silently entering production service paths.
- Service-layer Analytics Lab execution requires explicit opt-in through `allow_analytics_lab=True`.

Risks:

- Analytics Lab still shares physical folders with production engines.
- Research panels can still call raw models directly if not migrated to lab-specific services.
- No notebook or experiment registry exists.
- Promotion path is documented but not automated.

Missing functionality:

- Physical research module boundary.
- Experiment metadata, reproducibility, and comparison reports.
- Promotion checklist enforcement.
- Research notebook storage convention.

Next actions:

- Add `analytics/` ownership docs or package when folder movement is safe.
- Add experiment registry metadata for research runs.
- Add tests that research-only models are blocked in strict production mode.
- Define notebook/report storage standards.

## 8. UI

Score: 4/10.

Current state:

- UI has workspace-level structure: Dashboard, Market, Pricing, Portfolio, Risk, Analytics, Settings.
- Wave 1 migrated `bond_panel.py`, `var_panel.py`, `histvar_panel.py`, and `stress_panel.py` to services.
- Existing layout and styles were preserved.
- Service warnings are displayed in Banner for migrated panels.

Risks:

- Many panels remain thick and directly call models/instruments/risk functions.
- UI can still bypass governance in non-migrated workflows.
- UI still mixes parsing, calculation, formatting, and charting logic.
- Some docs may overstate old direct-coupling examples after Wave 1.

Missing functionality:

- Service-only UI dependency policy across all production panels.
- Central calculation controller or view model layer.
- Consistent warning/error rendering.
- Workflow-first screens for full portfolio risk lifecycle.

Next actions:

- Migrate rates, IRS, FX, option, portfolio, market, and pricing workspace paths.
- Add static import tests for all production panels.
- Keep Analytics Lab panels visibly research-governed.
- Avoid visual redesign until service migration is complete.

## 9. Testing

Score: 6/10.

Current state:

- Full suite currently covers market data, governance, portfolio, service boundaries, UI service migration smoke tests, fixed-income wrapper, VaR, Black-Scholes, trees, and Monte Carlo.
- Recent full run passed 101 tests.
- Tests protect backward compatibility for legacy service paths.

Risks:

- Tests are mostly unit/smoke tests, not workflow/integration tests.
- UI tests are static import checks, not interactive panel tests.
- Fixed-income methodology tests are insufficient for production.
- No CI evidence is documented in this audit.

Missing functionality:

- End-to-end workflow tests.
- Portfolio valuation/risk integration tests with market-data snapshots.
- Production-mode governance tests.
- UI smoke tests with Qt interaction where practical.
- Regression baselines for fixed-income and risk model methodology.

Next actions:

- Add workflow test: create snapshot -> create portfolio -> value -> risk -> scenario P&L.
- Add strict governance-mode tests.
- Add fixed-income benchmark tests after methodology refactor.
- Add static dependency tests for all production UI panels.

## 10. Production Readiness

Score: 4/10.

Current state:

- Architecture foundation is credible and improving.
- Core services exist and are tested.
- Market data snapshots, portfolio result objects, governance metadata, and Analytics Lab separation are in place.
- Backward compatibility has been preserved.

Risks:

- Quant methodology remains prototype-grade in fixed income and several risk areas.
- Real market-data ingestion is not implemented.
- Governance is not an enforcement gate yet.
- UI still has legacy direct-engine paths.
- No persistence, audit trail, security model, CI/CD, release process, or reproducibility framework is complete.

Missing functionality:

- Production market data adapters and storage.
- Portfolio-centered VaR/stress/P&L explain.
- Production fixed-income methodology.
- Hard production gating for model status and data quality.
- End-to-end auditability and reproducible calculation records.

Next actions:

1. Complete UI-to-service migration for remaining production panels.
2. Implement snapshot validation and CSV ingestion.
3. Refactor fixed-income methodology.
4. Add strict governance production mode.
5. Build end-to-end portfolio valuation/risk workflow tests.

## Score Summary

| Area | Score |
| --- | ---: |
| Architecture | 6 |
| Market Data | 6 |
| Pricing | 5 |
| Portfolio | 6 |
| Risk | 5 |
| Governance | 7 |
| Analytics | 6 |
| UI | 4 |
| Testing | 6 |
| Production Readiness | 4 |

Average score: 5.5/10.

Readiness classification: strong architectural prototype, not production-ready.
