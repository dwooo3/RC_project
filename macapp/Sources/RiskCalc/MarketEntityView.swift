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
        if supportsIntraday { interval = "15м" }        // realtime by default
    }

    /// The bridge category — ETF/ПИФ funds are served under equities.
    var apiCategory: String { category == "funds" ? "equities" : category }

    /// True for ETF / unit-fund rows (secType starts with "Пай").
    private func isFund(_ i: MDListItem) -> Bool { (i.secType ?? "").hasPrefix("Пай") }

    // MARK: live session (realtime price / day stats / live daily bar)

    /// Live intraday candles for the selected instrument, refreshed every 15s
    /// (independent of the chart's timeframe).
    var sessionCandles: [MDBar] = []

    /// Realtime quotes for the whole category (ISS marketdata): last, Δ% vs
    /// prev close, OHLC, turnover, trade count. Keeps the watchlist live too.
    var liveQuotes: [String: MDLiveQuote] = [:]

    /// Realtime quote for the selected instrument.
    var selectedQuote: MDLiveQuote? { selectedID.flatMap { liveQuotes[$0] } }

    /// True when any live source is feeding the selected instrument.
    var isLive: Bool { selectedQuote?.last != nil || !sessionCandles.isEmpty }

    /// Candles of the last (current) trading day only — the candle store spans
    /// several days, so the session must be date-scoped. On a non-trading day
    /// this is simply the last session.
    private var sessionDayBars: [MDBar] {
        guard let day = sessionCandles.last.map({ String($0.date.prefix(10)) }) else { return [] }
        return sessionCandles.filter { $0.date.hasPrefix(day) }
    }

    /// The current trading day: the realtime ISS quote when available (carries
    /// turnover + trade count), else aggregated from the candle session.
    var liveDay: MDDay? {
        let sessionDate = sessionDayBars.last.map { String($0.date.prefix(10)) }
        if let q = selectedQuote, let last = q.last {
            return MDDay(date: sessionDate ?? entity?.day?.date,
                         open: q.open, high: q.high, low: q.low, close: last,
                         volume: q.volume, value: q.value, yield: q.yld,
                         numtrades: q.numtrades)
        }
        let s = sessionDayBars
        guard let first = s.first, let last = s.last else { return nil }
        let highs = s.compactMap { $0.high ?? $0.close }
        let lows = s.compactMap { $0.low ?? $0.close }
        let vol = s.compactMap { $0.volume }.reduce(0.0, +)
        return MDDay(date: sessionDate,
                     open: first.open ?? first.close, high: highs.max(), low: lows.min(),
                     close: last.close, volume: vol > 0 ? vol : nil,
                     value: nil, yield: nil, numtrades: nil)
    }

    /// Latest price — realtime quote, else live session close, else stored.
    var livePrice: Double? {
        selectedQuote?.last ?? sessionDayBars.last?.close ?? entity?.last
    }

    /// Change %: quote's Δ% vs previous close, else session close vs open,
    /// else the stored change.
    var liveChangePct: Double? {
        if let c = selectedQuote?.changePct { return c }
        let s = sessionDayBars
        if let last = s.last?.close, let open = s.first.flatMap({ $0.open ?? $0.close }), open != 0 {
            return (last - open) / open * 100
        }
        return entity?.changePct
    }

    /// RU display mode → the chart's JS series id.
    var jsChartMode: String {
        switch chartMode {
        case "Линия":            return "Line"
        case "Доходность":       return "Yield"
        case "Полная доходность": return "TotalReturn"
        case "Отн. IMOEX":       return "RelIndex"
        default:                 return "Candles"
        }
    }

    /// Server-side transform for the fetched series (equities extras).
    var dataMode: String {
        switch chartMode {
        case "Полная доходность": return "total_return"
        case "Отн. IMOEX":       return "rel_index"
        default:                 return "price"
        }
    }

    var chartModes: [String] {
        var out = ["Свечи", "Линия"]
        if intradayMinutes == nil {
            if category == "bonds" { out.append("Доходность") }
            if category == "equities" { out += ["Полная доходность", "Отн. IMOEX"] }
        }
        return out
    }

    var market: String { mdMarket(apiCategory) }

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
            // Акции excludes funds; ПИФы keeps only them.
            (category == "funds" ? isFund(i) : (category == "equities" ? !isFund(i) : true))
                && (boardFilter.isEmpty || i.board == boardFilter)
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
            items = try await client.mdList(category: apiCategory).instruments
            serverDown = false
        } catch { serverDown = true }
        if currencyNames.isEmpty, let rd = try? await client.refData() {
            currencyNames = Dictionary(rd.currencies.map { ($0.code, $0.name ?? $0.code) },
                                       uniquingKeysWith: { a, _ in a })
        }
        loadingList = false
        // realtime quotes for the whole list (watchlist prices go live)
        if let live = try? await client.mdLive(category: apiCategory) { liveQuotes = live.quotes }
        if selectedID == nil, let first = filtered.first { await select(first.secid) }
    }

    func select(_ secid: String) async {
        selectedID = secid
        loadTask?.cancel()
        loadingDetail = true
        sessionCandles = []
        let e = try? await client.mdInstrument(category: apiCategory, secid: secid)
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
        let wantedMode = dataMode
        let pts: [MDBar]
        if let minutes = intradayMinutes {
            pts = (try? await client.mdCandles(secid: secid, market: market, interval: minutes))?.points ?? []
        } else {
            pts = (try? await client.mdHistory(secid: secid, market: market,
                                               range: Self.apiRange(range),
                                               interval: historyInterval,
                                               mode: dataMode))?.points ?? []
        }
        guard !Task.isCancelled, selectedID == secid, interval == wanted, dataMode == wantedMode else { return }
        bars = pts
        if intradayMinutes != nil {
            sessionCandles = pts               // the chart fetch doubles as the session
        } else if supportsIntraday {
            await refreshSession(secid)        // live price + Д-bar merge right away
        }
    }

    /// One live-session refresh: fetch intraday candles + realtime quotes,
    /// stream candles into an intraday chart, or merge into the daily tail.
    private func refreshSession(_ secid: String) async {
        let m = intradayMinutes ?? 15
        async let liveReq = try? client.mdLive(category: apiCategory)
        let pts = (try? await client.mdCandles(secid: secid, market: market, interval: m))?.points
        if let live = await liveReq { liveQuotes = live.quotes }
        guard let pts, !Task.isCancelled, selectedID == secid else { return }
        sessionCandles = pts
        if let viewM = intradayMinutes, viewM == m {
            bars = pts
        } else if interval == "Д", dataMode == "price" {
            mergeSessionIntoDaily()
        }
    }

    /// Overwrite (or append) the last daily bar with the live session so the
    /// Д chart is realtime like the intraday timeframes.
    private func mergeSessionIntoDaily() {
        guard let day = liveDay, let date = day.date, let close = day.close, !bars.isEmpty else { return }
        let bar = MDBar(date: date, open: day.open, high: day.high, low: day.low,
                        close: close, volume: day.volume, yld: bars.last?.yld, ts: nil)
        if bars.last?.date == date {
            bars[bars.count - 1] = bar
        } else if let last = bars.last?.date, date > last {
            bars.append(bar)
        }
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
        ["bonds", "equities", "funds", "futures", "commodities", "indices"].contains(category)
    }

    func changeRange(_ r: String) {
        range = r
        reloadBars()
    }

    func changeInterval(_ i: String) {
        interval = i
        // intraday ISS candles carry no yield and no derived (TR / rel) series
        if intradayMinutes != nil && !["Свечи", "Линия"].contains(chartMode) {
            chartMode = "Свечи"
        }
        if i == "Н" && ["1M", "3M", "6M"].contains(range) {
            range = "1Y"                       // weeks need a longer window
        }
        reloadBars()
    }

    /// Switch the display mode; only refetch when the server-side transform
    /// (price / total-return / vs-index) actually changes.
    func changeChartMode(_ m: String) {
        let previous = dataMode
        chartMode = m
        if dataMode != previous { reloadBars() }
    }

    private func reloadBars() {
        guard let id = selectedID else { return }
        loadTask?.cancel()
        loadTask = Task { await loadBars(id) }
    }

    /// Live polling — refreshes the session every 15s: streams new bars into
    /// intraday charts, keeps the header price / day stats realtime, and merges
    /// the session into the daily tail so Д is live too. Cancelled automatically
    /// by .task(id:) when the instrument/interval changes or the view disappears.
    func pollIntraday() async {
        guard supportsIntraday, interval != "Н" else { return }
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(15))
            guard !Task.isCancelled, let id = selectedID else { return }
            await refreshSession(id)
        }
    }
}

struct MarketEntityView: View {
    let category: String
    @State private var vm: MarketEntityVM
    @State private var showCard = false
    @State private var bookMessage: String?
    // collapsible detail sections (E2) — full spec and long lists fold away
    @State private var specExpanded = false
    @State private var couponsExpanded = false
    @State private var divsExpanded = false
    // user-adjustable list width, persisted per window (doc §3)
    @SceneStorage("mdListWidth") private var listWidth: Double = 320
    @State private var dragStartWidth: Double?
    @Environment(\.interfaceDensity) private var density

    /// Takes a (cached) VM so sub-tab switches keep list/selection state.
    init(vm: MarketEntityVM) {
        self.category = vm.category
        _vm = State(initialValue: vm)
    }

    var body: some View {
        HStack(spacing: 0) {
            listPane
                .frame(width: listWidth)             // no fill — sits on the window bg
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
            // No header: the instrument count is dropped and CSV export lives
            // in the "Торги за день" card.
            if vm.serverDown {
                ContentUnavailableView("Мост недоступен", systemImage: "bolt.horizontal.circle").frame(maxHeight: .infinity)
            } else if vm.loadingList && vm.filtered.isEmpty {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(0..<14, id: \.self) { _ in
                            SkeletonRow()
                            Divider().opacity(0.15)
                        }
                    }
                }
            } else if vm.filtered.isEmpty {
                VStack(spacing: 6) {
                    Image(systemName: "tray").foregroundStyle(.tertiary)
                    Text("Нет данных по этой категории").font(Typography.caption).foregroundStyle(.secondary)
                    Text("Загрузите рыночные данные кнопкой обновления в панели инструментов")
                        .font(Typography.caption).foregroundStyle(.tertiary)
                }
                .multilineTextAlignment(.center).padding().frame(maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(vm.filtered) { item in
                            InstrumentRow(item: item, quote: vm.liveQuotes[item.secid],
                                          selected: vm.selectedID == item.secid,
                                          vPad: density.listRowVPad) {
                                Task { await vm.select(item.secid) }
                            }
                        }
                    }
                    .padding(.vertical, Theme.s1)
                }
            }
        }
    }

    // (row view extracted to InstrumentRow below — live quotes + styled selection)

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
                        TradingChart(bars: vm.bars, mode: vm.jsChartMode)   // no on-chart event markers
                        eventChips(e)
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
            // Shadows fade past the pane bounds — no cut line at the splitter.
            .scrollClipDisabled()
        } else if vm.loadingDetail {
            skeletonDetail
        } else {
            ContentUnavailableView("Выбери инструмент слева", systemImage: "chart.xyaxis.line")
        }
    }

    /// Skeleton shown while the first instrument's detail loads.
    private var skeletonDetail: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s4) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        SkeletonBar(width: 170, height: 18)
                        SkeletonBar(width: 230, height: 10)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 4) {
                        SkeletonBar(width: 84, height: 18)
                        SkeletonBar(width: 52, height: 10)
                    }
                }
                SkeletonBar(height: 440, radius: Theme.cardRadius)
                SkeletonCard(lines: 3)
                SkeletonCard(lines: 5)
            }
            .padding(Theme.s4)
        }
    }

    private func detailHeader(_ e: MDEntity) -> some View {
        // Realtime quote when available (else stored EOD).
        let price = vm.livePrice
        let chg = vm.liveChangePct
        let live = vm.isLive
        return HStack(alignment: .firstTextBaseline, spacing: Theme.s3) {
            VStack(alignment: .leading, spacing: 1) {
                Text(e.issuerRu ?? e.secid).font(.system(size: 18, weight: .bold))
                Text("\(e.secid)\(e.isin.map { " · \($0)" } ?? "")\(e.secType.map { " · \($0)" } ?? "")")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
            Spacer()
            if ["bonds", "equities", "futures"].contains(category) {
                addToBookButton(e)
            }
            VStack(alignment: .trailing, spacing: 1) {
                Text(price.map { Fmt.number($0, digits: 2) } ?? "—")
                    .font(.system(size: 20, weight: .bold)).monospacedDigit()
                    .contentTransition(.numericText())
                if let c = chg {
                    Text(Fmt.signedPercent(c, digits: 2)).font(.system(size: 12, weight: .semibold)).monospacedDigit()
                        .foregroundStyle(c >= 0 ? Theme.positive : Theme.negative)
                }
                if live {
                    HStack(spacing: 3) {
                        Circle().fill(Theme.positive).frame(width: 5, height: 5)
                        Text("LIVE").font(.system(size: 8, weight: .semibold)).foregroundStyle(Theme.positive)
                    }
                } else if let d = e.asOf {
                    Text(d).font(.system(size: 9)).foregroundStyle(.tertiary)
                }
            }
        }
    }

    /// Trade capture from market data: the REAL instrument (по последнему
    /// торговому дню) becomes a persistent book position.
    private func addToBookButton(_ e: MDEntity) -> some View {
        Button {
            Task {
                bookMessage = nil
                do {
                    let res = try await BridgeClient().addMarketToPortfolio(
                        category: category, secid: e.secid, quantity: 1.0)
                    bookMessage = "✓ \(res.positionID)"
                } catch {
                    bookMessage = "Ошибка: \(error.localizedDescription)"
                }
            }
        } label: {
            VStack(spacing: 1) {
                Label("В портфель", systemImage: "plus.circle")
                    .font(.system(size: 11))
                if let msg = bookMessage {
                    Text(msg).font(.system(size: 8))
                        .foregroundStyle(msg.hasPrefix("✓") ? Theme.positive : Theme.negative)
                }
            }
        }
        .buttonStyle(.bordered)
        .help("Добавить позицию в книгу (qty 1, изменить можно в Portfolio)")
    }

    /// One compact row of dropdown chips: interval · chart mode · period/LIVE.
    private var rangeBar: some View {
        HStack(spacing: Theme.s2) {
            chipMenu("Интервал графика", vm.intervals,
                     Binding(get: { vm.interval }, set: { vm.changeInterval($0) }))
            chipMenu("Тип графика", vm.chartModes,
                     Binding(get: { vm.chartMode }, set: { vm.changeChartMode($0) }))
            if vm.intradayMinutes != nil {
                HStack(spacing: 4) {
                    Circle().fill(Theme.positive).frame(width: 6, height: 6)
                    Text("LIVE · 15с").font(.system(size: 10, weight: .medium))
                        .foregroundStyle(Theme.positive)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Живые данные, обновление каждые 15 секунд")
            } else {
                chipMenu("Период", vm.rangeOptions,
                         Binding(get: { vm.range }, set: { vm.changeRange($0) }))
            }
            Spacer()
        }
    }

    private func chipMenu(_ role: String, _ options: [String],
                          _ binding: Binding<String>) -> some View {
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
            .background(Color.primary.opacity(0.08), in: RoundedRectangle(cornerRadius: 7))
            .foregroundStyle(.primary)
        }
        .menuStyle(.borderlessButton).fixedSize()
        .help(role)
        .accessibilityLabel(role)
        .accessibilityValue(binding.wrappedValue)
    }

    private func dayStats(_ e: MDEntity) -> some View {
        // Live session when polling, else the stored EOD day (current trading
        // day; on a weekend — the last session).
        let day = vm.liveDay ?? e.day
        let live = vm.liveDay != nil
        let metrics = InstrumentPresentation.dayMetrics(e, category: category, day: day,
                                                        changePct: live ? vm.liveChangePct : nil)
        return GlassCard(padding: Theme.s3) {
            VStack(alignment: .leading, spacing: Theme.s2) {
                HStack(spacing: Theme.s2) {
                    BlockTitle("Торги за день\(day?.date.map { " · \($0)" } ?? "")", icon: "chart.bar")
                    if live {
                        Text("LIVE").font(.system(size: 8, weight: .semibold))
                            .foregroundStyle(Theme.positive)
                    }
                    Spacer()
                    exportMenu
                }
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), alignment: .leading), count: 4), spacing: Theme.s2) {
                    ForEach(metrics) { m in
                        VStack(alignment: .leading, spacing: 1) {
                            Text(m.title).font(Typography.micro).foregroundStyle(.secondary)
                            Text(m.value).font(Typography.subtitle.weight(.semibold))
                                .monospacedDigit().foregroundStyle(m.color)
                                .lineLimit(1).minimumScaleFactor(0.7)
                        }
                    }
                }
            }
        }
    }

    /// CSV export — lives in the "Торги за день" card header.
    private var exportMenu: some View {
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
            Image(systemName: "square.and.arrow.up").font(.system(size: 12)).foregroundStyle(.secondary)
                .frame(width: 24, height: 24).contentShape(Rectangle())
        }
        .menuStyle(.borderlessButton).fixedSize()
        .help("Экспорт в CSV")
        .accessibilityLabel("Экспорт в CSV")
    }

    /// Upcoming events (next coupon / offer / amortization / maturity / dividend)
    /// as a compact chip row under the chart — coupon schedules are forward-
    /// looking, so they live here rather than on the historical price axis.
    @ViewBuilder
    private func eventChips(_ e: MDEntity) -> some View {
        let events = InstrumentPresentation.upcomingEvents(e, today: Self.isoToday)
        if !events.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Theme.s2) {
                    Text("Ближайшие события")
                        .font(Typography.micro).foregroundStyle(.tertiary)
                    ForEach(events) { ev in
                        let color = eventColor(ev.type)
                        HStack(spacing: 5) {
                            Image(systemName: eventIcon(ev.type)).font(.system(size: 9))
                            Text(ev.title).font(Typography.caption.weight(.medium))
                            Text(ev.date).font(Typography.caption).monospacedDigit().foregroundStyle(.secondary)
                            if !ev.detail.isEmpty {
                                Text(ev.detail).font(Typography.caption).monospacedDigit().foregroundStyle(.secondary)
                            }
                        }
                        .foregroundStyle(color)
                        .padding(.horizontal, Theme.s2).padding(.vertical, 3)
                        .background(color.opacity(0.12), in: Capsule())
                    }
                }
            }
        }
    }

    private func eventIcon(_ type: InstrumentEventType) -> String {
        switch type {
        case .coupon:       return "banknote"
        case .offer:        return "arrow.left.arrow.right"
        case .amortization: return "chart.line.downtrend.xyaxis"
        case .maturity:     return "flag.checkered"
        case .dividend:     return "banknote.fill"
        default:            return "circle"
        }
    }

    private func eventColor(_ type: InstrumentEventType) -> Color {
        switch type {
        case .offer:     return Theme.warning
        case .maturity:  return Theme.negative
        case .dividend:  return Theme.positive
        default:         return Theme.accent
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
        .background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: 7))
    }

    private func keyInfo(_ e: MDEntity) -> some View {
        // Attributes are composed by the universal presentation layer (type-aware).
        let detail = InstrumentPresentation.detail(e, category: category)
        return GlassCard(padding: Theme.s3) {
            VStack(alignment: .leading, spacing: Theme.s2) {
                BlockTitle("Об инструменте", icon: "info.circle")
                ForEach(detail.analytics) { a in
                    infoRow(a.title, a.value, valueColor: Theme.accent, weight: .semibold)
                }
                if !detail.analytics.isEmpty && !detail.reference.isEmpty { Divider().opacity(0.3) }
                ForEach(detail.reference) { a in
                    infoRow(a.title, a.value)
                }
                // the rest of the reference, folded away
                if !detail.extra.isEmpty {
                    DisclosureGroup(isExpanded: $specExpanded) {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(detail.extra) { a in
                                infoRow(a.title, a.value)
                            }
                        }
                        .padding(.top, 4)
                    } label: {
                        Text("Вся спецификация · \(detail.extra.count) полей")
                            .font(Typography.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func infoRow(_ label: String, _ value: String,
                         valueColor: Color = .primary, weight: Font.Weight = .medium) -> some View {
        HStack(alignment: .top) {
            Text(label).font(Typography.caption).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(Typography.caption.weight(weight)).monospacedDigit()
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
            return "Купоны · ближайший \(next.couponDate)\(v)"
        }
        return "Купоны"
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
                BlockTitle("Дивиденды", icon: "banknote")
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

/// Watchlist row: live quote overrides the stored price/Δ%; the selected row
/// is a rounded accent pill (matching the sidebar), with a soft hover wash.
private struct InstrumentRow: View {
    let item: MDListItem
    let quote: MDLiveQuote?
    let selected: Bool
    let vPad: CGFloat
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        let last = quote?.last ?? item.last
        let chg = quote?.changePct ?? item.changePct
        Button(action: action) {
            HStack(spacing: Theme.s2) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(item.issuerRu ?? item.secid).font(Typography.ticker).lineLimit(1)
                    Text(item.isin ?? item.secid).font(Typography.micro).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: Theme.s2)
                VStack(alignment: .trailing, spacing: 1) {
                    Text(last.map { Fmt.number($0, digits: 2) } ?? "—")
                        .font(Typography.ticker).monospacedDigit()
                        .contentTransition(.numericText())
                    HStack(spacing: 4) {
                        if let y = item.ytm {
                            Text("YTM \(Fmt.percent(y, digits: 1))").font(.system(size: 9)).monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                        if let dv = item.divYieldPct {
                            Text("Див \(Fmt.percent(dv, digits: 1))").font(.system(size: 9)).monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                        if let c = chg {
                            Text(Fmt.signedPercent(c, digits: 2)).font(.system(size: 9, weight: .medium)).monospacedDigit()
                                .foregroundStyle(c >= 0 ? Theme.positive : Theme.negative)
                        }
                    }
                }
            }
            .padding(.horizontal, Theme.s3).padding(.vertical, vPad)
            .background {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(selected ? AnyShapeStyle(Theme.accent.opacity(0.16))
                                   : AnyShapeStyle(hovering ? Color.primary.opacity(0.05) : Color.clear))
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .padding(.horizontal, Theme.s2)
    }
}
