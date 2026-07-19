import SwiftUI
import Charts
import Observation

// MARK: - Multi-instrument pricing contract

/// One editable position in the local Pricing Set.  It points to an immutable
/// calculator run, while quantity and desk label remain set-level inputs.
struct PricingBookLegDraft: Identifiable, Sendable {
    let id: UUID
    var label: String
    let run: PricingRunRecord
    var quantity: Double

    init(run: PricingRunRecord, label: String, quantity: Double = 1) {
        id = UUID()
        self.label = label
        self.run = run
        self.quantity = quantity
    }

    var params: [String: BridgeValue] {
        var values: [String: BridgeValue] = [:]
        for (key, value) in run.numericValues {
            values[key] = BridgeValue(kind: .number(value))
        }
        for (key, value) in run.choiceValues {
            values[key] = BridgeValue(kind: .string(value))
        }
        if let secid = run.underlyingSecID {
            values["secid"] = BridgeValue(kind: .string(secid))
        }
        return values
    }
}

private struct WsBookLegBody: Encodable {
    let id: String
    let label: String
    let product: String
    let engine: String
    let risk_factor_id: String?
    let params: [String: BridgeValue]
    let quantity: Double
}

private struct WsBookBody: Encodable {
    let legs: [WsBookLegBody]
    let env_id: String?
}

struct WsBookLegResult: Decodable, Sendable, Identifiable {
    let id: String
    let label: String
    let product: String
    let engine: String?
    let riskFactorID: String?
    let quantity: Double
    let unitValue: Double?
    let positionValue: Double?
    let greeks: [WsMeasure]
    let result: WsResult?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case id, label, product, engine, quantity, greeks, result, error
        case riskFactorID = "risk_factor_id"
        case unitValue = "unit_value"
        case positionValue = "position_value"
    }
}

struct WsBookAggregation: Decodable, Sendable {
    let status: String
    let compatible: Bool
    let greeksCompatible: Bool?
    let basis: String?
    let riskFactorBasis: String?
    let reason: String

    enum CodingKeys: String, CodingKey {
        case status, compatible, basis, reason
        case greeksCompatible = "greeks_compatible"
        case riskFactorBasis = "risk_factor_basis"
    }
}

struct WsBookResult: Decodable, Sendable {
    let environment: String?
    let snapshotID: String?
    let contextHash: String?
    let calculationID: String?
    let calculationTimestamp: String?
    let inputsHash: String?
    let aggregation: WsBookAggregation?
    let count: Int
    let successCount: Int
    let totalValue: Double?
    let greeks: [WsMeasure]
    let legs: [WsBookLegResult]
    let errors: [String]

    enum CodingKeys: String, CodingKey {
        case environment, count, greeks, legs, errors, aggregation
        case snapshotID = "snapshot_id"
        case contextHash = "context_hash"
        case calculationID = "calculation_id"
        case calculationTimestamp = "calculation_timestamp"
        case inputsHash = "inputs_hash"
        case successCount = "success_count"
        case totalValue = "total_value"
    }
}

extension BridgeClient {
    func priceBook(_ legs: [PricingBookLegDraft], envID: String?) async throws -> WsBookResult {
        let requestLegs = legs.map {
            WsBookLegBody(
                id: $0.id.uuidString,
                label: $0.label,
                product: $0.run.productID,
                engine: $0.run.engineID,
                risk_factor_id: $0.run.underlyingSecID,
                params: $0.params,
                quantity: $0.quantity)
        }
        let body = try JSONEncoder().encode(
            WsBookBody(legs: requestLegs, env_id: envID))
        return try await post("pricing/book/price", body: body)
    }
}

// MARK: - State

@MainActor
@Observable
final class PricingBookViewModel {
    var legs: [PricingBookLegDraft] = []
    var environments: [WsEnvironment] = []
    var envID = "FO"
    var result: WsBookResult?
    var isPricing = false
    var errorMessage: String?
    var selectedGreek = "delta"
    private var pricedSignature: String?

    private let client = BridgeClient()

    var currentSignature: String {
        let rows = legs.map {
            "\($0.id.uuidString)|\($0.run.fingerprint)|\($0.quantity)|\($0.label)"
        }
        return ([envID] + rows).joined(separator: "\u{1f}")
    }

    var isStale: Bool {
        result != nil && pricedSignature != currentSignature
    }

    var availableGreekKeys: [String] {
        let aggregate = result?.greeks.map(\.key) ?? []
        let byLeg = result?.legs.flatMap { $0.greeks.map(\.key) } ?? []
        let keys = Set(aggregate + byLeg)
        let priority = ["delta", "gamma", "vega", "theta", "rho", "dv01", "cs01"]
        return priority.filter(keys.contains) + keys.subtracting(priority).sorted()
    }

    func load() async {
        guard environments.isEmpty else { return }
        environments = (try? await client.environments()) ?? []
        if !environments.contains(where: { $0.envID == envID }),
           let first = environments.first {
            envID = first.envID
        }
    }

    func add(_ run: PricingRunRecord) {
        guard run.result.value != nil, run.result.errors.isEmpty else { return }
        let sequence = legs.filter { $0.run.productID == run.productID }.count + 1
        legs.append(PricingBookLegDraft(
            run: run,
            label: sequence == 1 ? run.productName : "\(run.productName) \(sequence)"))
        if legs.count == 1, let origin = run.envID, !origin.isEmpty { envID = origin }
        result = nil
        pricedSignature = nil
    }

    func duplicate(_ id: UUID) {
        guard let source = legs.first(where: { $0.id == id }) else { return }
        legs.append(PricingBookLegDraft(
            run: source.run, label: source.label + " copy", quantity: source.quantity))
        result = nil
        pricedSignature = nil
    }

    func remove(_ id: UUID) {
        legs.removeAll { $0.id == id }
        result = nil
        pricedSignature = nil
    }

    func labelBinding(_ id: UUID) -> Binding<String> {
        Binding(
            get: { self.legs.first(where: { $0.id == id })?.label ?? "" },
            set: { value in
                guard let index = self.legs.firstIndex(where: { $0.id == id }) else { return }
                self.legs[index].label = value
            })
    }

    func quantityBinding(_ id: UUID) -> Binding<Double> {
        Binding(
            get: { self.legs.first(where: { $0.id == id })?.quantity ?? 0 },
            set: { value in
                guard let index = self.legs.firstIndex(where: { $0.id == id }) else { return }
                self.legs[index].quantity = value
            })
    }

    func priceAll() async {
        guard !legs.isEmpty, !isPricing else { return }
        // Freeze the submitted book before the suspension point.  Quantity,
        // labels and environment remain editable while the HTTP call is in
        // flight; using currentSignature after await would incorrectly bless
        // a response for old inputs as current.
        let submittedLegs = legs
        let submittedEnvID = envID.isEmpty ? nil : envID
        let submittedSignature = currentSignature
        isPricing = true
        errorMessage = nil
        do {
            let priced = try await client.priceBook(
                submittedLegs, envID: submittedEnvID)
            result = priced
            pricedSignature = submittedSignature
            if !priced.errors.isEmpty { errorMessage = priced.errors.joined(separator: " · ") }
            if !availableGreekKeys.contains(selectedGreek) {
                selectedGreek = availableGreekKeys.first ?? "delta"
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        isPricing = false
    }

    func result(for id: UUID) -> WsBookLegResult? {
        result?.legs.first { $0.id.caseInsensitiveCompare(id.uuidString) == .orderedSame }
    }
}

// MARK: - View

struct PricingBookView: View {
    @Bindable var vm: PricingBookViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s5) {
                header
                if vm.legs.isEmpty {
                    emptyState
                } else {
                    if let result = vm.result { aggregateSummary(result) }
                    positionsTable
                    if let result = vm.result,
                       result.legs.contains(where: { !$0.greeks.isEmpty }) {
                        greekContribution(result)
                    }
                    inputInspector
                }
            }
            .padding(Theme.s5)
            .frame(maxWidth: Theme.contentMaxWidth, alignment: .leading)
        }
        .task { await vm.load() }
    }

    private var header: some View {
        PageHeader("Pricing Set",
                   subtitle: "Несколько позиций · единый environment и frozen market context") {
            HStack(spacing: Theme.s2) {
                if !vm.environments.isEmpty {
                    Picker("Environment", selection: $vm.envID) {
                        ForEach(vm.environments) { env in
                            Text("\(env.envID) · \(env.name)").tag(env.envID)
                        }
                    }
                    .pickerStyle(.menu).neutralControlTint().fixedSize()
                }
                if vm.isStale {
                    Pill(text: "Inputs changed", color: Theme.warning)
                }
                Button {
                    Task { await vm.priceAll() }
                } label: {
                    if vm.isPricing {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("Price all", systemImage: "bolt.fill")
                    }
                }
                .buttonStyle(.borderedProminent).tint(Theme.accent).controlSize(.large)
                .disabled(vm.isPricing || vm.legs.isEmpty)
            }
        }
    }

    private var emptyState: some View {
        GlassCard {
            ContentUnavailableView {
                Label("Pricing Set is empty", systemImage: "text.badge.plus")
            } description: {
                Text("Рассчитайте инструмент в Calculator и нажмите Add to Pricing Set. Затем добавьте второй инструмент и получите совместные PV и Greeks.")
            }
            .frame(maxWidth: .infinity, minHeight: 360)
        }
    }

    private func aggregateSummary(_ result: WsBookResult) -> some View {
        let greek = Dictionary(uniqueKeysWithValues: result.greeks.map { ($0.key, $0.value) })
        return VStack(alignment: .leading, spacing: Theme.s3) {
            KPIStrip(items: [
                KPICard(label: "Aggregate PV",
                        value: result.totalValue.map { Fmt.number($0, digits: 4) } ?? "—",
                        sub: "\(result.successCount) of \(result.count) positions",
                        accent: Theme.accent, icon: "sum"),
                KPICard(label: "Delta", value: formatGreek(greek["delta"]),
                        sub: "quantity-weighted", accent: Theme.positive,
                        icon: "triangle"),
                KPICard(label: "Gamma", value: formatGreek(greek["gamma"]),
                        sub: "quantity-weighted", accent: Theme.warning,
                        icon: "waveform.path"),
                KPICard(label: "Vega", value: formatGreek(greek["vega"]),
                        sub: "quantity-weighted", accent: Theme.accent,
                        icon: "waveform.path.ecg"),
                KPICard(label: "Theta", value: formatGreek(greek["theta"]),
                        sub: "quantity-weighted", accent: Theme.neutral,
                        icon: "clock")
            ], maxColumns: 5)
            HStack(spacing: Theme.s3) {
                Label("FROZEN RUN", systemImage: "checkmark.shield.fill")
                    .font(.system(size: 10, weight: .semibold)).tracking(0.4)
                    .foregroundStyle(Theme.positive)
                bookEvidence("Environment", result.environment ?? "—")
                bookEvidence("Snapshot", result.snapshotID?.isEmpty == false
                             ? result.snapshotID! : "in-memory")
                bookEvidence("Context", shortHash(result.contextHash))
                bookEvidence("Inputs", shortHash(result.inputsHash))
                Spacer()
            }
            .padding(.horizontal, Theme.s2).padding(.vertical, 7)
            .background(Theme.positive.opacity(0.055),
                        in: RoundedRectangle(cornerRadius: 8))
            if result.aggregation?.compatible == false {
                Label(result.aggregation?.reason
                      ?? "Несовместимые headline measures не агрегируются.",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 10)).foregroundStyle(Theme.warning)
            } else {
                Label(result.aggregation?.reason
                      ?? "Aggregate PV/Greeks допустим только для совместимых позиций.",
                      systemImage: "info.circle")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
            if let message = vm.errorMessage {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.warning)
            }
        }
    }

    private var positionsTable: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    BlockTitle("Positions", icon: "list.bullet.rectangle")
                    Text("\(vm.legs.count)")
                        .font(.system(size: 10, weight: .semibold)).monospacedDigit()
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text("Положительное quantity = long, отрицательное = short")
                        .font(.caption).foregroundStyle(.tertiary)
                }
                .padding(.bottom, Theme.s3)
                bookHeader
                Divider()
                ForEach(vm.legs) { leg in
                    bookRow(leg)
                    if leg.id != vm.legs.last?.id { Divider() }
                }
            }
        }
    }

    private var bookHeader: some View {
        HStack(spacing: Theme.s2) {
            tableHeader("POSITION", width: 180, alignment: .leading)
            tableHeader("INSTRUMENT", width: 150, alignment: .leading)
            tableHeader("MODEL → PRICER", width: 210, alignment: .leading)
            tableHeader("QTY", width: 70, alignment: .trailing)
            tableHeader("PV", width: 90, alignment: .trailing)
            tableHeader("DELTA", width: 80, alignment: .trailing)
            tableHeader("GAMMA", width: 80, alignment: .trailing)
            tableHeader("VEGA", width: 80, alignment: .trailing)
            Spacer(minLength: 0)
            Color.clear.frame(width: 52)
        }
        .padding(.horizontal, Theme.s2).padding(.vertical, 5)
    }

    private func bookRow(_ leg: PricingBookLegDraft) -> some View {
        let priced = vm.result(for: leg.id)
        let greeks = Dictionary(uniqueKeysWithValues: (priced?.greeks ?? []).map { ($0.key, $0.value) })
        return HStack(spacing: Theme.s2) {
            TextField("Position", text: vm.labelBinding(leg.id))
                .textFieldStyle(.plain).font(.system(size: 12, weight: .semibold))
                .frame(width: 180, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(leg.run.productName).lineLimit(1)
                if let secid = leg.run.underlyingSecID {
                    Text(secid).font(.caption).foregroundStyle(.tertiary)
                }
            }
            .font(.system(size: 11)).frame(width: 150, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(priced?.result?.modelDefinitionID ?? leg.run.result.modelDefinitionID
                     ?? leg.run.result.modelID)
                    .lineLimit(1)
                Text(priced?.result?.solverDefinitionID ?? leg.run.result.solverDefinitionID
                     ?? leg.run.engineName)
                    .font(.caption).foregroundStyle(.tertiary).lineLimit(1)
            }
            .font(.system(size: 11)).monospaced()
            .frame(width: 210, alignment: .leading)
            TextField("Qty", value: vm.quantityBinding(leg.id), format: .number)
                .textFieldStyle(.roundedBorder).monospacedDigit()
                .multilineTextAlignment(.trailing).frame(width: 70)
            tableNumber(priced?.positionValue, width: 90)
            tableNumber(greeks["delta"], width: 80)
            tableNumber(greeks["gamma"], width: 80)
            tableNumber(greeks["vega"], width: 80)
            Spacer(minLength: 0)
            Menu {
                Button("Duplicate") { vm.duplicate(leg.id) }
                Divider()
                Button("Remove", role: .destructive) { vm.remove(leg.id) }
            } label: {
                Image(systemName: "ellipsis")
                    .frame(width: 28, height: 28)
            }
            .menuStyle(.borderlessButton).frame(width: 52)
        }
        .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
        .background((priced?.error == nil ? Color.clear : Theme.negative.opacity(0.06)),
                    in: RoundedRectangle(cornerRadius: 8))
        .help(priced?.error ?? "Exact calculator inputs retained below")
    }

    private func greekContribution(_ result: WsBookResult) -> some View {
        let keys = vm.availableGreekKeys
        let selected = keys.contains(vm.selectedGreek) ? vm.selectedGreek : (keys.first ?? "delta")
        let rows = result.legs.compactMap { leg -> (String, Double)? in
            guard let value = leg.greeks.first(where: { $0.key == selected })?.value else { return nil }
            return (leg.label, value)
        }
        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("Greek contribution", icon: "chart.bar.xaxis")
                    Spacer()
                    Picker("Greek", selection: $vm.selectedGreek) {
                        ForEach(keys, id: \.self) { key in
                            Text(key.capitalized).tag(key)
                        }
                    }
                    .pickerStyle(.menu).neutralControlTint().fixedSize()
                }
                Chart(Array(rows.enumerated()), id: \.offset) { _, row in
                    BarMark(x: .value(selected.capitalized, row.1),
                            y: .value("Position", row.0))
                        .foregroundStyle(row.1 >= 0 ? Theme.positive : Theme.negative)
                        .annotation(position: row.1 >= 0 ? .trailing : .leading) {
                            Text(Fmt.number(row.1, digits: 4))
                                .font(.system(size: 9)).monospacedDigit()
                        }
                }
                .frame(height: max(150, CGFloat(rows.count) * 34))
                .chartXAxis { AxisMarks(position: .bottom) }
            }
        }
    }

    private var inputInspector: some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            HStack(spacing: Theme.s2) {
                BlockTitle("Inputs by position", icon: "slider.horizontal.3")
                Text("Точные параметры каждого immutable calculator run")
                    .font(.caption).foregroundStyle(.tertiary)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 340), spacing: Theme.s3)],
                      alignment: .leading, spacing: Theme.s3) {
                ForEach(vm.legs) { leg in
                    GlassCard {
                        VStack(alignment: .leading, spacing: Theme.s3) {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(leg.label).font(.headline)
                                    Text("\(leg.run.productName) · \(leg.run.engineName)")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Pill(text: leg.run.shortHash, color: Theme.accent)
                            }
                            Divider()
                            let numeric = leg.run.numericValues.keys.sorted()
                            let choices = leg.run.choiceValues.keys.sorted()
                            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())],
                                      alignment: .leading, spacing: 6) {
                                ForEach(numeric, id: \.self) { key in
                                    KeyValueRow(key: key,
                                                value: Fmt.number(leg.run.numericValues[key] ?? 0,
                                                                  digits: 6))
                                }
                                ForEach(choices, id: \.self) { key in
                                    KeyValueRow(key: key, value: leg.run.choiceValues[key] ?? "")
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private func tableHeader(_ text: String, width: CGFloat,
                             alignment: Alignment) -> some View {
        Text(text).font(.system(size: 9, weight: .semibold)).tracking(0.45)
            .foregroundStyle(.tertiary).frame(width: width, alignment: alignment)
    }

    private func tableNumber(_ value: Double?, width: CGFloat) -> some View {
        Text(value.map { Fmt.number($0, digits: 4) } ?? "—")
            .font(.system(size: 11)).monospacedDigit()
            .foregroundStyle(value == nil ? .tertiary : .primary)
            .frame(width: width, alignment: .trailing)
    }

    private func formatGreek(_ value: Double?) -> String {
        value.map { Fmt.number($0, digits: 4) } ?? "—"
    }

    private func shortHash(_ value: String?) -> String {
        guard let value, !value.isEmpty else { return "—" }
        return String(value.prefix(12))
    }

    private func bookEvidence(_ label: String, _ value: String) -> some View {
        HStack(spacing: 4) {
            Text(label).foregroundStyle(.tertiary)
            Text(value).foregroundStyle(.secondary).monospaced()
        }
        .font(.system(size: 9))
    }
}
