import SwiftUI
import Charts
import Observation

@MainActor
@Observable
final class RealBondViewModel {
    var bonds: [RealBondRow] = []
    var boards: [String] = []
    var curveLines: [CurveData] = []
    var snapshot: RealSnapshot?
    var selectedID: String?
    var search = ""
    var board = ""   // empty = all boards
    var curveID = "GCURVE_RUB"
    var shiftBps: Double = 0
    var forecastCurveID = "RUONIA_RUB"
    var floatSpreadBps: Double = 0
    var result: RepriceResult?
    var isLoading = false
    var isPricing = false
    var serverDown = false
    var errorMessage: String?

    private let client = BridgeClient()

    var selected: RealBondRow? { bonds.first { $0.secid == selectedID } }
    var selectedCurveData: CurveData? { curveLines.first { $0.id == curveID } }
    var curveOptions: [(id: String, label: String)] { curveLines.map { ($0.id, $0.label) } }

    func load() async {
        guard bonds.isEmpty else { return }
        isLoading = true
        serverDown = false
        curveLines = (try? await client.curves()) ?? []
        do {
            try await reloadList()
        } catch {
            serverDown = true
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func reloadList() async throws {
        let list = try await client.realBonds(board: board.isEmpty ? nil : board, search: search, limit: 300)
        bonds = list.bonds
        boards = list.boards
        snapshot = list.snapshot
        if selectedID == nil || !bonds.contains(where: { $0.secid == selectedID }) {
            selectedID = bonds.first?.secid
            result = nil
        }
    }

    func applyFilters() async {
        do { try await reloadList() } catch { errorMessage = error.localizedDescription }
    }

    func select(_ secid: String) {
        guard secid != selectedID else { return }
        selectedID = secid
        result = nil
    }

    func reprice() async {
        guard let bond = selected else { return }
        isPricing = true
        errorMessage = nil
        do {
            result = try await client.reprice(secid: bond.secid, curveID: curveID, shiftBps: shiftBps,
                                              forecastCurveID: forecastCurveID, floatSpreadBps: floatSpreadBps)
        } catch {
            errorMessage = error.localizedDescription
        }
        isPricing = false
    }
}

// MARK: - View

struct RealBondPane: View {
    @Bindable var vm: RealBondViewModel

    var body: some View {
        Group {
            if vm.serverDown {
                ServerDownView(message: vm.errorMessage) { Task { await vm.load() } }
            } else {
                HStack(spacing: 0) {
                    listColumn
                    Divider()
                    detail
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await vm.load() }
    }

    // MARK: list

    private var listColumn: some View {
        VStack(spacing: 0) {
            VStack(spacing: Theme.s2) {
                TextField("Search secid / ISIN / issuer", text: $vm.search)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await vm.applyFilters() } }
                if !vm.boards.isEmpty {
                    Picker("Board", selection: $vm.board) {
                        Text("All boards").tag("")
                        ForEach(vm.boards, id: \.self) { Text($0).tag($0) }
                    }
                    .labelsHidden().pickerStyle(.menu)
                    .onChange(of: vm.board) { _, _ in Task { await vm.applyFilters() } }
                }
                HStack {
                    Text("\(vm.bonds.count) bonds").font(.system(size: 10)).foregroundStyle(.tertiary)
                    Spacer()
                    if vm.isLoading { ProgressView().controlSize(.mini) }
                }
            }
            .padding(Theme.s3)
            Divider()
            List(selection: Binding(get: { vm.selectedID }, set: { if let v = $0 { vm.select(v) } })) {
                ForEach(vm.bonds) { bond in bondRow(bond).tag(bond.secid) }
            }
            .listStyle(.plain)
        }
        .frame(width: 300)
        .background(Color(nsColor: .windowBackgroundColor).opacity(0.5))
    }

    private func bondRow(_ b: RealBondRow) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(b.secid).font(.system(size: 12, weight: .medium))
                Spacer()
                Text(b.cleanPrice.map { Fmt.number($0, digits: 2) } ?? "—")
                    .font(.system(size: 12)).monospacedDigit()
            }
            HStack {
                Text(b.issuer ?? "").font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                Spacer()
                Text(b.ytm.map { Fmt.percent($0 * 100, digits: 2) } ?? "")
                    .font(.system(size: 10)).foregroundStyle(.tertiary).monospacedDigit()
            }
        }
        .padding(.vertical, 2)
    }

    // MARK: detail

    @ViewBuilder
    private var detail: some View {
        if let bond = vm.selected {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s5) {
                    PageHeader(bond.secid, subtitle: bond.issuer ?? bond.isin ?? "") {
                        if let level = bond.listLevel { Pill(text: "Level \(level)", color: Theme.accent) }
                    }
                    refLine(bond)
                    controls
                    if let r = vm.result {
                        resultCards(r)
                        spreadNote(r)
                        if let cd = vm.selectedCurveData { curvePanel(cd, cashflows: r.cashflows) }
                        cashflowChart(r.cashflows)
                    } else {
                        ContentUnavailableView("Not repriced yet", systemImage: "function",
                                               description: Text("Pick a curve and press Reprice."))
                            .frame(height: 180)
                    }
                }
                .padding(Theme.s5)
                .frame(maxWidth: 920, alignment: .leading)
            }
            .frame(maxWidth: .infinity)
        } else {
            ContentUnavailableView("Select a bond", systemImage: "building.columns")
        }
    }

    private func refLine(_ b: RealBondRow) -> some View {
        HStack(spacing: Theme.s2) {
            if let c = b.couponPercent { Pill(text: "Coupon \(Fmt.number(c, digits: 2))%", color: .secondary) }
            if let m = b.matDate { Pill(text: "Maturity \(m)", color: .secondary) }
            if let isin = b.isin { Pill(text: isin, color: .secondary) }
            if let ccy = b.currency { Pill(text: ccy, color: .secondary) }
        }
    }

    private var controls: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack(alignment: .bottom, spacing: Theme.s4) {
                    labeled("Discount curve") {
                        Picker("", selection: $vm.curveID) {
                            ForEach(vm.curveOptions, id: \.id) { Text($0.label).tag($0.id) }
                        }.labelsHidden().fixedSize()
                    }
                    labeled("Curve shift (bp)") {
                        TextField("", value: $vm.shiftBps, format: .number)
                            .textFieldStyle(.roundedBorder).frame(width: 90).monospacedDigit()
                    }
                    Spacer()
                    Button {
                        Task { await vm.reprice() }
                    } label: {
                        HStack(spacing: Theme.s2) {
                            if vm.isPricing { ProgressView().controlSize(.small) }
                            Image(systemName: "bolt.fill").font(.system(size: 11))
                            Text(vm.isPricing ? "Repricing…" : "Reprice").fontWeight(.semibold)
                        }
                        .frame(minWidth: 120)
                    }
                    .controlSize(.large).buttonStyle(.borderedProminent).disabled(vm.isPricing)
                }
                Divider()
                HStack(alignment: .bottom, spacing: Theme.s4) {
                    Image(systemName: "waveform.path").foregroundStyle(.tertiary).font(.system(size: 11))
                    labeled("Forecast curve (floaters)") {
                        Picker("", selection: $vm.forecastCurveID) {
                            ForEach(vm.curveOptions, id: \.id) { Text($0.label).tag($0.id) }
                        }.labelsHidden().fixedSize()
                    }
                    labeled("Float spread (bp)") {
                        TextField("", value: $vm.floatSpreadBps, format: .number)
                            .textFieldStyle(.roundedBorder).frame(width: 90).monospacedDigit()
                    }
                    Spacer()
                }
            }
        }
    }

    private func labeled<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
            content()
        }
    }

    private func resultCards(_ r: RepriceResult) -> some View {
        KPIStrip(items: [
            KPICard(label: "Market clean", value: Fmt.number(r.marketClean, digits: 3),
                    sub: "MOEX quote", accent: Theme.accent, icon: "tag.fill"),
            KPICard(label: "Theoretical", value: Fmt.number(r.theoreticalClean, digits: 3),
                    sub: r.curveLabel + (r.shiftBps != 0 ? " \(Int(r.shiftBps) > 0 ? "+" : "")\(Int(r.shiftBps))bp" : ""),
                    accent: Theme.bucketColor("Rates"), icon: "function"),
            KPICard(label: "Price diff", value: (r.priceDiff >= 0 ? "+" : "") + Fmt.number(r.priceDiff, digits: 3),
                    sub: "theo − market", accent: Theme.trendColor(r.priceDiff), icon: "arrow.up.arrow.down"),
            KPICard(label: "Z-spread", value: r.zSpreadBps.map { Fmt.number($0, digits: 1) + " bp" } ?? "—",
                    sub: "to market (price)", accent: Theme.bucketColor("Credit"), icon: "shield.lefthalf.filled"),
            KPICard(label: "Yield vs curve", value: r.ytmSpreadBps.map { (($0 >= 0 ? "+" : "") + Fmt.number($0, digits: 1) + " bp") } ?? "—",
                    sub: "mkt − curve YTM", accent: Theme.bucketColor("FX"), icon: "chart.xyaxis.line"),
            KPICard(label: "Curve YTM", value: r.curveYtm.map { Fmt.percent($0 * 100, digits: 2) } ?? "—",
                    sub: "curve-implied", accent: Theme.bucketColor("Rates"), icon: "function"),
            KPICard(label: "Market YTM", value: r.marketYtm.map { Fmt.percent($0 * 100, digits: 2) } ?? "—",
                    sub: "MOEX quote", accent: Theme.warning, icon: "percent"),
        ], minWidth: 150)
    }

    private func spreadNote(_ r: RepriceResult) -> some View {
        let sovereign = (r.board ?? "").uppercased().hasPrefix("TQOB") || r.curveID == "GCURVE_RUB"
        var text = sovereign
            ? "Priced on the bond's own sovereign curve — Z-spread and yield-vs-curve are the bond's basis (rich/cheap) to the fitted OFZ curve, not a credit spread. Discount on a different curve to read a credit spread."
            : "Z-spread is the parallel zero-curve spread that reprices to the market; yield-vs-curve is the bond's YTM minus the curve-implied YTM of the same cashflows."
        if r.isFloater {
            text = "Floating-rate note — future coupons projected from the \(r.forecastCurveID ?? "forecast") forward curve + float spread. " + text
        }
        return HStack(alignment: .top, spacing: Theme.s2) {
            Image(systemName: "info.circle").foregroundStyle(Theme.accent).font(.system(size: 11))
            Text(text).font(.system(size: 11)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
        }
        .padding(Theme.s3)
        .background(Theme.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    }

    private struct Sample: Identifiable {
        let series: String; let t: Double; let r: Double
        var id: String { "\(series)-\(t)" }
    }

    private func curvePanel(_ cd: CurveData, cashflows: [Cashflow]) -> some View {
        var samples = cd.zero.map { Sample(series: "Zero", t: $0.t, r: $0.rate * 100) }
        if let r = vm.result, r.shiftBps != 0 {
            samples += cd.zero.map { Sample(series: "Shifted", t: $0.t, r: $0.rate * 100 + r.shiftBps / 100) }
        }
        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Discount curve · \(cd.label)", icon: "chart.xyaxis.line")
                Chart {
                    ForEach(samples) { s in
                        LineMark(x: .value("Tenor", s.t), y: .value("Rate", s.r))
                            .foregroundStyle(by: .value("Curve", s.series))
                            .interpolationMethod(.monotone)
                            .lineStyle(StrokeStyle(lineWidth: 2, dash: s.series == "Shifted" ? [4, 3] : []))
                    }
                    ForEach(cashflows.map { $0.t }, id: \.self) { t in
                        RuleMark(x: .value("t", t)).foregroundStyle(.gray.opacity(0.15))
                    }
                }
                .chartForegroundStyleScale(["Zero": Theme.accent, "Shifted": Theme.warning])
                .chartXAxisLabel("Tenor (years)").chartYAxisLabel("Rate (%)")
                .frame(height: 220)
            }
        }
    }

    private func cashflowChart(_ cashflows: [Cashflow]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Cashflows (per 100 face)", icon: "chart.bar.fill")
                Chart(cashflows) { cf in
                    BarMark(x: .value("Time", cf.t), y: .value("Cashflow", cf.amount), width: .fixed(6))
                        .foregroundStyle(Theme.accent).cornerRadius(2)
                }
                .chartXAxisLabel("Time (years)").frame(height: 180)
            }
        }
    }
}
