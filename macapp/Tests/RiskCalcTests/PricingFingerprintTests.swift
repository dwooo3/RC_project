import XCTest
@testable import RiskCalc

/// Acceptance §27.17: the Swift canonical fingerprint must reproduce the
/// shared versioned vectors byte-for-byte (the Python replica pins the same
/// fixture in tests/test_fingerprint_vectors.py). Plus the §26 Swift unit
/// tests for the workspace state machine primitives.
final class PricingFingerprintTests: XCTestCase {

    private struct VectorFile: Decodable {
        struct Case: Decodable {
            let name: String
            let product: String
            let engine: String
            let env: String?
            let secid: String?
            let numeric: [String: Double]
            let choice: [String: String]
            let expected: String
        }
        let algorithm: String
        let cases: [Case]
    }

    private func loadVectors() throws -> VectorFile {
        guard let url = Bundle.module.url(forResource: "fingerprint_vectors",
                                          withExtension: "json",
                                          subdirectory: "Fixtures") else {
            throw XCTSkip("fingerprint_vectors.json fixture missing")
        }
        return try JSONDecoder().decode(VectorFile.self,
                                        from: Data(contentsOf: url))
    }

    func testSharedVectorsMatchPython() throws {
        let file = try loadVectors()
        XCTAssertEqual(file.algorithm, "pricing-fingerprint-v1")
        XCTAssertGreaterThanOrEqual(file.cases.count, 5)
        for vector in file.cases {
            let got = PricingFingerprint.compute(
                product: vector.product, engine: vector.engine,
                envID: vector.env, numeric: vector.numeric,
                choice: vector.choice, secid: vector.secid)
            XCTAssertEqual(got, vector.expected,
                           "вектор '\(vector.name)' разошёлся с Python")
        }
    }

    func testCanonicalNumberEdges() {
        XCTAssertEqual(PricingFingerprint.canonicalNumber(0.0), "0")
        XCTAssertEqual(PricingFingerprint.canonicalNumber(-0.0), "0")
        XCTAssertEqual(PricingFingerprint.canonicalNumber(100.0), "100")
        XCTAssertEqual(PricingFingerprint.canonicalNumber(-42.0), "-42")
        XCTAssertEqual(PricingFingerprint.canonicalNumber(1e14),
                       "100000000000000")
        XCTAssertEqual(PricingFingerprint.canonicalNumber(100.5), "100.5")
        XCTAssertEqual(PricingFingerprint.canonicalNumber(1.0 / 3.0),
                       "0.333333333333")
        XCTAssertEqual(PricingFingerprint.canonicalNumber(2.5e-07), "2.5e-07")
    }

    func testFingerprintIsOrderIndependentAndSensitive() {
        let a = PricingFingerprint.compute(product: "p", engine: "e",
                                           envID: nil,
                                           numeric: ["x": 1.0, "y": 2.0],
                                           choice: [:], secid: nil)
        let b = PricingFingerprint.compute(product: "p", engine: "e",
                                           envID: nil,
                                           numeric: ["y": 2.0, "x": 1.0],
                                           choice: [:], secid: nil)
        XCTAssertEqual(a, b, "порядок ключей не должен влиять")
        let c = PricingFingerprint.compute(product: "p", engine: "e",
                                           envID: nil,
                                           numeric: ["x": 1.0, "y": 2.000001],
                                           choice: [:], secid: nil)
        XCTAssertNotEqual(a, c)
    }

    // §6.2: technical state busy semantics gate the run controls.
    func testRunTechStateBusy() {
        XCTAssertTrue(RunTechState.validating.isBusy)
        XCTAssertTrue(RunTechState.running.isBusy)
        XCTAssertFalse(RunTechState.idle.isBusy)
        XCTAssertFalse(RunTechState.failed("x").isBusy)
    }
}

/// Advanced editor (§16.1 mode 2): the editable AST must round-trip through
/// the server JSON without losing structure — otherwise «Сохранить и
/// скомпилировать» would silently rewrite the user's product.
@MainActor
final class CustomEditorRoundTripTests: XCTestCase {

    private func phoenixLikeDefinition() -> [String: Any] {
        func n(_ kind: String, _ extra: [String: Any] = [:],
               args: [[String: Any]] = []) -> [String: Any] {
            var node: [String: Any] = ["node": kind]
            extra.forEach { node[$0.key] = $0.value }
            if !args.isEmpty { node["args"] = args }
            return node
        }
        return [
            "name": "RT", "description": "round-trip", "author": "test",
            "assets": ["Asset A", "Asset B"],
            "slots": ["T": ["label": "Maturity", "default": 2.0,
                            "min": 0.25, "max": 10.0]],
            "state": ["memory": 0.0],
            "schedule": ["observations": 8, "maturity": ["slot": "T"]],
            "observation_program": [
                ["action": "accumulate", "name": "memory",
                 "value": n("mul", args: [n("param", ["name": "T"]),
                                          n("accrual")])],
                ["action": "terminate",
                 "when": n("ge", args: [n("worst_of"), n("const", ["value": 1.0])]),
                 "payout": n("add", args: [n("const", ["value": 1.0]),
                                           n("state", ["name": "memory"])])],
            ],
            "maturity_program": [
                ["action": "pay",
                 "amount": n("if", args: [
                     n("le", args: [n("worst_path_min"),
                                    n("const", ["value": 0.65])]),
                     n("asset", ["index": 1]),
                     n("nth_worst", ["rank": 2])])],
            ],
        ]
    }

    func testDefinitionRoundTripPreservesStructure() throws {
        let original = phoenixLikeDefinition()
        let editor = EDefinition.fromJSON(original)
        let restored = editor.toJSON()

        // Canonical-JSON comparison: what the editor sends back must be the
        // same document (modulo key order) it loaded.
        let a = try JSONSerialization.data(withJSONObject: original,
                                           options: [.sortedKeys])
        let b = try JSONSerialization.data(withJSONObject: restored,
                                           options: [.sortedKeys])
        XCTAssertEqual(String(data: a, encoding: .utf8),
                       String(data: b, encoding: .utf8))
    }

    func testTypedKindSwitchPreservesCompatibleChildren() {
        let node = ENode("add", children: [ENode("perf"),
                                           ENode("const", value: 5)])
        node.setKind("mul")                        // number → number
        XCTAssertEqual(node.children.map(\.kind), ["perf", "const"])
        node.setKind("ge")                         // args stay number-typed
        XCTAssertEqual(node.children.map(\.kind), ["perf", "const"])
        node.setKind("and")                        // bool args — defaults
        XCTAssertEqual(node.children.count, 2)
        XCTAssertTrue(node.children.allSatisfy {
            exprKinds[$0.kind]?.result == .bool
        })
    }
}
