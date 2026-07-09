import Foundation

// MARK: - Universal pricing workstation (GET /pricing/catalogue)

struct WsCatalogue: Decodable, Sendable {
    let assetClasses: [WsAssetClass]
    let curves: [WsCurveRef]
    let products: [WsProductModel]

    enum CodingKeys: String, CodingKey {
        case curves, products
        case assetClasses = "asset_classes"
    }
}

struct WsAssetClass: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let label: String
}

struct WsCurveRef: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let label: String
}

struct WsProductModel: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let name: String
    let assetClass: String
    let group: String
    let note: String
    let capturable: Bool
    let underlying: WsUnderlyingSpec?
    let engines: [WsEngineModel]

    enum CodingKeys: String, CodingKey {
        case id, name, group, note, capturable, underlying, engines
        case assetClass = "asset_class"
    }
}

struct WsUnderlyingSpec: Decodable, Sendable, Hashable {
    let categories: [String]
    let fill: [String: String]           // param key -> fact key
    let appendTo: String?                // e.g. basket text field

    enum CodingKeys: String, CodingKey {
        case categories, fill
        case appendTo = "append_to"
    }
}

struct WsEngineModel: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let modelID: String
    let name: String
    let governance: Governance
    let params: [ParamSpec]

    enum CodingKeys: String, CodingKey {
        case id, name, governance, params
        case modelID = "model_id"
    }
}

// MARK: - Result (POST /pricing/price)

struct WsMeasure: Decodable, Sendable, Identifiable, Hashable {
    let key: String
    let label: String
    let value: Double
    var id: String { key }
}

struct WsPoint: Decodable, Sendable, Hashable {
    let x: Double
    let y: Double
}

struct WsSeries: Decodable, Sendable, Identifiable, Hashable {
    let key: String
    let label: String
    let points: [WsPoint]
    var id: String { key }
}

struct WsResult: Decodable, Sendable {
    let value: Double?
    let modelID: String
    let modelStatus: String
    let greeks: [WsMeasure]
    let measures: [WsMeasure]
    let series: [WsSeries]
    let warnings: [String]
    let errors: [String]
    let limitations: [String]
    let product: String
    let engine: String

    enum CodingKeys: String, CodingKey {
        case value, greeks, measures, series, warnings, errors, limitations, product, engine
        case modelID = "model_id"
        case modelStatus = "model_status"
    }
}

// MARK: - Desk risk: ladder + scenarios

struct WsLadderRow: Decodable, Sendable, Hashable {
    let x: Double
    let value: Double?
    let pnl: Double?
    let error: String?
}

struct WsLadder: Decodable, Sendable {
    let product: String
    let engine: String
    let bumpKey: String
    let baseValue: Double?
    let rows: [WsLadderRow]

    enum CodingKeys: String, CodingKey {
        case product, engine, rows
        case bumpKey = "bump_key"
        case baseValue = "base_value"
    }
}

struct WsScenarioRow: Decodable, Sendable, Identifiable, Hashable {
    let scenario: String
    let spotShock: Double
    let volShock: Double
    let rateShock: Double
    let value: Double?
    let pnl: Double?
    let pnlPct: Double?
    let error: String?
    var id: String { scenario }

    enum CodingKeys: String, CodingKey {
        case scenario, value, pnl, error
        case spotShock = "spot_shock"
        case volShock = "vol_shock"
        case rateShock = "rate_shock"
        case pnlPct = "pnl_pct"
    }
}

struct WsScenarios: Decodable, Sendable {
    let product: String
    let engine: String
    let baseValue: Double?
    let rows: [WsScenarioRow]

    enum CodingKeys: String, CodingKey {
        case product, engine, rows
        case baseValue = "base_value"
    }
}

struct WsPayoff: Decodable, Sendable {
    let spot: Double
    let spotKey: String
    let baseValue: Double?
    let value: [WsPoint]
    let payoff: [WsPoint]

    enum CodingKeys: String, CodingKey {
        case spot, value, payoff
        case spotKey = "spot_key"
        case baseValue = "base_value"
    }
}

// MARK: - Underlying facts (GET /pricing/underlying/{category}/{secid})

struct UnderlyingFacts: Decodable, Sendable {
    let secid: String
    let category: String
    let label: String
    let currency: String?
    let facts: [String: Double?]
}

// MARK: - Bridge calls

private struct WsPriceBody: Encodable {
    let product: String
    let engine: String
    let params: [String: BridgeValue]
}

private struct WsLadderBody: Encodable {
    let product: String
    let engine: String
    let params: [String: BridgeValue]
    let bump_key: String
    let lo: Double
    let hi: Double
    let steps: Int
}

private struct WsCaptureBody: Encodable {
    let product: String
    let engine: String
    let params: [String: BridgeValue]
    let quantity: Double
}

struct WsIncrementalVaR: Decodable, Sendable {
    let varBase: Double
    let varWithTrade: Double
    let incrementalVaR: Double
    let standaloneVaR: Double
    let diversificationBenefit: Double
    let confidence: Double

    enum CodingKeys: String, CodingKey {
        case confidence
        case varBase = "var_base"
        case varWithTrade = "var_with_trade"
        case incrementalVaR = "incremental_var"
        case standaloneVaR = "standalone_var"
        case diversificationBenefit = "diversification_benefit"
    }
}

struct WsCaptureResult: Decodable, Sendable {
    let positionID: String
    let instrument: String
    let description: String
    let quantity: Double
    let marketValue: Double?
    let positions: Int

    enum CodingKeys: String, CodingKey {
        case instrument, description, quantity, positions
        case positionID = "position_id"
        case marketValue = "market_value"
    }
}

extension BridgeClient {
    func wsCatalogue() async throws -> WsCatalogue { try await get("pricing/catalogue") }

    func wsPrice(product: String, engine: String,
                 params: [String: BridgeValue]) async throws -> WsResult {
        let body = try JSONEncoder().encode(
            WsPriceBody(product: product, engine: engine, params: params))
        return try await post("pricing/price", body: body)
    }

    func wsLadder(product: String, engine: String, params: [String: BridgeValue],
                  bumpKey: String, lo: Double, hi: Double, steps: Int) async throws -> WsLadder {
        let body = try JSONEncoder().encode(WsLadderBody(
            product: product, engine: engine, params: params,
            bump_key: bumpKey, lo: lo, hi: hi, steps: steps))
        return try await post("pricing/ladder", body: body)
    }

    func wsScenarios(product: String, engine: String,
                     params: [String: BridgeValue]) async throws -> WsScenarios {
        let body = try JSONEncoder().encode(
            WsPriceBody(product: product, engine: engine, params: params))
        return try await post("pricing/scenarios", body: body)
    }

    func underlyingFacts(category: String, secid: String) async throws -> UnderlyingFacts {
        try await get("pricing/underlying/\(category)/\(secid)")
    }

    func payoff(product: String, engine: String,
                params: [String: BridgeValue]) async throws -> WsPayoff {
        let body = try JSONEncoder().encode(
            WsPriceBody(product: product, engine: engine, params: params))
        return try await post("pricing/payoff", body: body)
    }

    func impliedVol(product: String, params: [String: BridgeValue],
                    marketPrice: Double) async throws -> Double {
        struct Body: Encodable {
            let product: String
            let params: [String: BridgeValue]
            let market_price: Double
        }
        struct Resp: Decodable {
            let implied_vol: Double
        }
        let body = try JSONEncoder().encode(Body(product: product, params: params,
                                                 market_price: marketPrice))
        let resp: Resp = try await post("pricing/implied_vol", body: body)
        return resp.implied_vol
    }

    func addToPortfolio(product: String, engine: String, params: [String: BridgeValue],
                        quantity: Double) async throws -> WsCaptureResult {
        let body = try JSONEncoder().encode(WsCaptureBody(
            product: product, engine: engine, params: params, quantity: quantity))
        return try await post("portfolio/add", body: body)
    }

    func incrementalVaR(product: String, engine: String, params: [String: BridgeValue],
                        quantity: Double) async throws -> WsIncrementalVaR {
        let body = try JSONEncoder().encode(WsCaptureBody(
            product: product, engine: engine, params: params, quantity: quantity))
        return try await post("marketrisk/incremental", body: body)
    }

    func addMarketToPortfolio(category: String, secid: String,
                              quantity: Double) async throws -> WsCaptureResult {
        try await post("portfolio/add_market?category=\(category)&secid=\(secid)&quantity=\(quantity)",
                       body: Data("{}".utf8))
    }

    func removePosition(_ positionID: String) async throws {
        try await delete("portfolio/position/\(positionID)")
    }

    func resetPortfolio() async throws {
        struct ResetResponse: Decodable { let reset: Bool }
        let _: ResetResponse = try await post("portfolio/reset", body: Data("{}".utf8))
    }
}
