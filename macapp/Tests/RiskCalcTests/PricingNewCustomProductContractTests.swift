import XCTest
@testable import RiskCalc

final class PricingNewCustomProductContractTests: XCTestCase {
    func testValidSnapshotDraftBuildsVersionPinnedMultiAssetAttachment() throws {
        let detail = makeDetail()
        let draft = makeDraft(
            detail: detail,
            assets: [
                marketAsset(0, "SBER", snapshot: "snap-42"),
                marketAsset(1, "OFZ", snapshot: "snap-42", category: "bonds"),
            ])

        let attachment = try PricingNewCustomProductContract.make(from: draft)

        XCTAssertEqual(attachment.schemaVersion, 1)
        XCTAssertEqual(attachment.productID, "custom-worst-of")
        XCTAssertEqual(attachment.definitionVersion, 3)
        XCTAssertEqual(attachment.definitionHash, "def-hash")
        XCTAssertEqual(attachment.engineID, "custom_mc_multi_gbm")
        XCTAssertEqual(attachment.payoffBasis, "normalized_notional")
        XCTAssertEqual(attachment.stateMode, "inception")
        XCTAssertEqual(attachment.stateSource, "explicit_assumption")
        XCTAssertEqual(attachment.market.assets.map(\.index), [0, 1])
        XCTAssertTrue(attachment.limitations.contains { $0.contains("Bond underlyings") })
        XCTAssertEqual(attachment.contentHash.count, 64)

        let request = try JSONSerialization.jsonObject(
            with: JSONEncoder().encode(attachment.priceRequest)) as? [String: Any]
        let market = try XCTUnwrap(request?["market"] as? [String: Any])
        XCTAssertEqual((market["sigmas"] as? [Double])?.count, 2)
        XCTAssertEqual((market["corr"] as? [[Double]])?[0][1], 0.35)
        XCTAssertEqual(request?["n_sims"] as? Int, 25_000)

        let encoded = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(attachment))
                as? [String: Any])
        XCTAssertEqual(encoded["payoff_basis"] as? String, "normalized_notional")
        XCTAssertEqual(encoded["state_mode"] as? String, "inception")
        XCTAssertEqual(encoded["state_source"] as? String, "explicit_assumption")
    }

    func testLegacyAttachmentWithoutUnitAndStateFieldsStillDecodes() throws {
        let attachment = try PricingNewCustomProductContract.make(
            from: makeDraft(
                detail: makeDetail(),
                assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                         marketAsset(1, "OFZ", snapshot: "snap-42")]))
        var json = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(attachment))
                as? [String: Any])
        json.removeValue(forKey: "payoff_basis")
        json.removeValue(forKey: "state_mode")
        json.removeValue(forKey: "state_source")

        let restored = try JSONDecoder().decode(
            PricingNewCustomProductAttachment.self,
            from: JSONSerialization.data(withJSONObject: json))

        XCTAssertNil(restored.payoffBasis)
        XCTAssertNil(restored.stateMode)
        XCTAssertNil(restored.stateSource)
        XCTAssertEqual(restored.productID, attachment.productID)
    }

    func testAttachmentHashIsStableAcrossDictionaryInsertionOrder() throws {
        let detail = makeDetail()
        let assets = [
            marketAsset(0, "SBER", snapshot: "snap-42"),
            marketAsset(1, "OFZ", snapshot: "snap-42"),
        ]
        var slotsA: [String: Double] = [:]
        slotsA["coupon"] = 0.08
        slotsA["T"] = 2
        var slotsB: [String: Double] = [:]
        slotsB["T"] = 2
        slotsB["coupon"] = 0.08

        let first = try PricingNewCustomProductContract.make(
            from: makeDraft(detail: detail, assets: assets, slots: slotsA))
        let second = try PricingNewCustomProductContract.make(
            from: makeDraft(detail: detail, assets: assets, slots: slotsB))

        XCTAssertEqual(first.contentHash, second.contentHash)
    }

    func testDirtyEditorAndCompileHashMismatchFailClosed() {
        let detail = makeDetail(reportHash: "stale-hash")
        let draft = makeDraft(
            detail: detail,
            assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                     marketAsset(1, "OFZ", snapshot: "snap-42")],
            editorDirty: true)

        let issues = PricingNewCustomProductContract.issues(for: draft)
        let codes = Set(issues.map(\.code))

        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_UNSAVED_AST"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_HASH_MISMATCH"))
        XCTAssertThrowsError(try PricingNewCustomProductContract.make(from: draft))
    }

    func testManualAndSnapshotOverridesRequireReason() {
        var manual = marketAsset(0, "SBER", snapshot: "snap-42")
        manual = PricingNewCustomAssetInput(
            index: manual.index, assetName: manual.assetName,
            secid: nil, category: nil, label: nil, currency: nil,
            spot: manual.spot, volatility: manual.volatility,
            carryYield: manual.carryYield,
            marketSpot: nil, marketVolatility: nil, marketCarryYield: nil,
            source: .manualOverride, snapshotID: nil,
            marketDataSource: nil, marketDataQuality: nil,
            spotOverridden: false, volatilityOverridden: false,
            carryOverridden: false, overrideReason: nil)
        let overridden = PricingNewCustomAssetInput(
            index: 1, assetName: "OFZ", secid: "SU26238RMFS4",
            category: "bonds", label: "OFZ", currency: "RUB",
            spot: 99, volatility: 0.12, carryYield: 0.15,
            marketSpot: 99, marketVolatility: 0.10, marketCarryYield: 0.15,
            source: .marketSnapshot, snapshotID: "snap-42",
            marketDataSource: "MOEX", marketDataQuality: "OK",
            spotOverridden: false, volatilityOverridden: true,
            carryOverridden: false, overrideReason: nil)
        let draft = makeDraft(detail: makeDetail(), assets: [manual, overridden])

        let reasons = PricingNewCustomProductContract.issues(for: draft)
            .filter { $0.code == "CUSTOM_PRODUCT_OVERRIDE_REASON" }

        XCTAssertEqual(reasons.count, 2)
    }

    func testMixedSnapshotsAndInvalidCorrelationAreRejected() {
        let draft = makeDraft(
            detail: makeDetail(),
            assets: [marketAsset(0, "SBER", snapshot: "snap-A"),
                     marketAsset(1, "OFZ", snapshot: "snap-B")],
            correlation: [[1, 1.5], [1.5, 1]])

        let codes = Set(PricingNewCustomProductContract.issues(for: draft).map(\.code))

        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_MIXED_SNAPSHOTS"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_NUMERICAL_INPUT"))
    }

    func testUnitPathPointBudgetFailsBeforeAttachment() {
        let draft = makeDraft(
            detail: makeDetail(),
            assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                     marketAsset(1, "OFZ", snapshot: "snap-42")],
            paths: 50_000)

        let issues = PricingNewCustomProductContract.issues(for: draft)
        let resource = issues.first {
            $0.code == "CUSTOM_PRODUCT_RESOURCE_PATH_POINTS"
        }

        XCTAssertNotNil(resource)
        XCTAssertTrue(resource?.message.contains("Уменьши MC paths или time steps") == true)
        XCTAssertThrowsError(try PricingNewCustomProductContract.make(from: draft))
    }

    func testGreekWorkBudgetCanFailWhileUnitGridFits() {
        let detail = makeDetail(assetNames: ["SBER", "OFZ", "LKOH"])
        let draft = makeDraft(
            detail: detail,
            assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                     marketAsset(1, "OFZ", snapshot: "snap-42"),
                     marketAsset(2, "LKOH", snapshot: "snap-42")],
            correlation: [[1, 0.2, 0.1], [0.2, 1, 0.15], [0.1, 0.15, 1]],
            paths: 30_000)

        let codes = Set(PricingNewCustomProductContract.issues(for: draft).map(\.code))

        XCTAssertFalse(codes.contains("CUSTOM_PRODUCT_RESOURCE_PATH_POINTS"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_RESOURCE_GREEKS"))
    }

    func testResourceEstimateMirrorsBackendFormula() throws {
        let estimate = try XCTUnwrap(
            PricingNewCustomProductContract.resourceEstimate(
                assetCount: 2, paths: 25_000, steps: 252))

        XCTAssertEqual(estimate.unitPathPoints, 12_650_000)
        XCTAssertEqual(estimate.greekWorkPathPoints, 113_850_000)
        XCTAssertEqual(estimate.estimatedPeakBytes, 404_800_000)
    }

    @MainActor
    func testEnvironmentChangeInvalidatesResolvedEvidenceButKeepsVisibleValues() {
        let vm = PricingNewCustomProductIntegrationViewModel(environmentID: "FO")
        let asset = PricingNewCustomAssetDraft(index: 0, assetName: "SBER")
        asset.secid = "SBER"
        asset.category = "equities"
        asset.snapshotID = "fo-snapshot"
        asset.spot = 315
        asset.marketSpot = 315
        vm.assetDrafts = [asset]
        vm.rateSnapshotID = "fo-snapshot"
        vm.rateMarketValue = 0.15

        vm.setEnvironment("lab")

        XCTAssertEqual(vm.environmentID, "LAB")
        XCTAssertEqual(asset.spot, 315)
        XCTAssertEqual(asset.source, .manualOverride)
        XCTAssertNil(asset.snapshotID)
        XCTAssertNil(vm.rateSnapshotID)
        XCTAssertEqual(vm.rateSource, .manualOverride)
    }

    // MARK: Fixtures

    private func makeDetail(state: String = "published",
                            reportHash: String = "def-hash",
                            assetNames: [String] = ["SBER", "OFZ"])
        -> CustomProductDetail {
        let slots: [String: CustomSlotSpec] = [
            "T": .init(label: "Maturity", defaultValue: 2, min: 0.25, max: 10),
            "coupon": .init(label: "Coupon", defaultValue: 0.08, min: 0, max: 1),
        ]
        let classification = CustomClassification(
            pathDependent: true, earlyRedemption: true,
            underlyings: assetNames.count, dynamics: "correlated_gbm")
        let report = CustomCompileReport(
            ok: true, issues: [], definitionHash: reportHash,
            summary: "Worst-of autocall", classification: classification,
            compatibleEngines: ["custom_mc_multi_gbm"],
            testVectors: [], timeline: [])
        return CustomProductDetail(
            id: "custom-worst-of", version: 3, state: state,
            definition: CustomDefinitionDoc(
                name: "Custom Worst-of", description: "test", author: "qa",
                assets: assetNames, slots: slots),
            definitionHash: "def-hash", author: "qa",
            submittedBy: "qa", approvedBy: "checker",
            compileReport: report, isTemplate: false)
    }

    private func marketAsset(_ index: Int, _ name: String,
                             snapshot: String, category: String = "equities")
        -> PricingNewCustomAssetInput {
        PricingNewCustomAssetInput(
            index: index, assetName: name,
            secid: name == "OFZ" ? "SU26238RMFS4" : name,
            category: category, label: name, currency: "RUB",
            spot: name == "OFZ" ? 99 : 315,
            volatility: name == "OFZ" ? 0.10 : 0.25,
            carryYield: name == "OFZ" ? 0.15 : 0.01,
            marketSpot: name == "OFZ" ? 99 : 315,
            marketVolatility: name == "OFZ" ? 0.10 : 0.25,
            marketCarryYield: name == "OFZ" ? 0.15 : 0.01,
            source: .marketSnapshot, snapshotID: snapshot,
            marketDataSource: "MOEX", marketDataQuality: "OK",
            spotOverridden: false, volatilityOverridden: false,
            carryOverridden: false, overrideReason: nil)
    }

    private func makeDraft(
        detail: CustomProductDetail,
        assets: [PricingNewCustomAssetInput],
        slots: [String: Double] = ["T": 2, "coupon": 0.08],
        correlation: [[Double]] = [[1, 0.35], [0.35, 1]],
        editorDirty: Bool = false,
        paths: Double = 25_000,
        steps: Double = 252
    ) -> PricingNewCustomAttachmentDraft {
        PricingNewCustomAttachmentDraft(
            detail: detail,
            slots: slots,
            rate: PricingNewCustomRateInput(
                value: 0.15, marketValue: 0.15,
                source: .marketSnapshot, snapshotID: "snap-42",
                marketDataSource: "MOEX", marketDataQuality: "OK",
                overridden: false, overrideReason: nil),
            assets: assets, correlation: correlation,
            paths: paths, steps: steps, seed: 42,
            editorDirty: editorDirty)
    }
}
