import XCTest
@testable import RiskCalc

final class CustomMarketInputGridTests: XCTestCase {
    func testResizeOneToFivePreservesInputsAndBuildsSymmetricMatrix() {
        let vols = CustomMarketInputGrid.resizedVector([0.22], count: 5,
                                                       defaultValue: 0.30)
        let qs = CustomMarketInputGrid.resizedVector([0.01], count: 5,
                                                     defaultValue: 0.02)
        let corr = CustomMarketInputGrid.resizedCorrelation(
            [[1.0]], count: 5, defaultOffDiagonal: 0.35)

        XCTAssertEqual(vols, [0.22, 0.30, 0.30, 0.30, 0.30])
        XCTAssertEqual(qs, [0.01, 0.02, 0.02, 0.02, 0.02])
        XCTAssertEqual(corr.count, 5)
        XCTAssertEqual(corr[0][4], 0.35)
        XCTAssertEqual(corr[4][0], 0.35)
        XCTAssertEqual(corr[3][3], 1.0)
    }

    func testCorrelationEditMirrorsAndValidationChecksPSD() {
        let base = CustomMarketInputGrid.equicorrelation(count: 3, rho: 0.2)
        let edited = CustomMarketInputGrid.settingCorrelation(
            base, row: 0, column: 2, value: -0.4)
        XCTAssertEqual(edited[0][2], -0.4)
        XCTAssertEqual(edited[2][0], -0.4)

        let issues = CustomMarketInputGrid.validationIssues(
            sigmas: [0.2, 0.2, 0.2], qs: [0, 0, 0],
            correlation: [[1, 0.99, 0.99], [0.99, 1, -0.99],
                          [0.99, -0.99, 1]],
            assetCount: 3, rate: 0.05, nSims: 10_000, steps: 252, seed: 42)
        XCTAssertTrue(issues.contains { $0.contains("положительно определённой") })
    }

    func testCustomPricePayloadCarriesFullMultiAssetControls() throws {
        let market = CustomMarketPayload(
            r: 0.05, sigmas: [0.2, 0.25], qs: [0.01, 0.02],
            corr: [[1, 0.4], [0.4, 1]])
        let body = CustomPriceRequestBody(
            slots: ["coupon": 0.05], market: market,
            n_sims: 25_000, steps: 365, seed: 7)
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(body))
                as? [String: Any])
        let encodedMarket = try XCTUnwrap(object["market"] as? [String: Any])

        XCTAssertEqual(object["steps"] as? Int, 365)
        XCTAssertEqual((encodedMarket["qs"] as? [Double])?.count, 2)
        XCTAssertEqual((encodedMarket["corr"] as? [[Double]])?[0][1], 0.4)
    }

    func testSeedMustFitBackendSignedRange() {
        let issues = CustomMarketInputGrid.validationIssues(
            sigmas: [0.2], qs: [0], correlation: [[1]], assetCount: 1,
            rate: 0.05, nSims: 10_000, steps: 252,
            seed: Double(Int32.max) + 1)
        XCTAssertTrue(issues.contains { $0.contains("2147483647") })

        let huge = CustomMarketInputGrid.validationIssues(
            sigmas: [0.2], qs: [0], correlation: [[1]], assetCount: 1,
            rate: 0.05, nSims: 10_000, steps: 252, seed: 1e300)
        XCTAssertFalse(huge.isEmpty)
    }
}
