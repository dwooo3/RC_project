import Foundation

// MARK: - Shared

struct SnapshotMeta: Decodable, Sendable, Hashable {
    let snapshotID: String
    let valuationDate: String
    let source: String
    let quality: String
    let isLive: Bool
    let isDemo: Bool

    enum CodingKeys: String, CodingKey {
        case snapshotID = "snapshot_id"
        case valuationDate = "valuation_date"
        case source, quality
        case isLive = "is_live"
        case isDemo = "is_demo"
    }
}

struct Mover: Decodable, Sendable, Identifiable, Hashable {
    let secid: String
    let chgPct: Double
    let last: Double
    let volume: Double
    var id: String { secid }

    enum CodingKeys: String, CodingKey {
        case secid, last, volume
        case chgPct = "chg_pct"
    }
}

// MARK: - Dashboard

struct DashboardData: Decodable, Sendable {
    let snapshot: SnapshotMeta
    let portfolio: PortfolioMini
    let risk: RiskMini
    let governance: GovernanceMini
    let market: MarketMini
}

struct PortfolioMini: Decodable, Sendable {
    let totalMarketValue: Double
    let baseCurrency: String
    let nPositions: Int

    enum CodingKeys: String, CodingKey {
        case totalMarketValue = "total_market_value"
        case baseCurrency = "base_currency"
        case nPositions = "n_positions"
    }
}

struct RiskMini: Decodable, Sendable {
    let varValue: Double
    let expectedShortfall: Double
    let confidence: Double
    let horizonDays: Int

    enum CodingKeys: String, CodingKey {
        case varValue = "var"
        case expectedShortfall = "expected_shortfall"
        case confidence
        case horizonDays = "horizon_days"
    }
}

struct GovernanceMini: Decodable, Sendable {
    let counts: [String: Int]
    let total: Int
}

struct MarketMini: Decodable, Sendable {
    let keyRate: Double?
    let kbd: [String: Double]
    let fx: [String: Double]
    let keyVols: [String: Double]
    let topMovers: [Mover]
    let mostActive: [Mover]

    enum CodingKeys: String, CodingKey {
        case keyRate = "key_rate"
        case kbd, fx
        case keyVols = "key_vols"
        case topMovers = "top_movers"
        case mostActive = "most_active"
    }
}

// MARK: - Market

struct MarketData: Decodable, Sendable {
    let snapshot: SnapshotMeta
    let overview: MarketOverview
    let curve: [CurvePoint]
}

struct CurvePoint: Decodable, Sendable, Identifiable {
    let tenor: Double
    let rate: Double
    var id: Double { tenor }
}

struct MarketOverview: Decodable, Sendable {
    let kbd: [String: Double]
    let fx: [String: Double]
    let keyVols: [String: Double]
    let keyRate: Double?
    let topMovers: [Mover]
    let mostActive: [Mover]

    enum CodingKeys: String, CodingKey {
        case kbd, fx
        case keyVols = "key_vols"
        case keyRate = "key_rate"
        case topMovers = "top_movers"
        case mostActive = "most_active"
    }
}

// MARK: - Portfolio

struct PortfolioData: Decodable, Sendable {
    let snapshot: SnapshotMeta
    let valuation: Valuation
    let positions: [PositionRow]
    let aggregate: Aggregate
}

struct Valuation: Decodable, Sendable {
    let portfolioID: String
    let baseCurrency: String
    let snapshotID: String
    let totalMarketValue: Double
    let warnings: [String]
    let nPositions: Int

    enum CodingKeys: String, CodingKey {
        case portfolioID = "portfolio_id"
        case baseCurrency = "base_currency"
        case snapshotID = "snapshot_id"
        case totalMarketValue = "total_market_value"
        case warnings
        case nPositions = "n_positions"
    }
}

struct PositionRow: Decodable, Sendable, Identifiable {
    let id: String
    let instrument: String
    let description: String
    let quantity: Double
    let price: Double?
    let marketValue: Double?
    let delta: Double?
    let gamma: Double?
    let vega: Double?
    let theta: Double?
    let dv01: Double?
    let cs01: Double?

    enum CodingKeys: String, CodingKey {
        case id, instrument, description, quantity, price, delta, gamma, vega, theta, dv01, cs01
        case marketValue = "market_value"
    }
}

struct Aggregate: Decodable, Sendable {
    let nPositions: Int
    let marketValue: Double
    let exposureBuckets: [String: [String: Double]]

    enum CodingKeys: String, CodingKey {
        case nPositions = "n_positions"
        case marketValue = "market_value"
        case exposureBuckets = "exposure_buckets"
    }
}

// MARK: - Risk / Analytics

struct RiskData: Decodable, Sendable {
    let var99: VaR
    let var95: VaR
    let var9910d: VaR
    let decomposition: Decomposition
    let whatIfGrid: WhatIfGrid

    enum CodingKeys: String, CodingKey {
        case var99 = "var_99"
        case var95 = "var_95"
        case var9910d = "var_99_10d"
        case decomposition
        case whatIfGrid = "what_if_grid"
    }
}

struct VaR: Decodable, Sendable {
    let marketValue: Double
    let confidence: Double
    let varValue: Double
    let expectedShortfall: Double
    let sigmaAnnual: Double
    let horizonDays: Int
    let method: String
    let volSource: String

    enum CodingKeys: String, CodingKey {
        case marketValue = "market_value"
        case confidence
        case varValue = "var"
        case expectedShortfall = "expected_shortfall"
        case sigmaAnnual = "sigma_annual"
        case horizonDays = "horizon_days"
        case method
        case volSource = "vol_source"
    }
}

struct Decomposition: Decodable, Sendable {
    let byFactor: [FactorRow]
    let byBucket: [String: Double]
    let byPosition: [PositionExposure]

    enum CodingKeys: String, CodingKey {
        case byFactor = "by_factor"
        case byBucket = "by_bucket"
        case byPosition = "by_position"
    }
}

struct FactorRow: Decodable, Sendable, Identifiable {
    let factor: String
    let bucket: String
    let unit: String
    let sensitivity: Double
    let contribution: Double
    var id: String { factor }
}

struct PositionExposure: Decodable, Sendable, Identifiable {
    let id: String
    let instrument: String
    let mv: Double
    let dv01: Double
    let delta: Double
    let vega: Double
}

struct WhatIfGrid: Decodable, Sendable {
    let spotShocks: [Double]
    let volShocks: [Double]
    let pnlGrid: [[Double]]

    enum CodingKeys: String, CodingKey {
        case spotShocks = "spot_shocks"
        case volShocks = "vol_shocks"
        case pnlGrid = "pnl_grid"
    }
}

struct AnalyticsData: Decodable, Sendable {
    let decomposition: Decomposition
    let scenarios: ScenarioLibrary
    let whatIfGrid: WhatIfGrid

    enum CodingKeys: String, CodingKey {
        case decomposition, scenarios
        case whatIfGrid = "what_if_grid"
    }
}

struct ScenarioLibrary: Decodable, Sendable {
    let scenarios: [ScenarioRow]
}

struct ScenarioRow: Decodable, Sendable, Identifiable {
    let name: String
    let pnl: Double
    let shocks: [String: Double]
    var id: String { name }
}

// MARK: - Governance

struct GovernanceData: Decodable, Sendable {
    let counts: [String: Int]
    let models: [ModelRow]
    let limitations: [LimitationRow]
    let audit: [AuditRow]
}

struct ModelRow: Decodable, Sendable, Identifiable {
    let modelID: String
    let status: String
    let version: String
    let owner: String
    let name: String
    let domain: String
    let workflowLayer: String
    let productionAllowed: Bool
    let analyticsLabOnly: Bool
    var id: String { modelID }

    enum CodingKeys: String, CodingKey {
        case modelID = "model_id"
        case status, version, owner, name, domain
        case workflowLayer = "workflow_layer"
        case productionAllowed = "production_allowed"
        case analyticsLabOnly = "analytics_lab_only"
    }
}

struct LimitationRow: Decodable, Sendable, Identifiable {
    let modelID: String
    let status: String
    let limitation: String
    var id: String { modelID + limitation.prefix(12) }

    enum CodingKeys: String, CodingKey {
        case modelID = "model_id"
        case status, limitation
    }
}

// MARK: - Market-data browser (snapshots + curves)

struct SnapshotsResponse: Decodable, Sendable {
    let active: String
    let snapshots: [SnapshotInfo]
}

struct SnapshotInfo: Decodable, Sendable, Identifiable {
    let snapshotID: String
    let valuationDate: String
    let source: String?
    let quality: String?
    let active: Bool
    var id: String { snapshotID }

    enum CodingKeys: String, CodingKey {
        case snapshotID = "snapshot_id"
        case valuationDate = "valuation_date"
        case source, quality, active
    }
}

struct MarketCurvesResponse: Decodable, Sendable {
    let snapshotID: String
    let curves: [CurveSeries]
    enum CodingKeys: String, CodingKey {
        case snapshotID = "snapshot_id"
        case curves
    }
}

struct CurveSeries: Decodable, Sendable, Identifiable {
    let id: String
    let label: String
    let points: [CurveNode]
}

struct CurveNode: Decodable, Sendable, Identifiable {
    let tenor: Double
    let zero: Double?
    let discount: Double?
    var id: Double { tenor }
}

// MARK: - Instrument catalog (Market Data)

struct CatalogCategoriesResponse: Decodable, Sendable {
    let categories: [CatalogCategory]
}

struct CatalogCategory: Decodable, Sendable, Identifiable {
    let id: String
    let label: String
    let count: Int
}

struct CatalogResponse: Decodable, Sendable {
    let category: String
    let columns: [CatColumn]
    let rows: [CatRow]
    let boards: [String]?
}

// MARK: - Trade history (GET /history/{category}/{secid})

struct HistoryResponse: Decodable, Sendable {
    let secid: String
    let category: String
    let market: String?
    let points: [HistoryPoint]
    let error: String?
}

struct HistoryPoint: Decodable, Sendable, Identifiable {
    let date: String
    let open: Double?
    let high: Double?
    let low: Double?
    let close: Double
    let yld: Double?
    let volume: Double?
    var id: String { date }

    enum CodingKeys: String, CodingKey {
        case date, open, high, low, close, volume
        case yld = "yield"
    }
}

struct CatColumn: Decodable, Sendable, Identifiable {
    let key: String
    let label: String
    var id: String { key }
}

struct CatRow: Decodable, Sendable {
    let id: String
    let cells: [String]
    let spec: [SpecField]
}

struct SpecField: Decodable, Sendable, Identifiable {
    let label: String
    let value: String
    var id: String { label }
}

// MARK: - Historical time series (5y backfill store)

struct TSCatalog: Decodable, Sendable {
    let groups: [TSGroup]
    let count: Int
}

struct TSGroup: Decodable, Sendable, Identifiable {
    let id: String
    let label: String
    let series: [TSSeriesInfo]
}

struct TSSeriesInfo: Decodable, Sendable, Identifiable {
    let id: String          // factor_id
    let label: String
    let kind: String
    let isRate: Bool
    let points: Int
    let start: String
    let end: String

    enum CodingKeys: String, CodingKey {
        case id, label, kind, points, start, end
        case isRate = "is_rate"
    }
}

struct TSSeriesData: Decodable, Sendable {
    let factorID: String
    let label: String
    let isRate: Bool
    let unit: String
    let points: [TSPoint]
    let count: Int

    enum CodingKeys: String, CodingKey {
        case factorID = "factor_id"
        case label, unit, points, count
        case isRate = "is_rate"
    }
}

struct TSPoint: Decodable, Sendable, Identifiable {
    let date: String
    let value: Double
    var id: String { date }
}

// MARK: - Instrument-entity market data (/md/*)

struct MDListResponse: Decodable, Sendable {
    let category: String
    let instruments: [MDListItem]
    let count: Int
}

struct MDListItem: Decodable, Sendable, Identifiable {
    let secid: String
    let issuerRu: String?
    let isin: String?
    let last: Double?
    let changePct: Double?
    let asOf: String?
    let secType: String?
    let currency: String?
    let board: String?
    var id: String { secid }

    enum CodingKeys: String, CodingKey {
        case secid, isin, last, currency, board
        case issuerRu = "issuer_ru"
        case changePct = "change_pct"
        case asOf = "as_of"
        case secType = "sec_type"
    }
}

struct MDEntity: Decodable, Sendable {
    let secid: String
    let category: String?
    let issuerRu: String?
    let nameRu: String?
    let isin: String?
    let secType: String?
    let listLevel: Int?
    let currency: String?
    let board: String?
    let last: Double?
    let changePct: Double?
    let asOf: String?
    let fields: [MDField]
    let day: MDDay?
    let dividends: [MDDividend]?
    let assetCode: String?
    let chain: [MDChainContract]?
    let optionChain: [MDOptionExpiry]?

    enum CodingKeys: String, CodingKey {
        case secid, category, isin, currency, board, last, fields, day, dividends, chain
        case issuerRu = "issuer_ru"
        case nameRu = "name_ru"
        case secType = "sec_type"
        case listLevel = "list_level"
        case changePct = "change_pct"
        case asOf = "as_of"
        case assetCode = "asset_code"
        case optionChain = "option_chain"
    }
}

struct MDOptionExpiry: Decodable, Sendable, Identifiable {
    let expiry: String
    let centralStrike: Double?
    let strikes: [MDOptionStrike]
    var id: String { expiry }

    enum CodingKeys: String, CodingKey {
        case expiry, strikes
        case centralStrike = "central_strike"
    }
}

struct MDOptionStrike: Decodable, Sendable, Identifiable {
    let strike: Double
    let call: MDOptionSide?
    let put: MDOptionSide?
    var id: Double { strike }
}

struct MDOptionSide: Decodable, Sendable {
    let last: Double?
    let oi: Double?
}

// MARK: - Volatility surface (/md/volsurface)

struct VolSurfaceList: Decodable, Sendable {
    let asOf: String
    let underlyings: [VolUnderlying]
    let count: Int
    enum CodingKeys: String, CodingKey { case underlyings, count; case asOf = "as_of" }
}

struct VolUnderlying: Decodable, Sendable, Identifiable {
    let code: String
    let expiries: Int
    let points: Int
    var id: String { code }
}

struct VolSurface: Decodable, Sendable {
    let underlying: String
    let expiries: [VolExpiry]
    let deltas: [Double]
    let surface: [VolSurfaceRow]
    let diagnostics: VolDiagnostics?
}

struct VolDiagnostics: Decodable, Sendable {
    let fitModel: String?
    let nExpiries: Int?
    let nPoints: Int?
    let rmse: Double?
    enum CodingKeys: String, CodingKey {
        case rmse
        case fitModel = "fit_model"
        case nExpiries = "n_expiries"
        case nPoints = "n_points"
    }
}

struct VolExpiry: Decodable, Sendable, Identifiable {
    let expiry: String
    let t: Double?
    let forward: Double?
    let atmIv: Double?
    let sabr: VolSABR?
    let points: [VolPoint]
    let sabrCurve: [VolCurvePoint]
    var id: String { expiry }

    enum CodingKeys: String, CodingKey {
        case expiry, t, forward, points, sabr
        case atmIv = "atm_iv"
        case sabrCurve = "sabr_curve"
    }
}

struct VolSABR: Decodable, Sendable {
    let alpha: Double
    let beta: Double
    let rho: Double
    let nu: Double
}

struct VolPoint: Decodable, Sendable, Identifiable {
    let strike: Double
    let delta: Double?
    let iv: Double?
    let sabrIv: Double?
    let quote: Double?
    let fairValue: Double?
    let optType: String?
    var id: Double { strike }

    enum CodingKeys: String, CodingKey {
        case strike, delta, iv, quote
        case sabrIv = "sabr_iv"
        case fairValue = "fair_value"
        case optType = "opt_type"
    }
}

struct VolCurvePoint: Decodable, Sendable, Identifiable {
    let delta: Double
    let iv: Double
    var id: Double { delta }
}

struct VolSurfaceRow: Decodable, Sendable, Identifiable {
    let expiry: String
    let t: Double?
    let cells: [VolSurfaceCell]
    var id: String { expiry }
}

struct VolSurfaceCell: Decodable, Sendable {
    let delta: Double
    let iv: Double?
}

struct MDChainContract: Decodable, Sendable, Identifiable {
    let secid: String
    let shortname: String?
    let last: Double?
    let changePct: Double?
    let lastTradeDate: String?
    let isActive: Int?
    var id: String { secid }

    enum CodingKeys: String, CodingKey {
        case secid, shortname, last
        case changePct = "change_pct"
        case lastTradeDate = "last_trade_date"
        case isActive = "is_active"
    }
}

/// Maps a UI category to its ISS market for /md/history.
func mdMarket(_ category: String) -> String {
    switch category {
    case "equities": return "shares"
    case "bonds": return "bonds"
    case "futures", "options": return "forts"
    default: return category
    }
}

struct MDDividend: Decodable, Sendable, Identifiable {
    let registryDate: String
    let value: Double?
    let currency: String?
    var id: String { registryDate }

    enum CodingKeys: String, CodingKey {
        case value, currency
        case registryDate = "registry_date"
    }
}

/// One ISS description field; value can arrive as string/number/bool — flattened to a display string.
struct MDField: Decodable, Sendable, Identifiable {
    let name: String
    let title: String?
    let value: String?
    var id: String { name }

    enum CodingKeys: String, CodingKey { case name, title, value }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        title = try? c.decode(String.self, forKey: .title)
        if let s = try? c.decode(String.self, forKey: .value) {
            value = s
        } else if let n = try? c.decode(Double.self, forKey: .value) {
            value = n == n.rounded() ? String(Int(n)) : String(n)
        } else if let b = try? c.decode(Bool.self, forKey: .value) {
            value = b ? "1" : "0"
        } else {
            value = nil
        }
    }
}

struct MDDay: Decodable, Sendable {
    let date: String?
    let open: Double?
    let high: Double?
    let low: Double?
    let close: Double?
    let volume: Double?
    let value: Double?
    let yield: Double?
    let numtrades: Double?
}

struct MDHistory: Decodable, Sendable {
    let secid: String
    let market: String
    let range: String
    let points: [MDBar]
    let count: Int
}

struct MDBar: Decodable, Sendable, Identifiable {
    let date: String
    let open: Double?
    let high: Double?
    let low: Double?
    let close: Double
    let volume: Double?
    let yld: Double?
    var id: String { date }

    enum CodingKeys: String, CodingKey {
        case date, open, high, low, close, volume
        case yld = "yield"
    }

    private static let parser: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX"); return f
    }()
    var dateValue: Date { Self.parser.date(from: date) ?? Date() }
}

struct AuditRow: Decodable, Sendable, Identifiable {
    let timestamp: String
    let event: String
    let modelID: String
    let status: String
    let details: String
    var id: String { timestamp + event }

    enum CodingKeys: String, CodingKey {
        case timestamp, event, status, details
        case modelID = "model_id"
    }
}
