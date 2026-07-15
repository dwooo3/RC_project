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

    // MARK: workspace state machines (spec §6)

    /// Technical state of the current calculation.
    var techState: RunTechState = .idle
    /// Structured validation issues from the authoritative server check.
    var issues: [WsValidationIssue] = []
    /// Fingerprint of the last input set the server validated successfully.
    private var validatedFingerprint: String?
    /// Fingerprint of the last captured run.
    private var capturedFingerprint: String?
    /// The immutable run whose result is currently displayed.
    var currentRun: PricingRunRecord?
    /// Immutable history of completed runs in this workspace (newest first).
    var runHistory: [PricingRunRecord] = []
    /// secid restored from a historical run (when no live underlying picked).
    private var restoredSecID: String?

    /// Canonical fingerprint of the current user intent — the staleness key.
    var currentFingerprint: String {
        PricingFingerprint.compute(
            product: productID ?? "", engine: selectedEngine?.id ?? "",
            envID: envID.isEmpty ? nil : envID,
            numeric: numericValues, choice: choiceValues,
            secid: selectedUnderlying?.secid ?? restoredSecID)
    }

    /// Business state, derived from fingerprints — edits move it back to
    /// Draft automatically because the fingerprint changes (spec §6.1).
    var businessState: WorkspaceBusinessState {
        let fp = currentFingerprint
        if capturedFingerprint == fp { return .captured }
        if currentRun?.fingerprint == fp { return .priced }
        if validatedFingerprint == fp { return .validated }
        return .draft
    }

    /// True when a result is on screen but no longer matches the inputs.
    var isStale: Bool {
        result != nil && currentRun != nil && currentRun?.fingerprint != currentFingerprint
    }

    /// Field keys carrying validation errors (for form highlighting).
    var issueKeys: Set<String> { Set(issues.compactMap(\.param)) }

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
        currentRun = nil
        issues = []
        restoredSecID = nil
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
        currentRun = nil
        issues = []
        // desk-risk outputs belong to the previous engine's runs — never show
        // them as if they were produced by the new engine
        ladder = nil
        scenarios = nil
        payoff = nil
        grid2d = nil
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
        restoredSecID = nil                   // a live selection supersedes history
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
            let token = appendKey == "component_secids"
                ? facts.secid
                : "\(facts.secid):1.0"
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
        // Preserve the selected market identity through capture/incremental
        // requests. The bridge resolves FX futures (Si/Eu/CNY) to a pair and
        // equity-like instruments to their own historical factor series.
        if let secid = selectedUnderlying?.secid ?? restoredSecID {
            params["secid"] = BridgeValue(kind: .string(secid))
        }
        return params
    }

    /// Authoritative server validation of the exact request that Run would
    /// send (spec §7.5). Successful validation pins the current fingerprint.
    @discardableResult
    func validate() async -> Bool {
        guard let product = selectedProduct, let engine = selectedEngine else { return false }
        techState = .validating
        errorMessage = nil
        defer { if techState == .validating { techState = .idle } }
        do {
            let v = try await client.wsValidate(product: product.id, engine: engine.id,
                                                params: bridgeParams(),
                                                envID: envID.isEmpty ? nil : envID)
            issues = v.issues
            if v.valid { validatedFingerprint = currentFingerprint }
            return v.valid
        } catch {
            // validation transport failure is an error state, not a pass
            issues = []
            errorMessage = error.localizedDescription
            techState = .failed(error.localizedDescription)
            return false
        }
    }

    func price() async {
        guard let product = selectedProduct, let engine = selectedEngine else { return }
        isPricing = true
        errorMessage = nil
        // Validate → Run (fail closed): issues block the run and map to fields.
        let fingerprint = currentFingerprint
        guard await validate() else {
            if issues.contains(where: \.isError) {
                errorMessage = "Запрос не прошёл валидацию — исправь отмеченные поля"
                techState = .failed("validation")
            }
            isPricing = false
            return
        }
        techState = .running
        do {
            let priced = try await client.wsPrice(product: product.id, engine: engine.id,
                                                  params: bridgeParams(),
                                                  envID: envID.isEmpty ? nil : envID)
            result = priced
            if let first = priced.errors.first { errorMessage = first }
            // record the immutable run (spec §6.1: edits mark it stale later,
            // history never mutates)
            let record = PricingRunRecord(
                timestamp: Date(), fingerprint: fingerprint,
                productID: product.id, productName: product.name,
                engineID: engine.id, engineName: engine.name,
                envID: envID.isEmpty ? nil : envID,
                numericValues: numericValues, choiceValues: choiceValues,
                underlyingSecID: selectedUnderlying?.secid ?? restoredSecID,
                result: priced)
            currentRun = record
            runHistory.insert(record, at: 0)
            if runHistory.count > 20 { runHistory.removeLast(runHistory.count - 20) }
            techState = .idle
        } catch {
            errorMessage = error.localizedDescription
            techState = .failed(error.localizedDescription)
        }
        isPricing = false
    }

    /// Restore a historical run's exact inputs (and show its immutable result —
    /// same fingerprint ⇒ the evidence is current again).
    func restore(_ run: PricingRunRecord) {
        guard run.productID == productID || products.contains(where: { $0.id == run.productID })
        else { return }
        if productID != run.productID {
            productID = run.productID
        }
        engineID = run.engineID
        envID = run.envID ?? ""
        numericValues = run.numericValues
        choiceValues = run.choiceValues
        clearUnderlying()
        restoredSecID = run.underlyingSecID
        result = run.result
        currentRun = run
        issues = []
        errorMessage = nil
        ladder = nil
        scenarios = nil
        payoff = nil
        grid2d = nil
    }

    // MARK: trade capture

    func addToPortfolio() async {
        guard let product = selectedProduct, product.capturable,
              let engine = selectedEngine else { return }
        // Capture attaches to the exact priced run, never to an edited form
        // (spec §7.7 invariant): the current inputs must match the run.
        guard businessState == .priced || businessState == .captured else {
            captureMessage = "Сначала посчитай текущие inputs (Run) — capture относится к конкретному расчёту"
            return
        }
        isCapturing = true
        captureMessage = nil
        do {
            let res = try await client.addToPortfolio(product: product.id,
                                                      engine: engine.id,
                                                      params: bridgeParams(),
                                                      quantity: captureQuantity)
            captureMessage = "✓ \(res.positionID) — в книге \(res.positions) позиций"
            capturedFingerprint = currentFingerprint
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
