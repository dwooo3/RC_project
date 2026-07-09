import Foundation

struct Governance: Decodable, Hashable, Sendable {
    let status: String
    let assetClass: String
    let modelFamily: String
    let method: String
    let notes: String
    let productionAllowed: Bool
    let analyticsLabOnly: Bool

    enum CodingKeys: String, CodingKey {
        case status, method, notes
        case assetClass = "asset_class"
        case modelFamily = "model_family"
        case productionAllowed = "production_allowed"
        case analyticsLabOnly = "analytics_lab_only"
    }
}

struct ParamSpec: Decodable, Identifiable, Hashable, Sendable {
    var id: String { key }
    let key: String
    let label: String
    let group: String          // contract | market | model | numerical
    let dtype: String          // float | int | choice | text
    let choices: [String]?
    let minimum: Double?
    let maximum: Double?
    let advanced: Bool
    let unit: String
    let help: String
    let defaultValue: ParamDefault

    enum CodingKeys: String, CodingKey {
        case key, label, group, dtype, choices, minimum, maximum, advanced, unit, help
        case defaultValue = "default"
    }
}

/// A spec default that may arrive as a number or a string.
enum ParamDefault: Decodable, Hashable, Sendable {
    case number(Double)
    case string(String)

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let d = try? c.decode(Double.self) {
            self = .number(d)
        } else if let s = try? c.decode(String.self) {
            self = .string(s)
        } else {
            self = .string("")
        }
    }
}

/// Minimal JSON value used to decode the heterogeneous `raw` engine payload.
enum JSONValue: Decodable, Hashable, Sendable {
    case number(Double)
    case string(String)
    case bool(Bool)
    case array([JSONValue])
    case object([String: JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .null
        } else if let b = try? c.decode(Bool.self) {
            self = .bool(b)
        } else if let d = try? c.decode(Double.self) {
            self = .number(d)
        } else if let s = try? c.decode(String.self) {
            self = .string(s)
        } else if let a = try? c.decode([JSONValue].self) {
            self = .array(a)
        } else if let o = try? c.decode([String: JSONValue].self) {
            self = .object(o)
        } else {
            self = .null
        }
    }

    var doubleValue: Double? {
        if case .number(let d) = self { return d }
        return nil
    }
}
