import SwiftUI
import Charts
import Observation

/// Market Data = a data browser. Pick a snapshot date, choose a data group
/// (curves / fx / equities / bonds / commodities / vols / dividends) and view
/// everything as scrollable tables; curves also render with their tenor nodes
/// marked and a points table.
@MainActor
@Observable
final class MarketBrowserViewModel {
    struct SectionItem: Identifiable { let id: String; let label: String }

    var snapshots: [SnapshotInfo] = []
    var snapshotID = ""
    var sections: [SectionItem] = []
    var section = "curves"

    var catalog: CatalogResponse?
    var board = ""
    var sort: String?
    var sortDesc = false
    var search = ""

    var curves: [CurveSeries] = []
    var selectedCurveID = ""

    // History (5y backfill store) — snapshot-independent series.
    var tsCatalog: TSCatalog?
    var tsGroup = "indices"
    var tsSeriesID = ""
    var tsData: TSSeriesData?
    var tsYears = 5                 // lookback window; 0 = all

    var isLoading = false
    var serverDown = false

    private let client = BridgeClient()

    var boards: [String] { catalog?.boards ?? [] }
    var selectedCurve: CurveSeries? { curves.first { $0.id == selectedCurveID } }

    var tsGroupSeries: [TSSeriesInfo] {
        tsCatalog?.groups.first { $0.id == tsGroup }?.series ?? []
    }

    /// Points within the selected lookback window (client-side filter).
    var tsPoints: [TSPoint] {
        guard let pts = tsData?.points, tsYears > 0 else { return tsData?.points ?? [] }
        let cutoff = Calendar.current.date(byAdding: .year, value: -tsYears, to: Date()) ?? .distantPast
        let key = MarketBrowserViewModel.isoDay.string(from: cutoff)
        return pts.filter { $0.date >= key }
    }

    static let isoDay: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX"); return f
    }()

    func start() async {
        do {
            let resp = try await client.snapshots()
            snapshots = resp.snapshots
            if snapshotID.isEmpty { snapshotID = resp.active }
            serverDown = false
        } catch {
            serverDown = true
            return
        }
        tsCatalog = try? await client.timeseriesCatalog()
        await loadSnapshot()
    }

    func loadSnapshot() async {
        isLoading = true
        let cats = (try? await client.catalogCategories(snapshotID: snapshotID)) ?? []
        curves = (try? await client.marketCurves(snapshotID: snapshotID))?.curves ?? []
        var secs: [SectionItem] = []
        if !curves.isEmpty { secs.append(.init(id: "curves", label: "Curves")) }
        secs += cats.map { .init(id: $0.id, label: $0.label) }
        if let ts = tsCatalog, !ts.groups.isEmpty { secs.append(.init(id: "history", label: "History")) }
        sections = secs
        if !secs.contains(where: { $0.id == section }) { section = secs.first?.id ?? "curves" }
        if selectedCurveID.isEmpty || !curves.contains(where: { $0.id == selectedCurveID }) {
            selectedCurveID = curves.first(where: { $0.id == "GCURVE_RUB" })?.id ?? curves.first?.id ?? ""
        }
        if tsSeriesID.isEmpty { ensureTSSelection() }
        isLoading = false
        if section == "history" { await loadTS() } else { await loadSection() }
    }

    private func ensureTSSelection() {
        guard let ts = tsCatalog, !ts.groups.isEmpty else { return }
        if !ts.groups.contains(where: { $0.id == tsGroup }) { tsGroup = ts.groups.first!.id }
        if tsSeriesID.isEmpty || !tsGroupSeries.contains(where: { $0.id == tsSeriesID }) {
            tsSeriesID = tsGroupSeries.first?.id ?? ""
        }
    }

    func changeTSGroup(_ id: String) {
        tsGroup = id
        tsSeriesID = tsGroupSeries.first?.id ?? ""
        Task { await loadTS() }
    }

    func changeTSSeries(_ id: String) { tsSeriesID = id; Task { await loadTS() } }

    func loadTS() async {
        guard !tsSeriesID.isEmpty else { tsData = nil; return }
        isLoading = true
        tsData = try? await client.timeseries(factorID: tsSeriesID)
        isLoading = false
    }

    func loadSection() async {
        guard section != "curves", section != "history" else { return }
        isLoading = true
        catalog = try? await client.catalog(section, search: search.isEmpty ? nil : search,
                                            board: board.isEmpty ? nil : board,
                                            sort: sort, desc: sortDesc, snapshotID: snapshotID)
        isLoading = false
    }

    func changeSnapshot(_ id: String) { snapshotID = id; Task { await loadSnapshot() } }
    func changeSection(_ id: String) {
        section = id; board = ""; sort = nil; sortDesc = false; search = ""
        catalog = nil
        if id == "history" {
            ensureTSSelection()
            Task { await loadTS() }
        } else {
            Task { await loadSection() }
        }
    }
    func toggleSort(_ key: String) {
        if sort == key { sortDesc.toggle() } else { sort = key; sortDesc = false }
        Task { await loadSection() }
    }
}

/// Per-category MarketEntityVM cache: keeps the loaded list, selection and chart
/// state alive across sub-tab switches (plain holder — not observable, mutated
/// lazily from body without invalidation loops).
@MainActor
final class EntityVMCache {
    private var vms: [String: MarketEntityVM] = [:]

    func vm(for category: String) -> MarketEntityVM {
        if let vm = vms[category] { return vm }
        let vm = MarketEntityVM(category: category)
        vms[category] = vm
        return vm
    }
}

struct MarketScreen: View {
    @State private var vm = MarketBrowserViewModel()
    @State private var group = "overview"
    @State private var instrument = "bonds"
    @State private var curveType = "rates"
    @State private var entityVMs = EntityVMCache()
    // global search (C1)
    @State private var searchText = ""
    @State private var searchHits: [SearchHit] = []
    @State private var searchTask: Task<Void, Never>?
    @State private var headerMeta: MDOverview?
    private let client = BridgeClient()

    // Doc structure: Market Data is a market-data showcase grouped as
    // Overview · Instruments · Curves · Volatility · History (control/quality
    // lives in the separate Data Controls section).
    private let groups: [(String, String)] = [
        ("overview", "Overview"), ("instruments", "Instruments"),
        ("curves", "Curves"), ("volatility", "Volatility"), ("history", "History"),
    ]
    private let instruments: [(String, String)] = [
        ("bonds", "Bonds"), ("equities", "Equities"), ("futures", "Futures"),
        ("options", "Options"), ("indices", "Indices"), ("fx", "FX"),
        ("commodities", "Commodities"),
    ]

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            content
        }
        .navigationTitle("Market Data")
        .task {
            if vm.snapshots.isEmpty { await vm.start() }
            headerMeta = try? await client.mdOverview()
        }
        .onChange(of: group) { _, g in if g == "history" { vm.changeSection("history") } }
        .onChange(of: searchText) { _, q in scheduleSearch(q) }
        .overlay(alignment: .topLeading) { searchResults }
    }

    // MARK: global search (C1)

    private func scheduleSearch(_ q: String) {
        searchTask?.cancel()
        let query = q.trimmingCharacters(in: .whitespaces)
        guard query.count >= 2 else { searchHits = []; return }
        searchTask = Task {
            try? await Task.sleep(for: .milliseconds(250))          // debounce
            guard !Task.isCancelled else { return }
            let hits = (try? await client.mdSearch(query))?.results ?? []
            guard !Task.isCancelled, searchText.trimmingCharacters(in: .whitespaces) == query else { return }
            searchHits = hits
        }
    }

    @ViewBuilder
    private var searchResults: some View {
        if !searchHits.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(searchHits.prefix(10)) { hit in
                    Button { open(hit) } label: {
                        HStack(spacing: Theme.s2) {
                            Text(categoryLabel(hit.category)).font(.system(size: 9, weight: .semibold))
                                .foregroundStyle(Theme.accent)
                                .padding(.horizontal, 5).padding(.vertical, 2)
                                .background(Theme.accent.opacity(0.12), in: Capsule())
                                .frame(width: 86, alignment: .leading)
                            VStack(alignment: .leading, spacing: 0) {
                                Text(hit.issuerRu ?? hit.secid).font(.system(size: 12, weight: .medium)).lineLimit(1)
                                Text(hit.isin ?? hit.secid).font(.system(size: 9)).foregroundStyle(.tertiary)
                            }
                            Spacer()
                            if let l = hit.last {
                                Text(Fmt.number(l, digits: 2)).font(.system(size: 12, weight: .semibold)).monospacedDigit()
                            }
                            if let c = hit.changePct {
                                Text(Fmt.signedPercent(c, digits: 2)).font(.system(size: 10)).monospacedDigit()
                                    .foregroundStyle(c >= 0 ? Theme.positive : Theme.negative)
                            }
                        }
                        .padding(.horizontal, Theme.s3).padding(.vertical, 6).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    Divider().opacity(0.25)
                }
            }
            .frame(width: 430)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.gray.opacity(0.25)))
            .padding(.leading, Theme.s5)
            .padding(.top, 44)
            .shadow(radius: 14)
        }
    }

    private func categoryLabel(_ cat: String?) -> String {
        switch cat {
        case "bonds": "Облигация"; case "equities": "Акция"; case "futures": "Фьючерс"
        case "options": "Опцион"; case "indices": "Индекс"; case "fx": "Валюта"
        default: cat ?? "?"
        }
    }

    /// Jump to the instrument from a search hit (or Overview's recents).
    private func open(_ hit: SearchHit) {
        searchText = ""
        searchHits = []
        guard let cat = hit.category else { return }
        instrument = cat
        group = "instruments"
        let vm = entityVMs.vm(for: cat)
        Task { await vm.select(hit.secid) }
    }

    private var identityLine: String {
        var parts: [String] = []
        if let s = headerMeta?.source { parts.append(s) }
        if let a = headerMeta?.asOf { parts.append("данные на \(a)") }
        else if let s = vm.snapshots.first(where: { $0.active }) { parts.append("данные на \(s.valuationDate)") }
        if let u = headerMeta?.updated { parts.append("обновлено \(u)") }
        return parts.joined(separator: " · ")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: Theme.s3) {
                HStack(spacing: 4) {
                    Image(systemName: "magnifyingglass").font(.system(size: 10)).foregroundStyle(.tertiary)
                    TextField("Поиск: тикер · ISIN · эмитент", text: $searchText)
                        .textFieldStyle(.plain).font(.system(size: 12))
                }
                .padding(.horizontal, Theme.s2).padding(.vertical, 4)
                .background(Color.gray.opacity(0.12), in: RoundedRectangle(cornerRadius: 7))
                .frame(maxWidth: 280)
                Spacer()
                Text(identityLine).font(.caption2).foregroundStyle(.tertiary)
            }
            Picker("Group", selection: $group) {
                ForEach(groups, id: \.0) { Text($0.1).tag($0.0) }
            }
            .pickerStyle(.segmented).labelsHidden()
            if group == "instruments" {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: Theme.s2) {
                        ForEach(instruments, id: \.0) { item in
                            let on = instrument == item.0
                            Button { instrument = item.0 } label: {
                                Text(item.1)
                                    .font(.system(size: 12, weight: on ? .semibold : .regular))
                                    .foregroundStyle(on ? Theme.accent : .secondary)
                                    .padding(.horizontal, Theme.s3).padding(.vertical, 5)
                                    .background(on ? Theme.accent.opacity(0.16) : Color.gray.opacity(0.12),
                                                in: RoundedRectangle(cornerRadius: 8))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
        .padding(.horizontal, Theme.s5).padding(.top, Theme.s3).padding(.bottom, Theme.s3)
    }

    @ViewBuilder
    private var content: some View {
        switch group {
        case "overview":
            OverviewView(onSelect: handleOverviewSelect)
        case "instruments":
            // VMs are cached per category: switching sub-tabs re-uses the loaded
            // list/selection instead of refetching ~700KB (audit A4). The .id keeps
            // view identity per category so @State re-binds to the cached VM.
            MarketEntityView(vm: entityVMs.vm(for: instrument)).id(instrument)
        case "curves":
            ScreenScaffold {
                if vm.serverDown {
                    ContentUnavailableView("Bridge offline", systemImage: "bolt.horizontal.circle").frame(height: 200)
                } else {
                    curvesSection
                }
            }
        case "volatility":
            VolSurfaceView()
        case "history":
            ScreenScaffold {
                if vm.serverDown {
                    ContentUnavailableView("Bridge offline", systemImage: "bolt.horizontal.circle").frame(height: 200)
                } else {
                    historySection
                }
            }
        default:
            EmptyView()
        }
    }

    private func handleOverviewSelect(_ key: String) {
        switch key {
        case "curves": group = "curves"
        case "vols":   group = "volatility"
        case "bonds", "equities", "futures", "options", "indices", "fx", "commodities":
            instrument = key; group = "instruments"
        default: break
        }
    }

    // MARK: curves

    // Classify the snapshot's curves into the doc's families (Rates / FX Forwards
    // / Inflation / Credit / Funding) by id, so Curves gets a sub-tab strip.
    private let curveTypes: [(String, String)] = [
        ("rates", "Ставки"), ("fxfwd", "FX-форварды"), ("inflation", "Инфляция"),
        ("credit", "Кредит"), ("funding", "Фондирование"),
    ]

    private func curveTypeOf(_ id: String) -> String {
        let u = id.uppercased()
        if u.contains("FXFWD") { return "fxfwd" }
        if u.contains("REALCURVE") || u.contains("OFZIN") || u.contains("INFL") || u.contains("CPI") || u.contains("LINKER") { return "inflation" }
        if u.contains("CORP") || u.contains("CDS") || u.contains("SPREAD") || u.contains("RATING") || u.contains("ISSUER") { return "credit" }
        if u.contains("FUNDING") || u.contains("REPO") || u.contains("COLLAT") || u.hasPrefix("TP_") { return "funding" }
        return "rates"
    }

    private var presentCurveTypes: [(String, String)] {
        let present = Set(vm.curves.map { curveTypeOf($0.id) })
        return curveTypes.filter { present.contains($0.0) }
    }

    private func curvesOfType(_ t: String) -> [CurveSeries] {
        vm.curves.filter { curveTypeOf($0.id) == t }
    }

    @ViewBuilder
    private var curvesSection: some View {
        if presentCurveTypes.count > 1 {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Theme.s2) {
                    ForEach(presentCurveTypes, id: \.0) { t in
                        let on = curveType == t.0
                        Button {
                            curveType = t.0
                            if let first = curvesOfType(t.0).first { vm.selectedCurveID = first.id }
                        } label: {
                            Text(t.1).font(.system(size: 12, weight: on ? .semibold : .regular))
                                .foregroundStyle(on ? Theme.accent : .secondary)
                                .padding(.horizontal, Theme.s3).padding(.vertical, 5)
                                .background(on ? Theme.accent.opacity(0.16) : Color.gray.opacity(0.12),
                                            in: RoundedRectangle(cornerRadius: 8))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        HStack {
            Picker("Curve", selection: $vm.selectedCurveID) {
                ForEach(curvesOfType(curveType)) { Text($0.label).tag($0.id) }
            }
            .labelsHidden().fixedSize()
            Spacer()
            if let c = vm.selectedCurve { Text("\(c.points.count) nodes").font(.caption).foregroundStyle(.tertiary) }
        }
        if let c = vm.selectedCurve {
            curveChart(c)
            curveTable(c)
        } else {
            Text("No curve data for this snapshot").font(.caption).foregroundStyle(.secondary)
        }
    }

    private func curveChart(_ c: CurveSeries) -> some View {
        let zs = c.points.compactMap { $0.zero }.map { $0 * 100 }
        let lo = zs.min() ?? 0, hi = zs.max() ?? 1
        let pad = max((hi - lo) * 0.12, 0.2)
        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("\(c.label) · zero curve", icon: "chart.xyaxis.line")
                Chart(c.points) { p in
                    if let z = p.zero {
                        AreaMark(x: .value("Tenor", p.tenor),
                                 yStart: .value("Floor", lo - pad), yEnd: .value("Zero", z * 100))
                            .foregroundStyle(.linearGradient(colors: [Theme.accent.opacity(0.22), Theme.accent.opacity(0.02)],
                                                             startPoint: .top, endPoint: .bottom))
                            .interpolationMethod(.monotone)
                        LineMark(x: .value("Tenor", p.tenor), y: .value("Zero", z * 100))
                            .foregroundStyle(Theme.accent).lineStyle(StrokeStyle(lineWidth: 2.5))
                            .interpolationMethod(.monotone)
                        PointMark(x: .value("Tenor", p.tenor), y: .value("Zero", z * 100))
                            .foregroundStyle(Theme.accent).symbolSize(34)
                    }
                }
                .chartYScale(domain: (lo - pad)...(hi + pad))
                .chartXAxis {
                    AxisMarks(values: tenorAxisValues(c.points.map(\.tenor))) { value in
                        AxisGridLine()
                        AxisValueLabel {
                            if let y = value.as(Double.self) { Text(Fmt.tenor(y)) }
                        }
                    }
                }
                .chartXAxisLabel("Tenor").chartYAxisLabel("Zero rate (%)")
                .frame(height: 260)
            }
        }
    }

    /// Greedily thin node tenors so classic labels never overlap on a linear
    /// axis (short-end money-market nodes cluster near zero). Always keeps the
    /// first and last node.
    private func tenorAxisValues(_ tenors: [Double]) -> [Double] {
        let sorted = tenors.sorted()
        guard let lo = sorted.first, let hi = sorted.last, hi > lo else { return sorted }
        let minGap = (hi - lo) * 0.06
        var out: [Double] = []
        for t in sorted where out.isEmpty || t - out[out.count - 1] >= minGap {
            out.append(t)
        }
        if out.last != hi { out.append(hi) }
        return out
    }

    private func curveTable(_ c: CurveSeries) -> some View {
        GlassCard(padding: Theme.s2) {
            VStack(spacing: 0) {
                HStack(spacing: Theme.s2) {
                    tableHead("Tenor"); tableHead("Zero rate"); tableHead("Discount factor")
                }
                .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
                Divider()
                ForEach(c.points) { p in
                    HStack(spacing: Theme.s2) {
                        cell(Fmt.tenor(p.tenor), weight: .medium, align: .leading)
                        cell(p.zero.map { Fmt.percent($0 * 100, digits: 3) } ?? "—")
                        cell(p.discount.map { Fmt.number($0, digits: 6) } ?? "—")
                    }
                    .padding(.horizontal, Theme.s2).padding(.vertical, 4)
                    Divider().opacity(0.3)
                }
            }
        }
    }

    // MARK: history (5y backfill store)

    @ViewBuilder
    private var historySection: some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            if let cat = vm.tsCatalog, cat.groups.count > 1 {
                Picker("Group", selection: Binding(get: { vm.tsGroup }, set: { vm.changeTSGroup($0) })) {
                    ForEach(cat.groups) { Text($0.label).tag($0.id) }
                }
                .pickerStyle(.segmented).labelsHidden()
            }
            HStack(spacing: Theme.s3) {
                Picker("Series", selection: Binding(get: { vm.tsSeriesID }, set: { vm.changeTSSeries($0) })) {
                    ForEach(vm.tsGroupSeries) { Text($0.label).tag($0.id) }
                }
                .labelsHidden().fixedSize()
                Spacer()
                Picker("Period", selection: $vm.tsYears) {
                    Text("1Y").tag(1); Text("3Y").tag(3); Text("5Y").tag(5); Text("All").tag(0)
                }
                .pickerStyle(.segmented).labelsHidden().fixedSize()
                if vm.isLoading { ProgressView().controlSize(.small) }
                if let d = vm.tsData { Text("\(vm.tsPoints.count) pts").font(.caption).foregroundStyle(.tertiary).help(d.factorID) }
            }
        }
        if let d = vm.tsData, !vm.tsPoints.isEmpty {
            historyChart(d, points: vm.tsPoints)
            historyTable(d, points: vm.tsPoints)
        } else if !vm.isLoading {
            Text("No history for this series").font(.caption).foregroundStyle(.secondary).frame(height: 120)
        }
    }

    private func historyChart(_ d: TSSeriesData, points: [TSPoint]) -> some View {
        let scale = d.isRate ? 100.0 : 1.0
        let ys = points.map { $0.value * scale }
        let lo = ys.min() ?? 0, hi = ys.max() ?? 1
        let pad = max((hi - lo) * 0.12, abs(hi) * 0.02 + 0.001)
        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("\(d.label) · history", icon: "chart.xyaxis.line")
                Chart(points) { p in
                    AreaMark(x: .value("Date", p.dateValue),
                             yStart: .value("Floor", lo - pad), yEnd: .value("Value", p.value * scale))
                        .foregroundStyle(.linearGradient(colors: [Theme.accent.opacity(0.18), Theme.accent.opacity(0.02)],
                                                         startPoint: .top, endPoint: .bottom))
                        .interpolationMethod(.monotone)
                    LineMark(x: .value("Date", p.dateValue), y: .value("Value", p.value * scale))
                        .foregroundStyle(Theme.accent).lineStyle(StrokeStyle(lineWidth: 1.8))
                        .interpolationMethod(.monotone)
                }
                .chartYScale(domain: (lo - pad)...(hi + pad))
                .chartYAxisLabel(d.isRate ? "Rate (%)" : "Level")
                .frame(height: 280)
            }
        }
    }

    private func historyTable(_ d: TSSeriesData, points: [TSPoint]) -> some View {
        GlassCard(padding: Theme.s2) {
            VStack(spacing: 0) {
                HStack(spacing: Theme.s2) {
                    tableHead("Date"); tableHead(d.isRate ? "Rate" : "Value")
                }
                .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
                Divider()
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(Array(points.reversed())) { p in
                            HStack(spacing: Theme.s2) {
                                cell(p.date, weight: .medium, align: .leading)
                                cell(d.isRate ? Fmt.percent(p.value * 100, digits: 2) : Fmt.number(p.value, digits: 2))
                            }
                            .padding(.horizontal, Theme.s2).padding(.vertical, 4)
                            Divider().opacity(0.3)
                        }
                    }
                }
                .frame(height: 280)
            }
        }
    }

    private func tableHead(_ t: String) -> some View {
        Text(t.uppercased()).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func cell(_ t: String, weight: Font.Weight = .regular, align: Alignment = .trailing) -> some View {
        Text(t).font(.system(size: 12, weight: weight)).monospacedDigit().lineLimit(1)
            .frame(maxWidth: .infinity, alignment: align)
    }
}

extension TSPoint {
    private static let parser: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX"); return f
    }()
    var dateValue: Date { Self.parser.date(from: date) ?? Date() }
}
