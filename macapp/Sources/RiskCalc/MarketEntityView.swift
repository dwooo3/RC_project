import SwiftUI
import Observation
import AppKit

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
    var sortKey = "Имя"                       // Имя | Цена | Δ% | YTM | G-spread
    var currencyNames: [String: String] = [:]
    var selectedID: String?
    var entity: MDEntity?
    var bars: [MDBar] = []
    var range = "1Y"
    var interval = "Д"                        // 1м | 5м | 15м | 1ч (live ISS) | Д | Н (store)
    var chartMode = "Свечи"                   // Свечи | Линия | Доходность
    var loadingList = false
    var loadingDetail = false
    var serverDown = false

    private let client = BridgeClient()
    @ObservationIgnored private var loadTask: Task<Void, Never>?

    init(category: String) {
        self.category = category
        if category == "fx" || category == "indices" { chartMode = "Линия" }
    }

    /// RU display mode → the chart's JS series id.
    var jsChartMode: String {
        switch chartMode { case "Линия": "Line"; case "Доходность": "Yield"; default: "Candles" }
    }

    var chartModes: [String] {
        var out = ["Свечи", "Линия"]
        if category == "bonds" && intradayMinutes == nil { out.append("Доходность") }
        return out
    }

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

    var sortKeys: [String] {
        category == "bonds" ? ["Имя", "Цена", "Δ%", "YTM", "G-spread"] : ["Имя", "Цена", "Δ%"]
    }

    var filtered: [MDListItem] {
        let q = search.lowercased().trimmingCharacters(in: .whitespaces)
        let rows = items.filter { i in
            (boardFilter.isEmpty || i.board == boardFilter)
                && (currencyFilter.isEmpty || i.currency == currencyFilter)
                && (q.isEmpty
                    || (i.issuerRu ?? "").lowercased().contains(q)
                    || i.secid.lowercased().contains(q)
                    || (i.isin ?? "").lowercased().contains(q))
        }
        switch sortKey {
        case "Цена":     return rows.sorted { ($0.last ?? -.infinity) > ($1.last ?? -.infinity) }
        case "Δ%":       return rows.sorted { ($0.changePct ?? -.infinity) > ($1.changePct ?? -.infinity) }
        case "YTM":      return rows.sorted { ($0.ytm ?? -.infinity) > ($1.ytm ?? -.infinity) }
        case "G-spread": return rows.sorted { ($0.gSpreadBp ?? -.infinity) > ($1.gSpreadBp ?? -.infinity) }
        default:         return rows
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
        if let e {
            RecentInstruments.push(secid: secid, category: category,
                                   label: e.issuerRu ?? e.nameRu ?? secid)
        }
    }

    /// Daily/weekly bars from the EOD store, or live ISS candles when an
    /// intraday interval (1м/5м/15м/1ч) is selected. Discards the result if the
    /// selection moved on while the request was in flight (stale-write guard).
    private func loadBars(_ secid: String) async {
        let wanted = interval
        let pts: [MDBar]
        if let minutes = intradayMinutes {
            pts = (try? await client.mdCandles(secid: secid, market: market, interval: minutes))?.points ?? []
        } else {
            pts = (try? await client.mdHistory(secid: secid, market: market,
                                               range: Self.apiRange(range),
                                               interval: historyInterval))?.points ?? []
        }
        guard !Task.isCancelled, selectedID == secid, interval == wanted else { return }
        bars = pts
    }

    var intradayMinutes: Int? {
        switch interval { case "1м": 1; case "5м": 5; case "15м": 15; case "1ч": 60; default: nil }
    }

    /// Store timeframe for Д/Н (the API aggregates weeks from the daily store).
    var historyInterval: String { interval == "Н" ? "1w" : "1d" }

    var intervals: [String] {
        supportsIntraday ? ["1м", "5м", "15м", "1ч", "Д", "Н"] : ["Д", "Н"]
    }

    /// Period choices depend on the timeframe: weeks need a year at least.
    var rangeOptions: [String] {
        interval == "Н" ? ["1Y", "3Y", "5Y", "8Y", "Всё"]
                        : ["1M", "3M", "6M", "1Y", "5Y", "8Y", "Всё"]
    }

    static func apiRange(_ r: String) -> String { r == "Всё" ? "ALL" : r }

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
        if intradayMinutes != nil && chartMode == "Доходность" {
            chartMode = "Свечи"                // ISS candles carry no yield
        }
        if i == "Н" && ["1M", "3M", "6M"].contains(range) {
            range = "1Y"                       // weeks need a longer window
        }
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
    // collapsible detail sections (E2) — full spec and long lists fold away
    @State private var specExpanded = false
    @State private var couponsExpanded = false
    @State private var divsExpanded = false
    // user-adjustable list width, persisted per window (doc §3)
    @SceneStorage("mdListWidth") private var listWidth: Double = 320
    @State private var dragStartWidth: Double?

    /// Takes a (cached) VM so sub-tab switches keep list/selection state.
    init(vm: MarketEntityVM) {
        self.category = vm.category
        _vm = State(initialValue: vm)
    }

    var body: some View {
        HStack(spacing: 0) {
            listPane
                .frame(width: listWidth)
                .background(Theme.cardFill)          // list reads as its own panel
            splitter
            detailPane
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .task { if vm.items.isEmpty { await vm.start() } }
        .task(id: "\(vm.selectedID ?? "")|\(vm.interval)") { await vm.pollIntraday() }
        .sheet(isPresented: $showCard) {
            if let id = vm.selectedID {
                InstrumentCard(category: category, secid: id) { showCard = false }
            }
        }
    }

    /// Soft draggable divider between the list panel and the detail area — a
    /// hairline centred in an 8pt grab strip, with a left-right resize cursor.
    private var splitter: some View {
        ZStack {
            Color.clear.frame(width: 8)
            Rectangle().fill(Color.primary.opacity(0.08)).frame(width: 1)
        }
        .frame(maxHeight: .infinity)
        .contentShape(Rectangle())
        .onHover { $0 ? NSCursor.resizeLeftRight.push() : NSCursor.pop() }
        .gesture(
            DragGesture(minimumDistance: 1)
                .onChanged { value in
                    let start = dragStartWidth ?? listWidth
                    if dragStartWidth == nil { dragStartWidth = listWidth }
                    listWidth = min(480, max(260, start + Double(value.translation.width)))
                }
                .onEnded { _ in dragStartWidth = nil }
        )
    }

    // MARK: master list (1/3)

    private var listPane: some View {
        VStack(spacing: 0) {
            // The per-list filter/sort/search block is retired — the global
            // Market Data search covers lookup. Only CSV export remains.
            HStack(spacing: Theme.s2) {
                Text("\(vm.filtered.count)")
                    .font(.system(size: 11, weight: .semibold)).monospacedDigit()
                    .foregroundStyle(.secondary)
                Text("инструментов").font(.system(size: 11)).foregroundStyle(.tertiary)
                Spacer()
                Menu {
                    Button("Список (CSV)") { exportList() }
                    if vm.intradayMinutes != nil {
                        Button("Свечи \(vm.interval) выбранного (CSV)") { exportIntraday() }
                            .disabled(vm.bars.isEmpty)
                    } else {
                        Menu("История \(vm.interval) выбранного (CSV)") {
                            ForEach(vm.rangeOptions, id: \.self) { p in
                                Button(p) { exportHistory(period: p) }
                            }
                        }
                        .disabled(vm.selectedID == nil)
                    }
                } label: {
                    Image(systemName: "square.and.arrow.up").font(.system(size: 12))
                }
                .menuStyle(.borderlessButton).fixedSize()
                .help("Экспорт в CSV (текущий таймфрейм)")
            }
            .padding(.horizontal, Theme.s3).padding(.vertical, Theme.s2)
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
                Text(item.issuerRu ?? item.secid).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                Text(item.isin ?? item.secid).font(.system(size: 9)).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: Theme.s2)
            VStack(alignment: .trailing, spacing: 1) {
                Text(item.last.map { Fmt.number($0, digits: 2) } ?? "—").font(.system(size: 12, weight: .semibold)).monospacedDigit()
                HStack(spacing: 4) {
                    if let y = item.ytm {
                        Text("YTM \(Fmt.percent(y, digits: 1))").font(.system(size: 9)).monospacedDigit()
                            .foregroundStyle(.secondary)
                    }
                    if let dv = item.divYieldPct {
                        Text("Див \(Fmt.percent(dv, digits: 1))").font(.system(size: 9)).monospacedDigit()
                            .foregroundStyle(.secondary)
                    }
                    if let c = item.changePct {
                        Text(Fmt.signedPercent(c, digits: 2)).font(.system(size: 9, weight: .medium)).monospacedDigit()
                            .foregroundStyle(c >= 0 ? Theme.positive : Theme.negative)
                    }
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

    /// Export follows the chart's timeframe (Д/Н) with its own period pick —
    /// the data comes from the local store via the same /md/history endpoint.
    private func exportHistory(period: String) {
        guard let secid = vm.selectedID else { return }
        let tf = vm.interval, apiTF = vm.historyInterval, market = vm.market
        Task {
            let pts = (try? await BridgeClient().mdHistory(
                secid: secid, market: market,
                range: MarketEntityVM.apiRange(period), interval: apiTF))?.points ?? []
            guard !pts.isEmpty else { return }
            let rows = pts.map { b in
                [b.date, num(b.open), num(b.high), num(b.low), String(b.close), num(b.volume), num(b.yld)]
            }
            CSVExport.save(suggestedName: "\(secid)_\(tf)_\(period)",
                           header: ["Date", "Open", "High", "Low", "Close", "Volume", "Yield"], rows: rows)
        }
    }

    /// Intraday export dumps the accumulated bars of the current timeframe
    /// (whatever the local store has collected for this security).
    private func exportIntraday() {
        guard !vm.bars.isEmpty, let secid = vm.selectedID else { return }
        let rows = vm.bars.map { b in
            [b.date, num(b.open), num(b.high), num(b.low), String(b.close), num(b.volume)]
        }
        CSVExport.save(suggestedName: "\(secid)_\(vm.interval)",
                       header: ["DateTime", "Open", "High", "Low", "Close", "Volume"], rows: rows)
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
                        TradingChart(bars: vm.bars, mode: vm.jsChartMode)
                        dayStats(e)
                        if let s = e.stats { statsRow(s) }
                    }
                    keyInfo(e)
                    if category == "bonds", let cps = e.schedule?.coupons, !cps.isEmpty {
                        couponsSection(cps)
                    }
                    if category == "equities", let divs = e.dividends, !divs.isEmpty {
                        dividendsSection(divs)
                    }
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

    /// One compact row of dropdown chips: interval · chart mode · period/LIVE.
    private var rangeBar: some View {
        HStack(spacing: Theme.s2) {
            chipMenu(vm.intervals,
                     Binding(get: { vm.interval }, set: { vm.changeInterval($0) }))
            chipMenu(vm.chartModes, $vm.chartMode)
            if vm.intradayMinutes != nil {
                HStack(spacing: 4) {
                    Circle().fill(Theme.positive).frame(width: 6, height: 6)
                    Text("LIVE · 15с").font(.system(size: 10, weight: .medium))
                        .foregroundStyle(Theme.positive)
                }
            } else {
                chipMenu(vm.rangeOptions,
                         Binding(get: { vm.range }, set: { vm.changeRange($0) }))
            }
            Spacer()
        }
    }

    private func chipMenu(_ options: [String], _ binding: Binding<String>) -> some View {
        Menu {
            ForEach(options, id: \.self) { o in
                Button { binding.wrappedValue = o } label: {
                    if o == binding.wrappedValue { Label(o, systemImage: "checkmark") }
                    else { Text(o) }
                }
            }
        } label: {
            HStack(spacing: 3) {
                Text(binding.wrappedValue).font(.system(size: 11, weight: .semibold))
                Image(systemName: "chevron.down").font(.system(size: 7))
            }
            .padding(.horizontal, Theme.s2).padding(.vertical, 4)
            .background(Color.gray.opacity(0.14), in: RoundedRectangle(cornerRadius: 7))
            .foregroundStyle(.primary)
        }
        .menuStyle(.borderlessButton).fixedSize()
    }

    private func dayStats(_ e: MDEntity) -> some View {
        let d = e.day
        let stats: [(String, String)] = [
            ("Последняя", d?.close.map { Fmt.number($0, digits: 2) } ?? "—"),
            ("Открытие", d?.open.map { Fmt.number($0, digits: 2) } ?? "—"),
            ("Максимум", d?.high.map { Fmt.number($0, digits: 2) } ?? "—"),
            ("Минимум", d?.low.map { Fmt.number($0, digits: 2) } ?? "—"),
            (category == "bonds" ? "Доходность" : "Δ%", category == "bonds"
                ? (d?.yield.map { Fmt.percent($0, digits: 2) } ?? "—")
                : (e.changePct.map { Fmt.signedPercent($0, digits: 2) } ?? "—")),
            ("Объём", d?.volume.map { Fmt.money($0) } ?? "—"),
            ("Оборот", d?.value.map { Fmt.money($0) } ?? "—"),
            ("Сделки", d?.numtrades.map { Fmt.number($0, digits: 0) } ?? "—"),
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

    /// 52w range · realized vol · max drawdown — cheap analytics from 5y history (B6).
    private func statsRow(_ s: MDStats) -> some View {
        HStack(spacing: Theme.s3) {
            if let hi = s.hi52w, let lo = s.lo52w {
                statChip("52 нед", "\(Fmt.number(lo, digits: 2)) – \(Fmt.number(hi, digits: 2))")
            }
            if let rv = s.rv30dPct { statChip("RV 30д", Fmt.percent(rv, digits: 1)) }
            if let dd = s.maxDdPct { statChip("Просадка", Fmt.percent(dd, digits: 1), color: Theme.negative) }
            Spacer()
        }
    }

    private func statChip(_ label: String, _ value: String, color: Color = .primary) -> some View {
        HStack(spacing: 4) {
            Text(label.uppercased()).font(.system(size: 9, weight: .semibold)).foregroundStyle(.tertiary)
            Text(value).font(.system(size: 11, weight: .medium)).monospacedDigit().foregroundStyle(color)
        }
        .padding(.horizontal, Theme.s2).padding(.vertical, 3)
        .background(Color.gray.opacity(0.10), in: RoundedRectangle(cornerRadius: 6))
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
        let rest = e.fields.filter { !keys.contains($0.name) && ($0.value ?? "").isEmpty == false }
        // store-side analytics (B1/B2/B5): shown ahead of the ISS reference
        var analytics: [(String, String)] = []
        if category == "bonds" {
            analytics = [
                ("Доходность к погашению", e.ytm.map { Fmt.percent($0, digits: 2) } ?? ""),
                ("G-spread к КБД", e.gSpreadBp.map { "\(Fmt.number($0, digits: 0)) б.п." } ?? ""),
                ("НКД", e.accrued.map { Fmt.number($0, digits: 2) } ?? ""),
                ("Средневзв. цена", e.wap.map { Fmt.number($0, digits: 2) } ?? ""),
            ].filter { !$0.1.isEmpty }
        } else if category == "equities", let dv = e.divYieldPct {
            analytics = [("Див. доходность (12м)", Fmt.percent(dv, digits: 2))]
        }
        return GlassCard(padding: Theme.s3) {
            VStack(alignment: .leading, spacing: Theme.s2) {
                BlockTitle("Об инструменте", icon: "info.circle")
                ForEach(analytics, id: \.0) { a in
                    infoRow(a.0, a.1, valueColor: Theme.accent, weight: .semibold)
                }
                if !analytics.isEmpty && !info.isEmpty { Divider().opacity(0.3) }
                ForEach(info) { f in
                    infoRow(f.title ?? f.name, f.value ?? "—")
                }
                // the rest of the ISS reference, folded away (full card contents)
                if !rest.isEmpty {
                    DisclosureGroup(isExpanded: $specExpanded) {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(rest) { f in
                                infoRow(f.title ?? f.name, f.value ?? "—")
                            }
                        }
                        .padding(.top, 4)
                    } label: {
                        Text("Вся спецификация · \(rest.count) полей")
                            .font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func infoRow(_ label: String, _ value: String,
                         valueColor: Color = .primary, weight: Font.Weight = .medium) -> some View {
        HStack(alignment: .top) {
            Text(label).font(.system(size: 11)).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(.system(size: 11, weight: weight)).monospacedDigit()
                .foregroundStyle(valueColor).multilineTextAlignment(.trailing)
        }
    }

    // MARK: cash-flow history (E2) — bond coupons / equity dividends, foldable

    private func couponsSection(_ cps: [MDCoupon]) -> some View {
        let today = Self.isoToday
        return GlassCard(padding: Theme.s3) {
            DisclosureGroup(isExpanded: $couponsExpanded) {
                VStack(spacing: 0) {
                    HStack(spacing: Theme.s2) {
                        flowHead("Дата", .leading); flowHead("Купон", .trailing); flowHead("Ставка", .trailing)
                    }
                    .padding(.vertical, 4)
                    Divider()
                    ForEach(cps) { c in
                        let future = c.couponDate >= today
                        HStack(spacing: Theme.s2) {
                            flowCell(c.couponDate, .leading,
                                     color: future ? Theme.accent : .primary,
                                     weight: future ? .semibold : .regular)
                            flowCell(c.value.map { Fmt.number($0, digits: 2) } ?? "—", .trailing)
                            flowCell(c.valuePrc.map { Fmt.percent($0, digits: 2) } ?? "—", .trailing)
                        }
                        .padding(.vertical, 3)
                        Divider().opacity(0.25)
                    }
                }
                .padding(.top, 4)
            } label: {
                BlockTitle(couponsTitle(cps, today: today), icon: "calendar.badge.clock")
            }
        }
    }

    private func couponsTitle(_ cps: [MDCoupon], today: String) -> String {
        if let next = cps.first(where: { $0.couponDate >= today }) {
            let v = next.value.map { " · \(Fmt.number($0, digits: 2))" } ?? ""
            return "Купоны · \(cps.count) · ближайший \(next.couponDate)\(v)"
        }
        return "Купоны · \(cps.count)"
    }

    private func dividendsSection(_ divs: [MDDividend]) -> some View {
        GlassCard(padding: Theme.s3) {
            DisclosureGroup(isExpanded: $divsExpanded) {
                VStack(spacing: 0) {
                    HStack(spacing: Theme.s2) {
                        flowHead("Закрытие реестра", .leading); flowHead("Дивиденд", .trailing); flowHead("Валюта", .trailing)
                    }
                    .padding(.vertical, 4)
                    Divider()
                    ForEach(divs.reversed()) { d in
                        HStack(spacing: Theme.s2) {
                            flowCell(d.registryDate, .leading)
                            flowCell(d.value.map { Fmt.number($0, digits: 2) } ?? "—", .trailing)
                            flowCell(d.currency ?? "—", .trailing)
                        }
                        .padding(.vertical, 3)
                        Divider().opacity(0.25)
                    }
                }
                .padding(.top, 4)
            } label: {
                BlockTitle("Дивиденды · \(divs.count)", icon: "banknote")
            }
        }
    }

    private func flowHead(_ t: String, _ align: Alignment) -> some View {
        Text(t.uppercased()).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: align)
    }

    private func flowCell(_ t: String, _ align: Alignment,
                          color: Color = .primary, weight: Font.Weight = .regular) -> some View {
        Text(t).font(.system(size: 11, weight: weight)).monospacedDigit().foregroundStyle(color)
            .frame(maxWidth: .infinity, alignment: align)
    }

    private static var isoToday: String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f.string(from: Date())
    }
}
