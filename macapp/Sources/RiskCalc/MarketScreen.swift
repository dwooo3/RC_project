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

struct MarketScreen: View {
    @State private var vm = MarketBrowserViewModel()
    @State private var specRow: CatRow?

    var body: some View {
        ScreenScaffold {
            PageHeader("Market Data", subtitle: "Browse all market data by snapshot date") {
                snapshotPicker
            }
            if vm.serverDown {
                ContentUnavailableView("Bridge offline", systemImage: "bolt.horizontal.circle")
                    .frame(height: 200)
            } else {
                sectionPicker
                if vm.section == "curves" {
                    curvesSection
                } else if vm.section == "history" {
                    historySection
                } else {
                    tableSection
                }
            }
        }
        .navigationTitle("Market Data")
        .task { if vm.snapshots.isEmpty { await vm.start() } }
        .sheet(item: $specRow) { row in SpecSheet(row: row, category: vm.section) }
    }

    // MARK: top controls

    private var snapshotPicker: some View {
        HStack(spacing: Theme.s2) {
            Image(systemName: "calendar").foregroundStyle(.secondary).font(.system(size: 12))
            Picker("Snapshot", selection: Binding(get: { vm.snapshotID }, set: { vm.changeSnapshot($0) })) {
                ForEach(vm.snapshots) { s in
                    Text("\(s.valuationDate)\(s.quality == "PARTIAL" ? "  ⚠ partial" : "")").tag(s.snapshotID)
                }
            }
            .labelsHidden().fixedSize()
        }
    }

    private var sectionPicker: some View {
        Picker("Section", selection: Binding(get: { vm.section }, set: { vm.changeSection($0) })) {
            ForEach(vm.sections) { Text($0.label).tag($0.id) }
        }
        .pickerStyle(.segmented).labelsHidden()
    }

    // MARK: curves

    @ViewBuilder
    private var curvesSection: some View {
        HStack {
            Picker("Curve", selection: $vm.selectedCurveID) {
                ForEach(vm.curves) { Text($0.label).tag($0.id) }
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
                .chartXAxisLabel("Tenor (years)").chartYAxisLabel("Zero rate (%)")
                .frame(height: 260)
            }
        }
    }

    private func curveTable(_ c: CurveSeries) -> some View {
        GlassCard(padding: Theme.s2) {
            VStack(spacing: 0) {
                HStack(spacing: Theme.s2) {
                    tableHead("Tenor (y)"); tableHead("Zero rate"); tableHead("Discount factor")
                }
                .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
                Divider()
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(c.points) { p in
                            HStack(spacing: Theme.s2) {
                                cell(Fmt.number(p.tenor, digits: p.tenor < 1 ? 3 : 2), weight: .medium, align: .leading)
                                cell(p.zero.map { Fmt.percent($0 * 100, digits: 3) } ?? "—")
                                cell(p.discount.map { Fmt.number($0, digits: 6) } ?? "—")
                            }
                            .padding(.horizontal, Theme.s2).padding(.vertical, 4)
                            Divider().opacity(0.3)
                        }
                    }
                }
                .frame(height: 240)
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

    // MARK: generic data table

    @ViewBuilder
    private var tableSection: some View {
        HStack(spacing: Theme.s3) {
            if !vm.boards.isEmpty {
                Picker("Filter", selection: Binding(get: { vm.board }, set: { vm.board = $0; Task { await vm.loadSection() } })) {
                    Text("All").tag("")
                    ForEach(vm.boards, id: \.self) { Text($0).tag($0) }
                }
                .labelsHidden().fixedSize()
            }
            TextField("Search…", text: $vm.search)
                .textFieldStyle(.roundedBorder).frame(maxWidth: 280)
                .onSubmit { Task { await vm.loadSection() } }
            Spacer()
            if vm.isLoading { ProgressView().controlSize(.small) }
            if let n = vm.catalog?.rows.count { Text("\(n) rows").font(.caption).foregroundStyle(.tertiary) }
        }
        if let resp = vm.catalog, !resp.columns.isEmpty {
            GlassCard(padding: Theme.s2) {
                VStack(spacing: 0) {
                    HStack(spacing: Theme.s2) {
                        ForEach(resp.columns) { col in
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
                                .frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
                    Divider()
                    ScrollView {
                        LazyVStack(spacing: 0) {
                            ForEach(Array(resp.rows.enumerated()), id: \.offset) { _, row in
                                Button { specRow = row } label: { dataRow(row) }.buttonStyle(.plain)
                                Divider().opacity(0.35)
                            }
                        }
                    }
                    .frame(height: 520)
                }
            }
        } else if !vm.isLoading {
            Text("No data in this group for the selected snapshot")
                .font(.caption).foregroundStyle(.secondary).frame(height: 120)
        }
    }

    private func dataRow(_ row: CatRow) -> some View {
        HStack(spacing: Theme.s2) {
            ForEach(Array(row.cells.enumerated()), id: \.offset) { idx, c in
                Text(c).font(.system(size: 12, weight: idx == 0 ? .medium : .regular))
                    .monospacedDigit().lineLimit(1)
                    .foregroundStyle(idx == 0 ? .primary : .secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.horizontal, Theme.s2).padding(.vertical, 5).contentShape(Rectangle())
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
