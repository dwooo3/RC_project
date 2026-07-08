import SwiftUI
import Charts

/// Universal pricing workstation: every pricer in the model library, grouped
/// by asset class, with an engine selector, market-data underlying autofill,
/// a generic grouped parameter form and a measure/series-aware result panel.
struct PricingWorkstationView: View {
    @State private var vm = WorkstationViewModel()

    var body: some View {
        Group {
            if vm.serverDown {
                ServerDownView(message: vm.errorMessage) { Task { await vm.load() } }
            } else {
                HStack(spacing: 0) {
                    productRail
                    Divider()
                    workArea
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await vm.load() }
    }

    // MARK: product rail

    private var productRail: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s4) {
                ForEach(vm.railSections, id: \.assetClass.id) { section in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(section.assetClass.label.uppercased())
                            .font(.system(size: 10, weight: .semibold)).tracking(0.5)
                            .foregroundStyle(.tertiary)
                            .padding(.horizontal, Theme.s2)
                        ForEach(section.products) { product in
                            productRow(product)
                        }
                    }
                }
            }
            .padding(Theme.s3)
        }
        .frame(width: 250)
        .background(Color(nsColor: .windowBackgroundColor).opacity(0.5))
        .overlay {
            if vm.isLoading && vm.products.isEmpty {
                ProgressView().controlSize(.small)
            }
        }
    }

    private func productRow(_ product: WsProductModel) -> some View {
        let selected = vm.productID == product.id
        let status = product.engines.first?.governance.status ?? ""
        return Button {
            vm.selectProduct(product.id)
        } label: {
            HStack(spacing: Theme.s2) {
                Circle().fill(Theme.statusColor(status)).frame(width: 7, height: 7)
                Text(product.name)
                    .font(.system(size: 13, weight: selected ? .semibold : .regular))
                    .foregroundStyle(selected ? Theme.accent : .primary)
                    .lineLimit(1)
                Spacer(minLength: 0)
                if product.engines.count > 1 {
                    Text("\(product.engines.count)")
                        .font(.system(size: 9, weight: .semibold)).monospacedDigit()
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(Color.secondary.opacity(0.12), in: Capsule())
                        .help("\(product.engines.count) движков")
                }
            }
            .padding(.horizontal, Theme.s3).padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selected ? Theme.accent.opacity(0.14) : .clear,
                        in: RoundedRectangle(cornerRadius: 7))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: work area

    @ViewBuilder
    private var workArea: some View {
        if let product = vm.selectedProduct, let engine = vm.selectedEngine {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s5) {
                    PageHeader(product.name, subtitle: governanceLine(engine)) {
                        StatusChip(status: engine.governance.status)
                    }
                    enginePicker(product)
                    if !product.note.isEmpty {
                        Label(product.note, systemImage: "info.circle")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    HStack(alignment: .top, spacing: Theme.s4) {
                        VStack(alignment: .leading, spacing: Theme.s4) {
                            if product.underlying != nil {
                                UnderlyingPickerCard(vm: vm)
                            }
                            ForEach(["contract", "market", "model", "numerical"], id: \.self) { group in
                                paramGroup(engine, group: group)
                            }
                            calculateButton
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)

                        WorkstationResultPanel(vm: vm)
                            .frame(width: 360)
                    }
                    if vm.result != nil {
                        HStack(alignment: .top, spacing: Theme.s4) {
                            LadderCard(vm: vm)
                            ScenarioCard(vm: vm)
                        }
                    }
                }
                .padding(Theme.s5)
                .frame(maxWidth: 1240, alignment: .leading)
            }
            .frame(maxWidth: .infinity)
        } else {
            ContentUnavailableView("Select an instrument", systemImage: "function")
        }
    }

    private func governanceLine(_ engine: WsEngineModel) -> String {
        [engine.governance.assetClass, engine.governance.modelFamily,
         engine.governance.method]
            .filter { !$0.isEmpty }.joined(separator: " · ")
    }

    @ViewBuilder
    private func enginePicker(_ product: WsProductModel) -> some View {
        if product.engines.count > 1 {
            HStack(spacing: Theme.s2) {
                Text("Model")
                    .font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                Picker("", selection: Binding(
                    get: { vm.engineID ?? product.engines.first?.id ?? "" },
                    set: { vm.selectEngine($0) }
                )) {
                    ForEach(product.engines) { engine in
                        Text(engine.name).tag(engine.id)
                    }
                }
                .labelsHidden()
                .pickerStyle(.menu)
                .fixedSize()
                if let engine = vm.selectedEngine {
                    Circle().fill(Theme.statusColor(engine.governance.status))
                        .frame(width: 7, height: 7)
                    Text(engine.governance.status)
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
            }
        }
    }

    private let groupTitles = [
        "contract": "Contract", "market": "Market",
        "model": "Model parameters", "numerical": "Numerical",
    ]
    private let groupIcons = [
        "contract": "doc.text", "market": "globe",
        "model": "slider.horizontal.3", "numerical": "number",
    ]

    @ViewBuilder
    private func paramGroup(_ engine: WsEngineModel, group: String) -> some View {
        let specs = engine.params.filter { $0.group == group }
        if !specs.isEmpty {
            GlassCard {
                VStack(alignment: .leading, spacing: Theme.s3) {
                    BlockTitle(groupTitles[group] ?? group,
                               icon: groupIcons[group] ?? "circle")
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: Theme.s3)],
                              alignment: .leading, spacing: Theme.s3) {
                        ForEach(specs) { spec in
                            VStack(alignment: .leading, spacing: 2) {
                                if spec.dtype == "float" || spec.dtype == "int" {
                                    ParamFieldView(spec: spec,
                                                   numeric: vm.numericBinding(spec.key),
                                                   string: nil)
                                } else {
                                    ParamFieldView(spec: spec, numeric: nil,
                                                   string: vm.choiceBinding(spec.key))
                                }
                                if vm.autofilledKeys.contains(spec.key) {
                                    Label("из маркет даты", systemImage: "arrow.down.circle.fill")
                                        .font(.system(size: 9))
                                        .foregroundStyle(Theme.accent)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private var calculateButton: some View {
        HStack {
            if let message = vm.errorMessage, !vm.serverDown {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.negative).lineLimit(2)
            }
            Spacer()
            Button {
                Task { await vm.price() }
            } label: {
                HStack(spacing: Theme.s2) {
                    if vm.isPricing { ProgressView().controlSize(.small) }
                    Image(systemName: "bolt.fill").font(.system(size: 11))
                    Text(vm.isPricing ? "Pricing…" : "Calculate").fontWeight(.semibold)
                }
                .frame(minWidth: 130)
            }
            .controlSize(.large)
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.return, modifiers: .command)
            .disabled(vm.isPricing)
        }
    }
}

// MARK: - Underlying picker

/// Search-as-you-type picker over the market-data store; a selection pulls
/// /pricing/underlying facts and pours them into the parameter form.
private struct UnderlyingPickerCard: View {
    @Bindable var vm: WorkstationViewModel
    @FocusState private var focused: Bool

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Базовый актив", icon: "link")
                if let sel = vm.selectedUnderlying {
                    HStack(spacing: Theme.s2) {
                        Pill(text: sel.secid, color: Theme.accent, filled: true)
                        Text(sel.label).font(.system(size: 12)).lineLimit(1)
                        if let ccy = sel.currency {
                            Text(ccy).font(.caption2).foregroundStyle(.tertiary)
                        }
                        Spacer()
                        Button {
                            vm.clearUnderlying()
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.tertiary)
                        }
                        .buttonStyle(.plain)
                    }
                    if !vm.autofilledKeys.isEmpty {
                        Text("Заполнено: \(vm.autofilledKeys.joined(separator: ", "))")
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                } else {
                    HStack(spacing: Theme.s2) {
                        Image(systemName: "magnifyingglass")
                            .font(.system(size: 11)).foregroundStyle(.tertiary)
                        TextField("SECID / ISIN / эмитент…",
                                  text: Binding(get: { vm.underlyingQuery },
                                                set: { vm.searchUnderlying($0) }))
                            .textFieldStyle(.plain)
                            .font(.system(size: 12))
                            .focused($focused)
                        if vm.isSearching { ProgressView().controlSize(.mini) }
                    }
                    .padding(.horizontal, Theme.s3).padding(.vertical, 7)
                    .background(Color(nsColor: .controlBackgroundColor),
                                in: RoundedRectangle(cornerRadius: 7))
                    if !vm.underlyingHits.isEmpty {
                        VStack(spacing: 0) {
                            ForEach(vm.underlyingHits.prefix(6)) { hit in
                                Button {
                                    Task { await vm.pickUnderlying(hit) }
                                } label: {
                                    HStack(spacing: Theme.s2) {
                                        Text(hit.secid)
                                            .font(.system(size: 12, weight: .semibold))
                                            .monospaced()
                                        Text(hit.issuerRu ?? "")
                                            .font(.system(size: 11))
                                            .foregroundStyle(.secondary).lineLimit(1)
                                        Spacer()
                                        if let last = hit.last {
                                            Text(Fmt.number(last, digits: 2))
                                                .font(.system(size: 11)).monospacedDigit()
                                        }
                                        Text(hit.category ?? "")
                                            .font(.system(size: 9))
                                            .foregroundStyle(.tertiary)
                                    }
                                    .padding(.horizontal, Theme.s2).padding(.vertical, 5)
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    Text("Спот, волатильность, дивиденды и ставка подтянутся из стора")
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                }
            }
        }
    }
}

// MARK: - Desk risk: ladder

/// Full-revaluation sensitivity ladder over any numeric input of the pricer.
private struct LadderCard: View {
    @Bindable var vm: WorkstationViewModel

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Sensitivity ladder", icon: "chart.line.uptrend.xyaxis")
                HStack(spacing: Theme.s2) {
                    Picker("", selection: Binding(
                        get: { vm.ladderKey ?? "" },
                        set: { vm.selectLadderKey($0) }
                    )) {
                        Text("— параметр —").tag("")
                        ForEach(vm.ladderableParams) { spec in
                            Text(spec.label).tag(spec.key)
                        }
                    }
                    .labelsHidden().pickerStyle(.menu).fixedSize()

                    TextField("от", value: $vm.ladderLo, format: .number)
                        .textFieldStyle(.roundedBorder).frame(width: 80).monospacedDigit()
                    Text("–").foregroundStyle(.tertiary)
                    TextField("до", value: $vm.ladderHi, format: .number)
                        .textFieldStyle(.roundedBorder).frame(width: 80).monospacedDigit()

                    Button {
                        Task { await vm.runLadder() }
                    } label: {
                        if vm.isRunningLadder {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("Run")
                        }
                    }
                    .disabled(vm.ladderKey == nil || vm.isRunningLadder)
                    Spacer()
                }
                if let ladder = vm.ladder {
                    let pts = ladder.rows.filter { $0.pnl != nil }
                    Chart(pts, id: \.x) { row in
                        LineMark(x: .value(ladder.bumpKey, row.x),
                                 y: .value("P&L", row.pnl ?? 0))
                            .foregroundStyle(Theme.accent)
                            .interpolationMethod(.monotone)
                        AreaMark(x: .value(ladder.bumpKey, row.x),
                                 y: .value("P&L", row.pnl ?? 0))
                            .foregroundStyle(
                                LinearGradient(colors: [Theme.accent.opacity(0.18), .clear],
                                               startPoint: .top, endPoint: .bottom))
                            .interpolationMethod(.monotone)
                        RuleMark(y: .value("zero", 0))
                            .foregroundStyle(.tertiary)
                            .lineStyle(StrokeStyle(lineWidth: 0.5, dash: [3]))
                    }
                    .frame(height: 180)
                    Text("Полная переоценка тем же прайсером в \(ladder.rows.count) точках; P&L против базового значения \(ladder.baseValue.map { Fmt.number($0, digits: 2) } ?? "—").")
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                } else {
                    Text("Выберите параметр (спот, вола, ставка, корреляция…) и постройте P&L-профиль полной переоценкой.")
                        .font(.caption).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 120)
                }
            }
        }
    }
}

// MARK: - Desk risk: scenario simulation

/// The named historical macro-scenario library revalued through the pricer.
private struct ScenarioCard: View {
    @Bindable var vm: WorkstationViewModel

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("Scenario simulation", icon: "waveform.path.ecg")
                    Spacer()
                    Button {
                        Task { await vm.runScenarios() }
                    } label: {
                        if vm.isRunningScenarios {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("Run")
                        }
                    }
                    .disabled(vm.isRunningScenarios)
                }
                if let scenarios = vm.scenarios {
                    let rows = scenarios.rows.sorted { ($0.pnl ?? 0) < ($1.pnl ?? 0) }
                    VStack(spacing: 3) {
                        ForEach(rows) { row in
                            HStack(spacing: Theme.s2) {
                                Text(row.scenario)
                                    .font(.system(size: 11)).lineLimit(1)
                                Spacer()
                                Text(shockLine(row))
                                    .font(.system(size: 9)).foregroundStyle(.tertiary)
                                Text(row.pnl.map { Fmt.number($0, digits: 2) } ?? "—")
                                    .font(.system(size: 11, weight: .semibold)).monospacedDigit()
                                    .foregroundStyle(Theme.trendColor(row.pnl ?? 0))
                                    .frame(width: 86, alignment: .trailing)
                                Text(row.pnlPct.map { Fmt.signedPercent($0 * 100) } ?? "")
                                    .font(.system(size: 10)).monospacedDigit()
                                    .foregroundStyle(Theme.trendColor(row.pnl ?? 0))
                                    .frame(width: 56, alignment: .trailing)
                            }
                            .padding(.vertical, 2)
                        }
                    }
                    Text("Исторические макро-шоки (спот/вола относительные, ставка абсолютная) → полная переоценка. База: \(scenarios.baseValue.map { Fmt.number($0, digits: 2) } ?? "—").")
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                } else {
                    Text("14 именованных исторических сценариев — от Black Monday до COVID — через полную переоценку инструмента.")
                        .font(.caption).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 120)
                }
            }
        }
    }

    private func shockLine(_ row: WsScenarioRow) -> String {
        var parts: [String] = []
        if row.spotShock != 0 { parts.append("S \(Fmt.signedPercent(row.spotShock * 100))") }
        if row.volShock != 0 { parts.append("σ \(Fmt.signedPercent(row.volShock * 100))") }
        if row.rateShock != 0 { parts.append("r \(String(format: "%+.0f", row.rateShock * 10000))bp") }
        return parts.joined(separator: "  ")
    }
}

// MARK: - Result panel

private struct WorkstationResultPanel: View {
    let vm: WorkstationViewModel

    var body: some View {
        GlassCard {
            if let r = vm.result {
                VStack(alignment: .leading, spacing: Theme.s3) {
                    HStack {
                        Text("PRESENT VALUE").font(.system(size: 10, weight: .semibold))
                            .tracking(0.5).foregroundStyle(.secondary)
                        Spacer()
                        StatusChip(status: r.modelStatus)
                    }
                    Text(r.value.map { Fmt.number($0, digits: 4) } ?? "—")
                        .font(.system(size: 30, weight: .bold)).monospacedDigit()
                        .foregroundStyle(r.value == nil ? Color.secondary : Theme.accent)
                        .lineLimit(1).minimumScaleFactor(0.5)
                    Text(r.modelID).font(.caption).foregroundStyle(.tertiary)

                    if !r.greeks.isEmpty {
                        Divider()
                        measureGrid("GREEKS / SENSITIVITIES", r.greeks)
                    }
                    if !r.measures.isEmpty {
                        Divider()
                        measureGrid("MEASURES", r.measures)
                    }
                    ForEach(r.series) { series in
                        Divider()
                        seriesChart(series)
                    }
                    if !r.warnings.isEmpty {
                        Divider()
                        ForEach(r.warnings.prefix(3), id: \.self) { w in
                            Label(w, systemImage: "exclamationmark.triangle")
                                .font(.system(size: 10)).foregroundStyle(.secondary)
                                .padding(Theme.s2)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(Theme.warning.opacity(0.12),
                                            in: RoundedRectangle(cornerRadius: 6))
                        }
                    }
                }
            } else {
                VStack(spacing: Theme.s3) {
                    Image(systemName: "chart.line.uptrend.xyaxis")
                        .font(.system(size: 32)).foregroundStyle(.tertiary)
                    Text("No valuation yet").font(.system(size: 15, weight: .semibold))
                    Text("Press Calculate (⌘↵).").font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 220)
            }
        }
    }

    @ViewBuilder
    private func measureGrid(_ title: String, _ items: [WsMeasure]) -> some View {
        Text(title).font(.system(size: 10, weight: .semibold))
            .tracking(0.5).foregroundStyle(.secondary)
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: Theme.s2),
                                 count: 2), spacing: Theme.s2) {
            ForEach(items.prefix(14)) { m in
                MetricCell(name: m.label, value: m.value)
            }
        }
    }

    @ViewBuilder
    private func seriesChart(_ series: WsSeries) -> some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            Text(series.label.uppercased())
                .font(.system(size: 10, weight: .semibold))
                .tracking(0.5).foregroundStyle(.secondary)
            if series.key == "cashflows" || series.points.count <= 3 {
                Chart(series.points, id: \.x) { pt in
                    BarMark(x: .value("t", pt.x), y: .value(series.label, pt.y))
                        .foregroundStyle(Theme.accent.gradient)
                        .cornerRadius(2)
                }
                .frame(height: 110)
            } else {
                Chart(series.points, id: \.x) { pt in
                    LineMark(x: .value("t", pt.x), y: .value(series.label, pt.y))
                        .foregroundStyle(Theme.accent)
                        .interpolationMethod(.monotone)
                    AreaMark(x: .value("t", pt.x), y: .value(series.label, pt.y))
                        .foregroundStyle(Theme.accent.opacity(0.08))
                        .interpolationMethod(.monotone)
                }
                .chartYScale(domain: .automatic(includesZero: false))
                .frame(height: 110)
            }
        }
    }
}
