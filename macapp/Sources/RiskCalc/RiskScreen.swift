import SwiftUI
import Charts

struct RiskScreen: View {
    @Bindable var model: AppModel

    var body: some View {
        ScreenScaffold {
            PageHeader("Risk", subtitle: AppSection.risk.subtitle)
            LoadableView(state: model.risk,
                         retry: { Task { await model.load(.risk, force: true) } }) { d in
                content(d)
            }
        }
    }

    @ViewBuilder
    private func content(_ d: RiskData) -> some View {
        KPIStrip(items: [
            KPICard(label: "VaR 99% · 1d", value: Fmt.money(d.var99.varValue),
                    sub: d.var99.volSource, accent: Theme.negative, icon: "shield.lefthalf.filled"),
            KPICard(label: "VaR 95% · 1d", value: Fmt.money(d.var95.varValue),
                    sub: "parametric", accent: Theme.warning, icon: "shield"),
            KPICard(label: "VaR 99% · 10d", value: Fmt.money(d.var9910d.varValue),
                    sub: "√10 scaled", accent: Theme.negative, icon: "calendar"),
            KPICard(label: "Expected shortfall", value: Fmt.money(d.var99.expectedShortfall),
                    sub: "99% · 1d", accent: Theme.bucketColor("Volatility"), icon: "waveform.path.ecg"),
            KPICard(label: "σ (annual)", value: Fmt.percent(d.var99.sigmaAnnual * 100, digits: 1),
                    sub: "RTS implied", accent: Theme.accent, icon: "function"),
        ])

        methodNote(d.var99)
        heatmapCard(d.whatIfGrid)
        decompositionCard(d.decomposition)
    }

    private func methodNote(_ v: VaR) -> some View {
        GlassCard {
            HStack(spacing: Theme.s2) {
                Image(systemName: "info.circle").foregroundStyle(Theme.accent)
                Text("\(v.method) VaR on |market value| \(Fmt.money(abs(v.marketValue))), σ from \(v.volSource).")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
            }
        }
    }

    // MARK: what-if heatmap

    private func heatmapCard(_ grid: WhatIfGrid) -> some View {
        let cells = heatCells(grid)
        let maxAbs = max(1, cells.map { abs($0.pnl) }.max() ?? 1)
        let spotLabels = grid.spotShocks.map { label($0) }
        let volLabels = grid.volShocks.map { label($0) }

        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("What-if P&L · spot × vol", icon: "square.grid.3x3.fill")
                if cells.isEmpty {
                    Text("Grid unavailable").font(.caption).foregroundStyle(.secondary).frame(height: 200)
                } else {
                    Chart(cells) { c in
                        RectangleMark(
                            x: .value("Spot", c.spot),
                            y: .value("Vol", c.vol)
                        )
                        .foregroundStyle(heatColor(c.pnl, maxAbs: maxAbs))
                        .annotation(position: .overlay) {
                            Text(Fmt.money(c.pnl))
                                .font(.system(size: 9, weight: .medium)).monospacedDigit()
                                .foregroundStyle(.primary)
                        }
                    }
                    .chartXScale(domain: spotLabels)
                    .chartYScale(domain: volLabels)
                    .chartXAxisLabel("Spot shock")
                    .chartYAxisLabel("Vol shock")
                    .frame(height: 260)
                    HStack(spacing: Theme.s3) {
                        legendSwatch(Theme.negative, "loss")
                        legendSwatch(Theme.positive, "gain")
                        Spacer()
                    }
                }
            }
        }
    }

    private func decompositionCard(_ decomp: Decomposition) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Risk-factor sensitivities", icon: "chart.bar.xaxis")
                if decomp.byFactor.isEmpty {
                    Text("No factor exposures").font(.caption).foregroundStyle(.secondary)
                } else {
                    Chart(decomp.byFactor) { f in
                        BarMark(
                            x: .value("Sensitivity", abs(f.sensitivity)),
                            y: .value("Factor", f.factor)
                        )
                        .foregroundStyle(Theme.bucketColor(f.bucket))
                        .annotation(position: .trailing) {
                            Text("\(Fmt.money(f.sensitivity)) \(f.unit)")
                                .font(.system(size: 9)).foregroundStyle(.secondary)
                        }
                    }
                    .chartXAxis(.hidden)
                    .frame(height: CGFloat(decomp.byFactor.count) * 32 + 20)
                }
            }
        }
    }

    private func legendSwatch(_ color: Color, _ text: String) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 3).fill(color.opacity(0.7)).frame(width: 14, height: 10)
            Text(text).font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }

    // MARK: helpers

    private struct HeatCell: Identifiable {
        let id: Int
        let spot: String
        let vol: String
        let pnl: Double
    }

    private func heatCells(_ grid: WhatIfGrid) -> [HeatCell] {
        var cells: [HeatCell] = []
        var i = 0
        for (vi, dv) in grid.volShocks.enumerated() {
            guard vi < grid.pnlGrid.count else { break }
            for (si, ds) in grid.spotShocks.enumerated() {
                guard si < grid.pnlGrid[vi].count else { break }
                cells.append(HeatCell(id: i, spot: label(ds), vol: label(dv), pnl: grid.pnlGrid[vi][si]))
                i += 1
            }
        }
        return cells
    }

    private func label(_ shock: Double) -> String {
        let pct = shock * 100
        return (pct > 0 ? "+" : "") + "\(Int(pct.rounded()))%"
    }

    private func heatColor(_ pnl: Double, maxAbs: Double) -> Color {
        let t = max(-1, min(1, pnl / maxAbs))
        return (t >= 0 ? Theme.positive : Theme.negative).opacity(0.18 + 0.72 * abs(t))
    }
}
