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
    // Mode (Обзор/Инструменты/…) is driven by the nested sidebar items in RootView.
    @Binding var group: String
    var model: AppModel                       // global search open-requests
    @State private var vm = MarketBrowserViewModel()
    // Third-level selections persist across launches (doc §1).
    @SceneStorage("mdInstrument") private var instrument = "bonds"
    @SceneStorage("mdCurveType") private var curveType = "rates"
    @State private var entityVMs = EntityVMCache()
    @State private var headerMeta: MDOverview?
    private let client = BridgeClient()

    // Asset-class tabs (third level) shown in the work-area header for the
    // Инструменты mode. The mode set itself lives in the sidebar (RootView).
    private let instruments: [(String, String)] = [
        ("bonds", "Облигации"), ("equities", "Акции"), ("funds", "ПИФы"),
        ("futures", "Фьючерсы"), ("options", "Опционы"), ("indices", "Индексы"),
        ("fx", "Валюта"), ("commodities", "Товары"),
    ]

    var body: some View {
        VStack(spacing: 0) {
            workAreaHeader
            content
        }
        .task {
            if vm.snapshots.isEmpty { await vm.start() }
            headerMeta = try? await client.mdOverview()
        }
        .onChange(of: group) { _, g in if g == "history" { vm.changeSection("history") } }
        // Global search / recents jump here.
        .onChange(of: model.openRequest) { _, req in
            if let req { openInstrument(req.category, req.secid); model.openRequest = nil }
        }
        .task(id: model.openRequest?.id) {
            if let req = model.openRequest { openInstrument(req.category, req.secid); model.openRequest = nil }
        }
    }

    // MARK: work-area header (identity + third-level asset-class tabs)

    private var workAreaHeader: some View {
        // One tight row right under the toolbar: tabs left, identity right —
        // no empty band between the title pill and the tabs panel.
        HStack(spacing: Theme.s3) {
            if group == "instruments" {
                ScrollView(.horizontal, showsIndicators: false) {
                    SegmentedBar(items: instruments, selection: $instrument, compact: true)
                        .fixedSize()
                }
            }
            Spacer(minLength: 0)
            Text(identityLine).font(Typography.caption).foregroundStyle(.secondary)
        }
        .padding(.horizontal, Theme.s4).padding(.top, Theme.s2).padding(.bottom, Theme.s2)
    }

    private func openInstrument(_ category: String, _ secid: String) {
        instrument = category
        group = "instruments"
        let vm = entityVMs.vm(for: category)
        Task { await vm.select(secid) }
    }

    private var identityLine: String {
        var parts: [String] = []
        if let s = headerMeta?.source { parts.append(s) }
        if let a = headerMeta?.asOf { parts.append("данные на \(a)") }
        else if let s = vm.snapshots.first(where: { $0.active }) { parts.append("данные на \(s.valuationDate)") }
        if let u = headerMeta?.updated { parts.append("обновлено \(u)") }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder
    private var content: some View {
        switch group {
        case "overview":
            OverviewView(onSelect: handleOverviewSelect, onOpen: openInstrument)
        case "instruments":
            // VMs are cached per category: switching sub-tabs re-uses the loaded
            // list/selection instead of refetching ~700KB (audit A4). The .id keeps
            // view identity per category so @State re-binds to the cached VM.
            // Leading indent matches the asset-class tabs above (Theme.s4).
            MarketEntityView(vm: entityVMs.vm(for: instrument)).id(instrument)
                .padding(.leading, Theme.s4)
        case "curves":
            ScreenScaffold {
                if vm.serverDown {
                    ContentUnavailableView("Мост недоступен", systemImage: "bolt.horizontal.circle").frame(height: 200)
                } else {
                    curvesSection
                }
            }
        case "volatility":
            VolSurfaceView()
        case "history":
            ScreenScaffold {
                if vm.serverDown {
                    ContentUnavailableView("Мост недоступен", systemImage: "bolt.horizontal.circle").frame(height: 200)
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
                SegmentedBar(
                    items: presentCurveTypes,
                    selection: Binding(get: { curveType }, set: { newType in
                        curveType = newType
                        if let first = curvesOfType(newType).first { vm.selectedCurveID = first.id }
                    }),
                    compact: true
                )
                .fixedSize()
            }
        }
        HStack {
            Picker("Curve", selection: $vm.selectedCurveID) {
                ForEach(curvesOfType(curveType)) { Text($0.label).tag($0.id) }
            }
            .labelsHidden().neutralControlTint().fixedSize()
            Spacer()
            if let c = vm.selectedCurve {
                Text("\(c.points.count) узлов").font(.caption).foregroundStyle(.tertiary)
                Button { exportCurve(c) } label: { Label("CSV", systemImage: "square.and.arrow.up") }
                    .buttonStyle(.borderless).controlSize(.small)
            }
        }
        if let c = vm.selectedCurve {
            curveChart(c)
            curveTable(c)
        } else {
            Text("Нет данных кривых в этом снапшоте").font(.caption).foregroundStyle(.secondary)
        }
    }

    private func exportCurve(_ c: CurveSeries) {
        CSVExport.save(suggestedName: "\(c.id)_curve",
                       header: ["tenor_years", "zero_rate_pct", "discount_factor"],
                       rows: c.points.map { p in
                           [String(p.tenor),
                            p.zero.map { String($0 * 100) } ?? "",
                            p.discount.map { String($0) } ?? ""]
                       })
    }

    private func curveChart(_ c: CurveSeries) -> some View {
        let zs = c.points.compactMap { $0.zero }.map { $0 * 100 }
        let lo = zs.min() ?? 0, hi = zs.max() ?? 1
        let pad = max((hi - lo) * 0.12, 0.2)
        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("\(c.label) · бескупонная кривая", icon: "chart.xyaxis.line")
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
                .chartXAxisLabel("Тенор").chartYAxisLabel("Бескупонная ставка (%)")
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
                    tableHead("Тенор"); tableHead("Бескупонная ставка", align: .trailing); tableHead("Дисконт-фактор", align: .trailing)
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
                ScrollView(.horizontal, showsIndicators: false) {
                    SegmentedBar(
                        items: cat.groups.map { ($0.id, $0.label) },
                        selection: Binding(get: { vm.tsGroup }, set: { vm.changeTSGroup($0) }),
                        compact: true
                    )
                    .fixedSize()
                }
            }
            HStack(spacing: Theme.s3) {
                Picker("Series", selection: Binding(get: { vm.tsSeriesID }, set: { vm.changeTSSeries($0) })) {
                    ForEach(vm.tsGroupSeries) { Text($0.label).tag($0.id) }
                }
                .labelsHidden().neutralControlTint().fixedSize()
                Spacer()
                SegmentedBar(items: [(1, "1Y"), (3, "3Y"), (5, "5Y"), (0, "Всё")],
                             selection: $vm.tsYears, compact: true)
                    .fixedSize()
                if vm.isLoading { ProgressView().controlSize(.small) }
                if let d = vm.tsData { Text("\(vm.tsPoints.count) точек").font(.caption).foregroundStyle(.tertiary).help(d.factorID) }
            }
        }
        if let d = vm.tsData, !vm.tsPoints.isEmpty {
            historyChart(d, points: vm.tsPoints)
            historyTable(d, points: vm.tsPoints)
        } else if !vm.isLoading {
            Text("Нет истории по этой серии").font(.caption).foregroundStyle(.secondary).frame(height: 120)
        }
    }

    private func historyChart(_ d: TSSeriesData, points: [TSPoint]) -> some View {
        let scale = d.isRate ? 100.0 : 1.0
        let ys = points.map { $0.value * scale }
        let lo = ys.min() ?? 0, hi = ys.max() ?? 1
        let pad = max((hi - lo) * 0.12, abs(hi) * 0.02 + 0.001)
        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("\(d.label) · история", icon: "chart.xyaxis.line")
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
                .chartYAxisLabel(d.isRate ? "Ставка (%)" : "Уровень")
                .frame(height: 280)
            }
        }
    }

    private func historyTable(_ d: TSSeriesData, points: [TSPoint]) -> some View {
        GlassCard(padding: Theme.s2) {
            VStack(spacing: 0) {
                HStack(spacing: Theme.s2) {
                    tableHead("Дата"); tableHead(d.isRate ? "Ставка" : "Значение", align: .trailing)
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

    private func tableHead(_ t: String, align: Alignment = .leading) -> some View {
        Text(t.uppercased()).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: align)
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
