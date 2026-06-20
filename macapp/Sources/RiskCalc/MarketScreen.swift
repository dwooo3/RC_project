import SwiftUI
import Charts

struct MarketScreen: View {
    @Bindable var model: AppModel

    var body: some View {
        ScreenScaffold {
            PageHeader("Market Data", subtitle: AppSection.market.subtitle)
            LoadableView(state: model.market,
                         retry: { Task { await model.load(.market, force: true) } }) { d in
                content(d)
            }
            InstrumentCatalogView()
        }
        .navigationTitle("Market Data")
    }

    @ViewBuilder
    private func content(_ d: MarketData) -> some View {
        KPIStrip(items: [
            KPICard(label: "Key rate", value: d.overview.keyRate.map { Fmt.percent($0, digits: 2) } ?? "—",
                    sub: "CBR", accent: Theme.bucketColor("Rates"), icon: "percent"),
            KPICard(label: "USD/RUB", value: d.overview.fx["USD/RUB"].map { Fmt.number($0, digits: 2) } ?? "—",
                    sub: "spot", accent: Theme.bucketColor("FX"), icon: "dollarsign.circle"),
            KPICard(label: "RTS vol", value: d.overview.keyVols["RTS"].map { Fmt.percent($0, digits: 1) } ?? "—",
                    sub: "implied", accent: Theme.bucketColor("Volatility"), icon: "waveform"),
            KPICard(label: "Source", value: d.snapshot.isLive ? "Live" : "Demo",
                    sub: d.snapshot.snapshotID, accent: d.snapshot.isLive ? Theme.positive : Theme.warning,
                    icon: "antenna.radiowaves.left.and.right"),
        ])

        curveCard(d.curve)

        HStack(alignment: .top, spacing: Theme.s4) {
            quoteTable("Top movers", icon: "arrow.up.arrow.down", movers: d.overview.topMovers)
            quoteTable("Most active", icon: "chart.bar.fill", movers: d.overview.mostActive)
        }

        HStack(alignment: .top, spacing: Theme.s4) {
            mapCard("FX rates", icon: "dollarsign.arrow.circlepath",
                    rows: d.overview.fx.sorted(by: { $0.key < $1.key }).map { ($0.key, Fmt.number($0.value, digits: 4)) })
            mapCard("Key implied vols", icon: "waveform.path",
                    rows: d.overview.keyVols.sorted(by: { $0.key < $1.key }).map { ($0.key, Fmt.percent($0.value, digits: 1)) })
        }
    }

    private func curveCard(_ curve: [CurvePoint]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("OFZ zero curve", icon: "chart.xyaxis.line")
                if curve.isEmpty {
                    Text("Curve unavailable").font(.caption).foregroundStyle(.secondary).frame(height: 220)
                } else {
                    let rates = curve.map { $0.rate * 100 }
                    let lo = (rates.min() ?? 0), hi = (rates.max() ?? 1)
                    let pad = max((hi - lo) * 0.15, 0.2)
                    let floor = lo - pad
                    Chart(curve) { p in
                        AreaMark(x: .value("Tenor", p.tenor),
                                 yStart: .value("Floor", floor), yEnd: .value("Rate", p.rate * 100))
                            .foregroundStyle(.linearGradient(
                                colors: [Theme.accent.opacity(0.30), Theme.accent.opacity(0.02)],
                                startPoint: .top, endPoint: .bottom))
                            .interpolationMethod(.monotone)
                        LineMark(x: .value("Tenor", p.tenor), y: .value("Rate", p.rate * 100))
                            .foregroundStyle(Theme.accent)
                            .lineStyle(StrokeStyle(lineWidth: 2.5))
                            .interpolationMethod(.monotone)
                        PointMark(x: .value("Tenor", p.tenor), y: .value("Rate", p.rate * 100))
                            .foregroundStyle(Theme.accent)
                            .symbolSize(28)
                    }
                    .chartXAxisLabel("Tenor (years)")
                    .chartYAxisLabel("Zero rate (%)")
                    .chartYScale(domain: floor...(hi + pad))
                    .frame(height: 240)
                }
            }
        }
    }

    private func quoteTable(_ title: String, icon: String, movers: [Mover]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle(title, icon: icon)
                ForEach(movers) { m in
                    HStack {
                        Text(m.secid).font(.system(size: 12, weight: .medium)).frame(width: 76, alignment: .leading)
                        Spacer()
                        Text(Fmt.number(m.last, digits: 2)).font(.system(size: 12)).monospacedDigit().foregroundStyle(.secondary)
                        Text(Fmt.signedPercent(m.chgPct))
                            .font(.system(size: 12, weight: .semibold)).monospacedDigit()
                            .foregroundStyle(Theme.trendColor(m.chgPct))
                            .frame(width: 66, alignment: .trailing)
                    }
                }
            }
        }
    }

    private func mapCard(_ title: String, icon: String, rows: [(String, String)]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle(title, icon: icon)
                ForEach(rows, id: \.0) { k, v in KeyValueRow(key: k, value: v) }
            }
        }
    }
}
