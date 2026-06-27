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
    @State private var vm = OverviewVM()

    private let columns = [GridItem(.adaptive(minimum: 150, maximum: 220), spacing: Theme.s3)]

    var body: some View {
        ScreenScaffold {
            if vm.serverDown {
                ContentUnavailableView("Bridge offline", systemImage: "bolt.horizontal.circle").frame(height: 200)
            } else if let d = vm.data, d.available {
                if let line = asOfLine(d) {
                    Text(line).font(.caption).foregroundStyle(.secondary)
                }
                tiles(d)
                if let fx = d.fx, !fx.isEmpty { fxCard(fx) }
            } else if vm.loading {
                ProgressView().frame(maxWidth: .infinity, minHeight: 200)
            } else {
                Text("Нет данных. Запусти ingest.").font(.caption).foregroundStyle(.secondary).frame(height: 120)
            }
        }
        .task { await vm.load() }
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
