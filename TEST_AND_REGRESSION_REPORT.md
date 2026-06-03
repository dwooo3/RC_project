# Test and Regression Report

Date: 2026-06-04

Scope:

- Full test suite
- Import sanity
- Duplicate class definitions
- Broken module paths
- Direct UI-to-model coupling
- Empty/skeleton services
- Silent exception swallowing

Production code changes:

- None.

## Test Results

Command:

```bash
python3 -m pytest
```

Result:

```text
58 passed in 5.61s
```

Collected tests:

- `tests/test_architecture_phase1.py` - passed
- `tests/test_black_scholes.py` - passed
- `tests/test_market_data_foundation.py` - passed
- `tests/test_monte_carlo.py` - passed
- `tests/test_portfolio_service.py` - passed
- `tests/test_trees.py` - passed
- `tests/test_var.py` - passed

Failed tests:

- None.

## Static Sanity Checks

### Compile Check

Command:

```bash
python3 -m compileall -q .
```

Result:

- Passed.
- No syntax-level failures detected.

### Import Check

Core package import command covered:

- `domain`
- `services`
- `risk`
- `models`
- `instruments`
- `curves`

Result:

```text
CORE_IMPORT_FAILURES 0
```

Full package import command also included `app`.

Result:

```text
IMPORT_FAILURES 42
```

All 42 failures were caused by:

```text
ModuleNotFoundError: No module named 'PySide6'
```

Affected UI modules include:

- `app.chart`
- `app.main_window`
- `app.widgets`
- all `app.panels.*` modules

Interpretation:

- Core engine imports are healthy.
- UI imports cannot be fully validated in this environment because `PySide6` is
  not installed.
- This is an environment/dependency risk, not a proven broken module path inside
  the core packages.

### Additional Import Problem Found by Static Search

File:

- `app/panels/stress_panel.py`

Problem:

- Uses `ModelStatus.APPROXIMATION` but does not import `ModelStatus`.

Evidence:

- `app/panels/stress_panel.py:6` imports `ParamForm`, `FieldRow`, `ResultsGrid`,
  `SectionHeader`, `Banner`, `make_spin`, `make_pct`, `make_combo`.
- `app/panels/stress_panel.py:18` references `ModelStatus.APPROXIMATION`.

Impact:

- Once `PySide6` is installed, `StressPanel` initialization is likely to fail
  with `NameError`.

Fix status:

- Not fixed in this run because production code changes were only allowed for
  broken imports, and the missing `PySide6` dependency prevents confirming the UI
  import path dynamically. This should be the first minimal UI fix in the next
  code pass.

## Duplicate Class Definitions

Static class scan found these relevant duplicate or compatibility definitions:

### `VolSurface`

Files:

- `models/implied_vol.py`
- `risk/vol_surface.py`

Risk:

- Potential duplicate ownership of volatility surface concepts.
- This conflicts with the target architecture where Market Data should own
  volatility surfaces and Risk should consume them.

Recommended action:

- Decide canonical ownership, likely market-data/domain service ownership.
- Keep one implementation or make one an adapter.

### `Portfolio`

Files:

- `domain/portfolio.py`
- `risk/portfolio.py`

Risk:

- Low immediate risk because `risk.portfolio.Portfolio` is an explicit
  backward-compatible facade over `PortfolioService`.

Recommended action:

- Keep temporarily.
- Remove only after all imports move to `domain.Portfolio` or
  `services.PortfolioService`.

### `YieldCurve`

Files:

- `curves/yield_curve.py`

Status:

- No duplicate production `YieldCurve` class remains in fixed income.
- `instruments.fixed_income.YieldCurve` points to canonical curve ownership.

## Direct UI-to-Model Coupling

Static search found extensive direct imports from UI panels to:

- `models.*`
- `instruments.*`
- `risk.*`
- `curves.*`

Representative files:

- `app/panels/var_panel.py`
- `app/panels/histvar_panel.py`
- `app/panels/stress_panel.py`
- `app/panels/bond_panel.py`
- `app/panels/irs_panel.py`
- `app/panels/rates_panel.py`
- `app/panels/option_panel.py`
- `app/panels/montecarlo_panel.py`
- `app/panels/exotic_panel.py`
- `app/panels/fx_panel.py`
- `app/panels/credit_panel.py`
- `app/panels/yield_curve_panel.py`

Status:

- Expected for current migration stage.
- Still violates target dependency direction in `PRODUCT_ARCHITECTURE.md`:

```text
UI -> services -> domain -> engines
```

Immediate risk:

- Business logic remains duplicated in panels.
- Model governance and market-data snapshots are bypassed.
- UI behavior can diverge from service behavior as services are introduced.

Recommended action:

- Migrate panels incrementally through `PricingService`, `RiskService`, and
  `MarketDataService`.
- Start with `VarPanel`, `HistVarPanel`, `StressPanel`, `BondPanel`, and
  `IRSPannel`/`RatesPanel` because they touch known P0/P1 audit findings.

## Services Still Empty or Skeleton

### `services/pricing_service.py`

Status:

- Skeleton only.
- Holds `MarketDataService` and `GovernanceService`, but exposes no pricing
  workflow methods.

Impact:

- `PortfolioService` currently imports raw pricing engines directly.
- UI panels still bypass service routing.

Immediate fix priority:

- High.

### `services/risk_service.py`

Status:

- Skeleton only.
- Holds `MarketDataService` and `GovernanceService`, but exposes no VaR, ES,
  stress, backtesting, P&L explain, or scenario workflows.

Impact:

- Risk panels call raw risk functions directly.
- P0 issues in `RISK_MODEL_AUDIT.md` remain outside a governed service path.

Immediate fix priority:

- High.

### `services/market_data_service.py`

Status:

- Functionally useful despite header saying skeleton.
- Owns demo snapshots and curve factories.

Remaining gaps:

- Snapshot validation is shallow.
- Vol surfaces, FX, credit spreads, and source quality are not yet fully governed.
- Pricing/risk workflows are not forced to consume snapshots.

### `services/portfolio_service.py`

Status:

- Non-empty and functional.
- Owns portfolio pricing, exposure creation, bucket aggregation, and scenario P&L.

Remaining gaps:

- Directly imports raw engines instead of delegating to `PricingService`.
- Silently handles pricing failures by setting NaN without storing error details.
- Uses legacy scalar fields for compatibility.

## Silent Exception Swallowing

High-risk cases:

### `risk/historical_var.py`

Location:

- `mc_var_full_reprice`

Behavior:

- On pricing exception, appends zero P&L.

Impact:

- Understates VaR/ES by converting failed repricing scenarios into no-loss
  scenarios.

Immediate fix priority:

- P0.

### `services/portfolio_service.py`

Location:

- `price_all`

Behavior:

- On pricing exception, sets price and market value to NaN and clears exposures.
- Does not store `pricing_error` or structured warning.

Impact:

- Failures are visible only indirectly as NaN.
- Portfolio aggregation can proceed without a clear error contract.

Immediate fix priority:

- P1.

### `instruments/fixed_income.py`

Location:

- `fixed_bond` z-spread solver

Behavior:

- On solver failure, returns `np.nan` for z-spread.

Impact:

- Caller cannot distinguish no solution, bad inputs, or numerical failure.

Immediate fix priority:

- P1.

### `models/heston.py`

Location:

- Heston calibration objective

Behavior:

- On pricing exception, adds a penalty.

Impact:

- Acceptable as an optimizer tactic only if diagnostics expose failure counts.
- Currently no diagnostics are returned.

Immediate fix priority:

- P2.

### UI panels and workspaces

Behavior:

- Many panels catch exceptions and show banner errors, which is acceptable for UI
  containment.
- Some panels/workspaces use bare `pass`, which can hide missing panels or chart
  failures.

Representative files:

- `app/panels/impliedvol_panel.py`
- `app/panels/option_panel.py`
- `app/panels/risk_workspace.py`
- `app/panels/analytics_workspace.py`
- `app/panels/pricing_workspace.py`
- `app/panels/montecarlo_panel.py`

Immediate fix priority:

- P2 unless it hides a model/pricing error.

## Skipped Risks and Limitations

- UI runtime was not validated because `PySide6` is not installed in this
  environment.
- No GUI startup smoke test was run.
- No static type checker was run.
- No linter was run.
- No coverage report was generated.
- No benchmark or numerical regression baseline was generated.
- No full dependency graph was regenerated in this pass.
- `compileall` validates syntax but does not execute all runtime code paths.
- Importing app modules is blocked at dependency import time, so deeper UI import
  errors may still exist after `PySide6` is installed.

## Files That Need Immediate Fixes

### P0

- `risk/historical_var.py`
  - Stop replacing failed full-repricing MC scenarios with zero P&L.
  - Return failure count and fail above a governed tolerance.

### P1

- `app/panels/stress_panel.py`
  - Add missing `ModelStatus` import once UI dependency is available.

- `services/pricing_service.py`
  - Implement real pricing service methods.
  - Move raw engine calls out of `PortfolioService`.

- `services/risk_service.py`
  - Implement VaR/ES/stress/backtesting/P&L explain workflows.

- `services/portfolio_service.py`
  - Store position-level pricing errors and warnings.
  - Delegate pricing to `PricingService`.

- `instruments/fixed_income.py`
  - Replace silent z-spread `np.nan` with structured warning/error in service
    output.

### P2

- `models/implied_vol.py`
- `risk/vol_surface.py`
  - Resolve duplicate `VolSurface` ownership.

- `app/panels/*`
  - Migrate direct model imports to service calls incrementally.

## Regression Risk Summary

Current state is stable for the tested core suite:

```text
58 passed
core import failures: 0
compile failures: 0
```

Main regression risks are architectural, not immediate test failures:

- UI cannot be imported without `PySide6`.
- Risk and pricing services are incomplete.
- UI-to-model coupling remains widespread.
- Several model failures are silently converted to NaN, penalty values, banner
  errors, or zero P&L.
- Existing tests do not cover UI import/runtime, service governance, failed
  pricing paths, or the P0/P1 methodology issues identified in the audits.
