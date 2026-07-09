import SwiftUI
import Charts
import Observation

// MARK: - Models (GET /pnl/explain)

struct PXEffect: Decodable, Sendable, Identifiable, Hashable {
    let key: String
    let label: String
    let value: Double
    var id: String { key }
}

struct PXFactor: Decodable, Sendable, Hashable {
    let factor: String
    let pnl: Double
}

struct PXPosition: Decodable, Sendable, Hashable {
    let position: String
    let pnl: Double
}

struct PXMoves: Decodable, Sendable {
    let equity: Double
    let ratesBp: Double
    let volPts: Double
    let fx: Double

    enum CodingKeys: String, CodingKey {
        case equity, fx
        case ratesBp = "rates_bp"
        case volPts = "vol_pts"
    }
}

struct PnlExplain: Decodable, Sendable {
    let asOf: String
    let moves: PXMoves
    let totalPnl: Double
    let explained: Double
    let residual: Double
    let effects: [PXEffect]
    let byFactor: [PXFactor]
    let byPosition: [PXPosition]
    let note: String
    let warnings: [String]

    enum CodingKeys: String, CodingKey {
        case moves, effects, note, warnings, explained, residual
        case asOf = "as_of"
        case totalPnl = "total_pnl"
        case byFactor = "by_factor"
        case byPosition = "by_position"
    }
}

extension BridgeClient {
    func pnlExplain() async throws -> PnlExplain { try await get("pnl/explain") }
}

// MARK: - Pane

/// P&L Explained (Calypso §2.4): the latest day's actual factor moves, the
/// full-reprice total, greek-attributed market-data/time effects, residual.
struct PnlExplainPane: View {
    @State private var data: PnlExplain?
    @State private var isLoading = false
    @State private var errorMessage: String?
    private let client = BridgeClient()

    var body: some View {
        ScreenScaffold {
            PageHeader("P&L Explain",
                       subtitle: "market data effect · time effect · residual")
            if let message = errorMessage {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.negative)
            }
            if let d = data {
                content(d)
            } else if isLoading {
                SkeletonScreen()
            }
        }
        .task { await load() }
    }

    private func load() async {
        isLoading = true
        errorMessage = nil
        do {
            data = try await client.pnlExplain()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    @ViewBuilder
    private func content(_ d: PnlExplain) -> some View {
        KPIStrip(items: [
            KPICard(label: "Total P&L (\(d.asOf))", value: Fmt.money(d.totalPnl),
                    sub: "full reprice", accent: Theme.trendColor(d.totalPnl),
                    icon: "sum"),
            KPICard(label: "Explained", value: Fmt.money(d.explained),
                    sub: "greek attribution", accent: Theme.accent,
                    icon: "checkmark.circle"),
            KPICard(label: "Residual", value: Fmt.money(d.residual),
                    sub: "nonlinear + FX + cross", accent: Theme.warning,
                    icon: "questionmark.circle"),
            KPICard(label: "IMOEX", value: Fmt.signedPercent(d.moves.equity * 100),
                    sub: "equity move", accent: Theme.bucketColor("Equity"),
                    icon: "chart.line.uptrend.xyaxis"),
            KPICard(label: "КБД 5Y", value: String(format: "%+.1f bp", d.moves.ratesBp),
                    sub: "rate move", accent: Theme.bucketColor("Rates"),
                    icon: "percent"),
        ])

        HStack(alignment: .top, spacing: Theme.s4) {
            waterfallCard(d)
            positionsCard(d)
        }
        if !d.note.isEmpty {
            Label(d.note, systemImage: "info.circle")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private func waterfallCard(_ d: PnlExplain) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("P&L attribution", icon: "chart.bar.doc.horizontal")
                let rows = d.effects + [PXEffect(key: "residual", label: "Residual",
                                                 value: d.residual)]
                Chart(rows) { e in
                    BarMark(x: .value("P&L", e.value), y: .value("Effect", e.label))
                        .foregroundStyle(e.key == "residual"
                                         ? Theme.warning.gradient
                                         : Theme.trendColor(e.value).gradient)
                        .annotation(position: .trailing) {
                            Text(Fmt.money(e.value))
                                .font(.system(size: 9)).monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                }
                .chartXAxis(.hidden)
                .frame(height: CGFloat(rows.count) * 34 + 16)
                Text("Дневное движение факторов через гриэки книги; time effect = theta за 1 день.")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
    }

    private func positionsCard(_ d: PnlExplain) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("By position", icon: "list.bullet.indent")
                let rows = d.byPosition.sorted { abs($0.pnl) > abs($1.pnl) }
                ForEach(rows.prefix(10), id: \.position) { p in
                    HStack {
                        Text(p.position).font(.system(size: 11)).lineLimit(1)
                        Spacer()
                        Text(Fmt.money(p.pnl))
                            .font(.system(size: 11, weight: .semibold)).monospacedDigit()
                            .foregroundStyle(Theme.trendColor(p.pnl))
                    }
                    .padding(.vertical, 2)
                }
                if !d.byFactor.isEmpty {
                    Divider()
                    Text("BY FACTOR").font(.system(size: 9, weight: .semibold))
                        .tracking(0.5).foregroundStyle(.tertiary)
                    ForEach(d.byFactor.sorted { abs($0.pnl) > abs($1.pnl) }.prefix(6),
                            id: \.factor) { f in
                        HStack {
                            Text(f.factor).font(.system(size: 10)).foregroundStyle(.secondary)
                            Spacer()
                            Text(Fmt.money(f.pnl))
                                .font(.system(size: 10)).monospacedDigit()
                                .foregroundStyle(Theme.trendColor(f.pnl))
                        }
                    }
                }
            }
        }
        .frame(width: 320)
    }
}
