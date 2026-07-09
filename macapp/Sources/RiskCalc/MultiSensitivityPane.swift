import SwiftUI
import Charts
import Observation

// MARK: - Models (GET /desk/multisensitivity)

struct MSPosition: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let instrument: String
    let description: String
    let quantity: Double
    let marketValue: Double
    let delta: Double
    let gamma: Double
    let vega: Double
    let theta: Double
    let rho: Double
    let dv01: Double
    let cs01: Double
    let fxDelta: Double

    enum CodingKeys: String, CodingKey {
        case id, instrument, description, quantity, delta, gamma, vega, theta, rho, dv01, cs01
        case marketValue = "market_value"
        case fxDelta = "fx_delta"
    }
}

struct MSBump: Decodable, Sendable, Identifiable, Hashable {
    let factor: String
    let label: String
    let note: String
    let pnlUp: Double
    let pnlDown: Double
    let linear: Double
    let convexity: Double
    var id: String { factor }

    enum CodingKeys: String, CodingKey {
        case factor, label, note, linear, convexity
        case pnlUp = "pnl_up"
        case pnlDown = "pnl_down"
    }
}

struct MultiSensitivity: Decodable, Sendable {
    let positions: [MSPosition]
    let totals: [String: Double]
    let buckets: [String: [String: Double]]
    let bumps: [MSBump]
    let marketValue: Double
    let nPositions: Int
    let note: String
    let warnings: [String]

    enum CodingKeys: String, CodingKey {
        case positions, totals, buckets, bumps, note, warnings
        case marketValue = "market_value"
        case nPositions = "n_positions"
    }
}

extension BridgeClient {
    func multiSensitivity() async throws -> MultiSensitivity {
        try await get("desk/multisensitivity")
    }
}

// MARK: - Pane

/// MultiSensitivity (Calypso §2.2): все чувствительности книги в одном
/// отчёте — greek-слой по позициям + full-reprice бампы с асимметрией.
struct MultiSensitivityPane: View {
    @State private var data: MultiSensitivity?
    @State private var isLoading = false
    @State private var errorMessage: String?
    private let client = BridgeClient()

    var body: some View {
        ScreenScaffold {
            PageHeader("Sensitivities",
                       subtitle: "MultiSensitivity · greeks + full-reprice bumps")
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
            data = try await client.multiSensitivity()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    @ViewBuilder
    private func content(_ d: MultiSensitivity) -> some View {
        KPIStrip(items: d.bumps.map { b in
            KPICard(label: b.label, value: Fmt.money(b.linear),
                    sub: "convexity \(Fmt.money(b.convexity))",
                    accent: bucketColor(b.factor), icon: icon(b.factor))
        } + [
            KPICard(label: "Market value", value: Fmt.money(d.marketValue),
                    sub: "\(d.nPositions) positions", accent: Theme.accent,
                    icon: "briefcase.fill"),
        ])

        HStack(alignment: .top, spacing: Theme.s4) {
            bumpsCard(d)
            bucketsCard(d)
        }
        greeksTable(d)
        Label(d.note, systemImage: "info.circle")
            .font(.system(size: 10)).foregroundStyle(.tertiary)
    }

    private func bumpsCard(_ d: MultiSensitivity) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Full-reprice bumps (up / down)", icon: "arrow.up.arrow.down")
                Chart {
                    ForEach(d.bumps) { b in
                        BarMark(x: .value("P&L", b.pnlUp),
                                y: .value("Factor", b.label))
                            .foregroundStyle(Theme.positive.opacity(0.75))
                            .position(by: .value("dir", "up"))
                        BarMark(x: .value("P&L", b.pnlDown),
                                y: .value("Factor", b.label))
                            .foregroundStyle(Theme.negative.opacity(0.75))
                            .position(by: .value("dir", "down"))
                    }
                    RuleMark(x: .value("zero", 0))
                        .foregroundStyle(.tertiary)
                        .lineStyle(StrokeStyle(lineWidth: 0.5))
                }
                .frame(height: 190)
                Text("Полная переоценка книги на ±бампе; несимметричные бары = гамма/выпуклость.")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
    }

    private func bucketsCard(_ d: MultiSensitivity) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Exposure buckets", icon: "square.stack.3d.up")
                ForEach(d.buckets.sorted(by: { $0.key < $1.key }), id: \.key) { name, metrics in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: Theme.s2) {
                            Circle().fill(Theme.bucketColor(name)).frame(width: 7, height: 7)
                            Text(name).font(.system(size: 12, weight: .semibold))
                        }
                        ForEach(metrics.sorted(by: { abs($0.value) > abs($1.value) }),
                                id: \.key) { unit, value in
                            KeyValueRow(key: unit, value: Fmt.money(value))
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
        }
        .frame(width: 300)
    }

    private func greeksTable(_ d: MultiSensitivity) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Positions × sensitivities", icon: "tablecells")
                Table(d.positions) {
                    TableColumn("Position") { p in
                        Text(p.description).font(.system(size: 11)).lineLimit(1)
                    }
                    TableColumn("MV") { p in num(p.marketValue) }
                    TableColumn("Delta") { p in num(p.delta) }
                    TableColumn("Gamma") { p in num(p.gamma) }
                    TableColumn("Vega") { p in num(p.vega) }
                    TableColumn("Theta") { p in num(p.theta) }
                    TableColumn("Rho") { p in num(p.rho) }
                    TableColumn("DV01") { p in num(p.dv01) }
                    TableColumn("FX Δ") { p in num(p.fxDelta) }
                }
                .frame(height: min(CGFloat(max(1, d.positions.count)), 12) * 28 + 36)
                totalsRow(d)
            }
        }
    }

    private func totalsRow(_ d: MultiSensitivity) -> some View {
        HStack(spacing: Theme.s4) {
            Text("Σ").font(.system(size: 11, weight: .bold))
            ForEach(["delta", "gamma", "vega", "theta", "rho", "dv01", "fx_delta"],
                    id: \.self) { key in
                if let v = d.totals[key], abs(v) > 1e-9 {
                    Text("\(key): \(Fmt.money(v))")
                        .font(.system(size: 10, weight: .semibold)).monospacedDigit()
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
        }
    }

    private func num(_ value: Double) -> some View {
        Text(abs(value) > 1e-9 ? Fmt.number(value, digits: 1) : "—")
            .font(.system(size: 10)).monospacedDigit()
    }

    private func bucketColor(_ factor: String) -> Color {
        switch factor {
        case "equity": return Theme.bucketColor("Equity")
        case "rates": return Theme.bucketColor("Rates")
        case "vol": return Theme.bucketColor("Volatility")
        default: return Theme.bucketColor("FX")
        }
    }

    private func icon(_ factor: String) -> String {
        switch factor {
        case "equity": return "chart.line.uptrend.xyaxis"
        case "rates": return "percent"
        case "vol": return "waveform"
        default: return "dollarsign.circle"
        }
    }
}
