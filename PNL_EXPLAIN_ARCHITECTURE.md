# PnL Explain Architecture

Date: 2026-06-04

## Purpose

PnL Explain is the attribution framework that decomposes portfolio P&L into
risk-factor components and reports residual unexplained P&L. It sits on top of
the Portfolio and Scenario foundations rather than using UI-level calculator
logic.

## Architectural Ownership

Primary owner:

- `services/portfolio_service.py`

Domain contract:

- `domain/results.py` -> `PnLExplainResult`

Supporting domains:

- `domain/risk_factors.py`
- `domain/scenario.py`
- `domain/portfolio.py`

The UI must consume `PortfolioService.explain_pnl()` when migrated. It should not
recalculate attribution components directly.

## Result Contract

`PnLExplainResult` contains:

- `total_pnl`
- `explained_pnl`
- `residual`
- `delta_pnl`
- `gamma_pnl`
- `vega_pnl`
- `theta_pnl`
- `rate_pnl`
- `fx_pnl`
- `components`
- `factor_pnl`
- `position_pnl`
- `warnings`
- `errors`

Reconciliation rule:

```text
total_pnl = explained_pnl + residual
```

The `reconciles` property verifies this identity within numeric tolerance.

## Component Mapping

| Component | Source |
| --- | --- |
| Delta PnL | Equity `Delta` exposures |
| Gamma PnL | Equity `Gamma` exposures |
| Vega PnL | Volatility `Vega` exposures |
| Theta PnL | Position `theta` multiplied by `theta_days` |
| Rate PnL | Rates `DV01` and `Rho` exposures |
| FX PnL | FX `FX Delta` exposures |
| Residual | Reported total P&L minus explained P&L |

## Service API

Primary API:

```python
PortfolioService.explain_pnl(
    total_pnl=None,
    dS=0,
    dVol=0,
    dr=0,
    dSpread=0,
    theta_days=0,
    scenario=None,
)
```

Two modes are supported:

1. Shock-vector mode using `dS`, `dVol`, `dr`, `dSpread`, and `theta_days`.
2. Scenario mode using `Scenario` / `ScenarioShock`.

When `total_pnl` is omitted, total P&L is the model-explained scenario P&L. When
`total_pnl` is supplied, residual captures unexplained realised P&L.

## Current Limitations

- Attribution is first-order plus listed second-order gamma; it is not full
  revaluation P&L explain.
- Rate steepener/flattener explain still uses aggregate rate exposures until
  tenor-level bucketed DV01 exists.
- Cross-Greeks such as vanna and volga are not included.
- Credit P&L is available in scenario P&L but is not yet a named required
  `PnLExplainResult` component.
- Multi-currency conversion is not implemented.
- Residual is reported, not allocated.

## Migration Notes

Existing `PortfolioService.scenario_pnl()` remains for backward compatibility.
New code should call `PortfolioService.explain_pnl()` for attribution workflows.

Recommended next steps:

1. Add tenor-level rate exposures.
2. Add credit P&L as a named explain component if required by workflow.
3. Add full-revaluation explain mode using market-data snapshots.
4. Migrate `app/panels/pnl_panel.py` to `PortfolioService.explain_pnl()`.
5. Persist explain inputs, market-data snapshot ID, and model metadata for audit.

## Rollback Plan

The change is additive. Rollback is limited to:

- removing `PnLExplainResult` from `domain/results.py`;
- removing `PortfolioService.explain_pnl()`;
- removing tests that depend on the new result contract;
- keeping existing `scenario_pnl()` untouched for compatibility.
