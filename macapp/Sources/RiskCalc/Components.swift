import SwiftUI

/// Small coloured status capsule (governance status).
struct StatusChip: View {
    let status: String

    var body: some View {
        Text(status)
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(Theme.statusColor(status))
            .padding(.horizontal, Theme.s2)
            .padding(.vertical, 2)
            .background(Theme.statusColor(status).opacity(0.14), in: Capsule())
            .accessibilityLabel("Model status \(status)")
    }
}

/// Rounded surface card with a subtle border (adapts to appearance).
struct Card<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(Theme.s4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor), in: Theme.cardShape)
            .overlay(Theme.cardShape.strokeBorder(Theme.hairline, lineWidth: 1))
            .shadow(color: Theme.cardShadow, radius: 8, x: 0, y: 2)
    }
}

/// Section label above a group of fields.
struct SectionLabel: View {
    let text: String

    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 11, weight: .semibold))
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
                    .font(.system(size: 12, weight: .medium))
                if !spec.help.isEmpty {
                    Text(spec.help)
                        .font(.system(size: 10))
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
                .font(.system(size: 11))
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
                .font(.system(size: 12, weight: .medium))
            Spacer(minLength: Theme.s2)
            picker
        }
        .help(spec.help)
    }

    @ViewBuilder
    private var picker: some View {
        let base = Picker(spec.label, selection: $value) {
            ForEach(spec.choices ?? [], id: \.self) { choice in
                Text(choice).tag(choice)
            }
        }
        .labelsHidden()
        .fixedSize()

        if (spec.choices?.count ?? 0) <= 2 {
            base.pickerStyle(.segmented)
        } else {
            base.pickerStyle(.menu)
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
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)
            Text(value, format: .number.precision(.fractionLength(4)))
                .font(.system(size: 15, weight: .semibold))
                .monospacedDigit()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Theme.s3)
        .background(Color(nsColor: .windowBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}
