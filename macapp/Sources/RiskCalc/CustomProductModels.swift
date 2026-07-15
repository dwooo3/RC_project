import Foundation

// MARK: - Custom Product Engine models (spec §16)
//
// Template-mode client: the UI renders ANY definition from its slot schema —
// no product-specific Swift. Programs/AST stay opaque server-side documents.

struct CustomProductSummary: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let name: String
    let version: Int
    let state: String
    let author: String
    let definitionHash: String
    let isTemplate: Bool
    let versions: Int

    enum CodingKeys: String, CodingKey {
        case id, name, version, state, author, versions
        case definitionHash = "definition_hash"
        case isTemplate = "is_template"
    }
}

struct CustomSlotSpec: Decodable, Sendable, Hashable {
    let label: String?
    let defaultValue: Double
    let min: Double?
    let max: Double?

    enum CodingKeys: String, CodingKey {
        case label, min, max
        case defaultValue = "default"
    }
}

struct CustomDefinitionDoc: Decodable, Sendable {
    let name: String
    let description: String?
    let author: String?
    let slots: [String: CustomSlotSpec]
}

struct CustomCompileIssue: Decodable, Sendable, Hashable, Identifiable {
    let code: String
    let severity: String
    let message: String
    let path: String
    var id: String { code + path + message }
}

struct CustomTestVector: Decodable, Sendable, Hashable {
    let scenario: String
    let terminalPerf: Double
    let pv: Double

    enum CodingKeys: String, CodingKey {
        case scenario, pv
        case terminalPerf = "terminal_perf"
    }
}

struct CustomClassification: Decodable, Sendable {
    let pathDependent: Bool
    let earlyRedemption: Bool
    let underlyings: Int
    let dynamics: String

    enum CodingKeys: String, CodingKey {
        case underlyings, dynamics
        case pathDependent = "path_dependent"
        case earlyRedemption = "early_redemption"
    }
}

struct CustomCompileReport: Decodable, Sendable {
    let ok: Bool
    let issues: [CustomCompileIssue]
    let definitionHash: String
    let summary: String?
    let classification: CustomClassification?
    let compatibleEngines: [String]
    let testVectors: [CustomTestVector]

    enum CodingKeys: String, CodingKey {
        case ok, issues, summary, classification
        case definitionHash = "definition_hash"
        case compatibleEngines = "compatible_engines"
        case testVectors = "test_vectors"
    }
}

struct CustomProductDetail: Decodable, Sendable {
    let id: String
    let version: Int
    let state: String
    let definition: CustomDefinitionDoc
    let definitionHash: String
    let author: String
    let submittedBy: String?
    let approvedBy: String?
    let compileReport: CustomCompileReport?
    let isTemplate: Bool

    enum CodingKeys: String, CodingKey {
        case id, version, state, definition, author
        case definitionHash = "definition_hash"
        case submittedBy = "submitted_by"
        case approvedBy = "approved_by"
        case compileReport = "compile_report"
        case isTemplate = "is_template"
    }
}

struct CustomPriceResult: Decodable, Sendable {
    let value: Double
    let stderr: Double
    let earlyRedemptionProb: Double
    let definitionHash: String
    let state: String
    let version: Int
    let watermark: String?
    let nSims: Int
    let seed: Int

    enum CodingKeys: String, CodingKey {
        case value, stderr, state, version, watermark, seed
        case earlyRedemptionProb = "early_redemption_prob"
        case definitionHash = "definition_hash"
        case nSims = "n_sims"
    }
}

// MARK: - Bridge calls

extension BridgeClient {
    func customTemplates() async throws -> [CustomProductSummary] {
        struct Resp: Decodable { let templates: [CustomProductSummary] }
        return try await get("custom/templates", as: Resp.self).templates
    }

    func customProducts() async throws -> [CustomProductSummary] {
        struct Resp: Decodable { let products: [CustomProductSummary] }
        return try await get("custom/products", as: Resp.self).products
    }

    func customProduct(_ id: String) async throws -> CustomProductDetail {
        try await get("custom/products/\(id)")
    }

    func customCreate(templateID: String, name: String, author: String,
                      slotDefaults: [String: Double]) async throws -> CustomProductDetail {
        struct Body: Encodable {
            let template_id: String
            let name: String
            let author: String
            let slot_defaults: [String: Double]
        }
        let body = try JSONEncoder().encode(Body(
            template_id: templateID, name: name, author: author,
            slot_defaults: slotDefaults))
        return try await post("custom/products", body: body)
    }

    func customCompile(_ id: String) async throws -> CustomProductDetail {
        try await post("custom/products/\(id)/compile", body: Data("{}".utf8))
    }

    private func customAction(_ id: String, _ action: String,
                              user: String) async throws -> CustomProductDetail {
        struct Body: Encodable { let user: String }
        let body = try JSONEncoder().encode(Body(user: user))
        return try await post("custom/products/\(id)/\(action)", body: body)
    }

    func customSubmit(_ id: String, user: String) async throws -> CustomProductDetail {
        try await customAction(id, "submit", user: user)
    }

    func customApprove(_ id: String, user: String) async throws -> CustomProductDetail {
        try await customAction(id, "approve", user: user)
    }

    func customPublish(_ id: String) async throws -> CustomProductDetail {
        try await post("custom/products/\(id)/publish", body: Data("{}".utf8))
    }

    func customNewVersion(_ id: String, user: String) async throws -> CustomProductDetail {
        try await customAction(id, "versions", user: user)
    }

    func customPrice(_ id: String, slots: [String: Double],
                     market: [String: Double], nSims: Int,
                     seed: Int) async throws -> CustomPriceResult {
        struct Body: Encodable {
            let slots: [String: Double]
            let market: [String: Double]
            let n_sims: Int
            let seed: Int
        }
        let body = try JSONEncoder().encode(Body(
            slots: slots, market: market, n_sims: nSims, seed: seed))
        return try await post("custom/products/\(id)/price", body: body)
    }
}
