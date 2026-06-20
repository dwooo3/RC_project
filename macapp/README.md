# RiskCalc — native macOS app (SwiftUI)

The full RiskCalc workstation as a native macOS app. The Python engine and all
models are **unchanged**: a FastAPI bridge (`../api/`) exposes the existing
services as JSON and this SwiftUI app is the entire UI.

```
┌──────────────────┐   HTTP/JSON     ┌──────────────────┐   in-process   ┌─────────────────┐
│  SwiftUI app     │ ──────────────▶ │  FastAPI bridge  │ ─────────────▶ │ services + models│
│  (macapp/)       │  7 endpoints    │  (api/server.py) │   (unchanged)  │  + live MOEX DB  │
└──────────────────┘ ◀────────────── └──────────────────┘ ◀───────────── └─────────────────┘
```

## Run it

**1. Start the Python bridge** (from the repo root):

```bash
/usr/local/bin/python3.14 -m api.server      # http://127.0.0.1:8765
```

**2. Run the app — any of:**

- **Xcode** (live previews): `File ▸ Open…` → `macapp/Package.swift`, then ⌘R.
- **CLI dev build:** `cd macapp && swift run`
- **Double-clickable app:** `cd macapp && ./package_app.sh` → open `build/RiskCalc.app`

If the bridge is down the app shows a retry screen with the command to start it.

## Screens (all 7 workspaces)

| Screen | Content | Source |
|--------|---------|--------|
| **Dashboard** | KPI strip (portfolio value, VaR, ES, key rate, models), FX, vols, top movers, governance bar | `/dashboard` |
| **Portfolio** | KPI strip, sortable positions table, risk-factor exposure buckets | `/portfolio` |
| **Risk** | VaR 95/99 · 1d/10d + ES cards, what-if P&L heatmap, factor-sensitivity bars | `/risk` |
| **Market Data** | OFZ zero-curve chart, FX & vol grids, top-movers / most-active tables | `/market` |
| **Pricing** | Instrument-class tabs (Options · Bond). **Options**: 10 pricers incl. Heston/Merton. **Bond** has three modes: **Single** (14 instruments — ОФЗ, fixed/step/amortizing/perpetual, FRN/inflation, callable-putable w/ OAS-to-market, custom-cashflow, MBS, money-market — settlement dates/conventions/day-counts, discount-curve + parallel-shift, zero/par/forward curve chart, full analytics + cashflow chart/table); **Pricing sheet** (multi-bond portfolio aggregates + combined KRD ladder); **Real bonds** (live MOEX OFZ feed: search/select a real bond → market quote vs theoretical, Z-spread & G-spread, reprice on any curve with a shift) | `/catalogue`, `/price`, `/instruments/bond`, `/instruments/bond/price_batch`, `/curves`, `/realbonds`, `/realbonds/reprice` |
| **Governance** | Status donut, full model registry table, limitations | `/governance` |
| **Analytics Lab** | Scenario-library P&L bars + definitions, factor sensitivities | `/analytics` |

Data is **live MOEX** when `data/market_data.sqlite` is present (the sidebar
footer shows Live · `<snapshot>`), otherwise demo. The demo book is a
representative 4-position portfolio (equity / rates / FX).

## Design

Modern macOS (Tahoe / Liquid-Glass era): `NavigationSplitView` shell, translucent
material cards, SF Symbols, Swift Charts, tabular figures, semantic colours that
adapt to light/dark automatically. One accent + status palette
(Validated/Approximation/Prototype/…) is shared across every screen. Tokens live
in `Theme.swift`; reusable components in `DesignSystem.swift` / `Components.swift`.

## Structure

```
macapp/
  Package.swift            SwiftPM executable target
  Info.plist               bundle metadata (+ localhost ATS exception)
  package_app.sh           build release → assemble RiskCalc.app
  Sources/RiskCalc/
    RiskCalcApp.swift       @main + window activation
    RootView.swift          sidebar shell + routing + refresh + bridge-down overlay
    AppModel.swift          @Observable state, section routing, async loaders
    Theme.swift             colour / spacing / formatting tokens
    DesignSystem.swift      PageHeader, GlassCard, KPICard, LoadableView, …
    Components.swift         StatusChip, NumberField, ChoiceField, MetricCell, …
    DataModels.swift        Codable mirrors of every endpoint
    BridgeClient.swift      async URLSession client
    Dashboard/Market/Portfolio/Risk/Governance/Analytics Screen.swift
    Pricing*: PricingScreen (PricingView) + PricerList/ParameterForm/Result + PricingViewModel + Models
```

## Extending

- **New pricer:** one row in `../api/catalogue.py` — the Pricing screen renders it.
- **New screen:** add an `/endpoint` + payload builder in `../api/payloads.py`, a
  Codable in `DataModels.swift`, a loader in `AppModel`, and a screen view. The
  shell routing and design components are already shared.
