# RiskCalc Audit Report

Date: 2026-06-03
Repository: `dwooo3/RC_project`

This document is a technical and methodological audit of the current RiskCalc repository. It is intended as an implementation backlog for another AI agent or developer. The project must be treated as a prototype/research terminal until the P0/P1 items below are resolved and covered by tests.

---

## 0. Executive Summary

RiskCalc has moved in the right direction: navigation is now workflow-oriented, there is a model registry, and core quantitative modules are separated from UI panels. However, it is not production-ready.

Main blockers:

1. Weighted Historical VaR is inconsistent across modules.
2. Monte Carlo control variate has a discounting bug.
3. Heston antithetic path generation can break for odd simulation counts.
4. Portfolio aggregation mixes incompatible Greeks and risk units.
5. Fixed income methodology is too simplified for production use.
6. Market data is still demo/manual and not source-controlled by valuation date.
7. UI still has too much technical content on Dashboard and too many borders/frames.
8. Test coverage is narrow and does not validate the most important risk models.

---

## 1. Current Application Architecture

### Current positive changes

The application now uses 7 top-level sections:

```text
Dashboard
Market
Pricing
Portfolio
Risk
Analytics
Settings
```

This is the correct product direction. The previous structure, where every instrument was a direct sidebar item, was developer-oriented and created visual overload.

### Remaining issue

The new shell is only partially implemented. The main window and lazy panel loading are acceptable, but individual panels still look like technical PySide calculators rather than a unified institutional pricing/risk terminal.

### Target architecture

Keep exactly 7 top-level sidebar sections:

```text
Dashboard
Market
Pricing
Portfolio
Risk
Analytics
Settings
```

Do not add instrument-level entries to the sidebar. Instrument modules must live inside workspaces.

---

## 2. UI / UX Audit

## 2.1 Dashboard

### Current problem

Dashboard still contains technical model validation information and a large Quick Access block. This makes the first screen look like a diagnostic report, not a professional terminal start page.

### Required target

Dashboard should contain only:

1. Portfolio KPIs.
2. P&L / exposure summary.
3. Market data status.
4. Recent work.
5. Critical alerts only.

### Remove from Dashboard

- Full model validation table.
- Long model notes.
- Developer-style registry diagnostics.
- Excessive separators.
- Large Quick Access grid if it duplicates the sidebar.

### Move to Risk section

Move model validation into:

```text
Risk -> Model Validation
```

### New Dashboard layout

```text
Header
  RiskCalc
  Market Risk & Pricing Engine
  Data source chip

KPI row
  Portfolio MV
  Daily P&L
  VaR 95%
  ES 95%
  DV01
  Vega

Middle row
  P&L chart
  Exposure by asset class
  Yield curve snapshot
  Vol surface snapshot

Lower row
  Recent Work
  Market Data Status
  Critical Alerts
```

### Design rules

- Use cards, not bordered tables.
- KPI value should be large, 28-40px.
- Labels should be small, 10-12px, uppercase, muted.
- Maximum one border per card.
- Avoid nested borders.

---

## 2.2 Sidebar

### Current issue

The sidebar is structurally correct but visually plain. It uses placeholder square icons and still feels like a PySide menu.

### Required changes

Replace placeholder icon strings with either:

1. No icons at all, or
2. Minimal monochrome icons from a consistent source.

Recommended sidebar:

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

v1.0 · Demo market data
```

### Design rules

- Sidebar width: 220-240px.
- Active item: subtle orange background, not heavy border.
- Inactive item: muted gray.
- Do not use visual dividers after every item.
- Keep only one divider between logo/header and nav.

---

## 2.3 Workspace layout

All main modules must use a single layout pattern.

### Required module layout

```text
Breadcrumb / title

Left column: Inputs
Center: Results and charts
Right column: Context panel
Bottom: Details tabs
```

### Pricing module example

```text
Pricing > Bonds

Tabs:
Pricing | Cashflows | Sensitivities | Scenario | Validation
```

### Risk module example

```text
Risk > VaR

Tabs:
Overview | Historical | Parametric | Monte Carlo | Backtesting | Validation
```

### Market module example

```text
Market > Yield Curves

Tabs:
Overview | Curve Builder | Par/Zero/Forward | Scenarios | Validation
```

---

## 2.4 Card and border system

### Current problem

Too many frames, borders and horizontal separators. The UI becomes noisy and information is hard to parse.

### Required rule

Remove approximately 70% of visible lines.

### Use borders only for

- Cards.
- Tables.
- Focused input state.
- Major workspace separation.

### Do not use borders for

- Every group box.
- Every nested frame.
- Every header.
- Every row.

### Recommended palette

Dark theme:

```css
background: #0D0D0D;
sidebar:    #171717;
card:       #202020;
card_hover: #242428;
border:     #2A2A2A;
text:       #F5F5F5;
muted:      #8E8E93;
accent:     #D97757;
```

Light theme:

```css
background: #FAFAFA;
sidebar:    #FFFFFF;
card:       #FFFFFF;
border:     #E5E5E5;
text:       #111111;
muted:      #666666;
accent:     #D97757;
```

---

## 3. Quantitative Model Audit

---

## 3.1 Black-Scholes / Black-76 / Garman-Kohlhagen / Bachelier

### Status

Approximation. Useful and structurally sound, but not hardened.

### Problems

#### BSM expiry delta for put is wrong

At expiry, BSM currently returns a delta convention that handles calls only. For an in-the-money put, delta should be approximately -1. For an out-of-the-money put, delta should be 0. At-the-money should follow a documented convention.

#### No zero-volatility handling

If volatility is zero or negative, the d1/d2 helper returns NaN. The pricing functions then propagate NaNs. Production logic must return deterministic discounted intrinsic / forward payoff or raise a controlled `ValueError`.

#### Bachelier zero normal volatility issue

If `sigma_n <= 0`, division by zero occurs in the normal model. Add explicit guards.

#### Greek conventions are not enforced

The code uses:

- Vega per 1% volatility move.
- Rho per 1% rate move.
- Theta per calendar day.

This must be displayed in UI and encoded in metadata.

### Required fixes

1. Add input validation.
2. Add deterministic zero-volatility branch.
3. Fix put delta at expiry.
4. Add explicit `greek_convention` metadata.
5. Add tests:
   - BSM zero vol.
   - BSM expiry call/put delta.
   - Black-76 zero vol.
   - Bachelier zero normal vol.
   - invalid inputs.

---

## 3.2 Tree models: CRR, Leisen-Reimer, Trinomial

### Status

Approximation. Recursion has been addressed, but model validity is not fully controlled.

### Problems

#### Silent probability clipping in CRR

Risk-neutral probability is clipped to `[0, 1]`. This hides invalid model conditions and can produce misleading prices.

#### Trinomial probabilities are clipped but not renormalized

After setting negative probabilities to zero, probabilities may not sum to 1. This is methodologically invalid.

#### Leisen-Reimer edge cases

The model can become unstable for extreme parameters, especially where transformed probabilities approach zero.

#### Missing convergence tests

There are no sufficiently strong tests showing convergence of CRR/LR/Trinomial prices to BSM for European vanilla options.

### Required fixes

1. Do not silently clip CRR probability.
2. Return validation warning/error if probability is outside `[0, 1]`.
3. For trinomial, either enforce valid parameter region or renormalize probabilities with warning.
4. Add convergence tests:
   - CRR European call to BSM.
   - LR European call to BSM.
   - Trinomial European call to BSM.
   - American put >= European put.
   - Invalid parameter test.

---

## 3.3 Monte Carlo engine

### Status

Research prototype. Good base, not production.

### Problems

#### Odd `n_sims` with antithetic paths

When `antithetic=True` and `n_sims` is odd, GBM returns fewer paths than requested. Heston can produce shape mismatch because arrays are allocated with requested `n_sims` while generated shocks may have fewer rows.

#### Control variate discounting bug

The control variate uses discounted terminal spot, but the theoretical expectation is inconsistent. If the control variable is `disc * S_T`, its expectation should be `S0 * exp(-qT)`, not the forward `S0 * exp((r-q)T)`.

#### Moment matching is global

Moment matching is applied to the entire random matrix, not step-by-step. This must either be changed or documented.

#### Standard error uses requested simulations

`stderr` uses `sqrt(n_sims)` even if actual number of paths differs.

#### Multi-asset Cholesky has no fallback

Non-positive-definite correlation matrices will crash. Add nearest positive-definite repair or controlled error.

#### LSM lacks diagnostics

Longstaff-Schwartz returns price/stderr/delta/gamma only. It does not expose exercise boundary, exercise counts or regression diagnostics.

### Required fixes

1. Return `actual_sims` from all path generators.
2. For antithetic simulations, round up to an even number or validate input.
3. Fix control variate expected value.
4. Use `pv.std(ddof=1) / sqrt(actual_sims)`.
5. Add nearest-PD correlation handling.
6. Add LSM diagnostics:
   - exercise counts by step/date;
   - approximate exercise boundary;
   - regression R2;
   - warnings for low ITM sample count.
7. Add tests:
   - MC European call vs BSM within confidence interval;
   - antithetic odd n_sims;
   - control variate unbiasedness;
   - non-PD correlation handling.

---

## 3.4 VaR / ES / Backtesting

### Status

Mixed. Some functions are improved, but duplicate logic creates inconsistency.

### Critical issue

There are two Historical VaR implementations with inconsistent weighted logic:

- `risk/historical_var.py` has corrected age-weighted VaR logic.
- `risk/var.py` still uses older weighted branch logic.

### Problems

#### Weighted Historical VaR in `risk/var.py`

The weighted branch uses lower-tail return sorting and `1-confidence`, but does not apply horizon scaling consistently with the unweighted branch.

#### Component VaR in `historical_var.py`

`portfolio_hs_var()` calculates `var_up = -np.percentile(-pnl_up, confidence*100)`, then compares it to positive `res['VaR']`. This sign convention is likely inconsistent.

#### Monte Carlo full repricing masks pricing failures

If repricing fails, the code appends zero P&L. This understates VaR and hides pricing failures.

### Required fixes

1. Consolidate Historical VaR into one implementation.
2. Remove or refactor duplicate function in `risk/var.py`.
3. For weighted VaR, use explicit loss distribution and weighted quantile.
4. Apply horizon scaling consistently.
5. Do not replace failed MC repricing with zero P&L. Store failure count and fail the calculation if failures exceed threshold.
6. Add tests:
   - known array VaR;
   - weighted quantile;
   - ES >= VaR;
   - horizon scaling;
   - Kupiec edge cases;
   - Christoffersen edge cases.

---

## 3.5 Portfolio aggregation

### Status

Prototype. Not valid for production risk aggregation.

### Problems

#### Mixed risk units

Portfolio aggregation directly sums:

```text
delta, gamma, vega, theta, rho, dv01, cs01
```

This is not valid across asset classes unless all values have a consistent factor mapping, currency, bump size and unit convention.

#### Bond delta is not a true delta

Bond position assigns delta using modified duration and market value. This should not be aggregated with equity or option delta.

#### FX forward valuation is too simplified

FX forward market value ignores discounting, currency legs and settlement conventions.

#### Pricing errors are swallowed

If pricing fails, price is set to NaN but the error is not stored or surfaced.

### Required fixes

1. Introduce `RiskFactorExposure` dataclass:

```python
@dataclass
class RiskFactorExposure:
    factor_name: str
    factor_type: str
    currency: str
    bump_size: float
    sensitivity: float
    unit: str
```

2. Aggregate by risk factor, not by raw Greek name.
3. Remove bond `delta` or rename it to `rate_exposure_proxy` if kept.
4. Add position-level `pricing_status` and `pricing_error`.
5. Exclude failed positions from risk aggregation unless explicitly allowed.
6. Add tests for mixed asset-class portfolio aggregation.

---

## 3.6 Stress testing

### Status

Demo scenario engine.

### Problems

#### Historical scenarios are generic

Scenarios are hardcoded as simple spot/vol/rate shocks. They do not map by region, asset class, currency, curve bucket or factor.

#### `pnl_explain()` naming is wrong

`total_1st_order` includes only delta and theta. It excludes vega and rho, while `total_2nd_order` includes more terms. Naming is misleading.

#### Stress is mostly Greeks-based

Production stress should support full repricing and use Greeks only as approximation/explain.

### Required fixes

1. Create `Scenario` dataclass with:
   - name;
   - source;
   - date;
   - severity;
   - factor shocks;
   - applicable asset classes.
2. Separate full repricing stress from Greeks explain.
3. Rename P&L explain totals:
   - `total_delta_theta`;
   - `total_first_order`;
   - `total_second_order`;
   - `total_with_cross`.
4. Add portfolio-level stress function.
5. Add tests for P&L explain formulas.

---

## 3.7 Fixed income / OFZ / IRS / FRN

### Status

Approximation/prototype. Not valid for production fixed income pricing.

### Problems

#### Fixed bond has no dates

The function uses maturity in years and frequency only. It does not have:

- settlement date;
- coupon schedule;
- day count;
- accrued interest;
- business day calendar;
- clean/dirty price separation at core level.

#### FRN is methodologically too simplified

Current FRN logic approximates par plus spread PV and ignores reset timing, current coupon, projection curve and discount curve split.

#### IRS is single-curve

IRS pricing uses one curve and `1 - DF(T)` style floating leg. There is no OIS discounting/projection curve separation, fixing lag, schedule or day count.

#### Cap/Floor first caplet degeneracy

The first caplet starts at `T1=0`, which can create degenerate Black-76 pricing. Needs explicit handling.

### Required fixes

1. Add schedule engine:
   - start date;
   - maturity date;
   - frequency;
   - day count;
   - business day convention.
2. Split bond price into clean/dirty/accrued.
3. Add dual-curve IRS:
   - discount curve;
   - projection curve;
   - fixed leg schedule;
   - floating leg schedule.
4. Rebuild FRN:
   - current reset coupon;
   - future forward coupons;
   - spread;
   - discounting.
5. Add FI tests:
   - par bond price near par;
   - zero coupon known value;
   - DV01 finite difference;
   - par swap NPV approx zero;
   - FRN near par at reset.

---

## 3.8 Curves

### Status

Useful prototype, but conventions and market data semantics are incomplete.

### Problems

#### `year_fraction()` is identity

The function accepts float `T` and ignores actual dates. This is acceptable for demos but not production.

#### Cubic spline can create arbitrage-like shapes

Cubic interpolation on zero rates can create non-monotonic discount factors or unstable forwards. Need monotonic/shape-preserving options.

#### Rate clipping hides errors

`rate()` clips rates to `[-0.3, 2.0]`. This hides extrapolation/calibration issues.

#### Duration function has unused parameter

`duration(self, cashflows, prices)` accepts `prices` but does not use it.

#### `from_par_rates()` is simplified

Bootstrap assumes annualized par rates with simple coupon convention and does not validate tenor/frequency consistency.

#### NS/Svensson calibration has weak constraints

Calibration uses Nelder-Mead with limited constraints. It does not enforce parameter bounds or robust initializations.

### Required fixes

1. Implement real day count on date pairs.
2. Add interpolation choices:
   - linear zero;
   - linear discount factor;
   - log-linear discount factor;
   - PCHIP zero or discount.
3. Do not silently clip rates. Return warnings or errors.
4. Remove unused `prices` parameter from duration or use it properly.
5. Add curve validation:
   - positive discount factors;
   - monotonic discount factors;
   - reasonable forwards;
   - no NaN/inf.
6. Add tests for rate/DF conversion and par/zero consistency.

---

## 3.9 Russian market curves

### Status

Demo-only until MOEX ISS integration is implemented.

### Problems

#### Manual default data

OFZ, RUONIA and CBR key rate are hardcoded. The module says MOEX ISS integration is pending.

#### Ambiguous rate type

OFZ default rates are described as G-curve/par/zero inconsistently. If they are zero rates, they should be named zero rates. If par yields, they require bootstrap.

#### OFZ accrued convention is inconsistent

Docstring mentions 30/360, but default calculation uses 365-style denominator.

#### RUONIA compounding documentation mismatch

The docstring says continuous rates, while implementation compounds with `1 + r/365`.

### Required fixes

1. Add `MarketDataSnapshot`:

```python
@dataclass
class MarketDataSnapshot:
    valuation_date: date
    source: str
    data_type: str
    tenors: list[float]
    values: list[float]
    rate_type: str
    compounding: str
    day_count: str
```

2. Mark all hardcoded defaults as Demo.
3. Add MOEX ISS provider later.
4. Split OFZ zero curve and OFZ par curve construction.
5. Fix RUONIA convention.
6. Fix OFZ accrued interest convention.

---

## 4. Model Registry Audit

The registry is valuable and should be kept.

### Required improvements

1. Add `severity` field:
   - P0;
   - P1;
   - P2;
   - P3.
2. Add `production_allowed: bool`.
3. Add `owner` or `module_path`.
4. Add `last_validated` date.
5. Add `references` field.
6. Add `test_coverage_status`.

Recommended model status categories:

```text
Validated
Approximation
Prototype
Placeholder
Broken
Disabled
```

Production UI must block or warn on `Prototype`, `Placeholder`, `Broken`, `Disabled`.

---

## 5. Tests and Quality Gates

### Current issue

Tests exist but mostly cover Black-Scholes-style closed-form models. Coverage must be extended to risk, FI, curves and portfolio aggregation.

### Required test structure

```text
tests/
  test_black_scholes.py
  test_trees.py
  test_monte_carlo.py
  test_var.py
  test_historical_var.py
  test_portfolio.py
  test_fixed_income.py
  test_yield_curve.py
  test_russia_curves.py
  test_stress.py
```

### Required CI

Add GitHub Actions:

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

---

## 6. P0 Backlog

These must be fixed first.

| ID | Area | Problem | Required Fix |
|---|---|---|---|
| P0-001 | VaR | Weighted Historical VaR inconsistent between modules | Consolidate implementation and correct weighted loss quantile |
| P0-002 | MC | Control variate expected value is wrong | Use expectation of discounted terminal spot |
| P0-003 | MC | Heston odd `n_sims` shape bug | Enforce even simulations or use actual_sims |
| P0-004 | BSM | Zero-vol and expiry edge cases | Add deterministic branches and tests |
| P0-005 | Trees | Silent probability clipping | Replace with validation/warning |
| P0-006 | Portfolio | Mixed Greeks aggregation | Introduce risk factor exposure model |
| P0-007 | Stress | Misleading P&L explain totals | Rename and correct total fields |
| P0-008 | Curves | Manual market data may look real | Mark all defaults as Demo-only |

---

## 7. P1 Backlog

| ID | Area | Problem | Required Fix |
|---|---|---|---|
| P1-001 | FI | Bond pricing has no dates/accrual schedule | Add schedule engine |
| P1-002 | FI | IRS is single-curve | Add dual-curve IRS |
| P1-003 | FI | FRN lacks reset/projection logic | Rebuild FRN pricing |
| P1-004 | Curves | Weak interpolation/convention model | Add curve validation and interpolation options |
| P1-005 | Risk | Backtesting coverage narrow | Add Kupiec/Christoffersen edge tests |
| P1-006 | UI | Dashboard contains validation registry | Move validation to Risk section |
| P1-007 | UI | Too many borders | Implement card-based design system |
| P1-008 | Registry | No production gating | Add production_allowed and severity |

---

## 8. Target UI Implementation Instructions

### Step 1: Create shared UI components

Create:

```text
app/ui/components.py
app/ui/theme.py
app/ui/layouts.py
```

Components:

```text
KpiCard
SectionHeader
WorkspaceCard
ContextPanel
StatusChip
ModelWarningBanner
ModernTable
```

### Step 2: Replace Dashboard

Dashboard should not show the full model registry.

### Step 3: Create workspace screens

```text
MarketWorkspace
PricingWorkspace
PortfolioWorkspace
RiskWorkspace
AnalyticsWorkspace
SettingsWorkspace
```

### Step 4: Standardize internal tabs

Pricing modules:

```text
Pricing | Cashflows | Sensitivities | Scenario | Validation
```

Risk modules:

```text
Overview | Historical | Parametric | Monte Carlo | Backtesting | Validation
```

Market modules:

```text
Overview | Builder | Curves | Scenarios | Validation
```

### Step 5: Use model status everywhere

Every module header must show:

```text
Model status: Approximation / Prototype / Placeholder
Production allowed: Yes/No
Validation notes
```

---

## 9. Definition of Done

RiskCalc can be considered demo-quality when:

1. All P0 items are fixed.
2. Tests run in CI.
3. Dashboard no longer contains technical validation tables.
4. Models with Prototype/Placeholder status show warnings.
5. Weighted VaR has one implementation.
6. Monte Carlo known bugs are fixed.
7. Portfolio aggregation no longer mixes raw Greeks across asset classes.

RiskCalc can be considered production-candidate only when:

1. Market data has valuation date and source.
2. FI has real date schedules and day count conventions.
3. IRS/FRN methodology is rebuilt.
4. VaR/ES/backtesting has strong tests.
5. Model registry blocks non-production models.
6. UI clearly marks demo/manual data.
7. Error handling and logs are implemented.

---

## 10. Recommended Implementation Order

1. Fix P0 model bugs.
2. Add tests for P0 bugs.
3. Refactor Dashboard.
4. Add shared UI component layer.
5. Move validation to Risk section.
6. Refactor portfolio aggregation.
7. Refactor curves and market data snapshot.
8. Rebuild FI models.
9. Add CI.
10. Only then start cosmetic polish.

---

## 11. Final Assessment

RiskCalc is a strong prototype and a good portfolio project. It should not be described as production-ready yet. The current correct framing is:

```text
Research-grade pricing and risk analytics prototype with model validation registry and workflow-oriented UI shell.
```

After the P0/P1 backlog is implemented, it can become a serious demonstrator for market risk / quant pricing workflows.
