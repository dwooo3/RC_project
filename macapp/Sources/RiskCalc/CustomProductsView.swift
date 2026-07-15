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
    var nSims: Double = 50_000
    var seed: Double = 42

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

    func select(_ id: String) async {
        selectedID = id
        priceResult = nil
        message = nil
        do {
            let d = try await client.customProduct(id)
            detail = d
            slotValues = d.definition.slots.mapValues(\.defaultValue)
        } catch {
            message = error.localizedDescription
        }
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
        isPricing = true
        message = nil
        priceResult = nil
        do {
            priceResult = try await client.customPrice(
                id, slots: slotValues,
                market: ["r": marketR, "q": marketQ, "sigma": marketSigma],
                nSims: Int(nSims), seed: Int(seed))
        } catch {
            message = error.localizedDescription
        }
        isPricing = false
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
                } label: {
                    Label("Из шаблона", systemImage: "plus")
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
                                .help("Опубликованный шаблон")
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
                Button("Compile · validate") {
                    Task { await vm.lifecycle { try await vm.client.customCompile(detail.id) } }
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
        .disabled(vm.isBusy)
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
                    BlockTitle("Оценка · custom_mc_gbm", icon: "function")
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
                              || detail.state == "deprecated")
                }
                if detail.state == "draft" {
                    Label("Fail-closed: расчёт разрешён только после Compile",
                          systemImage: "lock.fill")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 120),
                                             spacing: Theme.s3)],
                          alignment: .leading, spacing: Theme.s3) {
                    marketField("Risk-free r", $vm.marketR)
                    marketField("Dividend q", $vm.marketQ)
                    marketField("Volatility σ", $vm.marketSigma)
                    marketField("MC paths", $vm.nSims)
                    marketField("Seed", $vm.seed)
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
                            Pill(text: watermark, color: Theme.warning)
                                .help("Определение не опубликовано — результат research-уровня (§20)")
                        } else {
                            Pill(text: "production", color: Theme.positive)
                        }
                        Spacer()
                    }
                    HStack(spacing: Theme.s4) {
                        stat("P(досрочное погашение)",
                             Fmt.signedPercent(result.earlyRedemptionProb * 100))
                        stat("Definition", String(result.definitionHash.prefix(12)))
                        stat("Paths", "\(result.nSims)")
                        stat("Seed", "\(result.seed)")
                        stat("Доля номинала", "1.0 = 100%")
                    }
                }
            }
        }
    }

    private func marketField(_ label: String, _ value: Binding<Double>) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)
            TextField("", value: value, format: .number)
                .textFieldStyle(.roundedBorder).monospacedDigit()
        }
    }

    private func stat(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label).font(.system(size: 8)).foregroundStyle(.tertiary)
            Text(value).font(.system(size: 11, weight: .medium)).monospacedDigit()
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
