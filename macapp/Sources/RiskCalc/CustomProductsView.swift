import SwiftUI

/// Custom Product Engine (spec §16), template mode: definitions render purely
/// from their slot schema — Phoenix/autocall needs zero product-specific code.
@MainActor
@Observable
final class CustomProductsViewModel {
    let client = BridgeClient()

    var templates: [CustomProductSummary] = []
    var products: [CustomProductSummary] = []
    var selectedID: String?
    var detail: CustomProductDetail?
    var slotValues: [String: Double] = [:]

    // market context for the generic MC evaluator
    var marketR: Double = 0.05
    var marketQ: Double = 0.0
    var marketSigma: Double = 0.25
    /// Per-asset market inputs used by the correlated-GBM evaluator.
    var marketSigmas: [Double] = []
    var marketQs: [Double] = []
    var marketCorrelation: [[Double]] = []
    /// Default for correlation cells created when an asset is appended.
    var marketRho: Double = 0.5
    var nSims: Double = 50_000
    var mcSteps: Double = 252
    var seed: Double = 42

    var assetNames: [String] {
        let names = editor?.assets.isEmpty == false
            ? editor?.assets : detail?.definition.assetNames
        return (names?.isEmpty == false ? names! : ["S"]).enumerated().map {
            let trimmed = $0.element.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? "Asset \($0.offset + 1)" : trimmed
        }
    }

    var engineLabel: String {
        assetNames.count > 1 ? "custom_mc_multi_gbm" : "custom_mc_gbm"
    }

    var valuationIssues: [String] {
        CustomMarketInputGrid.validationIssues(
            sigmas: marketSigmas, qs: marketQs,
            correlation: marketCorrelation, assetCount: assetNames.count,
            rate: marketR, nSims: nSims, steps: mcSteps, seed: seed)
    }

    var author: String = NSUserName().isEmpty ? "trader" : NSUserName()
    var approver: String = "risk-control"

    var priceResult: CustomPriceResult?
    var isBusy = false
    var isPricing = false
    var message: String?

    func load() async {
        do {
            templates = try await client.customTemplates()
            products = try await client.customProducts()
            if selectedID == nil, let first = products.first {
                await select(first.id)
            }
        } catch {
            message = error.localizedDescription
        }
    }

    /// Advanced editor document for the selected product (full AST).
    var editor: EDefinition?
    /// Canonical local JSON of the definition last loaded/saved on the server.
    /// The server definition remains authoritative for pricing and lifecycle.
    private var savedEditorJSON: Data?

    var isEditorDirty: Bool {
        guard let editor, let savedEditorJSON,
              let current = canonicalEditorJSON(editor) else { return false }
        return current != savedEditorJSON
    }

    func select(_ id: String) async {
        selectedID = id
        priceResult = nil
        message = nil
        editor = nil
        savedEditorJSON = nil
        do {
            let d = try await client.customProduct(id)
            detail = d
            slotValues = d.definition.slots.mapValues(\.defaultValue)
            marketSigmas = []
            marketQs = []
            marketCorrelation = []
            synchronizeMarketInputs(assetCount: d.definition.assetNames.count)
            let raw = try await client.customProductRaw(id)
            if let obj = try JSONSerialization.jsonObject(with: raw) as? [String: Any],
               let definition = obj["definition"] as? [String: Any] {
                editor = EDefinition.fromJSON(definition)
                savedEditorJSON = editor.flatMap(canonicalEditorJSON)
                synchronizeMarketInputs(assetCount: editor?.assets.count ?? 1)
            }
        } catch {
            message = error.localizedDescription
        }
    }

    /// Advanced mode: blank definition assembled entirely in the editor.
    func createAdvanced() async {
        isBusy = true
        message = nil
        do {
            let skeleton: [String: Any] = [
                "name": "Новый продукт",
                "description": "Собран в advanced-конструкторе",
                "author": author,
                "slots": ["T": ["label": "Maturity, y", "default": 1.0,
                                "min": 0.25, "max": 10.0]],
                "state": [:],
                "schedule": ["observations": 4, "maturity": ["slot": "T"]],
                "observation_program": [],
                "maturity_program": [["action": "pay",
                                      "amount": ["node": "const", "value": 1.0]]],
            ]
            let body = try JSONSerialization.data(
                withJSONObject: ["definition": skeleton, "author": author])
            let created = try await client.customCreateRaw(body)
            products = try await client.customProducts()
            await select(created.id)
        } catch {
            message = error.localizedDescription
        }
        isBusy = false
    }

    /// PUT the edited document, then run the authoritative server compile.
    func saveAndCompile() async {
        guard let id = selectedID, let editor else { return }
        isBusy = true
        message = nil
        do {
            let body = try JSONSerialization.data(
                withJSONObject: ["definition": editor.toJSON()])
            _ = try await client.customUpdateDefinition(id, body: body)
            detail = try await client.customCompile(id)
            products = try await client.customProducts()
            if let d = detail {
                slotValues = d.definition.slots.mapValues(\.defaultValue)
                synchronizeMarketInputs(assetCount: d.definition.assetNames.count)
            }
            savedEditorJSON = canonicalEditorJSON(editor)
        } catch {
            message = error.localizedDescription
        }
        isBusy = false
    }

    func createFromTemplate(_ template: CustomProductSummary) async {
        isBusy = true
        message = nil
        do {
            let created = try await client.customCreate(
                templateID: template.id,
                name: "\(template.name) · копия",
                author: author, slotDefaults: [:])
            products = try await client.customProducts()
            await select(created.id)
        } catch {
            message = error.localizedDescription
        }
        isBusy = false
    }

    /// One lifecycle transition; every error lands in `message`, never lost.
    func lifecycle(_ op: @escaping () async throws -> CustomProductDetail) async {
        guard !isEditorDirty else {
            message = "Есть несохранённые изменения payout. Сначала сохраните и скомпилируйте определение."
            return
        }
        isBusy = true
        message = nil
        do {
            detail = try await op()
            products = try await client.customProducts()
        } catch {
            message = error.localizedDescription
        }
        isBusy = false
    }

    func price() async {
        guard let id = selectedID else { return }
        synchronizeMarketInputs()
        guard !isEditorDirty else {
            message = "Расчёт заблокирован: payout на экране не сохранён на сервере."
            return
        }
        guard valuationIssues.isEmpty else {
            message = valuationIssues.joined(separator: " ")
            return
        }
        guard let submittedPaths = Int(exactly: nSims),
              let submittedSteps = Int(exactly: mcSteps),
              let submittedSeed = Int(exactly: seed) else {
            message = "Numerical controls не представимы как целые числа."
            return
        }
        isPricing = true
        message = nil
        priceResult = nil
        var market = CustomMarketPayload(r: marketR)
        if assetNames.count > 1 {
            market.sigmas = marketSigmas
            market.qs = marketQs
            market.corr = marketCorrelation
        } else {
            market.sigma = marketSigmas.first ?? marketSigma
            market.q = marketQs.first ?? marketQ
        }
        do {
            priceResult = try await client.customPrice(
                id, slots: slotValues, market: market,
                nSims: submittedPaths, steps: submittedSteps,
                seed: submittedSeed)
        } catch {
            message = error.localizedDescription
        }
        isPricing = false
    }

    /// Keep vector/matrix dimensions equal to the current definition. Existing
    /// leading values survive resize; newly created pairs use `marketRho`.
    func synchronizeMarketInputs(assetCount requestedCount: Int? = nil) {
        let count = max(1, requestedCount ?? assetNames.count)
        marketSigmas = CustomMarketInputGrid.resizedVector(
            marketSigmas, count: count, defaultValue: marketSigma)
        marketQs = CustomMarketInputGrid.resizedVector(
            marketQs, count: count, defaultValue: marketQ)
        marketCorrelation = CustomMarketInputGrid.resizedCorrelation(
            marketCorrelation, count: count, defaultOffDiagonal: marketRho)
        marketSigma = marketSigmas[0]
        marketQ = marketQs[0]
    }

    func sigmaBinding(_ index: Int) -> Binding<Double> {
        Binding(
            get: { index < self.marketSigmas.count
                ? self.marketSigmas[index] : self.marketSigma },
            set: { value in
                self.synchronizeMarketInputs()
                guard index < self.marketSigmas.count else { return }
                self.marketSigmas[index] = value
                if index == 0 { self.marketSigma = value }
            })
    }

    func qBinding(_ index: Int) -> Binding<Double> {
        Binding(
            get: { index < self.marketQs.count ? self.marketQs[index] : self.marketQ },
            set: { value in
                self.synchronizeMarketInputs()
                guard index < self.marketQs.count else { return }
                self.marketQs[index] = value
                if index == 0 { self.marketQ = value }
            })
    }

    func correlationBinding(row: Int, column: Int) -> Binding<Double> {
        Binding(
            get: {
                guard row < self.marketCorrelation.count,
                      column < self.marketCorrelation[row].count else { return 0 }
                return self.marketCorrelation[row][column]
            },
            set: { value in
                self.marketCorrelation = CustomMarketInputGrid.settingCorrelation(
                    self.marketCorrelation, row: row, column: column, value: value)
            })
    }

    func applyEquicorrelation() {
        marketCorrelation = CustomMarketInputGrid.equicorrelation(
            count: assetNames.count, rho: marketRho)
    }

    private func canonicalEditorJSON(_ editor: EDefinition) -> Data? {
        try? JSONSerialization.data(withJSONObject: editor.toJSON(),
                                    options: [.sortedKeys])
    }
}

struct CustomProductsView: View {
    @State private var vm = CustomProductsViewModel()

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            productList
                .frame(width: 250)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s4) {
                    if let detail = vm.detail {
                        DetailHeader(vm: vm, detail: detail)
                        SlotsCard(vm: vm, detail: detail)
                        PricingCard(vm: vm, detail: detail)
                        if let editor = vm.editor {
                            AdvancedEditorCard(vm: vm, detail: detail,
                                               editor: editor)
                        }
                        if let report = detail.compileReport {
                            CompileReportCard(report: report)
                        }
                    } else {
                        ContentUnavailableView(
                            "Выбери продукт или создай из шаблона",
                            systemImage: "puzzlepiece.extension")
                    }
                }
                .padding(Theme.s5)
                .frame(maxWidth: 980, alignment: .leading)
            }
            .frame(maxWidth: .infinity)
        }
        .task { await vm.load() }
    }

    private var productList: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack {
                Text("Custom products")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Menu {
                    ForEach(vm.templates) { template in
                        Button(template.name) {
                            Task { await vm.createFromTemplate(template) }
                        }
                    }
                    Divider()
                    Button("Advanced · с нуля") {
                        Task { await vm.createAdvanced() }
                    }
                } label: {
                    Label("Создать", systemImage: "plus")
                        .font(.system(size: 11))
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .disabled(vm.isBusy)
            }
            .padding(.horizontal, Theme.s3)
            .padding(.top, Theme.s3)

            List(vm.products, selection: Binding(
                get: { vm.selectedID },
                set: { id in if let id { Task { await vm.select(id) } } }
            )) { product in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 4) {
                        Text(product.name)
                            .font(.system(size: 12,
                                          weight: product.id == vm.selectedID ? .semibold : .regular))
                            .lineLimit(1)
                        if product.isTemplate {
                            Image(systemName: "doc.on.doc")
                                .font(.system(size: 8)).foregroundStyle(.tertiary)
                                .help("Опубликованное определение-шаблон; это lifecycle, не production eligibility")
                        }
                    }
                    HStack(spacing: 4) {
                        Pill(text: product.state, color: stateColor(product.state))
                        Text("v\(product.version)")
                            .font(.system(size: 9)).foregroundStyle(.tertiary)
                    }
                }
                .tag(product.id)
            }
            .listStyle(.sidebar)
            .scrollContentBackground(.hidden)
        }
    }
}

private func stateColor(_ state: String) -> Color {
    switch state {
    case "draft": return .secondary
    case "tested": return Theme.accent
    case "submitted": return Theme.warning
    case "approved": return .blue
    case "published": return Theme.positive
    case "deprecated": return Theme.negative
    default: return .secondary
    }
}

// MARK: - Detail header: name, lifecycle pipeline, transitions

private struct DetailHeader: View {
    @Bindable var vm: CustomProductsViewModel
    let detail: CustomProductDetail

    private static let pipeline = ["draft", "tested", "submitted",
                                   "approved", "published"]

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack(alignment: .firstTextBaseline) {
                    Text(detail.definition.name)
                        .font(.title3.weight(.semibold))
                    Text("v\(detail.version)")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                    Spacer()
                    Text("def \(String(detail.definitionHash.prefix(12)))")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.tertiary)
                        .help("Канонический хеш определения — неизменное доказательство")
                }
                if let description = detail.definition.description {
                    Text(description)
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }
                // lifecycle pipeline (spec §16.5)
                Text("DEFINITION LIFECYCLE · НЕ PRODUCTION ELIGIBILITY")
                    .font(.system(size: 9, weight: .semibold))
                    .tracking(0.4).foregroundStyle(.tertiary)
                HStack(spacing: Theme.s1) {
                    ForEach(Self.pipeline, id: \.self) { stage in
                        let reached = reachedIndex >= Self.pipeline.firstIndex(of: stage)!
                        Label(stage, systemImage: stage == detail.state
                              ? "circle.inset.filled" : (reached ? "checkmark.circle" : "circle"))
                            .font(.system(size: 10,
                                          weight: stage == detail.state ? .semibold : .regular))
                            .foregroundStyle(stage == detail.state ? Theme.accent
                                             : (reached ? Theme.positive : Color.secondary))
                        if stage != Self.pipeline.last {
                            Image(systemName: "chevron.right")
                                .font(.system(size: 7)).foregroundStyle(.quaternary)
                        }
                    }
                    if detail.state == "deprecated" {
                        Pill(text: "deprecated", color: Theme.negative)
                    }
                    Spacer()
                }
                transitions
                if let message = vm.message {
                    Label(message, systemImage: "xmark.octagon.fill")
                        .font(.system(size: 10)).foregroundStyle(Theme.negative)
                        .lineLimit(3)
                }
                HStack(spacing: Theme.s3) {
                    meta("Автор", detail.author)
                    if let by = detail.submittedBy { meta("Submitted", by) }
                    if let by = detail.approvedBy { meta("Approved", by) }
                }
            }
        }
    }

    private var reachedIndex: Int {
        Self.pipeline.firstIndex(of: detail.state)
            ?? (detail.state == "deprecated" ? Self.pipeline.count - 1 : 0)
    }

    @ViewBuilder
    private var transitions: some View {
        HStack(spacing: Theme.s2) {
            switch detail.state {
            case "draft":
                if vm.isEditorDirty {
                    Button("Сохранить и скомпилировать") {
                        Task { await vm.saveAndCompile() }
                    }
                } else {
                    Button("Compile · validate") {
                        Task { await vm.lifecycle {
                            try await vm.client.customCompile(detail.id)
                        } }
                    }
                }
            case "tested":
                Button("Submit") {
                    Task { await vm.lifecycle { try await vm.client.customSubmit(detail.id, user: vm.author) } }
                }
            case "submitted":
                TextField("кто согласует", text: $vm.approver)
                    .textFieldStyle(.roundedBorder).frame(width: 130)
                Button("Approve") {
                    Task { await vm.lifecycle { try await vm.client.customApprove(detail.id, user: vm.approver) } }
                }
            case "approved":
                Button("Publish") {
                    Task { await vm.lifecycle { try await vm.client.customPublish(detail.id) } }
                }
            case "published":
                Button("Новая версия") {
                    Task { await vm.lifecycle { try await vm.client.customNewVersion(detail.id, user: vm.author) } }
                }
            default:
                EmptyView()
            }
            if vm.isBusy { ProgressView().controlSize(.small) }
            Spacer()
        }
        .disabled(vm.isBusy || (vm.isEditorDirty && detail.state != "draft"))
    }

    private func meta(_ label: String, _ value: String) -> some View {
        HStack(spacing: 3) {
            Text(label).font(.system(size: 9)).foregroundStyle(.tertiary)
            Text(value).font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }
}

// MARK: - Slots (template mode: pure schema-driven form)

private struct SlotsCard: View {
    @Bindable var vm: CustomProductsViewModel
    let detail: CustomProductDetail

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Слоты шаблона", icon: "slider.horizontal.3")
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150),
                                             spacing: Theme.s3)],
                          alignment: .leading, spacing: Theme.s3) {
                    ForEach(detail.definition.slots.keys.sorted(), id: \.self) { key in
                        let spec = detail.definition.slots[key]!
                        VStack(alignment: .leading, spacing: 3) {
                            Text(spec.label ?? key)
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(.secondary)
                            TextField("", value: Binding(
                                get: { vm.slotValues[key] ?? spec.defaultValue },
                                set: { vm.slotValues[key] = $0 }
                            ), format: .number)
                                .textFieldStyle(.roundedBorder).monospacedDigit()
                            if let lo = spec.min, let hi = spec.max {
                                Text("\(Fmt.number(lo, digits: 2)) … \(Fmt.number(hi, digits: 2))")
                                    .font(.system(size: 9)).foregroundStyle(.tertiary)
                            }
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Pricing (generic MC evaluator)

private struct PricingCard: View {
    @Bindable var vm: CustomProductsViewModel
    let detail: CustomProductDetail

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("Оценка · \(vm.engineLabel)", icon: "function")
                    Spacer()
                    Button {
                        Task { await vm.price() }
                    } label: {
                        if vm.isPricing {
                            ProgressView().controlSize(.small)
                        } else {
                            Label("Price", systemImage: "bolt.fill")
                        }
                    }
                    .buttonStyle(.borderedProminent).tint(Theme.accent)
                    .disabled(vm.isPricing || detail.state == "draft"
                              || detail.state == "deprecated"
                              || vm.isEditorDirty
                              || !vm.valuationIssues.isEmpty)
                }
                if vm.isEditorDirty {
                    Label("Unsaved payout · Price использует только сохранённое server definition",
                          systemImage: "exclamationmark.triangle.fill")
                        .font(.system(size: 10)).foregroundStyle(Theme.warning)
                }
                if detail.state == "draft" {
                    Label("Fail-closed: расчёт разрешён только после Compile",
                          systemImage: "lock.fill")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                HStack(alignment: .top, spacing: Theme.s4) {
                    marketField("Risk-free r", $vm.marketR,
                                range: -1...2, hint: "−1 … 2")
                    Spacer()
                }
                Divider()
                Text("MARKET INPUTS · ПО АКТИВАМ")
                    .font(.system(size: 9, weight: .semibold))
                    .tracking(0.4).foregroundStyle(.tertiary)
                assetMarketTable
                if vm.assetNames.count > 1 {
                    Divider()
                    correlationEditor
                }
                Divider()
                Text("NUMERICAL · MONTE CARLO")
                    .font(.system(size: 9, weight: .semibold))
                    .tracking(0.4).foregroundStyle(.tertiary)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150),
                                             spacing: Theme.s3)],
                          alignment: .leading, spacing: Theme.s3) {
                    marketField("MC paths", $vm.nSims,
                                range: 1_000...200_000,
                                integer: true, hint: "1 000 … 200 000")
                    marketField("Time steps", $vm.mcSteps,
                                range: 16...1_024,
                                integer: true, hint: "16 … 1 024")
                    marketField("Seed", $vm.seed,
                                range: 0...Double(Int.max),
                                integer: true, hint: "целое ≥ 0")
                }
                if !vm.valuationIssues.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(vm.valuationIssues, id: \.self) { issue in
                            Label(issue, systemImage: "exclamationmark.circle.fill")
                                .font(.system(size: 10))
                                .foregroundStyle(Theme.negative)
                        }
                    }
                    .padding(Theme.s2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.negative.opacity(0.08),
                                in: RoundedRectangle(cornerRadius: 7))
                }
                if let result = vm.priceResult {
                    Divider()
                    HStack(alignment: .firstTextBaseline, spacing: Theme.s3) {
                        Text(Fmt.number(result.value, digits: 5))
                            .font(.system(size: 24, weight: .semibold))
                            .monospacedDigit()
                            .foregroundStyle(Theme.accent)
                        Text("± \(Fmt.number(2 * result.stderr, digits: 5)) (2σ)")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                            .monospacedDigit()
                        if let watermark = result.watermark {
                            Pill(text: "research result", color: Theme.warning)
                                .help("Определение не опубликовано; результат research-уровня (\(watermark))")
                        } else {
                            Pill(text: "published definition", color: Theme.accent)
                                .help("Только lifecycle определения. Production eligibility движка этим endpoint не подтверждается.")
                        }
                        Spacer()
                    }
                    Text("Статус определения не является production-допуском модели/прайсера.")
                        .font(.system(size: 9)).foregroundStyle(.tertiary)
                    HStack(spacing: Theme.s4) {
                        stat("P(досрочное погашение)",
                             Fmt.signedPercent(result.earlyRedemptionProb * 100))
                        stat("Engine", result.engine ?? vm.engineLabel)
                        stat("Definition", String(result.definitionHash.prefix(12)))
                        stat("Paths", "\(result.nSims)")
                        stat("Steps", result.steps.map(String.init) ?? "\(Int(vm.mcSteps))")
                        stat("Seed", "\(result.seed)")
                        stat("Доля номинала", "1.0 = 100%")
                    }
                }
            }
        }
        .onAppear { vm.synchronizeMarketInputs() }
        .onChange(of: vm.assetNames.count) { _, count in
            vm.synchronizeMarketInputs(assetCount: count)
        }
    }

    private var assetMarketTable: some View {
        Grid(alignment: .leading, horizontalSpacing: Theme.s3,
             verticalSpacing: Theme.s2) {
            GridRow {
                Text("Актив").foregroundStyle(.secondary)
                Text("Volatility σ").foregroundStyle(.secondary)
                Text("Dividend yield q").foregroundStyle(.secondary)
            }
            .font(.system(size: 10, weight: .semibold))
            ForEach(Array(vm.assetNames.enumerated()), id: \.offset) { index, name in
                GridRow {
                    Text(name).font(.system(size: 11, weight: .medium)).lineLimit(1)
                    boundedInput(vm.sigmaBinding(index), range: 0...5)
                        .frame(width: 125)
                    boundedInput(vm.qBinding(index), range: -1...1)
                        .frame(width: 125)
                }
            }
        }
    }

    private var correlationEditor: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack(spacing: Theme.s3) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("CORRELATION MATRIX")
                        .font(.system(size: 9, weight: .semibold))
                        .tracking(0.4).foregroundStyle(.tertiary)
                    Text("Редактируется верхний треугольник; нижний зеркалируется автоматически.")
                        .font(.system(size: 9)).foregroundStyle(.tertiary)
                }
                Spacer()
                marketField("Default ρ", $vm.marketRho,
                            range: -0.999...0.999, hint: "−0,999 … 0,999")
                    .frame(width: 125)
                Button("Заполнить ρ") { vm.applyEquicorrelation() }
                    .controlSize(.small)
            }
            ScrollView(.horizontal) {
                Grid(alignment: .center, horizontalSpacing: 5, verticalSpacing: 5) {
                    GridRow {
                        Text("").frame(width: 86)
                        ForEach(Array(vm.assetNames.enumerated()), id: \.offset) { _, name in
                            Text(name).font(.system(size: 9, weight: .semibold))
                                .lineLimit(1).frame(width: 72)
                        }
                    }
                    ForEach(Array(vm.assetNames.enumerated()), id: \.offset) { row, name in
                        GridRow {
                            Text(name).font(.system(size: 9, weight: .semibold))
                                .lineLimit(1).frame(width: 86, alignment: .leading)
                            ForEach(vm.assetNames.indices, id: \.self) { column in
                                correlationCell(row: row, column: column)
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func correlationCell(row: Int, column: Int) -> some View {
        if row == column {
            Text("1,000")
                .font(.system(size: 10, weight: .semibold)).monospacedDigit()
                .frame(width: 72, height: 22)
                .background(Color.secondary.opacity(0.08),
                            in: RoundedRectangle(cornerRadius: 5))
        } else if column > row {
            boundedInput(vm.correlationBinding(row: row, column: column),
                         range: -0.999...0.999)
                .frame(width: 72)
        } else {
            Text(correlationValue(row: row, column: column))
                .font(.system(size: 10)).monospacedDigit()
                .foregroundStyle(.secondary)
                .frame(width: 72, height: 22)
        }
    }

    private func correlationValue(row: Int, column: Int) -> String {
        guard row < vm.marketCorrelation.count,
              column < vm.marketCorrelation[row].count else { return "—" }
        return Fmt.number(vm.marketCorrelation[row][column], digits: 3)
    }

    private func marketField(_ label: String, _ value: Binding<Double>,
                             range: ClosedRange<Double>, integer: Bool = false,
                             hint: String) -> some View {
        let invalid = !value.wrappedValue.isFinite
            || !range.contains(value.wrappedValue)
            || (integer && value.wrappedValue.rounded() != value.wrappedValue)
        return VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)
            boundedInput(value, range: range, integer: integer)
            if invalid {
                Text(hint).font(.system(size: 9)).foregroundStyle(Theme.negative)
            }
        }
    }

    private func boundedInput(_ value: Binding<Double>,
                              range: ClosedRange<Double>,
                              integer: Bool = false) -> some View {
        let invalid = !value.wrappedValue.isFinite
            || !range.contains(value.wrappedValue)
            || (integer && value.wrappedValue.rounded() != value.wrappedValue)
        return TextField("", value: value,
                         format: integer
                            ? .number.precision(.fractionLength(0)) : .number)
            .textFieldStyle(.roundedBorder).monospacedDigit()
            .overlay(RoundedRectangle(cornerRadius: 5)
                .stroke(Theme.negative.opacity(invalid ? 0.85 : 0), lineWidth: 1))
    }

    private func stat(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label).font(.system(size: 8)).foregroundStyle(.tertiary)
            Text(value).font(.system(size: 11, weight: .medium)).monospacedDigit()
        }
    }
}

// MARK: - Advanced mode: typed payout-graph editor (spec §16.1 mode 2)

private struct AdvancedEditorCard: View {
    @Bindable var vm: CustomProductsViewModel
    let detail: CustomProductDetail
    @Bindable var editor: EDefinition
    @State private var expanded = false

    private var editable: Bool {
        detail.state != "published" && detail.state != "deprecated"
    }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("Конструктор выплат · advanced",
                               icon: "point.3.connected.trianglepath.dotted")
                    if vm.isEditorDirty {
                        Pill(text: "Unsaved", color: Theme.warning)
                    }
                    Spacer()
                    if editable && expanded {
                        Button {
                            Task { await vm.saveAndCompile() }
                        } label: {
                            if vm.isBusy {
                                ProgressView().controlSize(.small)
                            } else {
                                Label("Сохранить и скомпилировать",
                                      systemImage: "checkmark.seal")
                            }
                        }
                        .disabled(vm.isBusy)
                    }
                    Button {
                        withAnimation(.easeInOut(duration: 0.15)) {
                            expanded.toggle()
                        }
                    } label: {
                        Image(systemName: expanded ? "chevron.up" : "chevron.down")
                            .font(.system(size: 11))
                    }
                    .buttonStyle(.plain).foregroundStyle(.secondary)
                }
                if !editable {
                    Label("Версия published — неизменяема. «Новая версия» откроет редактирование.",
                          systemImage: "lock.fill")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                if expanded {
                    if editable {
                        ForEach(editor.localHints, id: \.self) { hint in
                            Label(hint, systemImage: "exclamationmark.triangle.fill")
                                .font(.system(size: 10)).foregroundStyle(Theme.warning)
                        }
                    }
                    assetsSection
                    slotsSection
                    statesSection
                    scheduleSection
                    programSection("Программа наблюдений (на каждой дате)",
                                   program: $editor.observationProgram,
                                   allowTerminate: true)
                    programSection("Программа погашения (выжившие пути)",
                                   program: $editor.maturityProgram,
                                   allowTerminate: false)
                }
            }
            .disabled(!editable)
        }
    }

    // ── assets (multi-underlying basket, spec §16.2) ─────
    private var assetsSection: some View {
        section("Базовые активы (корзина)") {
            ForEach(Array(editor.assets.enumerated()), id: \.offset) { index, _ in
                HStack(spacing: Theme.s2) {
                    TextField("имя актива", text: Binding(
                        get: { editor.assets[index] },
                        set: { editor.assets[index] = $0 }
                    ))
                        .textFieldStyle(.roundedBorder).frame(width: 150)
                    if editor.assets.count > 1 {
                        Button {
                            editor.assets.remove(at: index)
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                        }
                        .buttonStyle(.plain).foregroundStyle(.tertiary)
                    }
                    Spacer()
                }
            }
            HStack(spacing: Theme.s3) {
                Button {
                    editor.assets.append("Asset \(editor.assets.count + 1)")
                } label: {
                    Label("Добавить актив", systemImage: "plus.circle")
                        .font(.system(size: 10))
                }
                .buttonStyle(.plain).foregroundStyle(Theme.accent)
                if editor.assets.count > 1 {
                    Text("perf/path_min недоступны — используй узлы корзины (худший/лучший/среднее)")
                        .font(.system(size: 9)).foregroundStyle(.tertiary)
                }
            }
        }
    }

    // ── slots ────────────────────────────────────────────
    private var slotsSection: some View {
        section("Слоты (параметры шаблона)") {
            ForEach(editor.slots) { slot in
                SlotRow(slot: slot) {
                    editor.slots.removeAll { $0.id == slot.id }
                }
            }
            Button {
                editor.slots.append(ESlot(name: "slot\(editor.slots.count + 1)"))
            } label: {
                Label("Добавить слот", systemImage: "plus.circle")
                    .font(.system(size: 10))
            }
            .buttonStyle(.plain).foregroundStyle(Theme.accent)
        }
    }

    private var statesSection: some View {
        section("State-переменные (память, счётчики)") {
            ForEach(editor.states) { state in
                StateRow(state: state) {
                    editor.states.removeAll { $0.id == state.id }
                }
            }
            Button {
                editor.states.append(EStateVar(
                    name: editor.states.isEmpty ? "memory"
                          : "state\(editor.states.count + 1)"))
            } label: {
                Label("Добавить state", systemImage: "plus.circle")
                    .font(.system(size: 10))
            }
            .buttonStyle(.plain).foregroundStyle(Theme.accent)
        }
    }

    // ── schedule ─────────────────────────────────────────
    private var scheduleSection: some View {
        section("Расписание") {
            HStack(spacing: Theme.s3) {
                scheduleField("Наблюдений", slot: $editor.obsSlot,
                              value: $editor.obsCount)
                scheduleField("Погашение, лет", slot: $editor.matSlot,
                              value: $editor.matValue)
                Spacer()
            }
        }
    }

    private func scheduleField(_ title: String, slot: Binding<String>,
                               value: Binding<Double>) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.system(size: 10)).foregroundStyle(.secondary)
            HStack(spacing: 4) {
                Menu(slot.wrappedValue.isEmpty ? "число" : "слот «\(slot.wrappedValue)»") {
                    Button("число") { slot.wrappedValue = "" }
                    ForEach(editor.slotNames, id: \.self) { name in
                        Button("слот «\(name)»") { slot.wrappedValue = name }
                    }
                }
                .menuStyle(.borderlessButton).fixedSize()
                if slot.wrappedValue.isEmpty {
                    TextField("", value: value, format: .number)
                        .textFieldStyle(.roundedBorder).monospacedDigit()
                        .frame(width: 70)
                }
            }
        }
    }

    // ── programs ─────────────────────────────────────────
    private func programSection(_ title: String,
                                program: Binding<[EAction]>,
                                allowTerminate: Bool) -> some View {
        section(title) {
            ForEach(program.wrappedValue) { action in
                ActionEditor(action: action, defn: editor,
                             allowTerminate: allowTerminate,
                             onDelete: {
                                 program.wrappedValue.removeAll { $0.id == action.id }
                             },
                             onMove: { delta in
                                 move(action, in: program, by: delta)
                             })
            }
            Menu {
                let kinds = allowTerminate
                    ? ["accumulate", "set", "pay", "terminate"]
                    : ["accumulate", "set", "pay"]
                ForEach(kinds, id: \.self) { kind in
                    Button(actionTitle(kind)) {
                        program.wrappedValue.append(EAction(kind: kind))
                    }
                }
            } label: {
                Label("Добавить действие", systemImage: "plus.circle")
                    .font(.system(size: 10))
            }
            .menuStyle(.borderlessButton).fixedSize()
            .foregroundStyle(Theme.accent)
        }
    }

    private func move(_ action: EAction, in program: Binding<[EAction]>,
                      by delta: Int) {
        guard let index = program.wrappedValue.firstIndex(where: { $0.id == action.id })
        else { return }
        let target = index + delta
        guard program.wrappedValue.indices.contains(target) else { return }
        program.wrappedValue.swapAt(index, target)
    }

    private func section(_ title: String,
                         @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            Text(title.uppercased())
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.tertiary)
            content()
        }
        .padding(.top, Theme.s1)
    }
}

private struct SlotRow: View {
    @Bindable var slot: ESlot
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: Theme.s2) {
            TextField("имя", text: $slot.name)
                .textFieldStyle(.roundedBorder).frame(width: 110)
                .font(.system(size: 11, design: .monospaced))
            TextField("подпись", text: $slot.label)
                .textFieldStyle(.roundedBorder).frame(width: 150)
            numeric("default", $slot.def)
            numeric("min", $slot.lo)
            numeric("max", $slot.hi)
            Button { onDelete() } label: {
                Image(systemName: "xmark.circle.fill")
            }
            .buttonStyle(.plain).foregroundStyle(.tertiary)
            Spacer()
        }
    }

    private func numeric(_ placeholder: String,
                         _ value: Binding<Double>) -> some View {
        TextField(placeholder, value: value, format: .number)
            .textFieldStyle(.roundedBorder).monospacedDigit().frame(width: 70)
    }
}

private struct StateRow: View {
    @Bindable var state: EStateVar
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: Theme.s2) {
            TextField("имя", text: $state.name)
                .textFieldStyle(.roundedBorder).frame(width: 110)
                .font(.system(size: 11, design: .monospaced))
            Text("начальное").font(.system(size: 10)).foregroundStyle(.tertiary)
            TextField("", value: $state.initial, format: .number)
                .textFieldStyle(.roundedBorder).monospacedDigit().frame(width: 70)
            Button { onDelete() } label: {
                Image(systemName: "xmark.circle.fill")
            }
            .buttonStyle(.plain).foregroundStyle(.tertiary)
            Spacer()
        }
    }
}

// MARK: - Compile report: summary, classification, issues, test vectors

private struct CompileReportCard: View {
    let report: CustomCompileReport

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("Компиляция", icon: report.ok
                               ? "checkmark.seal.fill" : "xmark.seal.fill")
                    if report.ok {
                        Pill(text: "validated · compiled · tested",
                             color: Theme.positive)
                    }
                    Spacer()
                }
                if let summary = report.summary {
                    Text(summary)
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }
                if let cls = report.classification {
                    HStack(spacing: Theme.s2) {
                        if cls.pathDependent { Pill(text: "path-dependent", color: .secondary) }
                        if cls.earlyRedemption { Pill(text: "early redemption", color: .secondary) }
                        Pill(text: cls.dynamics.uppercased(), color: .secondary)
                        ForEach(report.compatibleEngines, id: \.self) { engine in
                            Pill(text: engine, color: Theme.accent)
                        }
                        Spacer()
                    }
                }
                ForEach(report.issues) { issue in
                    Label("\(issue.code): \(issue.message)" +
                          (issue.path.isEmpty ? "" : " (\(issue.path))"),
                          systemImage: "xmark.octagon.fill")
                        .font(.system(size: 10)).foregroundStyle(Theme.negative)
                }
                if let timeline = report.timeline, !timeline.isEmpty {
                    Text("Событийная шкала:")
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(alignment: .top, spacing: Theme.s3) {
                            ForEach(timeline, id: \.self) { entry in
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(String(format: "t=%.2f", entry.t))
                                        .font(.system(size: 9, weight: .semibold))
                                        .monospacedDigit()
                                        .foregroundStyle(entry.kind == "maturity"
                                                         ? Theme.accent : .secondary)
                                    ForEach(entry.events, id: \.self) { event in
                                        Text("· \(event)")
                                            .font(.system(size: 9))
                                            .foregroundStyle(.tertiary)
                                    }
                                }
                                .padding(6)
                                .background(Color.primary.opacity(0.04),
                                            in: RoundedRectangle(cornerRadius: 6))
                            }
                        }
                    }
                }
                if !report.testVectors.isEmpty {
                    Text("Регрессионные векторы (детерминированные сценарии):")
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                    HStack(spacing: Theme.s4) {
                        ForEach(report.testVectors, id: \.self) { vector in
                            VStack(alignment: .leading, spacing: 1) {
                                Text("\(vector.scenario) → perf \(Fmt.number(vector.terminalPerf, digits: 2))")
                                    .font(.system(size: 9)).foregroundStyle(.tertiary)
                                Text(Fmt.number(vector.pv, digits: 4))
                                    .font(.system(size: 12, weight: .medium))
                                    .monospacedDigit()
                            }
                        }
                        Spacer()
                    }
                }
            }
        }
    }
}
