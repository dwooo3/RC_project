import SwiftUI
import Charts
import Observation

@MainActor
@Observable
final class CatalogViewModel {
    var categories: [CatalogCategory] = []
    var category = "bonds"
    var search = ""
    var board = ""
    var sort: String?
    var sortDesc = false
    var boards: [String] = []
    var response: CatalogResponse?
    var isLoading = false
    var loadError: String?

    private let client = BridgeClient()

    func load() async {
        categories = (try? await client.catalogCategories()) ?? []
        if let first = categories.first, !categories.contains(where: { $0.id == category }) {
            category = first.id
        }
        await reload()
    }

    func reload() async {
        isLoading = true
        loadError = nil
        do {
            let resp = try await client.catalog(category, search: search.isEmpty ? nil : search,
                                                board: board.isEmpty ? nil : board,
                                                sort: sort, desc: sortDesc)
            response = resp
            boards = resp.boards ?? []
        } catch {
            loadError = error.localizedDescription
            response = nil
        }
        isLoading = false
    }

    func changeCategory(_ id: String) {
        category = id
        board = ""
        sort = nil
        sortDesc = false
        Task { await reload() }
    }

    func toggleSort(_ key: String) {
        if sort == key { sortDesc.toggle() } else { sort = key; sortDesc = false }
        Task { await reload() }
    }
}

/// Market-Data instrument catalog: category + board filters, sortable table, spec/history popup.
struct InstrumentCatalogView: View {
    @State private var vm = CatalogViewModel()
    @State private var specRow: CatRow?

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            HStack {
                BlockTitle("Instruments", icon: "tablecells")
                Spacer()
                if vm.isLoading { ProgressView().controlSize(.small) }
                if let n = vm.response?.rows.count { Text("\(n) shown").font(.system(size: 11)).foregroundStyle(.tertiary) }
            }
            filters
            if let err = vm.loadError {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.negative)
            }
            if let resp = vm.response, !resp.columns.isEmpty {
                GlassCard(padding: Theme.s2) {
                    VStack(spacing: 0) {
                        headerRow(resp.columns)
                        Divider()
                        ScrollView {
                            LazyVStack(spacing: 0) {
                                ForEach(Array(resp.rows.enumerated()), id: \.offset) { _, row in
                                    Button { specRow = row } label: { dataRow(row) }
                                        .buttonStyle(.plain)
                                    Divider().opacity(0.4)
                                }
                            }
                        }
                        .frame(height: 460)
                    }
                }
            }
        }
        .task { await vm.load() }
        .sheet(item: $specRow) { row in SpecSheet(row: row, category: vm.category) }
    }

    private var filters: some View {
        HStack(spacing: Theme.s3) {
            Picker("Category", selection: Binding(get: { vm.category }, set: { vm.changeCategory($0) })) {
                ForEach(vm.categories) { Text("\($0.label) (\($0.count))").tag($0.id) }
            }
            .labelsHidden().fixedSize()

            if !vm.boards.isEmpty {
                Picker("Board", selection: Binding(get: { vm.board }, set: { vm.board = $0; Task { await vm.reload() } })) {
                    Text("All boards").tag("")
                    ForEach(vm.boards, id: \.self) { Text($0).tag($0) }
                }
                .labelsHidden().fixedSize()
            }

            TextField("Search…", text: $vm.search)
                .textFieldStyle(.roundedBorder).frame(maxWidth: 260)
                .onSubmit { Task { await vm.reload() } }
            Spacer()
        }
    }

    private func headerRow(_ columns: [CatColumn]) -> some View {
        HStack(spacing: Theme.s2) {
            ForEach(columns) { col in
                Button { vm.toggleSort(col.key) } label: {
                    HStack(spacing: 3) {
                        Text(col.label.uppercased())
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(vm.sort == col.key ? Theme.accent : .secondary)
                        if vm.sort == col.key {
                            Image(systemName: vm.sortDesc ? "chevron.down" : "chevron.up")
                                .font(.system(size: 8, weight: .bold)).foregroundStyle(Theme.accent)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
    }

    private func dataRow(_ row: CatRow) -> some View {
        HStack(spacing: Theme.s2) {
            ForEach(Array(row.cells.enumerated()), id: \.offset) { idx, cell in
                Text(cell)
                    .font(.system(size: 12, weight: idx == 0 ? .medium : .regular))
                    .monospacedDigit().lineLimit(1)
                    .foregroundStyle(idx == 0 ? .primary : .secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.horizontal, Theme.s2).padding(.vertical, 6)
        .contentShape(Rectangle())
    }
}

/// Instrument specification + trade-history popup.
private struct SpecSheet: View {
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
                Picker("", selection: $timeframe) {
                    ForEach(Timeframe.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented).labelsHidden().fixedSize().controlSize(.small)
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
