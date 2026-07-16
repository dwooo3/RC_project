import Foundation

// MARK: - Bond catalogue (GET /instruments/bond)

struct BondCatalogue: Decodable, Sendable {
    let curves: [CurveOption]
    let instruments: [BondInstrument]
}

struct CurveOption: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let label: String
}

struct BondInstrument: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let modelID: String
    let name: String
    let group: String
    let needsCurve: Bool
    let governance: BondGovernance
    let params: [ParamSpec]

    enum CodingKeys: String, CodingKey {
        case id, name, group, governance, params
        case modelID = "model_id"
        case needsCurve = "needs_curve"
    }
}

struct BondGovernance: Decodable, Sendable, Hashable {
    let status: String
    let canonicalComponentID: String?
    let componentKind: String?
    let qLevel: String?
    let implementationScope: String?
    let assetClass: String
    let method: String
    let notes: String

    enum CodingKeys: String, CodingKey {
        case status, method, notes
        case canonicalComponentID = "canonical_component_id"
        case componentKind = "component_kind"
        case qLevel = "q_level"
        case implementationScope = "implementation_scope"
        case assetClass = "asset_class"
    }
}

// MARK: - Bond price result (POST /instruments/bond/price)

struct BondResult: Decodable, Sendable {
    let value: Double?
    let cleanPrice: Double?
    let dirtyPrice: Double?
    let accruedInterest: Double?
    let analytics: [AnalyticRow]
    let keyRateDurations: [KRDRow]
    let cashflows: [Cashflow]
    let modelID: String
    let modelStatus: String
    let modelLimitations: [String]
    let warnings: [String]
    let errors: [String]

    enum CodingKeys: String, CodingKey {
        case value, analytics, cashflows, warnings, errors
        case cleanPrice = "clean_price"
        case dirtyPrice = "dirty_price"
        case accruedInterest = "accrued_interest"
        case keyRateDurations = "key_rate_durations"
        case modelID = "model_id"
        case modelStatus = "model_status"
        case modelLimitations = "model_limitations"
    }
}

struct AnalyticRow: Decodable, Sendable, Identifiable {
    let key: String
    let label: String
    let value: Double
    var id: String { key }

    /// True for rate-like measures shown as a percentage.
    var isRate: Bool {
        ["ytm", "ytw", "ytc", "ytp", "zspread", "g_spread", "i_spread", "oas"].contains(key)
    }
}

struct KRDRow: Decodable, Sendable, Identifiable {
    let tenor: Double
    let value: Double
    var id: Double { tenor }
}

struct Cashflow: Decodable, Sendable, Identifiable {
    let t: Double
    let amount: Double
    var id: Double { t }
}

// MARK: - Curves (GET /curves)

struct CurvesResponse: Decodable, Sendable {
    let curves: [CurveData]
}

struct CurveData: Decodable, Sendable, Identifiable {
    let id: String
    let label: String
    let zero: [CurvePt]
    let par: [CurvePt]
    let forward: [CurvePt]
}

struct CurvePt: Decodable, Sendable, Identifiable {
    let t: Double
    let rate: Double
    var id: Double { t }
}

// MARK: - Batch pricing (POST /instruments/bond/price_batch)

struct BatchResponse: Decodable, Sendable {
    let results: [BatchRowResult]
    let aggregate: BondAggregate
}

struct BatchRowResult: Decodable, Sendable {
    let instrument: String
    let name: String
    let quantity: Double
    let value: Double?
    let analytics: [AnalyticRow]
    let modelStatus: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case instrument, name, quantity, value, analytics, error
        case modelStatus = "model_status"
    }

    func analytic(_ key: String) -> Double? { analytics.first { $0.key == key }?.value }
}

// MARK: - Real bonds (GET /realbonds, POST /realbonds/reprice)

struct RealSnapshot: Decodable, Sendable {
    let snapshotID: String
    let valuationDate: String
    let isLive: Bool
    enum CodingKeys: String, CodingKey {
        case snapshotID = "snapshot_id"
        case valuationDate = "valuation_date"
        case isLive = "is_live"
    }
}

struct RealBondList: Decodable, Sendable {
    let snapshot: RealSnapshot
    let bonds: [RealBondRow]
    let boards: [String]
    let count: Int
}

struct RealBondRow: Decodable, Sendable, Identifiable {
    let secid: String
    let isin: String?
    let issuer: String?
    let board: String?
    let couponPercent: Double?
    let matDate: String?
    let cleanPrice: Double?
    let ytm: Double?
    let volume: Double?
    let listLevel: Int?
    let currency: String?
    var id: String { secid }

    enum CodingKeys: String, CodingKey {
        case secid, isin, issuer, board, ytm, volume, currency
        case couponPercent = "coupon_percent"
        case matDate = "mat_date"
        case cleanPrice = "clean_price"
        case listLevel = "list_level"
    }
}

struct RepriceResult: Decodable, Sendable {
    let secid: String
    let isin: String?
    let issuer: String?
    let board: String?
    let couponPercent: Double?
    let matDate: String?
    let curveID: String
    let curveLabel: String
    let shiftBps: Double
    let marketClean: Double
    let marketDirty: Double
    let marketAccrued: Double
    let marketYtm: Double?
    let impliedYtm: Double?
    let curveYtm: Double?
    let theoreticalClean: Double
    let theoreticalDirty: Double
    let priceDiff: Double
    let zSpreadBps: Double?
    let ytmSpreadBps: Double?
    let isFloater: Bool
    let forecastCurveID: String?
    let floatSpreadBps: Double?
    let cashflows: [Cashflow]
    let nCashflows: Int
    let valuationDate: String

    enum CodingKeys: String, CodingKey {
        case secid, isin, issuer, board, cashflows
        case isFloater = "is_floater"
        case forecastCurveID = "forecast_curve_id"
        case floatSpreadBps = "float_spread_bps"
        case couponPercent = "coupon_percent"
        case matDate = "mat_date"
        case curveID = "curve_id"
        case curveLabel = "curve_label"
        case shiftBps = "shift_bps"
        case marketClean = "market_clean"
        case marketDirty = "market_dirty"
        case marketAccrued = "market_accrued"
        case marketYtm = "market_ytm"
        case impliedYtm = "implied_ytm"
        case curveYtm = "curve_ytm"
        case theoreticalClean = "theoretical_clean"
        case theoreticalDirty = "theoretical_dirty"
        case priceDiff = "price_diff"
        case zSpreadBps = "z_spread_bps"
        case ytmSpreadBps = "ytm_spread_bps"
        case nCashflows = "n_cashflows"
        case valuationDate = "valuation_date"
    }
}

struct BondAggregate: Decodable, Sendable {
    let count: Int
    let marketValue: Double
    let dv01: Double
    let modDuration: Double
    let convexity: Double
    let keyRateDurations: [KRDRow]

    enum CodingKeys: String, CodingKey {
        case count, dv01, convexity
        case marketValue = "market_value"
        case modDuration = "mod_duration"
        case keyRateDurations = "key_rate_durations"
    }
}
