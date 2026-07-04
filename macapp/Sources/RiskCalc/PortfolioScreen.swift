import SwiftUI

struct PortfolioScreen: View {
    @Bindable var model: AppModel

    var body: some View {
        ScreenScaffold {
            PageHeader("Portfolio", subtitle: AppSection.portfolio.subtitle)
            LoadableView(state: model.portfolio,
                         retry: { Task { await model.load(.portfolio, force: true) } }) { d in
                content(d)
            }
        }
    }

    @ViewBuilder
    private func content(_ d: PortfolioData) -> some View {
        let ccy = d.valuation.baseCurrency
        let buckets = d.aggregate.exposureBuckets

        KPIStrip(items: [
            KPICard(label: "Market value", value: Fmt.money(d.valuation.totalMarketValue, currency: ccy),
                    sub: d.valuation.portfolioID, accent: Theme.accent, icon: "briefcase.fill"),
            KPICard(label: "Positions", value: "\(d.valuation.nPositions)",
                    sub: "active", accent: Theme.bucketColor("Equity"), icon: "list.bullet.rectangle"),
            KPICard(label: "Equity Δ", value: Fmt.money(buckets["Equity"]?["Delta"] ?? 0),
                    sub: "spot delta", accent: Theme.bucketColor("Equity"), icon: "chart.line.uptrend.xyaxis"),
            KPICard(label: "Rates DV01", value: Fmt.money(buckets["Rates"]?["DV01"] ?? 0),
                    sub: "per bp", accent: Theme.bucketColor("Rates"), icon: "percent"),
            KPICard(label: "Vega", value: Fmt.money(buckets["Volatility"]?["Vega"] ?? 0),
                    sub: "per vol pt", accent: Theme.bucketColor("Volatility"), icon: "waveform"),
        ])

        if !d.valuation.warnings.isEmpty {
            warningBanner(d.valuation.warnings)
        }

        positionsCard(d.positions)
        exposuresCard(buckets)
    }

    private func positionsCard(_ positions: [PositionRow]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Positions", icon: "tablecells")
                Table(positions.sorted { ($0.marketValue ?? 0) > ($1.marketValue ?? 0) }) {
                    TableColumn("Instrument") { p in
                        Text(p.instrument).font(.system(size: 12, weight: .medium))
                    }
                    TableColumn("Description") { p in
                        Text(p.description).foregroundStyle(.secondary)
                    }
                    TableColumn("Qty") { p in num(p.quantity, 0) }
                    TableColumn("Price") { p in num(p.price, 2) }
                    TableColumn("Market value") { p in num(p.marketValue, 2).fontWeight(.semibold) }
                    TableColumn("Delta") { p in num(p.delta, 2) }
                    TableColumn("DV01") { p in num(p.dv01, 2) }
                    TableColumn("Vega") { p in num(p.vega, 2) }
                }
                // Size to content (+ header) so the table doesn't pad out with
                // empty filler rows; cap so a large book still scrolls.
                .frame(height: min(CGFloat(max(1, positions.count)), 14) * 28 + 36)
            }
        }
    }

    private func exposuresCard(_ buckets: [String: [String: Double]]) -> some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            BlockTitle("Risk-factor exposures", icon: "square.stack.3d.up")
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: Theme.s3)],
                      alignment: .leading, spacing: Theme.s3) {
                ForEach(buckets.filter { !$0.value.isEmpty }.sorted(by: { $0.key < $1.key }), id: \.key) { name, metrics in
                    GlassCard {
                        VStack(alignment: .leading, spacing: Theme.s2) {
                            HStack(spacing: Theme.s2) {
                                Circle().fill(Theme.bucketColor(name)).frame(width: 8, height: 8)
                                Text(name).font(.system(size: 13, weight: .semibold))
                            }
                            Divider()
                            ForEach(metrics.sorted(by: { $0.key < $1.key }), id: \.key) { metric, value in
                                KeyValueRow(key: metric, value: Fmt.money(value))
                            }
                        }
                        .frame(maxHeight: .infinity, alignment: .top)
                    }
                }
            }
        }
    }

    private func warningBanner(_ warnings: [String]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s2) {
                Label("Service notes", systemImage: "info.circle")
                    .font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.warning)
                ForEach(warnings.prefix(4), id: \.self) { w in
                    Text("• \(w)").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func num(_ value: Double?, _ digits: Int) -> Text {
        Text(value.map { Fmt.number($0, digits: digits) } ?? "—").monospacedDigit()
    }
}
