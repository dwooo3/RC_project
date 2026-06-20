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
    private let client = BridgeClient()

    private var supportsHistory: Bool { category == "bonds" || category == "equities" }

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
        .frame(width: 480, height: 640)
        .task {
            guard supportsHistory else { return }
            loadingHistory = true
            do {
                let resp = try await client.history(category: category, secid: row.id, days: 180)
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
                Text("TRADE HISTORY · 180D").font(.system(size: 10, weight: .semibold))
                    .tracking(0.5).foregroundStyle(.secondary)
                Spacer()
                if loadingHistory { ProgressView().controlSize(.mini) }
            }
            .padding(.horizontal, Theme.s4)

            if history.count > 1 {
                Chart(history) { p in
                    AreaMark(x: .value("Date", p.dateValue), y: .value("Close", p.close))
                        .foregroundStyle(.linearGradient(colors: [Theme.accent.opacity(0.25), Theme.accent.opacity(0.02)],
                                                         startPoint: .top, endPoint: .bottom))
                        .interpolationMethod(.monotone)
                    LineMark(x: .value("Date", p.dateValue), y: .value("Close", p.close))
                        .foregroundStyle(Theme.accent).interpolationMethod(.monotone)
                }
                .chartYScale(domain: .automatic(includesZero: false))
                .frame(height: 150).padding(.horizontal, Theme.s3)

                if history.contains(where: { $0.yld != nil }) {
                    Text("YIELD (%)").font(.system(size: 9, weight: .semibold)).foregroundStyle(.tertiary)
                        .padding(.horizontal, Theme.s4)
                    Chart(history.filter { $0.yld != nil }) { p in
                        LineMark(x: .value("Date", p.dateValue), y: .value("Yield", p.yld ?? 0))
                            .foregroundStyle(Theme.bucketColor("Rates")).interpolationMethod(.monotone)
                    }
                    .chartYScale(domain: .automatic(includesZero: false))
                    .frame(height: 90).padding(.horizontal, Theme.s3)
                }
            } else if !loadingHistory {
                Text(historyError ?? "No trade history available")
                    .font(.caption).foregroundStyle(.secondary).padding(.horizontal, Theme.s4)
            }
            Divider()
        }
    }

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
