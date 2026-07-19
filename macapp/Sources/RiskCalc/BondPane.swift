import SwiftUI
import Charts

/// Fixed-income pricing workspace: instrument rail + flexible parameter form +
/// detailed valuation (price block, analytics, key-rate durations, cashflows).
struct BondPane: View {
    enum Mode: String, CaseIterable, Identifiable {
        case single = "Single"
        case sheet = "Pricing sheet"
        case real = "Real bonds"
        var id: String { rawValue }
    }

    @State private var vm = BondViewModel()
    @State private var sheetVM = SheetViewModel()
    @State private var realVM = RealBondViewModel()
    @State private var mode: Mode = .single
    @State private var showPar = true
    @State private var showForward = false

    var body: some View {
        Group {
            if vm.serverDown {
                ServerDownView(message: vm.errorMessage) { Task { await vm.load() } }
            } else {
                VStack(spacing: 0) {
                    HStack {
                        SegmentedBar(items: Mode.allCases.map { ($0, $0.rawValue) },
                                     selection: $mode)
                            .fixedSize()
                        Spacer()
                    }
                    .padding(.horizontal, Theme.s5).padding(.vertical, Theme.s2)
                    Divider()
                    switch mode {
                    case .single:
                        HStack(spacing: 0) { rail; Divider(); workArea }
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    case .sheet:
                        BondSheetView(vm: sheetVM)
                    case .real:
                        RealBondPane(vm: realVM)
                    }
                }
            }
        }
        .task { if vm.instruments.isEmpty { await vm.load() } }
    }

    // MARK: instrument rail

    private var rail: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s4) {
                ForEach(vm.grouped, id: \.group) { group in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(group.group.uppercased())
                            .font(.system(size: 10, weight: .semibold)).tracking(0.5)
                            .foregroundStyle(.tertiary).padding(.horizontal, Theme.s2)
                        ForEach(group.items) { inst in row(inst) }
                    }
                }
            }
            .padding(Theme.s3)
        }
        .frame(width: 240)
        .background(Color(nsColor: .windowBackgroundColor).opacity(0.5))
        .overlay { if vm.isLoading && vm.instruments.isEmpty { ProgressView().controlSize(.small) } }
    }

    private func row(_ inst: BondInstrument) -> some View {
        let selected = vm.selectedID == inst.id
        return Button { vm.select(inst.id) } label: {
            HStack(spacing: Theme.s2) {
                Circle().fill(Theme.statusColor(inst.governance.status)).frame(width: 7, height: 7)
                Text(inst.name)
                    .font(.system(size: 13, weight: selected ? .semibold : .regular))
                    .foregroundStyle(selected ? Theme.accent : .primary).lineLimit(1)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, Theme.s3).padding(.vertical, 7)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selected ? Theme.accent.opacity(0.14) : .clear, in: RoundedRectangle(cornerRadius: 7))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: work area

    @ViewBuilder
    private var workArea: some View {
        if let inst = vm.selected {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s5) {
                    PageHeader(inst.name, subtitle: subtitle(inst)) {
                        StatusChip(status: inst.governance.status)
                    }
                    paramGroups(inst)
                    if let cd = vm.selectedCurveData { curvePanel(cd) }
                    calculateBar
                    if let r = vm.result { resultSection(r) }
                }
                .padding(Theme.s5)
                .frame(maxWidth: 1100, alignment: .leading)
            }
            .frame(maxWidth: .infinity)
        } else {
            ContentUnavailableView("Select an instrument", systemImage: "building.columns")
        }
    }

    private func subtitle(_ inst: BondInstrument) -> String {
        [inst.governance.assetClass, inst.governance.method].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private let groupTitles = ["contract": "Contract terms", "market": "Market & curves",
                               "model": "Model parameters", "numerical": "Numerical"]

    private func paramGroups(_ inst: BondInstrument) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: Theme.s4)],
                  alignment: .leading, spacing: Theme.s4) {
            ForEach(["contract", "market", "model", "numerical"], id: \.self) { group in
                let specs = inst.params.filter { $0.group == group }
                if !specs.isEmpty {
                    GlassCard {
                        VStack(alignment: .leading, spacing: Theme.s3) {
                            BlockTitle(groupTitles[group] ?? group, icon: icon(group))
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 130), spacing: Theme.s3)],
                                      alignment: .leading, spacing: Theme.s3) {
                                ForEach(specs) { spec in
                                    if spec.dtype == "float" || spec.dtype == "int" {
                                        ParamFieldView(spec: spec, numeric: vm.numericBinding(spec.key), string: nil)
                                    } else {
                                        ParamFieldView(spec: spec, numeric: nil, string: vm.choiceBinding(spec.key))
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private func icon(_ group: String) -> String {
        switch group {
        case "contract": return "doc.text"
        case "market": return "globe"
        case "model": return "slider.horizontal.3"
        default: return "number"
        }
    }

    // MARK: curve panel

    private struct CurveSample: Identifiable {
        let series: String
        let t: Double
        let ratePct: Double
        var id: String { "\(series)-\(t)" }
    }

    private func curveSamples(_ cd: CurveData) -> [CurveSample] {
        var s = cd.zero.map { CurveSample(series: "Zero", t: $0.t, ratePct: $0.rate * 100) }
        if showPar { s += cd.par.map { CurveSample(series: "Par", t: $0.t, ratePct: $0.rate * 100) } }
        if showForward { s += cd.forward.map { CurveSample(series: "Forward", t: $0.t, ratePct: $0.rate * 100) } }
        if vm.shiftBps != 0 {
            s += cd.zero.map { CurveSample(series: "Shifted", t: $0.t, ratePct: $0.rate * 100 + vm.shiftBps / 100) }
        }
        return s
    }

    private var cashflowTimes: [Double] { vm.result?.cashflows.map { $0.t } ?? [] }

    private func curvePanel(_ cd: CurveData) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("Curve · \(cd.label)", icon: "chart.xyaxis.line")
                    Spacer()
                    Toggle("Par", isOn: $showPar).toggleStyle(.button).controlSize(.small)
                    Toggle("Forward", isOn: $showForward).toggleStyle(.button).controlSize(.small)
                }
                Chart {
                    ForEach(curveSamples(cd)) { s in
                        LineMark(x: .value("Tenor", s.t), y: .value("Rate", s.ratePct))
                            .foregroundStyle(by: .value("Curve", s.series))
                            .interpolationMethod(.monotone)
                            .lineStyle(StrokeStyle(lineWidth: 2, dash: s.series == "Shifted" ? [4, 3] : []))
                    }
                    ForEach(cashflowTimes, id: \.self) { t in
                        RuleMark(x: .value("t", t))
                            .foregroundStyle(.gray.opacity(0.18))
                            .lineStyle(StrokeStyle(lineWidth: 1))
                    }
                }
                .chartForegroundStyleScale([
                    "Zero": Theme.accent, "Par": Theme.bucketColor("Rates"),
                    "Forward": Theme.bucketColor("FX"), "Shifted": Theme.warning,
                ])
                .chartXAxisLabel("Tenor (years)")
                .chartYAxisLabel("Rate (%)")
                .frame(height: 240)
                if !cashflowTimes.isEmpty {
                    Text("Vertical lines mark the bond's cashflow times.")
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                }
            }
        }
    }

    private var calculateBar: some View {
        HStack {
            if let message = vm.errorMessage, !vm.serverDown {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.negative).lineLimit(2)
            }
            Spacer()
            Button { Task { await vm.price() } } label: {
                HStack(spacing: Theme.s2) {
                    if vm.isPricing { ProgressView().controlSize(.small) }
                    Image(systemName: "bolt.fill").font(.system(size: 11))
                    Text(vm.isPricing ? "Pricing…" : "Price bond").fontWeight(.semibold)
                }
                .frame(minWidth: 140)
            }
            .controlSize(.large).buttonStyle(.borderedProminent).tint(Theme.accent)
            .keyboardShortcut(.return, modifiers: .command).disabled(vm.isPricing)
        }
    }

    // MARK: result

    @ViewBuilder
    private func resultSection(_ r: BondResult) -> some View {
        KPIStrip(items: priceCards(r))
        if !r.analytics.isEmpty { analyticsCard(r.analytics) }
        HStack(alignment: .top, spacing: Theme.s4) {
            if !r.cashflows.isEmpty { cashflowChart(r.cashflows) }
            if !r.keyRateDurations.isEmpty { krdChart(r.keyRateDurations) }
        }
        if !r.cashflows.isEmpty { cashflowTable(r.cashflows) }
        if !r.warnings.isEmpty { warningsCard(r.warnings) }
    }

    private func priceCards(_ r: BondResult) -> [KPICard] {
        var cards = [KPICard(label: "Value", value: fmt(r.value), sub: r.modelID,
                             accent: Theme.accent, icon: "banknote")]
        if let c = r.cleanPrice { cards.append(KPICard(label: "Clean price", value: Fmt.number(c, digits: 4), accent: Theme.bucketColor("Rates"), icon: "tag")) }
        if let d = r.dirtyPrice { cards.append(KPICard(label: "Dirty price", value: Fmt.number(d, digits: 4), accent: Theme.bucketColor("Rates"), icon: "tag.fill")) }
        if let a = r.accruedInterest { cards.append(KPICard(label: "Accrued", value: Fmt.number(a, digits: 4), accent: Theme.warning, icon: "clock")) }
        return cards
    }

    private func analyticsCard(_ rows: [AnalyticRow]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Risk & sensitivities", icon: "function")
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: Theme.s3)],
                          alignment: .leading, spacing: Theme.s3) {
                    ForEach(rows) { row in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(row.label).font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary).lineLimit(1)
                            Text(row.isRate ? Fmt.percent(row.value * 100, digits: 3) : Fmt.number(row.value, digits: 4))
                                .font(.system(size: 15, weight: .semibold)).monospacedDigit()
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(Theme.s3)
                        .background(Color(nsColor: .windowBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
        }
    }

    private func cashflowChart(_ cashflows: [Cashflow]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Cashflow schedule", icon: "chart.bar.fill")
                Chart(cashflows) { cf in
                    BarMark(x: .value("Time", cf.t), y: .value("Cashflow", cf.amount), width: .fixed(10))
                        .foregroundStyle(Theme.accent)
                        .cornerRadius(2)
                }
                .chartXAxisLabel("Time (years)")
                .frame(height: 200)
            }
        }
    }

    private func krdChart(_ krd: [KRDRow]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Key-rate durations", icon: "chart.bar.xaxis")
                Chart(krd) { k in
                    BarMark(x: .value("Tenor", "\(Fmt.number(k.tenor, digits: k.tenor < 1 ? 2 : 0))y"),
                            y: .value("KRD", k.value))
                        .foregroundStyle(Theme.trendColor(k.value))
                        .cornerRadius(2)
                }
                .chartXAxisLabel("Tenor")
                .frame(height: 200)
            }
        }
    }

    private func cashflowTable(_ cashflows: [Cashflow]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Cashflows", icon: "tablecells")
                Table(cashflows) {
                    TableColumn("Time (years)") { cf in
                        Text(Fmt.number(cf.t, digits: 4)).monospacedDigit()
                    }
                    TableColumn("Cashflow") { cf in
                        Text(Fmt.number(cf.amount, digits: 4)).monospacedDigit()
                    }
                }
                .frame(minHeight: 200)
            }
        }
    }

    private func warningsCard(_ warnings: [String]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s2) {
                BlockTitle("Model notes", icon: "info.circle")
                ForEach(warnings.prefix(4), id: \.self) { w in
                    Text("• \(w)").font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func fmt(_ v: Double?) -> String {
        v.map { Fmt.number($0, digits: 4) } ?? "—"
    }
}
