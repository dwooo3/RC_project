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
                            if let a = e.atm { Text("ATM \(Fmt.percent(a * 100, digits: 1))").font(.system(size: 9)) }
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

    // MARK: smile chart — family of curves, selected expiry highlighted

    private func smileChart(_ surf: VolSurface, selected: VolExpiry) -> some View {
        let ivs = surf.expiries.flatMap { $0.points }.map { $0.iv * 100 }
        let lo = ivs.min() ?? 0, hi = ivs.max() ?? 1
        let pad = max((hi - lo) * 0.1, 1)
        return GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("\(surf.underlying) · smile (IV / strike)", icon: "chart.xyaxis.line")
                Chart {
                    ForEach(surf.expiries.filter { $0.id != selected.id }) { e in
                        ForEach(e.points) { p in
                            LineMark(x: .value("Strike", p.strike), y: .value("IV", p.iv * 100),
                                     series: .value("e", e.expiry))
                                .foregroundStyle(.gray.opacity(0.22)).interpolationMethod(.catmullRom)
                        }
                    }
                    ForEach(selected.points) { p in
                        LineMark(x: .value("Strike", p.strike), y: .value("IV", p.iv * 100),
                                 series: .value("e", "sel"))
                            .foregroundStyle(Theme.accent).lineStyle(.init(lineWidth: 2.4))
                            .interpolationMethod(.catmullRom)
                        PointMark(x: .value("Strike", p.strike), y: .value("IV", p.iv * 100))
                            .foregroundStyle(Theme.accent).symbolSize(18)
                    }
                }
                .chartYScale(domain: (lo - pad)...(hi + pad))
                .chartXAxisLabel("Strike").chartYAxisLabel("IV %")
                .frame(height: 300)
            }
        }
    }

    private func smileTable(_ e: VolExpiry) -> some View {
        GlassCard(padding: Theme.s2) {
            VStack(spacing: 0) {
                HStack(spacing: Theme.s2) { head("Strike"); head("IV") }
                    .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
                Divider()
                ForEach(e.points) { p in
                    HStack(spacing: Theme.s2) {
                        Text(Fmt.number(p.strike, digits: p.strike < 100 ? 2 : 0))
                            .font(.system(size: 11, weight: .medium)).monospacedDigit()
                            .frame(maxWidth: .infinity, alignment: .leading)
                        Text(Fmt.percent(p.iv * 100, digits: 2)).font(.system(size: 11)).monospacedDigit()
                            .frame(maxWidth: .infinity, alignment: .trailing)
                    }
                    .padding(.horizontal, Theme.s2).padding(.vertical, 3)
                    Divider().opacity(0.25)
                }
            }
        }
    }

    private func head(_ t: String) -> some View {
        Text(t.uppercased()).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: t == "Strike" ? .leading : .trailing)
    }
}
