# Fixed Income Audit

Date: 2026-06-04

## Scope

Reviewed fixed-income valuation and curve code against the target architecture in
`PRODUCT_ARCHITECTURE.md`, with focus on:

- Bond pricing
- FRN pricing
- IRS pricing
- Yield curves
- Day count conventions
- Settlement logic
- Coupon schedule generation
- Accrued interest
- Dirty/clean price consistency
- Duration
- Convexity
- DV01

Primary files reviewed:

- `instruments/fixed_income.py`
- `curves/yield_curve.py`
- `curves/russia.py`
- `app/panels/bond_panel.py`
- `app/panels/irs_panel.py`
- `services/market_data_service.py`

Severity definitions:

- P0 = incorrect valuation
- P1 = methodology issue
- P2 = simplification
- P3 = enhancement

## Executive Summary

The current fixed-income implementation is suitable only for demos and simple
analytics. It is not yet production-grade valuation logic. The largest issues are
not UI-related. They are domain and service-layer issues:

- Bonds do not have settlement dates, coupon dates, day-count accruals, dirty
  price, or clean price as first-class concepts.
- FRN valuation is structurally incorrect for a floating-rate note because it
  discounts principal plus spread only and omits floating coupon projection and
  reset mechanics.
- IRS valuation is a single-curve approximation with no schedule dates, accrual
  factors, fixing logic, calendars, or dual-curve separation.
- Yield curves validate node discount factors but do not validate interpolated
  or extrapolated discount factors and still silently clip interpolated rates.
- Risk measures are mostly analytical proxies, not finite-difference sensitivities
  against governed market-data snapshots.

This creates a direct architectural gap against `PRODUCT_ARCHITECTURE.md`: pricing
models depend on loosely defined curve and time abstractions instead of explicit
domain contracts for market data, schedules, day counts, settlement, and model
governance.

## Severity Counts

| Severity | Count | Summary |
| --- | ---: | --- |
| P0 | 5 | Cases that can produce materially wrong valuations |
| P1 | 12 | Methodology gaps that must be corrected before production use |
| P2 | 8 | Known simplifications that limit accuracy and maintainability |
| P3 | 5 | Usability, diagnostics, and coverage improvements |

## Detailed Findings

### FI-001 - FRN pricing omits floating leg projection

Severity: P0

Location:

- `instruments/fixed_income.py`, `frn`

Current behavior:

- Prices an FRN as discounted principal plus discounted spread coupons.
- The base floating coupons are not projected from forward rates.
- Reset timing, current fixing, accrual period, index curve, and discount curve
  are absent.

Impact:

- A par floater with zero spread should generally price near par at reset,
  subject to credit and discounting assumptions. Current logic prices it close to
  `face * discount(T)`, which can materially understate value.

Required fix:

- Introduce an FRN cash-flow engine using coupon reset dates, accrual factors,
  projected index coupons, current fixing for the active coupon, spread, and a
  discount curve from `MarketDataService`.

Rollback plan:

- Keep the current function as a legacy approximation behind an explicit
  approximation flag until the new engine is validated.

### FI-002 - IRS floating leg is an oversimplified single-curve formula

Severity: P0

Location:

- `instruments/fixed_income.py`, `irs`

Current behavior:

- Floating leg is approximated as `discount(0.001) - discount(T)`.
- No effective date, settlement date, payment dates, fixing dates, calendars, or
  accrual factors are modeled.
- No separation between projection curve and discount curve.

Impact:

- The NPV, fair rate, and DV01 can be materially wrong for non-spot-starting
  swaps, seasoned swaps, non-standard accruals, and modern collateralized
  valuation.

Required fix:

- Create an IRS domain contract with fixed leg schedule, floating leg schedule,
  index tenor, current fixings, projection curve, discount curve, and settlement
  convention.

Rollback plan:

- Preserve the existing simple `irs` function as a demo adapter while routing
  production workflows to the new service implementation.

### FI-003 - Bond clean and dirty prices are not consistently modeled

Severity: P0

Location:

- `instruments/fixed_income.py`, `fixed_bond`
- `curves/russia.py`, `price_ofz`
- `app/panels/bond_panel.py`

Current behavior:

- `fixed_bond` returns one `price` and no accrued interest.
- The bond panel displays accrued interest as `0.0` and clean price equal to
  price.
- `price_ofz` computes a separate accrued amount from `accrued_days`, but this
  logic is outside the core bond model and is not based on actual coupon dates.

Impact:

- Off-coupon-date valuations can display and return wrong clean prices.
- Dirty/clean consistency is not guaranteed across UI, domain, and curve helpers.

Required fix:

- Make dirty price, clean price, accrued interest, settlement date, previous
  coupon date, next coupon date, and accrual factor explicit in the bond result.

Rollback plan:

- Maintain `price` as an alias to dirty price for backward compatibility during
  migration.

### FI-004 - Silent rate clipping can hide invalid curve states

Severity: P0

Location:

- `curves/yield_curve.py`, `YieldCurve.rate`

Current behavior:

- Interpolated rates are clipped to `[-0.3, 2.0]`.

Impact:

- Invalid market data, unstable interpolation, or extrapolation errors can be
  hidden and converted into plausible-looking valuations.
- This violates model governance expectations because pricing can proceed after
  data quality failure.

Required fix:

- Replace silent clipping with validation errors or explicit guarded behavior in
  `MarketDataService`.

Rollback plan:

- Add a temporary compatibility mode that preserves clipping only for demo
  sources and emits model warnings.

### FI-005 - Coupon schedules are generated from rounded year counts

Severity: P0

Location:

- `instruments/fixed_income.py`, `fixed_bond`, `frn`, `irs`
- `curves/yield_curve.py`, `par_rate`, `from_par_rates`, `bootstrap`

Current behavior:

- Coupon/payment times use `int(round(T * freq))` and `i / freq`.
- No date schedule, stub handling, maturity date, issue date, end-of-month rule,
  business-day adjustment, or holiday calendar is present.

Impact:

- Any bond or swap with irregular first/last coupons, non-exact maturity, or real
  market calendar can be valued incorrectly.

Required fix:

- Add a schedule-generation domain service before expanding product coverage.

Rollback plan:

- Keep year-based schedule generation as a legacy approximation for simple demo
  instruments.

### FI-006 - Day count conventions are declared but not implemented

Severity: P1

Location:

- `curves/yield_curve.py`, `year_fraction`

Current behavior:

- `year_fraction` returns the input float.
- The declared conventions `act365`, `act360`, `30360`, and `actact` are not
  implemented for date pairs.

Impact:

- Accrual, discounting, par rates, and risk measures cannot be made consistent
  with market conventions.

Required fix:

- Implement date-pair day-count functions and require instrument specs to pass
  conventions explicitly.

### FI-007 - Settlement logic is absent

Severity: P1

Location:

- `instruments/fixed_income.py`
- `curves/russia.py`

Current behavior:

- Models accept only time to maturity `T`.
- There is no valuation date, settlement lag, settlement date, ex-coupon period,
  or accrued-to-settlement calculation.

Impact:

- Values are only valid for abstract valuation at time zero and cannot represent
  real trade settlement.

Required fix:

- Add settlement conventions and settlement date calculation to fixed-income
  domain objects.

### FI-008 - Bond duration mixes curve valuation and yield convention

Severity: P1

Location:

- `instruments/fixed_income.py`, `fixed_bond`
- `curves/yield_curve.py`, `duration`

Current behavior:

- Macaulay duration is based on curve-discounted cash flows.
- Modified duration divides by `1 + r_T / freq`, where `r_T` is a zero rate at
  maturity.
- `YieldCurve.duration` assumes semiannual compounding and ignores its `prices`
  argument.

Impact:

- Reported modified duration may not match the reported YTM convention or the
  curve used for pricing.

Required fix:

- Separate yield-based duration from curve-risk duration and define compounding
  conventions explicitly.

### FI-009 - Bond convexity is a time moment, not market-convention convexity

Severity: P1

Location:

- `instruments/fixed_income.py`, `fixed_bond`, `zcb`

Current behavior:

- Convexity is computed as PV-weighted `t^2`.
- It does not account for yield compounding, coupon frequency convention, or
  finite-difference curve shifts.

Impact:

- The number is useful as a rough time moment but may not match trader or risk
  reports.

Required fix:

- Provide both analytical yield convexity and finite-difference curve convexity,
  with names that distinguish them.

### FI-010 - DV01 is not consistently finite-difference based

Severity: P1

Location:

- `instruments/fixed_income.py`, `zcb`, `fixed_bond`, `frn`, `irs`
- `curves/yield_curve.py`, `dv01`

Current behavior:

- ZCB and bond DV01 use analytical duration proxies.
- FRN DV01 uses an arbitrary `0.1` scaling.
- IRS DV01 is fixed-leg annuity only.

Impact:

- DV01 results are not comparable across products and may not equal actual price
  sensitivity to a one basis point curve move.

Required fix:

- Centralize DV01 as a pricing-service sensitivity using bumped
  `MarketDataSnapshot` / `YieldCurve` inputs and product-specific repricing.

### FI-011 - Yield curve validation only checks input nodes

Severity: P1

Location:

- `curves/yield_curve.py`, `YieldCurve.validate`, `_build_interp`

Current behavior:

- Validation checks node discount factors.
- Cubic interpolation and extrapolation can still create non-monotonic discount
  factors or unstable forwards between nodes.

Impact:

- Curve instances can pass validation but produce bad pricing at cash-flow dates.

Required fix:

- Validate discount factors and forward rates on a dense grid over the curve
  domain, including interpolation and controlled extrapolation behavior.

### FI-012 - Bootstrapping is not instrument-aware

Severity: P1

Location:

- `curves/yield_curve.py`, `from_par_rates`, `bootstrap`

Current behavior:

- Par-rate bootstrap uses simplified coupon periods and year fractions.
- Instrument bootstrap uses tuple inputs without dates, settlement, calendars, or
  conventions.
- Bootstrap failure falls back to `0.03` in one path.

Impact:

- Bootstrapped curves may not reproduce market instruments under real
  conventions.

Required fix:

- Move bootstrapping into `MarketDataService` or a dedicated curve construction
  service using explicit instrument quotes and conventions.

### FI-013 - OFZ accrued interest logic conflicts with its own convention note

Severity: P1

Location:

- `curves/russia.py`, `price_ofz`

Current behavior:

- Docstring says Russian OFZ use 30/360.
- Default `day_count` is `365`.
- Accrued interest is derived from `accrued_days` without coupon-date validation.

Impact:

- OFZ clean price and accrued interest can be wrong by convention.

Required fix:

- Implement OFZ convention explicitly and remove ad hoc accrued-day logic from
  curve helper code.

### FI-014 - Curve and pricing responsibilities are still mixed

Severity: P1

Location:

- `curves/russia.py`, `price_ofz`

Current behavior:

- A curve module contains an OFZ pricing function that imports
  `instruments.fixed_income.fixed_bond`.

Impact:

- This violates the target architecture direction. Curve modules should own curve
  construction and market data, while pricing belongs in pricing/domain services.

Required fix:

- Move OFZ pricing workflow into the pricing service or a fixed-income service,
  while keeping a temporary compatibility wrapper.

### FI-015 - Bond result contract is incomplete

Severity: P2

Location:

- `instruments/fixed_income.py`, `fixed_bond`

Current behavior:

- Result contains price, YTM, z-spread, durations, convexity, DV01, and cash-flow
  times.
- It does not contain valuation date, settlement date, clean price, dirty price,
  accrued interest, day count, coupon dates, or pricing warnings.

Impact:

- Services and UI must infer or fake missing concepts, creating duplicated logic.

Required fix:

- Add a canonical fixed-income pricing result object under the domain layer.

### FI-016 - Cash-flow tables can display PVs inconsistent with selected curve

Severity: P2

Location:

- `app/panels/bond_panel.py`

Current behavior:

- Bond valuation uses the selected curve.
- Cash-flow table PVs use the manual flat-rate input.

Impact:

- Users can see a price calculated from one curve and cash-flow PVs calculated
  from another curve.

Required fix:

- Use the same curve instance for valuation and cash-flow PV display.

### FI-017 - No fixed-income model governance flags in result objects

Severity: P2

Location:

- `instruments/fixed_income.py`

Current behavior:

- Function docstrings mention approximations, but return payloads do not expose
  approximation status, model limitations, or source metadata.

Impact:

- Service and UI layers cannot reliably warn users when a model is approximate.

Required fix:

- Return model metadata through the model registry / governance service.

### FI-018 - No key-rate or bucketed curve risk

Severity: P2

Location:

- `instruments/fixed_income.py`
- `curves/yield_curve.py`

Current behavior:

- Only scalar DV01-style measures are returned.

Impact:

- Portfolio and risk workflows cannot attribute fixed-income exposure by tenor.

Required fix:

- Add key-rate DV01 and bucketed sensitivity after the core pricing conventions
  are corrected.

### FI-019 - FRN and IRS do not model historical/current fixings

Severity: P2

Location:

- `instruments/fixed_income.py`, `frn`, `irs`
- `curves/russia.py`, `ruonia_compounded`

Current behavior:

- Current coupon/fixing state is absent from FRN and IRS.
- RUONIA compounding helper is isolated and not wired into valuation.

Impact:

- Seasoned floating-rate instruments cannot be valued correctly.

Required fix:

- Add fixing series ownership to market data snapshots and require fixing lookup
  for active coupon periods.

### FI-020 - NS/Svensson calibration has weak validation

Severity: P2

Location:

- `curves/yield_curve.py`, `NSCurve.fit`, `SvenssonCurve.fit`

Current behavior:

- Calibration has basic constraints but does not enforce monotonic discount
  factors, positive discount factors, stable forwards, or bounded extrapolation.

Impact:

- Fitted curves can look plausible while producing unstable risk and pricing.

Required fix:

- Apply the same curve quality gates used for raw/interpolated curves.

### FI-021 - Function names do not distinguish demo approximation from production model

Severity: P3

Location:

- `instruments/fixed_income.py`

Current behavior:

- `fixed_bond`, `frn`, and `irs` sound like production pricing functions even
  where implementation is approximate.

Impact:

- Developers may route production workflows through demo logic.

Required fix:

- Add explicit model registry entries and expose approximation status in service
  APIs.

### FI-022 - Missing fixed-income regression tests

Severity: P3

Location:

- `tests/`

Current behavior:

- Existing tests validate architecture and market-data foundation, but not fixed
  income methodology.

Impact:

- Refactors can silently change valuation outputs.

Required fix:

- Add tests for zero-coupon bonds, par fixed bonds, accrued interest, clean/dirty
  consistency, FRN-at-reset behavior, par swap NPV, finite-difference DV01, and
  curve validation.

### FI-023 - Z-spread solver returns NaN without diagnostics

Severity: P3

Location:

- `instruments/fixed_income.py`, `fixed_bond`

Current behavior:

- Z-spread failure returns `np.nan`.

Impact:

- UI and services cannot distinguish no solution, bad inputs, or numerical
  failure.

Required fix:

- Return structured pricing warnings or errors.

### FI-024 - Yield curve helper API has unused or misleading parameters

Severity: P3

Location:

- `curves/yield_curve.py`, `duration`

Current behavior:

- `duration(cashflows, prices)` accepts `prices` but does not use it.

Impact:

- The API is confusing and can cause incorrect assumptions during refactoring.

Required fix:

- Remove the unused parameter or define its intended role.

### FI-025 - Day-count and compounding metadata are not enforced downstream

Severity: P3

Location:

- `curves/yield_curve.py`
- `instruments/fixed_income.py`

Current behavior:

- Curves carry `day_count` and `compounding` metadata, but pricing functions
  generally use hard-coded year fractions and continuous discounting.

Impact:

- Metadata exists but does not yet govern valuation behavior.

Required fix:

- Make pricing services consume these metadata fields explicitly or reject
  unsupported conventions.

## Review Matrix

| Check | Bond | FRN | IRS | Yield curves |
| --- | --- | --- | --- | --- |
| Day count conventions | P1: absent for dates | P1: absent | P1: absent | P1: declared but identity |
| Settlement logic | P1: absent | P1: absent | P1: absent | P2: valuation date metadata only |
| Coupon schedule generation | P0: rounded year grid | P0: rounded year grid | P0: rounded year grid | P1: par/bootstrap use rounded periods |
| Accrued interest | P0: not core | P1: active coupon absent | P1: active coupon absent | N/A |
| Dirty/clean consistency | P0: inconsistent | N/A | N/A | N/A |
| Duration | P1: mixed conventions | P1: arbitrary low-duration proxy | P1: not a true swap duration | P1: assumes semiannual compounding |
| Convexity | P1: time moment only | N/A | N/A | P2: no curve convexity tools |
| DV01 | P1: analytical proxy | P0: arbitrary scaling | P1: annuity only | P1: ZCB-only helper |

## Architectural Impact

The fixed-income layer still needs a domain cleanup before any UI redesign:

1. Domain layer must own instrument contracts:
   - Fixed-rate bond spec
   - FRN spec
   - IRS spec
   - Coupon schedule
   - Day-count convention
   - Settlement convention
   - Pricing result

2. Service layer must own workflows:
   - Market data snapshot selection
   - Curve construction
   - Pricing model selection through the model registry
   - Sensitivity calculation through repricing
   - Validation and governance warnings

3. Curve modules must not own product pricing:
   - `curves.russia.price_ofz` should become a compatibility wrapper or move to
     a fixed-income pricing service.

4. UI should remain downstream:
   - UI panels should display service results and warnings, not construct missing
     financial concepts such as accrued interest.

## Recommended Remediation Order

### Step 1 - Add fixed-income domain contracts

Difficulty: Medium

Risk: Medium

Affected files:

- `domain/`
- `instruments/fixed_income.py`
- `services/pricing_service.py`
- `tests/`

Tasks:

- Add date-based schedule, day-count, settlement, and pricing result contracts.
- Preserve existing function signatures through adapters.

### Step 2 - Implement schedule and day-count engine

Difficulty: Medium

Risk: Medium

Affected files:

- `domain/`
- `services/`
- `tests/`

Tasks:

- Implement ACT/365, ACT/360, 30/360, ACT/ACT.
- Implement regular coupon schedules and basic stub support.
- Add settlement date and accrual period calculation.

### Step 3 - Rewrite bond pricing around generated cash flows

Difficulty: Medium

Risk: Medium

Affected files:

- `instruments/fixed_income.py`
- `services/pricing_service.py`
- `curves/russia.py`
- `app/panels/bond_panel.py`
- `tests/`

Tasks:

- Return dirty price, clean price, accrued interest, cash-flow dates, accrual
  factors, and warnings.
- Use finite-difference DV01 and clearly named yield-duration analytics.

### Step 4 - Replace FRN approximation

Difficulty: High

Risk: High

Affected files:

- `instruments/fixed_income.py`
- `services/market_data_service.py`
- `services/pricing_service.py`
- `domain/`
- `tests/`

Tasks:

- Add floating coupon projection.
- Add current fixing support.
- Separate projection and discount curves.

### Step 5 - Replace IRS approximation

Difficulty: High

Risk: High

Affected files:

- `instruments/fixed_income.py`
- `services/market_data_service.py`
- `services/pricing_service.py`
- `domain/`
- `app/panels/irs_panel.py`
- `tests/`

Tasks:

- Add fixed/floating leg schedules.
- Add projection and discount curve support.
- Add par swap, NPV, annuity, DV01, and leg-level PV outputs.

### Step 6 - Harden curve validation

Difficulty: Medium

Risk: Medium

Affected files:

- `curves/yield_curve.py`
- `services/market_data_service.py`
- `tests/`

Tasks:

- Remove silent clipping from production paths.
- Validate interpolated discount factors and forwards.
- Reject bad extrapolation unless explicitly allowed for demo curves.

## Test Requirements

Minimum fixed-income tests before production routing:

- Zero-coupon bond price equals `face * discount(T)`.
- Fixed-rate bond clean plus accrued equals dirty.
- Fixed-rate par bond prices near par under matching flat curve and coupon.
- Accrued interest matches 30/360 and ACT conventions on known date examples.
- FRN with zero spread prices near par at reset.
- IRS at fair fixed rate has near-zero NPV.
- Bond DV01 equals finite-difference price change under a 1 bp curve shift.
- IRS DV01 equals finite-difference NPV change under a 1 bp curve shift.
- Curve validation rejects NaN, inf, non-positive discount factors, and
  non-monotonic interpolated discount factors.

## Conclusion

The fixed-income stack should remain marked as approximate until the above P0 and
P1 items are resolved. The most urgent corrections are FRN valuation, IRS
valuation, clean/dirty bond pricing, real schedule generation, day-count
implementation, and removal of silent curve clipping from production valuation
paths.
