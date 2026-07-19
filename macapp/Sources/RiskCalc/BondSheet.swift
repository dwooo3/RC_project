import SwiftUI
import Charts
import Observation

/// One editable row in the pricing sheet — its own instrument + params + result.
@MainActor
@Observable
final class SheetRow: Identifiable, @unchecked Sendable {
    let id = UUID()
    var instrumentID: String
    var quantity: Double = 1
    var numericValues: [String: Double] = [:]
    var choiceValues: [String: String] = [:]
    var result: BatchRowResult?

    init(instrument: BondInstrument, quantity: Double = 1) {
        self.instrumentID = instrument.id
        self.quantity = quantity
        apply(instrument)
    }

    func apply(_ instrument: BondInstrument) {
        numericValues.removeAll()
        choiceValues.removeAll()
        for spec in instrument.params {
            switch spec.defaultValue {
            case .number(let d): numericValues[spec.key] = d
            case .string(let s): choiceValues[spec.key] = s
            }
        }
    }

    func params() -> [String: BridgeValue] {
        var p: [String: BridgeValue] = [:]
        for (k, v) in numericValues { p[k] = BridgeValue(kind: .number(v)) }
        for (k, v) in choiceValues { p[k] = BridgeValue(kind: .string(v)) }
        return p
    }
}

@MainActor
@Observable
final class SheetViewModel {
    var instruments: [BondInstrument] = []
    var rows: [SheetRow] = []
    var aggregate: BondAggregate?
    var isLoading = false
    var isPricing = false
    var serverDown = false
    var errorMessage: String?

    private let client = BridgeClient()

    var grouped: [(group: String, items: [BondInstrument])] {
        let order = ["Sovereign", "Fixed coupon", "Floating", "Embedded option",
                     "Custom", "Securitized", "Money market", "Credit"]
        let groups = Dictionary(grouping: instruments, by: \.group)
        return groups.keys
            .sorted { (order.firstIndex(of: $0) ?? .max, $0) < (order.firstIndex(of: $1) ?? .max, $1) }
            .map { ($0, groups[$0] ?? []) }
    }

    func instrument(_ id: String) -> BondInstrument? { instruments.first { $0.id == id } }

    func load() async {
        guard instruments.isEmpty else { return }
        isLoading = true
        serverDown = false
        do {
            instruments = try await client.bondCatalogue().instruments
            if rows.isEmpty { seed() }
        } catch {
            serverDown = true
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func seed() {
        for id in ["fixed", "frn", "amortizing"] {
            if let inst = instrument(id) { rows.append(SheetRow(instrument: inst)) }
        }
    }

    func addRow(_ id: String) {
        guard let inst = instrument(id) else { return }
        rows.append(SheetRow(instrument: inst))
    }

    func remove(_ row: SheetRow) {
        rows.removeAll { $0.id == row.id }
    }

    func numericBinding(_ row: SheetRow, _ key: String) -> Binding<Double> {
        Binding(get: { row.numericValues[key] ?? 0 }, set: { row.numericValues[key] = $0 })
    }

    func choiceBinding(_ row: SheetRow, _ key: String) -> Binding<String> {
        Binding(get: { row.choiceValues[key] ?? "" }, set: { row.choiceValues[key] = $0 })
    }

    func quantityBinding(_ row: SheetRow) -> Binding<Double> {
        Binding(get: { row.quantity }, set: { row.quantity = $0 })
    }

    func priceAll() async {
        guard !rows.isEmpty else { return }
        isPricing = true
        errorMessage = nil
        let payload = rows.map { BondBatchRow(instrument: $0.instrumentID, params: $0.params(), quantity: $0.quantity) }
        do {
            let response = try await client.priceBatch(payload)
            for (row, result) in zip(rows, response.results) { row.result = result }
            aggregate = response.aggregate
        } catch {
            errorMessage = error.localizedDescription
        }
        isPricing = false
    }
}

// MARK: - View

struct BondSheetView: View {
    @Bindable var vm: SheetViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s4) {
                toolbar
                if let agg = vm.aggregate { aggregateCard(agg) }
                ForEach(vm.rows) { row in rowCard(row) }
                if vm.rows.isEmpty {
                    ContentUnavailableView("No bonds in the sheet", systemImage: "tablecells",
                                           description: Text("Add bonds of any class, then Price all."))
                        .frame(height: 200)
                }
            }
            .padding(Theme.s5)
            .frame(maxWidth: 1100, alignment: .leading)
        }
        .task { await vm.load() }
    }

    private var toolbar: some View {
        HStack {
            Menu {
                ForEach(vm.grouped, id: \.group) { group in
                    Section(group.group) {
                        ForEach(group.items) { inst in
                            Button(inst.name) { vm.addRow(inst.id) }
                        }
                    }
                }
            } label: {
                Label("Add bond", systemImage: "plus")
            }
            .menuStyle(.borderedButton)
            .fixedSize()

            if let message = vm.errorMessage {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.negative).lineLimit(1)
            }
            Spacer()
            Button {
                Task { await vm.priceAll() }
            } label: {
                HStack(spacing: Theme.s2) {
                    if vm.isPricing { ProgressView().controlSize(.small) }
                    Image(systemName: "bolt.fill").font(.system(size: 11))
                    Text(vm.isPricing ? "Pricing…" : "Price all").fontWeight(.semibold)
                }
                .frame(minWidth: 120)
            }
            .controlSize(.large).buttonStyle(.borderedProminent).tint(Theme.accent)
            .disabled(vm.isPricing || vm.rows.isEmpty)
        }
    }

    private func aggregateCard(_ agg: BondAggregate) -> some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            KPIStrip(items: [
                KPICard(label: "Bonds priced", value: "\(agg.count)", sub: "in sheet", accent: Theme.accent, icon: "number"),
                KPICard(label: "Total value", value: Fmt.money(agg.marketValue), sub: "Σ value×qty", accent: Theme.accent, icon: "banknote"),
                KPICard(label: "Total DV01", value: Fmt.number(agg.dv01, digits: 3), sub: "per bp", accent: Theme.negative, icon: "shield.lefthalf.filled"),
                KPICard(label: "Mod duration", value: Fmt.number(agg.modDuration, digits: 3), sub: "MV-weighted", accent: Theme.bucketColor("Rates"), icon: "timer"),
                KPICard(label: "Convexity", value: Fmt.number(agg.convexity, digits: 2), sub: "MV-weighted", accent: Theme.bucketColor("Volatility"), icon: "function"),
            ])
            if !agg.keyRateDurations.isEmpty {
                GlassCard {
                    VStack(alignment: .leading, spacing: Theme.s3) {
                        BlockTitle("Portfolio key-rate durations", icon: "chart.bar.xaxis")
                        Chart(agg.keyRateDurations) { k in
                            BarMark(x: .value("Tenor", "\(Fmt.number(k.tenor, digits: k.tenor < 1 ? 2 : 0))y"),
                                    y: .value("KRD", k.value))
                                .foregroundStyle(Theme.trendColor(k.value)).cornerRadius(2)
                        }
                        .chartXAxisLabel("Tenor")
                        .frame(height: 200)
                    }
                }
            }
        }
    }

    private func rowCard(_ row: SheetRow) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack(spacing: Theme.s3) {
                    Picker("", selection: Binding(
                        get: { row.instrumentID },
                        set: { id in row.instrumentID = id; if let i = vm.instrument(id) { row.apply(i) }; row.result = nil }
                    )) {
                        ForEach(vm.grouped, id: \.group) { group in
                            Section(group.group) {
                                ForEach(group.items) { Text($0.name).tag($0.id) }
                            }
                        }
                    }
                    .labelsHidden().neutralControlTint().fixedSize()

                    HStack(spacing: 4) {
                        Text("Qty").font(.system(size: 11)).foregroundStyle(.secondary)
                        TextField("", value: vm.quantityBinding(row), format: .number)
                            .textFieldStyle(.roundedBorder).frame(width: 70).monospacedDigit()
                    }

                    if let r = row.result { resultStrip(r) }
                    Spacer()
                    Button { vm.remove(row) } label: { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.plain).foregroundStyle(.tertiary)
                }
                if let inst = vm.instrument(row.instrumentID) {
                    DisclosureGroup("Parameters") {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 130), spacing: Theme.s3)],
                                  alignment: .leading, spacing: Theme.s3) {
                            ForEach(inst.params) { spec in
                                if spec.dtype == "float" || spec.dtype == "int" {
                                    ParamFieldView(spec: spec, numeric: vm.numericBinding(row, spec.key), string: nil)
                                } else {
                                    ParamFieldView(spec: spec, numeric: nil, string: vm.choiceBinding(row, spec.key))
                                }
                            }
                        }
                        .padding(.top, Theme.s2)
                    }
                    .font(.system(size: 12, weight: .medium))
                }
            }
        }
    }

    private func resultStrip(_ r: BatchRowResult) -> some View {
        HStack(spacing: Theme.s4) {
            if let e = r.error {
                Label(e, systemImage: "exclamationmark.triangle").font(.system(size: 10)).foregroundStyle(Theme.negative).lineLimit(1)
            } else {
                metric("Value", r.value.map { Fmt.number($0, digits: 3) } ?? "—")
                metric("YTM", r.analytic("ytm").map { Fmt.percent($0 * 100, digits: 2) } ?? "—")
                metric("Mod dur", r.analytic("mod_duration").map { Fmt.number($0, digits: 2) } ?? "—")
                metric("DV01", r.analytic("dv01").map { Fmt.number($0, digits: 3) } ?? "—")
            }
        }
    }

    private func metric(_ label: String, _ value: String) -> some View {
        VStack(alignment: .trailing, spacing: 1) {
            Text(label).font(.system(size: 9)).foregroundStyle(.tertiary)
            Text(value).font(.system(size: 13, weight: .semibold)).monospacedDigit()
        }
    }
}
