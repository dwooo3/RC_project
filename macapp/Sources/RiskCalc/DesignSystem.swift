import SwiftUI

// MARK: - Page scaffolding

/// Large screen header with title, subtitle and optional trailing accessory.
struct PageHeader<Trailing: View>: View {
    let title: String
    let subtitle: String
    @ViewBuilder var trailing: Trailing

    init(_ title: String, subtitle: String, @ViewBuilder trailing: () -> Trailing = { EmptyView() }) {
        self.title = title
        self.subtitle = subtitle
        self.trailing = trailing()
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.system(size: 26, weight: .bold))
                Text(subtitle).font(.system(size: 13)).foregroundStyle(.secondary)
            }
            Spacer()
            trailing
        }
    }
}

/// Section title used between content blocks.
struct BlockTitle: View {
    let text: String
    var icon: String?

    init(_ text: String, icon: String? = nil) {
        self.text = text
        self.icon = icon
    }

    var body: some View {
        HStack(spacing: Theme.s2) {
            if let icon { Image(systemName: icon).foregroundStyle(Theme.accent) }
            Text(text).font(.system(size: 15, weight: .semibold))
        }
    }
}

/// Translucent surface card (Liquid-Glass friendly).
struct GlassCard<Content: View>: View {
    var padding: CGFloat = Theme.s4
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: Theme.radius))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.radius)
                    .strokeBorder(Color.primary.opacity(0.06), lineWidth: 1)
            )
    }
}

// MARK: - KPI

/// Headline metric tile with optional trend and accent.
struct KPICard: View {
    let label: String
    let value: String
    var sub: String? = nil
    var trend: Double? = nil
    var accent: Color = Theme.accent
    var icon: String? = nil

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s2) {
                HStack(spacing: Theme.s2) {
                    if let icon {
                        Image(systemName: icon)
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(accent)
                            .frame(width: 22, height: 22)
                            .background(accent.opacity(0.14), in: RoundedRectangle(cornerRadius: 6))
                    }
                    Text(label.uppercased())
                        .font(.system(size: 10, weight: .semibold))
                        .tracking(0.5)
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                Text(value)
                    .font(.system(size: 24, weight: .bold))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                if let trend {
                    HStack(spacing: 3) {
                        Image(systemName: trend >= 0 ? "arrow.up.right" : "arrow.down.right")
                        Text(Fmt.signedPercent(trend))
                    }
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Theme.trendColor(trend))
                } else if let sub {
                    Text(sub).font(.system(size: 11)).foregroundStyle(.tertiary).lineLimit(1)
                }
            }
        }
    }
}

/// Responsive KPI strip.
struct KPIStrip: View {
    let items: [KPICard]
    var minWidth: CGFloat = 180

    var body: some View {
        LazyVGrid(
            columns: [GridItem(.adaptive(minimum: minWidth), spacing: Theme.s3)],
            spacing: Theme.s3
        ) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, card in card }
        }
    }
}

// MARK: - Small bits

/// Neutral info pill.
struct Pill: View {
    let text: String
    var color: Color = .secondary
    var filled: Bool = false

    var body: some View {
        Text(text)
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(filled ? Color.white : color)
            .padding(.horizontal, Theme.s2)
            .padding(.vertical, 2)
            .background(color.opacity(filled ? 0.9 : 0.14), in: Capsule())
    }
}

/// Live/demo data-source badge.
struct SourceBadge: View {
    let live: Bool
    let label: String

    var body: some View {
        HStack(spacing: Theme.s2) {
            Circle().fill(live ? Theme.positive : Theme.warning).frame(width: 7, height: 7)
            Text(label).font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
        }
        .padding(.horizontal, Theme.s3).padding(.vertical, Theme.s2)
        .background(.regularMaterial, in: Capsule())
    }
}

/// A labelled key/value row used inside cards.
struct KeyValueRow: View {
    let key: String
    let value: String
    var valueColor: Color = .primary

    var body: some View {
        HStack {
            Text(key).font(.system(size: 12)).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(valueColor)
        }
    }
}

// MARK: - Async state wrappers

/// Renders content for a loaded value, or a spinner / error placeholder.
struct LoadableView<T, Content: View>: View {
    let state: Loadable<T>
    let retry: () -> Void
    @ViewBuilder var content: (T) -> Content

    var body: some View {
        switch state {
        case .idle, .loading:
            VStack(spacing: Theme.s3) {
                ProgressView().controlSize(.large)
                Text("Loading…").font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 280, alignment: .center)
        case .failed(let message):
            ContentUnavailableView {
                Label("Couldn't load data", systemImage: "exclamationmark.triangle")
            } description: {
                Text(message).font(.caption)
            } actions: {
                Button("Retry", action: retry).buttonStyle(.borderedProminent)
            }
        case .loaded(let value):
            content(value)
        }
    }
}
