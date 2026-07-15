import Foundation
import CryptoKit

// MARK: - Pricing workspace state machines (spec §6)
//
// Two orthogonal levels of state: the business lifecycle of the workspace
// (Draft → Validated → Priced → Captured, with edits making prior evidence
// stale) and the technical state of the current calculation. Both are derived
// from immutable evidence — input fingerprints — rather than mutable flags,
// so an edit can never leave the UI claiming a stale result is current.

/// Business state of the workspace (spec §6.1). `Approved` is intentionally
/// absent: the v1 bridge has no approval policy — a capability gap surfaced
/// in the UI, not silently faked.
enum WorkspaceBusinessState: String, CaseIterable {
    case draft = "Draft"
    case validated = "Validated"
    case priced = "Priced"
    case captured = "Captured"

    var title: String { rawValue }

    var icon: String {
        switch self {
        case .draft:     return "pencil"
        case .validated: return "checkmark.shield"
        case .priced:    return "equal.circle"
        case .captured:  return "tray.and.arrow.down"
        }
    }
}

/// Technical state of the current calculation (spec §6.2, sync subset —
/// the v1 bridge prices synchronously; queued/partial arrive with async jobs).
enum RunTechState: Equatable {
    case idle
    case validating
    case running
    case failed(String)

    var isBusy: Bool { self == .validating || self == .running }
}

/// One immutable completed run: the exact inputs, the result and the server
/// evidence. History entries are never mutated by later edits (spec §6.1).
struct PricingRunRecord: Identifiable, Sendable {
    let id = UUID()
    let timestamp: Date
    let fingerprint: String                    // local canonical fingerprint
    let productID: String
    let productName: String
    let engineID: String
    let engineName: String
    let envID: String?
    let numericValues: [String: Double]        // input snapshot
    let choiceValues: [String: String]
    let underlyingSecID: String?
    let result: WsResult

    var shortHash: String { String(fingerprint.prefix(8)) }
    var serverHash: String? { result.provenance?.inputsHash }
}

// MARK: - Canonical input fingerprint

/// Deterministic local fingerprint of the resolved user intent: product,
/// engine, environment and every parameter, canonically serialized (sorted
/// keys, normalized decimals) and SHA-256 hashed. Used for staleness detection
/// and run identity on the client; the server's `inputs_hash` (provenance)
/// remains the authoritative evidence for a completed run (spec §9.1).
enum PricingFingerprint {
    static func compute(product: String, engine: String, envID: String?,
                        numeric: [String: Double], choice: [String: String],
                        secid: String?) -> String {
        var parts: [String] = [
            "product=\(product)",
            "engine=\(engine)",
            "env=\(envID ?? "")",
            "secid=\(secid ?? "")",
        ]
        for key in numeric.keys.sorted() {
            parts.append("n:\(key)=\(canonicalNumber(numeric[key] ?? 0))")
        }
        for key in choice.keys.sorted() {
            parts.append("s:\(key)=\(choice[key] ?? "")")
        }
        let preimage = "pricing-fingerprint-v1\u{0}" + parts.joined(separator: "\u{1}")
        let digest = SHA256.hash(data: Data(preimage.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    /// Canonical decimal text: no exponent for typical magnitudes, trailing
    /// fractional zeros removed, `-0` normalized to `0` (spec §9.1 subset).
    static func canonicalNumber(_ v: Double) -> String {
        if v == 0 { return "0" }                       // covers -0.0
        if v == v.rounded() && abs(v) < 1e15 {
            return String(Int64(v))
        }
        var s = String(format: "%.12g", v)
        if s.contains(".") && !s.contains("e") && !s.contains("E") {
            while s.hasSuffix("0") { s.removeLast() }
            if s.hasSuffix(".") { s.removeLast() }
        }
        return s
    }
}
