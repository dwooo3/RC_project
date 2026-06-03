# Migration Plan

Date: 2026-06-04

Sources:

- `PRODUCT_ARCHITECTURE.md`
- `AUDIT.md`
- Current repository after Phase 3

Purpose:

This plan turns the target architecture into six implementation sprints. It is
ordered to keep architecture cleanup ahead of UI redesign and to preserve current
functionality while moving RiskCalc from calculator panels toward a portfolio-led
market-risk workstation.

Current baseline:

- Domain layer exists for market data, results, model governance, risk factors,
  and portfolio contracts.
- Service layer exists for market data, pricing, governance, risk skeleton, and
  portfolio workflow.
- `MarketDataService` owns canonical curves and demo snapshots.
- `PortfolioService` owns position pricing, risk-factor exposure buckets, and
  scenario P&L preparation.
- `risk.portfolio` remains a backward-compatible facade.
- Risk and pricing panels still call many raw model functions directly.
- Fixed income, VaR/ES, stress, Monte Carlo, and tree engines still contain P0/P1
  methodology and validation issues from `AUDIT.md`.

Architecture constraints:

- UI must depend on services, not raw pricing/risk functions.
- Services must depend on domain contracts and engines.
- Market data must be routed through `MarketDataService`.
- Pricing and risk workflows must not bypass model governance.
- Prototype models may remain available, but not silently enter production
  workflows.
- Portfolio is the central product object.

## Sprint 1 - Stabilize Service Boundaries

### Goals

- Make service ownership explicit for pricing, risk, portfolio, market data, and
  governance.
- Stop new direct UI-to-model coupling from spreading.
- Add canonical result/status contracts required by later sprints.
- Preserve existing panel behavior through adapters.

### Implementation Tasks

- Expand `PricingService` from skeleton into the canonical entry point for simple
  pricing workflows currently called directly by panels.
- Expand `RiskService` from skeleton into the canonical entry point for VaR,
  ES, backtesting, stress, and P&L explain workflows.
- Add service-level validation helpers for finite inputs, confidence levels,
  horizons, quantities, and market data source status.
- Add structured warnings/errors to service results without breaking legacy dict
  outputs.
- Add compatibility wrappers so existing panels can migrate one at a time.
- Add tests proving old function paths and new service paths produce equivalent
  results for selected baseline cases.

### Affected Files

- `services/pricing_service.py`
- `services/risk_service.py`
- `services/governance_service.py`
- `services/market_data_service.py`
- `services/portfolio_service.py`
- `domain/results.py`
- `domain/model_governance.py`
- `domain/market_data.py`
- `domain/portfolio.py`
- `domain/risk_factors.py`
- `models/registry.py`
- `tests/test_architecture_phase1.py`
- `tests/test_market_data_foundation.py`
- `tests/test_portfolio_service.py`
- New tests under `tests/`

### Risks

- Service layer can become a thin pass-through if result contracts are not
  enforced.
- Too much migration in one sprint can break many panels at once.
- Dict compatibility can hide missing structured fields.

### Rollback Strategy

- Keep existing raw model functions unchanged.
- Keep legacy dict return payloads as adapters around structured results.
- If a service route fails, panels can temporarily call the pre-existing function
  path while tests isolate the regression.

### Success Criteria

- All tests pass.
- `PricingService` and `RiskService` expose callable methods for at least one
  representative workflow each.
- New service methods return warnings/errors metadata.
- No UI panel is forced to know market-data construction details for migrated
  workflows.
- No production workflow bypasses `GovernanceService` for migrated models.

## Sprint 2 - Govern Market Data and Curves

### Goals

- Make `MarketDataSnapshot` the required input surface for pricing and risk
  workflows.
- Harden yield curve validation beyond node-level checks.
- Remove remaining duplicate or ad hoc curve ownership.
- Prepare market data for rates, FX, equity, credit, and volatility risk factors.

### Implementation Tasks

- Add snapshot-level validation for curves, vol surfaces, FX rates, and credit
  spreads.
- Replace silent curve clipping in production paths with controlled validation
  errors or demo-only warnings.
- Validate interpolated and extrapolated discount factors on a dense grid.
- Extend `MarketDataSnapshot` with source metadata usable by risk and portfolio
  services.
- Move or wrap `curves.russia.price_ofz` so curve modules do not own product
  pricing.
- Route yield-curve panel and rates-related panels through `MarketDataService`
  consistently.
- Add tests for invalid curves, non-monotonic interpolated discount factors,
  NaN/inf market data, and source metadata propagation.

### Affected Files

- `domain/market_data.py`
- `curves/yield_curve.py`
- `curves/russia.py`
- `risk/vol_surface.py`
- `services/market_data_service.py`
- `services/pricing_service.py`
- `services/risk_service.py`
- `app/panels/yield_curve_panel.py`
- `app/panels/rates_panel.py`
- `app/panels/bond_panel.py`
- `app/panels/irs_panel.py`
- `tests/test_market_data_foundation.py`
- New market-data validation tests

### Risks

- Removing silent clipping can expose bad demo data or previously tolerated
  interpolation artifacts.
- Some panels may depend on permissive curve behavior.
- Dense-grid validation can reject curves that are acceptable for demo use but
  invalid for production.

### Rollback Strategy

- Keep a `DEMO` source policy that can downgrade hard failures to warnings.
- Preserve `YieldCurve.flat()` and existing factory functions.
- If strict validation blocks existing screens, scope strict mode to service
  production paths and keep demo panels warning-only until updated.

### Success Criteria

- Market data used by migrated pricing/risk paths comes from a
  `MarketDataSnapshot`.
- Curve validation rejects NaN, inf, non-positive discount factors, and
  non-monotonic production curves.
- Demo curves remain usable with explicit source metadata.
- No new curve implementation is introduced outside canonical curve ownership.
- Tests cover valid and invalid snapshot construction.

## Sprint 3 - Fix Risk Models and RiskService Routing

### Goals

- Consolidate VaR/ES logic into governed risk workflows.
- Correct high-priority issues from `AUDIT.md` and `RISK_MODEL_AUDIT.md`.
- Make portfolio-level risk the default path.
- Preserve current CLI and UI outputs through service adapters.

### Implementation Tasks

- Define canonical risk input/result contracts:
  - return series vs P&L series;
  - position value;
  - horizon;
  - confidence;
  - currency;
  - data source.
- Implement one shared quantile and ES helper for weighted and unweighted samples.
- Fix weighted Historical VaR in `risk/var.py` or route it to the canonical
  implementation.
- Fix component VaR sign convention in `risk/historical_var.py`.
- Fix Student-t ES formula and add analytical benchmark tests.
- Stop full-repricing MC VaR from replacing pricing failures with zero P&L.
- Add failure count and tolerance policy to MC risk outputs.
- Route `VarPanel`, `HistVarPanel`, and CLI VaR calls through `RiskService`.
- Add risk result warnings when synthetic/demo data is used.

### Affected Files

- `domain/results.py`
- `domain/risk_factors.py`
- `services/risk_service.py`
- `services/portfolio_service.py`
- `risk/var.py`
- `risk/historical_var.py`
- `risk/stress.py`
- `app/panels/var_panel.py`
- `app/panels/histvar_panel.py`
- `main.py`
- `tests/test_var.py`
- New risk-service tests

### Risks

- VaR numbers can change because old inconsistent formulas are corrected.
- UI charts may assume old dict field names.
- Backtesting outputs can change when exception and confidence conventions are
  centralized.

### Rollback Strategy

- Keep old raw functions callable for comparison tests.
- Add service outputs that include `legacy_method` metadata during migration.
- If a UI regression appears, revert the panel to the old function call while
  keeping corrected core functions behind tests.

### Success Criteria

- Historical, Parametric, and Monte Carlo VaR all use the same positive-loss
  convention.
- ES is greater than or equal to VaR for covered methods.
- Weighted Historical VaR applies horizon policy consistently.
- MC full repricing reports failed scenarios instead of hiding them.
- `RiskService` is the default path for migrated VaR panels and CLI routes.
- Tests cover known-array VaR, weighted VaR, Student-t ES, component VaR signs,
  invalid inputs, and MC repricing failures.

## Sprint 4 - Productionize Portfolio, P&L Explain, and Stress

### Goals

- Make portfolio workflows the center of risk and stress.
- Replace raw Greek aggregation with risk-factor and bucket aggregation in user
  workflows.
- Add architecture for P&L explain and scenario P&L without overhauling UI.
- Correct stress-testing ownership from product-specific functions to
  portfolio-level service workflows.

### Implementation Tasks

- Extend `RiskFactorExposure` and `PortfolioService` to aggregate by:
  - factor name;
  - bucket;
  - currency;
  - unit;
  - bump size.
- Add `Scenario` domain contract with factor shocks, source, date, severity, and
  applicability metadata.
- Implement portfolio-level scenario P&L in `RiskService` using exposures from
  `PortfolioService`.
- Separate Greeks-based explain from full-repricing stress.
- Rename misleading `pnl_explain()` totals in `risk/stress.py` or wrap them with
  corrected service names.
- Add position-level pricing status and pricing error fields.
- Exclude failed positions from aggregated risk unless explicitly allowed by
  service options.
- Route `PortfolioPanel`, `StressPanel`, and `PnlPanel` through service methods
  where practical.

### Affected Files

- `domain/portfolio.py`
- `domain/risk_factors.py`
- New `domain/scenario.py`
- `services/portfolio_service.py`
- `services/risk_service.py`
- `risk/portfolio.py`
- `risk/stress.py`
- `app/panels/portfolio_panel.py`
- `app/panels/stress_panel.py`
- `app/panels/pnl_panel.py`
- `tests/test_portfolio_service.py`
- New stress/scenario tests

### Risks

- Existing scenario P&L numbers may change as unit handling becomes stricter.
- Full-repricing stress can expose pricing failures in prototype instruments.
- Position error handling can reduce reported aggregate risk if failed positions
  are excluded without clear warnings.

### Rollback Strategy

- Keep legacy scalar fields (`delta`, `gamma`, `vega`, `dv01`, `cs01`) in
  aggregate results for UI compatibility.
- Keep Greeks-based stress as an approximation mode.
- Add a service option to include/exclude failed positions explicitly.

### Success Criteria

- Portfolio aggregation reports exposure by bucket and by unit without mixing
  incompatible measures.
- Scenario P&L returns bucket-level components.
- Failed position pricing is visible in service results.
- Stress workflows can run on a one-position portfolio and a mixed portfolio.
- Existing portfolio UI remains functional.
- Tests cover mixed asset-class aggregation and scenario P&L decomposition.

## Sprint 5 - Fixed Income Methodology Hardening

### Goals

- Correct the largest fixed-income methodology gaps.
- Introduce date/schedule/day-count foundations.
- Make bond pricing clean/dirty/accrued aware.
- Prepare FRN and IRS for future dual-curve production workflows.

### Implementation Tasks

- Add fixed-income domain contracts for:
  - coupon schedule;
  - day-count convention;
  - settlement convention;
  - fixed bond spec;
  - FRN spec;
  - IRS spec;
  - fixed-income pricing result.
- Implement ACT/365, ACT/360, 30/360, and ACT/ACT date-pair functions.
- Implement regular coupon schedule generation with basic stub support.
- Refactor `fixed_bond` behind a compatibility adapter that can return dirty
  price, clean price, accrued interest, cash-flow dates, and warnings.
- Replace UI fake accrued interest with service result values.
- Add finite-difference DV01 for bond and IRS service workflows.
- Start FRN/IRS redesign by adding current fixing, projection curve, discount
  curve, and schedule fields to contracts.
- Keep current simplified FRN/IRS functions marked as approximation until full
  replacement is complete.

### Affected Files

- New fixed-income domain file under `domain/` or existing `domain/results.py`
- `instruments/fixed_income.py`
- `curves/yield_curve.py`
- `curves/russia.py`
- `services/pricing_service.py`
- `services/market_data_service.py`
- `app/panels/bond_panel.py`
- `app/panels/irs_panel.py`
- `app/panels/rates_panel.py`
- `tests/`
- Existing audit references:
  - `FIXED_INCOME_AUDIT.md`

### Risks

- Bond prices can change once accrued interest and settlement are modeled.
- Existing panels use simple `T` and `freq` inputs, not real dates.
- Adding schedules can expand scope if calendars and business-day conventions are
  attempted too early.

### Rollback Strategy

- Preserve current `fixed_bond(face, coupon, T, freq, curve)` signature.
- Return old `price` key as dirty price during migration.
- Gate date-based pricing behind new service methods until UI inputs support it.
- Keep simplified FRN/IRS outputs but mark them as model warnings.

### Success Criteria

- Fixed bond service result includes clean price, dirty price, accrued interest,
  cash-flow dates, day-count convention, and warnings.
- Day-count tests pass for known date examples.
- Par bond, zero-coupon, clean/dirty, and finite-difference DV01 tests pass.
- Existing bond panel continues to calculate.
- FRN and IRS approximation status is explicit in model/governance output.

## Sprint 6 - Governance, Validation, and UI Workflow Alignment

### Goals

- Enforce model governance consistently across migrated workflows.
- Move UI toward workflow screens only after service architecture is stable.
- Add production readiness checks and regression coverage.
- Clean up remaining duplicate logic and prototype leaks.

### Implementation Tasks

- Extend `models/registry.py` and `GovernanceService` with:
  - model version;
  - owner;
  - status;
  - production gate;
  - limitations;
  - validation tests;
  - last validated date.
- Add result-level governance warnings for models marked approximation,
  prototype, or blocked.
- Add a model validation screen or route within Risk/Governance per architecture
  priority.
- Migrate remaining panels away from direct raw model calls where service methods
  exist.
- Reduce dashboard technical diagnostics and move model validation details out of
  dashboard.
- Add regression tests for service routes and critical quantitative edge cases:
  - BSM expiry put delta;
  - zero volatility;
  - tree probability validation;
  - Monte Carlo odd antithetic paths;
  - MC control variate discounting;
  - fixed-income day count;
  - VaR/ES edge cases.
- Add lightweight CI command documentation for running tests before release.

### Affected Files

- `models/registry.py`
- `services/governance_service.py`
- `services/pricing_service.py`
- `services/risk_service.py`
- `domain/model_governance.py`
- `domain/results.py`
- `app/panels/dashboard_panel.py`
- `app/panels/risk_workspace.py`
- `app/panels/settings_panel.py`
- Relevant migrated panels under `app/panels/`
- `models/black_scholes.py`
- `models/monte_carlo.py`
- `models/heston.py`
- `models/trees.py`
- `tests/`
- `README.md`

### Risks

- Governance gating can block demo workflows if statuses are too strict.
- UI cleanup can accidentally become a redesign instead of a workflow alignment.
- Broad tests can reveal existing methodology defects that are out of sprint
  scope.

### Rollback Strategy

- Start governance in warning mode before enforcing hard blocks.
- Keep demo mode explicitly allowed for approximation models.
- Keep UI changes scoped to routing and information placement, not visual
  redesign.
- If a new validation test exposes a known defect, mark it expected-fail only if
  there is a linked remediation item.

### Success Criteria

- Migrated service workflows attach model governance metadata.
- Approximation/prototype models are visible to users and services.
- Dashboard no longer carries full model validation diagnostics.
- No production-marked workflow uses a model with `production_allowed=False`.
- Full test suite passes.
- Repository has a clear command for local validation before release.

## Cross-Sprint Implementation Rules

- Keep each sprint shippable and tested.
- Prefer adapters over rewrites.
- Keep old public function signatures until dependent panels are migrated.
- Add tests before changing formulas where behavior is already known to be
  fragile.
- Do not add new top-level modules unless they map to target architecture.
- Do not duplicate market data or curve ownership.
- Do not move prototype models into production workflows.
- Do not redesign UI until services and domain contracts own the workflow.

## Dependency Order

The intended dependency order is:

```text
Sprint 1: service boundaries
Sprint 2: market data foundation
Sprint 3: risk model correctness
Sprint 4: portfolio risk and scenario workflows
Sprint 5: fixed income methodology
Sprint 6: governance, validation, and UI alignment
```

This order should be preserved unless a P0 production blocker requires a smaller
hotfix. If a hotfix is needed, it should still respect the same dependency
direction:

```text
UI -> services -> domain -> engines
```
