import SwiftUI

// MARK: - Card surface

extension View {
    /// The app's single card look — Liquid Glass on macOS 26 (matching the
    /// toolbar pill), a soft floating panel as the fallback. Used by every
    /// card/panel for consistency.
    ///
    /// The glass carries a `cardFill` tint: untinted `.regular` glass samples
    /// whatever sits behind each card, so panels drift apart in tone and go
    /// nearly invisible when the window resigns key (worst in dark mode).
    /// Tinting pins every surface to the same base while keeping the glass
    /// edge lensing and highlights; the tint strength follows the design
    /// panel's translucency setting.
    @ViewBuilder
    func cardSurface(cornerRadius: CGFloat = Theme.cardRadius) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        let design = DesignSettings.shared
        if #available(macOS 26.0, *), design.isVibrant {
            self.glassEffect(.regular.tint(Theme.cardFill.opacity(design.cardTintOpacity)), in: shape)
        } else {
            self.background(Theme.cardFill, in: shape)
                .shadow(color: Theme.cardShadow,
                        radius: design.cardShadowRadius, x: 0, y: design.cardShadowY)
                .shadow(color: Theme.cardContactShadow, radius: 1.5, x: 0, y: 1)
        }
    }
}

// MARK: - Window surface

/// The app's base surface — ONE continuous matte frosted sheet (the classic
/// sidebar material, behind-window blending) under the sidebar, the content
/// area and the titlebar alike. The shell deliberately avoids
/// NavigationSplitView so nothing draws its own column material or divider on
/// top of this sheet; content cards float above it with their Liquid Glass
/// surface. Dragging translucency to the far left swaps in an opaque fill.
struct WindowBackground: View {
    var body: some View {
        // Continuously tunable: a neutral windowBackground wash over the
        // frosted sheet. 0 = raw frost, 1 = fully opaque (vibrancy dropped
        // entirely so an inactive window doesn't flicker the effect).
        let wash = DesignSettings.shared.backgroundOpacity
        if wash >= 0.98 {
            Color(nsColor: .windowBackgroundColor).ignoresSafeArea()
        } else {
            VibrancyBackground(material: .sidebar)
                .overlay(Color(nsColor: .windowBackgroundColor).opacity(wash))
                .ignoresSafeArea()
        }
    }
}

/// NSVisualEffectView bridge — SwiftUI has no behind-window vibrancy API.
private struct VibrancyBackground: NSViewRepresentable {
    let material: NSVisualEffectView.Material

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = .behindWindow
        view.state = .followsWindowActiveState
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
    }
}

// MARK: - Control tint (macOS 27 workaround)

extension View {
    /// macOS 27 (beta) started painting menu-picker labels with the window
    /// tint, so every dropdown went brand-orange. Pin the control back to the
    /// neutral label colour; effectively a no-op on macOS 26 where menu
    /// labels were neutral already.
    func neutralControlTint() -> some View { self.tint(Color.primary) }
}

// MARK: - Segmented control

/// A segmented control drawn in the app's card idiom: a clean white floating
/// track with a solid accent-filled pill for the selection. Sizes to content.
/// Generic over any `Hashable` tag so it works for string- and int-keyed sets.
struct SegmentedBar<Tag: Hashable>: View {
    let items: [(Tag, String)]           // (tag, label)
    @Binding var selection: Tag
    var compact: Bool = false            // tighter padding/type for inline use

    var body: some View {
        HStack(spacing: 2) {
            ForEach(items, id: \.0) { item in
                segment(item.0, item.1)
            }
        }
        .padding(compact ? 3 : 4)
        .cardSurface(cornerRadius: compact ? 10 : 12)
    }

    private func segment(_ tag: Tag, _ label: String) -> some View {
        let on = selection == tag
        return Button {
            withAnimation(.snappy(duration: 0.2)) { selection = tag }
        } label: {
            Text(label)
                .font(.system(size: compact ? 11 : 13, weight: on ? .semibold : .regular))
                .foregroundStyle(on ? Color.white : .secondary)
                .padding(.horizontal, compact ? Theme.s3 : Theme.s4)
                .padding(.vertical, compact ? 4 : 6)
                .background {
                    if on {
                        RoundedRectangle(cornerRadius: compact ? 7 : 8, style: .continuous)
                            .fill(Theme.accent)
                    }
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

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
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(Typography.pageTitle)
                Text(subtitle).font(Typography.subtitle).foregroundStyle(.secondary)
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
            Text(text).font(Typography.sectionTitle)
        }
    }
}

/// Clean, elevated white surface card — the floating-panel look. Inner padding
/// follows the interface density unless overridden.
struct GlassCard<Content: View>: View {
    var padding: CGFloat? = nil
    @ViewBuilder var content: Content
    @Environment(\.interfaceDensity) private var density

    var body: some View {
        content
            .padding(padding ?? density.cardPadding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .cardSurface()
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
    @Environment(\.interfaceDensity) private var density

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            HStack(spacing: Theme.s2) {
                if let icon {
                    Image(systemName: icon)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(accent)
                        .frame(width: 26, height: 26)
                        .background(accent.opacity(0.16), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                Text(label.uppercased())
                    .font(Typography.label)
                    .tracking(0.6)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                Spacer(minLength: 0)
            }
            Text(value)
                .font(Typography.cardValue)
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.55)
                .contentTransition(.numericText())
            if let trend {
                HStack(spacing: 3) {
                    Image(systemName: trend >= 0 ? "arrow.up.right" : "arrow.down.right")
                    Text(Fmt.signedPercent(trend))
                }
                .font(Typography.captionStrong)
                .foregroundStyle(Theme.changeColor(trend))
            } else if let sub {
                Text(sub).font(Typography.caption).foregroundStyle(.tertiary).lineLimit(1)
            }
        }
        .padding(density.cardPadding)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            // faint accent wash so each metric carries a hint of its colour,
            // sitting over the clean white card fill
            LinearGradient(colors: [accent.opacity(0.10), .clear],
                           startPoint: .topLeading, endPoint: .bottomTrailing),
            in: Theme.cardShape
        )
        .cardSurface()
    }
}

/// Responsive KPI strip. Cards share the row equally and stretch to fill the
/// full content width — up to `maxColumns` across, wrapping on narrow windows.
struct KPIStrip: View {
    let items: [KPICard]
    var maxColumns: Int = 5

    var body: some View {
        let count = max(1, min(items.count, maxColumns))
        let columns = Array(
            repeating: GridItem(.flexible(minimum: 150), spacing: Theme.s3),
            count: count
        )
        LazyVGrid(columns: columns, spacing: Theme.s3) {
            ForEach(items, id: \.label) { card in card }
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
            .font(Typography.label)
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
            Text(label).font(Typography.caption).foregroundStyle(.secondary)
        }
        .padding(.horizontal, Theme.s3).padding(.vertical, Theme.s2)
        .background(Color.primary.opacity(0.06), in: Capsule())
    }
}

/// A labelled key/value row used inside cards.
struct KeyValueRow: View {
    let key: String
    let value: String
    var valueColor: Color = .primary

    var body: some View {
        HStack {
            Text(key).font(Typography.body).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(Typography.bodyMedium).monospacedDigit().foregroundStyle(valueColor)
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
            SkeletonScreen()
        case .failed(let message):
            ContentUnavailableView {
                Label("Не удалось загрузить данные", systemImage: "exclamationmark.triangle")
            } description: {
                Text(message).font(Typography.caption)
            } actions: {
                Button("Повторить", action: retry).buttonStyle(.borderedProminent).tint(Theme.accent)
            }
            .frame(maxWidth: .infinity, minHeight: 280)
        case .loaded(let value):
            content(value)
        }
    }
}
