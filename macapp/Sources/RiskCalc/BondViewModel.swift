import SwiftUI
import Observation

@MainActor
@Observable
final class BondViewModel {
    var instruments: [BondInstrument] = []
    var curves: [CurveOption] = []
    var curveLines: [CurveData] = []
    var selectedID: String?
    var numericValues: [String: Double] = [:]
    var choiceValues: [String: String] = [:]
    var result: BondResult?

    var isLoading = false
    var isPricing = false
    var serverDown = false
    var errorMessage: String?

    private let client = BridgeClient()

    var selected: BondInstrument? { instruments.first { $0.id == selectedID } }

    /// The curve currently selected in the parameter form (if the instrument uses one).
    var selectedCurveData: CurveData? {
        guard let id = choiceValues["curve_id"] else { return nil }
        return curveLines.first { $0.id == id }
    }

    var shiftBps: Double { numericValues["shift_bps"] ?? 0 }

    var grouped: [(group: String, items: [BondInstrument])] {
        let order = ["Sovereign", "Fixed coupon", "Floating", "Embedded option",
                     "Custom", "Securitized", "Money market", "Credit"]
        let groups = Dictionary(grouping: instruments, by: \.group)
        return groups.keys
            .sorted { (order.firstIndex(of: $0) ?? .max, $0) < (order.firstIndex(of: $1) ?? .max, $1) }
            .map { ($0, groups[$0] ?? []) }
    }

    func load() async {
        isLoading = true
        serverDown = false
        errorMessage = nil
        do {
            let catalogue = try await client.bondCatalogue()
            instruments = catalogue.instruments
            curves = catalogue.curves
            curveLines = (try? await client.curves()) ?? []
            if selectedID == nil { selectedID = instruments.first?.id }
            if let inst = selected { resetParams(for: inst) }
        } catch {
            serverDown = true
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    func select(_ id: String) {
        guard id != selectedID else { return }
        selectedID = id
        result = nil
        errorMessage = nil
        if let inst = selected { resetParams(for: inst) }
    }

    func resetParams(for inst: BondInstrument) {
        numericValues.removeAll()
        choiceValues.removeAll()
        for spec in inst.params {
            switch spec.defaultValue {
            case .number(let d): numericValues[spec.key] = d
            case .string(let s): choiceValues[spec.key] = s
            }
        }
    }

    func numericBinding(_ key: String) -> Binding<Double> {
        Binding(get: { self.numericValues[key] ?? 0 }, set: { self.numericValues[key] = $0 })
    }

    func choiceBinding(_ key: String) -> Binding<String> {
        Binding(get: { self.choiceValues[key] ?? "" }, set: { self.choiceValues[key] = $0 })
    }

    func price() async {
        guard let inst = selected else { return }
        isPricing = true
        errorMessage = nil
        var params: [String: BridgeValue] = [:]
        for (k, v) in numericValues { params[k] = BridgeValue(kind: .number(v)) }
        for (k, v) in choiceValues { params[k] = BridgeValue(kind: .string(v)) }
        do {
            let r = try await client.priceBond(instrument: inst.id, params: params)
            result = r
            if let first = r.errors.first { errorMessage = first }
        } catch {
            errorMessage = error.localizedDescription
        }
        isPricing = false
    }
}
