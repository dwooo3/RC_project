import SwiftUI

/// Pricing route: an instrument-category switch over the per-category panes.
/// Options today; Bond (all rate instruments) now; structured / baskets / swaps
/// slot in here as further cases.
struct PricingScreen: View {
    enum Category: String, CaseIterable, Identifiable {
        case options = "Options"
        case bond = "Bond"
        var id: String { rawValue }
    }

    @State private var category: Category = .options

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                SegmentedBar(items: Category.allCases.map { ($0, $0.rawValue) },
                             selection: $category)
                    .fixedSize()
                Spacer()
            }
            .padding(.horizontal, Theme.s5)
            .padding(.vertical, Theme.s2)
            Divider()
            switch category {
            case .options: PricingView()
            case .bond: BondPane()
            }
        }
        .navigationTitle("Pricing")
    }
}

/// Options pricing workspace — full-height pricer rail + grouped, flexible
/// parameter form + detailed valuation.
struct PricingView: View {
    @State private var vm = PricingViewModel()

    var body: some View {
        Group {
            if vm.serverDown {
                ServerDownView(message: vm.errorMessage) { Task { await vm.load() } }
            } else {
                HStack(spacing: 0) {
                    pricerRail
                    Divider()
                    workArea
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await vm.load() }
        .navigationTitle("Pricing")
    }

    // MARK: pricer rail (left)

    private var pricerRail: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s4) {
                ForEach(vm.groupedPricers, id: \.family) { group in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(group.family.uppercased())
                            .font(.system(size: 10, weight: .semibold)).tracking(0.5)
                            .foregroundStyle(.tertiary)
                            .padding(.horizontal, Theme.s2)
                        ForEach(group.items) { pricer in
                            pricerRow(pricer)
                        }
                    }
                }
            }
            .padding(Theme.s3)
        }
        .frame(width: 240)
        .background(Color(nsColor: .windowBackgroundColor).opacity(0.5))
        .overlay {
            if vm.isLoading && vm.pricers.isEmpty {
                ProgressView().controlSize(.small)
            }
        }
    }

    private func pricerRow(_ pricer: Pricer) -> some View {
        let selected = vm.selectedID == pricer.id
        return Button {
            vm.select(pricer.id)
        } label: {
            HStack(spacing: Theme.s2) {
                Circle().fill(Theme.statusColor(pricer.governance.status)).frame(width: 7, height: 7)
                Text(pricer.name)
                    .font(.system(size: 13, weight: selected ? .semibold : .regular))
                    .foregroundStyle(selected ? Theme.accent : .primary)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, Theme.s3).padding(.vertical, 7)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selected ? Theme.accent.opacity(0.14) : .clear,
                        in: RoundedRectangle(cornerRadius: 7))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: work area (right)

    @ViewBuilder
    private var workArea: some View {
        if let pricer = vm.selected {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s5) {
                    PageHeader(pricer.name,
                               subtitle: governanceLine(pricer)) {
                        StatusChip(status: pricer.governance.status)
                    }
                    HStack(alignment: .top, spacing: Theme.s4) {
                        VStack(alignment: .leading, spacing: Theme.s4) {
                            ForEach(["contract", "market", "model", "numerical"], id: \.self) { group in
                                paramGroup(pricer, group: group)
                            }
                            calculateButton
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)

                        resultPanel
                            .frame(width: 320)
                    }
                }
                .padding(Theme.s5)
                .frame(maxWidth: 1100, alignment: .leading)
            }
            .frame(maxWidth: .infinity)
        } else {
            ContentUnavailableView("Select a pricer", systemImage: "function")
        }
    }

    private func governanceLine(_ pricer: Pricer) -> String {
        [pricer.governance.assetClass, pricer.governance.method]
            .filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private let groupTitles = [
        "contract": "Contract", "market": "Market",
        "model": "Model parameters", "numerical": "Numerical",
    ]

    @ViewBuilder
    private func paramGroup(_ pricer: Pricer, group: String) -> some View {
        let specs = pricer.params.filter { $0.group == group }
        if !specs.isEmpty {
            GlassCard {
                VStack(alignment: .leading, spacing: Theme.s3) {
                    BlockTitle(groupTitles[group] ?? group, icon: icon(for: group))
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: Theme.s3)],
                              alignment: .leading, spacing: Theme.s3) {
                        ForEach(specs) { spec in
                            if spec.dtype == "float" || spec.dtype == "int" {
                                ParamFieldView(spec: spec, numeric: vm.numericBinding(spec.key), string: nil)
                            } else {
                                ParamFieldView(spec: spec, numeric: nil, string: vm.choiceBinding(spec.key))
                            }
                        }
                    }
                }
            }
        }
    }

    private func icon(for group: String) -> String {
        switch group {
        case "contract": return "doc.text"
        case "market": return "globe"
        case "model": return "slider.horizontal.3"
        case "numerical": return "number"
        default: return "circle"
        }
    }

    private var calculateButton: some View {
        HStack {
            if let message = vm.errorMessage, !vm.serverDown {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.negative).lineLimit(2)
            }
            Spacer()
            Button {
                Task { await vm.price() }
            } label: {
                HStack(spacing: Theme.s2) {
                    if vm.isPricing { ProgressView().controlSize(.small) }
                    Image(systemName: "bolt.fill").font(.system(size: 11))
                    Text(vm.isPricing ? "Pricing…" : "Calculate").fontWeight(.semibold)
                }
                .frame(minWidth: 130)
            }
            .controlSize(.large)
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.return, modifiers: .command)
            .disabled(vm.isPricing)
        }
    }

    // MARK: result panel

    @ViewBuilder
    private var resultPanel: some View {
        GlassCard {
            if let r = vm.result {
                VStack(alignment: .leading, spacing: Theme.s3) {
                    HStack {
                        Text("PRESENT VALUE").font(.system(size: 10, weight: .semibold))
                            .tracking(0.5).foregroundStyle(.secondary)
                        Spacer()
                        StatusChip(status: r.modelStatus)
                    }
                    Text(r.value.map { Fmt.number($0, digits: 4) } ?? "—")
                        .font(.system(size: 32, weight: .bold)).monospacedDigit()
                        .foregroundStyle(r.value == nil ? Color.secondary : Theme.accent)
                        .lineLimit(1).minimumScaleFactor(0.5)
                    Text(r.modelID).font(.caption).foregroundStyle(.tertiary)

                    if !r.greeks.isEmpty {
                        Divider()
                        Text("GREEKS").font(.system(size: 10, weight: .semibold))
                            .tracking(0.5).foregroundStyle(.secondary)
                        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: Theme.s2), count: 2),
                                  spacing: Theme.s2) {
                            ForEach(r.greeks, id: \.name) { g in
                                MetricCell(name: g.name, value: g.value)
                            }
                        }
                    }

                    if !r.warnings.isEmpty {
                        Divider()
                        ForEach(r.warnings.prefix(3), id: \.self) { w in
                            Label(w, systemImage: "exclamationmark.triangle")
                                .font(.system(size: 10)).foregroundStyle(.secondary)
                                .padding(Theme.s2)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(Theme.warning.opacity(0.12), in: RoundedRectangle(cornerRadius: 6))
                        }
                    }
                }
            } else {
                VStack(spacing: Theme.s3) {
                    Image(systemName: "chart.line.uptrend.xyaxis")
                        .font(.system(size: 32)).foregroundStyle(.tertiary)
                    Text("No valuation yet").font(.system(size: 15, weight: .semibold))
                    Text("Press Calculate (⌘↵).").font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 200)
            }
        }
    }
}

/// One labelled parameter input — numeric, choice (menu), date (picker) or free
/// text/schedule — stacked label-over-field so it tiles cleanly in a grid.
struct ParamFieldView: View {
    let spec: ParamSpec
    let numeric: Binding<Double>?
    let string: Binding<String>?

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private var format: FloatingPointFormatStyle<Double> {
        spec.dtype == "int" ? .number.precision(.fractionLength(0)) : .number
    }

    private var dateBinding: Binding<Date> {
        Binding(
            get: { Self.dateFormatter.date(from: string?.wrappedValue ?? "") ?? Date() },
            set: { string?.wrappedValue = Self.dateFormatter.string(from: $0) }
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 4) {
                Text(spec.label)
                    .font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                    .lineLimit(1)
                if !spec.unit.isEmpty {
                    Text(spec.unit).font(.system(size: 10)).foregroundStyle(.tertiary)
                }
            }
            field
        }
        .help(spec.help)
    }

    @ViewBuilder
    private var field: some View {
        if spec.dtype == "choice", let string {
            Picker("", selection: string) {
                ForEach(spec.choices ?? [], id: \.self) { Text($0).tag($0) }
            }
            .labelsHidden().pickerStyle(.menu)
        } else if spec.dtype == "date", string != nil {
            DatePicker("", selection: dateBinding, displayedComponents: .date)
                .labelsHidden().datePickerStyle(.compact)
        } else if let string {   // text / schedule
            TextField("", text: string)
                .textFieldStyle(.roundedBorder)
        } else if let numeric {
            TextField("", value: numeric, format: format)
                .textFieldStyle(.roundedBorder).monospacedDigit()
        }
    }
}

/// Full-screen state shown when the Python bridge is unreachable.
struct ServerDownView: View {
    let message: String?
    let retry: () -> Void

    var body: some View {
        ZStack {
            Rectangle().fill(.regularMaterial).ignoresSafeArea()
            VStack(spacing: Theme.s4) {
                Image(systemName: "bolt.horizontal.circle")
                    .font(.system(size: 44)).foregroundStyle(Theme.warning)
                Text("Bridge not reachable").font(.title3.weight(.semibold))
                Text("Start the Python bridge, then retry:").foregroundStyle(.secondary)
                Text("python3.14 -m api.server")
                    .font(.system(.callout, design: .monospaced))
                    .padding(.horizontal, Theme.s3).padding(.vertical, Theme.s2)
                    .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 6))
                if let message, !message.isEmpty {
                    Text(message).font(.caption).foregroundStyle(.tertiary).multilineTextAlignment(.center)
                }
                Button("Retry", action: retry).buttonStyle(.borderedProminent).padding(.top, Theme.s2)
            }
            .padding(Theme.s6).frame(maxWidth: 380)
        }
    }
}
