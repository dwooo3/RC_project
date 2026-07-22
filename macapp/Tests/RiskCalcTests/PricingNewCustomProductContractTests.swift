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
        XCTAssertEqual(attachment.market.correlationCalibration?.mode, "historical")
        XCTAssertEqual(attachment.market.correlationCalibration?.method, "ewma")
        XCTAssertEqual(attachment.market.assets.map(\.index), [0, 1])
        XCTAssertEqual(attachment.market.assets.map(\.board), ["TQBR", "TQCB"])
        XCTAssertEqual(attachment.contractSchedule?.calendarID, .moexStock)
        XCTAssertEqual(attachment.contractSchedule?.businessDayConvention,
                       .unadjusted)
        XCTAssertEqual(attachment.contractSchedule?
            .contractualObservationDates.count, 4)
        XCTAssertEqual(attachment.contractSchedule?.fixingBindings.map(\.secid),
                       ["SBER", "SU26238RMFS4"])
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
        let rawSchedule = try XCTUnwrap(
            encoded["contract_schedule"] as? [String: Any])
        XCTAssertEqual(Set(rawSchedule.keys), Set([
            "schema_version", "effective_date", "contractual_maturity_date",
            "contractual_observation_dates", "business_day_convention",
            "calendar_id", "calendar_version", "day_count_convention",
            "valuation_cutoff", "fixing_bindings",
        ]))
        XCTAssertEqual(rawSchedule["calendar_id"] as? String, "MOEX_STOCK")
        XCTAssertEqual(rawSchedule["day_count_convention"] as? String,
                       "ACT/365F")
        XCTAssertEqual(rawSchedule["valuation_cutoff"] as? String,
                       "POST_CLOSE_POST_EVENTS")
        XCTAssertTrue(rawSchedule["calendar_version"] is NSNull)
        let bindings = try XCTUnwrap(
            rawSchedule["fixing_bindings"] as? [[String: Any]])
        XCTAssertEqual(Set(bindings[0].keys), Set([
            "asset_name", "secid", "price_basis", "board", "session",
            "source", "missing_fixing_policy",
        ]))
        XCTAssertEqual(bindings[0]["asset_name"] as? String, "SBER")
        XCTAssertEqual(bindings[0]["secid"] as? String, "SBER")
        XCTAssertEqual(bindings[0]["price_basis"] as? String, "CLOSE")
        XCTAssertEqual(bindings[0]["board"] as? String, "TQBR")
        XCTAssertEqual(bindings[0]["session"] as? String, "")
        XCTAssertEqual(bindings[0]["source"] as? String, "MOEX")
        XCTAssertEqual(bindings[0]["missing_fixing_policy"] as? String,
                       "error")
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
        json.removeValue(forKey: "contract_schedule")
        if var market = json["market"] as? [String: Any],
           var assets = market["assets"] as? [[String: Any]] {
            for index in assets.indices { assets[index].removeValue(forKey: "board") }
            market["assets"] = assets
            json["market"] = market
        }

        let restored = try JSONDecoder().decode(
            PricingNewCustomProductAttachment.self,
            from: JSONSerialization.data(withJSONObject: json))

        XCTAssertNil(restored.payoffBasis)
        XCTAssertNil(restored.stateMode)
        XCTAssertNil(restored.stateSource)
        XCTAssertNil(restored.contractSchedule)
        XCTAssertTrue(restored.market.assets.allSatisfy { $0.board == nil })
        XCTAssertEqual(restored.productID, attachment.productID)
    }

    func testSeasonedAttachmentRoundTripPreservesStateAndSchedule() throws {
        let original = try PricingNewCustomProductContract.make(
            from: makeDraft(
                detail: makeDetail(),
                assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                         marketAsset(1, "OFZ", snapshot: "snap-42")],
                stateMode: .seasoned,
                valuationState: seasonedState()))

        let restored = try JSONDecoder().decode(
            PricingNewCustomProductAttachment.self,
            from: JSONEncoder().encode(original))

        XCTAssertEqual(restored.valuationState, original.valuationState)
        XCTAssertEqual(restored.contractSchedule, original.contractSchedule)
        XCTAssertEqual(restored.stateMode, "seasoned")
        XCTAssertEqual(restored.stateSource, "seasoned_observation")
    }

    func testPublishedAndSeasonedAttachmentsRequireExplicitSchedule() {
        let assets = [marketAsset(0, "SBER", snapshot: "snap-42"),
                      marketAsset(1, "OFZ", snapshot: "snap-42")]
        let published = makeDraft(
            detail: makeDetail(), assets: assets,
            includeContractSchedule: false)
        let seasonedResearch = makeDraft(
            detail: makeDetail(state: "tested"), assets: assets,
            stateMode: .seasoned, valuationState: seasonedState(),
            includeContractSchedule: false)

        XCTAssertTrue(PricingNewCustomProductContract.issues(for: published)
            .contains { $0.code == "CUSTOM_PRODUCT_CONTRACT_SCHEDULE_REQUIRED" })
        XCTAssertTrue(PricingNewCustomProductContract.issues(for: seasonedResearch)
            .contains { $0.code == "CUSTOM_PRODUCT_CONTRACT_SCHEDULE_REQUIRED" })
    }

    func testContractScheduleRejectsDatesCountAndBindingMismatch() {
        let assets = [marketAsset(0, "SBER", snapshot: "snap-42"),
                      marketAsset(1, "OFZ", snapshot: "snap-42")]
        let badBinding = PricingNewCustomFixingBinding(
            assetName: "SBER", secid: "WRONG",
            priceBasis: .close, board: "TQTF", session: "",
            source: .moex, missingFixingPolicy: .error)
        let malformed = PricingNewCustomContractSchedule(
            schemaVersion: 1,
            effectiveDate: "2027-01-01",
            contractualMaturityDate: "2026-12-31",
            contractualObservationDates: ["2026-06-01", "2026-05-01"],
            businessDayConvention: .unadjusted,
            calendarID: .moexStock,
            calendarVersion: 0,
            dayCountConvention: .act365F,
            valuationCutoff: .postClosePostEvents,
            fixingBindings: [badBinding])
        let draft = makeDraft(
            detail: makeDetail(), assets: assets,
            contractSchedule: malformed)

        let codes = Set(PricingNewCustomProductContract.issues(for: draft)
            .map(\.code))

        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_RANGE"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_COUNT"))
        XCTAssertTrue(codes.contains(
            "CUSTOM_PRODUCT_CONTRACT_SCHEDULE_LAST_OBSERVATION"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_ORDER"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_BINDINGS"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_SECID"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_CONTRACT_SCHEDULE_BOARD"))
        XCTAssertTrue(codes.contains(
            "CUSTOM_PRODUCT_CONTRACT_SCHEDULE_CALENDAR_VERSION"))
        XCTAssertThrowsError(try PricingNewCustomProductContract.make(from: draft))
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
            secid: nil, category: nil, label: nil, currency: nil, board: nil,
            spot: manual.spot, volatility: manual.volatility,
            carryYield: manual.carryYield,
            marketSpot: nil, marketVolatility: nil, marketCarryYield: nil,
            source: .manualOverride, snapshotID: nil,
            marketDataSource: nil, marketDataQuality: nil,
            spotOverridden: false, volatilityOverridden: false,
            carryOverridden: false, overrideReason: nil)
        let overridden = PricingNewCustomAssetInput(
            index: 1, assetName: "OFZ", secid: "SU26238RMFS4",
            category: "bonds", label: "OFZ", currency: "RUB", board: "TQCB",
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

    func testHistoricalCorrelationRequiresSnapshotBoundAssets() {
        let snapshot = marketAsset(0, "SBER", snapshot: "snap-42")
        let original = marketAsset(1, "OFZ", snapshot: "snap-42")
        let manual = PricingNewCustomAssetInput(
            index: original.index, assetName: original.assetName,
            secid: nil, category: nil, label: nil, currency: "RUB", board: nil,
            spot: original.spot, volatility: original.volatility,
            carryYield: original.carryYield,
            marketSpot: nil, marketVolatility: nil, marketCarryYield: nil,
            source: .manualOverride, snapshotID: nil,
            marketDataSource: nil, marketDataQuality: nil,
            spotOverridden: false, volatilityOverridden: false,
            carryOverridden: false, overrideReason: "private proxy")
        let calibration = PricingNewCorrelationCalibrationInput(
            mode: "historical", method: "ewma", lookback: 252,
            decay: 0.97, minSamples: 60, fallbackPolicy: "prior")
        let draft = makeDraft(
            detail: makeDetail(), assets: [snapshot, manual],
            calibration: calibration)

        let codes = Set(PricingNewCustomProductContract.issues(for: draft).map(\.code))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_CORRELATION_HISTORY_REQUIRED"))
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
        XCTAssertEqual(estimate.greekWorkPathPoints, 189_750_000)
        XCTAssertEqual(estimate.estimatedPeakBytes, 404_800_000)
    }

    func testValidSeasonedDraftBuildsExplicitCanonicalAttachment() throws {
        let state = seasonedState()
        let draft = makeDraft(
            detail: makeDetail(),
            assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                     marketAsset(1, "OFZ", snapshot: "snap-42", category: "bonds")],
            stateMode: .seasoned,
            valuationState: state)

        let attachment = try PricingNewCustomProductContract.make(from: draft)

        XCTAssertEqual(attachment.stateMode, "seasoned")
        XCTAssertEqual(attachment.stateSource, "seasoned_observation")
        XCTAssertEqual(attachment.valuationState, state)
        XCTAssertEqual(attachment.valuationState?.stateAsOf, "2026-07-18")
        XCTAssertTrue(attachment.limitations.contains {
            $0.contains("explicit seasoned state")
        })
        let encoded = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(attachment))
                as? [String: Any])
        let rawState = try XCTUnwrap(encoded["valuation_state"] as? [String: Any])
        XCTAssertEqual(rawState["state_contract"] as? String,
                       "custom_ast_seasoned_state_v1")
        XCTAssertEqual(rawState["state_source_hash"] as? String,
                       String(repeating: "a", count: 64))
    }

    func testSeasonedStateRejectsMapMarketExtremaAndVariableMismatch() {
        let malformed = seasonedState(
            currentSpots: ["SBER": 314, "OFZ": 99],
            stateValues: ["unknown": 1],
            runningMin: ["SBER": 1.20])
        let draft = makeDraft(
            detail: makeDetail(),
            assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                     marketAsset(1, "OFZ", snapshot: "snap-42")],
            stateMode: .seasoned,
            valuationState: malformed)

        let codes = Set(PricingNewCustomProductContract.issues(for: draft).map(\.code))

        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_MAP_KEYS"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_MARKET_MISMATCH"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_EXTREMA"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_VARIABLES"))
        XCTAssertThrowsError(try PricingNewCustomProductContract.make(from: draft))
    }

    func testSeasonedStateRejectsAsOfAndSourceEvidenceMismatch() {
        let malformed = seasonedState(
            stateAsOf: "2026-02-30",
            stateSourceHash: String(repeating: "A", count: 64))
        let draft = makeDraft(
            detail: makeDetail(),
            assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                     marketAsset(1, "OFZ", snapshot: "snap-42")],
            stateMode: .seasoned,
            valuationState: malformed)

        let codes = Set(PricingNewCustomProductContract.issues(for: draft).map(\.code))

        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_ASOF"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_ASOF_MISMATCH"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_SOURCE_HASH"))
    }

    func testUnadjustedScheduleValidatesExactSeasonedPositionAndACT365F() {
        let malformed = seasonedState(observationIndex: 1, elapsedTime: 0.75)
        let draft = makeDraft(
            detail: makeDetail(),
            assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                     marketAsset(1, "OFZ", snapshot: "snap-42")],
            stateMode: .seasoned,
            valuationState: malformed)

        let codes = Set(PricingNewCustomProductContract.issues(for: draft)
            .map(\.code))

        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_SCHEDULE_MISMATCH"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_ELAPSED_MISMATCH"))
    }

    func testAdjustedScheduleDefersResolvedPositionToBackend() {
        let assets = [marketAsset(0, "SBER", snapshot: "snap-42"),
                      marketAsset(1, "OFZ", snapshot: "snap-42")]
        let adjusted = makeContractSchedule(
            assets: assets, businessDayConvention: .modifiedFollowing)
        let state = seasonedState(observationIndex: 0, elapsedTime: 0.123)
        let draft = makeDraft(
            detail: makeDetail(), assets: assets,
            stateMode: .seasoned, valuationState: state,
            contractSchedule: adjusted)

        let codes = Set(PricingNewCustomProductContract.issues(for: draft)
            .map(\.code))

        XCTAssertFalse(codes.contains("CUSTOM_PRODUCT_STATE_SCHEDULE_MISMATCH"))
        XCTAssertFalse(codes.contains("CUSTOM_PRODUCT_STATE_ELAPSED_MISMATCH"))
    }

    func testSeasonedStateFailsClosedWithoutSnapshotOrDefinitionContext() {
        let draft = makeDraft(
            detail: makeDetail(),
            assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                     marketAsset(1, "OFZ", snapshot: "snap-42")],
            stateMode: .seasoned,
            valuationState: seasonedState(),
            definitionStateDefaults: nil,
            resolvedObservationCount: nil,
            resolvedMaturity: nil,
            expectedStateAsOf: nil)

        let codes = Set(PricingNewCustomProductContract.issues(for: draft).map(\.code))

        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_SCHEMA_UNAVAILABLE"))
        XCTAssertTrue(codes.contains(
            "CUSTOM_PRODUCT_CONTRACT_SCHEDULE_COUNT_UNAVAILABLE"))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_STATE_ASOF_CONTEXT"))
    }

    func testInceptionRejectsInjectedSeasonedPayload() {
        let draft = makeDraft(
            detail: makeDetail(),
            assets: [marketAsset(0, "SBER", snapshot: "snap-42"),
                     marketAsset(1, "OFZ", snapshot: "snap-42")],
            valuationState: seasonedState())

        let codes = Set(PricingNewCustomProductContract.issues(for: draft).map(\.code))
        XCTAssertTrue(codes.contains("CUSTOM_PRODUCT_INCEPTION_STATE_CONFLICT"))
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

    @MainActor
    func testEnvironmentChangeInvalidatesSeasonedAsOfAndSourceHash() {
        let vm = PricingNewCustomProductIntegrationViewModel(environmentID: "FO")
        vm.stateSnapshotID = "snap-42"
        vm.stateSnapshotAsOf = "2026-07-18"
        vm.selectStateMode(.seasoned)
        vm.seasonedState.stateSourceHash = String(repeating: "a", count: 64)

        vm.setEnvironment("LAB")

        XCTAssertEqual(vm.stateMode, .seasoned)
        XCTAssertNil(vm.stateSnapshotID)
        XCTAssertNil(vm.stateSnapshotAsOf)
        XCTAssertEqual(vm.seasonedState.stateAsOf, "")
        XCTAssertEqual(vm.seasonedState.stateSourceHash, "")
    }

    @MainActor
    func testScheduleDraftBuildsTypedMOEXBindingFromResolvedAsset() throws {
        let vm = PricingNewCustomProductIntegrationViewModel(environmentID: "FO")
        let asset = PricingNewCustomAssetDraft(index: 0, assetName: "SBER")
        asset.secid = "SBER"
        asset.board = "TQBR"
        asset.fixingPriceBasis = .legalClosePrice
        asset.fixingSession = "main"
        vm.assetDrafts = [asset]
        vm.contractSchedule.effectiveDate = "2026-07-20"
        vm.contractSchedule.contractualMaturityDate = "2026-08-03"
        vm.contractSchedule.contractualObservationDates = ["2026-08-03"]
        vm.contractSchedule.businessDayConvention = .modifiedFollowing
        vm.contractSchedule.useLatestCalendarVersion = false
        vm.contractSchedule.calendarVersion = 7

        let schedule = try XCTUnwrap(vm.contractScheduleInput())

        XCTAssertEqual(schedule.calendarID, .moexStock)
        XCTAssertEqual(schedule.calendarVersion, 7)
        XCTAssertEqual(schedule.dayCountConvention, .act365F)
        XCTAssertEqual(schedule.valuationCutoff, .postClosePostEvents)
        XCTAssertEqual(schedule.fixingBindings.first?.assetName, "SBER")
        XCTAssertEqual(schedule.fixingBindings.first?.secid, "SBER")
        XCTAssertEqual(schedule.fixingBindings.first?.board, "TQBR")
        XCTAssertEqual(schedule.fixingBindings.first?.priceBasis,
                       .legalClosePrice)
        XCTAssertEqual(schedule.fixingBindings.first?.session, "main")
        XCTAssertEqual(schedule.fixingBindings.first?.source, .moex)
        XCTAssertEqual(schedule.fixingBindings.first?.missingFixingPolicy,
                       .error)

        asset.board = nil
        let boardless = try XCTUnwrap(vm.contractScheduleInput())
        let raw = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(boardless))
                as? [String: Any])
        let rawBindings = try XCTUnwrap(
            raw["fixing_bindings"] as? [[String: Any]])
        XCTAssertTrue(rawBindings[0]["board"] is NSNull)
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
            board: name == "OFZ" ? "TQCB" : "TQBR",
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

    private func seasonedState(
        currentSpots: [String: Double] = ["SBER": 315, "OFZ": 99],
        referenceSpots: [String: Double] = ["SBER": 300, "OFZ": 100],
        observationIndex: Int = 2,
        stateValues: [String: Double] = ["memory": 0.08],
        runningMin: [String: Double] = ["SBER": 0.80, "OFZ": 0.90],
        runningMax: [String: Double] = ["SBER": 1.10, "OFZ": 1.05],
        elapsedTime: Double = 273.0 / 365.0,
        stateAsOf: String = "2026-07-18",
        stateSourceHash: String? = String(repeating: "a", count: 64)
    ) -> PricingNewCustomValuationStateInput {
        PricingNewCustomValuationStateInput(
            schemaVersion: 1,
            stateContract: "custom_ast_seasoned_state_v1",
            mode: "seasoned",
            assetNames: ["SBER", "OFZ"],
            currentSpots: currentSpots,
            referenceSpots: referenceSpots,
            observationIndex: observationIndex,
            stateValues: stateValues,
            runningMin: runningMin,
            runningMax: runningMax,
            elapsedTime: elapsedTime,
            alive: true,
            stateAsOf: stateAsOf,
            stateSourceHash: stateSourceHash)
    }

    private func makeDraft(
        detail: CustomProductDetail,
        assets: [PricingNewCustomAssetInput],
        slots: [String: Double] = ["T": 2, "coupon": 0.08],
        correlation: [[Double]] = [[1, 0.35], [0.35, 1]],
        calibration: PricingNewCorrelationCalibrationInput = .init(
            mode: "auto", method: "ewma", lookback: 252,
            decay: 0.97, minSamples: 60, fallbackPolicy: "prior"),
        stateMode: PricingNewCustomValuationMode = .inception,
        valuationState: PricingNewCustomValuationStateInput? = nil,
        contractSchedule: PricingNewCustomContractSchedule? = nil,
        includeContractSchedule: Bool = true,
        definitionStateDefaults: [String: Double]? = ["memory": 0],
        resolvedObservationCount: Int? = 4,
        resolvedMaturity: Double? = 2,
        expectedStateAsOf: String? = "2026-07-18",
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
            correlationCalibration: calibration,
            paths: paths, steps: steps, seed: 42,
            editorDirty: editorDirty,
            stateMode: stateMode,
            valuationState: valuationState,
            contractSchedule: includeContractSchedule
                ? (contractSchedule ?? makeContractSchedule(assets: assets))
                : nil,
            definitionStateDefaults: definitionStateDefaults,
            resolvedObservationCount: resolvedObservationCount,
            resolvedMaturity: resolvedMaturity,
            expectedStateAsOf: expectedStateAsOf)
    }

    private func makeContractSchedule(
        assets: [PricingNewCustomAssetInput],
        businessDayConvention: PricingNewCustomBusinessDayConvention = .unadjusted
    ) -> PricingNewCustomContractSchedule {
        PricingNewCustomContractSchedule(
            schemaVersion: 1,
            effectiveDate: "2025-10-18",
            contractualMaturityDate: "2027-10-18",
            contractualObservationDates: [
                "2026-01-18", "2026-04-18", "2026-10-18", "2027-10-18",
            ],
            businessDayConvention: businessDayConvention,
            calendarID: .moexStock,
            calendarVersion: nil,
            dayCountConvention: .act365F,
            valuationCutoff: .postClosePostEvents,
            fixingBindings: assets.sorted { $0.index < $1.index }.map { asset in
                PricingNewCustomFixingBinding(
                    assetName: asset.assetName,
                    secid: asset.secid ?? "",
                    priceBasis: asset.category == "bonds" ? .settlePrice : .close,
                    board: asset.board,
                    session: "",
                    source: .moex,
                    missingFixingPolicy: .error)
            })
    }
}
