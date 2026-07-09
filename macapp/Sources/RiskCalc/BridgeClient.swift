import Foundation

enum BridgeError: LocalizedError {
    case badStatus(Int, String)
    case server(String)

    var errorDescription: String? {
        switch self {
        case .badStatus(let code, let body):
            return body.isEmpty ? "Server returned \(code)" : detail(from: body) ?? "Server \(code)"
        case .server(let message):
            return message
        }
    }

    private func detail(from body: String) -> String? {
        guard let data = body.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let d = obj["detail"] as? String else { return body }
        return d
    }
}

/// A request param value that encodes as a bare number or string (matching the
/// bridge's `dict[str, float | int | str]`).
struct BridgeValue: Encodable, Sendable {
    enum Kind: Sendable { case number(Double), string(String) }
    let kind: Kind

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch kind {
        case .number(let d): try c.encode(d)
        case .string(let s): try c.encode(s)
        }
    }
}

private struct PriceRequestBody: Encodable {
    let pricer: String
    let params: [String: BridgeValue]
}

private struct InstrumentRequestBody: Encodable {
    let instrument: String
    let params: [String: BridgeValue]
}

struct BondBatchRow: Encodable, Sendable {
    let instrument: String
    let params: [String: BridgeValue]
    let quantity: Double
}

private struct BatchBody: Encodable {
    let bonds: [BondBatchRow]
}

private struct RepriceBody: Encodable {
    let secid: String
    let curve_id: String
    let shift_bps: Double
    let forecast_curve_id: String
    let float_spread_bps: Double
}

/// Thin async client for the RiskCalc FastAPI bridge.
actor BridgeClient {
    private let base: URL
    private let session: URLSession

    init(base: URL = URL(string: "http://127.0.0.1:8765")!) {
        self.base = base
        // Live market data — never serve a stale cached response.
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        config.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        self.session = URLSession(configuration: config)
    }

    /// Generic typed GET against a bridge path.
    func get<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        let (data, response) = try await session.data(from: base.appending(path: path))
        try Self.check(response, data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    func catalogue() async throws -> [Pricer] {
        try await get("catalogue", as: Catalogue.self).pricers
    }

    func dashboard() async throws -> DashboardData { try await get("dashboard") }

    func catalogCategories() async throws -> [CatalogCategory] {
        try await get("catalog/categories", as: CatalogCategoriesResponse.self).categories
    }

    func snapshots() async throws -> SnapshotsResponse { try await get("snapshots") }

    func marketCurves(snapshotID: String?) async throws -> MarketCurvesResponse {
        var comps = URLComponents(url: base.appending(path: "marketcurves"), resolvingAgainstBaseURL: false)!
        if let snapshotID, !snapshotID.isEmpty { comps.queryItems = [URLQueryItem(name: "snapshot_id", value: snapshotID)] }
        let (data, response) = try await session.data(from: comps.url!)
        try Self.check(response, data)
        return try JSONDecoder().decode(MarketCurvesResponse.self, from: data)
    }

    func catalogCategories(snapshotID: String?) async throws -> [CatalogCategory] {
        var comps = URLComponents(url: base.appending(path: "catalog/categories"), resolvingAgainstBaseURL: false)!
        if let snapshotID, !snapshotID.isEmpty { comps.queryItems = [URLQueryItem(name: "snapshot_id", value: snapshotID)] }
        let (data, response) = try await session.data(from: comps.url!)
        try Self.check(response, data)
        return try JSONDecoder().decode(CatalogCategoriesResponse.self, from: data).categories
    }

    func catalog(_ category: String, search: String?, board: String? = nil,
                 sort: String? = nil, desc: Bool = false, snapshotID: String? = nil) async throws -> CatalogResponse {
        var comps = URLComponents(url: base.appending(path: "catalog/\(category)"), resolvingAgainstBaseURL: false)!
        var items = [URLQueryItem(name: "limit", value: "1000")]
        if let search, !search.isEmpty { items.append(URLQueryItem(name: "search", value: search)) }
        if let board, !board.isEmpty { items.append(URLQueryItem(name: "board", value: board)) }
        if let sort, !sort.isEmpty {
            items.append(URLQueryItem(name: "sort", value: sort))
            items.append(URLQueryItem(name: "desc", value: desc ? "true" : "false"))
        }
        if let snapshotID, !snapshotID.isEmpty { items.append(URLQueryItem(name: "snapshot_id", value: snapshotID)) }
        comps.queryItems = items
        let (data, response) = try await session.data(from: comps.url!)
        try Self.check(response, data)
        return try JSONDecoder().decode(CatalogResponse.self, from: data)
    }

    func history(category: String, secid: String, days: Int = 180) async throws -> HistoryResponse {
        var comps = URLComponents(url: base.appending(path: "history/\(category)/\(secid)"),
                                  resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "days", value: "\(days)")]
        let (data, response) = try await session.data(from: comps.url!)
        try Self.check(response, data)
        return try JSONDecoder().decode(HistoryResponse.self, from: data)
    }
    func timeseriesCatalog() async throws -> TSCatalog { try await get("timeseries/catalog") }

    func timeseries(factorID: String, frm: String? = nil, till: String? = nil) async throws -> TSSeriesData {
        var comps = URLComponents(url: base.appending(path: "timeseries"), resolvingAgainstBaseURL: false)!
        var items = [URLQueryItem(name: "factor_id", value: factorID)]
        if let frm, !frm.isEmpty { items.append(URLQueryItem(name: "frm", value: frm)) }
        if let till, !till.isEmpty { items.append(URLQueryItem(name: "till", value: till)) }
        comps.queryItems = items
        let (data, response) = try await session.data(from: comps.url!)
        try Self.check(response, data)
        return try JSONDecoder().decode(TSSeriesData.self, from: data)
    }

    func mdOverview() async throws -> MDOverview { try await get("md/overview") }

    func mdSearch(_ q: String) async throws -> SearchResults {
        var comps = URLComponents(url: base.appending(path: "md/search"), resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "q", value: q)]
        let (data, response) = try await session.data(from: comps.url!)
        try Self.check(response, data)
        return try JSONDecoder().decode(SearchResults.self, from: data)
    }

    func refData() async throws -> RefData { try await get("md/refdata") }

    func mdList(category: String) async throws -> MDListResponse {
        try await get("md/list/\(category)")
    }

    func mdInstrument(category: String, secid: String) async throws -> MDEntity {
        try await get("md/instrument/\(category)/\(secid)")
    }

    func mdHistory(secid: String, market: String, range: String,
                   interval: String = "1d", mode: String = "price") async throws -> MDHistory {
        var comps = URLComponents(url: base.appending(path: "md/history/\(secid)"), resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "market", value: market),
                            URLQueryItem(name: "range", value: range),
                            URLQueryItem(name: "interval", value: interval),
                            URLQueryItem(name: "mode", value: mode)]
        let (data, response) = try await session.data(from: comps.url!)
        try Self.check(response, data)
        return try JSONDecoder().decode(MDHistory.self, from: data)
    }

    func mdLive(category: String) async throws -> MDLiveResponse { try await get("md/live/\(category)") }

    func dataHealth() async throws -> DataHealth { try await get("md/health") }
    func validation() async throws -> ValidationData { try await get("md/validation") }

    func rawTables() async throws -> RawTableList { try await get("md/raw/tables") }
    func dataDictionary() async throws -> DataDictionary { try await get("md/raw/dictionary") }

    func rawTable(_ name: String, limit: Int = 200) async throws -> RawTable {
        var comps = URLComponents(url: base.appending(path: "md/raw/\(name)"), resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "limit", value: "\(limit)")]
        let (data, response) = try await session.data(from: comps.url!)
        try Self.check(response, data)
        return try JSONDecoder().decode(RawTable.self, from: data)
    }

    /// Live intraday candles from MOEX ISS (interval: 1 / 10 / 60 minutes).
    func mdCandles(secid: String, market: String, interval: Int) async throws -> MDHistory {
        var comps = URLComponents(url: base.appending(path: "md/candles/\(secid)"), resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "market", value: market),
                            URLQueryItem(name: "interval", value: "\(interval)")]
        let (data, response) = try await session.data(from: comps.url!)
        try Self.check(response, data)
        return try JSONDecoder().decode(MDHistory.self, from: data)
    }

    func volSurfaceList() async throws -> VolSurfaceList { try await get("md/volsurface") }

    func volSurface(underlying: String) async throws -> VolSurface {
        try await get("md/volsurface/\(underlying)")
    }

    func otcSurface(underlying: String) async throws -> OTCSurface {
        try await get("md/volsurface/\(underlying)/otc")
    }

    /// Rendered 3-axis surface chart (matplotlib mplot3d) as PNG bytes.
    func volSurfacePlot(underlying: String) async throws -> Data {
        let (data, response) = try await session.data(from: base.appending(path: "md/volsurface/\(underlying)/plot"))
        try Self.check(response, data)
        return data
    }

    func market() async throws -> MarketData { try await get("market") }
    func portfolio() async throws -> PortfolioData { try await get("portfolio") }
    func risk() async throws -> RiskData { try await get("risk") }
    func governance() async throws -> GovernanceData { try await get("governance") }
    func analytics() async throws -> AnalyticsData { try await get("analytics") }

    func startIngest() async throws -> IngestStatus { try await post("ingest/refresh", body: Data("{}".utf8)) }
    func ingestStatus() async throws -> IngestStatus { try await get("ingest/status") }

    func price(pricer: String, params: [String: BridgeValue]) async throws -> PriceResult {
        let body = try JSONEncoder().encode(PriceRequestBody(pricer: pricer, params: params))
        return try await post("price", body: body)
    }

    func bondCatalogue() async throws -> BondCatalogue { try await get("instruments/bond") }

    func curves() async throws -> [CurveData] { try await get("curves", as: CurvesResponse.self).curves }

    func realBonds(board: String?, search: String?, limit: Int = 300) async throws -> RealBondList {
        var comps = URLComponents(url: base.appending(path: "realbonds"), resolvingAgainstBaseURL: false)!
        var items = [URLQueryItem(name: "limit", value: "\(limit)")]
        if let board, !board.isEmpty { items.append(URLQueryItem(name: "board", value: board)) }
        if let search, !search.isEmpty { items.append(URLQueryItem(name: "search", value: search)) }
        comps.queryItems = items
        let (data, response) = try await session.data(from: comps.url!)
        try Self.check(response, data)
        return try JSONDecoder().decode(RealBondList.self, from: data)
    }

    func reprice(secid: String, curveID: String, shiftBps: Double,
                 forecastCurveID: String, floatSpreadBps: Double) async throws -> RepriceResult {
        let body = try JSONEncoder().encode(RepriceBody(
            secid: secid, curve_id: curveID, shift_bps: shiftBps,
            forecast_curve_id: forecastCurveID, float_spread_bps: floatSpreadBps))
        return try await post("realbonds/reprice", body: body)
    }

    func priceBond(instrument: String, params: [String: BridgeValue]) async throws -> BondResult {
        let body = try JSONEncoder().encode(InstrumentRequestBody(instrument: instrument, params: params))
        return try await post("instruments/bond/price", body: body)
    }

    func priceBatch(_ rows: [BondBatchRow]) async throws -> BatchResponse {
        let body = try JSONEncoder().encode(BatchBody(bonds: rows))
        return try await post("instruments/bond/price_batch", body: body)
    }

    func post<T: Decodable>(_ path: String, body: Data) async throws -> T {
        var request = URLRequest(url: base.appending(path: path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        let (data, response) = try await session.data(for: request)
        try Self.check(response, data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    func delete(_ path: String) async throws {
        var request = URLRequest(url: base.appending(path: path))
        request.httpMethod = "DELETE"
        let (data, response) = try await session.data(for: request)
        try Self.check(response, data)
    }

    private static func check(_ response: URLResponse, _ data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            throw BridgeError.badStatus(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
    }
}
