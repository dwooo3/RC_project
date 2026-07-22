import Foundation

// MARK: - Universal pricing workstation (GET /pricing/catalogue)

struct WsCatalogue: Decodable, Sendable {
    let assetClasses: [WsAssetClass]
    let curves: [WsCurveRef]
    let products: [WsProductModel]
    let conventions: [String]            // A5: глобальные конвенции воркстейшена

    enum CodingKeys: String, CodingKey {
        case curves, products, conventions
        case assetClasses = "asset_classes"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        assetClasses = try c.decode([WsAssetClass].self, forKey: .assetClasses)
        curves = try c.decode([WsCurveRef].self, forKey: .curves)
        products = try c.decode([WsProductModel].self, forKey: .products)
        conventions = try c.decodeIfPresent([String].self, forKey: .conventions) ?? []
    }
}

struct WsAssetClass: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let label: String
}

struct WsCurveRef: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let label: String
}

struct WsProductModel: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let name: String
    let assetClass: String
    let group: String
    let note: String
    let capturable: Bool
    let underlying: WsUnderlyingSpec?
    let engines: [WsEngineModel]

    enum CodingKeys: String, CodingKey {
        case id, name, group, note, capturable, underlying, engines
        case assetClass = "asset_class"
    }
}

struct WsUnderlyingSpec: Decodable, Sendable, Hashable {
    let categories: [String]
    let fill: [String: String]           // param key -> fact key
    let appendTo: String?                // e.g. basket text field

    enum CodingKeys: String, CodingKey {
        case categories, fill
        case appendTo = "append_to"
    }
}

struct WsEngineModel: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let modelID: String
    let name: String
    let governance: Governance
    let eligibility: WsEngineEligibility?
    /// All parameter-dependent publication decisions when one selector can
    /// resolve to different models (currently Carr-Madan: BSM vs Heston).
    /// Optional so catalogues captured before QW1 remain decodable.
    let eligibilityVariants: [WsEngineEligibility]?
    let params: [ParamSpec]

    enum CodingKeys: String, CodingKey {
        case id, name, governance, eligibility, params
        case modelID = "model_id"
        case eligibilityVariants = "eligibility_variants"
    }

    /// Static parameter-aware lookup. Returning nil for an unknown requested
    /// variant is deliberate: callers must obtain an authoritative decision
    /// from /pricing/validate instead of reusing the catalogue default.
    func eligibility(forRuntimeVariant requested: String?) -> WsEngineEligibility? {
        let variants = eligibilityVariants ?? []
        guard let requested, !requested.isEmpty else {
            return eligibility ?? variants.first
        }
        if let exact = variants.first(where: {
            $0.runtimeVariant.caseInsensitiveCompare(requested) == .orderedSame
        }) {
            return exact
        }
        if let eligibility,
           eligibility.runtimeVariant.caseInsensitiveCompare(requested) == .orderedSame {
            return eligibility
        }
        return nil
    }
}

/// QW1 product-qualified model × solver publication decision.
struct WsEngineEligibility: Decodable, Sendable, Hashable {
    let eligibilityID: String
    let eligibilityVersion: String
    let productDefinitionID: String
    let selectorID: String
    let implementationComponentID: String
    let modelDefinitionID: String
    let modelDefinitionVersion: String
    let solverDefinitionID: String
    let solverDefinitionVersion: String
    let pricerComponentID: String?
    let parameterizationComponentID: String?
    let runtimeVariant: String
    let status: String
    let productionAllowed: Bool
    /// Server-qualified execution flag. Optional so an early QW1 catalogue
    /// remains decodable; the computed predicate below still fails closed for
    /// a transition decision without an explicit active approval.
    let effectiveProductionAllowed: Bool?
    let approvalBasis: String
    let approvalRef: String
    let approvalExpiresOn: String
    let approvalActive: Bool?
    let fallbackPolicy: String
    let workflowLayer: String

    enum CodingKeys: String, CodingKey {
        case status
        case eligibilityID = "eligibility_id"
        case eligibilityVersion = "eligibility_version"
        case productDefinitionID = "product_definition_id"
        case selectorID = "selector_id"
        case implementationComponentID = "implementation_component_id"
        case modelDefinitionID = "model_definition_id"
        case modelDefinitionVersion = "model_definition_version"
        case solverDefinitionID = "solver_definition_id"
        case solverDefinitionVersion = "solver_definition_version"
        case pricerComponentID = "pricer_component_id"
        case parameterizationComponentID = "parameterization_component_id"
        case runtimeVariant = "runtime_variant"
        case productionAllowed = "production_allowed"
        case effectiveProductionAllowed = "effective_production_allowed"
        case approvalBasis = "approval_basis"
        case approvalRef = "approval_ref"
        case approvalExpiresOn = "approval_expires_on"
        case approvalActive = "approval_active"
        case fallbackPolicy = "fallback_policy"
        case workflowLayer = "workflow_layer"
    }

    var isResearchOnly: Bool {
        let layer = workflowLayer.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return status == "research-only"
            || layer == "research"
            || layer == "analytics_lab"
    }

    /// The only production predicate UI/actions may consume. The backend value
    /// is authoritative. For additive compatibility, non-transition approvals
    /// may fall back to their declared flag; transition approvals require an
    /// explicit `approval_active=true` and therefore fail closed when absent.
    var isEffectivelyProductionAllowed: Bool {
        guard productionAllowed else { return false }
        if approvalBasis == "legacy_transition" && approvalActive != true {
            return false
        }
        guard approvalActive != false else { return false }
        return effectiveProductionAllowed ?? true
    }

    var isPermanentlyBlocked: Bool {
        status == "deprecated" || status == "out-of-scope"
    }

    /// Mirrors the bridge's fail-closed eligibility policy. Returning a
    /// message (rather than only a Bool) lets the workstation explain which
    /// explicit environment permission is missing.
    func blockReason(in environment: WsEnvironment?) -> String? {
        if isPermanentlyBlocked {
            return "Движок не опубликован для расчётов (\(status))."
        }
        if productionAllowed && !isEffectivelyProductionAllowed {
            return approvalBasis == "legacy_transition"
                ? "Переходное production-разрешение истекло или неактивно."
                : "Production-разрешение неактивно."
        }
        if isResearchOnly && environment?.allowsAnalyticsLab != true {
            return "Research-only движок требует server-owned контур LAB."
        }
        if !productionAllowed && !isResearchOnly && status == "non-production"
            && environment?.allowsNonProduction != true {
            return "Non-production движок требует server-owned контур LAB."
        }
        return nil
    }
}

// MARK: - Pricing environments (GET /environments)

/// Контур оценки (A1): какой снапшот/кривые/движки использует расчёт.
struct WsEnvironment: Decodable, Sendable, Identifiable, Hashable {
    let envID: String
    let name: String
    let purpose: String
    let snapshotID: String?
    var id: String { envID }

    enum CodingKeys: String, CodingKey {
        case name, purpose
        case envID = "env_id"
        case snapshotID = "snapshot_id"
    }

    var allowsAnalyticsLab: Bool {
        envID.uppercased() == "LAB" && purpose.lowercased() == "research"
    }

    var allowsNonProduction: Bool { allowsAnalyticsLab }
}

struct WsEnvironments: Decodable, Sendable {
    let environments: [WsEnvironment]
}

// MARK: - Result (POST /pricing/price)

struct WsMeasure: Decodable, Sendable, Identifiable, Hashable {
    let key: String
    let label: String
    let value: Double
    let component: String?
    let kind: String?
    let convention: String?
    var id: String { key }
}

struct WsPoint: Decodable, Sendable, Hashable {
    let x: Double
    let y: Double
}

struct WsSeries: Decodable, Sendable, Identifiable, Hashable {
    let key: String
    let label: String
    let points: [WsPoint]
    var id: String { key }
}

/// Immutable calculation evidence (spec §10.3): the audit identifiers the
/// backend produces per run. inputs_hash is the server-authoritative hash.
struct WsProvenance: Decodable, Sendable {
    let calculationID: String
    let inputsHash: String
    let snapshotID: String
    let source: String
    let quality: String
    let modelVersion: String
    let modelOwner: String
    let modelValidationDate: String
    let eligibilityID: String?
    let eligibilityVersion: String?
    let modelDefinitionID: String?
    let modelDefinitionVersion: String?
    let solverDefinitionID: String?
    let solverDefinitionVersion: String?
    let implementationComponentID: String?
    let requestedEngineSelector: String?
    let runtimeVariant: String?
    let productionAllowed: Bool
    let declaredProductionAllowed: Bool?
    let approvalExpiresOn: String?
    let valuationTime: String

    enum CodingKeys: String, CodingKey {
        case calculationID = "calculation_id"
        case inputsHash = "inputs_hash"
        case snapshotID = "snapshot_id"
        case source = "market_data_source"
        case quality = "market_data_quality"
        case modelVersion = "model_version"
        case modelOwner = "model_owner"
        case modelValidationDate = "model_validation_date"
        case eligibilityID = "eligibility_id"
        case eligibilityVersion = "eligibility_version"
        case modelDefinitionID = "model_definition_id"
        case modelDefinitionVersion = "model_definition_version"
        case solverDefinitionID = "solver_definition_id"
        case solverDefinitionVersion = "solver_definition_version"
        case implementationComponentID = "implementation_component_id"
        case requestedEngineSelector = "requested_engine_selector"
        case runtimeVariant = "runtime_variant"
        case productionAllowed = "production_allowed"
        case declaredProductionAllowed = "declared_production_allowed"
        case approvalExpiresOn = "approval_expires_on"
        case valuationTime = "valuation_time"
    }
}

struct WsResult: Decodable, Sendable {
    let value: Double?
    let modelID: String
    let modelStatus: String
    let eligibilityID: String?
    let eligibilityVersion: String?
    let modelDefinitionID: String?
    let modelDefinitionVersion: String?
    let solverDefinitionID: String?
    let solverDefinitionVersion: String?
    let pricerComponentID: String?
    let runtimeVariant: String?
    let effectiveProductionAllowed: Bool?
    let greeks: [WsMeasure]
    let measures: [WsMeasure]
    let series: [WsSeries]
    let warnings: [String]
    let errors: [String]
    let limitations: [String]
    let product: String
    let engine: String
    let environment: String?              // контур оценки, если задан env_id
    let provenance: WsProvenance?         // immutable evidence (nil на старом мосте)
    let resolvedParams: [String: JSONValue]?
    let resolvedInputs: JSONValue?
    let marketDataEvidence: JSONValue?

    enum CodingKeys: String, CodingKey {
        case value, greeks, measures, series, warnings, errors, limitations, product, engine
        case environment, provenance
        case resolvedParams = "resolved_params"
        case resolvedInputs = "resolved_inputs"
        case marketDataEvidence = "market_data_evidence"
        case eligibilityID = "eligibility_id"
        case eligibilityVersion = "eligibility_version"
        case modelDefinitionID = "model_definition_id"
        case modelDefinitionVersion = "model_definition_version"
        case solverDefinitionID = "solver_definition_id"
        case solverDefinitionVersion = "solver_definition_version"
        case pricerComponentID = "pricer_component_id"
        case runtimeVariant = "runtime_variant"
        case effectiveProductionAllowed = "effective_production_allowed"
        case modelID = "model_id"
        case modelStatus = "model_status"
    }
}

// MARK: - Authoritative validation (spec §7.5 / §8.3)

/// One structured validation problem, mapped to a form field via `param`.
struct WsValidationIssue: Decodable, Sendable, Identifiable, Hashable {
    let code: String
    let severity: String                  // error | warning
    let message: String
    let param: String?

    var id: String { code + "|" + (param ?? "") + "|" + message }
    var isError: Bool { severity == "error" }
}

struct WsValidation: Decodable, Sendable {
    let valid: Bool
    let issues: [WsValidationIssue]
    let product: String
    let engine: String?
    let eligibility: WsEngineEligibility?
}

// MARK: - Desk risk: ladder + scenarios

struct WsLadderRow: Decodable, Sendable, Hashable {
    let x: Double
    let value: Double?
    let pnl: Double?
    let error: String?
    /// Additive profile payload returned by the same full revaluation.  Each
    /// key is a normalized Greek (`delta`, `gamma`, `vega`, ...), allowing the
    /// workstation to draw Greek curves without a second, inconsistent run.
    let greeks: [String: Double]?
}

struct WsLadder: Decodable, Sendable {
    let product: String
    let engine: String
    let bumpKey: String
    let baseValue: Double?
    let rows: [WsLadderRow]

    enum CodingKeys: String, CodingKey {
        case product, engine, rows
        case bumpKey = "bump_key"
        case baseValue = "base_value"
    }
}

struct WsScenarioRow: Decodable, Sendable, Identifiable, Hashable {
    let scenario: String
    let spotShock: Double
    let volShock: Double
    let rateShock: Double
    let value: Double?
    let pnl: Double?
    let pnlPct: Double?
    let error: String?
    var id: String { scenario }

    enum CodingKeys: String, CodingKey {
        case scenario, value, pnl, error
        case spotShock = "spot_shock"
        case volShock = "vol_shock"
        case rateShock = "rate_shock"
        case pnlPct = "pnl_pct"
    }
}

struct WsScenarios: Decodable, Sendable {
    let product: String
    let engine: String
    let baseValue: Double?
    let rows: [WsScenarioRow]

    enum CodingKeys: String, CodingKey {
        case product, engine, rows
        case baseValue = "base_value"
    }
}

struct WsGridCell: Decodable, Sendable, Hashable {
    let x: Double
    let y: Double
    let value: Double?
    let pnl: Double?
}

struct WsGrid2D: Decodable, Sendable {
    let xKey: String
    let yKey: String
    let baseValue: Double?
    let nx: Int
    let ny: Int
    let cells: [WsGridCell]

    enum CodingKeys: String, CodingKey {
        case nx, ny, cells
        case xKey = "x_key"
        case yKey = "y_key"
        case baseValue = "base_value"
    }
}

struct WsPayoff: Decodable, Sendable {
    let spot: Double
    let spotKey: String
    let baseValue: Double?
    let value: [WsPoint]
    let payoff: [WsPoint]

    enum CodingKeys: String, CodingKey {
        case spot, value, payoff
        case spotKey = "spot_key"
        case baseValue = "base_value"
    }
}

// MARK: - Underlying facts (GET /pricing/underlying/{category}/{secid})

struct UnderlyingFacts: Decodable, Sendable {
    let secid: String
    let category: String
    let label: String
    let currency: String?
    let board: String?
    let facts: [String: Double?]
    let snapshotID: String?
    let marketDataSource: String?
    let marketDataQuality: String?

    enum CodingKeys: String, CodingKey {
        case secid, category, label, currency, board, facts
        case snapshotID = "snapshot_id"
        case marketDataSource = "market_data_source"
        case marketDataQuality = "market_data_quality"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        secid = try c.decode(String.self, forKey: .secid)
        category = try c.decode(String.self, forKey: .category)
        label = try c.decode(String.self, forKey: .label)
        currency = try c.decodeIfPresent(String.self, forKey: .currency)
        board = try c.decodeIfPresent(String.self, forKey: .board)
        facts = try c.decode([String: Double?].self, forKey: .facts)
        snapshotID = try c.decodeIfPresent(String.self, forKey: .snapshotID)
        marketDataSource = try c.decodeIfPresent(String.self, forKey: .marketDataSource)
        marketDataQuality = try c.decodeIfPresent(String.self, forKey: .marketDataQuality)
    }
}

// MARK: - Bridge calls

private struct WsPriceBody: Encodable {
    let product: String
    let engine: String
    let params: [String: BridgeValue]
    var env_id: String? = nil            // nil → мост берёт дефолтный контур
}

private struct WsLadderBody: Encodable {
    let product: String
    let engine: String
    let params: [String: BridgeValue]
    let bump_key: String
    let lo: Double
    let hi: Double
    let steps: Int
    var env_id: String? = nil
}

private struct WsCaptureBody: Encodable {
    let product: String
    let engine: String
    let params: [String: BridgeValue]
    let quantity: Double
}

struct WsIncrementalVaR: Decodable, Sendable {
    let varBase: Double
    let varWithTrade: Double
    let incrementalVaR: Double
    let standaloneVaR: Double
    let diversificationBenefit: Double
    let confidence: Double

    enum CodingKeys: String, CodingKey {
        case confidence
        case varBase = "var_base"
        case varWithTrade = "var_with_trade"
        case incrementalVaR = "incremental_var"
        case standaloneVaR = "standalone_var"
        case diversificationBenefit = "diversification_benefit"
    }
}

struct WsRunApproval: Decodable, Sendable {
    let inputsHash: String
    let calculationID: String
    let approvedBy: String
    let approvedAt: String

    enum CodingKeys: String, CodingKey {
        case inputsHash = "inputs_hash"
        case calculationID = "calculation_id"
        case approvedBy = "approved_by"
        case approvedAt = "approved_at"
    }
}

struct WsCaptureLineage: Decodable, Sendable {
    let calculationID: String
    let inputsHash: String
    let snapshotID: String
    let approvedBy: String?
    let capturedBy: String
    let capturedAt: String

    enum CodingKeys: String, CodingKey {
        case calculationID = "calculation_id"
        case inputsHash = "inputs_hash"
        case snapshotID = "snapshot_id"
        case approvedBy = "approved_by"
        case capturedBy = "captured_by"
        case capturedAt = "captured_at"
    }
}

struct WsAtomicCaptureResult: Decodable, Sendable {
    let positionID: String
    let instrument: String
    let quantity: Double
    let positions: Int
    let lineage: WsCaptureLineage

    enum CodingKeys: String, CodingKey {
        case instrument, quantity, positions, lineage
        case positionID = "position_id"
    }
}

struct WsCaptureResult: Decodable, Sendable {
    let positionID: String
    let instrument: String
    let description: String
    let quantity: Double
    let marketValue: Double?
    let positions: Int

    enum CodingKeys: String, CodingKey {
        case instrument, description, quantity, positions
        case positionID = "position_id"
        case marketValue = "market_value"
    }
}

// MARK: - Phase 3: comparison / convergence / solve-for / simulation lab

struct WsCompareRow: Decodable, Sendable, Identifiable, Hashable {
    let engine: String
    let name: String
    let modelID: String
    let status: String
    let productionAllowed: Bool
    let contextHash: String
    let value: Double?
    let delta: Double?
    let stderr: Double?
    let runtimeMs: Double?
    let inputsHash: String
    let snapshotID: String
    let error: String?
    let diff: Double?
    let diffPct: Double?
    var id: String { engine }

    enum CodingKeys: String, CodingKey {
        case engine, name, status, value, delta, stderr, error, diff
        case modelID = "model_id"
        case productionAllowed = "production_allowed"
        case contextHash = "context_hash"
        case runtimeMs = "runtime_ms"
        case inputsHash = "inputs_hash"
        case snapshotID = "snapshot_id"
        case diffPct = "diff_pct"
    }
}

struct WsCompare: Decodable, Sendable {
    let product: String
    let reference: String
    let referenceValue: Double?
    let contextHash: String
    let rows: [WsCompareRow]

    enum CodingKeys: String, CodingKey {
        case product, reference, rows
        case referenceValue = "reference_value"
        case contextHash = "context_hash"
    }
}

struct WsConvergenceRow: Decodable, Sendable, Hashable {
    let effort: Int
    let value: Double?
    let stderr: Double?
    let runtimeMs: Double?
    let error: String?
    let errorVsRef: Double?

    enum CodingKeys: String, CodingKey {
        case effort, value, stderr, error
        case runtimeMs = "runtime_ms"
        case errorVsRef = "error_vs_ref"
    }
}

struct WsConvergence: Decodable, Sendable {
    let product: String
    let engine: String
    let effortKey: String
    let reference: Double?
    let rows: [WsConvergenceRow]

    enum CodingKeys: String, CodingKey {
        case product, engine, reference, rows
        case effortKey = "effort_key"
    }
}

struct WsSolveResult: Decodable, Sendable {
    let solveKey: String
    let target: Double
    let root: Double
    let achieved: Double
    let residual: Double
    let iterations: Int
    let evaluations: Int
    let engine: String

    enum CodingKeys: String, CodingKey {
        case target, root, achieved, residual, iterations, evaluations, engine
        case solveKey = "solve_key"
    }
}

struct WsSimLabBand: Decodable, Sendable {
    let p: Int
    let values: [Double]
}

struct WsSimLabBin: Decodable, Sendable, Hashable {
    let lo: Double
    let hi: Double
    let count: Int
}

struct WsSimLabTerminal: Decodable, Sendable {
    let bins: [WsSimLabBin]
    let mean: Double
    let std: Double
    let skew: Double
    let kurtosis: Double
    let percentiles: [String: Double]
}

struct WsSimLabPayoff: Decodable, Sendable {
    let opt: String
    let strike: Double
    let mcPrice: Double
    let mcStderr: Double
    let probItm: Double

    enum CodingKeys: String, CodingKey {
        case opt, strike
        case mcPrice = "mc_price"
        case mcStderr = "mc_stderr"
        case probItm = "prob_itm"
    }
}

struct WsSimLab: Decodable, Sendable {
    let nature: String
    let product: String
    let seed: Int
    let nPaths: Int
    let nSteps: Int
    let times: [Double]
    let fan: [WsSimLabBand]
    let samplePaths: [[Double]]
    let terminal: WsSimLabTerminal
    let payoff: WsSimLabPayoff?
    let warnings: [String]

    enum CodingKeys: String, CodingKey {
        case nature, product, seed, times, fan, terminal, payoff, warnings
        case nPaths = "n_paths"
        case nSteps = "n_steps"
        case samplePaths = "sample_paths"
    }
}

// MARK: - Async analytics jobs (spec §18)

struct WsJobProgress: Decodable, Sendable, Equatable {
    let completed: Int
    let total: Int?
    let unit: String?
}

struct WsJobError: Decodable, Sendable, Equatable {
    let code: String
    let message: String
    let retryable: Bool
}

struct WsJobPartial<Item: Decodable & Sendable>: Decodable, Sendable {
    let incomplete: Bool
    let items: [Item]
}

/// Snapshot of one analytics job. Generic over the completed-result payload
/// and the partial unit so ladder/grid/scenarios reuse their sync Decodables.
struct WsJobSnapshot<Payload: Decodable & Sendable,
                     Item: Decodable & Sendable>: Decodable, Sendable {
    let jobID: String
    let kind: String
    let state: String
    let inputsHash: String
    let lastSeq: Int
    let progress: WsJobProgress
    let error: WsJobError?
    let result: Payload?
    let partial: WsJobPartial<Item>?

    var isTerminal: Bool {
        state == "completed" || state == "failed"
            || state == "cancelled" || state == "expired"
    }

    enum CodingKeys: String, CodingKey {
        case kind, state, progress, error, result, partial
        case jobID = "job_id"
        case inputsHash = "inputs_hash"
        case lastSeq = "last_seq"
    }
}

struct WsJobCancelAck: Decodable, Sendable {
    let jobID: String
    let state: String

    enum CodingKeys: String, CodingKey {
        case state
        case jobID = "job_id"
    }
}

private struct WsJobSubmitBody: Encodable {
    let kind: String
    let product: String
    let engine: String
    let params: [String: BridgeValue]
    var env_id: String? = nil
    var bump_key: String? = nil
    var lo: Double? = nil
    var hi: Double? = nil
    var steps: Int = 15
    var x_key: String? = nil
    var y_key: String? = nil
    var x_lo: Double? = nil
    var x_hi: Double? = nil
    var y_lo: Double? = nil
    var y_hi: Double? = nil
    var nx: Int = 9
    var ny: Int = 7
    var reference_engine: String? = nil
}

extension BridgeClient {
    func wsCatalogue() async throws -> WsCatalogue { try await get("pricing/catalogue") }

    func environments() async throws -> [WsEnvironment] {
        try await get("environments", as: WsEnvironments.self).environments
    }

    func wsPrice(product: String, engine: String,
                 params: [String: BridgeValue],
                 envID: String? = nil) async throws -> WsResult {
        let body = try JSONEncoder().encode(
            WsPriceBody(product: product, engine: engine, params: params,
                        env_id: envID))
        return try await post("pricing/price", body: body)
    }

    /// Authoritative fail-closed validation of the exact request that would be
    /// priced (spec §7.5): unknown engine/params, dtype/choice/range issues.
    func wsValidate(product: String, engine: String,
                    params: [String: BridgeValue],
                    envID: String? = nil) async throws -> WsValidation {
        let body = try JSONEncoder().encode(
            WsPriceBody(product: product, engine: engine, params: params,
                        env_id: envID))
        return try await post("pricing/validate", body: body)
    }

    func wsLadder(product: String, engine: String, params: [String: BridgeValue],
                  bumpKey: String, lo: Double, hi: Double, steps: Int,
                  envID: String? = nil) async throws -> WsLadder {
        let body = try JSONEncoder().encode(WsLadderBody(
            product: product, engine: engine, params: params,
            bump_key: bumpKey, lo: lo, hi: hi, steps: steps, env_id: envID))
        return try await post("pricing/ladder", body: body)
    }

    func wsScenarios(product: String, engine: String,
                     params: [String: BridgeValue],
                     envID: String? = nil) async throws -> WsScenarios {
        let body = try JSONEncoder().encode(
            WsPriceBody(product: product, engine: engine, params: params,
                        env_id: envID))
        return try await post("pricing/scenarios", body: body)
    }

    func underlyingFacts(category: String, secid: String) async throws -> UnderlyingFacts {
        try await get("pricing/underlying/\(category)/\(secid)")
    }

    func pricingNewUnderlyingFacts(environment: String, category: String,
                                   secid: String) async throws -> UnderlyingFacts {
        try await get("pricing-new/underlying/\(environment)/\(category)/\(secid)")
    }

    func grid2d(product: String, engine: String, params: [String: BridgeValue],
                xKey: String, yKey: String, xLo: Double, xHi: Double,
                yLo: Double, yHi: Double,
                envID: String? = nil) async throws -> WsGrid2D {
        struct Body: Encodable {
            let product: String
            let engine: String
            let params: [String: BridgeValue]
            let x_key: String
            let y_key: String
            let x_lo: Double
            let x_hi: Double
            let y_lo: Double
            let y_hi: Double
            let env_id: String?
        }
        let body = try JSONEncoder().encode(Body(
            product: product, engine: engine, params: params,
            x_key: xKey, y_key: yKey, x_lo: xLo, x_hi: xHi,
            y_lo: yLo, y_hi: yHi, env_id: envID))
        return try await post("pricing/grid2d", body: body)
    }

    func payoff(product: String, engine: String,
                params: [String: BridgeValue],
                envID: String? = nil) async throws -> WsPayoff {
        let body = try JSONEncoder().encode(
            WsPriceBody(product: product, engine: engine, params: params,
                        env_id: envID))
        return try await post("pricing/payoff", body: body)
    }

    func impliedVol(product: String, params: [String: BridgeValue],
                    marketPrice: Double) async throws -> Double {
        struct Body: Encodable {
            let product: String
            let params: [String: BridgeValue]
            let market_price: Double
        }
        struct Resp: Decodable {
            let implied_vol: Double
        }
        let body = try JSONEncoder().encode(Body(product: product, params: params,
                                                 market_price: marketPrice))
        let resp: Resp = try await post("pricing/implied_vol", body: body)
        return resp.implied_vol
    }

    // ── async analytics jobs ─────────────────────────────
    func submitLadderJob(product: String, engine: String,
                         params: [String: BridgeValue], bumpKey: String,
                         lo: Double, hi: Double, steps: Int,
                         envID: String? = nil)
            async throws -> WsJobSnapshot<WsLadder, WsLadderRow> {
        let body = try JSONEncoder().encode(WsJobSubmitBody(
            kind: "ladder", product: product, engine: engine, params: params,
            env_id: envID, bump_key: bumpKey, lo: lo, hi: hi, steps: steps))
        return try await post("pricing/jobs", body: body)
    }

    func submitGridJob(product: String, engine: String,
                       params: [String: BridgeValue],
                       xKey: String, yKey: String,
                       xLo: Double, xHi: Double, yLo: Double, yHi: Double,
                       envID: String? = nil)
            async throws -> WsJobSnapshot<WsGrid2D, WsGridCell> {
        let body = try JSONEncoder().encode(WsJobSubmitBody(
            kind: "grid2d", product: product, engine: engine, params: params,
            env_id: envID, x_key: xKey, y_key: yKey,
            x_lo: xLo, x_hi: xHi, y_lo: yLo, y_hi: yHi))
        return try await post("pricing/jobs", body: body)
    }

    func submitScenariosJob(product: String, engine: String,
                            params: [String: BridgeValue],
                            envID: String? = nil)
            async throws -> WsJobSnapshot<WsScenarios, WsScenarioRow> {
        let body = try JSONEncoder().encode(WsJobSubmitBody(
            kind: "scenarios", product: product, engine: engine, params: params,
            env_id: envID))
        return try await post("pricing/jobs", body: body)
    }

    func submitPayoffJob(product: String, engine: String,
                         params: [String: BridgeValue],
                         envID: String? = nil)
            async throws -> WsJobSnapshot<WsPayoff, WsLadderRow> {
        let body = try JSONEncoder().encode(WsJobSubmitBody(
            kind: "payoff", product: product, engine: engine, params: params,
            env_id: envID))
        return try await post("pricing/jobs", body: body)
    }

    func submitCompareJob(product: String, referenceEngine: String,
                          params: [String: BridgeValue],
                          envID: String? = nil)
            async throws -> WsJobSnapshot<WsCompare, WsCompareRow> {
        let body = try JSONEncoder().encode(WsJobSubmitBody(
            kind: "compare", product: product, engine: referenceEngine,
            params: params, env_id: envID, reference_engine: referenceEngine))
        return try await post("pricing/jobs", body: body)
    }

    func submitConvergenceJob(product: String, engine: String,
                              params: [String: BridgeValue],
                              envID: String? = nil)
            async throws -> WsJobSnapshot<WsConvergence, WsConvergenceRow> {
        let body = try JSONEncoder().encode(WsJobSubmitBody(
            kind: "convergence", product: product, engine: engine,
            params: params, env_id: envID))
        return try await post("pricing/jobs", body: body)
    }

    func solveFor(product: String, engine: String,
                  params: [String: BridgeValue], solveKey: String,
                  target: Double, lo: Double, hi: Double,
                  envID: String? = nil) async throws -> WsSolveResult {
        struct Body: Encodable {
            let product: String
            let engine: String
            let params: [String: BridgeValue]
            let solve_key: String
            let target: Double
            let lo: Double
            let hi: Double
            let env_id: String?
        }
        let body = try JSONEncoder().encode(Body(
            product: product, engine: engine, params: params,
            solve_key: solveKey, target: target, lo: lo, hi: hi,
            env_id: envID))
        return try await post("pricing/solve", body: body)
    }

    func simLab(product: String, params: [String: BridgeValue],
                nPaths: Int = 2000, seed: Int = 42) async throws -> WsSimLab {
        struct Body: Encodable {
            let product: String
            let params: [String: BridgeValue]
            let n_paths: Int
            let seed: Int
        }
        let body = try JSONEncoder().encode(Body(
            product: product, params: params, n_paths: nPaths, seed: seed))
        return try await post("pricing/simlab", body: body)
    }

    func jobSnapshot<Payload: Decodable & Sendable, Item: Decodable & Sendable>(
            _ jobID: String) async throws -> WsJobSnapshot<Payload, Item> {
        try await get("pricing/jobs/\(jobID)")
    }

    /// Explicit server-side cancel (idempotent) — distinct from cancelling
    /// the Swift polling task (spec §21.3).
    func cancelJob(_ jobID: String) async throws -> WsJobCancelAck {
        try await post("pricing/jobs/\(jobID)/cancel", body: Data("{}".utf8))
    }

    func addToPortfolio(product: String, engine: String, params: [String: BridgeValue],
                        quantity: Double) async throws -> WsCaptureResult {
        let body = try JSONEncoder().encode(WsCaptureBody(
            product: product, engine: engine, params: params, quantity: quantity))
        return try await post("portfolio/add", body: body)
    }

    // ── Phase 5: approval evidence + atomic capture (spec §17, §20) ──
    func approveRun(inputsHash: String, calculationID: String,
                    user: String) async throws -> WsRunApproval {
        struct Body: Encodable {
            let inputs_hash: String
            let calculation_id: String
            let user: String
        }
        let body = try JSONEncoder().encode(Body(
            inputs_hash: inputsHash, calculation_id: calculationID, user: user))
        return try await post("pricing/runs/approve", body: body)
    }

    /// Atomic capture of the EXACT completed run: the server reprices on its
    /// frozen context and 409s when the inputs_hash drifted (spec phase 5).
    func captureAtomic(product: String, engine: String,
                       params: [String: BridgeValue], quantity: Double,
                       expectedInputsHash: String,
                       requestedBy: String) async throws -> WsAtomicCaptureResult {
        struct Body: Encodable {
            let product: String
            let engine: String
            let params: [String: BridgeValue]
            let quantity: Double
            let expected_inputs_hash: String
            let requested_by: String
        }
        let body = try JSONEncoder().encode(Body(
            product: product, engine: engine, params: params,
            quantity: quantity, expected_inputs_hash: expectedInputsHash,
            requested_by: requestedBy))
        return try await post("portfolio/capture", body: body)
    }

    func incrementalVaR(product: String, engine: String, params: [String: BridgeValue],
                        quantity: Double) async throws -> WsIncrementalVaR {
        let body = try JSONEncoder().encode(WsCaptureBody(
            product: product, engine: engine, params: params, quantity: quantity))
        return try await post("marketrisk/incremental", body: body)
    }

    func addMarketToPortfolio(category: String, secid: String,
                              quantity: Double) async throws -> WsCaptureResult {
        try await post("portfolio/add_market?category=\(category)&secid=\(secid)&quantity=\(quantity)",
                       body: Data("{}".utf8))
    }

    func removePosition(_ positionID: String) async throws {
        try await delete("portfolio/position/\(positionID)")
    }

    func resetPortfolio() async throws {
        struct ResetResponse: Decodable { let reset: Bool }
        let _: ResetResponse = try await post("portfolio/reset", body: Data("{}".utf8))
    }
}
