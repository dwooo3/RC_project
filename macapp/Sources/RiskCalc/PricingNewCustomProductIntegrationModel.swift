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

    func load() async {
        isLoading = true
        await core.load()
        synchronizeAssetDrafts(reset: true)
        isLoading = false
    }

    func select(_ id: String) async {
        await core.select(id)
        clearRateEvidence()
        synchronizeAssetDrafts(reset: true)
    }

    func create(from template: CustomProductSummary) async {
        await core.createFromTemplate(template)
        clearRateEvidence()
        synchronizeAssetDrafts(reset: true)
    }

    func createAdvanced() async {
        await core.createAdvanced()
        clearRateEvidence()
        synchronizeAssetDrafts(reset: true)
        showPayoutEditor = true
    }

    func saveAndCompile() async {
        await core.saveAndCompile()
        synchronizeAssetDrafts(reset: false)
    }

    func compile() async {
        guard let id = core.selectedID else { return }
        await core.lifecycle { try await self.core.client.customCompile(id) }
        synchronizeAssetDrafts(reset: false)
    }

    func newVersion() async {
        guard let id = core.selectedID else { return }
        await core.lifecycle {
            try await self.core.client.customNewVersion(id, user: self.core.author)
        }
        await core.select(id)
        synchronizeAssetDrafts(reset: false)
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
    }

    func synchronizeAssetDrafts(reset: Bool) {
        let names = core.assetNames
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
            paths: core.nSims,
            steps: core.mcSteps,
            seed: core.seed,
            editorDirty: core.isEditorDirty)
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
