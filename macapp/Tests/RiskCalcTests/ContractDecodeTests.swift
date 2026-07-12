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

// MARK: - Pricing workstation contracts

extension ContractDecodeTests {
    func testDecodeWsCatalogue() throws {
        let cat = try JSONDecoder().decode(WsCatalogue.self, from: load("ws_catalogue"))
        XCTAssertGreaterThanOrEqual(cat.products.count, 30)
        XCTAssertEqual(cat.assetClasses.map(\.id).prefix(2), ["equity", "rates"])
        let euro = cat.products.first { $0.id == "european_option" }
        XCTAssertNotNil(euro)
        XCTAssertGreaterThanOrEqual(euro?.engines.count ?? 0, 20)
        XCTAssertEqual(euro?.underlying?.fill["S"], "spot")
        // every engine carries params and governance
        for p in cat.products {
            XCTAssertFalse(p.engines.isEmpty, "\(p.id) engines empty")
            for e in p.engines {
                XCTAssertFalse(e.params.isEmpty, "\(p.id)/\(e.id) params empty")
                XCTAssertFalse(e.governance.status.isEmpty)
            }
        }
    }

    func testDecodeWsPriceIRS() throws {
        let r = try JSONDecoder().decode(WsResult.self, from: load("ws_price_irs"))
        XCTAssertNotNil(r.value)
        XCTAssertTrue(r.errors.isEmpty)
        XCTAssertEqual(r.product, "irs")
        XCTAssertTrue(r.measures.contains { $0.key == "fair_rate" })
    }

    func testDecodeWsPriceSeries() throws {
        let r = try JSONDecoder().decode(WsResult.self, from: load("ws_price_curve"))
        XCTAssertFalse(r.series.isEmpty)
        XCTAssertGreaterThanOrEqual(r.series[0].points.count, 3)
    }

    func testDecodeUnderlyingFacts() throws {
        let f = try JSONDecoder().decode(UnderlyingFacts.self, from: load("ws_underlying"))
        XCTAssertEqual(f.secid, "SBER")
        XCTAssertNotNil(f.facts["spot"] ?? nil)
        // null facts (atm_iv) must decode, not throw
        XCTAssertTrue(f.facts.keys.contains("atm_iv"))
    }

    // MARK: - Swift-бэклог: env picker, book-фильтр, MC VaR, actual P&L

    func testDecodeCatalogueConventions() throws {
        let cat = try JSONDecoder().decode(WsCatalogue.self, from: load("ws_catalogue"))
        XCTAssertFalse(cat.conventions.isEmpty)   // A5: глобальные конвенции
        XCTAssertTrue(cat.conventions.contains { $0.contains("ACT/365") })
    }

    func testDecodeEnvironments() throws {
        let envs = try JSONDecoder().decode(WsEnvironments.self, from: load("environments"))
        let ids = Set(envs.environments.map(\.envID))
        XCTAssertTrue(ids.isSuperset(of: ["FO", "RISK", "EOD", "VAR", "STRESS"]))
    }

    func testDecodeMarketRiskMonteCarlo() throws {
        let mc = try JSONDecoder().decode(MRMonteCarlo.self, from: load("marketrisk_montecarlo"))
        XCTAssertGreaterThan(mc.varValue, 0)
        XCTAssertFalse(mc.histogram.isEmpty)
        XCTAssertTrue(mc.factors.contains { $0.contains("eq") || $0.contains("equity") || $0.contains("IMOEX") })
    }

    func testDecodePortfolioBooks() throws {
        let books = try JSONDecoder().decode(MRBooks.self, from: load("portfolio_books"))
        XCTAssertFalse(books.books.isEmpty)
        XCTAssertGreaterThan(books.books[0].positions, 0)
    }

    func testDecodeMarketRiskBookSlice() throws {
        let ov = try JSONDecoder().decode(MROverview.self, from: load("marketrisk_overview"))
        XCTAssertEqual(ov.book, "Trading")
        XCTAssertGreaterThan(ov.varValue, 0)
    }

    func testDecodeMarketRiskBacktestActual() throws {
        let bt = try JSONDecoder().decode(MRBacktest.self, from: load("marketrisk_backtest"))
        XCTAssertNotNil(bt.actualBacktest)   // actual_backtest всегда присутствует
    }

    func testDecodePnlExplainWithActual() throws {
        let d = try JSONDecoder().decode(PnlExplain.self, from: load("pnl_explain_actual"))
        let avh = try XCTUnwrap(d.actualVsHypothetical)
        XCTAssertTrue(avh.available)
        XCTAssertNotNil(avh.actualPnl)
        XCTAssertNotNil(avh.gap)
    }

    func testDecodePnlExplainNoActual() throws {
        let d = try JSONDecoder().decode(PnlExplain.self, from: load("pnl_explain"))
        XCTAssertEqual(d.actualVsHypothetical?.available, false)
    }
}
