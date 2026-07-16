import XCTest
@testable import RiskCalc

final class PricingBookContractTests: XCTestCase {
    func testBookResponseDecodesAggregateAndSignedLegs() throws {
        let json = #"""
        {
          "environment":"FO",
          "snapshot_id":"snap-1",
          "context_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "calculation_id":"calc_book",
          "calculation_timestamp":"2026-07-16T08:00:00+00:00",
          "inputs_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "aggregation":{"status":"provisional","compatible":true,
                         "greeks_compatible":true,
                         "basis":"product:european_option",
                         "risk_factor_basis":"SBER","reason":"same product"},
          "count":2,
          "success_count":2,
          "total_value":7.5,
          "greeks":[{"key":"delta","label":"Delta","value":0.25}],
          "legs":[
            {"id":"A","label":"Long call","product":"european_option",
             "engine":"black_scholes","risk_factor_id":"SBER",
             "quantity":2,"unit_value":10,
             "position_value":20,
             "greeks":[{"key":"delta","label":"Delta","value":1.1}],
             "result":null,"error":null},
            {"id":"B","label":"Short call","product":"european_option",
             "engine":"black_scholes","quantity":-1,"unit_value":12.5,
             "position_value":-12.5,
             "greeks":[{"key":"delta","label":"Delta","value":-0.85}],
             "result":null,"error":null}
          ],
          "errors":[]
        }
        """#
        let book = try JSONDecoder().decode(WsBookResult.self, from: Data(json.utf8))

        XCTAssertEqual(book.environment, "FO")
        XCTAssertEqual(book.snapshotID, "snap-1")
        XCTAssertEqual(book.contextHash?.prefix(4), "aaaa")
        XCTAssertEqual(book.inputsHash?.prefix(4), "bbbb")
        XCTAssertEqual(book.calculationID, "calc_book")
        XCTAssertEqual(book.aggregation?.status, "provisional")
        XCTAssertEqual(book.aggregation?.compatible, true)
        XCTAssertEqual(book.aggregation?.greeksCompatible, true)
        XCTAssertEqual(book.legs.first?.riskFactorID, "SBER")
        XCTAssertEqual(book.successCount, 2)
        XCTAssertEqual(book.totalValue, 7.5)
        XCTAssertEqual(book.legs[1].quantity, -1)
        XCTAssertEqual(book.greeks.first?.value, 0.25)
    }

    func testLadderRowDecodesGreekProfileAdditively() throws {
        let json = #"""
        {"x":100,"value":10.45,"pnl":0,
         "greeks":{"delta":0.6368,"gamma":0.0188},"error":null}
        """#
        let row = try JSONDecoder().decode(WsLadderRow.self, from: Data(json.utf8))

        XCTAssertEqual(row.greeks?["delta"], 0.6368)
        XCTAssertEqual(row.greeks?["gamma"], 0.0188)
    }
}
