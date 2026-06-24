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

    var isLoading = false
    var serverDown = false

    private let client = BridgeClient()

    var boards: [String] { catalog?.boards ?? [] }
    var selectedCurve: CurveSeries? { curves.first { $0.id == selectedCurveID } }

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
        await loadSnapshot()
    }

    func loadSnapshot() async {
        isLoading = true
        let cats = (try? await client.catalogCategories(snapshotID: snapshotID)) ?? []
        curves = (try? await client.marketCurves(snapshotID: snapshotID))?.curves ?? []
        var secs: [SectionItem] = []
        if !curves.isEmpty { secs.append(.init(id: "curves", label: "Curves")) }
        secs += cats.map { .init(id: $0.id, label: $0.label) }
        sections = secs
        if !secs.contains(where: { $0.id == section }) { section = secs.first?.id ?? "curves" }
        if selectedCurveID.isEmpty || !curves.contains(where: { $0.id == selectedCurveID }) {
            selectedCurveID = curves.first(where: { $0.id == "GCURVE_RUB" })?.id ?? curves.first?.id ?? ""
        }
        isLoading = false
        await loadSection()
    }

    func loadSection() async {
        guard section != "curves" else { return }
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
        Task { await loadSection() }
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
