# Quant Governance Sync

**Date:** 2026-06-04
**Scope:** governance synchronization review across [MODEL_REVIEW_AND_RECOMMENDATIONS.md](MODEL_REVIEW_AND_RECOMMENDATIONS.md), [QUANT_STABILIZATION_REVIEW.md](QUANT_STABILIZATION_REVIEW.md), and [models/registry.py](models/registry.py).
**Rule:** no code or registry entries were modified.

---

## 1. Summary

The quant review backlog and the current model registry are partly synchronized:

- Several Critical/High/Medium review items are already fixed or explicitly documented as false positives by regression tests.
- Registry `notes` already mention some fixes, especially Black-Scholes Greeks, Monte Carlo control variates, fixed bond duration, Heston delta, and digital gamma.
- Registry `tests` fields are incomplete for several models even when regression tests exist in [tests/test_critical_fixes.py](tests/test_critical_fixes.py), [tests/test_high_severity_fixes.py](tests/test_high_severity_fixes.py), and [tests/test_medium_severity_fixes.py](tests/test_medium_severity_fixes.py).
- No model should be promoted to `Validated` solely because a bug was fixed. The correct governance posture remains `Approximation` or `Prototype` until benchmark packs and validation evidence exist.

Recommended governance direction:

- Keep production-facing models as `Approximation` unless full benchmark validation exists.
- Keep research models as `Prototype` and analytics-lab-only.
- Add explicit issue status metadata in registry notes or a future model issue register:
  - `Fixed`
  - `False Positive`
  - `Partially Validated`
  - `Open`

---

## 2. Reviewed Model Status Matrix

| Reviewed Model / Area | Registry ID | Current Registry Status | Quant Issue(s) | Sync Status | Governance Recommendation |
|---|---|---:|---|---:|---|
| Black-Scholes / Merton | `black_scholes` | `Approximation` | Expiry put delta, volga scaling, ultima formula; also reference model for theta tests | Fixed | Keep `Approximation`. Add regression test references for expiry delta, volga, ultima, and theta convention. Do not promote to `Validated` until discrete dividends, convention docs, and benchmark set are added. |
| Black-76 | `black76` | `Approximation` | Caplet discounting depends on Black-76 usage convention | Partially Validated | Keep `Approximation`. Add caplet parity/single-discount test evidence where this model is used. Limitation remains no vol surface by tenor/strike. |
| Binomial CRR | `binomial_crr` | `Approximation` | Theta scaling flagged Critical | False Positive | Keep `Approximation`. Update tests list with CRR daily theta tests. Notes should explicitly state theta is per calendar day and protected by regression tests. |
| Binomial Leisen-Reimer | `binomial_lr` | `Approximation` | Lattice family governance; no direct reviewed defect beyond lattice risk | Partially Validated | Keep `Approximation`. Add convergence and Greek unit tests before any production promotion. |
| Trinomial Tree | `trinomial` | `Approximation` | Theta/lattice governance risk; barrier use risk | Partially Validated | Keep `Approximation`. Add theta/Greek tests if Greeks are exposed; keep barrier-related use under caution. |
| Monte Carlo GBM | `mc_gbm` | `Approximation` | Theta scaling flagged; control variate expectation | Fixed / False Positive split | Keep `Approximation`. Notes already mention corrected control variate. Add tests list for `mc_price_has_no_theta_key` and control-variate unbiased tests. |
| Longstaff-Schwartz LSM | `mc_lsm` | `Prototype` | Monte Carlo family governance risk, no requested direct fix | Open | Keep `Prototype`. Require exercise-policy validation and benchmark against CRR/known American option cases. |
| Heston Monte Carlo | `mc_heston` | `Prototype` | Experimental Monte Carlo / stochastic volatility governance | Open | Keep `Prototype` and Analytics Lab only. Add path-discretization limitations and benchmark requirements. |
| Heston characteristic function | `heston_cf` | `Prototype` | Characteristic-function branch stability; dividend delta | False Positive / Fixed split | Keep `Prototype`. Registry notes already mention stable Little Heston Trap and dividend-adjusted delta. Add test evidence for low-vol-vol BSM convergence, extreme-parameter stability, and dividend delta. Do not allow production workflow until benchmark calibration and Feller-policy decisions exist. |
| SABR | `sabr` | `Prototype` | Not in focused issue list, but stochastic-vol research model | Open | Keep `Prototype`. Require ATM limit test, positivity safeguards, calibration validation, and market smile benchmark before production use. |
| GARCH / EWMA | `garch` | `Approximation` | Log-likelihood missing constant; input guards | Open | Consider downgrading production eligibility if exposed in production. Keep `Approximation` only for analytics; add likelihood constant, NaN/inf validation, and AIC/BIC tests before governance improvement. |
| Fixed-Rate Bond | `fixed_bond` | `Approximation` | Modified duration from YTM; broader fixed-income limitations | Fixed / Partially Validated split | Keep `Approximation`. Notes already mention YTM duration. Add tests list for modified duration and benchmark bond examples. Do not promote until holiday calendars, stubs, ex-coupon, amortization, callable/putable, and external benchmark validation are complete. |
| Floating Rate Note | `frn` | `Prototype` | FI audit backlog; no reset/projection logic | Open | Keep `Prototype`. Block production workflow until reset dates, projection curve, fixing lag, and spread conventions are implemented. |
| Interest Rate Swap | `irs` | `Approximation` | Single-curve methodology and schedule conventions | Partially Validated | Keep `Approximation`. Add warning that production rates workflow requires dual-curve/OIS discounting, schedules, fixing lag, and day-count conventions. |
| Cap / Floor / Swaption | `capfloor` | `Approximation` | Caplet double discounting | Fixed / Partially Validated split | Keep `Approximation`. Add tests list for caplet single discounting, cap/floor parity, and zero-vol/intrinsic cases. Limitation remains no tenor/strike vol surface and incomplete production conventions. |
| Short Rate Models | `short_rate` | `Prototype` | Hull-White calibration consistency; Vasicek kappa=0 sign recommendation | Fixed / False Positive split | Keep `Prototype`. Update notes: Hull-White curve reconstitution covered by tests; Vasicek sign change rejected by tests. Require calibration, simulation, and benchmark packs before production use. |
| FX Forward | `fx_forward` | `Approximation` | Not directly reviewed in quant issue list | Partially Validated | Keep `Approximation`. Add settlement calendar, bid/ask, and curve-source limitations before production promotion. |
| Garman-Kohlhagen | `garman_kohlhagen` | `Approximation` | Related to FX/dividend-style delta conventions, no direct issue | Partially Validated | Keep `Approximation`. Add FX smile, rates source, premium currency, and settlement convention limitations. |
| FX Vol Smile | `fx_smile` | `Placeholder` | Placeholder market model | Open | Keep `Placeholder`. Must stay blocked until ATM/RR/BF source model is implemented. |
| Asian Options | `asian` | `Prototype` | Discrete geometric Asian formula flagged High | False Positive | Keep `Prototype`. Add MC comparison test evidence. Notes should state discrete geometric formula is regression-checked, while arithmetic Asian remains approximation/MC. |
| Digital / Cash-or-Nothing | `digital` | `Approximation` | Digital put gamma sign | Fixed | Keep `Approximation`. Add tests list for put gamma finite-difference and call/put gamma sign relationship. Touch products remain limited. |
| Barrier Options | `barrier` | `Prototype` | Incomplete Reiner-Rubinstein table; double-barrier series incomplete | Open | Keep `Prototype`. Consider marking as Analytics Lab only or adding stronger warning until full barrier formula table and MC benchmarks exist. |
| Lookback Options | `lookback` | `Prototype` | Not in focused issue list but unvalidated exotic | Open | Keep `Prototype`. Require MC benchmark and convention documentation. |
| Multi-Asset / Rainbow | `multi_asset` | `Prototype` | Correlation/MC robustness risk | Open | Keep `Prototype`. Add nearest-PD handling, correlation validation, and benchmark tests. |
| Variance Swap | `variance_swap` | `Approximation` | Replication kernel had extra log multiplier | Fixed / Partially Validated split | Keep `Approximation`. Add tests list for flat-vol fair variance recovery. Add note that replication kernel fixed, but discrete monitoring adjustment and market convention validation remain open. |
| CDS | `cds` | `Approximation` | Pseudo-bootstrap survival curve | Open | Keep `Approximation` only with explicit flat-hazard limitation. Do not promote until term-structure bootstrap and CDS benchmark calibration exist. |
| CVA / DVA | `cva_dva` | `Prototype` | Exposure simulation / wrong-way risk missing | Open | Keep `Prototype`. Block production use until exposure simulation, collateral/netting, wrong-way risk, and benchmark validation exist. |
| Structured Autocall / Phoenix | `structured_autocall` | `Prototype` | Path MC and schedule convention gaps | Open | Keep `Prototype`. Require observation schedule, barrier convention, coupon memory, and MC validation. |
| CLN / FTD | `cln_ftd` | `Prototype` | Copula calibration missing | Open | Keep `Prototype`. Require market tranche calibration and credit model validation. |
| Parametric VaR | `var_parametric` | `Approximation` | VaR convention consolidation and horizon scaling | Partially Validated | Keep `Approximation`. Add explicit tests for confidence, ES >= VaR, horizon scaling, and NaN/empty inputs. Parametric sqrt(h) is acceptable but must be documented as assumption-based. |
| Historical VaR | `var_historical` | `Approximation` | Historical VaR sqrt(h) misuse; weighted branch; ES consistency | Fixed / Partially Validated split | Keep `Approximation`. Registry should add multi-day window tests, weighted historical tests, invalid confidence tests, NaN/empty input tests. Note fallback-to-sqrt policy for small samples. |
| Monte Carlo VaR | `var_mc` | `Approximation` | VaR convention consolidation; full repricing missing | Partially Validated | Keep `Approximation`. Add tests for sign convention, ES >= VaR, horizon scaling, and seed stability. Do not imply full repricing VaR. |
| EVT VaR | `evt_var` | `Approximation` | Tail methodology not focus of sprint; sufficient-tail risk | Partially Validated | Keep `Approximation`. Require tail sample diagnostics, parameter stability tests, and warning thresholds. |
| Portfolio Aggregation | `portfolio_aggregation` | `Prototype` | Registry note says mixed Greeks, but architecture now has risk-factor exposure | Partially Validated | Update registry notes: raw Greek aggregation has been replaced by risk-factor exposure architecture in `PortfolioService`, but benchmark and portfolio-level validation remain incomplete. Consider status `Approximation` only after tests and limitations are updated. |
| Implied Vol / SVI | No dedicated registry entry | N/A | SVI no-arbitrage constraint too strict | Open | Add registry entry if SVI is exposed. Keep `Prototype` or `Approximation` with explicit no-arbitrage limitation until constraint tests exist. |
| YieldCurve duration utility | No dedicated registry entry | N/A | Modified duration uses zero rate in utility method | Open | Governance owner should be Market Data / Rates Analytics. Add registry or market-data validation note if this utility is user-facing. |

---

## 3. Governance Recommendation by Sync Status

### Fixed

Fixed means the reviewed defect has a code-level correction and regression evidence.

Models/issues:

- `variance_swap`: replication weight fixed.
- `black_scholes`: expiry put delta, volga scaling, ultima fixed.
- `mc_gbm`: control-variate expectation fixed; theta item not applicable to current `mc_price`.
- `heston_cf`: dividend-adjusted delta fixed.
- `fixed_bond`: modified duration uses YTM.
- `digital`: cash digital put gamma sign fixed.
- `capfloor`: caplet discounting fixed at engine level.
- `var_historical`: multi-day historical VaR methodology fixed at engine level.
- `short_rate`: Hull-White curve reconstitution fixed at engine level.

Governance action:

- Do not automatically promote to `Validated`.
- Add exact regression test names to registry `tests`.
- Add validation-date and validation-pack references when GovernanceService supports richer metadata.
- Keep limitations visible in service result warnings.

### False Positive

False Positive means the original review recommendation is contradicted by current regression tests or current implementation behavior.

Models/issues:

- `binomial_crr`: theta is already per calendar day; proposed rescaling would be harmful.
- `mc_gbm`: Monte Carlo `mc_price` does not expose theta.
- `heston_cf`: current characteristic function is tested as stable Little Heston Trap behavior.
- `asian`: discrete geometric Asian formula is tested against Monte Carlo and treated as already correct.
- `short_rate`: Vasicek `kappa=0` sign change recommendation is rejected by tests.

Governance action:

- Document these as false positives in model notes or a model issue register.
- Keep regression tests as guardrails against future incorrect "fixes".
- Do not lower status solely because the issue appeared in the original model review.

### Partially Validated

Partially Validated means the immediate defect is fixed or bounded, but production validation is incomplete.

Models/issues:

- `fixed_bond`: bond conventions improved, but holiday calendars, stubs, ex-coupon, amortization, callable/putable, and benchmark validation remain open.
- `irs`: still single-curve and convention-limited.
- `capfloor`: caplet issue fixed, but vol surface and production conventions remain incomplete.
- `variance_swap`: replication fixed, but discrete monitoring and market convention validation remain open.
- `var_historical`, `var_parametric`, `var_mc`, `evt_var`: conventions improved, but validation depth and source data quality remain limited.
- `portfolio_aggregation`: architecture moved to risk-factor exposures, but registry is stale and portfolio benchmark validation is incomplete.
- `black76`, `garman_kohlhagen`, `fx_forward`: usable approximations but not fully validated production models.

Governance action:

- Keep `Approximation` where production workflow needs continuity.
- Attach stronger limitations and warnings.
- Require benchmark packs before promotion.
- Make production eligibility separate from status.

### Open

Open means no sufficient evidence of fix or production validation exists in the reviewed files.

Models/issues:

- `barrier`: incomplete single and double barrier formulas.
- `cds`: survival curve bootstrap remains simplified.
- `garch`: likelihood constant and input validation remain open.
- `frn`: reset/projection logic missing.
- `mc_lsm`, `mc_heston`, `sabr`, `lookback`, `multi_asset`, `cva_dva`, `structured_autocall`, `cln_ftd`: remain prototype/research or unvalidated.
- `fx_smile`: remains placeholder.
- SVI/implied-vol and YieldCurve duration utility need registry ownership if user-facing.

Governance action:

- Keep `Prototype` or `Placeholder` as applicable.
- Ensure services block `Placeholder` and `Broken`; prototypes should warn and stay out of production workflows unless explicitly allowed.
- Add issue register entries before exposing these in production-oriented workspaces.

---

## 4. Registry Synchronization Gaps

The following are recommended registry metadata updates, not code changes made by this document.

| Registry ID | Gap | Recommended Update |
|---|---|---|
| `binomial_crr` | Tests list does not mention theta regression evidence. | Add CRR theta daily-scale tests and note false-positive review outcome. |
| `mc_gbm` | Notes mention control-variate fix, but tests list only `mc_european_vs_bsm`. | Add control-variate unbiased tests and `mc_price` no-theta guard. |
| `heston_cf` | Notes mention stable form and dividend delta but tests list is empty. | Add Heston stability, BSM convergence, and dividend delta tests. Keep `Prototype`. |
| `short_rate` | Notes still say calibration not validated, but Hull-White reconstitution tests exist. | Update notes to distinguish Hull-White curve reconstitution regression from broader calibration validation. Keep `Prototype`. |
| `capfloor` | Tests list empty despite caplet discounting tests. | Add single-discount, parity, and zero-vol caplet tests. Keep approximation warning. |
| `asian` | Notes say no geometric exact formula comparison, but tests compare discrete geometric formula to MC. | Update notes to state discrete geometric formula is regression-checked; arithmetic Asian remains approximate. |
| `digital` | Notes mention gamma fix but tests list empty. | Add finite-difference and call/put gamma sign tests. |
| `variance_swap` | Notes do not explicitly mention the replication bug fix; tests list empty. | Add flat-vol replication tests and note discrete monitoring remains open. |
| `fixed_bond` | Notes mention YTM duration, but tests list omits modified-duration regression names. | Add modified duration tests and external benchmark requirement. |
| `var_historical` | Notes understate methodology improvements and fallback policy. | Add multi-day window, weighted historical, ES, invalid input tests; document small-sample fallback. |
| `portfolio_aggregation` | Notes are stale and still describe mixed Greek aggregation as current fact. | Update notes to reflect `RiskFactorExposure` architecture while retaining validation gaps. |
| `garch` | Open likelihood issue not visible. | Add limitation about AIC/BIC likelihood constant and input validation until fixed. |
| `cds` | Current flat-hazard limitation is correct but should map to the review issue. | Add explicit "not a term-structure bootstrap" warning. |
| `barrier` | Notes are too mild for known formula incompleteness. | Add incomplete Reiner-Rubinstein/double-barrier limitation. |
| `fx_smile` | Placeholder status is correct. | Keep blocked until proper ATM/RR/BF inputs exist. |

---

## 5. Production Eligibility Recommendations

Keep production allowed with explicit approximation warnings:

- `fixed_bond`
- `irs`
- `fx_forward`
- `garman_kohlhagen`
- `var_historical`
- `var_parametric`
- `var_mc`
- `evt_var`

Do not promote beyond `Approximation` yet:

- `black_scholes`
- `black76`
- `binomial_crr`
- `mc_gbm`
- `capfloor`
- `digital`
- `variance_swap`
- `cds`
- `garch`

Keep research/prototype-only:

- `heston_cf`
- `mc_lsm`
- `mc_heston`
- `sabr`
- `short_rate`
- `barrier`
- `asian`
- `lookback`
- `multi_asset`
- `cva_dva`
- `structured_autocall`
- `cln_ftd`

Keep blocked:

- `fx_smile` as `Placeholder`.

Needs governance ownership if user-facing:

- SVI / implied-vol surface logic.
- YieldCurve duration utility.

---

## 6. Recommended Governance Metadata Model

Future registry entries should support explicit issue synchronization fields:

```python
{
    "model_id": "variance_swap",
    "status": ModelStatus.APPROXIMATION,
    "quant_review_status": "Fixed",
    "validation_evidence": [
        "tests/test_critical_fixes.py::test_variance_swap_flat_vol_recovers_sigma_squared",
        "tests/test_critical_fixes.py::test_variance_swap_no_systematic_overestimate_under_refinement",
    ],
    "limitations": [
        "No discrete monitoring adjustment",
        "No market convention validation pack",
    ],
    "production_allowed": True,
}
```

Minimum recommended fields:

- `quant_review_status`: `Fixed`, `False Positive`, `Partially Validated`, or `Open`.
- `validation_evidence`: test names, benchmark pack references, or external validation references.
- `limitations`: user-facing limitations surfaced by services.
- `production_allowed`: separate from status.
- `analytics_lab_only`: explicit for research models.
- `last_reviewed`: date of governance review.

---

## 7. Next Governance Actions

1. Update registry `tests` fields for models already covered by regression tests.
2. Update stale registry notes, especially `portfolio_aggregation`, `asian`, `short_rate`, `variance_swap`, and `var_historical`.
3. Add explicit false-positive documentation for theta, Heston CF, discrete Asian, and Vasicek sign findings.
4. Add a model issue register or extend registry entries with `quant_review_status`.
5. Keep Market Data Workspace work restricted to provenance and validation until governance metadata is synced.
6. Move Governance Workspace earlier than the full Pricing Workspace productization pass so users can see model limitations before using prototype calculators.

