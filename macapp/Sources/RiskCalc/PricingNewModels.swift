import Foundation
import Observation
import SwiftUI

// MARK: - Pricing_new HTTP contract

struct PricingNewLegBody: Encodable, Sendable {
    let id: String
    let label: String
    let product: String
    let engine: String
    let riskFactorID: String?
    let currency: String?
    let params: [String: BridgeValue]
    let quantity: Double
    let customProduct: PricingNewCustomProductAttachment?

    enum CodingKeys: String, CodingKey {
        case id, label, product, engine, currency, params, quantity
        case riskFactorID = "risk_factor_id"
        case customProduct = "custom_product"
    }
}

struct PricingNewPriceBody: Encodable, Sendable {
    let name: String
    let legs: [PricingNewLegBody]
    let envID: String?

    enum CodingKeys: String, CodingKey {
        case name, legs
        case envID = "env_id"
    }
}

struct PricingNewStoredLeg: Decodable, Sendable {
    let id: String
    let label: String
    let product: String
    let engine: String?
    let riskFactorID: String?
    let currency: String?
    let params: [String: JSONValue]
    let quantity: Double
    let customProduct: PricingNewCustomProductAttachment?

    enum CodingKeys: String, CodingKey {
        case id, label, product, engine, currency, params, quantity
        case riskFactorID = "risk_factor_id"
        case customProduct = "custom_product"
    }
}

struct PricingNewStoredRequest: Decodable, Sendable {
    let legs: [PricingNewStoredLeg]
    let envID: String?

    enum CodingKeys: String, CodingKey {
        case legs
        case envID = "env_id"
    }
}

struct PricingNewRunRecord: Decodable, Sendable, Identifiable {
    let runID: String
    let createdAt: String
    let name: String
    let request: PricingNewStoredRequest
    let result: WsBookResult
    let contentHash: String
    var id: String { runID }

    enum CodingKeys: String, CodingKey {
        case name, request, result
        case runID = "run_id"
        case createdAt = "created_at"
        case contentHash = "content_hash"
    }
}

struct PricingNewRunSummary: Decodable, Sendable, Identifiable {
    let runID: String
    let createdAt: String
    let name: String
    let contentHash: String
    var id: String { runID }

    enum CodingKeys: String, CodingKey {
        case name
        case runID = "run_id"
        case createdAt = "created_at"
        case contentHash = "content_hash"
    }
}

struct PricingNewRunHistory: Decodable, Sendable {
    let runs: [PricingNewRunSummary]
}

struct PricingNewRiskUnsupported: Decodable, Sendable, Identifiable {
    let index: Int
    let id: String
    let label: String
    let product: String
    let engine: String?
    let code: String
    let reason: String
}

struct PricingNewRiskCapability: Decodable, Sendable {
    let supported: Bool
    let requestedCount: Int
    let convertibleCount: Int
    let supportedCount: Int
    let unsupported: [PricingNewRiskUnsupported]
    let currencies: [String]
    let baseCurrency: String?

    enum CodingKeys: String, CodingKey {
        case supported, unsupported, currencies
        case requestedCount = "requested_count"
        case convertibleCount = "convertible_count"
        case supportedCount = "supported_count"
        case baseCurrency = "base_currency"
    }
}

struct PricingNewRiskProvenance: Decodable, Sendable {
    let historySource: String
    let historyFirstDate: String?
    let historyLastDate: String?
    let historyObservations: Int
    let snapshotID: String
    let valuationDate: String?
    let calculationID: String
    let calculationTimestamp: String?
    let inputsHash: String
    let portfolioSource: String
    let globalPortfolioUsed: Bool
    let factorDiagnostics: JSONValue?
    let scenarioMatrixHash: String?
    let customRepricing: JSONValue?

    enum CodingKeys: String, CodingKey {
        case historySource = "history_source"
        case historyFirstDate = "history_first_date"
        case historyLastDate = "history_last_date"
        case historyObservations = "history_observations"
        case snapshotID = "snapshot_id"
        case valuationDate = "valuation_date"
        case calculationID = "calculation_id"
        case calculationTimestamp = "calculation_timestamp"
        case inputsHash = "inputs_hash"
        case portfolioSource = "portfolio_source"
        case globalPortfolioUsed = "global_portfolio_used"
        case factorDiagnostics = "factor_diagnostics"
        case scenarioMatrixHash = "scenario_matrix_hash"
        case customRepricing = "custom_repricing"
    }
}

struct PricingNewRiskResult: Decodable, Sendable {
    let scope: String
    let partial: Bool
    let confidence: Double
    let window: Int
    let horizon: Int
    let horizonMethod: String?
    let model: String
    let modelLabel: String
    let modelDiagnostics: JSONValue?
    let currency: String
    let portfolioValue: Double
    let positions: Int
    let varValue: Double
    let es: Double
    let nScenarios: Int
    let histogram: [MRHistBin]
    let hyppl: [MRPnlPoint]
    let factors: [String]
    let dataQuality: [String]
    let capability: PricingNewRiskCapability
    let provenance: PricingNewRiskProvenance
    let pricingRunID: String
    let pricingRunName: String

    enum CodingKeys: String, CodingKey {
        case scope, partial, confidence, window, horizon, model, currency
        case positions, es, histogram, hyppl, factors, capability, provenance
        case modelLabel = "model_label"
        case horizonMethod = "horizon_method"
        case modelDiagnostics = "model_diagnostics"
        case portfolioValue = "portfolio_value"
        case varValue = "var"
        case nScenarios = "n_scenarios"
        case dataQuality = "data_quality"
        case pricingRunID = "pricing_run_id"
        case pricingRunName = "pricing_run_name"
    }
}

struct PricingNewRiskBody: Encodable, Sendable {
    let confidence: Double
    let window: Int
    let horizon: Int
    let model: String
    let nSims: Int
    let seed: Int

    enum CodingKeys: String, CodingKey {
        case confidence, window, horizon, model, seed
        case nSims = "n_sims"
    }
}

extension BridgeClient {
    func pricingNewPrice(_ request: PricingNewPriceBody) async throws -> PricingNewRunRecord {
        try await post("pricing-new/runs/price", body: JSONEncoder().encode(request))
    }

    func pricingNewRuns() async throws -> [PricingNewRunSummary] {
        try await get("pricing-new/runs", as: PricingNewRunHistory.self).runs
    }

    func pricingNewRun(_ id: String) async throws -> PricingNewRunRecord {
        try await get("pricing-new/runs/\(id)")
    }

    func pricingNewRiskCapability(_ id: String) async throws -> PricingNewRiskCapability {
        try await get("pricing-new/runs/\(id)/risk/capabilities")
    }

    func pricingNewRisk(_ id: String, request: PricingNewRiskBody) async throws
        -> PricingNewRiskResult {
        try await post("pricing-new/runs/\(id)/risk",
                       body: JSONEncoder().encode(request))
    }
}

// MARK: - Editable worksheet state

struct PricingNewUnderlyingRef: Identifiable, Hashable, Sendable {
    let secid: String
    let category: String
    let label: String
    let currency: String?
    var id: String { "\(category)#\(secid)" }
}

@MainActor
@Observable
final class PricingNewLegDraft: Identifiable {
    let id: UUID
    var label: String
    var assetClass: String
    var productID: String
    var engineID: String
    var quantity: Double = 1.0
    var currency: String = "RUB"
    var numericValues: [String: Double] = [:]
    var choiceValues: [String: String] = [:]
    var autofilledKeys: Set<String> = []
    var selectedUnderlyings: [PricingNewUnderlyingRef] = []
    var underlyingQuery = ""
    var underlyingHits: [SearchHit] = []
    var isSearching = false
    var showAdvanced = true

    init(id: UUID = UUID(), label: String, product: WsProductModel,
         engineID: String? = nil) {
        self.id = id
        self.label = label
        self.assetClass = product.assetClass
        self.productID = product.id
        self.engineID = engineID ?? product.engines.first?.id ?? ""
        applyDefaults(product.engines.first(where: { $0.id == self.engineID }))
    }

    func applyDefaults(_ engine: WsEngineModel?) {
        numericValues.removeAll()
        choiceValues.removeAll()
        autofilledKeys.removeAll()
        guard let engine else { return }
        for spec in engine.params {
            switch spec.defaultValue {
            case .number(let value): numericValues[spec.key] = value
            case .string(let value): choiceValues[spec.key] = value
            }
        }
    }

    func bridgeParams() -> [String: BridgeValue] {
        var params: [String: BridgeValue] = [:]
        for (key, value) in numericValues {
            params[key] = BridgeValue(kind: .number(value))
        }
        for (key, value) in choiceValues {
            params[key] = BridgeValue(kind: .string(value))
        }
        if selectedUnderlyings.count == 1, params["secid"] == nil {
            params["secid"] = BridgeValue(kind: .string(selectedUnderlyings[0].secid))
        }
        return params
    }
}

@MainActor
@Observable
final class PricingNewWorkspaceViewModel {
    var catalogue: WsCatalogue?
    var environments: [WsEnvironment] = []
    var envID = "FO"
    var runName = ""
    var legs: [PricingNewLegDraft] = []
    var result: WsBookResult?
    var history: [PricingNewRunSummary] = []
    var lastRunID: String?
    var isLoading = false
    var isPricing = false
    var isRestoring = false
    var errorMessage: String?
    var selectedGreek = "delta"
    var riskConfidence = 0.99
    var riskWindow = 500
    var riskHorizon = 1
    var riskModel = "historical_full_reprice"
    var riskSims = 100_000
    var riskSeed = 42
    var riskCapability: PricingNewRiskCapability?
    var riskResult: PricingNewRiskResult?
    var isRisking = false
    var riskErrorMessage: String?
    private var pricedSignature: String?

    let maxLegs = 5
    private let client = BridgeClient()

    private func basketKind(for category: String) -> String {
        switch category.lowercased() {
        case "equities", "equity": return "equity"
        case "indices", "index": return "index"
        case "bonds", "bond": return "bond"
        case "futures", "future": return "future"
        case "commodities", "commodity": return "commodity"
        default: return category.lowercased()
        }
    }

    private func marketCategory(for kind: String) -> String {
        switch kind.lowercased() {
        case "equity", "equities": return "equities"
        case "index", "indices": return "indices"
        case "bond", "bonds": return "bonds"
        case "future", "futures": return "futures"
        case "commodity", "commodities": return "commodities"
        default: return "restored"
        }
    }

    private func normalizedCurrency(_ raw: String?) -> String? {
        guard let code = raw?.trimmingCharacters(in: .whitespacesAndNewlines)
            .uppercased(), !code.isEmpty else { return nil }
        // MOEX still exposes the historical ISO code SUR in some entity rows.
        // Pricing_new uses the current settlement code in the worksheet and
        // transient-risk scope while retaining the raw market snapshot itself.
        return ["SUR", "RUR"].contains(code) ? "RUB" : code
    }

    var products: [WsProductModel] { catalogue?.products ?? [] }
    var assetClasses: [WsAssetClass] { catalogue?.assetClasses ?? [] }

    var currentSignature: String {
        let rows = legs.map { leg in
            let numeric = leg.numericValues.keys.sorted().map {
                "\($0)=\(leg.numericValues[$0] ?? 0)"
            }.joined(separator: "|")
            let choices = leg.choiceValues.keys.sorted().map {
                "\($0)=\(leg.choiceValues[$0] ?? "")"
            }.joined(separator: "|")
            let underlyings = leg.selectedUnderlyings
                .map { "\($0.category):\($0.secid):\($0.currency ?? "")" }
                .joined(separator: "|")
            return [leg.id.uuidString, leg.label, leg.productID, leg.engineID,
                    "\(leg.quantity)", leg.currency, underlyings, numeric, choices]
                .joined(separator: "\u{1f}")
        }
        return ([envID] + rows).joined(separator: "\u{1e}")
    }

    var isStale: Bool { result != nil && pricedSignature != currentSignature }
    var canRunRisk: Bool {
        lastRunID != nil && !isStale && riskCapability?.supported == true && !isRisking
    }
    var canPrice: Bool {
        !isPricing && !runName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !legs.isEmpty && legs.count <= maxLegs
            && legs.allSatisfy { !$0.productID.isEmpty && !$0.engineID.isEmpty
                && $0.quantity.isFinite && $0.numericValues.values.allSatisfy(\.isFinite)
                && inputsWithinSchema($0) && engineAllowed($0)
                && ($0.productID != "custom_product"
                    || customAttachment(for: $0) != nil) }
    }

    var availableGreekKeys: [String] {
        let aggregate = result?.greeks.map(\.key) ?? []
        let byLeg = result?.legs.flatMap { $0.greeks.map(\.key) } ?? []
        let values = Set(aggregate + byLeg)
        let priority = ["delta", "gamma", "vega", "theta", "rho", "dv01", "cs01"]
        return priority.filter(values.contains) + values.subtracting(priority).sorted()
    }

    func load() async {
        guard catalogue == nil, !isLoading else { return }
        isLoading = true
        errorMessage = nil
        do {
            async let nextCatalogue = client.wsCatalogue()
            async let nextEnvironments = client.environments()
            catalogue = try await nextCatalogue
            environments = try await nextEnvironments
            if !environments.contains(where: { $0.envID == envID }),
               let first = environments.first {
                envID = first.envID
            }
            if legs.isEmpty { addInstrument() }
            history = (try? await client.pricingNewRuns()) ?? []
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    func products(for assetClass: String) -> [WsProductModel] {
        products.filter {
            $0.assetClass == assetClass && $0.id != "custom_product"
        }
            .sorted { lhs, rhs in
                let order = ["Vanilla", "Forwards", "Options", "Swaps", "Bonds",
                             "Exotics", "Multi-asset", "Structured notes"]
                let lhsRank = order.firstIndex(of: lhs.group) ?? order.count
                let rhsRank = order.firstIndex(of: rhs.group) ?? order.count
                if lhsRank != rhsRank { return lhsRank < rhsRank }
                if lhs.group != rhs.group { return lhs.group < rhs.group }
                return lhs.name < rhs.name
            }
    }

    func product(for leg: PricingNewLegDraft) -> WsProductModel? {
        products.first { $0.id == leg.productID }
    }

    func engine(for leg: PricingNewLegDraft) -> WsEngineModel? {
        product(for: leg)?.engines.first { $0.id == leg.engineID }
    }

    private func inputsWithinSchema(_ leg: PricingNewLegDraft) -> Bool {
        guard let specs = engine(for: leg)?.params else { return false }
        return specs.allSatisfy { spec in
            guard let value = leg.numericValues[spec.key] else { return true }
            return (spec.minimum.map { value >= $0 } ?? true)
                && (spec.maximum.map { value <= $0 } ?? true)
        }
    }

    private func engineAllowed(_ leg: PricingNewLegDraft) -> Bool {
        let environment = environments.first { $0.envID == envID }
        return engine(for: leg)?.eligibility?.blockReason(in: environment) == nil
    }

    func addInstrument() {
        guard legs.count < maxLegs else { return }
        let preferredClass = legs.last?.assetClass
            ?? (assetClasses.first(where: { $0.id == "equity" })?.id)
            ?? assetClasses.first?.id
        guard let assetClass = preferredClass,
              let product = (assetClass == "equity"
                    ? products.first(where: { $0.id == "european_option" })
                    : nil) ?? products(for: assetClass).first ?? products.first else { return }
        legs.append(PricingNewLegDraft(
            label: "Position \(legs.count + 1)", product: product))
    }

    func attachCustomProduct(_ attachment: PricingNewCustomProductAttachment) throws {
        guard legs.count < maxLegs else {
            throw BridgeError.server(
                "Worksheet уже содержит максимум \(maxLegs) позиций")
        }
        guard let product = products.first(where: { $0.id == "custom_product" }),
              let engine = product.engines.first(where: { $0.id == "custom_mc" })
        else {
            throw BridgeError.server(
                "Custom Product Engine отсутствует в текущем каталоге")
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        let data = try encoder.encode(attachment)
        guard let json = String(data: data, encoding: .utf8) else {
            throw BridgeError.server(
                "Не удалось сериализовать version-pinned custom attachment")
        }
        let draft = PricingNewLegDraft(
            label: attachment.productName, product: product,
            engineID: engine.id)
        draft.choiceValues["attachment_json"] = json
        draft.showAdvanced = false
        let assetCurrencies = attachment.market.assets.compactMap(\.currency)
        let currencies = Set(assetCurrencies)
        // Never infer a book currency from only part of a custom basket.  An
        // unresolved/manual asset keeps aggregation and transient risk behind
        // the explicit currency gate instead of silently inheriting RUB/USD.
        draft.currency = assetCurrencies.count == attachment.market.assets.count
            && currencies.count == 1 ? (currencies.first ?? "") : ""
        draft.selectedUnderlyings = attachment.market.assets.compactMap { asset in
            guard let secid = asset.secid, let category = asset.category else {
                return nil
            }
            return PricingNewUnderlyingRef(
                secid: secid, category: category,
                label: asset.label ?? asset.assetName,
                currency: asset.currency)
        }
        legs.append(draft)
    }

    func customAttachment(for leg: PricingNewLegDraft)
        -> PricingNewCustomProductAttachment? {
        guard leg.productID == "custom_product",
              let raw = leg.choiceValues["attachment_json"],
              let data = raw.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(
            PricingNewCustomProductAttachment.self, from: data)
    }

    func duplicate(_ leg: PricingNewLegDraft) {
        guard legs.count < maxLegs, let product = product(for: leg) else { return }
        let copy = PricingNewLegDraft(label: leg.label + " copy", product: product,
                                      engineID: leg.engineID)
        copy.quantity = leg.quantity
        copy.currency = leg.currency
        copy.numericValues = leg.numericValues
        copy.choiceValues = leg.choiceValues
        copy.autofilledKeys = leg.autofilledKeys
        copy.selectedUnderlyings = leg.selectedUnderlyings
        copy.showAdvanced = leg.showAdvanced
        legs.append(copy)
    }

    func remove(_ leg: PricingNewLegDraft) {
        legs.removeAll { $0.id == leg.id }
        if legs.isEmpty { addInstrument() }
    }

    func selectAssetClass(_ assetClass: String, for leg: PricingNewLegDraft) {
        guard let product = products(for: assetClass).first else { return }
        leg.assetClass = assetClass
        configure(product: product, leg: leg)
    }

    func selectProduct(_ productID: String, for leg: PricingNewLegDraft) {
        guard let product = products.first(where: { $0.id == productID }) else { return }
        configure(product: product, leg: leg)
    }

    private func configure(product: WsProductModel, leg: PricingNewLegDraft) {
        leg.assetClass = product.assetClass
        leg.productID = product.id
        leg.engineID = product.engines.first?.id ?? ""
        leg.applyDefaults(product.engines.first)
        leg.selectedUnderlyings = []
        leg.underlyingHits = []
        leg.underlyingQuery = ""
    }

    func selectEngine(_ engineID: String, for leg: PricingNewLegDraft) {
        guard engineID != leg.engineID,
              let next = product(for: leg)?.engines.first(where: { $0.id == engineID })
        else { return }
        let oldNumeric = leg.numericValues
        let oldChoices = leg.choiceValues
        leg.engineID = engineID
        leg.applyDefaults(next)
        for (key, value) in oldNumeric where leg.numericValues[key] != nil {
            leg.numericValues[key] = value
        }
        for (key, value) in oldChoices where leg.choiceValues[key] != nil {
            leg.choiceValues[key] = value
        }
    }

    func numericBinding(_ key: String, leg: PricingNewLegDraft) -> Binding<Double> {
        Binding(
            get: { leg.numericValues[key] ?? 0 },
            set: { value in
                leg.numericValues[key] = value
                leg.autofilledKeys.remove(key)
            })
    }

    func stringBinding(_ key: String, leg: PricingNewLegDraft) -> Binding<String> {
        Binding(
            get: { leg.choiceValues[key] ?? "" },
            set: { value in
                leg.choiceValues[key] = value
                leg.autofilledKeys.remove(key)
            })
    }

    func searchUnderlying(for leg: PricingNewLegDraft) async {
        let query = leg.underlyingQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        guard query.count >= 2, let spec = product(for: leg)?.underlying else {
            leg.underlyingHits = []
            return
        }
        leg.isSearching = true
        defer { leg.isSearching = false }
        do {
            let hits = try await client.mdSearch(query).results
            guard leg.underlyingQuery.trimmingCharacters(in: .whitespacesAndNewlines) == query
            else { return }
            let allowed = Set(spec.categories)
            leg.underlyingHits = hits.filter {
                allowed.isEmpty || allowed.contains($0.category ?? "")
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func pickUnderlying(_ hit: SearchHit, for leg: PricingNewLegDraft) async {
        guard let category = hit.category, let spec = product(for: leg)?.underlying else { return }
        do {
            let facts = try await client.pricingNewUnderlyingFacts(
                environment: envID, category: category, secid: hit.secid)
            let ref = PricingNewUnderlyingRef(
                secid: facts.secid, category: facts.category,
                label: facts.label, currency: normalizedCurrency(facts.currency))
            if let appendKey = spec.appendTo {
                if !leg.selectedUnderlyings.contains(where: { $0.id == ref.id }) {
                    leg.selectedUnderlyings.append(ref)
                    let token = appendKey == "component_secids"
                        ? facts.secid
                        : "\(facts.secid):1.0:\(basketKind(for: facts.category))"
                    let current = leg.choiceValues[appendKey] ?? ""
                    leg.choiceValues[appendKey] = current.isEmpty ? token : current + ", " + token
                    leg.autofilledKeys.insert(appendKey)
                }
            } else {
                leg.selectedUnderlyings = [ref]
                for (paramKey, factKey) in spec.fill {
                    guard let value = facts.facts[factKey] ?? nil,
                          leg.numericValues[paramKey] != nil else { continue }
                    leg.numericValues[paramKey] = value
                    leg.autofilledKeys.insert(paramKey)
                }
            }
            let currencies = Set(leg.selectedUnderlyings.compactMap(\.currency))
            if currencies.count == 1 {
                leg.currency = currencies.first ?? leg.currency
            } else if currencies.count > 1 {
                // A mixed-currency structure needs an explicit FX translation
                // policy; blank forces the risk capability gate to explain it.
                leg.currency = ""
            }
            leg.underlyingHits = []
            leg.underlyingQuery = ""
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func removeUnderlying(_ item: PricingNewUnderlyingRef, from leg: PricingNewLegDraft) {
        guard let spec = product(for: leg)?.underlying else { return }
        leg.selectedUnderlyings.removeAll { $0.id == item.id }
        if let appendKey = spec.appendTo {
            // Remove only the selected token. Preserve manually edited weights
            // and optional kind suffixes of every remaining constituent.
            let tokens = (leg.choiceValues[appendKey] ?? "")
                .replacingOccurrences(of: ";", with: ",")
                .split(separator: ",")
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { token in
                    token.split(separator: ":", maxSplits: 1)
                        .first.map(String.init)?.caseInsensitiveCompare(item.secid) != .orderedSame
                }
            leg.choiceValues[appendKey] = tokens.joined(separator: ", ")
        } else {
            // Retain the visible market numbers as explicit manual overrides,
            // but remove their live-data status and identity.
            leg.autofilledKeys.subtract(spec.fill.keys)
        }
    }

    func price() async {
        let name = runName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard canPrice else {
            errorMessage = name.isEmpty ? "Назови расчёт перед запуском" : "Проверь параметры позиций"
            return
        }
        let signature = currentSignature
        let body = PricingNewPriceBody(
            name: name,
            legs: legs.map { leg in
                let attachment = customAttachment(for: leg)
                var params = leg.bridgeParams()
                if attachment != nil {
                    // The immutable run stores this as a typed nested object;
                    // the server materialises the legacy flat adapter only for
                    // the generic workstation dispatcher.
                    params.removeValue(forKey: "attachment_json")
                }
                return PricingNewLegBody(
                    id: leg.id.uuidString, label: leg.label,
                    product: leg.productID, engine: leg.engineID,
                    riskFactorID: leg.selectedUnderlyings.isEmpty ? nil
                        : leg.selectedUnderlyings.map(\.secid).joined(separator: "+"),
                    currency: leg.currency.isEmpty ? nil : leg.currency,
                    params: params, quantity: leg.quantity,
                    customProduct: attachment)
            },
            envID: envID.isEmpty ? nil : envID)
        isPricing = true
        errorMessage = nil
        do {
            let run = try await client.pricingNewPrice(body)
            result = run.result
            lastRunID = run.runID
            pricedSignature = signature
            riskResult = nil
            await loadRiskCapability()
            history = (try? await client.pricingNewRuns()) ?? history
            if !run.result.errors.isEmpty {
                errorMessage = run.result.errors.joined(separator: " · ")
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        isPricing = false
    }

    func restore(_ summary: PricingNewRunSummary) async {
        isRestoring = true
        errorMessage = nil
        defer { isRestoring = false }
        do {
            let record = try await client.pricingNewRun(summary.runID)
            guard record.request.legs.count <= maxLegs else {
                throw BridgeError.server(
                    "Run содержит \(record.request.legs.count) позиций; текущий worksheet поддерживает \(maxLegs)")
            }
            var restored: [PricingNewLegDraft] = []
            for stored in record.request.legs {
                guard let product = products.first(where: { $0.id == stored.product }) else {
                    throw BridgeError.server("Продукт '\(stored.product)' отсутствует в текущем каталоге")
                }
                let id = UUID(uuidString: stored.id) ?? UUID()
                let engineID = stored.engine ?? product.engines.first?.id
                guard let engineID,
                      let selectedEngine = product.engines.first(where: { $0.id == engineID }) else {
                    throw BridgeError.server(
                        "Прайсер '\(stored.engine ?? "—")' больше не опубликован для \(product.name)")
                }
                let draft = PricingNewLegDraft(id: id, label: stored.label,
                                               product: product, engineID: engineID)
                draft.quantity = stored.quantity
                draft.currency = stored.currency ?? ""
                let schema = Dictionary(uniqueKeysWithValues:
                    selectedEngine.params.map { ($0.key, $0) })
                let unknown = Set(stored.params.keys)
                    .subtracting(schema.keys)
                    .subtracting(["secid"])
                guard unknown.isEmpty else {
                    throw BridgeError.server(
                        "Run содержит параметры вне текущей схемы: \(unknown.sorted().joined(separator: ", "))")
                }
                draft.numericValues.removeAll()
                draft.choiceValues.removeAll()
                for (key, value) in stored.params {
                    switch value {
                    case .number(let number):
                        if schema[key] != nil { draft.numericValues[key] = number }
                    case .string(let string):
                        if schema[key] != nil { draft.choiceValues[key] = string }
                    default: break
                    }
                }
                if let attachment = stored.customProduct {
                    let encoder = JSONEncoder()
                    encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
                    let encoded = try encoder.encode(attachment)
                    guard let json = String(data: encoded, encoding: .utf8) else {
                        throw BridgeError.server(
                            "Custom attachment в run не является UTF-8 JSON")
                    }
                    draft.choiceValues["attachment_json"] = json
                    draft.showAdvanced = false
                    draft.selectedUnderlyings = attachment.market.assets.compactMap {
                        asset in
                        guard let secid = asset.secid,
                              let category = asset.category else { return nil }
                        return PricingNewUnderlyingRef(
                            secid: secid,
                            category: category,
                            label: asset.label ?? asset.assetName,
                            currency: asset.currency)
                    }
                }
                let storedSecID: String? = {
                    if case .string(let value)? = stored.params["secid"] { return value }
                    return stored.riskFactorID
                }()
                if let appendKey = product.underlying?.appendTo,
                   case .string(let schedule)? = stored.params[appendKey] {
                    draft.selectedUnderlyings = schedule
                        .replacingOccurrences(of: ";", with: ",")
                        .split(separator: ",")
                        .compactMap { rawToken -> PricingNewUnderlyingRef? in
                            let parts = rawToken.split(separator: ":", omittingEmptySubsequences: false)
                                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                            guard let secid = parts.first, !secid.isEmpty else { return nil }
                            let kind = parts.count > 2 && !parts[2].isEmpty
                                ? parts[2] : "restored"
                            return PricingNewUnderlyingRef(
                                secid: secid,
                                category: marketCategory(for: kind),
                                label: secid,
                                currency: stored.currency)
                        }
                } else if stored.customProduct == nil,
                          let secid = storedSecID,
                          !secid.contains("+") {
                    draft.selectedUnderlyings = [PricingNewUnderlyingRef(
                        secid: secid, category: "restored", label: secid,
                        currency: stored.currency)]
                }
                restored.append(draft)
            }
            guard restored.count == record.request.legs.count, !restored.isEmpty else {
                throw BridgeError.server("Run нельзя восстановить без потери позиций")
            }
            legs = restored
            envID = record.request.envID ?? envID
            runName = record.name
            result = record.result
            lastRunID = record.runID
            pricedSignature = currentSignature
            riskResult = nil
            await loadRiskCapability()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadRiskCapability() async {
        guard let runID = lastRunID else {
            riskCapability = nil
            return
        }
        do {
            riskCapability = try await client.pricingNewRiskCapability(runID)
            riskErrorMessage = nil
        } catch {
            riskCapability = nil
            riskErrorMessage = error.localizedDescription
        }
    }

    func runRisk() async {
        guard let runID = lastRunID, canRunRisk else { return }
        isRisking = true
        riskErrorMessage = nil
        riskResult = nil
        do {
            riskResult = try await client.pricingNewRisk(
                runID,
                request: PricingNewRiskBody(
                    confidence: riskConfidence, window: riskWindow,
                    horizon: riskHorizon, model: riskModel,
                    nSims: riskSims, seed: riskSeed))
        } catch {
            riskErrorMessage = error.localizedDescription
        }
        isRisking = false
    }
}
