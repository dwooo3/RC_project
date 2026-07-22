import Foundation
import Observation

@MainActor
@Observable
final class PricingNewCustomAssetDraft: Identifiable {
    let id = UUID()
    var index: Int
    var assetName: String

    var query = ""
    var hits: [SearchHit] = []
    var isSearching = false

    var secid: String?
    var category: String?
    var label: String?
    var currency: String?
    var board: String?
    var fixingPriceBasis: PricingNewCustomPriceBasis = .close
    var fixingSession = ""
    var spot: Double = 100
    var snapshotID: String?
    var marketDataSource: String?
    var marketDataQuality: String?

    var marketSpot: Double?
    var marketVolatility: Double?
    var marketCarryYield: Double?
    var overrideReason = ""

    init(index: Int, assetName: String) {
        self.index = index
        self.assetName = assetName
    }

    var source: PricingNewCustomInputSource {
        secid == nil ? .manualOverride : .marketSnapshot
    }

    func resetToManual() {
        secid = nil
        category = nil
        label = nil
        currency = nil
        board = nil
        fixingPriceBasis = .close
        fixingSession = ""
        snapshotID = nil
        marketDataSource = nil
        marketDataQuality = nil
        marketSpot = nil
        marketVolatility = nil
        marketCarryYield = nil
        hits = []
        query = ""
        overrideReason = ""
    }
}

/// Explicit contractual dates and MOEX fixing conventions. No observation
/// date is synthesized from maturity: the user owns every contractual date.
@MainActor
@Observable
final class PricingNewCustomContractScheduleDraft {
    var effectiveDate = ""
    var contractualMaturityDate = ""
    var contractualObservationDates: [String] = []
    var businessDayConvention: PricingNewCustomBusinessDayConvention = .unadjusted
    var useLatestCalendarVersion = true
    var calendarVersion = 1
}

/// User-owned lifecycle state for an already-live custom trade. Current spots
/// are deliberately absent: they are read from the resolved market rows so a
/// saved attachment cannot contain two competing current-market levels.
@MainActor
@Observable
final class PricingNewCustomSeasonedStateDraft {
    var referenceSpots: [String: Double] = [:]
    var runningMin: [String: Double] = [:]
    var runningMax: [String: Double] = [:]
    var stateValues: [String: Double] = [:]
    var observationIndex = 0
    var elapsedTime = 0.0
    var alive = true
    var stateAsOf = ""
    var stateSourceHash = ""
}

/// State adapter between the existing generic Custom Product Engine and the
/// dense Pricing_new worksheet.  The original CustomProductsViewModel remains
/// the single owner of AST save/compile/lifecycle/price behavior.
@MainActor
@Observable
final class PricingNewCustomProductIntegrationViewModel {
    let core = CustomProductsViewModel()

    var environmentID: String
    var assetDrafts: [PricingNewCustomAssetDraft] = []
    var rateMarketValue: Double?
    var rateSnapshotID: String?
    var rateMarketDataSource: String?
    var rateMarketDataQuality: String?
    var rateOverrideReason = ""
    var correlationMode = "auto"
    var correlationMethod = "ewma"
    var correlationLookback = 252
    var correlationDecay = 0.97
    var correlationMinSamples = 60
    var correlationFallbackPolicy = "prior"
    var stateMode: PricingNewCustomValuationMode = .inception
    let seasonedState = PricingNewCustomSeasonedStateDraft()
    let contractSchedule = PricingNewCustomContractScheduleDraft()
    var stateSnapshotID: String?
    var stateSnapshotAsOf: String?
    var isLoading = false
    var showPayoutEditor = false

    init(environmentID: String = "FO") {
        self.environmentID = environmentID
    }

    var selectedSummary: CustomProductSummary? {
        core.products.first { $0.id == core.selectedID }
    }

    var rateSource: PricingNewCustomInputSource {
        rateSnapshotID == nil ? .manualOverride : .marketSnapshot
    }

    var rateOverridden: Bool {
        guard let rateMarketValue else { return false }
        return materiallyDifferent(core.marketR, rateMarketValue)
    }

    var contractIssues: [PricingNewCustomContractIssue] {
        PricingNewCustomProductContract.issues(for: attachmentDraft())
    }

    var canAttach: Bool { contractIssues.isEmpty }

    var effectiveCorrelationMode: String {
        if correlationMode != "auto" { return correlationMode }
        let fullySnapshotBound = !assetDrafts.isEmpty && assetDrafts.allSatisfy {
            $0.source == .marketSnapshot
                && $0.snapshotID != nil && $0.secid != nil
        }
        return fullySnapshotBound ? "historical" : "manual"
    }

    var definitionStateDefaults: [String: Double]? {
        guard let editor = core.editor else { return nil }
        var values: [String: Double] = [:]
        for state in editor.states {
            let name = state.name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty, values[name] == nil else { return nil }
            values[name] = state.initial
        }
        return values
    }

    var resolvedObservationCount: Int? {
        guard let editor = core.editor else { return nil }
        let raw = editor.obsSlot.isEmpty
            ? editor.obsCount : core.slotValues[editor.obsSlot]
        guard let raw, raw.isFinite, raw.rounded() == raw,
              raw >= 1, raw <= 10_000 else { return nil }
        return Int(raw)
    }

    var resolvedMaturity: Double? {
        guard let editor = core.editor else { return nil }
        let raw = editor.matSlot.isEmpty
            ? editor.matValue : core.slotValues[editor.matSlot]
        guard let raw, raw.isFinite, raw > 0 else { return nil }
        return raw
    }

    func currentSpot(for assetName: String) -> Double? {
        assetDrafts.first(where: { $0.assetName == assetName })?.spot
    }

    func currentPerformance(for assetName: String) -> Double? {
        guard let current = currentSpot(for: assetName), current.isFinite,
              let reference = seasonedState.referenceSpots[assetName],
              reference.isFinite, reference > 0 else { return nil }
        return current / reference
    }

    func selectStateMode(_ next: PricingNewCustomValuationMode) {
        guard next != stateMode else { return }
        stateMode = next
        if next == .seasoned { resetSeasonedState() }
    }

    var requiresExplicitContractSchedule: Bool {
        core.detail?.state == "published" || stateMode == .seasoned
    }

    func resetContractSchedule() {
        contractSchedule.effectiveDate = ""
        contractSchedule.contractualMaturityDate = ""
        contractSchedule.contractualObservationDates = Array(
            repeating: "", count: resolvedObservationCount ?? 0)
        contractSchedule.businessDayConvention = .unadjusted
        contractSchedule.useLatestCalendarVersion = true
        contractSchedule.calendarVersion = 1
        for asset in assetDrafts {
            asset.fixingPriceBasis = .close
            asset.fixingSession = ""
        }
        if stateMode == .seasoned {
            seasonedState.observationIndex = 0
            seasonedState.elapsedTime = 0
        }
        invalidateContractScheduleEvidence(recomputeState: false)
    }

    func addContractualObservationDate() {
        contractSchedule.contractualObservationDates.append("")
        invalidateContractScheduleEvidence()
    }

    func removeContractualObservationDate(at index: Int) {
        guard contractSchedule.contractualObservationDates.indices.contains(index)
        else { return }
        contractSchedule.contractualObservationDates.remove(at: index)
        invalidateContractScheduleEvidence()
    }

    func setContractualObservationDate(_ value: String, at index: Int) {
        guard contractSchedule.contractualObservationDates.indices.contains(index)
        else { return }
        contractSchedule.contractualObservationDates[index] = value
            .trimmingCharacters(in: .whitespacesAndNewlines)
        invalidateContractScheduleEvidence()
    }

    func invalidateContractScheduleEvidence(recomputeState: Bool = true) {
        seasonedState.stateSourceHash = ""
        if recomputeState { applyClientResolvableScheduleState() }
    }

    func applyClientResolvableScheduleState() {
        guard stateMode == .seasoned,
              let schedule = contractScheduleInput(),
              let resolved = PricingNewCustomProductContract
                .unadjustedSeasonedPosition(
                    schedule: schedule,
                    stateAsOf: seasonedState.stateAsOf) else { return }
        seasonedState.observationIndex = resolved.observationIndex
        seasonedState.elapsedTime = resolved.elapsedTime
    }

    func resetSeasonedState() {
        let names = core.assetNames
        let spots = Dictionary(names.compactMap { name -> (String, Double)? in
            guard let spot = currentSpot(for: name), spot.isFinite, spot > 0
            else { return nil }
            return (name, spot)
        }, uniquingKeysWith: { first, _ in first })
        seasonedState.referenceSpots = spots
        seasonedState.runningMin = Dictionary(
            uniqueKeysWithValues: names.map { ($0, 1.0) })
        seasonedState.runningMax = Dictionary(
            uniqueKeysWithValues: names.map { ($0, 1.0) })
        seasonedState.stateValues = definitionStateDefaults ?? [:]
        seasonedState.observationIndex = 0
        seasonedState.elapsedTime = 0.0
        seasonedState.alive = true
        seasonedState.stateAsOf = stateSnapshotAsOf ?? ""
        seasonedState.stateSourceHash = ""
        applyClientResolvableScheduleState()
    }

    func contractScheduleInput() -> PricingNewCustomContractSchedule? {
        let effective = contractSchedule.effectiveDate
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let maturity = contractSchedule.contractualMaturityDate
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let observations = contractSchedule.contractualObservationDates.map {
            $0.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        let hasExplicitDate = !effective.isEmpty || !maturity.isEmpty
            || observations.contains(where: { !$0.isEmpty })
        guard hasExplicitDate else { return nil }
        let bindings = assetDrafts.sorted { $0.index < $1.index }.map { asset in
            PricingNewCustomFixingBinding(
                assetName: asset.assetName,
                secid: asset.secid?.trimmingCharacters(
                    in: .whitespacesAndNewlines) ?? "",
                priceBasis: asset.fixingPriceBasis,
                board: nonEmpty(asset.board),
                session: asset.fixingSession.trimmingCharacters(
                    in: .whitespacesAndNewlines),
                source: .moex,
                missingFixingPolicy: .error)
        }
        return PricingNewCustomContractSchedule(
            schemaVersion: 1,
            effectiveDate: effective,
            contractualMaturityDate: maturity,
            contractualObservationDates: observations,
            businessDayConvention: contractSchedule.businessDayConvention,
            calendarID: .moexStock,
            calendarVersion: contractSchedule.useLatestCalendarVersion
                ? nil : contractSchedule.calendarVersion,
            dayCountConvention: .act365F,
            valuationCutoff: .postClosePostEvents,
            fixingBindings: bindings)
    }

    func valuationStateInput() -> PricingNewCustomValuationStateInput? {
        guard stateMode == .seasoned else { return nil }
        let names = core.assetNames
        let current = Dictionary(
            names.compactMap { name -> (String, Double)? in
                guard let spot = currentSpot(for: name) else { return nil }
                return (name, spot)
            }, uniquingKeysWith: { first, _ in first })
        let sourceHash = nonEmpty(seasonedState.stateSourceHash)?.lowercased()
        return PricingNewCustomValuationStateInput(
            schemaVersion: 1,
            stateContract: "custom_ast_seasoned_state_v1",
            mode: PricingNewCustomValuationMode.seasoned.rawValue,
            assetNames: names,
            currentSpots: current,
            referenceSpots: seasonedState.referenceSpots,
            observationIndex: seasonedState.observationIndex,
            stateValues: seasonedState.stateValues,
            runningMin: seasonedState.runningMin,
            runningMax: seasonedState.runningMax,
            elapsedTime: seasonedState.elapsedTime,
            alive: seasonedState.alive,
            stateAsOf: seasonedState.stateAsOf,
            stateSourceHash: sourceHash)
    }

    func load() async {
        isLoading = true
        await core.load()
        synchronizeAssetDrafts(reset: true)
        resetContractSchedule()
        await refreshValuationContext()
        isLoading = false
    }

    func select(_ id: String) async {
        await core.select(id)
        clearRateEvidence()
        synchronizeAssetDrafts(reset: true)
        resetLifecycleState()
    }

    func create(from template: CustomProductSummary) async {
        await core.createFromTemplate(template)
        clearRateEvidence()
        synchronizeAssetDrafts(reset: true)
        resetLifecycleState()
    }

    func createAdvanced() async {
        await core.createAdvanced()
        clearRateEvidence()
        synchronizeAssetDrafts(reset: true)
        resetLifecycleState()
        showPayoutEditor = true
    }

    func saveAndCompile() async {
        await core.saveAndCompile()
        synchronizeAssetDrafts(reset: false)
        resetLifecycleState()
    }

    func compile() async {
        guard let id = core.selectedID else { return }
        await core.lifecycle { try await self.core.client.customCompile(id) }
        synchronizeAssetDrafts(reset: false)
        resetLifecycleState()
    }

    func newVersion() async {
        guard let id = core.selectedID else { return }
        await core.lifecycle {
            try await self.core.client.customNewVersion(id, user: self.core.author)
        }
        await core.select(id)
        synchronizeAssetDrafts(reset: false)
        resetLifecycleState()
        showPayoutEditor = true
    }

    func submit() async {
        guard let id = core.selectedID else { return }
        await core.lifecycle {
            try await self.core.client.customSubmit(id, user: self.core.author)
        }
    }

    func approve() async {
        guard let id = core.selectedID else { return }
        await core.lifecycle {
            try await self.core.client.customApprove(id, user: self.core.approver)
        }
    }

    func publish() async {
        guard let id = core.selectedID else { return }
        await core.lifecycle { try await self.core.client.customPublish(id) }
    }

    func verifyPrice() async {
        await core.price()
    }

    /// Environment changes invalidate every resolved identity.  Values remain
    /// visible as manual inputs, but cannot retain stale snapshot provenance.
    func setEnvironment(_ next: String) {
        let normalized = next.trimmingCharacters(in: .whitespacesAndNewlines)
            .uppercased()
        guard !normalized.isEmpty, normalized != environmentID else { return }
        environmentID = normalized
        for draft in assetDrafts { draft.resetToManual() }
        clearRateEvidence()
        stateSnapshotID = nil
        stateSnapshotAsOf = nil
        seasonedState.stateAsOf = ""
        seasonedState.stateSourceHash = ""
    }

    /// Resolve the exact environment snapshot and its authoritative valuation
    /// date through existing typed endpoints. Snapshot identifiers are opaque;
    /// no date is inferred from their spelling.
    func refreshValuationContext() async {
        let requestedEnvironment = environmentID
        do {
            let environments = try await core.client.environments()
            let response = try await core.client.snapshots()
            guard requestedEnvironment == environmentID else { return }
            let pinned = environments.first {
                $0.envID.caseInsensitiveCompare(requestedEnvironment)
                    == .orderedSame
            }?.snapshotID
            let resolvedID = nonEmpty(pinned) ?? response.active
            let resolved = response.snapshots.first { $0.snapshotID == resolvedID }
            stateSnapshotID = resolvedID
            stateSnapshotAsOf = nonEmpty(resolved?.valuationDate)
            if stateMode == .seasoned {
                let nextAsOf = stateSnapshotAsOf ?? ""
                if seasonedState.stateAsOf != nextAsOf {
                    seasonedState.stateAsOf = nextAsOf
                    seasonedState.stateSourceHash = ""
                    applyClientResolvableScheduleState()
                }
            }
        } catch {
            guard requestedEnvironment == environmentID else { return }
            stateSnapshotID = nil
            stateSnapshotAsOf = nil
            if stateMode == .seasoned {
                seasonedState.stateAsOf = ""
                seasonedState.stateSourceHash = ""
            }
        }
    }

    func synchronizeAssetDrafts(reset: Bool) {
        let names = core.assetNames
        let previousNames = assetDrafts.sorted { $0.index < $1.index }
            .map(\.assetName)
        core.synchronizeMarketInputs(assetCount: names.count)
        let old = reset ? [] : assetDrafts
        assetDrafts = names.enumerated().map { index, name in
            if let existing = old.first(where: {
                $0.index == index && $0.assetName == name
            }) {
                existing.index = index
                existing.assetName = name
                return existing
            }
            return PricingNewCustomAssetDraft(index: index, assetName: name)
        }
        if previousNames != names {
            seasonedState.stateSourceHash = ""
        }
    }

    func search(asset: PricingNewCustomAssetDraft) async {
        let query = asset.query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard query.count >= 2 else {
            asset.hits = []
            return
        }
        asset.isSearching = true
        defer { asset.isSearching = false }
        do {
            let allowed = Set(["equities", "indices", "bonds", "futures",
                               "commodities"])
            let results = try await core.client.mdSearch(query).results
            guard asset.query.trimmingCharacters(in: .whitespacesAndNewlines) == query
            else { return }
            asset.hits = results.filter {
                guard let category = $0.category else { return false }
                return allowed.contains(category)
            }
        } catch {
            core.message = error.localizedDescription
        }
    }

    func resolve(_ hit: SearchHit, for asset: PricingNewCustomAssetDraft) async {
        guard let category = hit.category,
              let index = assetDrafts.firstIndex(where: { $0.id == asset.id })
        else { return }
        do {
            let facts = try await core.client.pricingNewUnderlyingFacts(
                environment: environmentID, category: category, secid: hit.secid)
            let spot = facts.facts["spot"] ?? nil
            let volatility = facts.facts["vol"] ?? nil
            let carry: Double?
            if category == "bonds" {
                carry = facts.facts["ytm"] ?? nil
            } else if category == "futures" {
                carry = facts.facts["r_zero"] ?? nil
            } else {
                carry = facts.facts["div_yield"] ?? nil
            }

            asset.secid = facts.secid
            asset.category = facts.category
            asset.label = facts.label
            asset.currency = normalizedCurrency(facts.currency)
            asset.board = nonEmpty(facts.board)
            asset.snapshotID = nonEmpty(facts.snapshotID)
            asset.marketDataSource = nonEmpty(facts.marketDataSource)
            asset.marketDataQuality = nonEmpty(facts.marketDataQuality)
            asset.marketSpot = spot
            asset.marketVolatility = volatility
            asset.marketCarryYield = carry
            if let spot { asset.spot = spot }
            if let volatility { core.marketSigmas[index] = volatility }
            if let carry { core.marketQs[index] = carry }
            asset.overrideReason = ""
            asset.hits = []
            asset.query = ""
            invalidateContractScheduleEvidence()

            if let rate = facts.facts["r_zero"] ?? nil {
                let firstResolution = rateSnapshotID == nil
                rateMarketValue = rate
                rateSnapshotID = nonEmpty(facts.snapshotID)
                rateMarketDataSource = nonEmpty(facts.marketDataSource)
                rateMarketDataQuality = nonEmpty(facts.marketDataQuality)
                if firstResolution {
                    core.marketR = rate
                    rateOverrideReason = ""
                }
            }
        } catch {
            core.message = error.localizedDescription
        }
    }

    func useManualInput(for asset: PricingNewCustomAssetDraft) {
        asset.resetToManual()
        invalidateContractScheduleEvidence()
    }

    func makeAttachment() throws -> PricingNewCustomProductAttachment {
        synchronizeAssetDrafts(reset: false)
        return try PricingNewCustomProductContract.make(from: attachmentDraft())
    }

    func attachmentDraft() -> PricingNewCustomAttachmentDraft {
        let assets = assetDrafts.enumerated().map { index, draft in
            PricingNewCustomAssetInput(
                index: index,
                assetName: draft.assetName,
                secid: draft.secid,
                category: draft.category,
                label: draft.label,
                currency: draft.currency,
                board: draft.board,
                spot: draft.spot,
                volatility: value(core.marketSigmas, at: index,
                                  fallback: core.marketSigma),
                carryYield: value(core.marketQs, at: index,
                                  fallback: core.marketQ),
                marketSpot: draft.marketSpot,
                marketVolatility: draft.marketVolatility,
                marketCarryYield: draft.marketCarryYield,
                source: draft.source,
                snapshotID: draft.snapshotID,
                marketDataSource: draft.marketDataSource,
                marketDataQuality: draft.marketDataQuality,
                spotOverridden: overridden(draft.spot, baseline: draft.marketSpot,
                                           source: draft.source),
                volatilityOverridden: overridden(
                    value(core.marketSigmas, at: index, fallback: core.marketSigma),
                    baseline: draft.marketVolatility, source: draft.source),
                carryOverridden: overridden(
                    value(core.marketQs, at: index, fallback: core.marketQ),
                    baseline: draft.marketCarryYield, source: draft.source),
                overrideReason: nonEmpty(draft.overrideReason))
        }
        return PricingNewCustomAttachmentDraft(
            detail: core.detail,
            slots: core.slotValues,
            rate: PricingNewCustomRateInput(
                value: core.marketR,
                marketValue: rateMarketValue,
                source: rateSource,
                snapshotID: rateSnapshotID,
                marketDataSource: rateMarketDataSource,
                marketDataQuality: rateMarketDataQuality,
                overridden: rateOverridden,
                overrideReason: nonEmpty(rateOverrideReason)),
            assets: assets,
            correlation: core.marketCorrelation,
            correlationCalibration: PricingNewCorrelationCalibrationInput(
                mode: correlationMode,
                method: correlationMethod,
                lookback: correlationLookback,
                decay: correlationDecay,
                minSamples: correlationMinSamples,
                fallbackPolicy: correlationFallbackPolicy),
            paths: core.nSims,
            steps: core.mcSteps,
            seed: core.seed,
            editorDirty: core.isEditorDirty,
            stateMode: stateMode,
            valuationState: valuationStateInput(),
            contractSchedule: contractScheduleInput(),
            definitionStateDefaults: definitionStateDefaults,
            resolvedObservationCount: resolvedObservationCount,
            resolvedMaturity: resolvedMaturity,
            expectedStateAsOf: stateSnapshotAsOf)
    }

    private func resetLifecycleState() {
        stateMode = .inception
        resetContractSchedule()
        resetSeasonedState()
    }

    private func clearRateEvidence() {
        rateMarketValue = nil
        rateSnapshotID = nil
        rateMarketDataSource = nil
        rateMarketDataQuality = nil
        rateOverrideReason = ""
    }

    private func value(_ values: [Double], at index: Int,
                       fallback: Double) -> Double {
        values.indices.contains(index) ? values[index] : fallback
    }

    private func overridden(_ value: Double, baseline: Double?,
                            source: PricingNewCustomInputSource) -> Bool {
        guard source == .marketSnapshot else { return false }
        guard let baseline else { return true }
        return materiallyDifferent(value, baseline)
    }

    private func materiallyDifferent(_ lhs: Double, _ rhs: Double) -> Bool {
        let scale = max(1, max(abs(lhs), abs(rhs)))
        return abs(lhs - rhs) > 1e-10 * scale
    }

    private func normalizedCurrency(_ raw: String?) -> String? {
        guard let code = nonEmpty(raw)?.uppercased() else { return nil }
        return ["SUR", "RUR"].contains(code) ? "RUB" : code
    }

    private func nonEmpty(_ value: String?) -> String? {
        guard let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines),
              !trimmed.isEmpty else { return nil }
        return trimmed
    }
}
