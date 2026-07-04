import SwiftUI
import Charts

struct AnalyticsScreen: View {
    @Bindable var model: AppModel

    var body: some View {
        ScreenScaffold {
            PageHeader("Analytics Lab", subtitle: AppSection.analytics.subtitle)
            LoadableView(state: model.analytics,
                         retry: { Task { await model.load(.analytics, force: true) } }) { d in
                content(d)
            }
        }
    }

    @ViewBuilder
    private func content(_ d: AnalyticsData) -> some View {
        let scenarios = d.scenarios.scenarios
        let worst = scenarios.min(by: { $0.pnl < $1.pnl })
        let best = scenarios.max(by: { $0.pnl < $1.pnl })

        KPIStrip(items: [
            KPICard(label: "Scenarios", value: "\(scenarios.count)", sub: "stress library",
                    accent: Theme.accent, icon: "flask.fill"),
            KPICard(label: "Worst case", value: Fmt.money(worst?.pnl ?? 0),
                    sub: worst?.name ?? "—", accent: Theme.negative, icon: "arrow.down.right.circle.fill"),
            KPICard(label: "Best case", value: Fmt.money(best?.pnl ?? 0),
                    sub: best?.name ?? "—", accent: Theme.positive, icon: "arrow.up.right.circle.fill"),
        ])

        scenarioChartCard(scenarios)
        scenarioTableCard(scenarios)
        decompositionCard(d.decomposition)
    }

    private func scenarioChartCard(_ scenarios: [ScenarioRow]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Scenario P&L", icon: "chart.bar.fill")
                Chart(scenarios.sorted(by: { $0.pnl < $1.pnl })) { s in
                    BarMark(
                        x: .value("P&L", s.pnl),
                        y: .value("Scenario", s.name)
                    )
                    .foregroundStyle(Theme.trendColor(s.pnl))
                    .cornerRadius(3)
                }
                .chartXAxis {
                    AxisMarks { value in
                        AxisGridLine()
                        AxisValueLabel {
                            if let d = value.as(Double.self) { Text(Fmt.money(d)) }
                        }
                    }
                }
                .frame(height: CGFloat(scenarios.count) * 34 + 24)
            }
        }
    }

    private func scenarioTableCard(_ scenarios: [ScenarioRow]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Scenario definitions", icon: "list.bullet.clipboard")
                ForEach(scenarios) { s in
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.name).font(.system(size: 12, weight: .semibold))
                            Text(shockDescription(s.shocks))
                                .font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(Fmt.money(s.pnl))
                            .font(.system(size: 13, weight: .semibold)).monospacedDigit()
                            .foregroundStyle(Theme.trendColor(s.pnl))
                    }
                    Divider()
                }
            }
        }
    }

    private func decompositionCard(_ decomp: Decomposition) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Factor sensitivities", icon: "chart.bar.xaxis")
                ForEach(decomp.byFactor) { f in
                    HStack {
                        Circle().fill(Theme.bucketColor(f.bucket)).frame(width: 8, height: 8)
                        Text(f.factor).font(.system(size: 12))
                        Spacer()
                        Text("\(Fmt.money(f.sensitivity)) \(f.unit)")
                            .font(.system(size: 12, weight: .medium)).monospacedDigit()
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func shockDescription(_ shocks: [String: Double]) -> String {
        let names = ["dS": "spot", "dr": "rate", "dvol": "vol", "dfx": "fx", "dSpread": "spread"]
        return shocks.sorted(by: { $0.key < $1.key })
            .map { "\(names[$0.key] ?? $0.key) \(Fmt.signedPercent($0.value * 100, digits: 0))" }
            .joined(separator: " · ")
    }
}
