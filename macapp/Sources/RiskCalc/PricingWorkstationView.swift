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
                    stateStrip
                    HStack(spacing: Theme.s4) {
                        enginePicker(product)
                        environmentPicker
                    }
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
                            issuesCard
                            calculateButton
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)

                        VStack(spacing: Theme.s4) {
                            WorkstationResultPanel(vm: vm)
                            RunHistoryCard(vm: vm)
                        }
                        .frame(width: 360)
                    }
                    if vm.result != nil {
                        HStack(alignment: .top, spacing: Theme.s4) {
                            LadderCard(vm: vm)
                            ScenarioCard(vm: vm)
                        }
                        PayoffCard(vm: vm)
                        if vm.gridKeys != nil {
                            Grid2DCard(vm: vm)
                        }
                    }
                    conventionsFooter
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

    // MARK: workspace state strip (spec §6.1)

    /// Business lifecycle chips + staleness + technical state + input hash.
    /// Status is never colour-only: each state carries an icon and a label.
    private var stateStrip: some View {
        HStack(spacing: Theme.s2) {
            ForEach(WorkspaceBusinessState.allCases, id: \.self) { s in
                stateChip(s)
            }
            if vm.isStale {
                Label("Inputs изменены — результат устарел",
                      systemImage: "exclamationmark.arrow.circlepath")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Theme.warning)
                    .padding(.horizontal, Theme.s2).padding(.vertical, 3)
                    .background(Theme.warning.opacity(0.14), in: Capsule())
            }
            Spacer()
            switch vm.techState {
            case .validating:
                HStack(spacing: 4) {
                    ProgressView().controlSize(.mini)
                    Text("Валидация…").font(.system(size: 10)).foregroundStyle(.secondary)
                }
            case .running:
                HStack(spacing: 4) {
                    ProgressView().controlSize(.mini)
                    Text("Расчёт…").font(.system(size: 10)).foregroundStyle(.secondary)
                }
            case .failed:
                Label("Ошибка", systemImage: "xmark.octagon")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Theme.negative)
            case .idle:
                EmptyView()
            }
            Text("inputs \(String(vm.currentFingerprint.prefix(8)))")
                .font(.system(size: 9)).monospaced().foregroundStyle(.tertiary)
                .help("Локальный канонический fingerprint текущих inputs; авторитетный hash расчёта — в Provenance")
        }
    }

    private func stateChip(_ s: WorkspaceBusinessState) -> some View {
        let all = WorkspaceBusinessState.allCases
        let currentIdx = all.firstIndex(of: vm.businessState) ?? 0
        let idx = all.firstIndex(of: s) ?? 0
        let isCurrent = s == vm.businessState
        let reached = idx <= currentIdx
        return HStack(spacing: 4) {
            Image(systemName: reached && !isCurrent ? "checkmark" : s.icon)
                .font(.system(size: 9, weight: .semibold))
            Text(s.title).font(.system(size: 10, weight: isCurrent ? .semibold : .regular))
        }
        .foregroundStyle(isCurrent ? Color.white : (reached ? Theme.accent : .secondary))
        .padding(.horizontal, Theme.s2).padding(.vertical, 3)
        .background(isCurrent ? AnyShapeStyle(Theme.accent)
                              : AnyShapeStyle(Color.primary.opacity(reached ? 0.07 : 0.04)),
                    in: Capsule())
        .help(stateHelp(s))
    }

    private func stateHelp(_ s: WorkspaceBusinessState) -> String {
        switch s {
        case .draft:     return "Есть невалидированные изменения inputs"
        case .validated: return "Сервер подтвердил схему, типы и диапазоны текущих inputs"
        case .priced:    return "Для текущих inputs существует завершённый immutable-расчёт"
        case .captured:  return "Расчёт зафиксирован позицией в портфеле"
        }
    }

    /// Structured validation issues with a jump reference to the field key
    /// (spec §8.3) — shown between the form and the run control.
    @ViewBuilder
    private var issuesCard: some View {
        if !vm.issues.isEmpty {
            GlassCard {
                VStack(alignment: .leading, spacing: Theme.s2) {
                    BlockTitle("Валидация", icon: "checkmark.shield")
                    ForEach(vm.issues) { issue in
                        HStack(alignment: .top, spacing: Theme.s2) {
                            Image(systemName: issue.isError
                                  ? "xmark.octagon.fill" : "exclamationmark.triangle.fill")
                                .font(.system(size: 10))
                                .foregroundStyle(issue.isError ? Theme.negative : Theme.warning)
                                .padding(.top, 1)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(issue.message).font(.system(size: 11))
                                HStack(spacing: Theme.s2) {
                                    Text(issue.code)
                                        .font(.system(size: 9)).monospaced()
                                        .foregroundStyle(.tertiary)
                                    if let p = issue.param {
                                        Text("поле: \(p)")
                                            .font(.system(size: 9, weight: .semibold)).monospaced()
                                            .foregroundStyle(Theme.accent)
                                    }
                                }
                            }
                            Spacer()
                        }
                    }
                }
            }
        }
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

    /// Глобальные конвенции воркстейшена (A5): day count, начисление, seed,
    /// bump-размеры, источники σ/кривых — то, что раньше жило неявно.
    @State private var showConventions = false

    @ViewBuilder
    private var conventionsFooter: some View {
        if let conventions = vm.catalogue?.conventions, !conventions.isEmpty {
            GlassCard {
                DisclosureGroup(isExpanded: $showConventions) {
                    VStack(alignment: .leading, spacing: 5) {
                        ForEach(conventions, id: \.self) { c in
                            HStack(alignment: .top, spacing: 6) {
                                Circle().fill(.tertiary).frame(width: 4, height: 4)
                                    .padding(.top, 5)
                                Text(c).font(.system(size: 11)).foregroundStyle(.secondary)
                            }
                        }
                    }
                    .padding(.top, Theme.s2)
                } label: {
                    BlockTitle("Конвенции расчёта", icon: "ruler")
                }
            }
        }
    }

    /// Контур оценки (A1): FO/RISK/EOD/VAR/STRESS — задаёт снапшот, кривые
    /// ролей и дефолтные движки; запрос всегда побеждает контур.
    @ViewBuilder
    private var environmentPicker: some View {
        if !vm.environments.isEmpty {
            HStack(spacing: Theme.s2) {
                Text("Environment")
                    .font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                Picker("", selection: $vm.envID) {
                    ForEach(vm.environments) { env in
                        Text(env.envID).tag(env.envID)
                    }
                }
                .labelsHidden()
                .pickerStyle(.menu)
                .fixedSize()
                .help("Контур оценки: снапшот, кривые ролей и движки по умолчанию")
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

    // advanced-группы: model раскрыта (параметры движка — суть выбора),
    // numerical свёрнута (griды/пути редко трогают)
    @State private var expandedGroups: Set<String> = ["model"]

    @ViewBuilder
    private func paramGroup(_ engine: WsEngineModel, group: String) -> some View {
        let specs = engine.params.filter { $0.group == group }
        if !specs.isEmpty {
            let advanced = specs.allSatisfy(\.advanced)
            GlassCard {
                VStack(alignment: .leading, spacing: Theme.s3) {
                    if advanced {
                        Button {
                            withAnimation(.snappy(duration: 0.15)) {
                                if expandedGroups.contains(group) {
                                    expandedGroups.remove(group)
                                } else {
                                    expandedGroups.insert(group)
                                }
                            }
                        } label: {
                            HStack(spacing: Theme.s2) {
                                BlockTitle(groupTitles[group] ?? group,
                                           icon: groupIcons[group] ?? "circle")
                                Text("\(specs.count)")
                                    .font(.system(size: 9, weight: .semibold)).monospacedDigit()
                                    .foregroundStyle(.tertiary)
                                Spacer()
                                Image(systemName: expandedGroups.contains(group)
                                      ? "chevron.down" : "chevron.right")
                                    .font(.system(size: 10, weight: .semibold))
                                    .foregroundStyle(.tertiary)
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    } else {
                        BlockTitle(groupTitles[group] ?? group,
                                   icon: groupIcons[group] ?? "circle")
                    }
                    if !advanced || expandedGroups.contains(group) {
                        paramFields(specs)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func paramFields(_ specs: [ParamSpec]) -> some View {
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
                    // server-validation issue anchored to this field (spec §8.3)
                    if let issue = vm.issues.first(where: { $0.param == spec.key }) {
                        Label(issue.message, systemImage: "exclamationmark.circle.fill")
                            .font(.system(size: 9))
                            .foregroundStyle(issue.isError ? Theme.negative : Theme.warning)
                            .lineLimit(2)
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
            // Authoritative pre-run check without pricing (spec §7.5).
            Button {
                Task { await vm.validate() }
            } label: {
                Label("Validate", systemImage: "checkmark.shield")
            }
            .controlSize(.large)
            .disabled(vm.techState.isBusy || vm.isPricing)
            .help("Серверная валидация схемы, типов и диапазонов без запуска расчёта")
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

// MARK: - 2D what-if grid (spot × vol)

/// Full-revaluation P&L mesh over spot ±20% × vol ±10pt — the instrument-level
/// аналог портфельного what-if хитмапа.
private struct Grid2DCard: View {
    @Bindable var vm: WorkstationViewModel

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("What-if grid · spot × vol", icon: "square.grid.3x3.fill")
                    Spacer()
                    Button {
                        Task { await vm.loadGrid2d() }
                    } label: {
                        if vm.isLoadingGrid {
                            ProgressView().controlSize(.small)
                        } else {
                            Text(vm.grid2d == nil ? "Построить" : "Обновить")
                        }
                    }
                    .disabled(vm.isLoadingGrid)
                }
                if let g = vm.grid2d {
                    let maxAbs = max(1e-9, g.cells.compactMap { $0.pnl.map(abs) }.max() ?? 1)
                    Chart(g.cells, id: \.self) { c in
                        RectangleMark(
                            x: .value(g.xKey, xLabel(c.x)),
                            y: .value(g.yKey, yLabel(c.y))
                        )
                        .foregroundStyle(heatColor(c.pnl ?? 0, maxAbs: maxAbs))
                        .annotation(position: .overlay) {
                            Text(Fmt.number(c.pnl ?? 0, digits: 1))
                                .font(.system(size: 8, weight: .medium)).monospacedDigit()
                        }
                    }
                    .chartXAxisLabel("\(g.xKey) (спот)")
                    .chartYAxisLabel("\(g.yKey) (вола)")
                    .frame(height: 260)
                    Text("P&L против базы \(g.baseValue.map { Fmt.number($0, digits: 2) } ?? "—"); полная переоценка в \(g.nx)×\(g.ny) точках.")
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                } else if !vm.isLoadingGrid {
                    Text("Сетка P&L: спот ±20% × вола ±10 пунктов, полная переоценка выбранным движком.")
                        .font(.caption).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 50)
                }
            }
        }
    }

    private func xLabel(_ v: Double) -> String { Fmt.number(v, digits: 1) }
    private func yLabel(_ v: Double) -> String { Fmt.number(v, digits: 3) }

    private func heatColor(_ pnl: Double, maxAbs: Double) -> Color {
        let t = max(-1, min(1, pnl / maxAbs))
        return (t >= 0 ? Theme.positive : Theme.negative).opacity(0.15 + 0.7 * abs(t))
    }
}

// MARK: - Payoff diagram

/// Value today vs intrinsic at expiry over a ±50% spot range — the same
/// pricer, two ladders (T as-is / T→0).
private struct PayoffCard: View {
    @Bindable var vm: WorkstationViewModel

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("Payoff diagram", icon: "chart.line.flattrend.xyaxis")
                    Spacer()
                    Button {
                        Task { await vm.loadPayoff() }
                    } label: {
                        if vm.isLoadingPayoff {
                            ProgressView().controlSize(.small)
                        } else {
                            Text(vm.payoff == nil ? "Построить" : "Обновить")
                        }
                    }
                    .disabled(vm.isLoadingPayoff)
                }
                if let p = vm.payoff {
                    Chart {
                        ForEach(p.payoff, id: \.x) { pt in
                            LineMark(x: .value("Spot", pt.x), y: .value("Payoff", pt.y),
                                     series: .value("s", "At expiry"))
                                .foregroundStyle(Theme.negative.opacity(0.8))
                                .lineStyle(StrokeStyle(lineWidth: 1.2, dash: [5, 3]))
                        }
                        ForEach(p.value, id: \.x) { pt in
                            LineMark(x: .value("Spot", pt.x), y: .value("Value", pt.y),
                                     series: .value("s", "Today"))
                                .foregroundStyle(Theme.accent)
                                .interpolationMethod(.monotone)
                        }
                        RuleMark(x: .value("Spot", p.spot))
                            .foregroundStyle(.tertiary)
                            .lineStyle(StrokeStyle(lineWidth: 0.5, dash: [3]))
                            .annotation(position: .top, alignment: .leading) {
                                Text("spot").font(.system(size: 9)).foregroundStyle(.tertiary)
                            }
                    }
                    .frame(height: 200)
                    HStack(spacing: Theme.s3) {
                        legendLine(Theme.accent, "Стоимость сегодня")
                        legendLine(Theme.negative.opacity(0.8), "Payoff на экспирации")
                        Spacer()
                        Text("Временная стоимость = зазор между линиями")
                            .font(.system(size: 10)).foregroundStyle(.tertiary)
                    }
                } else if !vm.isLoadingPayoff {
                    Text("Профиль стоимости по споту ±50%: сегодня и на экспирации (тем же прайсером).")
                        .font(.caption).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 60)
                }
            }
        }
    }

    private func legendLine(_ color: Color, _ text: String) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 14, height: 3)
            Text(text).font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }
}

// MARK: - Result panel

private struct WorkstationResultPanel: View {
    @Bindable var vm: WorkstationViewModel

    var body: some View {
        GlassCard {
            if let r = vm.result {
                VStack(alignment: .leading, spacing: Theme.s3) {
                    // A stale result must never look current (spec §6.2):
                    // explicit banner + dimmed content until re-run.
                    if vm.isStale {
                        Label("УСТАРЕЛ — inputs изменены; Calculate пересчитает",
                              systemImage: "exclamationmark.arrow.circlepath")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(Theme.warning)
                            .padding(Theme.s2)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Theme.warning.opacity(0.14),
                                        in: RoundedRectangle(cornerRadius: 6))
                    }
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
                    HStack {
                        Text(r.modelID).font(.caption).foregroundStyle(.tertiary)
                        if let env = r.environment {
                            Text(env)
                                .font(.system(size: 9, weight: .semibold))
                                .foregroundStyle(Theme.accent)
                                .padding(.horizontal, 5).padding(.vertical, 1)
                                .background(Theme.accent.opacity(0.12), in: Capsule())
                                .help("Контур оценки")
                        }
                        Spacer()
                        Button {
                            vm.exportCSV()
                        } label: {
                            Label("CSV", systemImage: "square.and.arrow.up")
                                .font(.system(size: 10))
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                        .help("Экспорт параметров и результата в CSV")
                    }

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
                    if let prov = r.provenance {
                        Divider()
                        provenanceSection(prov)
                    }
                    if vm.supportsImpliedVol {
                        Divider()
                        impliedVolRow
                    }
                    if vm.selectedProduct?.capturable == true {
                        Divider()
                        captureRow
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

    /// Implied vol: invert a market premium into σ (BSM / Garman-Kohlhagen)
    /// and pour it back into the form.
    @ViewBuilder
    private var impliedVolRow: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack(spacing: Theme.s2) {
                Text("Рыночная цена")
                    .font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                TextField("", value: $vm.impliedPrice, format: .number)
                    .textFieldStyle(.roundedBorder).frame(width: 90).monospacedDigit()
                Spacer()
                Button("Implied vol") {
                    Task { await vm.solveImpliedVol() }
                }
                .disabled(vm.impliedPrice <= 0)
            }
            if let msg = vm.impliedVolResult {
                Text(msg).font(.system(size: 10))
                    .foregroundStyle(msg.hasPrefix("σ") ? Theme.positive : Theme.negative)
            }
        }
    }

    /// Trade capture: quantity + "В портфель" — the priced instrument becomes
    /// a persistent book position revalued by the portfolio layer.
    @ViewBuilder
    private var captureRow: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack(spacing: Theme.s2) {
                Text("Qty")
                    .font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                TextField("", value: $vm.captureQuantity, format: .number)
                    .textFieldStyle(.roundedBorder).frame(width: 90).monospacedDigit()
                Spacer()
                Button {
                    Task { await vm.addToPortfolio() }
                } label: {
                    HStack(spacing: 4) {
                        if vm.isCapturing { ProgressView().controlSize(.mini) }
                        Image(systemName: "plus.circle.fill").font(.system(size: 11))
                        Text("В портфель")
                    }
                }
                // Capture attaches to the exact priced run: edited (stale)
                // inputs must be re-run first (spec §7.7 invariant).
                .disabled(vm.isCapturing
                          || (vm.businessState != .priced && vm.businessState != .captured))
                .help(vm.businessState == .priced || vm.businessState == .captured
                      ? "Зафиксировать позицию по текущему расчёту"
                      : "Сначала Calculate: capture относится к конкретному расчёту, а не к форме")
            }
            if let msg = vm.captureMessage {
                Text(msg)
                    .font(.system(size: 10))
                    .foregroundStyle(msg.hasPrefix("✓") ? Theme.positive : Theme.negative)
            }
            HStack(spacing: Theme.s2) {
                Button {
                    Task { await vm.runIncrementalVaR() }
                } label: {
                    HStack(spacing: 4) {
                        if vm.isRunningIncremental { ProgressView().controlSize(.mini) }
                        Image(systemName: "plus.forwardslash.minus").font(.system(size: 10))
                        Text("What-if VaR").font(.system(size: 11))
                    }
                }
                .disabled(vm.isRunningIncremental)
                .help("Incremental VaR: VaR(книга + сделка) − VaR(книга), без записи в портфель")
                Spacer()
            }
            if let ivar = vm.incrementalVaR {
                VStack(alignment: .leading, spacing: 2) {
                    KeyValueRow(key: "Incremental VaR \(Int(ivar.confidence * 100))%",
                                value: Fmt.money(ivar.incrementalVaR),
                                valueColor: ivar.incrementalVaR > 0 ? Theme.negative : Theme.positive)
                    KeyValueRow(key: "Standalone VaR", value: Fmt.money(ivar.standaloneVaR))
                    KeyValueRow(key: "Diversification",
                                value: Fmt.money(ivar.diversificationBenefit),
                                valueColor: Theme.positive)
                }
            }
        }
    }

    /// Immutable evidence of the displayed run (spec §7.6): calculation ID,
    /// the server-authoritative inputs hash, snapshot lineage and model
    /// version/owner. Nothing here is client-invented.
    @ViewBuilder
    private func provenanceSection(_ p: WsProvenance) -> some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack {
                Text("PROVENANCE").font(.system(size: 10, weight: .semibold))
                    .tracking(0.5).foregroundStyle(.secondary)
                Spacer()
                if p.productionAllowed {
                    Pill(text: "production", color: Theme.positive)
                } else {
                    Pill(text: "research", color: Theme.warning)
                }
            }
            VStack(alignment: .leading, spacing: 3) {
                provRow("Calculation", String(p.calculationID.suffix(12)), full: p.calculationID)
                provRow("Inputs hash", String(p.inputsHash.prefix(12)) + "…", full: p.inputsHash)
                provRow("Snapshot", p.snapshotID, full: p.snapshotID)
                provRow("Data", [p.source, p.quality].filter { !$0.isEmpty }
                            .joined(separator: " · "), full: nil)
                provRow("Model", "v\(p.modelVersion) · \(p.modelOwner)", full: nil)
                if !p.valuationTime.isEmpty {
                    provRow("Valued at", String(p.valuationTime.prefix(19))
                                .replacingOccurrences(of: "T", with: " ") + " UTC",
                            full: p.valuationTime)
                }
            }
        }
    }

    private func provRow(_ key: String, _ value: String, full: String?) -> some View {
        HStack(alignment: .top) {
            Text(key).font(.system(size: 10)).foregroundStyle(.secondary)
                .frame(width: 78, alignment: .leading)
            Text(value.isEmpty ? "—" : value)
                .font(.system(size: 10)).monospaced()
                .textSelection(.enabled)
                .lineLimit(1)
            Spacer(minLength: 0)
        }
        .help(full ?? value)
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
    fileprivate func seriesChart(_ series: WsSeries) -> some View {
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

// MARK: - Run history

/// Immutable run log of the workspace (spec §7.5): every completed calculation
/// with its evidence hash; selecting an entry restores the exact inputs and
/// shows that run's result again.
private struct RunHistoryCard: View {
    @Bindable var vm: WorkstationViewModel

    var body: some View {
        if !vm.runHistory.isEmpty {
            GlassCard {
                VStack(alignment: .leading, spacing: Theme.s2) {
                    BlockTitle("История расчётов", icon: "clock.arrow.circlepath")
                    ForEach(vm.runHistory.prefix(8)) { run in
                        runRow(run)
                    }
                    if vm.runHistory.count > 8 {
                        Text("… ещё \(vm.runHistory.count - 8)")
                            .font(.system(size: 9)).foregroundStyle(.tertiary)
                    }
                }
            }
        }
    }

    private func runRow(_ run: PricingRunRecord) -> some View {
        let isCurrent = vm.currentRun?.id == run.id && !vm.isStale
        return Button {
            vm.restore(run)
        } label: {
            HStack(spacing: Theme.s2) {
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 4) {
                        Text(run.timestamp, format: .dateTime.hour().minute().second())
                            .font(.system(size: 10, weight: .medium)).monospacedDigit()
                        Text(run.engineName)
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    HStack(spacing: 4) {
                        Text(run.shortHash)
                            .font(.system(size: 8)).monospaced().foregroundStyle(.tertiary)
                        if let env = run.envID {
                            Text(env).font(.system(size: 8, weight: .semibold))
                                .foregroundStyle(Theme.accent)
                        }
                    }
                }
                Spacer(minLength: Theme.s2)
                Text(run.result.value.map { Fmt.number($0, digits: 4) } ?? "—")
                    .font(.system(size: 11, weight: .semibold)).monospacedDigit()
                if isCurrent {
                    Pill(text: "текущий", color: Theme.positive)
                }
            }
            .padding(.horizontal, Theme.s2).padding(.vertical, 4)
            .background(isCurrent ? Theme.accent.opacity(0.08) : .clear,
                        in: RoundedRectangle(cornerRadius: 6))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("Восстановить точные inputs этого расчёта (fingerprint \(run.shortHash))")
    }
}
