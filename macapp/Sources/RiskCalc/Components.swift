import SwiftUI

/// Small coloured status capsule (governance status).
struct StatusChip: View {
    let status: String

    var body: some View {
        Text(status)
            .font(Typography.label)
            .foregroundStyle(Theme.statusColor(status))
            .padding(.horizontal, Theme.s2)
            .padding(.vertical, 2)
            .background(Theme.statusColor(status).opacity(0.14), in: Capsule())
            .accessibilityLabel("Registry status \(status)")
    }
}

/// Rounded surface card with a subtle border (adapts to appearance). Inner
/// padding follows the interface density.
struct Card<Content: View>: View {
    @ViewBuilder var content: Content
    @Environment(\.interfaceDensity) private var density

    var body: some View {
        content
            .padding(density.cardPadding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .cardSurface()
    }
}

/// Section label above a group of fields.
struct SectionLabel: View {
    let text: String

    var body: some View {
        Text(text.uppercased())
            .font(Typography.captionStrong)
            .tracking(0.6)
            .foregroundStyle(.secondary)
    }
}

/// A labelled numeric input row.
struct NumberField: View {
    let spec: ParamSpec
    @Binding var value: Double

    private var format: FloatingPointFormatStyle<Double> {
        spec.dtype == "int" ? .number.precision(.fractionLength(0)) : .number
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Theme.s3) {
            VStack(alignment: .leading, spacing: 1) {
                Text(spec.label)
                    .font(Typography.bodyMedium)
                if !spec.help.isEmpty {
                    Text(spec.help)
                        .font(Typography.label.weight(.regular))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: Theme.s2)
            TextField(spec.label, value: $value, format: format)
                .textFieldStyle(.roundedBorder)
                .multilineTextAlignment(.trailing)
                .monospacedDigit()
                .frame(width: 112)
                .labelsHidden()
            Text(spec.unit)
                .font(Typography.caption)
                .foregroundStyle(.tertiary)
                .frame(width: 16, alignment: .leading)
        }
        .help(spec.help)
    }
}

/// A labelled choice input row (segmented for 2 options, menu otherwise).
struct ChoiceField: View {
    let spec: ParamSpec
    @Binding var value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Theme.s3) {
            Text(spec.label)
                .font(Typography.bodyMedium)
            Spacer(minLength: Theme.s2)
            picker
        }
        .help(spec.help)
    }

    @ViewBuilder
    private var picker: some View {
        if (spec.choices?.count ?? 0) <= 2 {
            SegmentedBar(items: (spec.choices ?? []).map { ($0, $0) },
                         selection: $value, compact: true)
                .fixedSize()
        } else {
            Picker(spec.label, selection: $value) {
                ForEach(spec.choices ?? [], id: \.self) { choice in
                    Text(choice).tag(choice)
                }
            }
            .labelsHidden()
            .fixedSize()
            .pickerStyle(.menu).neutralControlTint()
        }
    }
}

/// One metric (greek) cell.
struct MetricCell: View {
    let name: String
    let value: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(name.capitalized)
                .font(Typography.caption)
                .foregroundStyle(.secondary)
            Text(value, format: .number.precision(.fractionLength(4)))
                .font(Typography.metricValue)
                .monospacedDigit()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Theme.s3)
        .background(Color(nsColor: .windowBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}
