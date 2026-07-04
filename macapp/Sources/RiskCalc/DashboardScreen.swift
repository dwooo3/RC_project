import SwiftUI

struct DashboardScreen: View {
    @Bindable var model: AppModel

    var body: some View {
        ScreenScaffold {
            PageHeader("Dashboard", subtitle: AppSection.dashboard.subtitle)
            LoadableView(state: model.dashboard,
                         retry: { Task { await model.load(.dashboard, force: true) } }) { d in
                content(d)
            }
        }
    }

    @ViewBuilder
    private func content(_ d: DashboardData) -> some View {
        let ccy = d.portfolio.baseCurrency
        let validated = d.governance.counts["Validated"] ?? 0

        KPIStrip(items: [
            KPICard(label: "Portfolio value", value: Fmt.money(d.portfolio.totalMarketValue, currency: ccy),
                    sub: "\(d.portfolio.nPositions) positions", accent: Theme.accent, icon: "briefcase.fill"),
            KPICard(label: "VaR 99% · 1d", value: Fmt.money(d.risk.varValue, currency: ccy),
                    sub: "parametric", accent: Theme.negative, icon: "shield.lefthalf.filled"),
            KPICard(label: "Expected shortfall", value: Fmt.money(d.risk.expectedShortfall, currency: ccy),
                    sub: "99% · 1d", accent: Theme.warning, icon: "waveform.path.ecg"),
            KPICard(label: "Key rate", value: d.market.keyRate.map { Fmt.percent($0, digits: 2) } ?? "—",
                    sub: "CBR", accent: Theme.bucketColor("Rates"), icon: "percent"),
            KPICard(label: "Models", value: "\(validated)/\(d.governance.total)",
                    sub: "validated", accent: Theme.positive, icon: "checkmark.seal.fill"),
        ])

        HStack(alignment: .top, spacing: Theme.s4) {
            fxCard(d.market.fx, ccy: ccy)
            volsCard(d.market.keyVols)
        }

        moversCard(d.market.topMovers)
        governanceCard(d.governance)
    }

    private func fxCard(_ fx: [String: Double], ccy: String) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("FX rates", icon: "dollarsign.arrow.circlepath")
                ForEach(fx.sorted(by: { $0.key < $1.key }), id: \.key) { pair, rate in
                    KeyValueRow(key: pair, value: Fmt.number(rate, digits: 4))
                }
            }
        }
    }

    private func volsCard(_ vols: [String: Double]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Key implied vols", icon: "waveform")
                ForEach(vols.sorted(by: { $0.key < $1.key }), id: \.key) { name, vol in
                    KeyValueRow(key: name, value: Fmt.percent(vol, digits: 1))
                }
            }
        }
    }

    private func moversCard(_ movers: [Mover]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Top movers", icon: "arrow.up.arrow.down")
                ForEach(movers) { m in
                    HStack {
                        Text(m.secid).font(.system(size: 12, weight: .medium))
                        Spacer()
                        Text(Fmt.number(m.last, digits: 2))
                            .font(.system(size: 12)).monospacedDigit().foregroundStyle(.secondary)
                        Text(Fmt.signedPercent(m.chgPct))
                            .font(.system(size: 12, weight: .semibold)).monospacedDigit()
                            .foregroundStyle(Theme.trendColor(m.chgPct))
                            .frame(width: 72, alignment: .trailing)
                    }
                }
            }
        }
    }

    private func governanceCard(_ g: GovernanceMini) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Model governance", icon: "checkmark.seal")
                StatusBar(counts: g.counts)
                HStack(spacing: Theme.s2) {
                    ForEach(["Validated", "Approximation", "Prototype", "Placeholder", "Broken"], id: \.self) { s in
                        if let n = g.counts[s], n > 0 {
                            Pill(text: "\(s) \(n)", color: Theme.statusColor(s))
                        }
                    }
                }
            }
        }
    }
}

/// Proportional horizontal bar of governance statuses.
struct StatusBar: View {
    let counts: [String: Int]
    private let order = ["Validated", "Approximation", "Prototype", "Placeholder", "Broken"]

    var body: some View {
        let total = max(1, counts.values.reduce(0, +))
        GeometryReader { geo in
            HStack(spacing: 2) {
                ForEach(order, id: \.self) { s in
                    let n = counts[s] ?? 0
                    if n > 0 {
                        Theme.statusColor(s)
                            .frame(width: max(2, geo.size.width * CGFloat(n) / CGFloat(total)))
                    }
                }
            }
            .clipShape(Capsule())
        }
        .frame(height: 10)
    }
}
