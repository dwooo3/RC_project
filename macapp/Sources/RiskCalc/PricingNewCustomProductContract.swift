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
        case index, secid, category, label, currency, spot, volatility, source
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

struct PricingNewCustomMarketInput: Codable, Sendable, Hashable {
    let rate: PricingNewCustomRateInput
    let assets: [PricingNewCustomAssetInput]
    let correlation: [[Double]]
}

struct PricingNewCustomNumericalInput: Codable, Sendable, Hashable {
    let paths: Int
    let steps: Int
    let seed: Int
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
    let paths: Double
    let steps: Double
    let seed: Double
    let editorDirty: Bool
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
        let greekWork = (1.0 + 4.0 * Double(assetCount)) * unit
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
                correlation: draft.correlation),
            numerical: PricingNewCustomNumericalInput(
                paths: paths, steps: steps, seed: seed),
            payoffBasis: "normalized_notional",
            stateMode: "inception",
            stateSource: "explicit_assumption",
            limitations: limitations(detail: detail, assets: assets))
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

    private static func limitations(detail: CustomProductDetail,
                                    assets: [PricingNewCustomAssetInput])
        -> [String] {
        var values: [String] = []
        if detail.state != "published" {
            values.append("Definition lifecycle state is \(detail.state); result is research-only.")
        }
        values.append("Valuation state is an explicit inception assumption: current spots equal reference spots; seasoned path state is unsupported.")
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

    private static func formattedCount(_ value: Double) -> String {
        guard value.isFinite else { return "non-finite" }
        return String(format: "%.2f млн", value / 1_000_000.0)
    }
}
