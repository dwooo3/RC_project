import SwiftUI

/// Full instrument card: everything ISS exposes + the 5-year daily price history
/// (Date · Price · Yield · day change, coloured) + bond coupon schedule.
struct InstrumentCard: View {
    let category: String
    let secid: String
    var onClose: () -> Void

    @State private var entity: MDEntity?
    @State private var bars: [MDBar] = []
    @State private var loading = true
    private let client = BridgeClient()

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if loading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: Theme.s4) {
                        specSection
                        if category == "equities", let divs = entity?.dividends, !divs.isEmpty {
                            dividendsSection(divs)
                        }
                        historySection
                    }
                    .padding(Theme.s4)
                }
            }
        }
        .frame(width: 760, height: 720)
        .task { await load() }
    }

    private func load() async {
        async let e = try? await client.mdInstrument(category: category, secid: secid)
        async let h = try? await client.mdHistory(secid: secid, market: market, range: "ALL")
        entity = await e
        bars = (await h)?.points ?? []
        loading = false
    }

    private var market: String { category == "equities" ? "shares" : category == "bonds" ? "bonds" : category }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: Theme.s3) {
            VStack(alignment: .leading, spacing: 2) {
                Text(entity?.issuerRu ?? secid).font(.system(size: 17, weight: .bold))
                Text("\(secid)\(entity?.isin.map { " · \($0)" } ?? "")")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
            Spacer()
            Button("Done") { onClose() }.keyboardShortcut(.defaultAction)
        }
        .padding(Theme.s4)
    }

    // MARK: specification (all ISS fields)

    private var specSection: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            BlockTitle("Specification", icon: "doc.text")
            let fields = entity?.fields.filter { ($0.value ?? "").isEmpty == false } ?? []
            LazyVGrid(columns: [GridItem(.flexible(), alignment: .topLeading),
                                GridItem(.flexible(), alignment: .topLeading)], spacing: 6) {
                ForEach(fields) { f in
                    HStack(alignment: .top, spacing: Theme.s2) {
                        Text(f.title ?? f.name).font(.system(size: 11)).foregroundStyle(.secondary)
                            .frame(width: 150, alignment: .leading)
                        Text(f.value ?? "—").font(.system(size: 11, weight: .medium)).textSelection(.enabled)
                        Spacer(minLength: 0)
                    }
                }
            }
        }
    }

    // MARK: dividends (equities)

    private func dividendsSection(_ divs: [MDDividend]) -> some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            BlockTitle("Дивиденды", icon: "banknote")
            HStack(spacing: Theme.s2) { head("Дата закрытия реестра"); head("На акцию"); head("Валюта") }
                .padding(.vertical, 4)
            Divider()
            ForEach(Array(divs.reversed())) { d in
                HStack(spacing: Theme.s2) {
                    cell(d.registryDate, align: .leading)
                    cell(d.value.map { Fmt.number($0, digits: 2) } ?? "—")
                    cell(d.currency ?? "—")
                }
                .padding(.vertical, 3)
                Divider().opacity(0.25)
            }
        }
    }

    // MARK: 5y daily history

    private var historySection: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            BlockTitle("Price history · \(bars.count) days", icon: "calendar")
            HStack(spacing: Theme.s2) {
                head("Date"); head("Price"); if category == "bonds" { head("Yield") }; head("Δ day")
            }
            .padding(.vertical, 4)
            Divider()
            ForEach(Array(rowsNewestFirst().enumerated()), id: \.offset) { _, row in
                HStack(spacing: Theme.s2) {
                    cell(row.bar.date, align: .leading)
                    cell(Fmt.number(row.bar.close, digits: 2))
                    if category == "bonds" { cell(row.bar.yld.map { Fmt.percent($0, digits: 2) } ?? "—") }
                    cell(row.change.map { Fmt.signedPercent($0, digits: 2) } ?? "—",
                         color: row.change.map { $0 >= 0 ? Theme.positive : Theme.negative })
                }
                .padding(.vertical, 3)
                Divider().opacity(0.25)
            }
        }
    }

    private struct Row { let bar: MDBar; let change: Double? }
    private func rowsNewestFirst() -> [Row] {
        var out: [Row] = []
        for i in bars.indices {
            let prev = i > 0 ? bars[i - 1].close : nil
            let chg = prev.map { (bars[i].close - $0) / $0 * 100 }
            out.append(Row(bar: bars[i], change: chg))
        }
        return out.reversed()
    }

    private func head(_ t: String) -> some View {
        Text(t.uppercased()).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: t == "Date" ? .leading : .trailing)
    }

    private func cell(_ t: String, align: Alignment = .trailing, color: Color? = nil) -> some View {
        Text(t).font(.system(size: 11)).monospacedDigit().foregroundStyle(color ?? .primary)
            .frame(maxWidth: .infinity, alignment: align)
    }
}
