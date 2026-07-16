import SwiftUI
import Observation

/// Top-level navigation sections (mirrors the desktop workspaces).
enum AppSection: String, CaseIterable, Identifiable, Sendable {
    case dashboard, portfolio, risk, market, dataControls, pricing, pricingNew, governance, analytics

    var id: String { rawValue }

    var title: String {
        switch self {
        case .dashboard:    return "Dashboard"
        case .portfolio:    return "Portfolio"
        case .risk:         return "Risk"
        case .market:       return "Market Data"
        case .dataControls: return "Контроль данных"
        case .pricing:      return "Pricing"
        case .pricingNew:   return "Pricing_new"
        case .governance:   return "Governance"
        case .analytics:    return "Analytics Lab"
        }
    }

    var icon: String {
        switch self {
        case .dashboard:    return "square.grid.2x2.fill"
        case .portfolio:    return "briefcase.fill"
        case .risk:         return "shield.lefthalf.filled"
        case .market:       return "chart.line.uptrend.xyaxis"
        case .dataControls: return "checklist"
        case .pricing:      return "function"
        case .pricingNew:   return "rectangle.3.group.fill"
        case .governance:   return "checkmark.seal.fill"
        case .analytics:    return "flask.fill"
        }
    }

    var subtitle: String {
        switch self {
        case .dashboard:    return "Daily risk control tower"
        case .portfolio:    return "Positions, exposures & P&L"
        case .risk:         return "VaR, stress & decomposition"
        case .market:       return "Live MOEX curves & quotes"
        case .dataControls: return "Качество и загрузка данных"
        case .pricing:      return "Instrument valuation"
        case .pricingNew:   return "Multi-instrument pricing worksheet"
        case .governance:   return "Quant definitions, solvers & engine publication"
        case .analytics:    return "Scenarios & what-if"
        }
    }
}

/// Generic async-loadable state.
enum Loadable<T> {
    case idle
    case loading
    case loaded(T)
    case failed(String)

    var value: T? {
        if case .loaded(let v) = self { return v }
        return nil
    }

    var isLoading: Bool {
        if case .loading = self { return true }
        return false
    }
}

struct HealthInfo: Decodable, Sendable {
    let status: String
    let service: String
    let version: String
    let live: Bool
    let snapshotID: String

    enum CodingKeys: String, CodingKey {
        case status, service, version, live
        case snapshotID = "snapshot_id"
    }
}

struct IngestStatus: Decodable, Sendable {
    let status: String
    let message: String
    let snapshotID: String?

    enum CodingKeys: String, CodingKey {
        case status, message
        case snapshotID = "snapshot_id"
    }
}

/// A request to open a specific instrument in Market Data (from global search).
struct OpenInstrumentRequest: Equatable, Identifiable {
    let id = UUID()
    let category: String
    let secid: String
}

@MainActor
@Observable
final class AppModel {
    var section: AppSection = .dashboard

    var health: HealthInfo?
    var serverDown = false

    var ingestRunning = false
    var ingestMessage = ""

    var dashboard: Loadable<DashboardData> = .idle
    var market: Loadable<MarketData> = .idle
    var portfolio: Loadable<PortfolioData> = .idle
    var risk: Loadable<RiskData> = .idle
    var governance: Loadable<GovernanceData> = .idle
    var analytics: Loadable<AnalyticsData> = .idle

    // Global search (toolbar command palette)
    var searchText = ""
    var searchHits: [SearchHit] = []
    @ObservationIgnored private var searchTask: Task<Void, Never>?
    /// Set when a search hit / recent is chosen — Market Data opens it.
    var openRequest: OpenInstrumentRequest?

    private let client = BridgeClient()

    /// Debounced global instrument search (ticker · ISIN · issuer).
    func runSearch(_ q: String) {
        searchTask?.cancel()
        let query = q.trimmingCharacters(in: .whitespaces)
        guard query.count >= 2 else { searchHits = []; return }
        searchTask = Task {
            try? await Task.sleep(for: .milliseconds(250))
            guard !Task.isCancelled else { return }
            let hits = (try? await client.mdSearch(query))?.results ?? []
            guard !Task.isCancelled, searchText.trimmingCharacters(in: .whitespaces) == query else { return }
            searchHits = hits
        }
    }

    /// Route to Market Data → Instruments and open the given instrument.
    func requestOpen(category: String, secid: String) {
        openRequest = OpenInstrumentRequest(category: category, secid: secid)
        section = .market
    }

    func start() async {
        await loadHealth()
        await load(section)
    }

    func loadHealth() async {
        do {
            health = try await client.get("health", as: HealthInfo.self)
            serverDown = false
        } catch {
            serverDown = true
        }
    }

    func refresh() async {
        await loadHealth()
        await load(section, force: true)
    }

    /// Trigger a full MOEX+CBR ingest for today and poll until it finishes,
    /// then reload everything onto the fresh snapshot.
    func startIngest() async {
        guard !ingestRunning else { return }
        ingestRunning = true
        ingestMessage = "starting…"
        do {
            _ = try await client.startIngest()
            while true {
                try? await Task.sleep(for: .seconds(3))
                let status = try await client.ingestStatus()
                ingestMessage = status.message
                if status.status != "running" { break }
            }
        } catch {
            ingestMessage = error.localizedDescription
        }
        ingestRunning = false
        // clear cached section data so it reloads on the new snapshot
        dashboard = .idle; market = .idle; portfolio = .idle
        risk = .idle; governance = .idle; analytics = .idle
        await refresh()
    }

    func load(_ section: AppSection, force: Bool = false) async {
        if serverDown { await loadHealth() }
        switch section {
        case .dashboard:
            if force || dashboard.value == nil { await loadDashboard() }
        case .market:
            if force || market.value == nil { await loadMarket() }
        case .portfolio:
            if force || portfolio.value == nil { await loadPortfolio() }
        case .risk:
            if force || risk.value == nil { await loadRisk() }
        case .governance:
            if force || governance.value == nil { await loadGovernance() }
        case .analytics:
            if force || analytics.value == nil { await loadAnalytics() }
        case .pricing, .pricingNew:
            break   // Pricing workspaces manage their own state
        case .dataControls:
            break   // DataControlsScreen manages its own state
        }
    }

    private func loadDashboard() async {
        dashboard = .loading
        do { dashboard = .loaded(try await client.dashboard()) }
        catch { dashboard = .failed(error.localizedDescription) }
    }

    private func loadMarket() async {
        market = .loading
        do { market = .loaded(try await client.market()) }
        catch { market = .failed(error.localizedDescription) }
    }

    private func loadPortfolio() async {
        portfolio = .loading
        do { portfolio = .loaded(try await client.portfolio()) }
        catch { portfolio = .failed(error.localizedDescription) }
    }

    private func loadRisk() async {
        risk = .loading
        do { risk = .loaded(try await client.risk()) }
        catch { risk = .failed(error.localizedDescription) }
    }

    private func loadGovernance() async {
        governance = .loading
        do { governance = .loaded(try await client.governance()) }
        catch { governance = .failed(error.localizedDescription) }
    }

    private func loadAnalytics() async {
        analytics = .loading
        do { analytics = .loaded(try await client.analytics()) }
        catch { analytics = .failed(error.localizedDescription) }
    }
}
