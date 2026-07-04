import SwiftUI
import Charts
import Observation


/// Instrument specification + trade-history popup.
struct SpecSheet: View {
    let row: CatRow
    let category: String
    @Environment(\.dismiss) private var dismiss
    @State private var history: [HistoryPoint] = []
    @State private var loadingHistory = false
    @State private var historyError: String?
    @State private var timeframe: Timeframe = .day
    private let client = BridgeClient()

    private var supportsHistory: Bool { category == "bonds" || category == "equities" }
    private var candles: [Candle] { Candle.aggregate(history, timeframe) }
    private var hasYield: Bool { history.contains { $0.yld != nil } }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(row.id).font(.system(size: 16, weight: .bold))
                    Text("Instrument specification").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Done") { dismiss() }.keyboardShortcut(.defaultAction)
            }
            .padding(Theme.s4)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s4) {
                    if supportsHistory { historySection }
                    specSection
                }
                .padding(.vertical, Theme.s2)
            }
        }
        .frame(width: 600, height: 720)
        .task {
            guard supportsHistory else { return }
            loadingHistory = true
            do {
                let resp = try await client.history(category: category, secid: row.id, days: 365)
                history = resp.points
                historyError = resp.error
            } catch {
                historyError = error.localizedDescription
            }
            loadingHistory = false
        }
    }

    private var historySection: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack {
                Text("TRADE HISTORY").font(.system(size: 10, weight: .semibold))
                    .tracking(0.5).foregroundStyle(.secondary)
                if loadingHistory { ProgressView().controlSize(.mini) }
                Spacer()
                SegmentedBar(items: Timeframe.allCases.map { ($0, $0.rawValue) },
                             selection: $timeframe, compact: true)
                    .fixedSize()
            }
            .padding(.horizontal, Theme.s4)

            if candles.count > 1 {
                candleChart
                if hasYield { yieldChart }
                priceTable
            } else if !loadingHistory {
                Text(historyError ?? "No trade history available")
                    .font(.caption).foregroundStyle(.secondary).padding(.horizontal, Theme.s4)
            }
            Divider()
        }
    }

    private var candleChart: some View {
        let cs = candles
        let lo = cs.map(\.low).min() ?? 0
        let hi = cs.map(\.high).max() ?? 1
        let pad = max((hi - lo) * 0.06, hi * 0.002)
        let width = max(2.0, min(12.0, 340.0 / Double(cs.count)))
        return Chart(cs) { c in
            RuleMark(x: .value("Date", c.date),
                     yStart: .value("Low", c.low), yEnd: .value("High", c.high))
                .foregroundStyle(c.up ? Theme.positive : Theme.negative)
                .lineStyle(StrokeStyle(lineWidth: 1))
            RectangleMark(x: .value("Date", c.date),
                          yStart: .value("Open", c.open), yEnd: .value("Close", c.close),
                          width: .fixed(width))
                .foregroundStyle(c.up ? Theme.positive : Theme.negative)
        }
        .chartYScale(domain: (lo - pad)...(hi + pad))
        .frame(height: 200).padding(.horizontal, Theme.s3)
    }

    private var yieldChart: some View {
        let pts = history.filter { $0.yld != nil }
        let ys = pts.compactMap(\.yld)
        let lo = ys.min() ?? 0, hi = ys.max() ?? 1
        let pad = max((hi - lo) * 0.06, 0.01)
        return VStack(alignment: .leading, spacing: 2) {
            Text("YIELD (%)").font(.system(size: 9, weight: .semibold)).foregroundStyle(.tertiary)
                .padding(.horizontal, Theme.s4)
            Chart(pts) { p in
                LineMark(x: .value("Date", p.dateValue), y: .value("Yield", p.yld ?? 0))
                    .foregroundStyle(Theme.bucketColor("Rates")).interpolationMethod(.monotone)
            }
            .chartYScale(domain: (lo - pad)...(hi + pad))
            .frame(height: 90).padding(.horizontal, Theme.s3)
        }
    }

    private var priceTable: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("PRICE SERIES").font(.system(size: 9, weight: .semibold)).foregroundStyle(.tertiary)
                .padding(.horizontal, Theme.s4).padding(.top, Theme.s2)
            HStack(spacing: 0) {
                priceCell("Date", weight: .semibold, align: .leading)
                priceCell("O"); priceCell("H"); priceCell("L"); priceCell("C")
                priceCell("Vol")
            }
            .foregroundStyle(.secondary).padding(.horizontal, Theme.s4)
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(candles.reversed()) { c in
                        HStack(spacing: 0) {
                            priceCell(Self.dayFormatter.string(from: c.date), align: .leading)
                            priceCell(Fmt.number(c.open, digits: 2))
                            priceCell(Fmt.number(c.high, digits: 2))
                            priceCell(Fmt.number(c.low, digits: 2))
                            priceCell(Fmt.number(c.close, digits: 2), weight: .medium)
                            priceCell(Fmt.money(c.volume))
                        }
                        .padding(.horizontal, Theme.s4).padding(.vertical, 3)
                        Divider().opacity(0.3)
                    }
                }
            }
            .frame(height: 150)
        }
    }

    private func priceCell(_ text: String, weight: Font.Weight = .regular, align: Alignment = .trailing) -> some View {
        Text(text)
            .font(.system(size: 11, weight: weight)).monospacedDigit().lineLimit(1)
            .frame(maxWidth: .infinity, alignment: align)
    }

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX"); return f
    }()

    private var specSection: some View {
        VStack(spacing: 0) {
            ForEach(row.spec) { field in
                HStack {
                    Text(field.label).font(.system(size: 12)).foregroundStyle(.secondary)
                    Spacer()
                    Text(field.value).font(.system(size: 12, weight: .medium)).monospacedDigit()
                        .textSelection(.enabled)
                }
                .padding(.horizontal, Theme.s4).padding(.vertical, Theme.s2)
                Divider().opacity(0.4)
            }
        }
    }
}

extension CatRow: Identifiable {}

extension HistoryPoint {
    private static let parser: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()
    var dateValue: Date { Self.parser.date(from: date) ?? Date() }
}

/// Candle timeframe (daily base; week/month aggregate the daily series).
enum Timeframe: String, CaseIterable, Identifiable {
    case day = "1D", week = "1W", month = "1M"
    var id: String { rawValue }
}

/// An OHLC candle, aggregated from the daily trade-history series.
struct Candle: Identifiable {
    let date: Date
    let open, high, low, close, volume: Double
    var id: Date { date }
    var up: Bool { close >= open }

    static func aggregate(_ points: [HistoryPoint], _ tf: Timeframe) -> [Candle] {
        guard !points.isEmpty else { return [] }
        let cal = Calendar(identifier: .iso8601)
        func bucket(_ d: Date) -> Date {
            switch tf {
            case .day: return cal.startOfDay(for: d)
            case .week: return cal.dateInterval(of: .weekOfYear, for: d)?.start ?? d
            case .month: return cal.dateInterval(of: .month, for: d)?.start ?? d
            }
        }
        var order: [Date] = []
        var groups: [Date: [HistoryPoint]] = [:]
        for p in points.sorted(by: { $0.date < $1.date }) {
            let b = bucket(p.dateValue)
            if groups[b] == nil { order.append(b); groups[b] = [] }
            groups[b]?.append(p)
        }
        return order.map { b in
            let g = groups[b] ?? []
            let o = g.first?.open ?? g.first?.close ?? 0
            let c = g.last?.close ?? 0
            let hi = g.map { $0.high ?? $0.close }.max() ?? c
            let lo = g.map { $0.low ?? $0.close }.min() ?? c
            let v = g.compactMap { $0.volume }.reduce(0, +)
            return Candle(date: b, open: o, high: hi, low: lo, close: c, volume: v)
        }
    }
}
