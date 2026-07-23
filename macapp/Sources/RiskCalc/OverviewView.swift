import SwiftUI
import Observation

/// Market Data landing — a navigational summary, not a quality dashboard:
/// asset-class tiles (counts, tap to open) + key FX + an as-of line. Backed by
/// GET /md/overview.
@MainActor
@Observable
final class OverviewVM {
    var data: MDOverview?
    var loading = false
    var serverDown = false
    private let client = BridgeClient()

    func load() async {
        loading = true
        do { data = try await client.mdOverview(); serverDown = false }
        catch { serverDown = true }
        loading = false
    }
}

struct OverviewView: View {
    /// Tile tap → parent switches to that data section.
    var onSelect: (String) -> Void
    /// Indicator / recent-instrument tap → parent opens it (category, secid).
    var onOpen: (String, String) -> Void
    @State private var vm = OverviewVM()
    @State private var recents: [RecentInstrument] = []

    private let columns = [GridItem(.adaptive(minimum: 150, maximum: 220), spacing: Theme.s3)]

    var body: some View {
        ScreenScaffold {
            if vm.serverDown {
                ContentUnavailableView("Мост недоступен", systemImage: "bolt.horizontal.circle").frame(height: 200)
            } else if let d = vm.data, d.available {
                if let line = asOfLine(d) {
                    Text(line).font(.caption).foregroundStyle(.secondary)
                }
                if let ind = d.indicators, !ind.isEmpty { indicatorStrip(ind) }
                tiles(d)
                if !recents.isEmpty { recentsCard }
                if let fx = d.fx, !fx.isEmpty { fxCard(fx) }
            } else if vm.loading {
                ProgressView().frame(maxWidth: .infinity, minHeight: 200)
            } else {
                Text("Нет данных. Запустите загрузку данных.").font(.caption).foregroundStyle(.secondary).frame(height: 120)
            }
        }
        .task {
            recents = RecentInstruments.all()
            await vm.load()
        }
    }

    // MARK: market pulse (C2)

    private func indicatorStrip(_ ind: [OverviewIndicator]) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Theme.s3) {
                ForEach(ind) { i in
                    Button { onOpen(i.category, i.key) } label: { indicatorCard(i) }
                        .buttonStyle(.plain)
                }
            }
        }
    }

    private func indicatorCard(_ i: OverviewIndicator) -> some View {
        GlassCard(padding: Theme.s3) {
            VStack(alignment: .leading, spacing: 2) {
                Text(i.label).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                Text(Fmt.number(i.value, digits: 2)).font(.system(size: 16, weight: .bold)).monospacedDigit()
                Text(i.changePct.map { Fmt.signedPercent($0, digits: 2) } ?? " ")
                    .font(.system(size: 10, weight: .medium)).monospacedDigit()
                    .foregroundStyle((i.changePct ?? 0) >= 0 ? Theme.positive : Theme.negative)
            }
            .frame(width: 118, alignment: .leading)
        }
        .contentShape(Rectangle())
    }

    private var recentsCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Недавно просмотренные", icon: "clock.arrow.circlepath")
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: Theme.s2) {
                        ForEach(recents) { r in
                            Button { onOpen(r.category, r.secid) } label: {
                                HStack(spacing: 5) {
                                    Text(r.label).font(.system(size: 11, weight: .medium)).lineLimit(1)
                                    Text(r.secid).font(.system(size: 9)).foregroundStyle(.tertiary)
                                }
                                .padding(.horizontal, Theme.s3).padding(.vertical, 5)
                                .background(Color.primary.opacity(0.06), in: Capsule())
                                .contentShape(Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }

    private func asOfLine(_ d: MDOverview) -> String? {
        guard let a = d.asOf else { return nil }
        return "Данные на \(a)" + (d.source.map { " · \($0)" } ?? "")
    }

    private func tiles(_ d: MDOverview) -> some View {
        LazyVGrid(columns: columns, spacing: Theme.s3) {
            ForEach(d.tiles ?? []) { t in
                Button { onSelect(t.key) } label: { tile(t) }
                    .buttonStyle(.plain)
            }
        }
    }

    private func tile(_ t: OverviewTile) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s2) {
                HStack {
                    Image(systemName: icon(t.key)).font(.system(size: 14)).foregroundStyle(Theme.accent)
                    Spacer()
                    Image(systemName: "chevron.right").font(.system(size: 10)).foregroundStyle(.tertiary)
                }
                Text("\(t.count)").font(.system(size: 26, weight: .bold)).monospacedDigit()
                Text(t.label).font(.system(size: 12)).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .contentShape(Rectangle())
    }

    private func fxCard(_ fx: [OverviewFX]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Ключевые курсы", icon: "dollarsign.arrow.circlepath")
                ForEach(fx) { r in
                    HStack {
                        Text(r.pair).font(.system(size: 13, weight: .medium))
                        Spacer()
                        Text(Fmt.number(r.rate, digits: 4)).font(.system(size: 13)).monospacedDigit()
                    }
                    Divider().opacity(0.25)
                }
            }
        }
    }

    private func icon(_ key: String) -> String {
        switch key {
        case "bonds":       return "doc.plaintext"
        case "equities":    return "chart.bar.fill"
        case "futures":     return "calendar.badge.clock"
        case "options":     return "function"
        case "commodities": return "drop.fill"
        case "indices":     return "chart.line.uptrend.xyaxis"
        case "fx":          return "dollarsign.circle"
        case "curves":      return "point.topleft.down.curvedto.point.bottomright.up"
        case "vols":        return "cube"
        default:            return "square.grid.2x2"
        }
    }
}
