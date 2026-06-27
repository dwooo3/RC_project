import XCTest
@testable import RiskCalc

/// Contract tests (audit MD-013): decode the Swift API models against real JSON
/// payloads captured from the bridge (Tests/.../Fixtures/*.json). A backend that
/// changes a key, nests a value, or sends null in a non-optional field breaks
/// these — catching macOS decode failures that green backend tests would miss.
///
/// Refresh fixtures with the bridge running:
///   curl -s localhost:8765/catalogue > Tests/RiskCalcTests/Fixtures/catalogue.json   (etc.)
final class ContractDecodeTests: XCTestCase {

    private func load(_ name: String) throws -> Data {
        guard let url = Bundle.module.url(forResource: name, withExtension: "json",
                                          subdirectory: "Fixtures") else {
            XCTFail("fixture \(name).json not bundled"); return Data()
        }
        return try Data(contentsOf: url)
    }

    private func decode<T: Decodable>(_ type: T.Type, _ name: String) throws -> T {
        try JSONDecoder().decode(T.self, from: load(name))
    }

    func testDecodeCatalogue() throws {
        let cat = try decode(Catalogue.self, "catalogue")
        XCTAssertFalse(cat.pricers.isEmpty)
        let bsm = cat.pricers.first { $0.id == "bsm" }
        XCTAssertNotNil(bsm, "expected a bsm pricer")
        // the vol-surface selector must be present with a manual-σ + at least one surface
        let surfaceParam = bsm?.params.first { $0.key == "vol_surface_id" }
        XCTAssertNotNil(surfaceParam, "bsm should expose vol_surface_id")
        XCTAssertGreaterThanOrEqual(surfaceParam?.choices?.count ?? 0, 2)
    }

    func testDecodeMDListBonds() throws {
        let list = try decode(MDListResponse.self, "md_list_bonds")
        XCTAssertEqual(list.category, "bonds")
        XCTAssertFalse(list.instruments.isEmpty)
        XCTAssertFalse(list.instruments[0].secid.isEmpty)
    }

    func testDecodeMDInstrumentBond() throws {
        let e = try decode(MDEntity.self, "md_instrument_bond")
        XCTAssertFalse(e.secid.isEmpty)
    }

    func testDecodeMDHistory() throws {
        let h = try decode(MDHistory.self, "md_history")
        XCTAssertFalse(h.points.isEmpty)
        XCTAssertEqual(h.points.count, h.count)
    }

    func testDecodeVolSurfaceList() throws {
        let l = try decode(VolSurfaceList.self, "volsurface_list")
        XCTAssertFalse(l.underlyings.isEmpty)
    }

    func testDecodeVolSurface() throws {
        let s = try decode(VolSurface.self, "volsurface")
        XCTAssertFalse(s.expiries.isEmpty)
        XCTAssertFalse(s.deltas.isEmpty)
        // fit diagnostics (cluster 1 / MD-011) must round-trip
        XCTAssertNotNil(s.diagnostics?.rmse)
    }

    func testDecodeDataHealth() throws {
        let h = try decode(DataHealth.self, "health")
        XCTAssertTrue(h.available)
        XCTAssertNotNil(h.status)
        XCTAssertNotNil(h.productionEligible)
    }

    func testDecodeCurves() throws {
        let c = try decode(CurvesResponse.self, "curves")
        XCTAssertFalse(c.curves.isEmpty)
    }
}
