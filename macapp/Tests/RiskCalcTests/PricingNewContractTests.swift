import XCTest
@testable import RiskCalc

final class PricingNewContractTests: XCTestCase {
    func testNamedRunDecodesExactRequestAndBookResult() throws {
        let json = #"""
        {
          "run_id":"8f218f93-168c-4b75-b624-c8dff4f7cc82",
          "created_at":"2026-07-16T10:00:00.000Z",
          "name":"Two-option validation",
          "content_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "request":{"env_id":"FO","legs":[{
            "id":"A","label":"Long call","product":"european_option",
            "engine":"black_scholes","risk_factor_id":"SBER","currency":"RUB",
            "params":{"S":100,"K":105,"opt":"call","secid":"SBER"},"quantity":2
          }]},
          "result":{"environment":"FO","snapshot_id":"snap-1","context_hash":"ctx",
            "calculation_id":"calc-1","calculation_timestamp":"2026-07-16T10:00:00Z",
            "inputs_hash":"hash","aggregation":null,"count":1,"success_count":1,
            "total_value":12.5,"greeks":[],"legs":[],"errors":[]}
        }
        """#
        let run = try JSONDecoder().decode(PricingNewRunRecord.self, from: Data(json.utf8))

        XCTAssertEqual(run.name, "Two-option validation")
        XCTAssertEqual(run.request.envID, "FO")
        XCTAssertEqual(run.request.legs.first?.currency, "RUB")
        XCTAssertEqual(run.request.legs.first?.params["K"]?.doubleValue, 105)
        XCTAssertEqual(run.result.successCount, 1)
    }

    func testTransientRiskDecodesScopeAndNoGlobalPortfolioEvidence() throws {
        let json = #"""
        {
          "scope":"pricing_new_transient_book","partial":false,
          "confidence":0.99,"window":500,"horizon":1,
          "model":"historical_full_reprice","model_label":"Historical (full reprice)",
          "currency":"RUB","portfolio_value":1000,"positions":2,
          "var":42,"es":55,"n_scenarios":250,
          "histogram":[{"x":-42,"count":3}],
          "hyppl":[{"date":"2026-07-15","pnl":-42}],
          "factors":["EQ:SBER"],"data_quality":[],
          "capability":{"supported":true,"requested_count":2,"convertible_count":2,
            "supported_count":2,"unsupported":[],"currencies":["RUB"],"base_currency":"RUB"},
          "provenance":{"history_source":"stored_market_factor_history",
            "history_first_date":"2025-07-15","history_last_date":"2026-07-15",
            "history_observations":250,"snapshot_id":"snap-1","calculation_id":"risk-1",
            "inputs_hash":"hash","portfolio_source":"request_legs_only",
            "global_portfolio_used":false},
          "pricing_run_id":"run-1","pricing_run_name":"Validation"
        }
        """#
        let risk = try JSONDecoder().decode(PricingNewRiskResult.self, from: Data(json.utf8))

        XCTAssertEqual(risk.varValue, 42)
        XCTAssertEqual(risk.es, 55)
        XCTAssertTrue(risk.capability.supported)
        XCTAssertFalse(risk.provenance.globalPortfolioUsed)
        XCTAssertEqual(risk.provenance.portfolioSource, "request_legs_only")
    }

    @MainActor
    func testWorksheetStartsWithExplicitRUBEuropeanOptionAndRequiresName() throws {
        guard let url = Bundle.module.url(forResource: "ws_catalogue", withExtension: "json",
                                          subdirectory: "Fixtures") else {
            return XCTFail("ws_catalogue fixture not bundled")
        }
        let catalogue = try JSONDecoder().decode(
            WsCatalogue.self, from: Data(contentsOf: url))
        let vm = PricingNewWorkspaceViewModel()
        vm.catalogue = catalogue

        vm.addInstrument()

        XCTAssertEqual(vm.legs.count, 1)
        XCTAssertEqual(vm.legs[0].productID, "european_option")
        XCTAssertEqual(vm.legs[0].engineID, "black_scholes")
        XCTAssertEqual(vm.legs[0].currency, "RUB")
        XCTAssertFalse(vm.canPrice)
        vm.runName = "Named run"
        XCTAssertTrue(vm.canPrice)
    }

    @MainActor
    func testUnderlyingIdentityParticipatesInStaleSignature() throws {
        guard let url = Bundle.module.url(forResource: "ws_catalogue", withExtension: "json",
                                          subdirectory: "Fixtures") else {
            return XCTFail("ws_catalogue fixture not bundled")
        }
        let vm = PricingNewWorkspaceViewModel()
        vm.catalogue = try JSONDecoder().decode(
            WsCatalogue.self, from: Data(contentsOf: url))
        vm.addInstrument()
        let before = vm.currentSignature

        vm.legs[0].selectedUnderlyings = [PricingNewUnderlyingRef(
            secid: "SBER", category: "equities", label: "Sber", currency: "RUB")]

        XCTAssertNotEqual(vm.currentSignature, before)
    }
}
