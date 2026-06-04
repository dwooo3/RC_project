# RiskCalc Desktop Workstation Design System

Date: 2026-06-04

Status: Product design specification

Companion wireframes:

- `RISKCALC_SCREEN_WIREFRAMES.md`

References:

- `PRODUCT_ARCHITECTURE.md`
- `RISKCALC_INFORMATION_ARCHITECTURE.md`
- `RISKCALC_UX_AUDIT.md`
- `UI_REDESIGN.md`

Benchmark intent:

- Bloomberg Terminal: dense analytics, keyboard speed, persistent context, fast module switching.
- Calypso: controlled front-to-risk workflow state, operational consistency, cross-asset process discipline.
- Murex MX.3: integrated trading, risk, pricing, and market-data workflow across asset classes.
- OpenGamma: transparent analytics, risk explainability, model and data provenance.

This design system must not imitate consumer finance dashboards, mobile-first SaaS, or decorative concept UI. RiskCalc is a professional desktop workstation for market risk, pricing, portfolio analytics, and model governance.

## 1. Design Principles

### 1.1 Workstation First

RiskCalc should feel like software used for repeated analytical work during a market day.

Design for:

- dense information;
- keyboard operation;
- multi-panel workflows;
- persistent portfolio and market-data context;
- reproducible calculations;
- fast drill-down from summary to detail;
- clear warnings and model status.

Avoid:

- hero sections;
- oversized empty cards;
- mobile navigation patterns;
- marketing copy;
- decorative illustrations;
- consumer banking aesthetics;
- large rounded tiles that hide data.

### 1.2 Portfolio And Risk Before Calculators

The design must reinforce this IA order:

```text
Dashboard
Portfolio
Risk
Market Data
Pricing
Governance
Analytics Lab
```

Pricing modules are important, but the product should not feel like a catalog of calculators. Portfolio and risk workflows are the operating center.

### 1.3 Every Number Must Explain Itself

Every calculated value must be traceable to:

- portfolio;
- book;
- valuation date;
- market-data snapshot;
- source;
- model ID;
- model status;
- calculation timestamp;
- warnings;
- assumptions and limitations.

This should be visible in the UI, not hidden in logs.

### 1.4 Density With Control

Dense does not mean chaotic. The workstation should use:

- tight tables;
- small labels;
- high contrast numeric values;
- minimal borders;
- fixed panel proportions;
- compact command bars;
- right-side context panels;
- no decorative empty space.

## 2. Layout System

### 2.1 Application Frame

The application frame has four persistent regions:

```text
┌──────────────────────────────────────────────────────────────┐
│ Top Command Bar                                              │
├────────────┬──────────────────────────────────────┬──────────┤
│ Sidebar    │ Workspace                            │ Context  │
│ Navigation │                                      │ Drawer   │
├────────────┴──────────────────────────────────────┴──────────┤
│ Status / Audit Bar                                           │
└──────────────────────────────────────────────────────────────┘
```

Required frame regions:

- Left sidebar: product layers only.
- Top command bar: global search, active portfolio, valuation date, market-data snapshot, mode, run/save/export controls.
- Workspace: current screen content.
- Right context drawer: calculation metadata, warnings, model details, selected object detail.
- Bottom status/audit bar: last calculation, data freshness, keyboard hint, warning count.

### 2.2 Workspace Grid

Use a 12-column desktop grid.

Recommended dimensions:

```text
Minimum window: 1280 x 800
Ideal window:   1440 x 900
Power layout:   1920 x 1080+
Sidebar:        196 px
Context drawer: 300-360 px
Top bar:        44 px
Status bar:     24 px
Gutter:         8 px
Panel padding:  10-14 px
```

### 2.3 Standard Workspace Anatomy

Every major workspace should follow this structure:

```text
Workspace Header
  Title / subtitle
  Scope controls
  Primary actions

KPI Strip
  5-8 compact metrics

Main Split
  Left: filters / inputs / object list
  Center: table / chart / calculation result
  Right: context / warnings / metadata

Bottom Tabs
  Detail views, logs, validation, history
```

### 2.4 Panel Sizes

Use stable sizes to avoid layout jump:

```text
Sidebar              196 px fixed
Left workflow panel  280-360 px
Context drawer       300-360 px
KPI card height      64-76 px
Command bar height   44 px
Status bar height    24 px
Table row height     24-28 px
Tabs height          32-36 px
Toolbar height       32-36 px
```

## 3. Color System

### 3.1 Dark Theme Tokens

RiskCalc should use one institutional dark theme as the primary product theme.

```text
bg_root              #0B0D10
bg_sidebar           #111418
bg_topbar            #0F1216
bg_workspace         #14171C
bg_panel             #181C22
bg_panel_elevated    #1D2229
bg_table_header      #202630
bg_table_row         #15191F
bg_table_row_alt     #181D24
bg_selected          #2A211B
bg_warning           #2A2115
bg_error             #2A1518
bg_success           #14231B

border_strong        #38404A
border_default       #2A313A
border_soft          #20262E
divider              #252C34

text_primary         #F2F4F7
text_secondary       #B8C0CC
text_muted           #7C8796
text_disabled        #505A66

accent_orange        #D97757
accent_orange_soft   #3A251C
accent_blue          #5AA9E6
accent_green         #30D158
accent_red           #FF453A
accent_amber         #FFD60A
accent_cyan          #4DD0E1
accent_purple        #B39DDB
```

### 3.2 Semantic Colors

Use semantic color consistently:

```text
Validated      green
Approximation  amber
Prototype      purple
Placeholder    muted gray
Broken         red
Demo data      amber
Manual data    blue
CSV data       cyan
External data  green
Risk breach    red
Warning        amber
Info           blue
Selected       orange soft background
```

### 3.3 Color Discipline

Rules:

- Orange is the product accent and active-state color.
- Red is only for breaches, broken models, failed calculations, and hard errors.
- Amber is for approximations, demo data, stale data, and warnings.
- Green is for validated/healthy states.
- Blue/cyan are for data sources and informational state.
- Do not make charts and panels a one-note orange or blue theme.
- Do not use gradients, glassmorphism, decorative glows, or bokeh backgrounds.

## 4. Typography

### 4.1 Font Strategy

Use a highly legible desktop UI font.

Preferred stack:

```text
Inter
SF Pro
Segoe UI
Arial
```

Use a monospace font for:

- IDs;
- tickers;
- tenors;
- timestamps;
- model IDs;
- calculation IDs;
- numeric tables where alignment matters.

Monospace stack:

```text
JetBrains Mono
SF Mono
Consolas
monospace
```

### 4.2 Type Scale

```text
App title              18 px / 700
Workspace title        20 px / 700
Section title          11 px / 700 uppercase
Card title             13 px / 600
KPI value              24 px / 700
KPI label              10 px / 700 uppercase
Body                   12 px / 400
Table                  12 px / 400
Table numeric          12 px / 500 monospace
Secondary              11 px / 400
Micro label            10 px / 500
Status chip            10 px / 700 uppercase
```

### 4.3 Numeric Formatting

Rules:

- Align numeric columns right.
- Use tabular numerals where available.
- Use consistent sign display:

```text
+1.25
-0.84
0.00
```

- Use fixed precision by metric type:

```text
Price / NPV       2-4 decimals
Rates             2-4 decimals or bp
VaR / ES          currency with separator
Sensitivities     2-4 decimals
Percentages       2 decimals
Dates             YYYY-MM-DD
Timestamps        YYYY-MM-DD HH:MM:SS
```

## 5. Component System

### 5.1 Navigation Components

#### SidebarNav

Purpose:

- primary layer navigation.

Items:

```text
Dashboard
Portfolio
Risk
Market Data
Pricing
Governance
Analytics Lab
```

Behavior:

- fixed width;
- keyboard shortcuts visible on hover or context help;
- active item uses orange accent rail;
- no instrument modules in sidebar.

#### CommandBar

Purpose:

- global search and active context control.

Contains:

- command palette trigger;
- active portfolio selector;
- book selector;
- valuation date;
- active market-data snapshot;
- mode selector;
- run/save/export buttons;
- warning count.

#### BreadcrumbBar

Purpose:

- reveal workflow position.

Example:

```text
Portfolio > Scenario P&L > Historical Shock
Pricing > Rates > Bond Pricing
Risk > VaR / ES > Backtesting
```

### 5.2 Status Components

#### StatusChip

Variants:

```text
Healthy
Warning
Error
Info
Muted
```

#### ModelStatusChip

Variants:

```text
Validated
Approximation
Prototype
Placeholder
Broken
```

#### DataSourceChip

Variants:

```text
DEMO
MANUAL
CSV
MOEX
Bloomberg
Reuters
```

#### WarningBanner

Use for:

- demo data warnings;
- model approximation warnings;
- broken calculation errors;
- stale snapshot warnings;
- unsupported workflow warnings.

Rules:

- do not hide warnings below the fold;
- do not use only color to convey severity;
- warnings should link to detail or Governance where possible.

### 5.3 Data Components

#### DenseTable

Purpose:

- positions, risk results, curves, cashflows, audit records.

Features:

- sortable columns;
- frozen left identifier column for large tables;
- right-aligned numeric columns;
- compact row height;
- column resize;
- filter row;
- selected row detail in context drawer.

#### MetricGrid

Purpose:

- compact metric groups inside a panel.

Use for:

- pricing metrics;
- valuation metrics;
- risk metric groups;
- model metadata.

#### KpiStrip

Purpose:

- top-level summary of current workspace.

Rules:

- 5-8 KPIs maximum;
- each KPI has label, value, delta/status, and optional source;
- do not use giant marketing dashboard cards.

### 5.4 Workflow Components

#### WorkspaceHeader

Contains:

- title;
- subtitle;
- scope controls;
- model/data status chips;
- primary actions.

#### ObjectDrawer

Purpose:

- selected row/object detail.

Use for:

- position detail;
- model detail;
- market-data snapshot detail;
- scenario detail;
- calculation result detail.

#### ScenarioBuilder

Purpose:

- standard shock configuration.

Controls:

- scenario type;
- factor group;
- shock magnitude;
- tenor selection;
- save/apply buttons.

#### ResultContextPanel

Purpose:

- provenance for calculated results.

Required fields:

- calculation ID;
- timestamp;
- model ID;
- model status;
- market-data snapshot;
- valuation date;
- warnings;
- errors;
- limitations.

## 6. Screen Templates

### 6.1 Dashboard Template

```text
Header
KPI Strip
Left: Daily checklist
Center: portfolio/risk status grid
Right: warnings and recent calculations
Bottom: alerts table
```

### 6.2 Portfolio Template

```text
Header
KPI Strip
Left: portfolio/book/filter panel
Center: positions/exposure/risk tables
Right: selected position/context drawer
Bottom: tabs for valuation, scenario, attribution, validation
```

### 6.3 Risk Template

```text
Header
KPI Strip
Left: risk method and scope controls
Center: distribution/stress/backtest view
Right: model/data/warning context
Bottom: method comparison and contribution tables
```

### 6.4 Pricing Template

```text
Header
Left: trade inputs
Center: pricing result and charts
Right: model/data/context
Bottom: cashflows, sensitivities, scenario, validation tabs
```

### 6.5 Market Data Template

```text
Header
KPI Strip
Left: source/snapshot tree
Center: curve/surface/FX/credit views
Right: validation/source metadata
Bottom: points table and version history
```

## 7. Interaction Model

### 7.1 Keyboard First

Every screen must support:

- focus movement with Tab / Shift+Tab;
- row movement with arrow keys;
- primary calculation action from keyboard;
- Escape to close drawers/dialogs;
- command palette search.

Global shortcuts:

```text
Ctrl+K  Command palette
Ctrl+R  Run calculation
Ctrl+S  Save current object/result
Ctrl+E  Export current screen/result
Ctrl+L  Warning log
Ctrl+F  Focus local filter/search
F1      Context help
Esc     Close current overlay/drawer
```

Layer shortcuts:

```text
Ctrl+1  Dashboard
Ctrl+2  Portfolio
Ctrl+3  Risk
Ctrl+4  Market Data
Ctrl+5  Pricing
Ctrl+6  Governance
Ctrl+7  Analytics Lab
```

### 7.2 Mouse Interaction

Mouse interactions should support:

- row selection;
- column sorting;
- drag column resize;
- context drawer opening;
- chart hover tooltips;
- quick action menus.

Do not rely on hover-only controls for critical actions.

### 7.3 Command Palette

Command palette must support:

- open layer;
- open screen;
- run workflow;
- search model;
- search portfolio;
- search market-data snapshot;
- open recent calculation.

Example commands:

```text
Run VaR
Run Stress
Open Bond Pricing
Open Active Snapshot
Open Model Registry
Export Risk Report
Add Position
Open Warnings
```

## 8. Workspace-Specific Requirements

### 8.1 Dashboard

Must show:

- portfolio status;
- risk status;
- market-data status;
- model status;
- required actions;
- warning count;
- recent calculations.

Must not show:

- pricing forms;
- full model registry;
- raw technical logs;
- research experiments.

### 8.2 Portfolio Workspace

Must show:

- positions;
- market value;
- P&L;
- factor exposures;
- portfolio valuation status;
- scenario P&L;
- P&L explain;
- validation issues.

Must avoid:

- raw aggregate Greeks as the main summary;
- modal-only position management;
- untyped position forms without validation.

### 8.3 Risk Workspace

Must show:

- VaR / ES;
- stress;
- backtesting;
- limits;
- risk contribution;
- model/data warnings.

Must avoid:

- generic Portfolio card;
- disconnected single-series VaR as the main professional workflow;
- hidden demo-data warnings.

### 8.4 Pricing Workspace

Must show:

- grouped product modules;
- active market-data snapshot;
- model status;
- pricing inputs;
- pricing results;
- sensitivities;
- scenario;
- save-to-portfolio action;
- export ticket action.

Must avoid:

- flat 17-card catalog;
- XVA as a generic pricing module;
- market-data construction in pricing UI;
- silent prototype model use.

### 8.5 Market Data Workspace

Must show:

- active snapshot;
- source status;
- yield curves;
- vol surfaces;
- FX market data;
- credit curves;
- validation.

Must avoid:

- FX option pricing in Market Data;
- unversioned curve edits;
- hidden demo/manual source state.

## 9. Accessibility And Legibility

Requirements:

- all critical text must meet contrast expectations for dark UI;
- warnings cannot rely on color alone;
- focus state must be visible;
- tables must support keyboard selection;
- charts must expose numeric values in tables;
- text must not scale with viewport width;
- dense tables must retain readable row height;
- status chips must use label plus color.

## 10. Implementation Guidance

### 10.1 Component Ownership

Recommended component modules:

```text
ui/theme.py
ui/components.py
ui/layouts.py
ui/tables.py
ui/charts.py
ui/commands.py
```

Do not duplicate:

- module cards;
- status chips;
- warning banners;
- KPI cards;
- table styles;
- context drawers.

### 10.2 Migration Order

1. Add command bar and global context bar.
2. Create shared workstation layout primitives.
3. Rebuild Dashboard shell with existing data.
4. Rebuild Portfolio workspace around tabs and factor exposures.
5. Rebuild Risk workspace around portfolio risk.
6. Rebuild Market Data as snapshot control center.
7. Rebuild Pricing landing as grouped workflow.
8. Add Governance top-level workspace.
9. Apply Analytics Lab research-mode treatment.

### 10.3 Acceptance Criteria

The workstation redesign is acceptable when:

- a user can operate core workflows without opening isolated calculators;
- every screen shows active portfolio, valuation date, market-data source, and warning state;
- every calculation result has visible provenance;
- tables are dense and keyboard navigable;
- warnings and model statuses are visible before action;
- Portfolio, Risk, Market Data, and Pricing each have distinct ownership;
- the product looks institutional and operational, not consumer or concept-oriented.

## 11. Source Notes

Benchmark sources used for product positioning:

- Bloomberg Portfolio Analytics: https://www.bloomberg.com/professional/products/bloomberg-terminal/portfolio-analytics/
- Nasdaq Calypso: https://www.nasdaq.com/solutions/fintech/nasdaq-calypso
- Murex MX.3: https://www.murex.com/en
- OpenGamma documentation: https://docs.opengamma.com/
