import SwiftUI
import AppKit
import Observation

// MARK: - Store

/// User-tunable design tokens, persisted in UserDefaults.
///
/// Read through `Theme` (`Theme.accent`, `Theme.cardFill`, …) rather than
/// directly: because this is `@Observable`, any read inside a view body — even
/// via those static helpers — registers a dependency, so moving a slider
/// invalidates exactly the views that use the token. No app restart, no forced
/// rebuild of the whole tree.
@Observable
final class DesignSettings {
    /// UI-only state, mutated from the main actor by the design panel.
    nonisolated(unsafe) static let shared = DesignSettings()

    var theme: AppTheme { didSet { write(theme.rawValue, Keys.theme) } }
    var density: InterfaceDensity { didSet { write(density.rawValue, Keys.density) } }

    /// Accent hue/saturation (0…1). Brightness is fixed so any hue stays a
    /// usable UI accent.
    var accentHue: Double { didSet { write(accentHue, Keys.accentHue) } }
    var accentSaturation: Double { didSet { write(accentSaturation, Keys.accentSaturation) } }

    /// Card glass: 0 = solid cards · 1 = maximum see-through.
    var translucency: Double { didSet { write(translucency, Keys.translucency) } }

    /// Window sheet: opacity of the neutral wash over the matte backdrop.
    /// 0 = pure frosted glass · 1 = fully opaque window background.
    var backgroundOpacity: Double { didSet { write(backgroundOpacity, Keys.backgroundOpacity) } }

    /// Card/panel tone: 0 = darker than default · 0.5 = default · 1 = lighter.
    var surfaceLevel: Double { didSet { write(surfaceLevel, Keys.surfaceLevel) } }

    /// Card corner radius in points.
    var cornerRadius: Double { didSet { write(cornerRadius, Keys.cornerRadius) } }

    /// 0 = no card shadows · 1 = pronounced.
    var shadowStrength: Double { didSet { write(shadowStrength, Keys.shadowStrength) } }

    // MARK: derived tokens

    /// Brand accent built from the hue/saturation sliders.
    var accentColor: Color {
        Color(hue: accentHue, saturation: accentSaturation, brightness: 0.80)
    }

    /// Whether window surfaces let the desktop through.
    var isVibrant: Bool { translucency > 0.02 }

    /// Tint strength of the glass card surface — higher reads as more opaque.
    var cardTintOpacity: Double { 1.0 - 0.68 * translucency }

    /// Card fill for the current tone, resolved per appearance. Dark stays an
    /// elevated grey (never near-black, or cards read as holes); light tops out
    /// at paper white.
    var cardFillColor: Color {
        let grey = 0.10 + 0.14 * surfaceLevel                 // 0.17 at the default
        let dark = NSColor(srgbRed: grey, green: grey, blue: grey + 0.015, alpha: 1)
        let w = min(1.0, 0.86 + 0.28 * surfaceLevel)          // white at the default
        let light = NSColor(srgbRed: w, green: w, blue: w, alpha: 1)
        return Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
        })
    }

    /// Ambient shadow under a card. Kept soft even at full strength: a heavy
    /// shadow gets clipped by scroll bounds and reads as a phantom border.
    var cardShadowColor: Color { .black.opacity(0.18 * shadowStrength) }
    var cardContactShadowColor: Color { .black.opacity(0.12 * shadowStrength) }
    var cardShadowRadius: Double { 4 + 14 * shadowStrength }
    var cardShadowY: Double { 1 + 5 * shadowStrength }

    // MARK: persistence

    private enum Keys {
        static let theme = "appTheme"          // shared with the sidebar toggle
        static let density = "designDensity"
        static let accentHue = "designAccentHue"
        static let accentSaturation = "designAccentSaturation"
        static let translucency = "designTranslucency2"
        static let backgroundOpacity = "designBackgroundOpacity"
        static let surfaceLevel = "designSurfaceLevel"
        static let cornerRadius = "designCornerRadius"
        static let shadowStrength = "designShadowStrength"
    }

    private enum Default {
        static let accentHue = 0.044           // terracotta — the brand accent
        static let accentSaturation = 0.56
        static let translucency = 0.5
        static let backgroundOpacity = 0.4     // noticeably whiter than raw frost
        static let surfaceLevel = 0.5
        static let cornerRadius = 16.0
        static let shadowStrength = 0.3
    }

    private init() {
        let d = UserDefaults.standard
        theme = AppTheme(rawValue: d.string(forKey: Keys.theme) ?? "") ?? .system
        density = InterfaceDensity(rawValue: d.string(forKey: Keys.density) ?? "") ?? .compact
        accentHue = d.object(forKey: Keys.accentHue) as? Double ?? Default.accentHue
        accentSaturation = d.object(forKey: Keys.accentSaturation) as? Double ?? Default.accentSaturation
        translucency = d.object(forKey: Keys.translucency) as? Double ?? Default.translucency
        backgroundOpacity = d.object(forKey: Keys.backgroundOpacity) as? Double ?? Default.backgroundOpacity
        surfaceLevel = d.object(forKey: Keys.surfaceLevel) as? Double ?? Default.surfaceLevel
        cornerRadius = d.object(forKey: Keys.cornerRadius) as? Double ?? Default.cornerRadius
        shadowStrength = d.object(forKey: Keys.shadowStrength) as? Double ?? Default.shadowStrength
    }

    private func write(_ value: String, _ key: String) { UserDefaults.standard.set(value, forKey: key) }
    private func write(_ value: Double, _ key: String) { UserDefaults.standard.set(value, forKey: key) }

    func reset() {
        theme = .system
        density = .compact
        accentHue = Default.accentHue
        accentSaturation = Default.accentSaturation
        translucency = Default.translucency
        backgroundOpacity = Default.backgroundOpacity
        surfaceLevel = Default.surfaceLevel
        cornerRadius = Default.cornerRadius
        shadowStrength = Default.shadowStrength
    }
}

// MARK: - Panel

/// Sidebar-footer button that opens the design panel in a popover.
struct DesignSettingsButton: View {
    @State private var open = false
    @State private var hovering = false

    var body: some View {
        Button { open.toggle() } label: {
            Image(systemName: "slider.horizontal.3")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .frame(width: 24, height: 24)
                .background(
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .fill(hovering ? Color.primary.opacity(0.06) : Color.clear)
                )
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .help("Настройки оформления")
        .popover(isPresented: $open, arrowEdge: .top) {
            DesignSettingsPanel(settings: DesignSettings.shared)
        }
    }
}

/// Compact appearance panel — theme, accent, translucency, surface tone and
/// interface density. Every control writes straight through to the store, and
/// the app repaints live as the sliders move.
struct DesignSettingsPanel: View {
    @Bindable var settings: DesignSettings

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s4) {
            Text("Оформление").font(.system(size: 14, weight: .semibold))

            field("Тема") {
                Picker("", selection: $settings.theme) {
                    ForEach(AppTheme.allCases) { Text($0.title).tag($0) }
                }
                .labelsHidden().pickerStyle(.segmented)
            }

            accentField
            slider("Фон окна", value: $settings.backgroundOpacity,
                   low: "Стекло", high: "Плотный")
            slider("Стекло блоков", value: $settings.translucency,
                   low: "Плотное", high: "Прозрачное")
            slider("Тон блоков", value: $settings.surfaceLevel,
                   low: "Темнее", high: "Светлее")
            slider("Тени блоков", value: $settings.shadowStrength,
                   low: "Нет", high: "Выражены")
            slider("Скругление углов", value: $settings.cornerRadius, in: 8...24,
                   low: "Меньше", high: "Больше")

            field("Плотность") {
                Picker("", selection: $settings.density) {
                    ForEach(InterfaceDensity.allCases) { Text($0.title).tag($0) }
                }
                .labelsHidden().pickerStyle(.segmented)
            }

            Divider().opacity(0.5)
            HStack {
                Text("Настройки сохраняются между запусками")
                    .font(Typography.micro).foregroundStyle(.tertiary)
                Spacer()
                Button("Сбросить") { settings.reset() }
                    .buttonStyle(.bordered).controlSize(.small)
            }
        }
        .padding(Theme.s4)
        .frame(width: 340)
    }

    // MARK: pieces

    private var accentField: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: Theme.s2) {
                Text("АКЦЕНТ").font(Typography.label).tracking(0.5).foregroundStyle(.secondary)
                Circle().fill(settings.accentColor).frame(width: 14, height: 14)
                    .overlay(Circle().strokeBorder(Color.primary.opacity(0.12), lineWidth: 1))
                Spacer()
            }
            // Hue legend — the strip shows where the slider lands.
            LinearGradient(colors: stride(from: 0.0, through: 1.0, by: 0.05).map {
                Color(hue: $0, saturation: settings.accentSaturation, brightness: 0.80)
            }, startPoint: .leading, endPoint: .trailing)
                .frame(height: 6)
                .clipShape(Capsule())
            Slider(value: $settings.accentHue, in: 0...1)
            HStack(spacing: Theme.s2) {
                Text("Насыщенность").font(Typography.micro).foregroundStyle(.tertiary)
                Slider(value: $settings.accentSaturation, in: 0.15...0.95)
            }
        }
    }

    private func slider(_ label: String, value: Binding<Double>,
                        in range: ClosedRange<Double> = 0...1,
                        low: String, high: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label.uppercased()).font(Typography.label).tracking(0.5).foregroundStyle(.secondary)
            Slider(value: value, in: range)
            HStack {
                Text(low).font(Typography.micro).foregroundStyle(.tertiary)
                Spacer()
                Text(high).font(Typography.micro).foregroundStyle(.tertiary)
            }
        }
    }

    private func field<Content: View>(_ label: String,
                                      @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label.uppercased())
                .font(Typography.label).tracking(0.5).foregroundStyle(.secondary)
            content()
        }
    }
}
