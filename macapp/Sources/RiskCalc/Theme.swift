import SwiftUI

/// Semantic design tokens. Colours are chosen to read well in both light and
/// dark appearance — surfaces and text use system materials so the window
/// adapts automatically, and only the brand/status accents are fixed.
enum Theme {
    // Brand + status accents (fixed across appearances)
    static let accent   = Color(red: 0.80, green: 0.47, blue: 0.35)   // terracotta
    static let positive = Color(red: 0.13, green: 0.70, blue: 0.38)   // green
    static let negative = Color(red: 0.90, green: 0.27, blue: 0.24)   // red
    static let warning  = Color(red: 0.86, green: 0.60, blue: 0.10)   // amber

    // 4/8 spacing rhythm
    static let s1: CGFloat = 4
    static let s2: CGFloat = 8
    static let s3: CGFloat = 12
    static let s4: CGFloat = 16
    static let s5: CGFloat = 20
    static let s6: CGFloat = 28

    static let radius: CGFloat = 10

    // MARK: Elevation & surfaces
    /// Card corner radius — generous continuous (squircle) corners, floating look.
    static let cardRadius: CGFloat = 16
    /// Clean, solid card fill — paper-white in light, near-black in dark (no grey
    /// translucency). `textBackgroundColor` is the true content white, so cards
    /// read as bright floating panels rather than grey material.
    static let cardFill = Color(nsColor: .textBackgroundColor)
    /// Barely-there edge so a white card keeps definition against a light page.
    static let hairline = Color.primary.opacity(0.05)
    /// Soft, wide ambient shadow — the "float".
    static let cardShadow = Color.black.opacity(0.08)
    /// Tight contact shadow layered under the ambient one for crispness.
    static let cardContactShadow = Color.black.opacity(0.05)
    /// Content column max width — keeps line length comfortable on wide displays.
    static let contentMaxWidth: CGFloat = 1240

    /// Rounded rect used for every card surface.
    static var cardShape: RoundedRectangle {
        RoundedRectangle(cornerRadius: cardRadius, style: .continuous)
    }

    /// Status chip colour for a governance status string.
    static func statusColor(_ status: String) -> Color {
        switch status.lowercased() {
        case "validated":     return positive
        case "approximation": return accent
        case "prototype":     return warning
        case "broken":        return negative
        default:              return .secondary   // placeholder / unknown
        }
    }

    /// Green for gains, red for losses, neutral at zero.
    static func trendColor(_ value: Double) -> Color {
        if value > 0 { return positive }
        if value < 0 { return negative }
        return .secondary
    }

    static let bucketColors: [String: Color] = [
        "Equity": Color(red: 0.36, green: 0.42, blue: 0.95),   // indigo (kept distinct from FX/accent)
        "Rates": Color(red: 0.20, green: 0.66, blue: 0.62),
        "FX": Color(red: 0.85, green: 0.47, blue: 0.18),
        "Volatility": Color(red: 0.60, green: 0.36, blue: 0.86),
        "Credit": Color(red: 0.82, green: 0.30, blue: 0.45),
    ]

    static func bucketColor(_ name: String) -> Color {
        bucketColors[name] ?? accent
    }
}

// MARK: - Formatting helpers

enum Fmt {
    /// Compact money: 2.42M, 94.1k, 512.
    static func money(_ v: Double, currency: String = "") -> String {
        let suffix = currency.isEmpty ? "" : " \(currency)"
        let a = abs(v)
        let sign = v < 0 ? "-" : ""
        switch a {
        case 1_000_000_000...: return "\(sign)\(round1(a / 1e9))B\(suffix)"
        case 1_000_000...:     return "\(sign)\(round1(a / 1e6))M\(suffix)"
        case 1_000...:         return "\(sign)\(round1(a / 1e3))k\(suffix)"
        default:               return "\(sign)\(round1(a))\(suffix)"
        }
    }

    static func number(_ v: Double, digits: Int = 2) -> String {
        v.formatted(.number.precision(.fractionLength(digits)))
    }

    static func percent(_ v: Double, digits: Int = 2) -> String {
        "\(v.formatted(.number.precision(.fractionLength(digits))))%"
    }

    static func signedPercent(_ v: Double, digits: Int = 2) -> String {
        (v >= 0 ? "+" : "") + percent(v, digits: digits)
    }

    /// A tenor expressed in years rendered as a classic money-market / swap
    /// label — O/N, 1W, 1M, 6M, 1Y, 10Y. Display only; the stored tenor stays
    /// in years. Falls back to "{n}Y" / "{n}M" for off-grid values.
    static func tenor(_ years: Double) -> String {
        if years <= 0 { return "0" }
        let days = years * 365.0
        if days < 4.5 { return "\(max(1, Int(days.rounded())))D" }  // 1D (overnight)
        if days < 26 {                                        // weeks
            return "\(Int((days / 7.0).rounded()))W"
        }
        if years < 1 - 1e-6 {                                 // months
            return "\(max(1, Int((years * 12.0).rounded())))M"
        }
        if abs(years - years.rounded()) < 0.02 {              // whole years
            return "\(Int(years.rounded()))Y"
        }
        return "\(Int((years * 12.0).rounded()))M"            // off-grid fallback
    }

    private static func round1(_ v: Double) -> String {
        v >= 100 ? String(Int(v.rounded())) : v.formatted(.number.precision(.fractionLength(1)))
    }
}
