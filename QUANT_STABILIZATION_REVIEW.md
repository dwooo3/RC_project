# Quant Stabilization Review

**Date:** 2026-06-04
**Scope:** review-only assessment before continuing the Product Roadmap to Market Data Workspace.
**Inputs:** [MODEL_REVIEW_AND_RECOMMENDATIONS.md](MODEL_REVIEW_AND_RECOMMENDATIONS.md), [CURRENT_ISSUES_AND_REMEDIATION.md](CURRENT_ISSUES_AND_REMEDIATION.md), current repository state.
**Rule:** no production code changes were made for this review.

---

# 1. Executive Summary

The Quant Stabilization Sprint is primarily a **pricing and risk methodology stabilization** stage, not a UI redesign stage.

The original model review identified 22 quantitative issues. The current repository state shows that several of the critical/high/medium items have already been handled or explicitly classified as false positives by regression tests:

- Critical fixes:
  - Variance swap replication was a genuine pricing defect and is fixed in [instruments/variance_swaps.py](instruments/variance_swaps.py).
  - Tree theta scaling is documented by tests as already daily-scaled; applying the proposed review fix would be harmful. See [tests/test_critical_fixes.py](tests/test_critical_fixes.py).
  - Monte Carlo pricing currently does not return theta, so the Monte Carlo theta item does not apply to current `mc_price`.
- High fixes:
  - Caplet discounting, Hull-White curve fit, and Historical VaR horizon methodology are covered by [tests/test_high_severity_fixes.py](tests/test_high_severity_fixes.py).
  - Heston characteristic function and discrete geometric Asian formula are treated as false positives by regression tests.
- Medium fixes:
  - Black-Scholes expiry delta, volga scaling, ultima, Heston dividend delta, Monte Carlo control variate expectation, fixed-income modified duration, and digital put gamma are covered by [tests/test_medium_severity_fixes.py](tests/test_medium_severity_fixes.py).
  - Vasicek `kappa=0` sign recommendation is treated as a false positive by regression tests.

Pricing impact:

- Direct pricing impact remains highest in the legacy/prototype pricing modules: variance swaps, cap/floor, exotic Asian, digital/touch, Heston, short-rate models, Monte Carlo, and fixed income analytics.
- Core service-backed pricing is safer than legacy direct panel use because [services/pricing_service.py](services/pricing_service.py) attaches governance metadata, model status, warnings, and market data snapshot metadata.

Risk impact:

- Historical VaR methodology directly affects [risk/var.py](risk/var.py), [services/risk_service.py](services/risk_service.py), and [app/panels/risk_workspace.py](app/panels/risk_workspace.py).
- The Risk Workspace uses `RiskService`, which is the correct architecture boundary.
- Remaining risk is model validation depth, not UI wiring.

Governance impact:

- Governance remains essential. Many affected models are still marked `Approximation` or `Prototype` in [models/registry.py](models/registry.py).
- The stabilization work should not automatically promote models to production status. It should update limitations, validation evidence, and allowed workflow layers.

UI impact:

- UI is affected only indirectly. The UI should display service warnings, model status, snapshot source, and calculation timestamps.
- UI must not compensate for quantitative defects and must not bypass services to call pricing/risk engines directly.

---

# 2. Dependency Analysis

| Issue | Severity From Review | Current Read | Impacted Models | Impacted Services | Impacted Workspaces |
|---|---:|---|---|---|---|
| Theta scaling | Critical | Tree theta is guarded as daily-scaled; Monte Carlo price has no theta output. Treat as **resolved/false-positive split**. | [models/trees.py](models/trees.py), [models/monte_carlo.py](models/monte_carlo.py), [models/black_scholes.py](models/black_scholes.py) as reference | [services/pricing_service.py](services/pricing_service.py) if tree/MC model selected; [services/portfolio_service.py](services/portfolio_service.py) for theta P&L | Pricing Workspace, Portfolio Workspace, legacy Binomial/Monte Carlo panels |
| Variance Swap replication | Critical | Genuine pricing issue fixed; regression tests cover flat-vol replication. | [instruments/variance_swaps.py](instruments/variance_swaps.py) | No canonical service wrapper yet; future `PricingService` route required | Pricing Workspace via legacy Variance Swap panel |
| Heston characteristic function | High | Regression tests classify current implementation as stable Little Heston Trap behavior; keep as research/prototype. | [models/heston.py](models/heston.py) | `PricingService` only if Heston is explicitly exposed later; governance currently important | Analytics Lab, future Pricing Workspace Heston module |
| Hull-White calibration consistency | High | Current tests require initial curve reconstitution. | [models/short_rate.py](models/short_rate.py), [curves/yield_curve.py](curves/yield_curve.py) | Future `PricingService` rates wrappers; current direct panels may still exist | Pricing Workspace rates modules, Analytics Lab |
| Historical VaR methodology | High | Current engine uses actual multi-day windows when enough data exists, with backward-compatible fallback. | [risk/var.py](risk/var.py), [risk/historical_var.py](risk/historical_var.py) | [services/risk_service.py](services/risk_service.py) | Risk Workspace VaR and Backtesting |
| Caplet discounting | High | Current tests cover single discounting and parity. | [instruments/fixed_income.py](instruments/fixed_income.py), [models/black_scholes.py](models/black_scholes.py) Black-76 | Future `PricingService` cap/floor wrapper needed; current cap/floor panels may bypass service | Pricing Workspace Rates & Credit |
| Discrete Asian formula | High | Regression tests classify current formula as already correct against Monte Carlo. | [instruments/asian.py](instruments/asian.py), [models/monte_carlo.py](models/monte_carlo.py) | Future `PricingService` exotic wrapper if promoted | Pricing Workspace Structured & Exotic, legacy Asian panel |
| Black-Scholes Greeks corrections | Medium | Current tests cover expiry put delta, volga, and ultima. | [models/black_scholes.py](models/black_scholes.py) | [services/pricing_service.py](services/pricing_service.py), [services/portfolio_service.py](services/portfolio_service.py), [services/risk_service.py](services/risk_service.py) for stress | Pricing Workspace, Portfolio Workspace, Risk Workspace stress |
| Heston dividend delta | Medium | Current tests cover dividend-adjusted delta. | [models/heston.py](models/heston.py) | Governance and future `PricingService` Heston exposure | Analytics Lab, future Pricing Workspace Heston |
| Monte Carlo control variates | Medium | Current tests cover discounted terminal spot expectation. | [models/monte_carlo.py](models/monte_carlo.py) | [services/pricing_service.py](services/pricing_service.py) when `mc_gbm` is selected | Pricing Workspace, Analytics Lab |
| Fixed income duration methodology | Medium | Current tests cover modified duration from YTM in bond engine. Yield-curve utility duration remains lower-priority audit surface. | [instruments/fixed_income.py](instruments/fixed_income.py), [curves/yield_curve.py](curves/yield_curve.py) | [services/pricing_service.py](services/pricing_service.py), [services/portfolio_service.py](services/portfolio_service.py) | Portfolio Workspace valuation/exposures, Pricing Workspace bond |
| Digital option gamma | Medium | Current tests cover cash digital put gamma sign. | [instruments/digital.py](instruments/digital.py) | Future `PricingService` digital wrapper if promoted | Pricing Workspace Structured & Exotic, legacy Digital panel |

Additional model-review backlog not part of the requested focus but still relevant:

- Barrier option formula coverage remains a medium/high productization risk for exotic pricing.
- Credit survival curve bootstrap remains a methodology risk for credit pricing.
- SVI, GARCH likelihood, and yield-curve utility duration remain lower-severity analytics issues.

---

# 3. Product Impact Analysis

| Issue | Product Classification | Production Risk | Model Risk | Reporting Risk | User Impact |
|---|---:|---|---|---|---|
| Theta scaling | Medium after current tests; Critical in original review | Low for current tree/MC implementation if tests remain green; high if future refactor changes theta units | Unit convention risk for PnL Explain and Greeks | Theta P&L can be materially wrong if annual/daily units drift | Trader sees wrong carry/theta P&L |
| Variance Swap replication | Low after fix; Critical before fix | Low if regression test remains enforced | Model-free replication kernel is now correct for flat-vol test case; still needs market strike convention validation | Variance strike reports can be wrong if future wrapper bypasses tested engine | Trader/quant sees wrong fair variance/vol strike |
| Heston characteristic function | Medium; High in original review | Low for production because Heston is research/prototype; high if promoted silently | Numerical stability risk in extreme parameter regimes | Exotic/stochastic-vol reports can show unstable prices | Quant Analyst affected most |
| Hull-White calibration | Medium after tests; High before fix | Medium until rates products are service-routed and benchmarked | Curve reconstitution is essential for no-arbitrage rates pricing | Rates valuation can mismatch market curve | Trader/Risk Manager sees rates P&L noise |
| Historical VaR methodology | Medium after tests; High before fix | Medium because demo/synthetic returns still dominate UI examples | Multi-day VaR methodology is now directionally correct; backtesting depth remains limited | VaR/ES reports sensitive to sample size and fallback policy | Market Risk Manager affected directly |
| Caplet discounting | Medium after tests; High before fix | Medium because cap/floor panel is still prototype-oriented | Black-76 caplet convention requires service wrapper and vol surface ownership | Cap/floor valuation reports can be misleading if direct panel bypasses governance | Rates trader affected |
| Discrete Asian formula | Medium/Low after tests; High in original review | Low while kept prototype/research | Closed-form validated against MC in tests; production requires conventions and path averaging clarity | Exotic valuation report limitations must stay visible | Quant Analyst affected |
| Black-Scholes Greeks | Low after fixes | Low for core vanilla options; still depends on convention consistency | Higher-order Greeks require documented units | PnL Explain can misattribute vega/volga if units drift | Trader and Risk Manager affected |
| Heston dividend delta | Medium | Low in production if Heston remains research-only | Dividend/foreign-rate delta risk for equity/FX options if promoted | Hedge reports can overstate delta | Quant Analyst/trader affected |
| Monte Carlo control variates | Low after tests | Low for current GBM MC path; model remains approximation | Bias risk reduced; convergence/reporting still requires error bars | Pricing confidence intervals need display if used | Quant Analyst affected |
| Fixed income duration | Medium | Medium because bond valuation feeds Portfolio Workspace | Duration/DV01 require benchmark validation beyond unit tests | Portfolio rates exposure can be wrong if duration convention drifts | Market Risk Manager and rates trader affected |
| Digital option gamma | Low after tests | Medium if digital panel becomes production workflow without service wrapper | Gamma signs matter for local hedging and scenario P&L | Greeks/exposure reports can flip sign | Trader affected |

---

# 4. Architecture Impact

Domain layer:

- Formula fixes mostly do not require new domain objects.
- The main domain impact is conventions metadata: theta unit, Greek units, horizon methodology, curve convention, day count, and model limitations should be visible in result/domain objects where applicable.
- `PortfolioService` already consumes position-level theta and risk-factor exposure. Therefore any theta or Greek unit change must be treated as a contract change and tested against portfolio aggregation.

Service layer:

- `RiskService` is the correct mandatory boundary for Historical, Parametric, and Monte Carlo VaR. The Risk Workspace already consumes this service.
- `PricingService` is the correct boundary for vanilla, bond, IRS, FX, and future rates/exotic wrappers.
- The remaining architecture risk is legacy panel paths that instantiate `instruments.*`, `models.*`, or `risk.*` directly for prototype workflows. Those paths preserve functionality but must remain marked as prototype/research until migrated.

Governance layer:

- Governance must remain mandatory for all service calculations.
- Quant fixes should update `ModelRegistryEntry` limitations and validation evidence, but should not automatically mark models `Validated`.
- Heston, short-rate research models, exotic options, and variance products should remain `Prototype` or `Approximation` until benchmark packs exist.
- Broken or placeholder models must stay blocked. Prototype models must remain warning-generating.

UI layer:

- No UI formula work is required.
- UI must continue to surface `model_id`, `model_status`, warnings, errors, market data source, snapshot id, and calculation timestamp.
- Pricing Workspace currently acts as a grouped launcher and can still open legacy calculators. This is acceptable for preservation, but it is not sufficient for production-grade pricing workflows until each module is service-routed.

Architectural conflicts to watch:

- Market Data Workspace must not create a second market data implementation or construct curves outside `MarketDataService`.
- Pricing Workspace must not promote prototype models by presentation alone.
- Analytics Lab must stay separated from production workflows.
- Future fixes must not bypass the model registry to call engines directly.

---

# 5. Readiness Assessment

**Recommendation: B. Continue with restrictions.**

Market Data Workspace can begin before every quant issue is fully production-validated because it is an upstream platform/workflow layer. It should focus on snapshot browsing, source ownership, curve/FX/vol/credit data visibility, validation status, and provenance. Those capabilities support quant stabilization rather than conflict with it.

Restrictions:

1. Do not add new pricing/risk calculations inside Market Data Workspace.
2. Do not let the UI construct yield curves, FX data, vol surfaces, or credit curves directly.
3. Route all market data reads through `MarketDataService`.
4. Display source, snapshot id, timestamp, quality, and validation errors prominently.
5. Keep affected models marked `Approximation` or `Prototype` until benchmark validation exists.
6. Do not begin a production-grade Pricing Workspace pass until service wrappers and governance metadata exist for affected pricing models.
7. Do not use Market Data Workspace completion as evidence that pricing/risk engines are production-ready.

Rationale:

- Critical pricing defects have either been fixed or classified as false positives by regression tests.
- The remaining major risk is governance/productization of prototype workflows, not the market data platform itself.
- Market Data Workspace is needed to improve reproducibility and auditability of future quant validation.

---

# 6. Roadmap Adjustment

Current roadmap:

1. Risk Workspace v1
2. Quant Stabilization Sprint
3. Market Data Workspace
4. Pricing Workspace
5. Governance Workspace
6. Analytics Lab Workspace
7. Bloomberg/Calypso UI Pass

Recommended adjustment:

1. Risk Workspace v1 — done.
2. Quant Stabilization Gate 1 — confirm critical/high regression suite and document false positives.
3. Market Data Workspace — proceed with restrictions listed above.
4. Governance Workspace — move before Pricing Workspace if possible, because model issue visibility and validation evidence are now central to product trust.
5. Quant Stabilization Gate 2 — benchmark packs for remaining pricing/risk models before production-grade pricing UX.
6. Pricing Workspace — service-routed, governed, no direct engine calls for production workflows.
7. Analytics Lab Workspace — explicitly research-only, with opt-in governance bypass where allowed.
8. Bloomberg/Calypso UI Pass — only after service, market data, and governance workflows are stable.

This is not a full reorder away from Market Data Workspace. It inserts two gates and moves Governance Workspace earlier in the sequence.

---

# 7. Implementation Guidance

Market Data Workspace:

- Implement as a pure `MarketDataService` consumer.
- Show active snapshot id, version, timestamp, source, quality, warnings, and validation status.
- Provide separate views for yield curves, FX, vol surfaces, and credit curves.
- Treat DEMO/MANUAL/CSV sources as visible provenance, not hidden defaults.
- Do not add pricing previews unless they call services and expose governance metadata.

Pricing Workspace:

- Do not productize legacy exotic panels as production workflows.
- Prioritize service wrappers for variance swaps, cap/floor, digital options, and Asian options before making them first-class workstation modules.
- Every pricing result must show model id, model status, limitations, warnings, market data snapshot id, and source.
- Add benchmark packs before raising model status above `Approximation`.
- Keep Heston, short-rate research models, barrier options, and structured products under prototype/research governance until validation expands.

Governance Workspace:

- Add a model issue register that links each model to:
  - status,
  - owner,
  - validation date,
  - limitations,
  - affected services,
  - affected workspaces,
  - regression test evidence.
- Distinguish "fixed by code", "false positive", "partially validated", and "still open".
- Expose production eligibility separately from implementation status.
- Make prototype and broken-model warnings visible before users enter Pricing or Risk workflows.

Immediate next tasks:

1. Run and record the current full regression suite after this review.
2. Update governance metadata to reflect fixed/false-positive/remaining quant issues.
3. Implement Market Data Workspace as a service-only provenance and validation surface.
4. Add service wrappers for remaining prototype pricing modules before deeper Pricing Workspace work.
5. Create benchmark validation packs for fixed income, VaR, vanilla/exotic options, and rates models.

