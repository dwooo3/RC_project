import SwiftUI
import Observation

/// Instrument-entity browser: master list (1/3) + TradingView-style detail (2/3).
/// Each row is an entity (issuer · ISIN · price · change); selecting one loads its
/// chart + day stats + key info, with a button to the full card.
@MainActor
@Observable
final class MarketEntityVM {
    let category: String
    var items: [MDListItem] = []
    var search = ""
    var selectedID: String?
    var entity: MDEntity?
    var bars: [MDBar] = []
    var range = "1Y"
    var loadingList = false
    var loadingDetail = false
    var serverDown = false

    private let client = BridgeClient()

    init(category: String) { self.category = category }

    var market: String { mdMarket(category) }

    var filtered: [MDListItem] {
        let q = search.lowercased().trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return items }
        return items.filter {
            ($0.issuerRu ?? "").lowercased().contains(q) || $0.secid.lowercased().contains(q)
                || ($0.isin ?? "").lowercased().contains(q)
        }
    }

    func start() async {
        loadingList = true
        do {
            items = try await client.mdList(category: category).instruments
            serverDown = false
        } catch { serverDown = true }
        loadingList = false
        if selectedID == nil, let first = items.first { await select(first.secid) }
    }

    func select(_ secid: String) async {
        selectedID = secid
        loadingDetail = true
        async let e = try? await client.mdInstrument(category: category, secid: secid)
        async let h = try? await client.mdHistory(secid: secid, market: market, range: range)
        entity = await e
        bars = (await h)?.points ?? []
        loadingDetail = false
    }

    func changeRange(_ r: String) {
        range = r
        guard let id = selectedID else { return }
        Task {
            bars = (try? await client.mdHistory(secid: id, market: market, range: r))?.points ?? []
        }
    }
}

struct MarketEntityView: View {
    let category: String
    @State private var vm: MarketEntityVM
    @State private var showCard = false

    init(category: String) {
        self.category = category
        _vm = State(initialValue: MarketEntityVM(category: category))
    }

    var body: some View {
        GeometryReader { geo in
            HStack(spacing: 0) {
                listPane.frame(width: max(280, geo.size.width * 0.33))
                Divider()
                detailPane.frame(maxWidth: .infinity)
            }
        }
        .task { if vm.items.isEmpty { await vm.start() } }
        .sheet(isPresented: $showCard) {
            if let id = vm.selectedID {
                InstrumentCard(category: category, secid: id) { showCard = false }
            }
        }
        .onChange(of: category) { _, _ in Task { await vm.start() } }
    }

    // MARK: master list (1/3)

    private var listPane: some View {
        VStack(spacing: 0) {
            TextField("Поиск…", text: $vm.search).textFieldStyle(.roundedBorder).padding(Theme.s2)
            Divider()
            if vm.serverDown {
                ContentUnavailableView("Bridge offline", systemImage: "bolt.horizontal.circle").frame(maxHeight: .infinity)
            } else if vm.filtered.isEmpty && !vm.loadingList {
                VStack(spacing: 6) {
                    Image(systemName: "tray").foregroundStyle(.tertiary)
                    Text("Нет данных. Запусти предзагрузку:").font(.caption).foregroundStyle(.secondary)
                    Text("python3.14 -m scripts.preload_history \(category)").font(.system(size: 10, design: .monospaced)).foregroundStyle(.tertiary)
                }
                .multilineTextAlignment(.center).padding().frame(maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(vm.filtered) { item in
                            Button { Task { await vm.select(item.secid) } } label: { row(item) }
                                .buttonStyle(.plain)
                                .background(vm.selectedID == item.secid ? Theme.accent.opacity(0.14) : .clear)
                            Divider().opacity(0.25)
                        }
                    }
                }
            }
        }
    }

    private func row(_ item: MDListItem) -> some View {
        HStack(spacing: Theme.s2) {
            VStack(alignment: .leading, spacing: 1) {
                Text(item.issuerRu ?? item.secid).font(.system(size: 12, weight: .medium)).lineLimit(1)
                Text(item.isin ?? item.secid).font(.system(size: 9)).foregroundStyle(.tertiary).lineLimit(1)
            }
            Spacer(minLength: Theme.s2)
            VStack(alignment: .trailing, spacing: 1) {
                Text(item.last.map { Fmt.number($0, digits: 2) } ?? "—").font(.system(size: 12, weight: .semibold)).monospacedDigit()
                if let c = item.changePct {
                    Text(Fmt.signedPercent(c, digits: 2)).font(.system(size: 9, weight: .medium)).monospacedDigit()
                        .foregroundStyle(c >= 0 ? Theme.positive : Theme.negative)
                }
            }
        }
        .padding(.horizontal, Theme.s2).padding(.vertical, 6).contentShape(Rectangle())
    }

    // MARK: detail (2/3)

    @ViewBuilder
    private var detailPane: some View {
        if let e = vm.entity {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s4) {
                    detailHeader(e)
                    rangeBar
                    TradingChart(bars: vm.bars, isBond: category == "bonds")
                    dayStats(e)
                    keyInfo(e)
                }
                .padding(Theme.s4)
            }
        } else {
            ContentUnavailableView("Выбери инструмент слева", systemImage: "chart.xyaxis.line")
        }
    }

    private func detailHeader(_ e: MDEntity) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Theme.s3) {
            VStack(alignment: .leading, spacing: 1) {
                Text(e.issuerRu ?? e.secid).font(.system(size: 18, weight: .bold))
                Text("\(e.secid)\(e.isin.map { " · \($0)" } ?? "") · \(e.secType ?? "")")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 1) {
                Text(e.last.map { Fmt.number($0, digits: 2) } ?? "—").font(.system(size: 20, weight: .bold)).monospacedDigit()
                if let c = e.changePct {
                    Text(Fmt.signedPercent(c, digits: 2)).font(.system(size: 12, weight: .semibold)).monospacedDigit()
                        .foregroundStyle(c >= 0 ? Theme.positive : Theme.negative)
                }
                if let d = e.asOf { Text(d).font(.system(size: 9)).foregroundStyle(.tertiary) }
            }
            Button { showCard = true } label: { Label("Карточка", systemImage: "doc.text.magnifyingglass") }
        }
    }

    private var rangeBar: some View {
        Picker("", selection: Binding(get: { vm.range }, set: { vm.changeRange($0) })) {
            ForEach(["1M", "3M", "6M", "1Y", "5Y", "ALL"], id: \.self) { Text($0).tag($0) }
        }
        .pickerStyle(.segmented).fixedSize().labelsHidden()
    }

    private func dayStats(_ e: MDEntity) -> some View {
        let d = e.day
        let stats: [(String, String)] = [
            ("Last", d?.close.map { Fmt.number($0, digits: 2) } ?? "—"),
            ("Open", d?.open.map { Fmt.number($0, digits: 2) } ?? "—"),
            ("High", d?.high.map { Fmt.number($0, digits: 2) } ?? "—"),
            ("Low", d?.low.map { Fmt.number($0, digits: 2) } ?? "—"),
            (category == "bonds" ? "Yield" : "Δ%", category == "bonds"
                ? (d?.yield.map { Fmt.percent($0, digits: 2) } ?? "—")
                : (e.changePct.map { Fmt.signedPercent($0, digits: 2) } ?? "—")),
            ("Volume", d?.volume.map { Fmt.money($0) } ?? "—"),
            ("Value", d?.value.map { Fmt.money($0) } ?? "—"),
            ("Trades", d?.numtrades.map { Fmt.number($0, digits: 0) } ?? "—"),
        ]
        return GlassCard(padding: Theme.s3) {
            VStack(alignment: .leading, spacing: Theme.s2) {
                BlockTitle("Торги за день\(d?.date.map { " · \($0)" } ?? "")", icon: "chart.bar")
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), alignment: .leading), count: 4), spacing: Theme.s2) {
                    ForEach(stats, id: \.0) { s in
                        VStack(alignment: .leading, spacing: 1) {
                            Text(s.0).font(.system(size: 10)).foregroundStyle(.secondary)
                            Text(s.1).font(.system(size: 13, weight: .semibold)).monospacedDigit()
                        }
                    }
                }
            }
        }
    }

    private func keyInfo(_ e: MDEntity) -> some View {
        let keys = category == "bonds"
            ? ["ISSUENAME", "MATDATE", "COUPONPERCENT", "COUPONVALUE", "COUPONFREQUENCY",
               "FACEVALUE", "FACEUNIT", "LISTLEVEL", "ISSUESIZE", "BOND_TYPE"]
            : ["ISSUENAME", "LATNAME", "ISSUESIZE", "LISTLEVEL", "FACEVALUE", "FACEUNIT", "ISSUEDATE"]
        let info = e.fields.filter { keys.contains($0.name) && ($0.value ?? "").isEmpty == false }
        return GlassCard(padding: Theme.s3) {
            VStack(alignment: .leading, spacing: Theme.s2) {
                BlockTitle("Об инструменте", icon: "info.circle")
                ForEach(info) { f in
                    HStack {
                        Text(f.title ?? f.name).font(.system(size: 11)).foregroundStyle(.secondary)
                        Spacer()
                        Text(f.value ?? "—").font(.system(size: 11, weight: .medium)).monospacedDigit()
                    }
                }
            }
        }
    }
}
