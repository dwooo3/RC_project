import Charts
import CryptoKit
import Foundation
import SwiftUI

/// A single dense pricing worksheet. Instruments are configured side by side;
/// valuation, risk and immutable run history stay on the same vertical surface.
struct PricingNewScreen: View {
    @State private var vm = PricingNewWorkspaceViewModel()
    @State private var showCustomBuilder = false

    var body: some View {
        ScrollView {
            pageContent
                .padding(Theme.s4)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        // Let card shadows fade past the scroll bounds instead of being cut
        // into a phantom border at the sidebar edge.
        .scrollClipDisabled()
        .environment(\.interfaceDensity, .dense)
        .task { await vm.load() }
    }

    private var pageContent: some View {
        VStack(alignment: .leading, spacing: Theme.s4) {
            workspaceHeader
            if let message = vm.errorMessage {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(Typography.caption)
                    .foregroundStyle(Theme.negative)
                    .padding(.horizontal, Theme.s2)
            }
            if vm.catalogue == nil && vm.isLoading {
                SkeletonScreen()
            } else {
                worksheet
                if showCustomBuilder {
                    PricingNewCustomProductEmbeddedEditor(
                        environmentID: vm.envID
                    ) { attachment in
                        do {
                            try vm.attachCustomProduct(attachment)
                            showCustomBuilder = false
                        } catch {
                            vm.errorMessage = error.localizedDescription
                        }
                    }
                }
                resultsBlock
                riskBlock
                historyBlock
            }
        }
    }

    // MARK: - Run toolbar

    private var workspaceHeader: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s2) {
                HStack(alignment: .bottom, spacing: Theme.s3) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Pricing_new")
                            .font(.system(size: 19, weight: .bold,
                                         design: .rounded))
                            .lineLimit(1)
                        Text("Единый расчёт · 1–5 инструментов · real market data")
                            .font(Typography.micro).foregroundStyle(.tertiary)
                            .lineLimit(1)
                    }
                    .fixedSize(horizontal: true, vertical: false)
                    Divider().frame(height: 34)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("ИМЯ РАСЧЁТА")
                            .font(Typography.label).foregroundStyle(.secondary)
                        TextField("Например: Autocall validation · 16 Jul",
                                  text: $vm.runName)
                            .textFieldStyle(.roundedBorder)
                            .frame(minWidth: 210, maxWidth: 380)
                    }
                    .layoutPriority(1)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("КОНТУР")
                            .font(Typography.label).foregroundStyle(.secondary)
                        Picker("Environment", selection: $vm.envID) {
                            ForEach(vm.environments) { env in
                                Text("\(env.envID) · \(env.name)").tag(env.envID)
                            }
                        }
                        .labelsHidden().pickerStyle(.menu)
                        .neutralControlTint().fixedSize()
                    }
                    Spacer(minLength: 0)
                }
                HStack(spacing: Theme.s2) {
                    if vm.isStale {
                        Pill(text: "inputs changed", color: Theme.warning)
                            .fixedSize()
                    } else if let result = vm.result {
                        Pill(text: result.snapshotID ?? "priced",
                             color: Theme.positive)
                            .fixedSize()
                    }
                    Spacer(minLength: Theme.s2)
                    Button {
                        showCustomBuilder.toggle()
                    } label: {
                        Label(showCustomBuilder ? "Скрыть конструктор" : "Custom payout",
                              systemImage: "point.3.connected.trianglepath.dotted")
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    Button {
                        vm.addInstrument()
                    } label: {
                        Label("Инструмент", systemImage: "plus")
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(vm.legs.count >= vm.maxLegs)
                    Button {
                        Task { await vm.price() }
                    } label: {
                        if vm.isPricing {
                            ProgressView().controlSize(.small)
                        } else {
                            Label("Рассчитать и сохранить",
                                  systemImage: "play.fill")
                        }
                    }
                    .buttonStyle(.borderedProminent).tint(Theme.accent)
                    .controlSize(.small)
                    .disabled(!vm.canPrice)
                    .keyboardShortcut(.return, modifiers: [.command])
                }
            }
        }
    }

    // MARK: - Multi-instrument worksheet

    private var worksheet: some View {
        GlassCard(padding: 0) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: Theme.s2) {
                    BlockTitle("Инструменты", icon: "rectangle.3.group")
                    Pill(text: "\(vm.legs.count) / \(vm.maxLegs)", color: Theme.accent)
                    Text("Каждая колонка — отдельная позиция с собственным продуктом, прайсером и параметрами")
                        .font(Typography.caption).foregroundStyle(.tertiary)
                    Spacer()
                }
                .padding(.horizontal, Theme.s3).padding(.vertical, Theme.s3)
                Divider()
                ScrollView(.horizontal) {
                    LazyHStack(alignment: .top, spacing: 1) {
                        ForEach(Array(vm.legs.enumerated()), id: \.element.id) { index, leg in
                            PricingNewInstrumentColumn(
                                index: index, leg: leg, vm: vm)
                        }
                        if vm.legs.count < vm.maxLegs {
                            Button { vm.addInstrument() } label: {
                                VStack(spacing: Theme.s2) {
                                    Image(systemName: "plus.square.dashed")
                                        .font(.system(size: 24))
                                    Text("Добавить позицию")
                                        .font(Typography.captionStrong)
                                    Text("до \(vm.maxLegs) в одном расчёте")
                                        .font(Typography.micro).foregroundStyle(.tertiary)
                                }
                                .foregroundStyle(Theme.accent)
                                .frame(width: 210, height: 150)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            // edge-to-edge content must follow the card's rounded shape
            .clipShape(Theme.cardShape)
        }
    }

    // MARK: - Results

    @ViewBuilder
    private var resultsBlock: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("Результаты и метрики", icon: "sum")
                    Spacer()
                    if let result = vm.result {
                        Text("snapshot \(result.snapshotID ?? "—")")
                            .font(Typography.micro).foregroundStyle(.tertiary)
                        Text("hash \((result.inputsHash ?? "—").prefix(10))")
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                }
                if let result = vm.result {
                    if vm.isStale {
                        Label("Показан сохранённый результат; параметры выше уже изменены.",
                              systemImage: "clock.arrow.circlepath")
                            .font(Typography.caption).foregroundStyle(Theme.warning)
                    }
                    resultSummary(result)
                    resultTable(result)
                    greekChart(result)
                    allMetrics(result)
                    evidencePanel(result)
                } else {
                    HStack(spacing: Theme.s3) {
                        Image(systemName: "function")
                            .font(.system(size: 22)).foregroundStyle(.tertiary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Заполни колонки и запусти общий расчёт")
                                .font(Typography.bodyMedium)
                            Text("PV, position value, Greeks, model measures и диагностика появятся здесь без перехода на другой экран.")
                                .font(Typography.caption).foregroundStyle(.tertiary)
                        }
                    }
                    .padding(.vertical, Theme.s2)
                }
            }
        }
    }

    private func resultSummary(_ result: WsBookResult) -> some View {
        HStack(spacing: Theme.s2) {
            PricingNewMetricTile(label: "Priced", value: "\(result.successCount)/\(result.count)",
                                 color: result.successCount == result.count ? Theme.positive : Theme.warning)
            PricingNewMetricTile(label: "Environment", value: result.environment ?? vm.envID,
                                 color: Theme.accent)
            if result.aggregation?.compatible == true, let total = result.totalValue {
                PricingNewMetricTile(label: "Aggregate PV", value: Fmt.number(total, digits: 4),
                                     color: Theme.positive)
            } else {
                PricingNewMetricTile(label: "Aggregate PV", value: "blocked",
                                     color: Theme.warning)
            }
            ForEach(result.greeks.prefix(4)) { greek in
                PricingNewMetricTile(label: greek.label,
                                     value: Fmt.number(greek.value, digits: 4),
                                     color: Theme.bucketColor("Volatility"))
            }
            Spacer(minLength: 0)
        }
    }

    private func resultTable(_ result: WsBookResult) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if let aggregation = result.aggregation, !aggregation.compatible {
                Label(aggregation.reason, systemImage: "equal.circle")
                    .font(Typography.caption).foregroundStyle(Theme.warning)
                    .padding(.bottom, Theme.s2)
            }
            ScrollView(.horizontal) {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 0) {
                        resultHeader("POSITION", width: 180, alignment: .leading)
                        resultHeader("PRODUCT / PRICER", width: 210, alignment: .leading)
                        resultHeader("QTY", width: 70, alignment: .trailing)
                        resultHeader("UNIT PV", width: 110, alignment: .trailing)
                        resultHeader("POSITION PV", width: 120, alignment: .trailing)
                        ForEach(vm.availableGreekKeys.prefix(6), id: \.self) { key in
                            resultHeader(key.uppercased(), width: 100, alignment: .trailing)
                        }
                        resultHeader("STATUS", width: 150, alignment: .leading)
                    }
                    .padding(.vertical, 5)
                    Divider()
                    ForEach(Array(result.legs.enumerated()), id: \.element.id) { index, leg in
                        HStack(spacing: 0) {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(leg.label).font(Typography.bodyMedium).lineLimit(1)
                                Text("#\(index + 1)").font(Typography.micro).foregroundStyle(.tertiary)
                            }.frame(width: 180, alignment: .leading)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(leg.product).font(Typography.body).lineLimit(1)
                                Text(leg.engine ?? "—").font(Typography.micro).foregroundStyle(.tertiary)
                            }.frame(width: 210, alignment: .leading)
                            resultNumber(leg.quantity, width: 70)
                            resultNumber(leg.unitValue, width: 110)
                            resultNumber(leg.positionValue, width: 120)
                            ForEach(vm.availableGreekKeys.prefix(6), id: \.self) { key in
                                resultNumber(leg.greeks.first(where: { $0.key == key })?.value,
                                             width: 100)
                            }
                            HStack(spacing: 4) {
                                Circle().fill(leg.error == nil ? Theme.positive : Theme.negative)
                                    .frame(width: 6, height: 6)
                                Text(leg.error ?? "priced")
                                    .font(Typography.micro).lineLimit(1)
                            }.frame(width: 150, alignment: .leading)
                        }
                        .padding(.vertical, 5)
                        Divider().opacity(0.25)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func greekChart(_ result: WsBookResult) -> some View {
        let keys = vm.availableGreekKeys
        if !keys.isEmpty {
            VStack(alignment: .leading, spacing: Theme.s2) {
                HStack {
                    Text("GREEK EXPOSURE BY POSITION")
                        .font(Typography.label).tracking(0.5).foregroundStyle(.secondary)
                    Spacer()
                    Picker("Greek", selection: $vm.selectedGreek) {
                        ForEach(keys, id: \.self) { Text($0.capitalized).tag($0) }
                    }.labelsHidden().pickerStyle(.menu).neutralControlTint().fixedSize()
                }
                let selected = keys.contains(vm.selectedGreek) ? vm.selectedGreek : keys[0]
                let rows = result.legs.compactMap { leg -> (String, Double)? in
                    guard let value = leg.greeks.first(where: { $0.key == selected })?.value else { return nil }
                    return (leg.label, value)
                }
                Chart(Array(rows.enumerated()), id: \.offset) { _, row in
                    BarMark(x: .value(selected.capitalized, row.1),
                            y: .value("Position", row.0))
                        .foregroundStyle(row.1 >= 0 ? Theme.positive : Theme.negative)
                        .annotation(position: row.1 >= 0 ? .trailing : .leading) {
                            Text(Fmt.number(row.1, digits: 4))
                                .font(Typography.micro).monospacedDigit()
                        }
                }
                .frame(height: max(130, CGFloat(rows.count) * 28))
            }
            .padding(Theme.s2)
            .background(Color.primary.opacity(0.025), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
    }

    @ViewBuilder
    private func allMetrics(_ result: WsBookResult) -> some View {
        let successful = result.legs.compactMap { $0.result }
        if successful.contains(where: { !$0.measures.isEmpty || !$0.greeks.isEmpty }) {
            VStack(alignment: .leading, spacing: Theme.s2) {
                Text("ALL MODEL OUTPUTS")
                    .font(Typography.label).tracking(0.5).foregroundStyle(.secondary)
                ForEach(result.legs) { leg in
                    if let priced = leg.result {
                        HStack(alignment: .top, spacing: Theme.s2) {
                            Text(leg.label).font(Typography.captionStrong)
                                .frame(width: 150, alignment: .leading)
                            PricingNewFlowLayout(spacing: 5) {
                                ForEach(priced.measures + priced.greeks) { measure in
                                    HStack(spacing: 3) {
                                        Text(measure.label).foregroundStyle(.secondary)
                                        Text(Fmt.number(measure.value, digits: 5)).monospacedDigit()
                                    }
                                    .font(Typography.micro)
                                    .padding(.horizontal, 6).padding(.vertical, 3)
                                    .background(Color.primary.opacity(0.045), in: Capsule())
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func evidencePanel(_ result: WsBookResult) -> some View {
        let evidenceLegs = result.legs.filter { leg in
            guard let priced = leg.result else { return false }
            return priced.provenance != nil
                || priced.resolvedInputs != nil
                || priced.marketDataEvidence != nil
                || !(priced.warnings + priced.limitations).isEmpty
        }
        if !evidenceLegs.isEmpty {
            DisclosureGroup {
                VStack(alignment: .leading, spacing: Theme.s2) {
                    ForEach(evidenceLegs) { leg in
                        if let priced = leg.result {
                            evidenceRow(leg: leg, priced: priced)
                            Divider().opacity(0.25)
                        }
                    }
                }
                .padding(.top, Theme.s2)
            } label: {
                HStack(spacing: Theme.s2) {
                    Text("MARKET DATA · MODEL EVIDENCE")
                        .font(Typography.label).tracking(0.5)
                    Pill(text: "\(evidenceLegs.count) priced legs",
                         color: Theme.positive)
                }
                .foregroundStyle(.secondary)
            }
            .padding(Theme.s2)
            .background(Color.primary.opacity(0.025),
                        in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
    }

    private func evidenceRow(leg: WsBookLegResult, priced: WsResult) -> some View {
        let evidence = priced.marketDataEvidence?.objectValue
        let snapshot = evidence?["snapshot"]?.objectValue
        let fallbackFlags = evidence?["fallback_flags"]?.arrayValue ?? []
        let constituents = evidence?["constituents"]?.arrayValue ?? []
        let resolved = priced.resolvedInputs?.objectValue
        let customState = resolved?["valuation_state"]?.objectValue
        let correlationEvidence = resolved?["correlation_evidence"]?.objectValue
        let isCustomRepricing = resolved?["schema"]?.stringValue
            == "custom-product-portfolio-repricing-v1"
        return VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: Theme.s2) {
                Text(leg.label).font(Typography.captionStrong)
                    .frame(width: 150, alignment: .leading)
                if let provenance = priced.provenance {
                    Text("snapshot \(provenance.snapshotID)")
                    Text("hash \(provenance.inputsHash.prefix(12))")
                    Text("\(provenance.source) · \(provenance.quality)")
                }
                if let resolverHash = evidence?["resolved_inputs_hash"]?.stringValue {
                    Text("resolver \(resolverHash.prefix(12))")
                }
                Spacer()
            }
            .font(.system(size: 9, design: .monospaced))
            .foregroundStyle(.secondary)
            if let cutoff = evidence?["history_cutoff"]?.stringValue {
                Text("As-of \(cutoff) · \(snapshot?["selection"]?.stringValue ?? "pinned")")
                    .font(Typography.micro).foregroundStyle(.tertiary)
            }
            if isCustomRepricing {
                HStack(spacing: Theme.s2) {
                    Pill(text: "AST reprice contract", color: Theme.positive)
                    Text("state \(customState?["mode"]?.stringValue ?? "—")")
                    if let version = resolved?["definition_version"]?.doubleValue {
                        Text("definition v\(Int(version))")
                    }
                    if let hash = resolved?["definition_hash"]?.stringValue {
                        Text("hash \(hash.prefix(12))")
                    }
                    if let contractHash = resolved?["repricing_contract_hash"]?.stringValue {
                        Text("contract \(contractHash.prefix(12))")
                    }
                    if let basis = resolved?["payoff_basis"]?.stringValue {
                        Text("basis \(basis)")
                    }
                    if let source = resolved?["state_source"]?.stringValue {
                        Text("state source \(source)")
                    }
                    Text("CRN component Δ / Γ / Vega")
                    Spacer(minLength: 0)
                }
                .font(.system(size: 8, design: .monospaced))
                .foregroundStyle(.secondary)
                if let correlationEvidence {
                    HStack(spacing: Theme.s2) {
                        Pill(
                            text: correlationEvidence["source"]?.stringValue
                                ?? "correlation evidence missing",
                            color: correlationEvidence["historical_estimation_bound"]?.boolValue == true
                                ? Theme.positive : .secondary)
                        Text(correlationEvidence["method"]?.stringValue ?? "manual")
                        if let lookback = correlationEvidence["lookback"]?.doubleValue {
                            Text("lookback \(Int(lookback))")
                        }
                        if let asOf = correlationEvidence["as_of"]?.stringValue {
                            Text("as-of \(asOf)")
                        }
                        if correlationEvidence["fallback"]?.boolValue == true {
                            Text("prior fallback used").foregroundStyle(Theme.warning)
                        }
                        if let hash = correlationEvidence["matrix_hash"]?.stringValue {
                            Text("corr hash \(hash.prefix(12))")
                        }
                        Spacer(minLength: 0)
                    }
                    .font(.system(size: 8, design: .monospaced))
                    .foregroundStyle(.secondary)
                }
            }
            if !constituents.isEmpty {
                PricingNewFlowLayout(spacing: 5) {
                    ForEach(Array(constituents.enumerated()), id: \.offset) { _, raw in
                        if let item = raw.objectValue {
                            let secid = item["secid"]?.stringValue ?? "asset"
                            let spot = evidenceField(item["spot"], name: "S")
                            let vol = evidenceField(item["vol"], name: "σ")
                            let income = evidenceField(item["income"], name: "q")
                            VStack(alignment: .leading, spacing: 1) {
                                Text(secid).font(Typography.captionStrong)
                                Text([spot, vol, income].joined(separator: " · "))
                                    .font(.system(size: 8, design: .monospaced))
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.horizontal, 6).padding(.vertical, 4)
                            .background(Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 5))
                        }
                    }
                }
            }
            ForEach(Array(fallbackFlags.enumerated()), id: \.offset) { _, flag in
                if let message = flag.stringValue {
                    Label(message, systemImage: "exclamationmark.triangle.fill")
                        .font(Typography.micro).foregroundStyle(Theme.warning)
                }
            }
            ForEach(priced.warnings + priced.limitations, id: \.self) { warning in
                Label(warning, systemImage: "info.circle")
                    .font(Typography.micro).foregroundStyle(.secondary)
            }
        }
    }

    private func evidenceField(_ value: JSONValue?, name: String) -> String {
        guard let block = value?.objectValue else { return "\(name) —" }
        let number = block["value"]?.doubleValue
            .map { Fmt.number($0, digits: 4) } ?? "—"
        let source = block["source"]?.stringValue ?? "unknown"
        let date = block["effective_date"]?.stringValue ?? "—"
        let fallback = block["fallback"]?.boolValue == true ? " fallback" : ""
        return "\(name) \(number) [\(source)@\(date)\(fallback)]"
    }

    // MARK: - Risk and history stay on the same surface

    private var riskBlock: some View {
        PricingNewRiskBlock(vm: vm)
    }

    private var historyBlock: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s2) {
                HStack {
                    BlockTitle("Журнал расчётов", icon: "clock.arrow.circlepath")
                    Text("Точные inputs + result + server hash")
                        .font(Typography.caption).foregroundStyle(.tertiary)
                    Spacer()
                    if vm.isRestoring { ProgressView().controlSize(.small) }
                }
                if vm.history.isEmpty {
                    Text("После первого запуска здесь появится воспроизводимая запись.")
                        .font(Typography.caption).foregroundStyle(.tertiary)
                } else {
                    ForEach(vm.history.prefix(10)) { run in
                        HStack(spacing: Theme.s2) {
                            Text(run.name).font(Typography.bodyMedium).lineLimit(1)
                                .frame(minWidth: 180, maxWidth: .infinity, alignment: .leading)
                            Text(run.createdAt.replacingOccurrences(of: "T", with: " ").prefix(19))
                                .font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary)
                            Text(run.contentHash.prefix(10))
                                .font(.system(size: 9, design: .monospaced)).foregroundStyle(.tertiary)
                            Button("Восстановить") { Task { await vm.restore(run) } }
                                .buttonStyle(.bordered).controlSize(.mini)
                        }
                        .padding(.vertical, 4)
                        Divider().opacity(0.25)
                    }
                }
            }
        }
    }

    private func resultHeader(_ text: String, width: CGFloat,
                              alignment: Alignment) -> some View {
        Text(text).font(Typography.label).tracking(0.35).foregroundStyle(.tertiary)
            .frame(width: width, alignment: alignment)
    }

    private func resultNumber(_ value: Double?, width: CGFloat) -> some View {
        Text(value.map { Fmt.number($0, digits: 5) } ?? "—")
            .font(.system(size: 10, design: .monospaced))
            .frame(width: width, alignment: .trailing)
    }
}

// MARK: - One worksheet column

private struct PricingNewInstrumentColumn: View {
    let index: Int
    @Bindable var leg: PricingNewLegDraft
    let vm: PricingNewWorkspaceViewModel

    private var product: WsProductModel? { vm.product(for: leg) }
    private var engine: WsEngineModel? { vm.engine(for: leg) }
    private let groups = ["contract", "market", "model", "numerical"]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            columnHeader
            selectorRows
            marketDataSection
            parameterRows
        }
        .frame(width: 324, alignment: .topLeading)
        .overlay(alignment: .trailing) { Divider().opacity(0.5) }
    }

    private var columnHeader: some View {
        VStack(spacing: 5) {
            HStack(spacing: 5) {
                Text("\(index + 1)")
                    .font(Typography.captionStrong).foregroundStyle(.white)
                    .frame(width: 22, height: 22)
                    .background(Theme.bucketColor(product?.assetClass.capitalized ?? "Equity"), in: RoundedRectangle(cornerRadius: 5))
                TextField("Position name", text: $leg.label)
                    .textFieldStyle(.plain).font(Typography.bodyMedium)
                Button { vm.duplicate(leg) } label: { Image(systemName: "plus.square.on.square") }
                    .buttonStyle(.plain).help("Дублировать")
                    .disabled(vm.legs.count >= vm.maxLegs)
                Button(role: .destructive) { vm.remove(leg) } label: { Image(systemName: "trash") }
                    .buttonStyle(.plain).help("Удалить")
            }
            HStack(spacing: 5) {
                Text("QTY").font(Typography.label).foregroundStyle(.tertiary)
                TextField("Quantity", value: $leg.quantity, format: .number)
                    .textFieldStyle(.roundedBorder).monospacedDigit().frame(width: 74)
                Text("CCY").font(Typography.label).foregroundStyle(.tertiary)
                TextField("RUB", text: $leg.currency)
                    .textFieldStyle(.roundedBorder).frame(width: 58)
                Spacer()
                if let engine {
                    StatusChip(status: engine.governance.status)
                }
            }
        }
        .padding(Theme.s2)
        .overlay(alignment: .bottom) { Divider().opacity(0.4) }
    }

    private var selectorRows: some View {
        VStack(spacing: 0) {
            PricingNewSelectorRow(label: "Asset class") {
                Picker("Asset class", selection: Binding(
                    get: { leg.assetClass },
                    set: { vm.selectAssetClass($0, for: leg) })) {
                        ForEach(vm.assetClasses) { asset in Text(asset.label).tag(asset.id) }
                    }
                    .labelsHidden().pickerStyle(.menu).neutralControlTint()
            }
            PricingNewSelectorRow(label: "Instrument") {
                Picker("Instrument", selection: Binding(
                    get: { leg.productID },
                    set: { vm.selectProduct($0, for: leg) })) {
                        ForEach(vm.products(for: leg.assetClass)) { item in
                            Text("\(item.group) · \(item.name)").tag(item.id)
                        }
                    }
                    .labelsHidden().pickerStyle(.menu).neutralControlTint()
            }
            PricingNewSelectorRow(label: "Pricer") {
                Picker("Pricer", selection: Binding(
                    get: { leg.engineID },
                    set: { vm.selectEngine($0, for: leg) })) {
                        ForEach(product?.engines ?? []) { item in
                            Text(item.name).tag(item.id)
                        }
                    }
                    .labelsHidden().pickerStyle(.menu).neutralControlTint()
            }
            PricingNewSelectorRow(label: "Model") {
                Text(engine?.modelID ?? "—")
                    .font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
    }

    @ViewBuilder
    private var marketDataSection: some View {
        if let spec = product?.underlying {
            VStack(alignment: .leading, spacing: 5) {
                HStack {
                    Text("REAL UNDERLYINGS")
                        .font(Typography.label).tracking(0.4).foregroundStyle(Theme.positive)
                    Spacer()
                    Text(spec.categories.map { $0.uppercased() }.joined(separator: " · "))
                        .font(Typography.micro).foregroundStyle(.tertiary).lineLimit(1)
                }
                HStack(spacing: 4) {
                    TextField("SECID / ISIN / issuer", text: $leg.underlyingQuery)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { Task { await vm.searchUnderlying(for: leg) } }
                    Button { Task { await vm.searchUnderlying(for: leg) } } label: {
                        if leg.isSearching { ProgressView().controlSize(.mini) }
                        else { Image(systemName: "magnifyingglass") }
                    }
                    .buttonStyle(.bordered).controlSize(.mini)
                }
                if !leg.underlyingHits.isEmpty {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(leg.underlyingHits.prefix(6)) { hit in
                            Button { Task { await vm.pickUnderlying(hit, for: leg) } } label: {
                                HStack {
                                    Text(hit.secid).font(Typography.captionStrong)
                                    Text(hit.issuerRu ?? hit.isin ?? "")
                                        .font(Typography.micro).foregroundStyle(.secondary).lineLimit(1)
                                    Spacer()
                                    if let last = hit.last {
                                        Text(Fmt.number(last, digits: 3)).font(Typography.micro).monospacedDigit()
                                    }
                                }.padding(.vertical, 3)
                            }.buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 5)
                    .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 5))
                }
                if !leg.selectedUnderlyings.isEmpty {
                    PricingNewFlowLayout(spacing: 4) {
                        ForEach(leg.selectedUnderlyings) { item in
                            HStack(spacing: 3) {
                                Circle().fill(Theme.positive).frame(width: 5, height: 5)
                                Text(item.secid).font(Typography.micro)
                                Button { vm.removeUnderlying(item, from: leg) } label: {
                                    Image(systemName: "xmark").font(.system(size: 7, weight: .bold))
                                }.buttonStyle(.plain)
                            }
                            .padding(.horizontal, 5).padding(.vertical, 3)
                            .background(Theme.positive.opacity(0.10), in: Capsule())
                        }
                    }
                }
            }
            .padding(Theme.s2)
            .overlay(alignment: .bottom) { Divider().opacity(0.4) }
        }
    }

    private var parameterRows: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let attachment = vm.customAttachment(for: leg) {
                customAttachmentSummary(attachment)
            }
            ForEach(groups, id: \.self) { group in
                let specs = (engine?.params ?? []).filter {
                    $0.group == group && $0.key != "attachment_json"
                        && (leg.showAdvanced || !$0.advanced)
                }
                if !specs.isEmpty {
                    HStack {
                        Text(group.uppercased())
                            .font(Typography.label).tracking(0.55)
                            .foregroundStyle(groupColor(group))
                        Spacer()
                        Text("\(specs.count)").font(Typography.micro).foregroundStyle(.tertiary)
                    }
                    .padding(.horizontal, Theme.s2).padding(.top, Theme.s2).padding(.bottom, 4)
                    ForEach(specs) { spec in
                        PricingNewParameterRow(
                            spec: spec,
                            numeric: leg.numericValues[spec.key] == nil ? nil
                                : vm.numericBinding(spec.key, leg: leg),
                            string: leg.choiceValues[spec.key] == nil ? nil
                                : vm.stringBinding(spec.key, leg: leg),
                            autofilled: leg.autofilledKeys.contains(spec.key))
                    }
                }
            }
            if (engine?.params.contains(where: \.advanced) ?? false) {
                Toggle("Показать advanced parameters", isOn: $leg.showAdvanced)
                    .toggleStyle(.checkbox).font(Typography.micro)
                    .padding(Theme.s2)
            }
            if let note = product?.note, !note.isEmpty {
                Text(note).font(Typography.micro).foregroundStyle(.tertiary)
                    .padding(Theme.s2)
            }
        }
    }

    private func customAttachmentSummary(
        _ attachment: PricingNewCustomProductAttachment
    ) -> some View {
        let payoffBasis = attachment.payoffBasis ?? "legacy_unspecified"
        let stateMode = attachment.stateMode ?? "legacy_unspecified"
        let stateSource = attachment.stateSource ?? "legacy_unspecified"
        let resource = PricingNewCustomProductContract.resourceEstimate(
            assetCount: attachment.market.assets.count,
            paths: Double(attachment.numerical.paths),
            steps: Double(attachment.numerical.steps))
        return VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text("VERSION-PINNED PAYOUT")
                    .font(Typography.label).tracking(0.45)
                    .foregroundStyle(Theme.accent)
                Spacer()
                Pill(text: attachment.definitionState,
                     color: attachment.isResearch ? Theme.warning : Theme.positive)
            }
            Text(attachment.productName)
                .font(Typography.captionStrong).lineLimit(1)
            HStack(spacing: 5) {
                Text("v\(attachment.definitionVersion)")
                Text(attachment.definitionHash.prefix(12))
                Text(attachment.engineID)
            }
            .font(.system(size: 8, design: .monospaced))
            .foregroundStyle(.secondary)
            PricingNewFlowLayout(spacing: 4) {
                ForEach(attachment.market.assets) { asset in
                    HStack(spacing: 3) {
                        Circle().fill(asset.source == .marketSnapshot
                                      ? Theme.positive : Theme.warning)
                            .frame(width: 5, height: 5)
                        Text(asset.secid ?? asset.assetName)
                            .font(Typography.micro)
                    }
                    .padding(.horizontal, 5).padding(.vertical, 3)
                    .background(Color.primary.opacity(0.045), in: Capsule())
                }
            }
            Text("PV = normalized payoff × QTY currency notional (\(leg.currency)) · basis \(payoffBasis)")
                .font(Typography.micro)
                .foregroundStyle(attachment.payoffBasis == nil
                                 ? Theme.warning : .secondary)
            if let schedule = attachment.contractSchedule {
                Text(contractScheduleSummary(schedule))
                    .font(Typography.micro).foregroundStyle(.secondary)
                Text("Fixings " + schedule.fixingBindings.map {
                    "\($0.assetName):\($0.secid)/\($0.board ?? "default")/\($0.priceBasis.rawValue)"
                }.joined(separator: " · "))
                    .font(.system(size: 8, design: .monospaced))
                    .foregroundStyle(.tertiary).lineLimit(2)
            } else {
                Text("Contract schedule missing · legacy/current-state compatibility only")
                    .font(Typography.micro).foregroundStyle(Theme.warning)
            }
            if let state = attachment.valuationState,
               stateMode == PricingNewCustomValuationMode.seasoned.rawValue {
                Text("State seasoned · obs \(state.observationIndex) · elapsed "
                     + "\(Fmt.number(state.elapsedTime, digits: 6))y · as-of "
                     + "\(state.stateAsOf) · source \(stateSource)")
                    .font(Typography.micro).foregroundStyle(.secondary)
                if let hash = state.stateSourceHash {
                    Text("state source \(hash.prefix(16))")
                        .font(.system(size: 8, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
            } else {
                Text("State \(stateMode) · source \(stateSource) · current spots = reference spots")
                    .font(Typography.micro)
                    .foregroundStyle(attachment.stateMode == nil
                                     ? Theme.warning : .secondary)
            }
            if let calibration = attachment.market.correlationCalibration {
                Text("Correlation \(calibration.mode) · \(calibration.method) "
                     + "\(calibration.lookback)d · fallback \(calibration.fallbackPolicy)")
                    .font(Typography.micro).foregroundStyle(.secondary)
            }
            Text(stateMode == "seasoned"
                 ? "Seasoned state is explicit and sequential historical path roll is enabled."
                 : "Inception state; sequential historical path roll is enabled.")
                .font(Typography.micro)
                .foregroundStyle(stateMode == "seasoned" ? Theme.positive : .secondary)
            if let resource {
                Text("MC \(formatMillions(resource.unitPathPoints)) path-points "
                     + "(≈\(Int(resource.estimatedPeakMiB.rounded())) MiB) · Greeks "
                     + "\(formatMillions(resource.greekWorkPathPoints)) work units")
                    .font(.system(size: 8, design: .monospaced))
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(Theme.s2)
        .overlay(alignment: .bottom) { Divider().opacity(0.4) }
    }

    private func formatMillions(_ value: Double) -> String {
        String(format: "%.2fM", value / 1_000_000.0)
    }

    private func contractScheduleSummary(
        _ schedule: PricingNewCustomContractSchedule
    ) -> String {
        let version = schedule.calendarVersion.map { "v\($0)" }
            ?? "server latest"
        return "Contract \(schedule.effectiveDate) → "
            + "\(schedule.contractualMaturityDate) · "
            + "\(schedule.contractualObservationDates.count) obs · "
            + "\(schedule.businessDayConvention.rawValue) · "
            + "\(schedule.calendarID.rawValue) \(version)"
    }

    private func groupColor(_ group: String) -> Color {
        switch group {
        case "contract": Theme.accent
        case "market": Theme.positive
        case "model": Theme.bucketColor("Volatility")
        case "numerical": Theme.bucketColor("Rates")
        default: .secondary
        }
    }
}

private struct PricingNewSelectorRow<Content: View>: View {
    let label: String
    @ViewBuilder var content: Content

    var body: some View {
        HStack(spacing: Theme.s2) {
            Text(label).font(Typography.caption).foregroundStyle(.secondary)
                .frame(width: 82, alignment: .leading)
            content.frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, Theme.s2).padding(.vertical, 4)
    }
}

private struct PricingNewParameterRow: View {
    let spec: ParamSpec
    let numeric: Binding<Double>?
    let string: Binding<String>?
    let autofilled: Bool

    private var outOfBounds: Bool {
        guard let value = numeric?.wrappedValue else { return false }
        return spec.minimum.map { value < $0 } ?? false
            || spec.maximum.map { value > $0 } ?? false
    }

    var body: some View {
        HStack(spacing: Theme.s2) {
            HStack(spacing: 3) {
                if autofilled {
                    Circle().fill(Theme.positive).frame(width: 5, height: 5)
                }
                Text(spec.label).font(Typography.micro).foregroundStyle(.secondary)
                    .lineLimit(1)
                if !spec.unit.isEmpty {
                    Text(spec.unit).font(.system(size: 8)).foregroundStyle(.quaternary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            field
                .overlay {
                    RoundedRectangle(cornerRadius: 4)
                        .stroke(outOfBounds ? Theme.negative : Color.clear, lineWidth: 1)
                }
        }
        .padding(.horizontal, Theme.s2).padding(.vertical, 3)
        .help(spec.help)
    }

    @ViewBuilder
    private var field: some View {
        if spec.dtype == "choice", let string {
            Picker("", selection: string) {
                ForEach(spec.choices ?? [], id: \.self) { Text($0).tag($0) }
            }.labelsHidden().pickerStyle(.menu).neutralControlTint().fixedSize()
        } else if let numeric {
            TextField("", value: numeric,
                      format: spec.dtype == "int"
                        ? .number.precision(.fractionLength(0)) : .number)
                .textFieldStyle(.roundedBorder).monospacedDigit()
                .multilineTextAlignment(.trailing)
                .frame(width: 112)
        } else if let string {
            TextField("", text: string)
                .textFieldStyle(.roundedBorder).multilineTextAlignment(.trailing)
                .frame(width: 112)
        }
    }
}

// MARK: - Transient risk for the saved worksheet

struct PricingNewRiskBlock: View {
    @Bindable var vm: PricingNewWorkspaceViewModel

    private let models: [(String, String)] = [
        ("historical_full_reprice", "Historical · full reprice"),
        ("parametric_normal", "Parametric · Normal"),
        ("parametric_t", "Parametric · Student-t"),
        ("monte_carlo_fitted_normal", "Monte Carlo · fitted Normal"),
    ]

    private var hasCustomAST: Bool {
        vm.legs.contains { vm.customAttachment(for: $0) != nil }
    }

    private var customHorizonUnsupported: Bool {
        hasCustomAST && !(1...250).contains(vm.riskHorizon)
    }

    private var customWindowUnsupported: Bool {
        hasCustomAST && vm.riskWindow > 500
    }

    private var customPolicyUnsupported: Bool {
        customHorizonUnsupported || customWindowUnsupported
    }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("Риск текущего расчёта", icon: "shield.lefthalf.filled")
                    SourceBadge(live: true, label: "stored real factor history")
                    Spacer()
                    if let capability = vm.riskCapability {
                        Pill(text: capability.supported ? "book supported" : "risk blocked",
                             color: capability.supported ? Theme.positive : Theme.warning)
                    } else if vm.lastRunID == nil {
                        Pill(text: "price first", color: .secondary)
                    }
                }
                controls
                if vm.riskModel == "historical_full_reprice" {
                    historicalStateExplanation
                }
                if hasCustomAST {
                    Label(vm.effectiveHistoricalStateMode == .actualTradeBackcast
                          ? "Custom AST actual-trade backcast · historical lifecycle reconstruction · 1 000 inner paths · paired CRN"
                          : "Custom AST current-state HypPL · current lifecycle state + historical factor paths · 1 000 inner paths · paired CRN",
                          systemImage: "checkmark.shield.fill")
                        .font(Typography.micro)
                        .foregroundStyle(.secondary)
                    if customHorizonUnsupported {
                        Label("Custom AST horizon должен быть от 1 до 250 дней.",
                              systemImage: "exclamationmark.triangle.fill")
                            .font(Typography.micro).foregroundStyle(Theme.warning)
                    }
                    if customWindowUnsupported {
                        Label("History window \(vm.riskWindow) превышает custom AST limit 500 scenarios. Уменьши HISTORY до 500.",
                              systemImage: "exclamationmark.triangle.fill")
                            .font(Typography.micro).foregroundStyle(Theme.warning)
                    }
                }
                if vm.isStale {
                    Label("Сначала пересчитай изменённые inputs: риск всегда привязан к immutable run.",
                          systemImage: "lock.trianglebadge.exclamationmark")
                        .font(Typography.caption).foregroundStyle(Theme.warning)
                }
                if let message = vm.riskErrorMessage {
                    Label(message, systemImage: "exclamationmark.triangle.fill")
                        .font(Typography.caption).foregroundStyle(Theme.negative)
                }
                capabilityDetails
                if let result = vm.riskResult {
                    riskResult(result)
                } else if vm.isRisking {
                    ProgressView("Полная переоценка исторических сценариев…")
                        .controlSize(.small).font(Typography.caption)
                }
            }
        }
    }

    private var controls: some View {
        HStack(alignment: .bottom, spacing: Theme.s3) {
            riskField("MODEL") {
                Picker("Model", selection: $vm.riskModel) {
                    ForEach(models, id: \.0) { Text($0.1).tag($0.0) }
                }.labelsHidden().pickerStyle(.menu).neutralControlTint().frame(width: 220)
            }
            riskField("STATE HISTORY") {
                Picker("Historical state mode", selection: Binding(
                    get: { vm.effectiveHistoricalStateMode },
                    set: { vm.selectHistoricalStateMode($0) }
                )) {
                    Text("Current-state HypPL")
                        .tag(PricingNewHistoricalStateMode.currentStateHypPL)
                    Text("Actual trade backcast")
                        .tag(PricingNewHistoricalStateMode.actualTradeBackcast)
                }
                .labelsHidden().pickerStyle(.menu).neutralControlTint()
                .frame(width: 190)
                .disabled(vm.riskModel != "historical_full_reprice")
            }
            riskField("CONFIDENCE") {
                Picker("Confidence", selection: $vm.riskConfidence) {
                    Text("95.0%").tag(0.95)
                    Text("97.5%").tag(0.975)
                    Text("99.0%").tag(0.99)
                    Text("99.5%").tag(0.995)
                }.labelsHidden().pickerStyle(.menu).neutralControlTint().fixedSize()
            }
            riskField("HISTORY") {
                HStack(spacing: 3) {
                    TextField("Window", value: $vm.riskWindow, format: .number)
                        .textFieldStyle(.roundedBorder).monospacedDigit().frame(width: 66)
                    Text("obs").font(Typography.micro).foregroundStyle(.tertiary)
                }
            }
            riskField("HORIZON") {
                HStack(spacing: 3) {
                    TextField("Days", value: $vm.riskHorizon, format: .number)
                        .textFieldStyle(.roundedBorder).monospacedDigit().frame(width: 48)
                    Text("d").font(Typography.micro).foregroundStyle(.tertiary)
                }
            }
            if vm.riskModel == "monte_carlo_fitted_normal" {
                riskField("SIMULATIONS") {
                    TextField("Paths", value: $vm.riskSims, format: .number)
                        .textFieldStyle(.roundedBorder).monospacedDigit().frame(width: 86)
                }
                riskField("SEED") {
                    TextField("Seed", value: $vm.riskSeed, format: .number)
                        .textFieldStyle(.roundedBorder).monospacedDigit().frame(width: 64)
                }
            }
            Spacer(minLength: 0)
            Button { Task { await vm.runRisk() } } label: {
                if vm.isRisking { ProgressView().controlSize(.small) }
                else { Label("Рассчитать VaR / ES", systemImage: "waveform.path.ecg") }
            }
            .buttonStyle(.borderedProminent).tint(Theme.accent).controlSize(.small)
            .disabled(!vm.canRunRisk || customPolicyUnsupported)
        }
        .padding(Theme.s2)
        .background(Color.primary.opacity(0.025), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var historicalStateExplanation: some View {
        Group {
            if vm.effectiveHistoricalStateMode == .actualTradeBackcast {
                Label("Actual trade backcast восстанавливает lifecycle/path state сделки на каждой исторической scenario date. Это backcast P&L, не обычный HypPL.",
                      systemImage: "calendar.badge.clock")
            } else {
                Label("Current-state HypPL применяет исторические factor paths к сегодняшнему lifecycle/path state сделки.",
                      systemImage: "clock.arrow.circlepath")
            }
        }
        .font(Typography.micro).foregroundStyle(.secondary)
    }

    @ViewBuilder
    private var capabilityDetails: some View {
        if let capability = vm.riskCapability, !capability.supported {
            VStack(alignment: .leading, spacing: 3) {
                Text("RISK CAPABILITY GATE")
                    .font(Typography.label).foregroundStyle(Theme.warning)
                ForEach(capability.unsupported) { issue in
                    HStack(alignment: .firstTextBaseline, spacing: Theme.s2) {
                        Text(issue.label.isEmpty ? issue.product : issue.label)
                            .font(Typography.captionStrong).frame(width: 150, alignment: .leading)
                        Text(issue.code).font(.system(size: 9, design: .monospaced))
                            .foregroundStyle(Theme.warning).frame(width: 150, alignment: .leading)
                        Text(issue.reason).font(Typography.caption).foregroundStyle(.secondary)
                    }
                }
                Text("Частичный риск не подменяет полный: unsupported leg блокирует весь book.")
                    .font(Typography.micro).foregroundStyle(.tertiary)
            }
            .padding(Theme.s2)
            .background(Theme.warning.opacity(0.06), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
    }

    private func riskResult(_ result: PricingNewRiskResult) -> some View {
        let stateMode = result.historicalStateMode
            ?? vm.effectiveHistoricalStateMode.rawValue
        let isActualBackcast = stateMode
            == PricingNewHistoricalStateMode.actualTradeBackcast.rawValue
        return VStack(alignment: .leading, spacing: Theme.s3) {
            HStack(spacing: Theme.s2) {
                PricingNewRiskTile(label: "VaR \(Fmt.percent(result.confidence * 100, digits: 1))",
                                   value: Fmt.money(result.varValue, currency: result.currency),
                                   color: Theme.negative)
                PricingNewRiskTile(label: "Expected shortfall",
                                   value: Fmt.money(result.es, currency: result.currency),
                                   color: Theme.warning)
                PricingNewRiskTile(label: "Portfolio value",
                                   value: Fmt.money(result.portfolioValue, currency: result.currency),
                                   color: Theme.accent)
                PricingNewRiskTile(label: "Scenarios", value: "\(result.nScenarios)",
                                   color: Theme.bucketColor("Rates"))
                PricingNewRiskTile(label: "History",
                                   value: "\(result.provenance.historyObservations) obs",
                                   color: Theme.positive)
                Spacer()
            }
            operationalEvidence(result)
            HStack(alignment: .top, spacing: Theme.s3) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(isActualBackcast
                         ? "ACTUAL-TRADE BACKCAST P&L DISTRIBUTION"
                         : "HYPOTHETICAL P&L DISTRIBUTION")
                        .font(Typography.label).foregroundStyle(.secondary)
                    Chart(result.histogram, id: \.x) { bin in
                        BarMark(x: .value("P&L", bin.x), y: .value("Count", bin.count))
                            .foregroundStyle(Theme.accent.opacity(0.65))
                        RuleMark(x: .value("VaR", -result.varValue))
                            .foregroundStyle(Theme.negative)
                            .lineStyle(StrokeStyle(lineWidth: 1.5, dash: [4, 3]))
                    }
                    .frame(height: 170)
                }
                .frame(maxWidth: .infinity)
                VStack(alignment: .leading, spacing: 4) {
                    Text(isActualBackcast
                         ? "HISTORICAL ACTUAL-TRADE BACKCAST"
                         : "HISTORICAL CURRENT-STATE HYPPL")
                        .font(Typography.label).foregroundStyle(.secondary)
                    Chart(Array(result.hyppl.enumerated()), id: \.offset) { index, point in
                        LineMark(x: .value("Scenario", index), y: .value("P&L", point.pnl))
                            .foregroundStyle(Theme.bucketColor("Rates"))
                        AreaMark(x: .value("Scenario", index), y: .value("P&L", point.pnl))
                            .foregroundStyle(Theme.bucketColor("Rates").opacity(0.10))
                        RuleMark(y: .value("Zero", 0)).foregroundStyle(.secondary.opacity(0.35))
                    }
                    .frame(height: 170)
                }
                .frame(maxWidth: .infinity)
            }
            HStack(spacing: Theme.s3) {
                Label(result.modelLabel, systemImage: "function")
                Label(isActualBackcast ? "actual trade backcast"
                      : "current-state HypPL",
                      systemImage: "point.topleft.down.to.point.bottomright.curvepath")
                Label("horizon \(result.horizon)d · \(result.horizonMethod ?? "legacy_unspecified")",
                      systemImage: "clock.arrow.circlepath")
                Label("\(result.provenance.historyFirstDate ?? "—") → \(result.provenance.historyLastDate ?? "—")",
                      systemImage: "calendar")
                if let valuationDate = result.provenance.valuationDate,
                   !valuationDate.isEmpty {
                    Label("as-of \(valuationDate)", systemImage: "calendar.badge.clock")
                }
                if let timestamp = result.provenance.calculationTimestamp,
                   !timestamp.isEmpty {
                    Label("calculated \(timestamp)", systemImage: "checkmark.seal")
                }
                Label("global portfolio: \(result.provenance.globalPortfolioUsed ? "YES" : "NO")",
                      systemImage: "lock.shield")
                Spacer()
                Text("audit \(result.provenance.calculationID.prefix(10))")
                    .font(.system(size: 9, design: .monospaced))
            }
            .font(Typography.micro).foregroundStyle(.tertiary)
        }
    }

    @ViewBuilder
    private func operationalEvidence(_ result: PricingNewRiskResult) -> some View {
        let model = result.modelDiagnostics?.objectValue ?? [:]
        let factors = result.provenance.factorDiagnostics?.objectValue ?? [:]
        let custom = result.provenance.customRepricing?.objectValue
        let execution = custom?["execution"]?.objectValue
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: Theme.s2) {
                Pill(text: "horizon \(result.horizonMethod ?? "legacy")",
                     color: result.horizonMethod == nil ? Theme.warning : Theme.positive)
                Pill(text: result.historicalStateMode
                     ?? vm.effectiveHistoricalStateMode.rawValue,
                     color: (result.historicalStateMode
                             ?? vm.effectiveHistoricalStateMode.rawValue)
                        == PricingNewHistoricalStateMode.actualTradeBackcast.rawValue
                        ? Theme.accent : .secondary)
                if !model.isEmpty {
                    Text("model \(diagnosticsSummary(model))")
                }
                if !factors.isEmpty {
                    Text("factor routes \(factors.count) · \(factors.keys.sorted().joined(separator: ", "))")
                        .lineLimit(1)
                    Text("factor hash \(jsonFingerprint(.object(factors)).prefix(12))")
                }
                if let scenarioHash = result.provenance.scenarioMatrixHash,
                   !scenarioHash.isEmpty {
                    Text("scenario matrix \(scenarioHash.prefix(12))")
                }
                Spacer(minLength: 0)
            }
            .font(.system(size: 8, design: .monospaced))
            .foregroundStyle(.secondary)

            if let custom {
                HStack(spacing: Theme.s2) {
                    Pill(text: custom["profile"]?.stringValue ?? "custom profile missing",
                         color: custom["profile"]?.stringValue == "custom_hist_crn_v1"
                            ? Theme.positive : Theme.warning)
                    evidenceToken("inner", custom["inner_paths"], suffix: " paths")
                    evidenceToken("scenarios", custom["actual_scenarios"],
                                  denominator: custom["requested_scenarios"])
                    evidenceToken("limit", custom["scenario_limit"], suffix: " scenarios")
                    Text("state horizon \(custom["horizon_method"]?.stringValue ?? "—")")
                    Spacer(minLength: 0)
                }
                .font(.system(size: 8, design: .monospaced))
                .foregroundStyle(.secondary)
                HStack(spacing: Theme.s2) {
                    evidenceToken("work", custom["actual_work_path_points"],
                                  denominator: custom["requested_work_path_points"])
                    evidenceToken("work limit", custom["work_limit_path_points"])
                    evidenceToken("deadline", custom["deadline_seconds"], suffix: "s")
                    Text("CRN \(custom["common_random_numbers"]?.boolValue == true ? "YES" : "NO")")
                    if let execution {
                        evidenceToken("elapsed", execution["elapsed_seconds"], suffix: "s", digits: 3)
                        let sources = execution["base_value_sources"]?.arrayValue?
                            .compactMap(\.stringValue).joined(separator: "+") ?? "—"
                        Text("base \(sources)")
                        Text("cache/reprice-once \(execution["base_value_repriced_once"]?.boolValue == true ? "YES" : "NO")")
                    }
                    Spacer(minLength: 0)
                }
                .font(.system(size: 8, design: .monospaced))
                .foregroundStyle(.secondary)
            }
        }
        .padding(Theme.s2)
        .background(Color.primary.opacity(0.025),
                    in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    @ViewBuilder
    private func evidenceToken(_ label: String, _ value: JSONValue?,
                               denominator: JSONValue? = nil,
                               suffix: String = "", digits: Int = 0) -> some View {
        let current = value?.doubleValue.map {
            Fmt.number($0, digits: digits)
        } ?? "—"
        if let total = denominator?.doubleValue {
            Text("\(label) \(current)/\(Fmt.number(total, digits: digits))\(suffix)")
        } else {
            Text("\(label) \(current)\(suffix)")
        }
    }

    private func diagnosticsSummary(_ values: [String: JSONValue]) -> String {
        values.keys.sorted().prefix(4).map { key in
            guard let value = values[key] else { return key }
            if let text = value.stringValue { return "\(key)=\(text)" }
            if let number = value.doubleValue {
                return "\(key)=\(Fmt.number(number, digits: 3))"
            }
            if let flag = value.boolValue { return "\(key)=\(flag ? "true" : "false")" }
            return key
        }.joined(separator: " · ")
    }

    private func riskField<Content: View>(_ label: String,
                                          @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(Typography.label).foregroundStyle(.secondary)
            content()
        }
    }
}

private struct PricingNewRiskTile: View {
    let label: String
    let value: String
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased()).font(Typography.micro).foregroundStyle(.secondary)
            Text(value).font(Typography.metricValue).monospacedDigit().lineLimit(1)
        }
        .padding(Theme.s2).frame(minWidth: 120, alignment: .leading)
        .background(color.opacity(0.09), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

// MARK: - Dense shared pieces

private struct PricingNewMetricTile: View {
    let label: String
    let value: String
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label.uppercased()).font(Typography.micro).foregroundStyle(.secondary)
            Text(value).font(Typography.bodyMedium).monospacedDigit().lineLimit(1)
        }
        .padding(.horizontal, Theme.s2).padding(.vertical, 5)
        .frame(minWidth: 90, alignment: .leading)
        .background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

/// Lightweight wrapping layout for chips and metrics; no nested tabs or sheets.
struct PricingNewFlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews,
                      cache: inout ()) -> CGSize {
        layout(proposal: proposal, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize,
                       subviews: Subviews, cache: inout ()) {
        let result = layout(proposal: ProposedViewSize(width: bounds.width,
                                                       height: proposal.height),
                            subviews: subviews)
        for (index, point) in result.points.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + point.x,
                                              y: bounds.minY + point.y),
                                  proposal: .unspecified)
        }
    }

    private func layout(proposal: ProposedViewSize, subviews: Subviews)
        -> (size: CGSize, points: [CGPoint]) {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var lineHeight: CGFloat = 0
        var points: [CGPoint] = []
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width {
                x = 0
                y += lineHeight + spacing
                lineHeight = 0
            }
            points.append(CGPoint(x: x, y: y))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
        return (CGSize(width: width.isFinite ? width : x,
                       height: y + lineHeight), points)
    }
}

extension JSONValue {
    var objectValue: [String: JSONValue]? {
        if case .object(let value) = self { return value }
        return nil
    }

    var arrayValue: [JSONValue]? {
        if case .array(let value) = self { return value }
        return nil
    }

    var stringValue: String? {
        if case .string(let value) = self { return value }
        return nil
    }

    var boolValue: Bool? {
        if case .bool(let value) = self { return value }
        return nil
    }
}

private func jsonFingerprint(_ value: JSONValue) -> String {
    let digest = SHA256.hash(data: Data(canonicalJSON(value).utf8))
    return digest.map { String(format: "%02x", $0) }.joined()
}

private func canonicalJSON(_ value: JSONValue) -> String {
    switch value {
    case .null:
        return "null"
    case .bool(let flag):
        return flag ? "true" : "false"
    case .number(let number):
        return String(format: "%.17g", number)
    case .string(let text):
        let encoded = try? JSONSerialization.data(withJSONObject: [text])
        let array = encoded.flatMap { String(data: $0, encoding: .utf8) } ?? "[\"\"]"
        return String(array.dropFirst().dropLast())
    case .array(let values):
        return "[" + values.map(canonicalJSON).joined(separator: ",") + "]"
    case .object(let values):
        return "{" + values.keys.sorted().map { key in
            canonicalJSON(.string(key)) + ":" + canonicalJSON(values[key] ?? .null)
        }.joined(separator: ",") + "}"
    }
}
