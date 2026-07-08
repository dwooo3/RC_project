import SwiftUI
import Observation

/// State for the universal pricing workstation: asset-class rail -> product ->
/// engine -> generic param form (+ market-data underlying autofill) -> result.
@MainActor
@Observable
final class WorkstationViewModel {
    var catalogue: WsCatalogue?
    var productID: String?
    var engineID: String?

    var numericValues: [String: Double] = [:]
    var choiceValues: [String: String] = [:]
    var result: WsResult?

    // underlying picker
    var underlyingQuery = ""
    var underlyingHits: [SearchHit] = []
    var selectedUnderlying: UnderlyingFacts?
    var isSearching = false
    var autofilledKeys: [String] = []

    var isLoading = false
    var isPricing = false
    var serverDown = false
    var errorMessage: String?

    private let client = BridgeClient()
    private var searchTask: Task<Void, Never>?

    var products: [WsProductModel] { catalogue?.products ?? [] }
    var selectedProduct: WsProductModel? { products.first { $0.id == productID } }
    var selectedEngine: WsEngineModel? {
        selectedProduct?.engines.first { $0.id == engineID } ?? selectedProduct?.engines.first
    }

    /// Rail sections: asset classes in catalogue order, products grouped inside.
    var railSections: [(assetClass: WsAssetClass, products: [WsProductModel])] {
        guard let cat = catalogue else { return [] }
        return cat.assetClasses.compactMap { ac in
            let items = cat.products.filter { $0.assetClass == ac.id }
            return items.isEmpty ? nil : (ac, items)
        }
    }

    func load() async {
        isLoading = true
        serverDown = false
        errorMessage = nil
        do {
            catalogue = try await client.wsCatalogue()
            if productID == nil { productID = products.first?.id }
            resetForSelection()
        } catch {
            serverDown = true
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    func selectProduct(_ id: String) {
        guard id != productID else { return }
        productID = id
        engineID = selectedProduct?.engines.first?.id
        result = nil
        errorMessage = nil
        clearUnderlying()
        resetForSelection()
    }

    func selectEngine(_ id: String) {
        guard id != engineID else { return }
        let saved = (numericValues, choiceValues)
        engineID = id
        result = nil
        resetForSelection()
        // keep shared param values across engine switches (spot, strike, ...)
        for (k, v) in saved.0 where numericValues[k] != nil { numericValues[k] = v }
        for (k, v) in saved.1 where choiceValues[k] != nil { choiceValues[k] = v }
    }

    func resetForSelection() {
        numericValues.removeAll()
        choiceValues.removeAll()
        autofilledKeys = []
        guard let engine = selectedEngine else { return }
        for spec in engine.params {
            switch spec.defaultValue {
            case .number(let d): numericValues[spec.key] = d
            case .string(let s): choiceValues[spec.key] = s
            }
        }
    }

    func numericBinding(_ key: String) -> Binding<Double> {
        Binding(get: { self.numericValues[key] ?? 0 },
                set: { self.numericValues[key] = $0 })
    }

    func choiceBinding(_ key: String) -> Binding<String> {
        Binding(get: { self.choiceValues[key] ?? "" },
                set: { self.choiceValues[key] = $0 })
    }

    // MARK: underlying search + autofill

    func searchUnderlying(_ query: String) {
        searchTask?.cancel()
        underlyingQuery = query
        guard query.count >= 2 else {
            underlyingHits = []
            return
        }
        searchTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(250))
            guard let self, !Task.isCancelled else { return }
            self.isSearching = true
            defer { self.isSearching = false }
            if let hits = try? await self.client.mdSearch(query).results {
                guard !Task.isCancelled else { return }
                let allowed = Set(self.selectedProduct?.underlying?.categories ?? [])
                self.underlyingHits = allowed.isEmpty
                    ? hits
                    : hits.filter { allowed.contains($0.category ?? "") }
            }
        }
    }

    func pickUnderlying(_ hit: SearchHit) async {
        guard let category = hit.category, let spec = selectedProduct?.underlying else { return }
        underlyingHits = []
        underlyingQuery = ""
        do {
            let facts = try await client.underlyingFacts(category: category, secid: hit.secid)
            selectedUnderlying = facts
            applyFacts(facts, spec: spec)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func applyFacts(_ facts: UnderlyingFacts, spec: WsUnderlyingSpec) {
        autofilledKeys = []
        if let appendKey = spec.appendTo {
            // basket-style products: append SECID to a schedule text field
            let current = choiceValues[appendKey] ?? ""
            let token = "\(facts.secid):1.0"
            choiceValues[appendKey] = current.isEmpty ? token : current + ", " + token
            autofilledKeys.append(appendKey)
            return
        }
        for (paramKey, factKey) in spec.fill {
            guard let value = facts.facts[factKey] ?? nil else { continue }
            if numericValues[paramKey] != nil {
                numericValues[paramKey] = value
                autofilledKeys.append(paramKey)
            }
        }
    }

    func clearUnderlying() {
        selectedUnderlying = nil
        underlyingQuery = ""
        underlyingHits = []
        autofilledKeys = []
    }

    // MARK: pricing

    func price() async {
        guard let product = selectedProduct, let engine = selectedEngine else { return }
        isPricing = true
        errorMessage = nil
        var params: [String: BridgeValue] = [:]
        for (key, value) in numericValues { params[key] = BridgeValue(kind: .number(value)) }
        for (key, value) in choiceValues { params[key] = BridgeValue(kind: .string(value)) }
        do {
            let priced = try await client.wsPrice(product: product.id, engine: engine.id,
                                                  params: params)
            result = priced
            if let first = priced.errors.first { errorMessage = first }
        } catch {
            errorMessage = error.localizedDescription
        }
        isPricing = false
    }
}
