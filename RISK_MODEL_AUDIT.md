# Risk Model Audit

Date: 2026-06-04

## Scope

Reviewed market-risk model implementations and UI/service routing for:

- Historical VaR
- Parametric VaR
- Monte Carlo VaR
- Stress testing

Checks performed:

- Loss sign conventions
- Confidence level interpretation
- Horizon scaling
- ES consistency
- Portfolio aggregation
- Risk factor aggregation
- Numerical stability

Primary files reviewed:

- `risk/var.py`
- `risk/historical_var.py`
- `risk/stress.py`
- `risk/portfolio.py`
- `services/risk_service.py`
- `domain/risk_factors.py`
- `app/panels/var_panel.py`
- `app/panels/histvar_panel.py`
- `app/panels/stress_panel.py`
- `tests/test_var.py`

Severity definitions:

- P0 = incorrect valuation
- P1 = methodology issue
- P2 = simplification
- P3 = enhancement

## Executive Summary

The risk stack contains useful demo implementations, but it is not yet a governed
production risk engine. The biggest issues are inconsistent input contracts and
duplicated model logic:

- `risk/var.py` treats inputs as returns.
- `risk/historical_var.py` treats inputs as P&L.
- UI panels contain additional local VaR implementations.
- `RiskService` is still only a skeleton and does not own risk workflows.

Several methods can return incorrect or misleading risk numbers under realistic
conditions. The most material issues are the Student-t ES formula, sign handling
when VaR would be negative, weighted historical VaR horizon/ES treatment,
portfolio historical component VaR sign logic, silent failures in full-repricing
Monte Carlo, and stress testing that bypasses portfolio and risk-factor contracts.

## Severity Counts

| Severity | Count | Summary |
| --- | ---: | --- |
| P0 | 6 | Can produce materially wrong VaR/ES/P&L or silently hide pricing failure |
| P1 | 11 | Methodology issues that must be resolved before production routing |
| P2 | 9 | Simplifications that limit accuracy, aggregation, or governance |
| P3 | 5 | Diagnostics, naming, and test coverage improvements |

## Detailed Findings

### RM-001 - Student-t parametric ES formula is incorrect

Severity: P0

Location:

- `risk/var.py`, `parametric_var`
- `app/panels/histvar_panel.py`, `_tvar`

Current behavior:

- `risk/var.py` computes Student-t CVaR using
  `-pdf(z)/(1-confidence) * scale + mu`, then takes `abs`.
- The UI panel has a different local Student-t ES formula.
- The formulas are not centralized and do not clearly account for degrees of
  freedom, location, scale, and loss-sign convention in the same way.

Impact:

- Parametric t VaR/ES can report an ES that is too low, wrong-signed, or not
  comparable with VaR.
- This is material because Student-t is used specifically for tail-risk
  estimation.

Required fix:

- Implement one canonical Student-t loss distribution formula in the risk
  service and test `ES >= VaR` across skewed and fat-tailed samples.

Rollback plan:

- Keep current t output under an explicit `approximation` model flag until the
  corrected method is validated.

### RM-002 - VaR can become negative or misleading under strong positive drift

Severity: P0

Location:

- `risk/var.py`, `parametric_var`, `portfolio_var`
- `app/panels/histvar_panel.py`, `_parametric_normal`

Current behavior:

- Parametric VaR is calculated as `-(mu + z * sigma)` and then multiplied by
  position value.
- There is no explicit floor at zero or explicit signed-risk policy.
- Historical/MC methods use `abs`, while parametric methods do not consistently
  do so.

Impact:

- A high positive mean with low volatility can produce negative VaR, while other
  models force positive VaR. This breaks cross-method comparison and can
  understate risk.

Required fix:

- Define a canonical convention: VaR is positive loss amount, with optional
  signed quantile reported separately.

Rollback plan:

- Add `signed_quantile` while preserving `VaR` as positive loss output.

### RM-003 - Weighted historical VaR misses horizon scaling

Severity: P0

Location:

- `risk/var.py`, `historical_var`

Current behavior:

- Unweighted historical VaR scales returns by `sqrt(horizon)`.
- Weighted historical VaR does not apply horizon scaling.

Impact:

- Same method can return one-day risk for weighted mode while reporting a
  multi-day horizon in metadata.

Required fix:

- Apply consistent horizon treatment before sorting or explicitly reject
  horizons greater than one for weighted historical VaR.

Rollback plan:

- Gate weighted historical VaR to one-day mode until scaling is validated.

### RM-004 - Portfolio historical marginal VaR sign is wrong

Severity: P0

Location:

- `risk/historical_var.py`, `portfolio_hs_var`

Current behavior:

- Base portfolio VaR is computed through `hs_var`.
- Perturbed VaR uses `-np.percentile(-pnl_up, confidence*100)`.
- This expression returns the negative of a loss percentile, while the base VaR
  is a positive loss amount.

Impact:

- Marginal VaR and component VaR can have wrong sign and magnitude.
- Percent contribution can be meaningless or unstable.

Required fix:

- Compute perturbed VaR through the same canonical VaR function and use a
  consistent positive-loss convention.

Rollback plan:

- Disable or label component VaR from this function as approximate until fixed.

### RM-005 - Full-repricing Monte Carlo hides pricing failures as zero P&L

Severity: P0

Location:

- `risk/historical_var.py`, `mc_var_full_reprice`

Current behavior:

- If the pricer raises, the simulation appends `0` P&L.

Impact:

- Failed stressed scenarios reduce measured tail loss instead of failing the run
  or being reported as invalid.
- This can materially understate VaR and ES.

Required fix:

- Count failed reprices, return diagnostics, and fail if failure rate exceeds a
  governed tolerance.

Rollback plan:

- Keep a demo mode that can impute failures, but expose the imputation count and
  method.

### RM-006 - Stress testing panel references an undefined symbol

Severity: P0

Location:

- `app/panels/stress_panel.py`

Current behavior:

- The panel uses `ModelStatus.APPROXIMATION` but does not import `ModelStatus`.

Impact:

- Stress testing UI can fail to initialize, blocking access to the stress model
  from the application.

Required fix:

- Import `ModelStatus` or remove the dependency in the panel.

Rollback plan:

- Revert to a plain section header without model status if the import causes
  broader UI issues.

### RM-007 - Historical VaR has two incompatible contracts

Severity: P1

Location:

- `risk/var.py`, `historical_var`
- `risk/historical_var.py`, `hs_var`

Current behavior:

- `risk/var.py` accepts returns and `position_value`.
- `risk/historical_var.py` accepts P&L directly.
- Both return `VaR`, `CVaR`, confidence, and horizon, but use different internal
  sign and percentile logic.

Impact:

- Callers can easily pass P&L into a returns-based function or returns into a
  P&L-based function.
- Aggregation and UI comparison can mix incompatible units.

Required fix:

- Create a canonical risk input contract under the domain/service layer:
  `returns`, `pnl`, `position_value`, and `valuation_currency` must be explicit.

### RM-008 - Historical VaR quantile convention is inconsistent

Severity: P1

Location:

- `risk/var.py`, `historical_var`
- `risk/historical_var.py`, `hs_var`, `hs_age_weighted`, `filtered_hs_var`

Current behavior:

- Return-based VaR uses `np.percentile` on left-tail returns.
- P&L-based VaR sorts positive losses and selects `ceil(confidence * n) - 1`.
- Weighted VaR uses `searchsorted(cum_w, confidence)`.

Impact:

- Same confidence level can map to different sample quantile conventions.
- Backtests and method comparisons are not strictly apples-to-apples.

Required fix:

- Define one quantile convention, such as lower-tail loss quantile with documented
  interpolation, and use it everywhere.

### RM-009 - ES denominator and tail inclusion are inconsistent

Severity: P1

Location:

- `risk/var.py`, `historical_var`
- `risk/historical_var.py`, `hs_var`, `hs_age_weighted`, `filtered_hs_var`
- `app/panels/histvar_panel.py`

Current behavior:

- Some methods average observations at or beyond VaR.
- Weighted return-based CVaR divides by `1-confidence` rather than actual selected
  tail weight.
- UI methods use local formulas and `max(es, var)` guards.

Impact:

- ES may not be coherent across methods and may be biased for small samples or
  discrete weighted samples.

Required fix:

- Implement one expected-shortfall helper that handles discrete quantile
  interpolation and weighted tails.

### RM-010 - Horizon scaling is applied mechanically across incompatible methods

Severity: P1

Location:

- `risk/var.py`
- `risk/historical_var.py`
- `app/panels/histvar_panel.py`

Current behavior:

- Historical P&L and returns are scaled by `sqrt(horizon)`.
- Parametric mean is sometimes scaled linearly and sometimes not.
- UI computes one-day VaR first, then multiplies by `sqrt(horizon)`.
- Full-repricing MC has no horizon parameter.

Impact:

- Multi-day VaR can be inconsistent across models, especially with drift,
  autocorrelation, volatility clustering, and non-linear portfolios.

Required fix:

- Define per-method horizon policy:
  - Parametric: `mu * horizon`, `sigma * sqrt(horizon)`.
  - Historical: overlapping/non-overlapping horizon P&L or documented square-root
    approximation.
  - Full-repricing MC: scenario model must generate horizon shocks directly.

### RM-011 - Parametric VaR uses population standard deviation by default

Severity: P1

Location:

- `risk/var.py`, `parametric_var`, `montecarlo_var`
- `app/panels/histvar_panel.py`, `_parametric_normal`

Current behavior:

- `returns.std()` and `pnl.std()` use `ddof=0`.

Impact:

- Sample volatility is biased low for small samples.

Required fix:

- Use a governed estimator choice, defaulting to `ddof=1` for sample data or
  explicitly documenting population-vol input.

### RM-012 - Monte Carlo VaR is normal simulation, not full portfolio MC

Severity: P1

Location:

- `risk/var.py`, `montecarlo_var`
- `risk/historical_var.py`, `mc_var_full_reprice`
- `app/panels/montecarlo_panel.py`

Current behavior:

- Core MC VaR fits a normal distribution to historical returns and simulates
  scalar returns.
- Full-repricing MC exists separately but uses generic fixed shock sizes and is
  not routed through `RiskService`.

Impact:

- Non-linear portfolios are not handled by the main MC VaR method.
- Model name can imply full revaluation when the implementation is distribution
  simulation.

Required fix:

- Rename scalar return simulation clearly and route full-repricing MC through
  portfolio/pricing services.

### RM-013 - Portfolio aggregation assumes weights and returns are already aligned

Severity: P1

Location:

- `risk/var.py`, `portfolio_var`, `component_var`

Current behavior:

- No validation of weight sum, dimensions, NaN/inf values, timestamps, missing
  returns, or currency consistency.

Impact:

- Misaligned inputs can silently produce incorrect portfolio VaR.

Required fix:

- Add input validation and a portfolio risk data contract with asset IDs,
  timestamps, currencies, and weights/market values.

### RM-014 - Risk factor aggregation is not implemented as a governed workflow

Severity: P1

Location:

- `domain/risk_factors.py`
- `risk/portfolio.py`
- `services/risk_service.py`

Current behavior:

- `RiskFactorExposure` exists as a small contract.
- Portfolio aggregation sums Greeks and DV01/CS01 fields directly.
- There is no risk-factor taxonomy, factor ID mapping, scenario set, or
  covariance/aggregation service.

Impact:

- Cross-asset risk factor aggregation is incomplete and can double-count or mix
  incompatible units.

Required fix:

- Route risk aggregation through `RiskService` using factor-level exposures from
  pricing outputs.

### RM-015 - Portfolio Greeks aggregation mixes units

Severity: P1

Location:

- `risk/portfolio.py`, `aggregate`, `scenario_pnl`

Current behavior:

- Option delta, bond duration-derived delta, equity quantity, DV01, CS01, rho,
  and FX delta are all stored in flat fields.
- Scenario P&L applies generic formulas to the sums.

Impact:

- Aggregated delta/gamma/vega/rho may combine different underlyings, currencies,
  and units.
- Scenario P&L can be wrong for multi-asset portfolios.

Required fix:

- Aggregate by named risk factor and unit, not by one global scalar per Greek.

### RM-016 - Stress testing is product-specific and bypasses portfolio service

Severity: P1

Location:

- `risk/stress.py`, `stress_option`, `stress_bond`
- `app/panels/stress_panel.py`

Current behavior:

- Stress testing reprices a single Black-Scholes option or applies duration/
  convexity to a bond.
- There is no portfolio-level scenario application through `PricingService` or
  `RiskService`.

Impact:

- Stress results do not represent portfolio aggregation, cross-factor moves, or
  current market-data snapshots.

Required fix:

- Define scenario shocks as market-data snapshot transformations and reprice
  positions through services.

### RM-017 - Stress scenario metadata is under-specified

Severity: P1

Location:

- `risk/stress.py`, `HISTORICAL_SCENARIOS`

Current behavior:

- Scenarios are hard-coded dictionaries with spot, vol, and rate shocks.
- No asset class, region, base date, source, calibration date, horizon, or
  applicability tags are stored.

Impact:

- The same scenario can be applied to unrelated underlyings without governance.

Required fix:

- Add scenario metadata and validation before applying a stress set.

### RM-018 - Numerical validation is missing for risk inputs

Severity: P1

Location:

- `risk/var.py`
- `risk/historical_var.py`
- `risk/stress.py`

Current behavior:

- Functions generally do not reject empty arrays, NaN/inf values, zero variance,
  invalid confidence levels, negative horizons, or invalid position values.

Impact:

- Bad inputs can produce NaN, inf, misleading zeros, or runtime errors that are
  not governed.

Required fix:

- Add shared validators for risk inputs and return structured errors/warnings.

### RM-019 - EVT VaR omits horizon in returned metadata

Severity: P2

Location:

- `risk/var.py`, `evt_var`

Current behavior:

- EVT applies horizon scaling but does not include `horizon` in the returned
  dictionary.

Impact:

- Downstream reporting can mislabel EVT risk horizon.

Required fix:

- Include horizon and method assumptions in the result contract.

### RM-020 - EVT threshold handling is too coarse for production

Severity: P2

Location:

- `risk/var.py`, `evt_var`

Current behavior:

- Threshold is fixed as a fraction of worst returns.
- No stability diagnostics, mean residual life check, shape-parameter warnings,
  or confidence intervals are returned.

Impact:

- EVT output can look precise despite unstable tail fit.

Required fix:

- Add EVT diagnostics before using it in governed workflows.

### RM-021 - PCA VaR lacks horizon, sign, and factor validation

Severity: P2

Location:

- `risk/historical_var.py`, `pca_var`

Current behavior:

- PCA VaR computes factor sensitivities and covariance from yield changes.
- There is no horizon argument, no NaN/inf validation, and no check that
  `dv01_vector` aligns with tenor columns.

Impact:

- Yield-curve VaR can be mis-scaled or mis-attributed.

Required fix:

- Add tenor metadata, horizon handling, and shape validation.

### RM-022 - Backtesting implementation is not centralized

Severity: P2

Location:

- `risk/var.py`, `kupiec_test`, `christoffersen_test`
- `risk/historical_var.py`, `backtest_var`
- `app/panels/histvar_panel.py`, `calculate`, `backtest`

Current behavior:

- Core functions and UI have separate backtesting logic.
- UI uses a simplified binomial probability display rather than the core Kupiec
  function.

Impact:

- Backtest results can differ between CLI/core/UI paths.

Required fix:

- Route all backtesting through `RiskService`.

### RM-023 - Stress option clamps stressed volatility and rate without governance

Severity: P2

Location:

- `risk/stress.py`, `stress_option`

Current behavior:

- Volatility is floored at `0.01`.
- Rate is floored at `-0.05`.

Impact:

- Extreme scenarios are silently altered.

Required fix:

- Expose clamp policy in scenario metadata or reject out-of-domain scenarios.

### RM-024 - Reverse stress ignores position direction

Severity: P2

Location:

- `risk/stress.py`, `reverse_stress`
- `app/panels/stress_panel.py`

Current behavior:

- Reverse stress minimizes shock to reduce option price by target loss.
- It does not accept position quantity or long/short direction.

Impact:

- Reverse stress can search for the wrong loss direction for short positions.

Required fix:

- Include signed position value and define loss as negative portfolio P&L.

### RM-025 - Monte Carlo VaR reproducibility is fixed but not configurable in UI

Severity: P2

Location:

- `risk/var.py`, `montecarlo_var`
- `app/panels/var_panel.py`

Current behavior:

- Core MC uses a seed argument with default `42`.
- UI does not expose seed or confidence intervals.

Impact:

- Results are deterministic but users cannot assess sampling error.

Required fix:

- Return simulation standard error or confidence intervals for VaR/ES.

### RM-026 - Tests check only broad sanity, not edge cases

Severity: P2

Location:

- `tests/test_var.py`

Current behavior:

- Tests cover positivity, ES >= VaR, and simple horizon scaling.
- One test contains `assert res["VaR"] >= 0 or True`, which always passes.

Impact:

- Known sign and edge-case issues are not protected.

Required fix:

- Add deterministic tests for sign conventions, weighted VaR, t ES, negative
  VaR prevention, invalid inputs, and component VaR.

### RM-027 - RiskService does not yet own risk workflows

Severity: P2

Location:

- `services/risk_service.py`

Current behavior:

- `RiskService` only stores market-data and governance dependencies.
- Risk calculations are called directly from UI, CLI, and modules.

Impact:

- No single place enforces model registry, market-data snapshots, validation, or
  governance warnings.

Required fix:

- Implement `RiskService` as the canonical entry point for VaR, ES, stress, and
  aggregation.

### RM-028 - Method result contracts are inconsistent

Severity: P3

Location:

- `risk/var.py`
- `risk/historical_var.py`
- `risk/stress.py`

Current behavior:

- Some methods return `ES`, some `CVaR`, some both, some neither.
- Some include `horizon`, `n_obs`, or `method`; others omit them.

Impact:

- UI and service layers must contain defensive logic and assumptions.

Required fix:

- Add a canonical risk result dataclass with required fields.

### RM-029 - Confidence level validation is absent

Severity: P3

Location:

- `risk/var.py`
- `risk/historical_var.py`

Current behavior:

- Confidence is accepted without explicit bounds checking.

Impact:

- Invalid values can produce invalid quantiles or empty tails.

Required fix:

- Require `0.5 < confidence < 1.0` or a documented allowed range.

### RM-030 - Synthetic demo data can be mistaken for production inputs

Severity: P3

Location:

- `app/panels/var_panel.py`
- `app/panels/histvar_panel.py`

Current behavior:

- UI panels generate synthetic returns/P&L and display demo warnings.

Impact:

- Warnings are present, but service-level governance does not prevent synthetic
  data from entering production-style workflows.

Required fix:

- Tag synthetic risk data as `DEMO` in the market/risk data layer and propagate
  source metadata into risk outputs.

### RM-031 - Stress P&L percentage denominator is fragile

Severity: P3

Location:

- `risk/stress.py`, `stress_option`

Current behavior:

- `pnl_pct` divides by `base.price * abs(position)`.

Impact:

- If position is zero, denominator becomes zero and output falls back only when
  base price is zero. Very small base values can produce unstable percentages.

Required fix:

- Validate non-zero position and use a stable market-value denominator.

## Review Matrix

| Check | Historical VaR | Parametric VaR | Monte Carlo VaR | Stress Testing |
| --- | --- | --- | --- | --- |
| Loss sign conventions | P1: returns/P&L contracts differ | P0: negative VaR possible | P1: scalar returns vs P&L paths differ | P2: reverse stress ignores signed positions |
| Confidence interpretation | P1: quantile methods differ | P1: t ES mismatch | P2: no sampling diagnostics | P2: no scenario probability/confidence concept |
| Horizon scaling | P0: weighted mode misses scaling | P1: drift/vol policy inconsistent across UI/core | P1: full reprice MC has no horizon | P2: scenario horizon metadata absent |
| ES consistency | P1: tail averaging inconsistent | P0: Student-t ES incorrect | P1: failure imputation biases ES | N/A |
| Portfolio aggregation | P0: component VaR sign bug | P1: weights unchecked | P1: no full portfolio MC route | P1: no portfolio stress engine |
| Risk factor aggregation | P2: not factor-owned | P2: covariance only by returns matrix | P2: no factor taxonomy | P1: hard-coded spot/vol/rate only |
| Numerical stability | P1: no input validators | P1: zero variance/invalid confidence unguarded | P0: pricing failures become zero P&L | P2: silent clamps |

## Architectural Impact

The current risk layer does not yet satisfy the target architecture direction:

1. Domain layer:
   - Has a minimal `RiskFactorExposure` contract.
   - Does not yet define canonical `RiskInput`, `RiskResult`,
     `ScenarioDefinition`, or `BacktestResult`.

2. Service layer:
   - `RiskService` is a dependency holder, not a workflow owner.
   - UI and CLI bypass the service and call low-level functions directly.

3. Model governance:
   - Model status is visible in parts of the UI, but not enforced in risk
     calculation outputs.
   - Demo/synthetic data is not tagged through the risk result contract.

4. Portfolio/risk factor aggregation:
   - Aggregation is scalar and unit-mixed.
   - There is no governed mapping from positions to factor exposures to
     aggregated risk.

## Recommended Remediation Order

### Step 1 - Define canonical risk contracts

Difficulty: Medium

Risk: Medium

Affected files:

- `domain/`
- `services/risk_service.py`
- `risk/var.py`
- `risk/historical_var.py`
- `tests/`

Tasks:

- Add explicit contracts for P&L series, return series, risk horizon, confidence,
  result metadata, and source.
- Define VaR as positive loss amount and expose signed quantile separately.

### Step 2 - Centralize VaR and ES helpers

Difficulty: Medium

Risk: Medium

Affected files:

- `risk/var.py`
- `risk/historical_var.py`
- `app/panels/histvar_panel.py`
- `tests/`

Tasks:

- Implement shared quantile and ES functions for weighted and unweighted samples.
- Remove UI-local VaR formula duplication.
- Fix Student-t ES.

### Step 3 - Implement RiskService workflows

Difficulty: Medium

Risk: Medium

Affected files:

- `services/risk_service.py`
- `app/panels/var_panel.py`
- `app/panels/histvar_panel.py`
- `main.py`
- `tests/`

Tasks:

- Route Historical, Parametric, MC, EVT, and backtesting through `RiskService`.
- Attach model governance and data-source metadata to all results.

### Step 4 - Fix portfolio and risk-factor aggregation

Difficulty: High

Risk: High

Affected files:

- `domain/risk_factors.py`
- `risk/portfolio.py`
- `services/pricing_service.py`
- `services/risk_service.py`
- `tests/`

Tasks:

- Aggregate by named factor, currency, and unit.
- Recompute component VaR with consistent sign and finite-difference logic.

### Step 5 - Harden Monte Carlo and stress testing

Difficulty: High

Risk: Medium

Affected files:

- `risk/historical_var.py`
- `risk/stress.py`
- `services/risk_service.py`
- `app/panels/stress_panel.py`
- `tests/`

Tasks:

- Fail or report repricing errors in MC.
- Add scenario metadata and market-data snapshot transformations.
- Route stress through portfolio repricing.

## Minimum Test Additions

Required before production routing:

- VaR is non-negative for all methods unless an explicit signed result is used.
- Historical return-based and P&L-based VaR agree after unit conversion.
- Weighted and unweighted historical VaR use the same horizon policy.
- ES is greater than or equal to VaR for normal, Student-t, historical, weighted
  historical, and MC methods.
- Student-t ES matches a known analytical benchmark.
- Invalid confidence, empty arrays, NaN, inf, and zero-vol samples are rejected.
- Component VaR signs and totals are consistent with total VaR.
- MC full repricing reports failed reprices and does not impute zero silently.
- Stress panel imports and initializes successfully.
- Reverse stress handles long and short positions consistently.

## Conclusion

Risk models should remain marked as approximate until P0 and P1 issues are
resolved. The next architecture step should not be UI redesign. It should be a
service-layer cleanup that creates one governed risk workflow, one sign
convention, one quantile/ES implementation, and one risk-factor aggregation path.
