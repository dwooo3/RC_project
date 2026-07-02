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
    var boardFilter = ""                      // "" = все
    var currencyFilter = ""
    var currencyNames: [String: String] = [:]
    var selectedID: String?
    var entity: MDEntity?
    var bars: [MDBar] = []
    var range = "1Y"
    var interval = "Д"                        // Д (daily) | 1м | 10м | 1ч (live ISS)
    var loadingList = false
    var loadingDetail = false
    var serverDown = false

    private let client = BridgeClient()
    @ObservationIgnored private var loadTask: Task<Void, Never>?

    init(category: String) { self.category = category }

    var market: String { mdMarket(category) }

    var availableBoards: [String] {
        Array(Set(items.compactMap { $0.board })).sorted()
    }

    var availableCurrencies: [String] {
        Array(Set(items.compactMap { $0.currency })).sorted()
    }

    func currencyLabel(_ code: String) -> String {
        if let n = currencyNames[code], n != code { return "\(code) · \(n)" }
        return code
    }

    var filtered: [MDListItem] {
        let q = search.lowercased().trimmingCharacters(in: .whitespaces)
        return items.filter { i in
            (boardFilter.isEmpty || i.board == boardFilter)
                && (currencyFilter.isEmpty || i.currency == currencyFilter)
                && (q.isEmpty
                    || (i.issuerRu ?? "").lowercased().contains(q)
                    || i.secid.lowercased().contains(q)
                    || (i.isin ?? "").lowercased().contains(q))
        }
    }

    func start() async {
        loadingList = true
        do {
            items = try await client.mdList(category: category).instruments
            serverDown = false
        } catch { serverDown = true }
        if currencyNames.isEmpty, let rd = try? await client.refData() {
            currencyNames = Dictionary(rd.currencies.map { ($0.code, $0.name ?? $0.code) },
                                       uniquingKeysWith: { a, _ in a })
        }
        loadingList = false
        if selectedID == nil, let first = items.first { await select(first.secid) }
    }

    func select(_ secid: String) async {
        selectedID = secid
        loadTask?.cancel()
        loadingDetail = true
        let e = try? await client.mdInstrument(category: category, secid: secid)
        guard selectedID == secid else { return }        // a later click won the race
        if category == "options" {
            bars = []                                   // options have no price series
        } else {
            await loadBars(secid)
        }
        guard selectedID == secid else { return }
        entity = e
        loadingDetail = false
    }

    /// Daily bars from the EOD store, or live ISS candles when an intraday
    /// interval (1м/10м/1ч) is selected. Discards the result if the selection
    /// moved on while the request was in flight (stale-write guard).
    private func loadBars(_ secid: String) async {
        let wanted = interval
        let pts: [MDBar]
        if let minutes = intradayMinutes {
            pts = (try? await client.mdCandles(secid: secid, market: market, interval: minutes))?.points ?? []
        } else {
            pts = (try? await client.mdHistory(secid: secid, market: market, range: range))?.points ?? []
        }
        guard !Task.isCancelled, selectedID == secid, interval == wanted else { return }
        bars = pts
    }

    var intradayMinutes: Int? {
        switch interval { case "1м": 1; case "10м": 10; case "1ч": 60; default: nil }
    }

    /// FX rows are CBR fixings (no ISS intraday trades under these secids);
    /// options render a chain board instead of a chart.
    var supportsIntraday: Bool {
        ["bonds", "equities", "futures", "commodities", "indices"].contains(category)
    }

    func changeRange(_ r: String) {
        range = r
        reloadBars()
    }

    func changeInterval(_ i: String) {
        interval = i
        reloadBars()
    }

    private func reloadBars() {
        guard let id = selectedID else { return }
        loadTask?.cancel()
        loadTask = Task { await loadBars(id) }
    }

    /// Live polling while an intraday interval is active — re-fetches candles so
    /// the chart's updateLast streams the newest bar. Cancelled automatically by
    /// .task(id:) when the instrument/interval changes or the view disappears.
    func pollIntraday() async {
        guard intradayMinutes != nil else { return }
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(15))
            guard !Task.isCancelled, let id = selectedID, let m = intradayMinutes else { return }
            if let pts = try? await client.mdCandles(secid: id, market: market, interval: m).points {
                guard !Task.isCancelled, selectedID == id, intradayMinutes == m else { return }
                bars = pts
            }
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
        .task(id: "\(vm.selectedID ?? "")|\(vm.interval)") { await vm.pollIntraday() }
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
            HStack(spacing: Theme.s2) {
                TextField("Поиск…", text: $vm.search).textFieldStyle(.roundedBorder)
                Menu {
                    Button("Список (CSV)") { exportList() }
                    Button("История выбранного (CSV)") { exportHistory() }
                        .disabled(vm.bars.isEmpty)
                } label: {
                    Image(systemName: "square.and.arrow.up")
                }
                .menuStyle(.borderlessButton).fixedSize()
                .help("Экспорт в CSV")
            }
            .padding(.horizontal, Theme.s2).padding(.top, Theme.s2)
            if vm.availableBoards.count > 1 || vm.availableCurrencies.count > 1 {
                HStack(spacing: Theme.s2) {
                    if vm.availableBoards.count > 1 {
                        filterMenu("Борд", vm.availableBoards, $vm.boardFilter)
                    }
                    if vm.availableCurrencies.count > 1 {
                        filterMenu("Валюта", vm.availableCurrencies, $vm.currencyFilter,
                                   label: { vm.currencyLabel($0) })
                    }
                    Spacer()
                }
                .padding(.horizontal, Theme.s2)
            }
            Color.clear.frame(height: Theme.s2)
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

    private func filterMenu(_ title: String, _ options: [String], _ binding: Binding<String>,
                            label: ((String) -> String)? = nil) -> some View {
        let active = !binding.wrappedValue.isEmpty
        return Menu {
            Button("Все") { binding.wrappedValue = "" }
            Divider()
            ForEach(options, id: \.self) { o in
                Button(label?(o) ?? o) { binding.wrappedValue = o }
            }
        } label: {
            HStack(spacing: 3) {
                Text("\(title): \(active ? binding.wrappedValue : "все")")
                    .font(.system(size: 10, weight: active ? .semibold : .regular)).lineLimit(1)
                Image(systemName: "chevron.down").font(.system(size: 7))
            }
            .padding(.horizontal, Theme.s2).padding(.vertical, 3)
            .background(active ? Theme.accent.opacity(0.16) : Color.gray.opacity(0.12),
                        in: RoundedRectangle(cornerRadius: 7))
            .foregroundStyle(active ? Theme.accent : .secondary)
        }
        .menuStyle(.borderlessButton).fixedSize()
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

    // MARK: export

    private func num(_ v: Double?) -> String { v.map { String($0) } ?? "" }

    private func exportList() {
        let rows = vm.filtered.map { i in
            [i.secid, i.issuerRu ?? "", i.isin ?? "", num(i.last), num(i.changePct), i.asOf ?? ""]
        }
        CSVExport.save(suggestedName: "\(category)_list",
                       header: ["SecID", "Issuer", "ISIN", "Last", "Change%", "AsOf"], rows: rows)
    }

    private func exportHistory() {
        guard !vm.bars.isEmpty else { return }
        let rows = vm.bars.map { b in
            [b.date, num(b.open), num(b.high), num(b.low), String(b.close), num(b.volume), num(b.yld)]
        }
        CSVExport.save(suggestedName: "\(vm.selectedID ?? category)_history",
                       header: ["Date", "Open", "High", "Low", "Close", "Volume", "Yield"], rows: rows)
    }

    // MARK: detail (2/3)

    @ViewBuilder
    private var detailPane: some View {
        if let e = vm.entity {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s4) {
                    detailHeader(e)
                    if category == "options" {
                        OptionChainView(chain: e.optionChain ?? [])
                    } else {
                        rangeBar
                        TradingChart(bars: vm.bars, isBond: category == "bonds", preferLine: category == "fx")
                        dayStats(e)
                    }
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
        HStack(spacing: Theme.s3) {
            // interval: daily from the EOD store, or live ISS intraday candles
            if vm.supportsIntraday {
                Picker("", selection: Binding(get: { vm.interval }, set: { vm.changeInterval($0) })) {
                    ForEach(["1м", "10м", "1ч", "Д"], id: \.self) { Text($0).tag($0) }
                }
                .pickerStyle(.segmented).fixedSize().labelsHidden()
            }
            if vm.intradayMinutes != nil {
                HStack(spacing: 4) {
                    Circle().fill(Theme.positive).frame(width: 6, height: 6)
                    Text("LIVE · обновление 15с").font(.system(size: 10, weight: .medium))
                        .foregroundStyle(Theme.positive)
                }
            } else {
                Picker("", selection: Binding(get: { vm.range }, set: { vm.changeRange($0) })) {
                    ForEach(["1M", "3M", "6M", "1Y", "5Y", "ALL"], id: \.self) { Text($0).tag($0) }
                }
                .pickerStyle(.segmented).fixedSize().labelsHidden()
            }
            Spacer()
        }
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
        let keys: [String]
        switch category {
        case "bonds":
            keys = ["ISSUENAME", "MATDATE", "COUPONPERCENT", "COUPONVALUE", "COUPONFREQUENCY",
                    "FACEVALUE", "FACEUNIT", "LISTLEVEL", "ISSUESIZE", "BOND_TYPE"]
        case "fx":
            keys = ["pair", "code", "source"]
        default:
            keys = ["ISSUENAME", "LATNAME", "ISSUESIZE", "LISTLEVEL", "FACEVALUE", "FACEUNIT", "ISSUEDATE"]
        }
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
