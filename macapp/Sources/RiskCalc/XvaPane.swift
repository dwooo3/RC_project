import SwiftUI
import Charts
import Observation

// MARK: - Models (POST /xva)

struct XvaMetric: Decodable, Sendable, Identifiable, Hashable {
    let key: String
    let label: String
    let value: Double
    var id: String { key }
}

struct XvaProfile: Decodable, Sendable {
    let times: [Double]
    let epe: [Double]
    let ene: [Double]
    let pfe95: [Double]
    let pfe99: [Double]
    let epeUncollateralised: [Double]
    let im: [Double]

    enum CodingKeys: String, CodingKey {
        case times, epe, ene, pfe95, pfe99, im
        case epeUncollateralised = "epe_uncollateralised"
    }
}

struct XvaTrade: Decodable, Sendable, Hashable {
    let notional: Double
    let fixedRate: Double
    let T: Double
    let payFixed: Bool
    let source: String

    enum CodingKeys: String, CodingKey {
        case notional, T, source
        case fixedRate = "fixed_rate"
        case payFixed = "pay_fixed"
    }
}

struct XvaResult: Decodable, Sendable {
    let value: Double?
    let errors: [String]
    let warnings: [String]
    let modelStatus: String
    let metrics: [XvaMetric]
    let peakEpe: Double
    let peakIm: Double
    let collateralised: Bool
    let profile: XvaProfile?
    let trades: [XvaTrade]
    let nettingSource: String
    let curveID: String
    let cptyNote: String
    let ownNote: String

    enum CodingKeys: String, CodingKey {
        case value, errors, warnings, metrics, collateralised, profile, trades
        case modelStatus = "model_status"
        case peakEpe = "peak_epe"
        case peakIm = "peak_im"
        case nettingSource = "netting_source"
        case curveID = "curve_id"
        case cptyNote = "cpty_note"
        case ownNote = "own_note"
    }
}

private struct XvaBody: Encodable {
    let cpty_issuer: String
    let cpty_spread_bps: Double
    let own_spread_bps: Double
    let funding_spread_bps: Double
    let cost_of_capital: Double
    let csa_enabled: Bool
    let threshold: Double
    let mta: Double
    let n_sims: Int
    let use_book: Bool
}

extension BridgeClient {
    func runXva(issuer: String, cptySpreadBps: Double, ownSpreadBps: Double,
                fundingSpreadBps: Double, costOfCapital: Double,
                csaEnabled: Bool, threshold: Double, mta: Double,
                nSims: Int) async throws -> XvaResult {
        let body = try JSONEncoder().encode(XvaBody(
            cpty_issuer: issuer, cpty_spread_bps: cptySpreadBps,
            own_spread_bps: ownSpreadBps, funding_spread_bps: fundingSpreadBps,
            cost_of_capital: costOfCapital, csa_enabled: csaEnabled,
            threshold: threshold, mta: mta, n_sims: nSims, use_book: true))
        return try await post("xva", body: body)
    }
}

// MARK: - View model

@MainActor
@Observable
final class XvaViewModel {
    var issuer = ""
    var cptySpreadBps: Double = 200
    var ownSpreadBps: Double = 0
    var fundingSpreadBps: Double = 100
    var costOfCapital: Double = 0.10
    var csaEnabled = false
    var threshold: Double = 0
    var mta: Double = 0
    var nSims: Double = 4000

    var result: XvaResult?
    var isRunning = false
    var errorMessage: String?

    private let client = BridgeClient()

    func run() async {
        isRunning = true
        errorMessage = nil
        do {
            result = try await client.runXva(
                issuer: issuer, cptySpreadBps: cptySpreadBps,
                ownSpreadBps: ownSpreadBps, fundingSpreadBps: fundingSpreadBps,
                costOfCapital: costOfCapital, csaEnabled: csaEnabled,
                threshold: threshold, mta: mta, nSims: Int(nSims))
            if let first = result?.errors.first { errorMessage = first }
        } catch {
            errorMessage = error.localizedDescription
        }
        isRunning = false
    }
}

// MARK: - Pane

/// XVA workstation (Calypso §2.5): CVA/DVA/FVA/MVA/KVA on the book's IRS
/// netting set, counterparty hazard from issuer z-spreads, two-way CSA.
struct XvaPane: View {
    @State private var vm = XvaViewModel()

    var body: some View {
        ScreenScaffold {
            PageHeader("XVA", subtitle: "netting set · CSA · CVA / DVA / FVA / MVA / KVA")
            controls
            if let message = vm.errorMessage {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.negative)
            }
            if let r = vm.result {
                content(r)
            } else if vm.isRunning {
                SkeletonScreen()
            } else {
                GlassCard {
                    VStack(spacing: Theme.s3) {
                        Image(systemName: "arrow.triangle.branch")
                            .font(.system(size: 32)).foregroundStyle(.tertiary)
                        Text("Неттинг-сет — IRS-позиции текущей книги (Hull-White MtM-куб). Контрагент: эмитент (hazard из z-спредов) или флэт-спред.")
                            .font(.caption).foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                        Button("Рассчитать XVA") { Task { await vm.run() } }
                            .buttonStyle(.borderedProminent)
                    }
                    .frame(maxWidth: .infinity, minHeight: 180)
                }
            }
        }
        .task { if vm.result == nil { await vm.run() } }
    }

    private var controls: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack(spacing: Theme.s3) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Контрагент (эмитент)").font(.system(size: 10)).foregroundStyle(.secondary)
                        TextField("пусто = флэт-спред", text: $vm.issuer)
                            .textFieldStyle(.roundedBorder).frame(width: 180)
                    }
                    numField("Флэт-спред, bp", $vm.cptySpreadBps, width: 90)
                    numField("Funding, bp", $vm.fundingSpreadBps, width: 80)
                    numField("Cost of capital", $vm.costOfCapital, width: 80)
                    numField("MC paths", $vm.nSims, width: 80)
                    Spacer()
                    Button {
                        Task { await vm.run() }
                    } label: {
                        if vm.isRunning {
                            ProgressView().controlSize(.small)
                        } else {
                            Label("Run", systemImage: "play.fill")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(vm.isRunning)
                }
                HStack(spacing: Theme.s3) {
                    Toggle("CSA (variation margin)", isOn: $vm.csaEnabled)
                        .toggleStyle(.checkbox).font(.system(size: 11))
                    if vm.csaEnabled {
                        numField("Threshold", $vm.threshold, width: 100)
                        numField("MTA", $vm.mta, width: 90)
                    }
                    Spacer()
                }
            }
        }
    }

    private func numField(_ label: String, _ value: Binding<Double>,
                          width: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 10)).foregroundStyle(.secondary)
            TextField("", value: value, format: .number)
                .textFieldStyle(.roundedBorder).frame(width: width).monospacedDigit()
        }
    }

    @ViewBuilder
    private func content(_ r: XvaResult) -> some View {
        let m = Dictionary(uniqueKeysWithValues: r.metrics.map { ($0.key, $0.value) })
        KPIStrip(items: [
            KPICard(label: "Total XVA", value: Fmt.money(m["total_xva"] ?? 0),
                    sub: r.collateralised ? "с CSA" : "без CSA",
                    accent: Theme.negative, icon: "sum"),
            KPICard(label: "CVA", value: Fmt.money(m["cva"] ?? 0),
                    sub: "counterparty", accent: Theme.warning, icon: "person.crop.circle.badge.exclamationmark"),
            KPICard(label: "FVA", value: Fmt.money(m["fva"] ?? 0),
                    sub: "funding", accent: Theme.bucketColor("Rates"), icon: "banknote"),
            KPICard(label: "KVA", value: Fmt.money(m["kva"] ?? 0),
                    sub: "capital", accent: Theme.bucketColor("Credit"), icon: "building.columns"),
            KPICard(label: "Peak EPE", value: Fmt.money(r.peakEpe),
                    sub: "\(r.trades.count) trades · \(r.nettingSource)",
                    accent: Theme.accent, icon: "chart.line.uptrend.xyaxis"),
        ])
        Label(r.cptyNote, systemImage: "person.text.rectangle")
            .font(.caption).foregroundStyle(.secondary)
        HStack(alignment: .top, spacing: Theme.s4) {
            profileCard(r)
            metricsCard(r)
        }
    }

    @ViewBuilder
    private func profileCard(_ r: XvaResult) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Exposure profile", icon: "chart.xyaxis.line")
                if let p = r.profile {
                    Chart {
                        ForEach(Array(p.times.enumerated()), id: \.offset) { i, t in
                            LineMark(x: .value("T", t), y: .value("PFE 99", p.pfe99[i]),
                                     series: .value("s", "PFE 99%"))
                                .foregroundStyle(Theme.negative.opacity(0.7))
                                .lineStyle(StrokeStyle(lineWidth: 1, dash: [3]))
                            LineMark(x: .value("T", t), y: .value("PFE 95", p.pfe95[i]),
                                     series: .value("s", "PFE 95%"))
                                .foregroundStyle(Theme.warning.opacity(0.8))
                            LineMark(x: .value("T", t), y: .value("EPE", p.epe[i]),
                                     series: .value("s", "EPE"))
                                .foregroundStyle(Theme.accent)
                            if r.collateralised {
                                LineMark(x: .value("T", t),
                                         y: .value("EPE unc", p.epeUncollateralised[i]),
                                         series: .value("s", "EPE без CSA"))
                                    .foregroundStyle(Theme.accent.opacity(0.35))
                                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [4]))
                            }
                        }
                    }
                    .frame(height: 240)
                    HStack(spacing: Theme.s3) {
                        legend(Theme.accent, "EPE")
                        legend(Theme.warning, "PFE 95%")
                        legend(Theme.negative, "PFE 99%")
                        if r.collateralised { legend(Theme.accent.opacity(0.35), "EPE без CSA") }
                        Spacer()
                    }
                    Text("Hull-White MtM-куб, общий путь ставки для всех сделок неттинг-сета — неттинг учтён точно.")
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                }
            }
        }
    }

    private func metricsCard(_ r: XvaResult) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Adjustments", icon: "list.number")
                ForEach(r.metrics) { metric in
                    HStack {
                        Text(metric.label).font(.system(size: 11))
                        Spacer()
                        Text(Fmt.money(metric.value))
                            .font(.system(size: 12, weight: metric.key == "total_xva" ? .bold : .semibold))
                            .monospacedDigit()
                            .foregroundStyle(metric.key == "total_xva" ? Theme.negative : .primary)
                    }
                    .padding(.vertical, 2)
                    if metric.key != r.metrics.last?.key { Divider() }
                }
                Divider()
                Text("НЕТТИНГ-СЕТ").font(.system(size: 9, weight: .semibold))
                    .tracking(0.5).foregroundStyle(.tertiary)
                ForEach(r.trades, id: \.source) { t in
                    HStack {
                        Text(t.source).font(.system(size: 10)).foregroundStyle(.secondary)
                        Spacer()
                        Text("\(t.payFixed ? "pay" : "rcv") \(Fmt.percent(t.fixedRate * 100, digits: 1)) · \(Fmt.money(t.notional)) · \(Int(t.T))y")
                            .font(.system(size: 10)).monospacedDigit()
                    }
                }
            }
        }
        .frame(width: 330)
    }

    private func legend(_ color: Color, _ text: String) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 14, height: 3)
            Text(text).font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }
}
