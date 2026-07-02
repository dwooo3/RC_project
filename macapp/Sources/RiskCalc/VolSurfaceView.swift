import SwiftUI
import AppKit
import Charts
import Observation

/// Volatility-surface browser: underlyings (1/3) + the calibrated SABR surface
/// as a static 3-axis chart (rendered server-side) + one flat table holding every
/// option across all expiries. Market / OTC split (OTC is a placeholder for now).
@MainActor
@Observable
final class VolSurfaceVM {
    var underlyings: [VolUnderlying] = []
    var selected: String?
    var surface: VolSurface?
    var plotImage: NSImage?
    var otc: OTCSurface?
    var loading = false
    var serverDown = false

    private let client = BridgeClient()

    func start() async {
        loading = true
        do {
            underlyings = try await client.volSurfaceList().underlyings
            serverDown = false
        } catch { serverDown = true }
        loading = false
        if let first = underlyings.first { await select(first.code) }
    }

    func select(_ code: String) async {
        selected = code
        surface = nil
        plotImage = nil
        otc = nil
        loading = true
        surface = try? await client.volSurface(underlying: code)
        if let data = try? await client.volSurfacePlot(underlying: code) {
            plotImage = NSImage(data: data)
        }
        otc = try? await client.otcSurface(underlying: code)
        loading = false
    }
}

struct VolSurfaceView: View {
    @State private var vm = VolSurfaceVM()
    @State private var section = "market"

    var body: some View {
        GeometryReader { geo in
            HStack(spacing: 0) {
                listPane.frame(width: max(220, geo.size.width * 0.28))
                Divider()
                detailPane.frame(maxWidth: .infinity)
            }
        }
        .task { if vm.underlyings.isEmpty { await vm.start() } }
    }

    // MARK: underlyings list

    private var listPane: some View {
        Group {
            if vm.serverDown {
                ContentUnavailableView("Bridge offline", systemImage: "bolt.horizontal.circle")
            } else if vm.underlyings.isEmpty && !vm.loading {
                Text("Нет поверхностей. Запусти ingest.")
                    .font(.caption).foregroundStyle(.secondary).padding().frame(maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(vm.underlyings) { u in
                            Button { Task { await vm.select(u.code) } } label: {
                                HStack {
                                    Text(u.code).font(.system(size: 12, weight: .medium))
                                    Spacer()
                                    Text("\(u.expiries) экс · \(u.points)")
                                        .font(.system(size: 9)).foregroundStyle(.tertiary)
                                }
                                .padding(.horizontal, Theme.s2).padding(.vertical, 7).contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .background(vm.selected == u.code ? Theme.accent.opacity(0.14) : .clear)
                            Divider().opacity(0.25)
                        }
                    }
                }
            }
        }
    }

    // MARK: detail

    @ViewBuilder
    private var detailPane: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s4) {
                HStack(alignment: .firstTextBaseline) {
                    Text(vm.selected ?? "—").font(.system(size: 18, weight: .bold))
                    Text("поверхность волатильности").font(.system(size: 11)).foregroundStyle(.secondary)
                    Spacer()
                }
                Picker("", selection: $section) {
                    Text("Market").tag("market"); Text("OTC").tag("otc")
                }
                .pickerStyle(.segmented).fixedSize().labelsHidden()

                if section == "otc" {
                    otcSection
                } else if vm.loading {
                    HStack(spacing: Theme.s2) {
                        ProgressView().controlSize(.small)
                        Text("Калибровка поверхности…").font(.caption).foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, minHeight: 240)
                } else if let surf = vm.surface, !surf.expiries.isEmpty {
                    surfacePlot
                    if let d = surf.diagnostics { fitCaption(d) }
                    rvVsIv(surf)
                    atmTermStructure(surf)
                    fullTable(surf)
                } else {
                    Text("Нет данных").font(.caption).foregroundStyle(.secondary).frame(height: 120)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(Theme.s4)
        }
    }

    // MARK: surface chart (matplotlib mplot3d, rendered server-side)

    @ViewBuilder
    private var surfacePlot: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s2) {
                BlockTitle("Поверхность волатильности · дельта × срок × IV", icon: "cube")
                if let img = vm.plotImage {
                    Image(nsImage: img)
                        .resizable()
                        .interpolation(.high)
                        .scaledToFit()
                        .frame(maxWidth: .infinity)
                        .frame(maxHeight: 440)
                } else {
                    Text("График недоступен").font(.caption).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 200)
                }
            }
        }
    }

    // MARK: OTC FX vols (ATM / 25Δ RR / 25Δ BF term structure)

    @ViewBuilder
    private var otcSection: some View {
        if vm.loading {
            HStack(spacing: Theme.s2) {
                ProgressView().controlSize(.small)
                Text("Загрузка OTC…").font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 240)
        } else if let otc = vm.otc, otc.isFx, !otc.tenors.isEmpty {
            otcChart(otc)
            otcTable(otc)
            Text("OTC-котировки FX: ATM / 25Δ risk-reversal / 25Δ butterfly, выведены из FX-опционов FORTS (self-implied, крылья по ликвидности).")
                .font(.system(size: 9)).foregroundStyle(.tertiary)
        } else if vm.otc?.isFx == false {
            ContentUnavailableView("OTC только для FX", systemImage: "building.columns",
                                   description: Text("OTC-котировки доступны для валютных базовых активов (Si · CNY · Eu · ED). Для остальных нужен брокерский фид."))
                .frame(height: 260)
        } else {
            Text("Нет OTC-данных").font(.caption).foregroundStyle(.secondary).frame(height: 120)
        }
    }

    private func otcChart(_ otc: OTCSurface) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("\(otc.underlying) · OTC термоструктура (ATM / RR / BF)", icon: "chart.xyaxis.line")
                Chart {
                    ForEach(otc.tenors) { t in
                        if let a = t.atm {
                            LineMark(x: .value("Срок", t.t), y: .value("%", a * 100), series: .value("s", "ATM"))
                                .foregroundStyle(Theme.accent)
                            PointMark(x: .value("Срок", t.t), y: .value("%", a * 100)).foregroundStyle(Theme.accent).symbolSize(22)
                        }
                        if let rr = t.rr25 {
                            LineMark(x: .value("Срок", t.t), y: .value("%", rr * 100), series: .value("s", "25Δ RR"))
                                .foregroundStyle(Theme.negative)
                        }
                        if let bf = t.bf25 {
                            LineMark(x: .value("Срок", t.t), y: .value("%", bf * 100), series: .value("s", "25Δ BF"))
                                .foregroundStyle(Theme.positive)
                        }
                    }
                }
                .chartForegroundStyleScale(["ATM": Theme.accent, "25Δ RR": Theme.negative, "25Δ BF": Theme.positive])
                .chartXAxisLabel("Срок, лет").chartYAxisLabel("%")
                .frame(height: 240)
            }
        }
    }

    private func otcTable(_ otc: OTCSurface) -> some View {
        GlassCard(padding: Theme.s2) {
            VStack(spacing: 0) {
                HStack(spacing: Theme.s2) {
                    head("Экспирация", .leading); head("Срок", .trailing); head("ATM", .trailing)
                    head("25Δ RR", .trailing); head("25Δ BF", .trailing)
                    head("σ 25P", .trailing); head("σ 25C", .trailing)
                }
                .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
                Divider()
                ForEach(otc.tenors) { t in
                    HStack(spacing: Theme.s2) {
                        cell(t.expiry, .leading, .medium)
                        cell(String(format: "%.2f", t.t), .trailing)
                        cell(t.atm.map { Fmt.percent($0 * 100, digits: 1) } ?? "—", .trailing)
                        cell(t.rr25.map { Fmt.signedPercent($0 * 100, digits: 1) } ?? "—", .trailing,
                             .regular, (t.rr25 ?? 0) < 0 ? Theme.negative : Theme.positive)
                        cell(t.bf25.map { Fmt.percent($0 * 100, digits: 1) } ?? "—", .trailing)
                        cell(t.sig25p.map { Fmt.percent($0 * 100, digits: 1) } ?? "—", .trailing)
                        cell(t.sig25c.map { Fmt.percent($0 * 100, digits: 1) } ?? "—", .trailing)
                    }
                    .padding(.horizontal, Theme.s2).padding(.vertical, 3)
                    Divider().opacity(0.25)
                }
            }
        }
    }

    // MARK: RV vs IV (B7) — implied premium over realized vol of the futures

    @ViewBuilder
    private func rvVsIv(_ surf: VolSurface) -> some View {
        if let rv = surf.rv30dPct,
           let atm = surf.expiries.first(where: { $0.atmIv != nil })?.atmIv {
            let iv = atm * 100
            let prem = iv - rv
            HStack(spacing: Theme.s2) {
                Image(systemName: "waveform.path.ecg").font(.system(size: 10)).foregroundStyle(.tertiary)
                Text("ATM IV \(Fmt.percent(iv, digits: 1)) · RV 30д \(Fmt.percent(rv, digits: 1)) → IV-премия ")
                    .font(.system(size: 10)).foregroundStyle(.secondary)
                + Text("\(prem >= 0 ? "+" : "")\(Fmt.number(prem, digits: 1)) п.п.")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(prem >= 0 ? Theme.warning : Theme.positive)
                Spacer()
            }
            .padding(.horizontal, Theme.s1)
        }
    }

    // MARK: ATM / 25Δ RR / 25Δ BF term structure (B8 — skew for every asset)

    private func atmTermStructure(_ surf: VolSurface) -> some View {
        let pts = surf.expiries.compactMap { e -> (t: Double, iv: Double, rr: Double?, bf: Double?, exp: String)? in
            guard let t = e.t, let a = e.atmIv else { return nil }
            return (t, a * 100, e.rr25.map { $0 * 100 }, e.bf25.map { $0 * 100 }, e.expiry)
        }.sorted { $0.t < $1.t }
        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Термоструктура · ATM / 25Δ RR / 25Δ BF", icon: "chart.xyaxis.line")
                if pts.count >= 2 {
                    Chart {
                        ForEach(pts, id: \.exp) { p in
                            LineMark(x: .value("Срок", p.t), y: .value("%", p.iv), series: .value("s", "ATM"))
                                .foregroundStyle(Theme.accent).lineStyle(.init(lineWidth: 2.2))
                                .interpolationMethod(.catmullRom)
                            PointMark(x: .value("Срок", p.t), y: .value("%", p.iv))
                                .foregroundStyle(Theme.accent).symbolSize(28)
                            if let rr = p.rr {
                                LineMark(x: .value("Срок", p.t), y: .value("%", rr), series: .value("s", "25Δ RR"))
                                    .foregroundStyle(Theme.negative).lineStyle(.init(lineWidth: 1.6))
                            }
                            if let bf = p.bf {
                                LineMark(x: .value("Срок", p.t), y: .value("%", bf), series: .value("s", "25Δ BF"))
                                    .foregroundStyle(Theme.positive).lineStyle(.init(lineWidth: 1.6))
                            }
                        }
                    }
                    .chartForegroundStyleScale(["ATM": Theme.accent, "25Δ RR": Theme.negative, "25Δ BF": Theme.positive])
                    .chartXAxisLabel("Срок, лет").chartYAxisLabel("%")
                    .frame(height: 220)
                } else {
                    Text("Недостаточно экспираций").font(.caption).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 80)
                }
            }
        }
    }

    private func fitCaption(_ d: VolDiagnostics) -> some View {
        HStack(spacing: Theme.s2) {
            Image(systemName: "checkmark.seal").font(.system(size: 10)).foregroundStyle(.tertiary)
            Text([d.fitModel,
                  d.rmse.map { "RMSE \(Fmt.percent($0 * 100, digits: 2))" },
                  d.nExpiries.map { "\($0) экс" },
                  d.nPoints.map { "\($0) точек" }]
                .compactMap { $0 }.joined(separator: " · "))
                .font(.system(size: 10)).foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.horizontal, Theme.s1)
    }

    // MARK: flat table — every option across all expiries

    private struct FlatRow: Identifiable {
        let id: String
        let expiry: String
        let p: VolPoint
    }

    private func flatRows(_ surf: VolSurface) -> [FlatRow] {
        surf.expiries
            .sorted { ($0.t ?? 0) < ($1.t ?? 0) }
            .flatMap { e in
                e.points.map { FlatRow(id: "\(e.expiry)#\($0.strike)", expiry: e.expiry, p: $0) }
            }
    }

    private func fullTable(_ surf: VolSurface) -> some View {
        let rows = flatRows(surf)
        return GlassCard(padding: Theme.s2) {
            VStack(spacing: 0) {
                HStack(spacing: Theme.s2) {
                    head("Экспирация", .leading); head("Strike", .trailing); head("Δ", .trailing)
                    head("IV", .trailing); head("Котировка", .trailing); head("Fair Value", .trailing)
                }
                .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
                Divider()
                ForEach(rows) { r in
                    let p = r.p
                    HStack(spacing: Theme.s2) {
                        cell(r.expiry, .leading, .regular, .secondary)
                        cell(Fmt.number(p.strike, digits: p.strike < 100 ? 2 : 0), .trailing, .medium)
                        cell(p.delta.map { Fmt.number($0, digits: 2) } ?? "—", .trailing)
                        cell(p.iv.map { Fmt.percent($0 * 100, digits: 2) } ?? "—", .trailing)
                        cell(p.quote.map { Fmt.number($0, digits: 1) } ?? "—", .trailing)
                        cell(p.fairValue.map { Fmt.number($0, digits: 1) } ?? "—", .trailing,
                             .regular, fairColor(p))
                    }
                    .padding(.horizontal, Theme.s2).padding(.vertical, 3)
                    Divider().opacity(0.25)
                }
            }
        }
    }

    private func fairColor(_ p: VolPoint) -> Color {
        guard let q = p.quote, let f = p.fairValue, q > 0 else { return .primary }
        return f > q ? Theme.positive : (f < q ? Theme.negative : .primary)   // fair vs market
    }

    private func head(_ t: String, _ align: Alignment) -> some View {
        Text(t.uppercased()).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: align)
    }

    private func cell(_ t: String, _ align: Alignment, _ weight: Font.Weight = .regular,
                      _ color: Color = .primary) -> some View {
        Text(t).font(.system(size: 11, weight: weight)).monospacedDigit().foregroundStyle(color)
            .frame(maxWidth: .infinity, alignment: align)
    }
}
