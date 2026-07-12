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

    // pricing environment (контур оценки, A1)
    var environments: [WsEnvironment] = []
    var envID: String = "FO"

    // underlying picker
    var underlyingQuery = ""
    var underlyingHits: [SearchHit] = []
    var selectedUnderlying: UnderlyingFacts?
    var isSearching = false
    var autofilledKeys: [String] = []

    // trade capture
    var captureQuantity: Double = 1.0
    var captureMessage: String?
    var isCapturing = false
    var incrementalVaR: WsIncrementalVaR?
    var isRunningIncremental = false

    // desk risk
    var ladderKey: String?
    var ladderLo: Double = 0
    var ladderHi: Double = 0
    var ladderSteps: Int = 15
    var ladder: WsLadder?
    var scenarios: WsScenarios?
    var isRunningLadder = false
    var isRunningScenarios = false

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
            // контуры — не критично: без них прайсим в дефолтном FO
            environments = (try? await client.environments()) ?? []
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
        ladder = nil
        scenarios = nil
        ladderKey = nil
        payoff = nil
        grid2d = nil
        errorMessage = nil
        captureMessage = nil
        impliedVolResult = nil
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

    private func bridgeParams() -> [String: BridgeValue] {
        var params: [String: BridgeValue] = [:]
        for (key, value) in numericValues { params[key] = BridgeValue(kind: .number(value)) }
        for (key, value) in choiceValues { params[key] = BridgeValue(kind: .string(value)) }
        return params
    }

    func price() async {
        guard let product = selectedProduct, let engine = selectedEngine else { return }
        isPricing = true
        errorMessage = nil
        do {
            let priced = try await client.wsPrice(product: product.id, engine: engine.id,
                                                  params: bridgeParams(),
                                                  envID: envID.isEmpty ? nil : envID)
            result = priced
            if let first = priced.errors.first { errorMessage = first }
        } catch {
            errorMessage = error.localizedDescription
        }
        isPricing = false
    }

    // MARK: trade capture

    func addToPortfolio() async {
        guard let product = selectedProduct, product.capturable,
              let engine = selectedEngine else { return }
        isCapturing = true
        captureMessage = nil
        do {
            let res = try await client.addToPortfolio(product: product.id,
                                                      engine: engine.id,
                                                      params: bridgeParams(),
                                                      quantity: captureQuantity)
            captureMessage = "✓ \(res.positionID) — в книге \(res.positions) позиций"
        } catch {
            captureMessage = error.localizedDescription
        }
        isCapturing = false
    }

    // payoff diagram
    var payoff: WsPayoff?
    var isLoadingPayoff = false

    // 2D what-if grid (spot × vol)
    var grid2d: WsGrid2D?
    var isLoadingGrid = false

    /// (spot-like, vol-like) numeric keys present on the current engine form.
    var gridKeys: (x: String, y: String)? {
        let keys = Set((selectedEngine?.params ?? []).map(\.key))
        let x = ["S", "S0", "spot"].first { keys.contains($0) }
        let y = ["sigma", "vol"].first { keys.contains($0) }
        if let x, let y { return (x, y) }
        return nil
    }

    func loadGrid2d() async {
        guard let product = selectedProduct, let engine = selectedEngine,
              let keys = gridKeys else { return }
        isLoadingGrid = true
        let s0 = numericValues[keys.x] ?? 100
        let v0 = numericValues[keys.y] ?? 0.2
        grid2d = try? await client.grid2d(
            product: product.id, engine: engine.id, params: bridgeParams(),
            xKey: keys.x, yKey: keys.y,
            xLo: s0 * 0.8, xHi: s0 * 1.2,
            yLo: max(v0 - 0.1, 0.01), yHi: v0 + 0.1)
        isLoadingGrid = false
    }

    func loadPayoff() async {
        guard let product = selectedProduct, let engine = selectedEngine else { return }
        isLoadingPayoff = true
        payoff = try? await client.payoff(product: product.id, engine: engine.id,
                                          params: bridgeParams())
        isLoadingPayoff = false
    }

    /// CSV of the current result (params + measures + greeks) via save panel.
    func exportCSV() {
        guard let r = result, let product = selectedProduct else { return }
        var rows: [[String]] = [["product", product.id],
                                ["engine", r.engine],
                                ["model", r.modelID],
                                ["status", r.modelStatus],
                                ["value", r.value.map { "\($0)" } ?? ""]]
        for (k, v) in numericValues.sorted(by: { $0.key < $1.key }) {
            rows.append(["param:\(k)", "\(v)"])
        }
        for (k, v) in choiceValues.sorted(by: { $0.key < $1.key }) {
            rows.append(["param:\(k)", v])
        }
        for g in r.greeks { rows.append(["greek:\(g.key)", "\(g.value)"]) }
        for m in r.measures { rows.append(["measure:\(m.key)", "\(m.value)"]) }
        CSVExport.save(suggestedName: "\(product.id)_\(r.engine)",
                       header: ["field", "value"], rows: rows)
    }

    // implied vol (european_option / fx_option)
    var impliedPrice: Double = 0
    var impliedVolResult: String?

    var supportsImpliedVol: Bool {
        productID == "european_option" || productID == "fx_option"
    }

    func solveImpliedVol() async {
        guard let product = selectedProduct, impliedPrice > 0 else { return }
        impliedVolResult = nil
        do {
            let iv = try await client.impliedVol(product: product.id,
                                                 params: bridgeParams(),
                                                 marketPrice: impliedPrice)
            numericValues["sigma"] = iv
            impliedVolResult = String(format: "σ = %.4f (подставлена в форму)", iv)
        } catch {
            impliedVolResult = error.localizedDescription
        }
    }

    func runIncrementalVaR() async {
        guard let product = selectedProduct, product.capturable,
              let engine = selectedEngine else { return }
        isRunningIncremental = true
        incrementalVaR = nil
        do {
            incrementalVaR = try await client.incrementalVaR(
                product: product.id, engine: engine.id,
                params: bridgeParams(), quantity: captureQuantity)
        } catch {
            captureMessage = error.localizedDescription
        }
        isRunningIncremental = false
    }

    // MARK: desk risk

    /// Numeric params eligible for a ladder bump.
    var ladderableParams: [ParamSpec] {
        (selectedEngine?.params ?? []).filter {
            ($0.dtype == "float" || $0.dtype == "int") && $0.key != "shift_bps"
        }
    }

    func selectLadderKey(_ key: String) {
        ladderKey = key
        ladder = nil
        let current = numericValues[key] ?? 0
        if current == 0 {
            ladderLo = -1; ladderHi = 1
        } else {
            ladderLo = current * 0.7
            ladderHi = current * 1.3
        }
    }

    func runLadder() async {
        guard let product = selectedProduct, let engine = selectedEngine,
              let key = ladderKey else { return }
        isRunningLadder = true
        errorMessage = nil
        do {
            ladder = try await client.wsLadder(product: product.id, engine: engine.id,
                                               params: bridgeParams(), bumpKey: key,
                                               lo: ladderLo, hi: ladderHi,
                                               steps: ladderSteps)
        } catch {
            errorMessage = error.localizedDescription
        }
        isRunningLadder = false
    }

    func runScenarios() async {
        guard let product = selectedProduct, let engine = selectedEngine else { return }
        isRunningScenarios = true
        errorMessage = nil
        do {
            scenarios = try await client.wsScenarios(product: product.id, engine: engine.id,
                                                     params: bridgeParams())
        } catch {
            errorMessage = error.localizedDescription
        }
        isRunningScenarios = false
    }
}
