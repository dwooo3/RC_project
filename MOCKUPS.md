# RiskCalc — UI Mockups (target UX for Swift beta)

Low-fi wireframes of the target workstation. Dark institutional theme
(DESIGN_SYSTEM.md tokens). Each screen maps 1:1 to existing services so the Swift
client just renders the governed JSON from the API.

Legend: `[ ]` input · `[v]` dropdown · `▸` nav · `■` chip/badge · `│ │` panel.

---

## 0. Global shell

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ RiskCalc                          ■ MOEX  ■ EOD 2026-06-02   ⌘K  ◐ theme   ⚙   │ topbar
├────────────┬─────────────────────────────────────────────────────────────────┤
│ Dashboard  │                                                                   │
│ Market     │                                                                   │
│ Pricing  ▸ │                  ( active workspace renders here )                │
│ Portfolio  │                                                                   │
│ Risk       │                                                                   │
│ Governance │                                                                   │
│ Analytics  │                                                                   │
│ Settings   │                                                                   │
└────────────┴─────────────────────────────────────────────────────────────────┘
 sidebar 200px                       workspace
```

---

## 1. Pricing workstation  (focus)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Pricing                                                          ■ DEMO        │
│ Value any instrument · view sensitivities · add to portfolio                   │
├──────────────────────────────────────────────────────────────────────────────┤
│ [ Fixed Income ][ Option ][ Equity ][ FX ][ Swaps ][ Structured ][ Credit ]   │ category tabs
├──────────────────────────────────────────────────────────────────────────────┤
│ Instrument [ Bond / OFZ                       v ]                              │ product dropdown
│                                                                                │
│ ┌─ Inputs ───────────────┐   ┌─ Result ─────────────────────────────────────┐ │
│ │ Face          [ 1000  ] │   │  PRICE                                       │ │
│ │ Coupon        [ 0.07  ] │   │  799.39        ■ Approximation  ■ MOEX/OK    │ │
│ │ Maturity (y)  [ 10    ] │   │  model fixed_bond v0.1 · snap moex-2026-06-02│ │
│ │ Freq/y        [ 2     ] │   │ ──────────────────────────────────────────  │ │
│ │ Flat rate     [ 0.12  ] │   │  SENSITIVITIES        │ CASHFLOWS            │ │
│ │ Day count   [ act365 v] │   │  YTM           0.1163 │  t      amount       │ │
│ │ Disc curve  [ flat(r) v]│   │  Mod dur       6.42   │  0.5    35.00        │ │
│ │                         │   │  Eff dur       6.40   │  1.0    35.00        │ │
│ │                         │   │  Convexity     51.2   │  ...    ...          │ │
│ │   [   Calculate   ]     │   │  DV01          0.62   │  10.0   1035.00      │ │
│ │                         │   │  Key-rate ▸ 1y .12 5y .帝│                    │ │
│ │                         │   │ ──────────────────────────────────────────  │ │
│ │                         │   │  ⚠ Demo/manual market data. Not production.  │ │
│ │                         │   │  Qty [ 1 ]   [ + Add to portfolio ]   ✓ added│ │
│ └─────────────────────────┘   └──────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
```
Notes: left = product input fields (driven by catalogue), right = governed result
(price + provenance chips + sensitivities + cashflow schedule + warnings + add-to-portfolio).

---

## 2. Dashboard

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Dashboard                                            ■ MOEX/OK   2026-06-02    │
├───────────────┬───────────────┬───────────────┬───────────────┬──────────────┤
│ PORTFOLIO MV  │ DAILY P&L     │ VaR 95%       │ ES 95%        │ DV01         │
│  ₽ 1.24bn     │  +₽ 3.1m      │  ₽ 18.4m      │  ₽ 24.1m      │  ₽ 0.9m      │
├───────────────┴───────────────┴───────────────┴───────────────┴──────────────┤
│ ┌─ Market summary ───────────┐  ┌─ Risk summary ─────────────────────────────┐│
│ │ КБД 10y   13.2%   ▲         │  │ VaR by factor  ▓▓▓▓ rates ▓▓ fx ▓ equity   ││
│ │ USD/RUB   74.36   ▼         │  │ Limit usage    ███████░░░ 72%              ││
│ │ RVI       28.4    ▲         │  │ Breaches       0                          ││
│ └────────────────────────────┘  └────────────────────────────────────────────┘│
│ ┌─ Model status ─────────────┐  ┌─ System / data status ─────────────────────┐│
│ │ Validated 4 · Approx 12 ·   │  │ MOEX EOD ✓   CBR ✓   FORTS ⚠   Snap OK     ││
│ │ Prototype 8 · Open 3        │  │ Last ingest 18:05                          ││
│ └────────────────────────────┘  └────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Portfolio

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Portfolio · Main                         MV ₽1.24bn   P&L +3.1m   ■ MOEX/OK    │
│ [ Positions ][ Exposure ][ Performance ][ Scenario P&L ][ Attribution ][ Valid]│
├──────────────────────────────────────────────────────────────────────────────┤
│ POSITIONS                                                                      │
│ Instrument        Qty     Price     MV        Delta   DV01   Vega   Status     │
│ Bond / OFZ        2500    799.4     1.99m       –      0.62    –     ■ Approx   │
│ Vanilla call      100     10.45     1.0k      0.58      –     0.39   ■ Fixed    │
│ Barrier DO        50      6.30      315       0.41      –     0.22   ■ Proto ⚠  │
│ Swaption payer    1m      8.0k      8.0k       –        4.1    250   ■ Approx   │
│ ...                                                                            │
├──────────────────────────────────────────────────────────────────────────────┤
│ EXPOSURE (risk-factor)   equity.spot  fx.usdrub  rates.5y  vol.implied  credit │
│                          ▓▓▓▓▓▓        ▓▓         ▓▓▓▓▓▓▓    ▓▓▓          ▓     │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Risk

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Risk · Main portfolio                                            ■ MOEX/OK     │
│ [ VaR / ES ][ Stress ][ Backtesting ][ Limits ][ Capital ]                     │
├──────────────────────────────────────────────────────────────────────────────┤
│ Method [ Historical v]  Conf [ 99% v]  Horizon [ 10d ]   [ Run ]               │
│ ┌─ Result ──────────────────┐  ┌─ Factor decomposition ────────────────────┐  │
│ │ VaR 99%   ₽ 18.4m         │  │ rates   ▓▓▓▓▓▓▓▓  11.2m                    │  │
│ │ ES  99%   ₽ 24.1m         │  │ equity  ▓▓▓▓      4.1m                     │  │
│ │ ES ≥ VaR  ✓               │  │ fx      ▓▓▓       2.3m                     │  │
│ │ ┌ P&L distribution ┐      │  │ vol     ▓         0.8m                     │  │
│ │ │   .▁▂▃▅█▅▃▂▁.     │      │  │ credit  ▎         0.1m                     │  │
│ │ └──────────────────┘      │  └────────────────────────────────────────────┘ │
│ └───────────────────────────┘                                                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Market Data

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Market Data                                  ■ MOEX  ■ CBR   Snap moex-…06-02  │
│ [ Yield Curves ][ FX ][ Vol Surfaces ][ Credit ][ Data Monitor ]              │
├──────────────────────────────────────────────────────────────────────────────┤
│ Curve [ GCURVE_RUB v]   source MOEX · quality OK · trade 2026-06-02            │
│ ┌─ Zero curve ───────────────────────────┐  ┌─ Lineage ─────────────────────┐ │
│ │ 15%┤                                    │  │ v3  OK   18:05  MOEX          │ │
│ │ 13%┤    ╴╴╴───────________              │  │ v2  STALE 06-01 MOEX          │ │
│ │ 11%┤ ╱                                  │  │ v1  OK    05-31 MOEX          │ │
│ │    └┬───┬───┬───┬───┬───┬──             │  └───────────────────────────────┘ │
│ │     1y  2y  5y  7y 10y 20y              │   tenors 0.25..20 · NSS B1 B2 B3   │ │
│ └────────────────────────────────────────┘                                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Design notes for Swift
- 3 zones: topbar (global status) · sidebar nav (8 sections) · workspace.
- Workspace pattern: header + horizontal tabs + content; right-rail only where it
  adds value (lineage), no empty drawers.
- Every result shows provenance inline: status chip · data source/quality · model
  version · snapshot id · warnings. Demo/stale → amber banner.
- Tables: dense, right-aligned numerics, monospaced figures.
- Each screen binds to one service response (PricingService / PortfolioService /
  RiskService / MarketDataService) → drives the FastAPI contract for Swift.
```
