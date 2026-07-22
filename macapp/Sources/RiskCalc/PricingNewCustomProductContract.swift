import CryptoKit
import Foundation

// MARK: - Pricing_new ↔ Custom Product Engine attachment contract

/// Origin of a market input carried by an embedded custom-product draft.
/// Manual input is deliberately explicit: a saved Pricing_new run must never
/// make a user override look like snapshot market data.
enum PricingNewCustomInputSource: String, Codable, Sendable, Hashable {
    case marketSnapshot = "market_snapshot"
    case manualOverride = "manual_override"
}

struct PricingNewCustomRateInput: Codable, Sendable, Hashable {
    let value: Double
    let marketValue: Double?
    let source: PricingNewCustomInputSource
    let snapshotID: String?
    let marketDataSource: String?
    let marketDataQuality: String?
    let overridden: Bool
    let overrideReason: String?

    enum CodingKeys: String, CodingKey {
        case value, source, overridden
        case marketValue = "market_value"
        case snapshotID = "snapshot_id"
        case marketDataSource = "market_data_source"
        case marketDataQuality = "market_data_quality"
        case overrideReason = "override_reason"
    }
}

/// One AST asset resolved to either an environment-pinned market entity or an
/// auditable manual input.  Spot is evidence for the normalized-performance
/// process even though the current generic evaluator consumes σ and q.
struct PricingNewCustomAssetInput: Codable, Sendable, Hashable, Identifiable {
    let index: Int
    let assetName: String
    let secid: String?
    let category: String?
    let label: String?
    let currency: String?
    let board: String?
    let spot: Double
    let volatility: Double
    let carryYield: Double
    let marketSpot: Double?
    let marketVolatility: Double?
    let marketCarryYield: Double?
    let source: PricingNewCustomInputSource
    let snapshotID: String?
    let marketDataSource: String?
    let marketDataQuality: String?
    let spotOverridden: Bool
    let volatilityOverridden: Bool
    let carryOverridden: Bool
    let overrideReason: String?

    var id: Int { index }

    enum CodingKeys: String, CodingKey {
        case index, secid, category, label, currency, board, spot, volatility, source
        case assetName = "asset_name"
        case carryYield = "carry_yield"
        case marketSpot = "market_spot"
        case marketVolatility = "market_volatility"
        case marketCarryYield = "market_carry_yield"
        case snapshotID = "snapshot_id"
        case marketDataSource = "market_data_source"
        case marketDataQuality = "market_data_quality"
        case spotOverridden = "spot_overridden"
        case volatilityOverridden = "volatility_overridden"
        case carryOverridden = "carry_overridden"
        case overrideReason = "override_reason"
    }
}

enum PricingNewCustomBusinessDayConvention: String, Codable, Sendable,
                                                  Hashable, CaseIterable {
    case unadjusted = "UNADJUSTED"
    case following = "FOLLOWING"
    case modifiedFollowing = "MODIFIED_FOLLOWING"
    case preceding = "PRECEDING"
    case modifiedPreceding = "MODIFIED_PRECEDING"
}

enum PricingNewCustomPriceBasis: String, Codable, Sendable, Hashable,
                                 CaseIterable {
    case close = "CLOSE"
    case legalClosePrice = "LEGALCLOSEPRICE"
    case weightedAveragePrice = "WAPRICE"
    case settlePrice = "SETTLEPRICE"
}

enum PricingNewCustomCalendarID: String, Codable, Sendable, Hashable {
    case moexStock = "MOEX_STOCK"
}

enum PricingNewCustomDayCountConvention: String, Codable, Sendable, Hashable {
    case act365F = "ACT/365F"
}

enum PricingNewCustomValuationCutoff: String, Codable, Sendable, Hashable {
    case postClosePostEvents = "POST_CLOSE_POST_EVENTS"
}

enum PricingNewCustomFixingSource: String, Codable, Sendable, Hashable {
    case moex = "MOEX"
}

enum PricingNewCustomMissingFixingPolicy: String, Codable, Sendable, Hashable {
    case error
}

struct PricingNewCustomFixingBinding: Codable, Sendable, Hashable {
    let assetName: String
    let secid: String
    let priceBasis: PricingNewCustomPriceBasis
    let board: String?
    let session: String
    let source: PricingNewCustomFixingSource
    let missingFixingPolicy: PricingNewCustomMissingFixingPolicy

    enum CodingKeys: String, CodingKey {
        case secid, board, session, source
        case assetName = "asset_name"
        case priceBasis = "price_basis"
        case missingFixingPolicy = "missing_fixing_policy"
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(assetName, forKey: .assetName)
        try container.encode(secid, forKey: .secid)
        try container.encode(priceBasis, forKey: .priceBasis)
        if let board {
            try container.encode(board, forKey: .board)
        } else {
            try container.encodeNil(forKey: .board)
        }
        try container.encode(session, forKey: .session)
        try container.encode(source, forKey: .source)
        try container.encode(missingFixingPolicy,
                             forKey: .missingFixingPolicy)
    }
}

struct PricingNewCustomContractSchedule: Codable, Sendable, Hashable {
    let schemaVersion: Int
    let effectiveDate: String
    let contractualMaturityDate: String
    let contractualObservationDates: [String]
    let businessDayConvention: PricingNewCustomBusinessDayConvention
    let calendarID: PricingNewCustomCalendarID
    let calendarVersion: Int?
    let dayCountConvention: PricingNewCustomDayCountConvention
    let valuationCutoff: PricingNewCustomValuationCutoff
    let fixingBindings: [PricingNewCustomFixingBinding]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case effectiveDate = "effective_date"
        case contractualMaturityDate = "contractual_maturity_date"
        case contractualObservationDates = "contractual_observation_dates"
        case businessDayConvention = "business_day_convention"
        case calendarID = "calendar_id"
        case calendarVersion = "calendar_version"
        case dayCountConvention = "day_count_convention"
        case valuationCutoff = "valuation_cutoff"
        case fixingBindings = "fixing_bindings"
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(effectiveDate, forKey: .effectiveDate)
        try container.encode(contractualMaturityDate,
                             forKey: .contractualMaturityDate)
        try container.encode(contractualObservationDates,
                             forKey: .contractualObservationDates)
        try container.encode(businessDayConvention,
                             forKey: .businessDayConvention)
        try container.encode(calendarID, forKey: .calendarID)
        if let calendarVersion {
            try container.encode(calendarVersion, forKey: .calendarVersion)
        } else {
            try container.encodeNil(forKey: .calendarVersion)
        }
        try container.encode(dayCountConvention,
                             forKey: .dayCountConvention)
        try container.encode(valuationCutoff, forKey: .valuationCutoff)
        try container.encode(fixingBindings, forKey: .fixingBindings)
    }
}

struct PricingNewCorrelationCalibrationInput: Codable, Sendable, Hashable {
    let mode: String
    let method: String
    let lookback: Int
    let decay: Double
    let minSamples: Int
    let fallbackPolicy: String

    enum CodingKeys: String, CodingKey {
        case mode, method, lookback, decay
        case minSamples = "min_samples"
        case fallbackPolicy = "fallback_policy"
    }
}

struct PricingNewCustomMarketInput: Codable, Sendable, Hashable {
    let rate: PricingNewCustomRateInput
    let assets: [PricingNewCustomAssetInput]
    let correlation: [[Double]]
    var correlationCalibration: PricingNewCorrelationCalibrationInput? = nil

    enum CodingKeys: String, CodingKey {
        case rate, assets, correlation
        case correlationCalibration = "correlation_calibration"
    }
}

struct PricingNewCustomNumericalInput: Codable, Sendable, Hashable {
    let paths: Int
    let steps: Int
    let seed: Int
}

enum PricingNewCustomValuationMode: String, Codable, Sendable, Hashable,
                                      CaseIterable {
    case inception
    case seasoned
}

struct PricingNewCustomValuationStateInput: Codable, Sendable, Hashable {
    let schemaVersion: Int
    let stateContract: String
    let mode: String
    let assetNames: [String]
    let currentSpots: [String: Double]
    let referenceSpots: [String: Double]
    let observationIndex: Int
    let stateValues: [String: Double]
    let runningMin: [String: Double]
    let runningMax: [String: Double]
    let elapsedTime: Double
    let alive: Bool
    let stateAsOf: String
    let stateSourceHash: String?

    enum CodingKeys: String, CodingKey {
        case mode, alive
        case schemaVersion = "schema_version"
        case stateContract = "state_contract"
        case assetNames = "asset_names"
        case currentSpots = "current_spots"
        case referenceSpots = "reference_spots"
        case observationIndex = "observation_index"
        case stateValues = "state_values"
        case runningMin = "running_min"
        case runningMax = "running_max"
        case elapsedTime = "elapsed_time"
        case stateAsOf = "state_as_of"
        case stateSourceHash = "state_source_hash"
    }
}

/// Immutable, version-pinned payload emitted by the embedded builder.  It is
/// intentionally independent of SwiftUI and of PricingNewLegDraft so the
/// backend contract can evolve without coupling the AST editor to a screen.
struct PricingNewCustomProductAttachment: Codable, Sendable, Hashable {
    let schemaVersion: Int
    let productID: String
    let productName: String
    let definitionVersion: Int
    let definitionState: String
    let definitionHash: String
    let engineID: String
    let slots: [String: Double]
    let market: PricingNewCustomMarketInput
    let numerical: PricingNewCustomNumericalInput
    /// Unit convention and lifecycle assumptions are optional only so runs
    /// saved before this contract addition remain decodable. New attachments
    /// always write all three fields explicitly.
    let payoffBasis: String?
    let stateMode: String?
    let stateSource: String?
    var valuationState: PricingNewCustomValuationStateInput? = nil
    /// Optional only for decoding pre-contract-schedule saved runs. Every new
    /// production or seasoned attachment is built fail-closed with this field.
    var contractSchedule: PricingNewCustomContractSchedule? = nil
    let limitations: [String]

    enum CodingKeys: String, CodingKey {
        case slots, market, numerical, limitations
        case schemaVersion = "schema_version"
        case productID = "product_id"
        case productName = "product_name"
        case definitionVersion = "definition_version"
        case definitionState = "definition_state"
        case definitionHash = "definition_hash"
        case engineID = "engine_id"
        case payoffBasis = "payoff_basis"
        case stateMode = "state_mode"
        case stateSource = "state_source"
        case valuationState = "valuation_state"
        case contractSchedule = "contract_schedule"
    }

    var isResearch: Bool { definitionState != "published" }

    /// Request accepted by the existing `/custom/products/{id}/price` route.
    /// Asset identity and snapshot evidence remain in this attachment and in
    /// the Pricing_new run envelope; the evaluator consumes normalized paths.
    var priceRequest: CustomPriceRequestBody {
        let vols = market.assets.map(\.volatility)
        let qs = market.assets.map(\.carryYield)
        var payload = CustomMarketPayload(r: market.rate.value)
        if market.assets.count <= 1 {
            payload.sigma = vols.first ?? 0
            payload.q = qs.first ?? 0
        } else {
            payload.sigmas = vols
            payload.qs = qs
            payload.corr = market.correlation
        }
        return CustomPriceRequestBody(
            slots: slots,
            market: payload,
            n_sims: numerical.paths,
            steps: numerical.steps,
            seed: numerical.seed)
    }

    /// Stable client-side fingerprint useful while composing a run.  The
    /// backend remains authoritative and hashes the complete saved request.
    var contentHash: String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        guard let data = try? encoder.encode(self) else { return "" }
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }
            .joined()
    }
}

struct PricingNewCustomContractIssue: Error, LocalizedError, Sendable,
                                      Hashable, Identifiable {
    let code: String
    let path: String
    let message: String

    var id: String { "\(code)|\(path)|\(message)" }
    var errorDescription: String? { message }
}

struct PricingNewCustomAttachmentDraft: Sendable {
    let detail: CustomProductDetail?
    let slots: [String: Double]
    let rate: PricingNewCustomRateInput
    let assets: [PricingNewCustomAssetInput]
    let correlation: [[Double]]
    let correlationCalibration: PricingNewCorrelationCalibrationInput
    let paths: Double
    let steps: Double
    let seed: Double
    let editorDirty: Bool
    let stateMode: PricingNewCustomValuationMode
    let valuationState: PricingNewCustomValuationStateInput?
    let contractSchedule: PricingNewCustomContractSchedule?
    /// Exact state schema and resolved schedule are taken from the same raw,
    /// version-pinned definition shown by the embedded AST editor. Optional
    /// means unavailable, not an empty schema, and therefore fails closed for
    /// a seasoned attachment.
    let definitionStateDefaults: [String: Double]?
    let resolvedObservationCount: Int?
    let resolvedMaturity: Double?
    /// Valuation date of the snapshot resolved for the selected environment.
    /// The UI never manufactures it from a snapshot identifier.
    let expectedStateAsOf: String?
}

/// Pure fail-closed validator/builder.  Keeping this logic out of the view
/// makes the exact attachment boundary testable without a running bridge.
enum PricingNewCustomProductContract {
    static let maximumUnitPathPoints = 25_000_000.0
    static let maximumGreekWorkPathPoints = 250_000_000.0
    static let estimatedBytesPerPathPoint = 32.0

    struct ResourceEstimate: Sendable, Hashable {
        let unitPathPoints: Double
        let greekWorkPathPoints: Double
        let estimatedPeakBytes: Double

        var estimatedPeakMiB: Double {
            estimatedPeakBytes / 1_048_576.0
        }
    }

    static func resourceEstimate(assetCount: Int, paths: Double,
                                 steps: Double) -> ResourceEstimate? {
        guard assetCount > 0, paths.isFinite, paths > 0,
              steps.isFinite, steps >= 0 else { return nil }
        let unit = Double(assetCount) * paths * (steps + 1.0)
        let count = Double(assetCount)
        let greekRepricings = 3.0 + 4.0 * count
            + 4.0 * (count * (count - 1.0) / 2.0)
        let greekWork = greekRepricings * unit
        guard unit.isFinite, greekWork.isFinite else { return nil }
        return ResourceEstimate(
            unitPathPoints: unit,
            greekWorkPathPoints: greekWork,
            estimatedPeakBytes: unit * estimatedBytesPerPathPoint)
    }

    static func issues(for draft: PricingNewCustomAttachmentDraft)
        -> [PricingNewCustomContractIssue] {
        var issues: [PricingNewCustomContractIssue] = []
        func add(_ code: String, _ path: String, _ message: String) {
            issues.append(.init(code: code, path: path, message: message))
        }

        guard let detail = draft.detail else {
            add("CUSTOM_PRODUCT_REQUIRED", "product_id",
                "Выбери custom product перед добавлением в Pricing_new.")
            return issues
        }

        if draft.editorDirty {
            add("CUSTOM_PRODUCT_UNSAVED_AST", "definition",
                "Payout изменён: сначала сохрани и скомпилируй определение.")
        }
        if detail.state == "draft" || detail.state == "deprecated" {
            add("CUSTOM_PRODUCT_STATE_BLOCKED", "definition_state",
                "Определение в состоянии «\(detail.state)» нельзя оценивать.")
        }
        guard let report = detail.compileReport else {
            add("CUSTOM_PRODUCT_NOT_COMPILED", "compile_report",
                "Нет authoritative compile report для выбранной версии.")
            return issues
        }
        if !report.ok {
            add("CUSTOM_PRODUCT_COMPILE_FAILED", "compile_report",
                "Компилятор отклонил payout graph; исправь ошибки определения.")
        }
        if report.definitionHash != detail.definitionHash {
            add("CUSTOM_PRODUCT_HASH_MISMATCH", "definition_hash",
                "Hash compile report не совпадает с выбранной версией определения.")
        }

        let expectedSlots = Set(detail.definition.slots.keys)
        let suppliedSlots = Set(draft.slots.keys)
        for key in expectedSlots.subtracting(suppliedSlots).sorted() {
            add("CUSTOM_PRODUCT_SLOT_MISSING", "slots.\(key)",
                "Не задан обязательный слот «\(key)».")
        }
        for key in suppliedSlots.subtracting(expectedSlots).sorted() {
            add("CUSTOM_PRODUCT_SLOT_UNKNOWN", "slots.\(key)",
                "Слот «\(key)» отсутствует в version-pinned определении.")
        }
        for (key, value) in draft.slots.sorted(by: { $0.key < $1.key }) {
            guard value.isFinite else {
                add("CUSTOM_PRODUCT_SLOT_NON_FINITE", "slots.\(key)",
                    "Слот «\(key)» должен быть конечным числом.")
                continue
            }
            guard let spec = detail.definition.slots[key] else { continue }
            if let lo = spec.min, value < lo {
                add("CUSTOM_PRODUCT_SLOT_RANGE", "slots.\(key)",
                    "Слот «\(key)» не может быть меньше \(lo).")
            }
            if let hi = spec.max, value > hi {
                add("CUSTOM_PRODUCT_SLOT_RANGE", "slots.\(key)",
                    "Слот «\(key)» не может быть больше \(hi).")
            }
        }

        let assetNames = detail.definition.assetNames
        let expectedEngine = assetNames.count == 1
            ? "custom_mc_gbm" : "custom_mc_multi_gbm"
        if !report.compatibleEngines.contains(expectedEngine) {
            add("CUSTOM_PRODUCT_ENGINE_MISMATCH", "engine_id",
                "Compile report не разрешает ожидаемый движок \(expectedEngine).")
        }
        let byIndex = Dictionary(grouping: draft.assets, by: \.index)
        if draft.assets.count != assetNames.count
            || byIndex.count != assetNames.count
            || !Set(byIndex.keys).isSuperset(of: Set(assetNames.indices)) {
            add("CUSTOM_PRODUCT_ASSET_GRID", "market.assets",
                "Нужно по одному market input на каждый из \(assetNames.count) активов.")
        }
        for asset in draft.assets.sorted(by: { $0.index < $1.index }) {
            let path = "market.assets[\(asset.index)]"
            guard asset.index >= 0, asset.index < assetNames.count else {
                add("CUSTOM_PRODUCT_ASSET_INDEX", path,
                    "Индекс market input не входит в определение продукта.")
                continue
            }
            if asset.assetName != assetNames[asset.index] {
                add("CUSTOM_PRODUCT_ASSET_NAME", path + ".asset_name",
                    "Имя актива не совпадает с version-pinned определением.")
            }
            if !asset.spot.isFinite || asset.spot <= 0 {
                add("CUSTOM_PRODUCT_SPOT_RANGE", path + ".spot",
                    "Spot/price должен быть конечным положительным числом.")
            }
            if !asset.volatility.isFinite || !(0...5).contains(asset.volatility) {
                add("CUSTOM_PRODUCT_VOL_RANGE", path + ".volatility",
                    "Волатильность должна быть в диапазоне 0 … 5.")
            }
            if !asset.carryYield.isFinite || !(-1...1).contains(asset.carryYield) {
                add("CUSTOM_PRODUCT_CARRY_RANGE", path + ".carry_yield",
                    "Carry/dividend yield должен быть в диапазоне −1 … 1.")
            }
            validateEvidence(asset, path: path, add: add)
        }

        if !draft.rate.value.isFinite || !(-1...2).contains(draft.rate.value) {
            add("CUSTOM_PRODUCT_RATE_RANGE", "market.rate.value",
                "Risk-free rate должен быть в диапазоне −1 … 2.")
        }
        validateEvidence(draft.rate, add: add)

        let snapshotIDs = Set(draft.assets.compactMap { asset -> String? in
            guard asset.source == .marketSnapshot else { return nil }
            return nonEmpty(asset.snapshotID)
        } + (draft.rate.source == .marketSnapshot
             ? [nonEmpty(draft.rate.snapshotID)].compactMap { $0 } : []))
        if snapshotIDs.count > 1 {
            add("CUSTOM_PRODUCT_MIXED_SNAPSHOTS", "market",
                "Все market inputs одного расчёта должны относиться к одному snapshot.")
        }

        validateContractSchedule(
            draft, detail: detail, assetNames: assetNames, add: add)
        validateValuationState(
            draft, assetNames: assetNames, add: add)

        if assetNames.count > 1 {
            let calibration = draft.correlationCalibration
            let allowedModes = Set(["auto", "manual", "historical"])
            if !allowedModes.contains(calibration.mode) {
                add("CUSTOM_PRODUCT_CORRELATION_MODE",
                    "market.correlation_calibration.mode",
                    "Correlation mode должен быть auto, historical или manual.")
            }
            if !Set(["pearson", "ewma"]).contains(calibration.method) {
                add("CUSTOM_PRODUCT_CORRELATION_METHOD",
                    "market.correlation_calibration.method",
                    "Correlation method должен быть Pearson или EWMA.")
            }
            if !(2...10_000).contains(calibration.lookback) {
                add("CUSTOM_PRODUCT_CORRELATION_LOOKBACK",
                    "market.correlation_calibration.lookback",
                    "Lookback должен быть от 2 до 10 000 наблюдений.")
            }
            if !calibration.decay.isFinite
                || !(0.0..<1.0).contains(calibration.decay)
                || calibration.decay == 0.0 {
                add("CUSTOM_PRODUCT_CORRELATION_DECAY",
                    "market.correlation_calibration.decay",
                    "EWMA decay должен быть в интервале (0, 1).")
            }
            if calibration.minSamples < 2
                || calibration.minSamples > calibration.lookback {
                add("CUSTOM_PRODUCT_CORRELATION_SAMPLES",
                    "market.correlation_calibration.min_samples",
                    "Min samples должен быть от 2 до lookback.")
            }
            if !Set(["error", "prior"]).contains(calibration.fallbackPolicy) {
                add("CUSTOM_PRODUCT_CORRELATION_FALLBACK",
                    "market.correlation_calibration.fallback_policy",
                    "Fallback должен быть fail-closed или prior matrix.")
            }
            let fullySnapshotBound = draft.assets.allSatisfy {
                $0.source == .marketSnapshot
                    && nonEmpty($0.snapshotID) != nil
                    && nonEmpty($0.secid) != nil
            }
            if calibration.mode == "historical" && !fullySnapshotBound {
                add("CUSTOM_PRODUCT_CORRELATION_HISTORY_REQUIRED",
                    "market.correlation_calibration.mode",
                    "Historical correlation требует snapshot-bound SECID для каждого актива.")
            }
        }

        let gridIssues = CustomMarketInputGrid.validationIssues(
            sigmas: draft.assets.sorted(by: { $0.index < $1.index })
                .map(\.volatility),
            qs: draft.assets.sorted(by: { $0.index < $1.index })
                .map(\.carryYield),
            correlation: draft.correlation,
            assetCount: assetNames.count,
            rate: draft.rate.value,
            nSims: draft.paths,
            steps: draft.steps,
            seed: draft.seed)
        for message in gridIssues {
            add("CUSTOM_PRODUCT_NUMERICAL_INPUT", "market", message)
        }
        if let estimate = resourceEstimate(
            assetCount: assetNames.count, paths: draft.paths,
            steps: draft.steps) {
            if estimate.unitPathPoints > maximumUnitPathPoints {
                add(
                    "CUSTOM_PRODUCT_RESOURCE_PATH_POINTS",
                    "numerical",
                    "MC-сетка требует \(formattedCount(estimate.unitPathPoints)) path-points "
                        + "(≈\(Int(estimate.estimatedPeakMiB.rounded())) MiB), лимит — "
                        + "\(formattedCount(maximumUnitPathPoints)). Уменьши MC paths или time steps.")
            }
            if estimate.greekWorkPathPoints > maximumGreekWorkPathPoints {
                add(
                    "CUSTOM_PRODUCT_RESOURCE_GREEKS",
                    "numerical",
                    "Расчёт CRN component Greeks требует "
                        + "\(formattedCount(estimate.greekWorkPathPoints)) path-point операций, "
                        + "лимит — \(formattedCount(maximumGreekWorkPathPoints)). "
                        + "Уменьши MC paths или time steps.")
            }
        }

        return issues
    }

    static func make(from draft: PricingNewCustomAttachmentDraft) throws
        -> PricingNewCustomProductAttachment {
        let found = issues(for: draft)
        if let first = found.first { throw first }
        guard let detail = draft.detail,
              let paths = Int(exactly: draft.paths),
              let steps = Int(exactly: draft.steps),
              let seed = Int(exactly: draft.seed) else {
            throw PricingNewCustomContractIssue(
                code: "CUSTOM_PRODUCT_INTEGER_INPUT",
                path: "numerical",
                message: "MC controls должны быть целыми числами.")
        }
        let assets = draft.assets.sorted { $0.index < $1.index }
        let correlationCalibration: PricingNewCorrelationCalibrationInput? = {
            guard assets.count > 1 else { return nil }
            let fullySnapshotBound = assets.allSatisfy {
                $0.source == .marketSnapshot
                    && nonEmpty($0.snapshotID) != nil
                    && nonEmpty($0.secid) != nil
            }
            let requested = draft.correlationCalibration
            let resolvedMode = requested.mode == "auto"
                ? (fullySnapshotBound ? "historical" : "manual")
                : requested.mode
            return PricingNewCorrelationCalibrationInput(
                mode: resolvedMode,
                method: requested.method,
                lookback: requested.lookback,
                decay: requested.decay,
                minSamples: requested.minSamples,
                fallbackPolicy: requested.fallbackPolicy)
        }()
        return PricingNewCustomProductAttachment(
            schemaVersion: 1,
            productID: detail.id,
            productName: detail.definition.name,
            definitionVersion: detail.version,
            definitionState: detail.state,
            definitionHash: detail.definitionHash,
            engineID: assets.count == 1
                ? "custom_mc_gbm" : "custom_mc_multi_gbm",
            slots: draft.slots,
            market: PricingNewCustomMarketInput(
                rate: draft.rate,
                assets: assets,
                correlation: draft.correlation,
                correlationCalibration: correlationCalibration),
            numerical: PricingNewCustomNumericalInput(
                paths: paths, steps: steps, seed: seed),
            payoffBasis: "normalized_notional",
            stateMode: draft.stateMode.rawValue,
            stateSource: draft.stateMode == .seasoned
                ? "seasoned_observation" : "explicit_assumption",
            valuationState: draft.stateMode == .seasoned
                ? draft.valuationState : nil,
            contractSchedule: draft.contractSchedule,
            limitations: limitations(
                detail: detail, assets: assets, stateMode: draft.stateMode))
    }

    private static func validateContractSchedule(
        _ draft: PricingNewCustomAttachmentDraft,
        detail: CustomProductDetail,
        assetNames: [String],
        add: (String, String, String) -> Void
    ) {
        let required = detail.state == "published"
            || draft.stateMode == .seasoned
        guard let schedule = draft.contractSchedule else {
            if required {
                add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_REQUIRED",
                    "contract_schedule",
                    "Published/seasoned attachment требует explicit contractual schedule.")
            }
            return
        }

        if schedule.schemaVersion != 1 {
            add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_SCHEMA",
                "contract_schedule.schema_version",
                "Поддерживается contract_schedule schema_version=1.")
        }
        let effective = parseISOCalendarDate(schedule.effectiveDate)
        if effective == nil {
            add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_DATE",
                "contract_schedule.effective_date",
                "Effective date должен быть реальной датой YYYY-MM-DD.")
        }
        let maturity = parseISOCalendarDate(schedule.contractualMaturityDate)
        if maturity == nil {
            add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_DATE",
                "contract_schedule.contractual_maturity_date",
                "Contractual maturity должен быть реальной датой YYYY-MM-DD.")
        }
        if let effective, let maturity, effective >= maturity {
            add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_RANGE",
                "contract_schedule.contractual_maturity_date",
                "Effective date должен быть раньше contractual maturity.")
        }

        let parsedObservations = schedule.contractualObservationDates.map {
            parseISOCalendarDate($0)
        }
        for (index, date) in parsedObservations.enumerated() where date == nil {
            add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_DATE",
                "contract_schedule.contractual_observation_dates[\(index)]",
                "Observation date должен быть реальной датой YYYY-MM-DD.")
        }
        if let expectedCount = draft.resolvedObservationCount {
            if schedule.contractualObservationDates.count != expectedCount {
                add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_COUNT",
                    "contract_schedule.contractual_observation_dates",
                    "Число contractual observations должно быть равно definition schedule: \(expectedCount).")
            }
        } else {
            add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_COUNT_UNAVAILABLE",
                "contract_schedule.contractual_observation_dates",
                "Не удалось разрешить число observations из version-pinned definition.")
        }
        if schedule.contractualObservationDates.last
            != schedule.contractualMaturityDate {
            add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_LAST_OBSERVATION",
                "contract_schedule.contractual_observation_dates",
                "Последняя contractual observation должна совпадать с maturity.")
        }
        if parsedObservations.allSatisfy({ $0 != nil }) {
            let dates = parsedObservations.compactMap { $0 }
            if let effective, let first = dates.first, first <= effective {
                add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_RANGE",
                    "contract_schedule.contractual_observation_dates[0]",
                    "Первая observation должна быть позже effective date.")
            }
            for index in dates.indices.dropFirst()
                where dates[index] <= dates[index - 1] {
                add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_ORDER",
                    "contract_schedule.contractual_observation_dates[\(index)]",
                    "Contractual observation dates должны строго возрастать.")
            }
        }
        if let version = schedule.calendarVersion, version <= 0 {
            add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_CALENDAR_VERSION",
                "contract_schedule.calendar_version",
                "Calendar version должен быть положительным; nil означает server latest.")
        }
        validateScheduleBindings(
            schedule, assets: draft.assets, assetNames: assetNames, add: add)
    }

    private static func validateScheduleBindings(
        _ schedule: PricingNewCustomContractSchedule,
        assets: [PricingNewCustomAssetInput],
        assetNames: [String],
        add: (String, String, String) -> Void
    ) {
        let orderedAssets = assets.sorted { $0.index < $1.index }
        let grouped = Dictionary(grouping: schedule.fixingBindings,
                                 by: \.assetName)
        if schedule.fixingBindings.count != assetNames.count
            || Set(grouped.keys) != Set(assetNames)
            || grouped.values.contains(where: { $0.count != 1 }) {
            add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_BINDINGS",
                "contract_schedule.fixing_bindings",
                "Нужно ровно одно fixing binding на каждый asset definition.")
        }
        if schedule.fixingBindings.map(\.assetName) != assetNames {
            add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_BINDING_ORDER",
                "contract_schedule.fixing_bindings",
                "Fixing bindings должны следовать порядку assets version-pinned definition.")
        }
        for asset in orderedAssets where asset.index >= 0
            && asset.index < assetNames.count {
            let path = "contract_schedule.fixing_bindings[\(asset.index)]"
            guard let binding = grouped[asset.assetName]?.first else { continue }
            guard let secid = nonEmpty(asset.secid) else {
                add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_SECID", path + ".secid",
                    "Contractual fixing требует resolved SECID для \(asset.assetName).")
                continue
            }
            if binding.secid != secid {
                add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_SECID", path + ".secid",
                    "Fixing SECID должен точно совпадать с market asset SECID.")
            }
            if nonEmpty(binding.board) != nonEmpty(asset.board) {
                add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_BOARD", path + ".board",
                    "Fixing board должен точно совпадать с market asset board.")
            }
            if binding.session != binding.session
                .trimmingCharacters(in: .whitespacesAndNewlines) {
                add("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_SESSION", path + ".session",
                    "Fixing session не должен содержать внешние пробелы.")
            }
        }
    }

    private static func validateValuationState(
        _ draft: PricingNewCustomAttachmentDraft,
        assetNames: [String],
        add: (String, String, String) -> Void
    ) {
        guard draft.stateMode == .seasoned else {
            if draft.valuationState != nil {
                add("CUSTOM_PRODUCT_INCEPTION_STATE_CONFLICT", "valuation_state",
                    "Inception attachment не должен содержать seasoned valuation_state.")
            }
            return
        }
        guard let state = draft.valuationState else {
            add("CUSTOM_PRODUCT_SEASONED_STATE_REQUIRED", "valuation_state",
                "Seasoned mode требует полный canonical valuation state.")
            return
        }

        if state.schemaVersion != 1 {
            add("CUSTOM_PRODUCT_STATE_SCHEMA", "valuation_state.schema_version",
                "Поддерживается valuation state schema_version=1.")
        }
        if state.stateContract != "custom_ast_seasoned_state_v1" {
            add("CUSTOM_PRODUCT_STATE_CONTRACT", "valuation_state.state_contract",
                "Seasoned state требует custom_ast_seasoned_state_v1.")
        }
        if state.mode != PricingNewCustomValuationMode.seasoned.rawValue {
            add("CUSTOM_PRODUCT_STATE_MODE", "valuation_state.mode",
                "valuation_state.mode должен быть seasoned.")
        }
        if state.assetNames != assetNames {
            add("CUSTOM_PRODUCT_STATE_ASSETS", "valuation_state.asset_names",
                "Активы valuation state должны точно совпадать с version-pinned definition.")
        }

        let expectedKeys = Set(assetNames)
        let maps: [(String, [String: Double])] = [
            ("current_spots", state.currentSpots),
            ("reference_spots", state.referenceSpots),
            ("running_min", state.runningMin),
            ("running_max", state.runningMax),
        ]
        for (name, values) in maps {
            if Set(values.keys) != expectedKeys {
                add("CUSTOM_PRODUCT_STATE_MAP_KEYS", "valuation_state.\(name)",
                    "\(name) должен содержать ровно один ключ на каждый актив definition.")
            }
            for (asset, value) in values where !value.isFinite || value <= 0 {
                add("CUSTOM_PRODUCT_STATE_VALUE_RANGE",
                    "valuation_state.\(name).\(asset)",
                    "\(name).\(asset) должен быть конечным положительным числом.")
            }
        }

        let marketSpots = Dictionary(
            draft.assets.sorted(by: { $0.index < $1.index }).map {
                ($0.assetName, $0.spot)
            }, uniquingKeysWith: { first, _ in first })
        for asset in assetNames {
            guard let current = state.currentSpots[asset],
                  let market = marketSpots[asset] else { continue }
            if !materiallyEqual(current, market) {
                add("CUSTOM_PRODUCT_STATE_MARKET_MISMATCH",
                    "valuation_state.current_spots.\(asset)",
                    "Current spot state должен совпадать с market spot этого же attachment.")
            }
            guard let reference = state.referenceSpots[asset], reference > 0,
                  let runningMin = state.runningMin[asset],
                  let runningMax = state.runningMax[asset] else { continue }
            let performance = current / reference
            if !performance.isFinite
                || runningMin > performance + 1e-12
                || runningMax < performance - 1e-12
                || runningMin > runningMax + 1e-12 {
                add("CUSTOM_PRODUCT_STATE_EXTREMA",
                    "valuation_state.running_extrema.\(asset)",
                    "Running extrema должны содержать текущую performance current/reference.")
            }
        }

        guard let stateDefaults = draft.definitionStateDefaults else {
            add("CUSTOM_PRODUCT_STATE_SCHEMA_UNAVAILABLE", "valuation_state.state_values",
                "Не удалось прочитать state schema version-pinned definition.")
            validateStateScheduleAndEvidence(draft, state: state, add: add)
            return
        }
        if Set(state.stateValues.keys) != Set(stateDefaults.keys) {
            add("CUSTOM_PRODUCT_STATE_VARIABLES", "valuation_state.state_values",
                "State variables должны точно совпадать с definition.state.")
        }
        for (name, value) in state.stateValues where !value.isFinite {
            add("CUSTOM_PRODUCT_STATE_VALUE_RANGE",
                "valuation_state.state_values.\(name)",
                "State variable \(name) должен быть конечным числом.")
        }
        validateStateScheduleAndEvidence(draft, state: state, add: add)
    }

    private static func validateStateScheduleAndEvidence(
        _ draft: PricingNewCustomAttachmentDraft,
        state: PricingNewCustomValuationStateInput,
        add: (String, String, String) -> Void
    ) {
        guard let schedule = draft.contractSchedule,
              !schedule.contractualObservationDates.isEmpty else {
            add("CUSTOM_PRODUCT_STATE_SCHEDULE_UNAVAILABLE", "valuation_state",
                "Seasoned state требует explicit contractual schedule.")
            validateStateEvidence(draft, state: state, add: add)
            return
        }
        let observations = schedule.contractualObservationDates.count
        if state.observationIndex < 0 || state.observationIndex > observations {
            add("CUSTOM_PRODUCT_STATE_OBSERVATION_INDEX",
                "valuation_state.observation_index",
                "Processed observations должны быть в диапазоне 0 … \(observations).")
        }
        if !state.elapsedTime.isFinite || state.elapsedTime <= 0 {
            add("CUSTOM_PRODUCT_STATE_ELAPSED", "valuation_state.elapsed_time",
                "Elapsed time должен быть конечным положительным ACT/365F значением.")
        }

        // Only UNADJUSTED dates are fully resolvable by the client. For every
        // other BDC the backend owns the versioned MOEX holiday adjustment;
        // the UI deliberately does not manufacture a local trading calendar.
        if schedule.businessDayConvention == .unadjusted {
            if let expected = unadjustedSeasonedPosition(
                    schedule: schedule, stateAsOf: state.stateAsOf) {
                if state.observationIndex != expected.observationIndex {
                    add("CUSTOM_PRODUCT_STATE_SCHEDULE_MISMATCH",
                        "valuation_state.observation_index",
                        "Processed observations не совпадают с explicit UNADJUSTED schedule (ожидается \(expected.observationIndex)).")
                }
                if !materiallyEqual(state.elapsedTime, expected.elapsedTime) {
                    add("CUSTOM_PRODUCT_STATE_ELAPSED_MISMATCH",
                        "valuation_state.elapsed_time",
                        "Elapsed time должен равняться ACT/365F от effective date: \(expected.elapsedTime).")
                }
            } else if let effective = parseISOCalendarDate(
                        schedule.effectiveDate),
                      let maturity = parseISOCalendarDate(
                        schedule.contractualMaturityDate),
                      let asOf = parseISOCalendarDate(state.stateAsOf),
                      !(effective < asOf && asOf <= maturity) {
                add("CUSTOM_PRODUCT_STATE_DATE_RANGE",
                    "valuation_state.state_as_of",
                    "Seasoned state as-of должен быть после effective date и не позже maturity.")
            }
        }
        validateStateEvidence(draft, state: state, add: add)
    }

    /// Client-resolvable lifecycle position. Non-UNADJUSTED schedules return
    /// nil because the backend is authoritative for versioned MOEX holidays.
    static func unadjustedSeasonedPosition(
        schedule: PricingNewCustomContractSchedule,
        stateAsOf: String
    ) -> (observationIndex: Int, elapsedTime: Double)? {
        guard schedule.businessDayConvention == .unadjusted,
              let effective = parseISOCalendarDate(schedule.effectiveDate),
              let maturity = parseISOCalendarDate(
                schedule.contractualMaturityDate),
              let asOf = parseISOCalendarDate(stateAsOf),
              effective < asOf, asOf <= maturity else { return nil }
        let observations = schedule.contractualObservationDates.compactMap {
            parseISOCalendarDate($0)
        }
        guard observations.count
                == schedule.contractualObservationDates.count,
              let days = utcGregorianCalendar
                .dateComponents([.day], from: effective, to: asOf).day,
              days > 0 else { return nil }
        return (
            observationIndex: observations.filter { $0 <= asOf }.count,
            elapsedTime: Double(days) / 365.0)
    }

    private static func validateStateEvidence(
        _ draft: PricingNewCustomAttachmentDraft,
        state: PricingNewCustomValuationStateInput,
        add: (String, String, String) -> Void
    ) {
        if !isISOCalendarDate(state.stateAsOf) {
            add("CUSTOM_PRODUCT_STATE_ASOF", "valuation_state.state_as_of",
                "State as-of должен быть реальной календарной датой YYYY-MM-DD.")
        }
        guard let expectedAsOf = nonEmpty(draft.expectedStateAsOf) else {
            add("CUSTOM_PRODUCT_STATE_ASOF_CONTEXT", "valuation_state.state_as_of",
                "Seasoned state требует valuation date выбранного environment snapshot.")
            validateStateSourceHash(state.stateSourceHash, add: add)
            return
        }
        if state.stateAsOf != expectedAsOf {
            add("CUSTOM_PRODUCT_STATE_ASOF_MISMATCH", "valuation_state.state_as_of",
                "State as-of должен совпадать с valuation date активного snapshot: \(expectedAsOf).")
        }
        validateStateSourceHash(state.stateSourceHash, add: add)
    }

    private static func validateStateSourceHash(
        _ value: String?, add: (String, String, String) -> Void
    ) {
        guard let value, value.count == 64,
              value.unicodeScalars.allSatisfy({ scalar in
                  (scalar.value >= 48 && scalar.value <= 57)
                      || (scalar.value >= 97 && scalar.value <= 102)
              }) else {
            add("CUSTOM_PRODUCT_STATE_SOURCE_HASH",
                "valuation_state.state_source_hash",
                "Seasoned state требует lowercase SHA-256 исходного state/fixing record.")
            return
        }
    }

    private static func validateEvidence(
        _ asset: PricingNewCustomAssetInput,
        path: String,
        add: (String, String, String) -> Void
    ) {
        if asset.source == .marketSnapshot {
            if nonEmpty(asset.secid) == nil || nonEmpty(asset.category) == nil {
                add("CUSTOM_PRODUCT_MARKET_IDENTITY", path,
                    "Snapshot input должен содержать SECID и market category.")
            }
            if nonEmpty(asset.snapshotID) == nil {
                add("CUSTOM_PRODUCT_SNAPSHOT_REQUIRED", path + ".snapshot_id",
                    "Для market input обязателен environment-pinned snapshot ID.")
            }
        } else if nonEmpty(asset.overrideReason) == nil {
            add("CUSTOM_PRODUCT_OVERRIDE_REASON", path + ".override_reason",
                "Для ручного market input укажи причину override.")
        }
        if (asset.spotOverridden || asset.volatilityOverridden
            || asset.carryOverridden), nonEmpty(asset.overrideReason) == nil {
            add("CUSTOM_PRODUCT_OVERRIDE_REASON", path + ".override_reason",
                "Изменение snapshot-параметров требует причины override.")
        }
    }

    private static func validateEvidence(
        _ rate: PricingNewCustomRateInput,
        add: (String, String, String) -> Void
    ) {
        if rate.source == .marketSnapshot, nonEmpty(rate.snapshotID) == nil {
            add("CUSTOM_PRODUCT_SNAPSHOT_REQUIRED", "market.rate.snapshot_id",
                "Для snapshot-ставки обязателен environment-pinned snapshot ID.")
        } else if rate.source == .marketSnapshot,
                  !(rate.marketValue?.isFinite ?? false) {
            add("CUSTOM_PRODUCT_RATE_EVIDENCE", "market.rate.market_value",
                "Snapshot-ставка должна сохранять исходное market value.")
        } else if rate.source == .manualOverride,
                  nonEmpty(rate.overrideReason) == nil {
            add("CUSTOM_PRODUCT_OVERRIDE_REASON", "market.rate.override_reason",
                "Для ручной ставки укажи причину override.")
        }
        if rate.overridden, nonEmpty(rate.overrideReason) == nil {
            add("CUSTOM_PRODUCT_OVERRIDE_REASON", "market.rate.override_reason",
                "Изменение snapshot-ставки требует причины override.")
        }
    }

    private static func limitations(
        detail: CustomProductDetail,
        assets: [PricingNewCustomAssetInput],
        stateMode: PricingNewCustomValuationMode
    )
        -> [String] {
        var values: [String] = []
        if detail.state != "published" {
            values.append("Definition lifecycle state is \(detail.state); result is research-only.")
        }
        if stateMode == .seasoned {
            values.append("This builder captured an explicit seasoned state bound to the selected environment snapshot and source-record hash.")
        } else {
            values.append("This builder captured an explicit inception state; historical risk advances it through a sequential daily path.")
        }
        if assets.contains(where: { $0.category == "bonds" }) {
            values.append("Bond underlyings use a normalized GBM price-index proxy; cashflows, curve dynamics and default are not modelled by the generic custom engine.")
        }
        if assets.contains(where: { $0.source == .manualOverride }) {
            values.append("At least one underlying is driven by explicitly documented manual market input.")
        }
        if assets.contains(where: {
            $0.spotOverridden || $0.volatilityOverridden || $0.carryOverridden
        }) {
            values.append("At least one snapshot market field is manually overridden.")
        }
        return values
    }

    private static func nonEmpty(_ value: String?) -> String? {
        guard let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines),
              !trimmed.isEmpty else { return nil }
        return trimmed
    }

    private static func materiallyEqual(_ lhs: Double, _ rhs: Double) -> Bool {
        guard lhs.isFinite, rhs.isFinite else { return false }
        let scale = max(1.0, max(abs(lhs), abs(rhs)))
        return abs(lhs - rhs) <= 1e-10 * scale
    }

    private static func isISOCalendarDate(_ value: String) -> Bool {
        parseISOCalendarDate(value) != nil
    }

    private static func parseISOCalendarDate(_ value: String) -> Date? {
        guard value.count == 10 else { return nil }
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        guard let parsed = formatter.date(from: value),
              formatter.string(from: parsed) == value else { return nil }
        return parsed
    }

    private static var utcGregorianCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        return calendar
    }

    private static func formattedCount(_ value: Double) -> String {
        guard value.isFinite else { return "non-finite" }
        return String(format: "%.2f млн", value / 1_000_000.0)
    }
}
