import SwiftUI

/// Pricing route: the universal derivatives workstation (every pricer in the
/// model library, grouped by asset class) plus the dedicated fixed-income pane.
struct PricingScreen: View {
    enum Category: String, CaseIterable, Identifiable {
        case derivatives = "Derivatives"
        case bond = "Bond"
        var id: String { rawValue }
    }

    @State private var category: Category = .derivatives

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
            case .derivatives: PricingWorkstationView()
            case .bond: BondPane()
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

    /// Server-declared bounds check (spec.minimum / maximum) — the value stays
    /// editable, the field just flags it before the server would 400.
    private var outOfBounds: Bool {
        guard let v = numeric?.wrappedValue else { return false }
        if let lo = spec.minimum, v < lo { return true }
        if let hi = spec.maximum, v > hi { return true }
        return false
    }

    private var boundsHint: String {
        let lo = spec.minimum.map { Fmt.number($0, digits: 4) } ?? "−∞"
        let hi = spec.maximum.map { Fmt.number($0, digits: 4) } ?? "∞"
        return "допустимо \(lo) … \(hi)"
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
                .overlay(
                    RoundedRectangle(cornerRadius: 5)
                        .stroke(Theme.negative.opacity(outOfBounds ? 0.8 : 0), lineWidth: 1)
                )
            if outOfBounds {
                Text(boundsHint)
                    .font(.system(size: 9)).foregroundStyle(Theme.negative)
            }
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
