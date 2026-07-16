import XCTest
@testable import RiskCalc

final class QW1GovernanceContractTests: XCTestCase {
    private func eligibilityJSON(runtime: String, status: String,
                                 production: Bool, workflow: String,
                                 approvalActive: Bool = true) -> String {
        let active = production && approvalActive
        let approvalBasis = production ? "legacy_transition" : "none"
        let approvalRef = production ? "QW1-LEGACY-TRANSITION-2026-07-15" : ""
        let approvalExpiry = production ? "2027-01-31" : ""
        return """
        {
          "eligibility_id":"european_option:carr_madan:\(runtime)",
          "eligibility_version":"1.0.0",
          "product_definition_id":"european_option",
          "selector_id":"carr_madan",
          "implementation_component_id":"carr_madan",
          "model_definition_id":"\(runtime == "heston" ? "heston" : "black_scholes_merton")",
          "model_definition_version":"1.0.0",
          "solver_definition_id":"carr_madan",
          "solver_definition_version":"1.0.0",
          "pricer_component_id":null,
          "parameterization_component_id":null,
          "runtime_variant":"\(runtime)",
          "status":"\(status)",
          "production_allowed":\(production),
          "effective_production_allowed":\(active),
          "approval_basis":"\(approvalBasis)",
          "approval_ref":"\(approvalRef)",
          "approval_expires_on":"\(approvalExpiry)",
          "approval_active":\(active),
          "fallback_policy":"error",
          "workflow_layer":"\(workflow)"
        }
        """
    }

    func testCarrMadanVariantLookupNeverReusesBSMForHeston() throws {
        let bsm = eligibilityJSON(runtime: "bsm", status: "legacy-transition",
                                  production: true, workflow: "Production")
        let heston = eligibilityJSON(runtime: "heston", status: "research-only",
                                     production: false, workflow: "Research")
        let json = """
        {
          "id":"carr_madan", "model_id":"carr_madan", "name":"Carr-Madan FFT",
          "governance":{
            "status":"Validated", "asset_class":"equity", "model_family":"fourier",
            "method":"fourier", "notes":"", "production_allowed":true,
            "analytics_lab_only":false
          },
          "eligibility":\(bsm),
          "eligibility_variants":[\(bsm),\(heston)],
          "params":[]
        }
        """
        let engine = try JSONDecoder().decode(WsEngineModel.self, from: Data(json.utf8))

        XCTAssertEqual(engine.eligibilityVariants?.count, 2)
        XCTAssertEqual(engine.eligibility(forRuntimeVariant: "bsm")?.modelDefinitionID,
                       "black_scholes_merton")
        XCTAssertEqual(engine.eligibility(forRuntimeVariant: "heston")?.modelDefinitionID,
                       "heston")
        XCTAssertNil(engine.eligibility(forRuntimeVariant: "unknown"))
    }

    func testResearchEligibilityRequiresExplicitEnvironmentPermission() throws {
        let eligibility = try JSONDecoder().decode(
            WsEngineEligibility.self,
            from: Data(eligibilityJSON(runtime: "heston", status: "research-only",
                                       production: false, workflow: "Research").utf8))
        let fo = try JSONDecoder().decode(
            WsEnvironment.self,
            from: Data(#"{"env_id":"FO","name":"Front Office","purpose":"fo","metadata":{}}"#.utf8))
        let lab = try JSONDecoder().decode(
            WsEnvironment.self,
            from: Data(#"{"env_id":"LAB","name":"Analytics Lab","purpose":"research","metadata":{}}"#.utf8))

        XCTAssertNotNil(eligibility.blockReason(in: fo))
        XCTAssertNil(eligibility.blockReason(in: lab))
    }

    func testNonProductionEligibilityUsesSeparatePermission() throws {
        let eligibility = try JSONDecoder().decode(
            WsEngineEligibility.self,
            from: Data(eligibilityJSON(runtime: "bsm", status: "non-production",
                                       production: false, workflow: "Production").utf8))
        let lab = try JSONDecoder().decode(
            WsEnvironment.self,
            from: Data(#"{"env_id":"LAB","name":"Lab","purpose":"research","metadata":{}}"#.utf8))
        let untrustedMetadata = try JSONDecoder().decode(
            WsEnvironment.self,
            from: Data(#"{"env_id":"UAT","name":"UAT","purpose":"fo","metadata":{"allow_non_production":"yes"}}"#.utf8))

        XCTAssertNil(eligibility.blockReason(in: lab))
        XCTAssertNotNil(eligibility.blockReason(in: untrustedMetadata))
    }

    func testBackendResearchWorkflowVocabularyIsNormalized() throws {
        let eligibility = try JSONDecoder().decode(
            WsEngineEligibility.self,
            from: Data(eligibilityJSON(runtime: "heston", status: "implemented",
                                       production: false, workflow: " Research ").utf8))

        XCTAssertTrue(eligibility.isResearchOnly)
    }

    func testInactiveTransitionIsNeverEffectivelyProductionAllowed() throws {
        let inconsistentPayload = eligibilityJSON(
            runtime: "bsm", status: "legacy-transition",
            production: true, workflow: "Production", approvalActive: false
        ).replacingOccurrences(
            of: #""effective_production_allowed":false"#,
            with: #""effective_production_allowed":true"#
        )
        let eligibility = try JSONDecoder().decode(
            WsEngineEligibility.self,
            from: Data(inconsistentPayload.utf8))
        let fo = try JSONDecoder().decode(
            WsEnvironment.self,
            from: Data(#"{"env_id":"FO","name":"Front Office","purpose":"fo"}"#.utf8))

        XCTAssertTrue(eligibility.productionAllowed)
        XCTAssertFalse(eligibility.isEffectivelyProductionAllowed)
        XCTAssertNotNil(eligibility.blockReason(in: fo))
    }

    func testGovernanceDecodesSeparatedQuantCoverage() throws {
        let json = """
        {
          "counts":{"Validated":115,"Approximation":4,"Prototype":5},
          "quant_coverage_summary":{
            "schema_version":"1.0.0",
            "component_count":124,
            "model_definition_count":39,
            "canonical_solver_count":17,
            "solver_definition_count":107,
            "solver_evidence_count":107,
            "publication_counts":{"published":85,"routed":18,"research-only":20,"deprecated":1},
            "model_q_counts":{"Q1":21,"Q2":18},
            "generated_on":"2026-07-15",
            "workstation_selector_count":103,
            "engine_eligibility_count":104,
            "production_engine_count":84,
            "declared_production_engine_count":84,
            "legacy_transition_engine_count":84,
            "expired_transition_engine_count":0,
            "independently_approved_engine_count":0,
            "research_engine_count":15
          },
          "models":[], "limitations":[], "audit":[]
        }
        """
        let data = try JSONDecoder().decode(GovernanceData.self, from: Data(json.utf8))
        let summary = try XCTUnwrap(data.quantCoverageSummary)

        XCTAssertEqual(summary.componentCount, 124)
        XCTAssertEqual(summary.modelDefinitionCount, 39)
        XCTAssertEqual(summary.solverDefinitionCount, 107)
        XCTAssertEqual(summary.modelQCounts["Q1"], 21)
        XCTAssertEqual(summary.modelQCounts["Q2"], 18)
        XCTAssertEqual(summary.publicationCounts["published"], 85)
        XCTAssertEqual(summary.publicationCounts["routed"], 18)
        XCTAssertEqual(summary.publicationCounts["research-only"], 20)
        XCTAssertEqual(summary.publicationCounts["deprecated"], 1)
        XCTAssertEqual(summary.productionEngineCount, 84)
        XCTAssertEqual(summary.declaredProductionEngineCount, 84)
        XCTAssertEqual(summary.legacyTransitionEngineCount, 84)
        XCTAssertEqual(summary.expiredTransitionEngineCount, 0)
        XCTAssertEqual(summary.independentlyApprovedEngineCount, 0)
        XCTAssertEqual(summary.engineEligibilityCount, 104)
    }

    func testPreQW1GovernancePayloadRemainsDecodable() throws {
        let json = #"{"counts":{"Validated":98},"models":[],"limitations":[],"audit":[]}"#
        let data = try JSONDecoder().decode(GovernanceData.self, from: Data(json.utf8))
        XCTAssertNil(data.quantCoverageSummary)
    }
}
