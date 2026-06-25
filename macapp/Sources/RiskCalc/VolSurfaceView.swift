import SwiftUI
import Charts
import Observation

/// Volatility-surface browser: underlyings (1/3) + the surface (2/3) as a family
/// of smile curves (IV vs strike per expiry) + a per-expiry table. Market / OTC
/// split (OTC is a placeholder for now). Styled after the option board.
@MainActor
@Observable
final class VolSurfaceVM {
    var underlyings: [VolUnderlying] = []
    var selected: String?
    var surface: VolSurface?
    var expiryID: String?
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
        surface = try? await client.volSurface(underlying: code)
        expiryID = surface?.expiries.first?.id
    }

    var expiry: VolExpiry? { surface?.expiries.first { $0.id == expiryID } ?? surface?.expiries.first }
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
                    ContentUnavailableView("OTC — позже", systemImage: "building.columns")
                        .frame(height: 220)
                } else if let surf = vm.surface, !surf.expiries.isEmpty, let e = vm.expiry {
                    expiryChips(surf)
                    smileChart(surf, selected: e)
                    if !surf.surface.isEmpty { surfacePlot(surf) }
                    smileTable(e)
                } else if !vm.loading {
                    Text("Нет данных").font(.caption).foregroundStyle(.secondary).frame(height: 120)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(Theme.s4)
        }
    }

    private func expiryChips(_ surf: VolSurface) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Theme.s2) {
                ForEach(surf.expiries) { e in
                    let on = vm.expiry?.id == e.id
                    Button { vm.expiryID = e.id } label: {
                        VStack(spacing: 1) {
                            Text(e.expiry).font(.system(size: 11, weight: on ? .semibold : .regular))
                            if let a = e.atmIv { Text("ATM \(Fmt.percent(a * 100, digits: 1))").font(.system(size: 9)) }
                        }
                        .foregroundStyle(on ? Theme.accent : .secondary)
                        .padding(.horizontal, Theme.s2).padding(.vertical, 4)
                        .background(on ? Theme.accent.opacity(0.16) : Color.gray.opacity(0.12), in: RoundedRectangle(cornerRadius: 7))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    // MARK: smile chart — IV vs delta, market points + calibrated SABR curve

    private func smileChart(_ surf: VolSurface, selected: VolExpiry) -> some View {
        let ivs = surf.expiries.flatMap { $0.sabrCurve }.map { $0.iv * 100 }
        let lo = ivs.min() ?? 0, hi = ivs.max() ?? 1
        let pad = max((hi - lo) * 0.1, 1)
        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("\(surf.underlying) · smile по дельте (SABR)", icon: "chart.xyaxis.line")
                if let s = selected.sabr {
                    HStack(spacing: Theme.s2) {
                        sabrChip("α", s.alpha, 3); sabrChip("β", s.beta, 2)
                        sabrChip("ρ", s.rho, 3); sabrChip("ν", s.nu, 3)
                        Spacer(minLength: Theme.s2)
                        if let f = selected.forward {
                            Text("F \(Fmt.number(f, digits: 0))").font(.system(size: 10)).foregroundStyle(.tertiary)
                        }
                        if let a = selected.atmIv {
                            Text("ATM \(Fmt.percent(a * 100, digits: 1))").font(.system(size: 10)).foregroundStyle(.tertiary)
                        }
                    }
                }
                Chart {
                    ForEach(surf.expiries.filter { $0.id != selected.id }) { e in
                        ForEach(e.sabrCurve) { p in
                            LineMark(x: .value("Δ", p.delta), y: .value("IV", p.iv * 100),
                                     series: .value("e", e.expiry))
                                .foregroundStyle(.gray.opacity(0.18)).interpolationMethod(.catmullRom)
                        }
                    }
                    ForEach(selected.sabrCurve) { p in
                        LineMark(x: .value("Δ", p.delta), y: .value("IV", p.iv * 100),
                                 series: .value("e", "sel"))
                            .foregroundStyle(Theme.accent).lineStyle(.init(lineWidth: 2.4))
                            .interpolationMethod(.catmullRom)
                    }
                    ForEach(selected.points) { p in
                        if let d = p.delta {
                            PointMark(x: .value("Δ", d), y: .value("IV", p.iv * 100))
                                .foregroundStyle(Theme.warning).symbolSize(26)
                        }
                    }
                }
                .chartXScale(domain: 0...1)
                .chartYScale(domain: (lo - pad)...(hi + pad))
                .chartXAxisLabel("Call delta").chartYAxisLabel("IV %")
                .frame(height: 300)
                Text("● рыночные точки   — калиброванный SABR")
                    .font(.system(size: 9)).foregroundStyle(.tertiary)
            }
        }
    }

    private func sabrChip(_ name: String, _ value: Double, _ digits: Int) -> some View {
        HStack(spacing: 3) {
            Text(name).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            Text(Fmt.number(value, digits: digits)).font(.system(size: 10, weight: .medium)).monospacedDigit()
        }
        .padding(.horizontal, 6).padding(.vertical, 2)
        .background(Theme.accent.opacity(0.12), in: Capsule())
    }

    // MARK: calibrated surface plot (heatmap chart: delta × expiry → IV)

    private func surfacePlot(_ surf: VolSurface) -> some View {
        let all = surf.surface.flatMap { $0.cells }.compactMap { $0.iv }
        let lo = all.min() ?? 0, hi = all.max() ?? 1
        let step = surf.deltas.count > 1 ? (surf.deltas[1] - surf.deltas[0]) : 0.05
        let rows = surf.surface.map(\.expiry)
        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Поверхность волатильности (SABR)", icon: "cube")
                Chart {
                    ForEach(surf.surface) { row in
                        ForEach(row.cells, id: \.delta) { c in
                            if let iv = c.iv {
                                RectangleMark(
                                    xStart: .value("Δ0", c.delta - step / 2),
                                    xEnd: .value("Δ1", c.delta + step / 2),
                                    y: .value("Экспирация", row.expiry)
                                )
                                .foregroundStyle(heatColor(iv, lo, hi))
                            }
                        }
                    }
                }
                .chartXScale(domain: 0...1)
                .chartYScale(domain: .automatic(reversed: true))
                .chartXAxis { AxisMarks(values: [0.1, 0.25, 0.5, 0.75, 0.9]) { v in
                    AxisGridLine(); AxisValueLabel { if let d = v.as(Double.self) { Text("Δ\(Int(d * 100))") } }
                } }
                .chartPlotStyle { $0.border(Color.gray.opacity(0.15)) }
                .frame(height: CGFloat(max(rows.count, 1)) * 30 + 36)
                .chartXAxisLabel("Call delta")
                legend(lo, hi)
            }
        }
    }

    private func legend(_ lo: Double, _ hi: Double) -> some View {
        HStack(spacing: Theme.s2) {
            Text("низкий IV").font(.system(size: 9)).foregroundStyle(.tertiary)
            LinearGradient(
                colors: [heatColor(lo, lo, hi), heatColor((lo + hi) / 2, lo, hi), heatColor(hi, lo, hi)],
                startPoint: .leading, endPoint: .trailing)
                .frame(width: 120, height: 8).clipShape(Capsule())
            Text("высокий").font(.system(size: 9)).foregroundStyle(.tertiary)
            Spacer()
            Text("\(Fmt.percent(lo * 100, digits: 0)) … \(Fmt.percent(hi * 100, digits: 0))")
                .font(.system(size: 9)).foregroundStyle(.secondary)
        }
    }

    private func heatColor(_ iv: Double?, _ lo: Double, _ hi: Double) -> Color {
        guard let iv, hi > lo else { return Color.gray.opacity(0.12) }
        let t = min(max((iv - lo) / (hi - lo), 0), 1)        // 0 low IV → 1 high IV
        return Color(hue: (1 - t) * 0.62, saturation: 0.65, brightness: 0.55).opacity(0.55)  // blue→red
    }

    private func smileTable(_ e: VolExpiry) -> some View {
        GlassCard(padding: Theme.s2) {
            VStack(spacing: 0) {
                HStack(spacing: Theme.s2) {
                    head("Strike", .leading); head("Δ", .trailing); head("IV", .trailing)
                    head("Котировка", .trailing); head("Fair Value", .trailing)
                }
                .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
                Divider()
                ForEach(e.points) { p in
                    HStack(spacing: Theme.s2) {
                        cell(Fmt.number(p.strike, digits: p.strike < 100 ? 2 : 0), .leading, .medium)
                        cell(p.delta.map { Fmt.number($0, digits: 2) } ?? "—", .trailing)
                        cell(Fmt.percent(p.iv * 100, digits: 2), .trailing)
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
