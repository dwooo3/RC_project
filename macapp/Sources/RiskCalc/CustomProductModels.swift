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
    let assets: [String]?
    let slots: [String: CustomSlotSpec]

    var assetNames: [String] { assets?.isEmpty == false ? assets! : ["S"] }
}

/// Market context for the generic MC evaluator; optional fields are omitted
/// from the JSON so the server applies its own defaults.
struct CustomMarketPayload: Encodable, Sendable {
    var r: Double = 0.05
    var q: Double? = nil
    var sigma: Double? = nil
    var sigmas: [Double]? = nil
    var qs: [Double]? = nil
    var rho: Double? = nil
    var corr: [[Double]]? = nil
}

/// Pure helpers for keeping the multi-asset valuation inputs aligned with the
/// product definition.  They live outside SwiftUI so resize/mirroring and the
/// request contract can be pinned by ordinary unit tests.
enum CustomMarketInputGrid {
    static func resizedVector(_ values: [Double], count: Int,
                              defaultValue: Double) -> [Double] {
        let n = max(1, count)
        if values.count >= n { return Array(values.prefix(n)) }
        return values + Array(repeating: defaultValue, count: n - values.count)
    }

    static func resizedCorrelation(_ matrix: [[Double]], count: Int,
                                   defaultOffDiagonal: Double) -> [[Double]] {
        let n = max(1, count)
        var result = Array(repeating: Array(repeating: defaultOffDiagonal,
                                            count: n), count: n)
        for row in 0..<n {
            result[row][row] = 1.0
            for column in (row + 1)..<n {
                let old = existingSymmetricValue(matrix, row: row, column: column)
                let value = old ?? defaultOffDiagonal
                result[row][column] = value
                result[column][row] = value
            }
        }
        return result
    }

    static func settingCorrelation(_ matrix: [[Double]], row: Int,
                                   column: Int, value: Double) -> [[Double]] {
        let n = max(matrix.count, max(row, column) + 1)
        var result = resizedCorrelation(matrix, count: n,
                                        defaultOffDiagonal: 0.0)
        guard row >= 0, column >= 0, row < n, column < n else { return result }
        if row == column {
            result[row][column] = 1.0
        } else {
            result[row][column] = value
            result[column][row] = value
        }
        return result
    }

    static func equicorrelation(count: Int, rho: Double) -> [[Double]] {
        resizedCorrelation([], count: count, defaultOffDiagonal: rho)
    }

    static func validationIssues(sigmas: [Double], qs: [Double],
                                 correlation: [[Double]], assetCount: Int,
                                 rate: Double, nSims: Double, steps: Double,
                                 seed: Double) -> [String] {
        let n = max(1, assetCount)
        var issues: [String] = []
        if !rate.isFinite || rate < -1 || rate > 2 {
            issues.append("Risk-free r должен быть в диапазоне −1 … 2.")
        }
        if sigmas.count != n {
            issues.append("Нужно по одной волатильности на каждый актив (\(n)).")
        } else if sigmas.contains(where: { !$0.isFinite || $0 < 0 || $0 > 5 }) {
            issues.append("Волатильности должны быть в диапазоне 0 … 5.")
        }
        if qs.count != n {
            issues.append("Нужно по одной дивидендной доходности на каждый актив (\(n)).")
        } else if qs.contains(where: { !$0.isFinite || $0 < -1 || $0 > 1 }) {
            issues.append("Дивидендные доходности должны быть в диапазоне −1 … 1.")
        }
        if !isIntegerInRange(nSims, 1_000...200_000) {
            issues.append("MC paths должно быть целым числом 1 000 … 200 000.")
        }
        if !isIntegerInRange(steps, 16...1_024) {
            issues.append("Time steps должно быть целым числом 16 … 1 024.")
        }
        if !seed.isFinite || seed < 0 || seed > Double(Int32.max)
            || seed.rounded() != seed {
            issues.append("Seed должен быть целым числом 0 … \(Int32.max).")
        }
        if n > 1 {
            if !hasValidShape(correlation, count: n) {
                issues.append("Корреляционная матрица должна иметь размер \(n)×\(n).")
            } else if !isSymmetricCorrelation(correlation) {
                issues.append("Корреляции должны быть симметричными, с диагональю 1 и значениями от −0,999 до 0,999.")
            } else if !isPositiveDefinite(correlation) {
                issues.append("Корреляционная матрица должна быть положительно определённой.")
            }
        }
        return issues
    }

    private static func existingSymmetricValue(_ matrix: [[Double]], row: Int,
                                               column: Int) -> Double? {
        if row < matrix.count, column < matrix[row].count {
            return matrix[row][column]
        }
        if column < matrix.count, row < matrix[column].count {
            return matrix[column][row]
        }
        return nil
    }

    private static func isIntegerInRange(_ value: Double,
                                         _ range: ClosedRange<Int>) -> Bool {
        value.isFinite && value.rounded() == value
            && value >= Double(range.lowerBound)
            && value <= Double(range.upperBound)
    }

    private static func hasValidShape(_ matrix: [[Double]], count: Int) -> Bool {
        matrix.count == count && matrix.allSatisfy { $0.count == count }
    }

    private static func isSymmetricCorrelation(_ matrix: [[Double]]) -> Bool {
        for row in matrix.indices {
            if !matrix[row][row].isFinite || abs(matrix[row][row] - 1.0) > 1e-10 {
                return false
            }
            for column in (row + 1)..<matrix.count {
                let value = matrix[row][column]
                if !value.isFinite || value < -0.999 || value > 0.999
                    || abs(value - matrix[column][row]) > 1e-10 {
                    return false
                }
            }
        }
        return true
    }

    /// Cholesky feasibility check matching the backend's fail-closed MC gate.
    private static func isPositiveDefinite(_ matrix: [[Double]]) -> Bool {
        let n = matrix.count
        var lower = Array(repeating: Array(repeating: 0.0, count: n), count: n)
        for row in 0..<n {
            for column in 0...row {
                var sum = matrix[row][column]
                for k in 0..<column { sum -= lower[row][k] * lower[column][k] }
                if row == column {
                    if !sum.isFinite || sum <= 1e-12 { return false }
                    lower[row][column] = sqrt(sum)
                } else {
                    lower[row][column] = sum / lower[column][column]
                }
            }
        }
        return true
    }
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

struct CustomTimelineEntry: Decodable, Sendable, Hashable {
    let t: Double
    let kind: String            // observation | maturity
    let events: [String]
}

struct CustomCompileReport: Decodable, Sendable {
    let ok: Bool
    let issues: [CustomCompileIssue]
    let definitionHash: String
    let summary: String?
    let classification: CustomClassification?
    let compatibleEngines: [String]
    let testVectors: [CustomTestVector]
    let timeline: [CustomTimelineEntry]?    // absent in pre-timeline reports

    enum CodingKeys: String, CodingKey {
        case ok, issues, summary, classification, timeline
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
    let steps: Int?
    let seed: Int
    let engine: String?

    enum CodingKeys: String, CodingKey {
        case value, stderr, state, version, watermark, steps, seed, engine
        case earlyRedemptionProb = "early_redemption_prob"
        case definitionHash = "definition_hash"
        case nSims = "n_sims"
    }
}

struct CustomPriceRequestBody: Encodable, Sendable {
    let slots: [String: Double]
    let market: CustomMarketPayload
    let n_sims: Int
    let steps: Int
    let seed: Int
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

    // ── advanced mode: raw definition documents ──────────
    /// Full product JSON including the AST programs the typed models omit.
    func customProductRaw(_ id: String) async throws -> Data {
        try await getRaw("custom/products/\(id)")
    }

    /// body = {"definition": {...}} serialized by the editor.
    func customUpdateDefinition(_ id: String,
                                body: Data) async throws -> CustomProductDetail {
        try await put("custom/products/\(id)", body: body)
    }

    /// body = {"definition": {...}, "author": ...} for advanced creation.
    func customCreateRaw(_ body: Data) async throws -> CustomProductDetail {
        try await post("custom/products", body: body)
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
                     market: CustomMarketPayload, nSims: Int,
                     steps: Int, seed: Int) async throws -> CustomPriceResult {
        let body = try JSONEncoder().encode(CustomPriceRequestBody(
            slots: slots, market: market, n_sims: nSims,
            steps: steps, seed: seed))
        return try await post("custom/products/\(id)/price", body: body)
    }
}
