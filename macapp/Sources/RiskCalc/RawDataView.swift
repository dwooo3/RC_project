import SwiftUI
import Observation

// MARK: - Raw table browser

@MainActor
@Observable
final class RawDataVM {
    var tables: [RawTableInfo] = []
    var selected = ""
    var data: RawTable?
    var loading = false
    var serverDown = false
    private let client = BridgeClient()

    func start() async {
        do {
            tables = try await client.rawTables().tables
            serverDown = false
        } catch { serverDown = true; return }
        if selected.isEmpty { selected = tables.first?.name ?? "" }
        await load()
    }

    func select(_ name: String) { selected = name; Task { await load() } }

    func load() async {
        guard !selected.isEmpty else { return }
        loading = true
        data = try? await client.rawTable(selected, limit: 200)
        loading = false
    }
}

struct RawDataView: View {
    @State private var vm = RawDataVM()

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            if vm.serverDown {
                ContentUnavailableView("Bridge offline", systemImage: "bolt.horizontal.circle").frame(maxHeight: .infinity)
            } else {
                HStack(spacing: Theme.s3) {
                    Picker("Таблица", selection: Binding(get: { vm.selected }, set: { vm.select($0) })) {
                        ForEach(vm.tables) { Text("\($0.name) (\($0.rows))").tag($0.name) }
                    }
                    .labelsHidden().fixedSize()
                    if vm.loading { ProgressView().controlSize(.small) }
                    Spacer()
                    if let d = vm.data {
                        Text("показано \(d.shown) из \(d.count)").font(.caption).foregroundStyle(.tertiary)
                    }
                }
                if let d = vm.data, !d.columns.isEmpty {
                    grid(d)
                } else if !vm.loading {
                    Text("Нет данных").font(.caption).foregroundStyle(.secondary).frame(maxHeight: .infinity)
                }
            }
        }
        .padding(Theme.s5)
        .task { if vm.tables.isEmpty { await vm.start() } }
    }

    private func grid(_ d: RawTable) -> some View {
        ScrollView([.horizontal, .vertical]) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 0) {
                    ForEach(d.columns, id: \.self) { c in gcell(c, header: true) }
                }
                Divider()
                ForEach(Array(d.rows.enumerated()), id: \.offset) { _, row in
                    HStack(spacing: 0) {
                        ForEach(Array(d.columns.indices), id: \.self) { j in
                            gcell(j < row.count ? row[j] : "")
                        }
                    }
                    Divider().opacity(0.2)
                }
            }
        }
        .background(Color(nsColor: .textBackgroundColor).opacity(0.25), in: RoundedRectangle(cornerRadius: 8))
    }

    private func gcell(_ t: String, header: Bool = false) -> some View {
        Text(t.isEmpty ? "—" : t)
            .font(.system(size: 11, weight: header ? .semibold : .regular, design: .monospaced))
            .foregroundStyle(header ? .secondary : .primary)
            .lineLimit(1).truncationMode(.middle)
            .frame(width: 150, alignment: .leading)
            .padding(.horizontal, Theme.s2).padding(.vertical, 5)
    }
}

// MARK: - Data dictionary

@MainActor
@Observable
final class DataDictionaryVM {
    var tables: [DictTable] = []
    var serverDown = false
    private let client = BridgeClient()

    func load() async {
        do { tables = try await client.dataDictionary().tables; serverDown = false }
        catch { serverDown = true }
    }
}

struct DataDictionaryView: View {
    @State private var vm = DataDictionaryVM()

    var body: some View {
        ScreenScaffold {
            if vm.serverDown {
                ContentUnavailableView("Bridge offline", systemImage: "bolt.horizontal.circle").frame(height: 200)
            } else {
                ForEach(vm.tables) { t in
                    GlassCard(padding: Theme.s2) {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(t.table).font(.system(size: 13, weight: .semibold, design: .monospaced))
                                .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
                            Divider()
                            ForEach(t.fields) { f in
                                HStack(spacing: Theme.s2) {
                                    Text(f.name).font(.system(size: 11, weight: .medium, design: .monospaced))
                                        .frame(width: 180, alignment: .leading)
                                    Text(f.type).font(.system(size: 10)).foregroundStyle(.tertiary)
                                        .frame(width: 70, alignment: .leading)
                                    Text(f.meaning).font(.system(size: 11)).foregroundStyle(.secondary)
                                    Spacer()
                                }
                                .padding(.horizontal, Theme.s2).padding(.vertical, 3)
                                Divider().opacity(0.2)
                            }
                        }
                    }
                }
            }
        }
        .task { if vm.tables.isEmpty { await vm.load() } }
    }
}
