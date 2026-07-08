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
    let underlying: WsUnderlyingSpec?
    let engines: [WsEngineModel]

    enum CodingKeys: String, CodingKey {
        case id, name, group, note, underlying, engines
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

extension BridgeClient {
    func wsCatalogue() async throws -> WsCatalogue { try await get("pricing/catalogue") }

    func wsPrice(product: String, engine: String,
                 params: [String: BridgeValue]) async throws -> WsResult {
        let body = try JSONEncoder().encode(
            WsPriceBody(product: product, engine: engine, params: params))
        return try await post("pricing/price", body: body)
    }

    func underlyingFacts(category: String, secid: String) async throws -> UnderlyingFacts {
        try await get("pricing/underlying/\(category)/\(secid)")
    }
}
