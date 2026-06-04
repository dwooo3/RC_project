# Analytics Lab Architecture

Date: 2026-06-04

Purpose:

Separate production workflows from research workflows without moving UI screens or
rewriting quantitative engines.

## Production Ownership

Production workflows are the governed service paths used by pricing, risk, and
portfolio workflows:

- Bond pricing through `PricingService.price_bond`.
- IRS pricing through `PricingService.price_irs`.
- FX forward/options through `PricingService`.
- VaR through `RiskService`.
- Stress through `RiskService`.

Production models must:

- be reachable through `PricingService` or `RiskService`;
- expose `model_id`, `model_status`, `model_version`, owner, limitations, and
  production flags in result metadata;
- attach market-data snapshot metadata where applicable;
- never use prototype/research models silently.

## Research Ownership

Analytics Lab owns research and experimental models:

- Heston characteristic-function and Heston Monte Carlo models.
- SABR models.
- GARCH/EWMA volatility forecasting.
- Experimental Monte Carlo engines such as LSM and Heston MC.
- Research notebooks and model comparison workflows when added.

Research models may remain callable inside Analytics Lab panels and tests, but
their registry metadata must identify them as Research / Analytics Lab models.
They must not be production allowed unless explicitly promoted through model
governance.

## Governance Boundary

The boundary is enforced through `models/registry.py` and
`services/governance_service.py`.

Registry ownership flags:

- `workflow_layer = "Production"` for production workflow models.
- `workflow_layer = "Research"` for Analytics Lab models.
- `analytics_lab_only = True` for research-only models.
- `production_allowed = False` for Analytics Lab models unless explicitly
  promoted.

Service result flags:

- `model_workflow_layer`
- `model_analytics_lab_only`
- `model_production_allowed`
- `model_metadata`

If a research model is requested through a service path, the result must include
warnings that the model belongs to Analytics Lab and is not production allowed.

## Current Boundary

Production set:

- `fixed_bond`
- `irs`
- `fx_forward`
- `garman_kohlhagen`
- `var_historical`
- `var_parametric`
- `var_mc`
- `evt_var`

Research set:

- `mc_gbm`
- `mc_lsm`
- `mc_heston`
- `heston_cf`
- `sabr`
- `garch`
- `short_rate`

## Promotion Rule

A research model can move into production only after:

- validation tests are added;
- limitations are documented;
- owner and version are assigned;
- `production_allowed` is explicitly set;
- `analytics_lab_only` is removed or set to `False`;
- production service tests prove warnings and metadata behavior.

