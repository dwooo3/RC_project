import SwiftUI

/// Option chain board: pick an expiry, then Call (Last · OI) | Strike | Put (Last · OI),
/// centred on the ATM strike. Options have no single price series, so this replaces
/// the price chart in the detail pane.
struct OptionChainView: View {
    let chain: [MDOptionExpiry]
    @State private var expiryID: String?
    @State private var moneyness = "all"        // "5" | "10" | "20" | "all"
    @State private var minOI = 0.0              // 0 | 100 | 1000

    private var expiry: MDOptionExpiry? {
        chain.first { $0.id == expiryID } ?? chain.first
    }

    /// Strikes within the moneyness window of the central strike and above the OI
    /// floor — the doc's chain filters (moneyness / min OI).
    private func visibleStrikes(_ e: MDOptionExpiry) -> [MDOptionStrike] {
        var out = e.strikes
        if let cs = e.centralStrike, cs > 0, let pct = Double(moneyness) {
            out = out.filter { abs($0.strike - cs) / cs <= pct / 100 }
        }
        if minOI > 0 {
            out = out.filter { max($0.call?.oi ?? 0, $0.put?.oi ?? 0) >= minOI }
        }
        return out
    }

    var body: some View {
        if chain.isEmpty {
            Text("Нет данных по цепочке опционов").font(.caption).foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: Theme.s3) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: Theme.s2) {
                        ForEach(chain) { e in
                            let on = (expiry?.id ?? chain[0].id) == e.id
                            Button { expiryID = e.id } label: {
                                Text(e.expiry)
                                    .font(.system(size: 11, weight: on ? .semibold : .regular))
                                    .foregroundStyle(on ? Theme.accent : .secondary)
                                    .padding(.horizontal, Theme.s2).padding(.vertical, 4)
                                    .background(on ? Theme.accent.opacity(0.16) : Color.gray.opacity(0.12),
                                                in: Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                if let e = expiry {
                    filterRow(e)
                    if let cs = e.centralStrike {
                        Text("Центральный страйк \(strikeStr(cs)) · показано \(visibleStrikes(e).count) из \(e.strikes.count)")
                            .font(.caption).foregroundStyle(.tertiary)
                    }
                    board(e)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func filterRow(_ e: MDOptionExpiry) -> some View {
        HStack(spacing: Theme.s3) {
            Picker("", selection: $moneyness) {
                Text("±5%").tag("5"); Text("±10%").tag("10"); Text("±20%").tag("20"); Text("Все").tag("all")
            }
            .pickerStyle(.segmented).fixedSize().labelsHidden()
            Menu {
                Button("OI ≥ 0") { minOI = 0 }
                Button("OI ≥ 100") { minOI = 100 }
                Button("OI ≥ 1000") { minOI = 1000 }
            } label: {
                Text("OI ≥ \(Int(minOI))").font(.system(size: 11, weight: minOI > 0 ? .semibold : .regular))
            }
            .menuStyle(.borderlessButton).fixedSize()
            Spacer()
        }
    }

    private func board(_ e: MDOptionExpiry) -> some View {
        GlassCard(padding: Theme.s2) {
            VStack(spacing: 0) {
                HStack(spacing: Theme.s2) {
                    head("Call OI", .trailing); head("Call", .trailing)
                    head("Strike", .center)
                    head("Put", .leading); head("Put OI", .leading)
                }
                .padding(.horizontal, Theme.s2).padding(.vertical, Theme.s2)
                Divider()
                ForEach(visibleStrikes(e)) { s in
                    let atm = e.centralStrike.map { abs(s.strike - $0) < 1e-6 } ?? false
                    HStack(spacing: Theme.s2) {
                        cell(fmt(s.call?.oi, 0), .trailing, Theme.positive.opacity(0.85))
                        cell(fmt(s.call?.last), .trailing)
                        Text(strikeStr(s.strike))
                            .font(.system(size: 12, weight: .semibold)).monospacedDigit()
                            .frame(maxWidth: .infinity, alignment: .center)
                        cell(fmt(s.put?.last), .leading)
                        cell(fmt(s.put?.oi, 0), .leading, Theme.negative.opacity(0.85))
                    }
                    .padding(.horizontal, Theme.s2).padding(.vertical, 4)
                    .background(atm ? Theme.accent.opacity(0.14) : .clear)
                    Divider().opacity(0.25)
                }
            }
        }
    }

    private func fmt(_ v: Double?, _ digits: Int = 2) -> String {
        guard let v, v != 0 else { return "—" }
        return Fmt.number(v, digits: digits)
    }

    /// Strike precision adapts to magnitude so small-strike underlyings (e.g.
    /// AFKS ~12) don't collapse distinct strikes to the same integer.
    private func strikeStr(_ v: Double) -> String {
        Fmt.number(v, digits: v < 100 ? 2 : 0)
    }

    private func head(_ t: String, _ align: Alignment) -> some View {
        Text(t.uppercased()).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: align)
    }

    private func cell(_ t: String, _ align: Alignment, _ color: Color = .primary) -> some View {
        Text(t).font(.system(size: 11)).monospacedDigit().foregroundStyle(color)
            .frame(maxWidth: .infinity, alignment: align)
    }
}
