# Release Candidate Audit

Date: 2026-06-04

Reference:

- `PRODUCT_ARCHITECTURE.md`
- Current repository state after Market Data Platform, Portfolio Center, Fixed Income Professionalization, Scenario Engine Foundation, PnL Explain Foundation, Governance Enforcement, Analytics Lab separation, and UI Replatforming preparation.

Scoring:

- 0 = absent
- 5 = usable prototype foundation
- 10 = production-ready target architecture

## Executive Decision

RiskCalc should currently be classified as:

```text
Advanced Prototype
```

It is no longer a simple prototype. The repository now has explicit domain contracts, service entry points, market-data snapshots, governed pricing/risk service paths, portfolio-centered valuation and risk-factor aggregation, scenario P&L, PnL Explain, an Analytics Lab boundary, and a shared UI component/theme foundation.

It is not yet a Professional Workstation because major workflows still rely on simplified engines, demo/manual market data, partial UI-to-service migration, and incomplete portfolio-level risk workflows.

It is not a Production Candidate because production requirements from `PRODUCT_ARCHITECTURE.md` remain incomplete: real market-data ingestion and persistence, end-to-end auditability, validated model evidence, full workflow UI enforcement, CI/release process, and production-grade fixed-income/risk methodology.

## Classification Threshold

| Classification | Meaning | RiskCalc Status |
| --- | --- | --- |
| Prototype | Calculator/model collection with limited architecture | Exceeded |
| Advanced Prototype | Coherent architecture foundation with tested service/domain paths | Current |
| Professional Workstation | Workflow-first user experience with credible desk-level analytics | Not yet |
| Production Candidate | Auditable, validated, reproducible, governed, deployable system | Not yet |

## 1. Architecture

Maturity score: 7/10.

Current maturity:

- `domain/`, `services/`, and `ui/` are now explicit architecture layers.
- Core service entry points exist: `MarketDataService`, `PricingService`, `RiskService`, `PortfolioService`, `GovernanceService`.
- Workflow foundations now exist for portfolio valuation, risk-factor aggregation, scenarios, PnL Explain, model governance, and Analytics Lab separation.
- Backward compatibility layers remain in place, especially `risk.portfolio`.

Remaining risks:

- Legacy engine folders `models/`, `instruments/`, `risk/`, and `curves/` still coexist with the target service/domain architecture.
- Some UI panels and raw modules can still bypass service boundaries.
- Physical target structure from `PRODUCT_ARCHITECTURE.md` is not fully realized.

Blockers:

- No global dependency enforcement proving production UI paths can only call services.
- No production workflow orchestrator for load market data -> value portfolio -> risk -> scenario -> PnL Explain -> export.

Recommended next actions:

- Add dependency tests blocking UI imports from `models`, `instruments`, `risk`, and `curves` for production panels.
- Create end-to-end workflow test around `MarketDataSnapshot`, `PortfolioService`, `RiskService`, `Scenario`, and `PnLExplainResult`.
- Continue incremental module migration only after service contracts stabilize.

## 2. Domain Layer

Maturity score: 7/10.

Current maturity:

- Domain contracts exist for market data, model governance, portfolio, risk factors, scenarios, pricing results, bond requests/results, and PnL Explain.
- `RiskFactor`, `RiskFactorExposure`, and `RiskFactorGroup` support portfolio aggregation by factor hierarchy.
- `Scenario`, `ScenarioShock`, and `ScenarioResult` provide a unified scenario framework.
- `PnLExplainResult` enforces explicit total/explained/residual reconciliation.

Remaining risks:

- `Position.params` is still an untyped dictionary.
- Many service methods still return structured dictionaries rather than typed result objects.
- Product-specific request/result contracts are incomplete outside bonds and PnL Explain.

Blockers:

- No typed position schemas by asset class.
- No model usage audit domain object.
- No market-data validation report domain object.

Recommended next actions:

- Introduce typed position specs for equity, option, bond, IRS, FX, and credit.
- Add typed request/result contracts for VaR, ES, stress, IRS, FX, and credit.
- Add calculation audit record contracts linking portfolio, market data, model metadata, and result IDs.

## 3. Services

Maturity score: 7/10.

Current maturity:

- Services are canonical for many new workflows.
- Pricing and risk services now enforce governance before calculations.
- PortfolioService owns valuation, risk-factor aggregation, scenario P&L, contribution analysis, and PnL Explain.
- MarketDataService owns snapshots, curves, FX, vol, credit containers, and source metadata.

Remaining risks:

- Services still wrap legacy engines rather than owning complete product engines.
- PortfolioService still handles some raw instrument logic directly, especially credit.
- Several services return dictionaries rather than typed result contracts.

Blockers:

- No full portfolio VaR/stress service workflow.
- No complete calculation lifecycle service tying market data, portfolio, pricing, risk, governance, and audit.

Recommended next actions:

- Add `PortfolioRiskRequest` and route portfolio VaR/stress through RiskService.
- Move credit pricing behind PricingService.
- Standardize typed service result objects.

## 4. Market Data

Maturity score: 6/10.

Current maturity:

- `MarketDataSnapshot`, `MarketDataStore`, and `MarketDataSource` exist.
- Sources include DEMO, MANUAL, CSV, MOEX, Bloomberg, and Reuters interfaces.
- Snapshots own curves, FX rates, volatility surfaces, credit curves, and credit spreads.
- Yield curves validate finite nodes and positive/monotonic discount factors at nodes.

Remaining risks:

- Market data remains mostly demo/manual.
- CSV support is architecture-level, not a full production parser.
- MOEX/Bloomberg/Reuters adapters are not implemented.
- Snapshot validation is incomplete across all data types.

Blockers:

- No persistent immutable market-data store.
- No lineage/hash/audit trail for snapshots.
- No real source adapter with operational error handling.

Recommended next actions:

- Implement snapshot validation across curves, FX, vol, credit.
- Implement real CSV ingestion.
- Add MOEX adapter before any production-readiness claim.
- Add immutable snapshot IDs/hash lineage.

## 5. Pricing

Maturity score: 6/10.

Current maturity:

- PricingService supports vanilla options, fixed bonds, IRS, FX forwards, and FX options.
- PricingService attaches model metadata, market-data metadata, warnings, and errors.
- PricingService enforces governance and blocks Placeholder/Broken models.
- PricingService includes curve shock support for parallel shifts, steepeners, and flatteners.

Remaining risks:

- Most pricing workflows still use generic dict results.
- IRS remains a single-curve approximation.
- Credit and some structured/exotic paths are not consistently routed through PricingService.
- UI pricing panels are not fully migrated.

Blockers:

- No typed request/result contracts for most products.
- No product-level pricing model selection policy beyond model registry.
- No full market-data snapshot requirement across every pricing method.

Recommended next actions:

- Add typed IRS, FX, option, and credit pricing contracts.
- Route remaining production pricing panels through PricingService.
- Add model-specific limitations for IRS and FX paths comparable to fixed bond.

## 6. Fixed Income

Maturity score: 6/10.

Current maturity:

- Fixed-rate bond pricing now supports ACT/365F, ACT/360, 30/360, regular coupon schedules, settlement handling, business-day adjustment, clean price, dirty price, accrued interest, duration, convexity, and finite-difference DV01.
- `BondPricingRequest` and `BondPricingResult` expose fixed-income conventions through the service boundary.
- Tests validate day counts, schedule generation, business-day adjustment, clean/dirty/accrued consistency, and flat-curve examples.

Remaining risks:

- FRN remains prototype-level.
- IRS lacks production-grade schedules, dual-curve discounting/projection, fixing calendars, and accrual conventions.
- Bond engine lacks external holiday calendars, irregular stub policies, ex-coupon logic, amortization, callable/putable features, and inflation-linked mechanics.

Blockers:

- No professional IRS engine.
- No FRN projection/reset engine.
- No validated benchmark pack against market examples.

Recommended next actions:

- Implement IRS request/result and explicit limitations first.
- Add holiday calendar and stub policy framework.
- Add benchmark tests for bonds and swaps.
- Keep fixed-income models marked Approximation until validation evidence exists.

## 7. Portfolio

Maturity score: 7/10.

Current maturity:

- Portfolio is now a central domain object.
- PortfolioService owns valuation, risk-factor aggregation, scenario P&L, contribution analysis, and PnL Explain.
- Portfolio risk factors are grouped by Rates, FX, Equity, Credit, and Volatility.
- Legacy Greek totals are preserved as compatibility views over factor exposures.

Remaining risks:

- Position schemas are still untyped.
- Some portfolio pricing paths still use direct/ad hoc curve inputs.
- Credit pricing still needs full PricingService ownership.
- Scenario and PnL Explain are Greek/exposure-based, not full repricing.

Blockers:

- No portfolio import/export.
- No full portfolio VaR/stress workflow.
- No audit trail binding portfolio valuation to market-data snapshot and model usage record.

Recommended next actions:

- Add typed position specs and validation.
- Bind portfolio valuation/risk runs to immutable market-data snapshots.
- Add full-repricing scenario mode.
- Route portfolio risk through RiskService as default.

## 8. Risk

Maturity score: 6/10.

Current maturity:

- VaR/ES conventions are consolidated around positive loss.
- Historical, weighted historical, parametric, Monte Carlo, EVT, historical P&L, age-weighted P&L, stress, and reverse stress are service-accessible.
- RiskService enforces governance before calculations.
- Scenario engine and PnL Explain now provide portfolio-level risk workflow foundations.

Remaining risks:

- RiskService remains mostly single-series or option-stress oriented.
- Portfolio VaR is not yet the default workflow.
- Backtesting is not a governed service method.
- MC full repricing failure policy remains a risk in legacy code.

Blockers:

- No portfolio-level VaR/ES result contract.
- No scenario full revaluation risk.
- No backtesting service contract.

Recommended next actions:

- Add `PortfolioVaRRequest` / `PortfolioVaRResult`.
- Expose backtesting through RiskService.
- Replace option-only stress with portfolio scenario stress workflow.
- Fix MC repricing failure handling.

## 9. Governance

Maturity score: 7/10.

Current maturity:

- `ModelRegistryEntry` normalizes model metadata.
- Statuses include Validated, Approximation, Prototype, Placeholder, and Broken.
- PricingService and RiskService enforce governance before calculation.
- Broken and Placeholder models are blocked.
- Analytics Lab models are blocked unless `allow_analytics_lab=True`.
- Prototype/research models generate warnings.

Remaining risks:

- Governance can still be bypassed through raw engine imports.
- Approximation models remain allowed for workflow continuity.
- Registry metadata is sparse for owners, versions, validation dates, limitations, and documentation.

Blockers:

- No validation evidence store.
- No model approval workflow.
- No model usage audit trail.
- No global production-mode dependency enforcement.

Recommended next actions:

- Add model usage audit records to service results.
- Require owner/version/docs for production-allowed models.
- Add dependency tests proving production UI cannot bypass governed services.
- Introduce strict production mode that can block Approximation models when required.

## 10. Analytics

Maturity score: 6/10.

Current maturity:

- Analytics Lab ownership is documented.
- Research models are flagged as Analytics Lab only and not production allowed.
- Service-layer research execution requires explicit opt-in.
- Research models remain available for exploration without silently entering production service paths.

Remaining risks:

- Research code still physically shares legacy folders with production engines.
- Research panels may still call raw models directly.
- No experiment registry or notebook governance exists.

Blockers:

- No physical `analytics/` package ownership.
- No promotion checklist enforcement from research to production.
- No experiment reproducibility metadata.

Recommended next actions:

- Create research workflow metadata and experiment registry.
- Add tests that research models cannot enter production paths.
- Define promotion checklist from Analytics Lab to production model registry.

## 11. UI

Maturity score: 5/10.

Current maturity:

- UI has workspace-level navigation: Dashboard, Market, Pricing, Portfolio, Risk, Analytics, Settings.
- Wave 1 migrated selected risk/fixed-income panels to services.
- Shared UI architecture now exists under `ui/` with `WorkspacePage`, `WorkspaceCard`, `KpiCard`, `StatusChip`, and `WarningBanner`.
- Theme ownership moved to `ui/theme.py`.
- Dashboard duplicated card implementations were removed without redesign.

Remaining risks:

- Many panels remain thick and directly call models/instruments/risk functions.
- UI can still bypass service governance outside migrated panels.
- Shared components exist, but most panels have not been replatformed onto them.
- Some hardcoded colors remain in legacy UI files.

Blockers:

- No complete service-only UI dependency policy.
- No central view-model/controller layer.
- No interactive UI test coverage.

Recommended next actions:

- Continue UI-to-service migration for rates, IRS, FX, option, portfolio, market, and analytics panels.
- Add static tests preventing production panels from importing raw engines.
- Replatform panels incrementally onto `ui.components` without visual redesign.
- Move remaining hardcoded colors to `ui/theme.py` as panels are touched.

## Score Summary

| Area | Score |
| --- | ---: |
| Architecture | 7 |
| Domain Layer | 7 |
| Services | 7 |
| Market Data | 6 |
| Pricing | 6 |
| Fixed Income | 6 |
| Portfolio | 7 |
| Risk | 6 |
| Governance | 7 |
| Analytics | 6 |
| UI | 5 |

Average score: 6.36/10.

## Release Candidate Verdict

RiskCalc is an Advanced Prototype.

It has enough architecture and tested service/domain foundations to be treated as a serious pre-workstation platform. It should not be called a Professional Workstation yet because too many user-facing production workflows still depend on approximations, incomplete UI migration, and demo/manual data. It should not be called a Production Candidate because auditability, validation evidence, persistence, real market-data ingestion, and global governance enforcement are not complete.

## Release Blockers Before Professional Workstation

1. Complete UI-to-service migration for all production panels.
2. Implement real market-data ingestion and snapshot validation.
3. Add portfolio-level VaR/stress as canonical RiskService workflows.
4. Add typed position schemas and portfolio import/export.
5. Strengthen IRS/FRN fixed-income methodology.
6. Add full workflow integration tests.

## Release Blockers Before Production Candidate

1. Immutable market-data and calculation audit trail.
2. Validation evidence and model approval workflow.
3. Strict production-mode model gating.
4. Real source adapters and operational error handling.
5. CI/CD release process and regression benchmark suite.
6. Security, permissions, reproducibility, and export/report controls.
