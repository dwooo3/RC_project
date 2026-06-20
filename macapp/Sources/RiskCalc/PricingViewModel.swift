import SwiftUI
import Observation

@MainActor
@Observable
final class PricingViewModel {
    var pricers: [Pricer] = []
    var selectedID: String?
    var numericValues: [String: Double] = [:]
    var choiceValues: [String: String] = [:]
    var result: PriceResult?

    var isLoading = false
    var isPricing = false
    var serverDown = false
    var errorMessage: String?

    private let client = BridgeClient()

    var selected: Pricer? { pricers.first { $0.id == selectedID } }

    // Pricers grouped by family for the sidebar, families in a stable order.
    var groupedPricers: [(family: String, items: [Pricer])] {
        let order = ["Analytic", "Lattice", "PDE", "Monte Carlo", "Stochastic vol", "Jump"]
        let groups = Dictionary(grouping: pricers, by: \.family)
        return groups.keys
            .sorted { (order.firstIndex(of: $0) ?? .max, $0) < (order.firstIndex(of: $1) ?? .max, $1) }
            .map { ($0, groups[$0] ?? []) }
    }

    func load() async {
        isLoading = true
        serverDown = false
        errorMessage = nil
        do {
            pricers = try await client.catalogue()
            if selectedID == nil { selectedID = pricers.first?.id }
            if let pricer = selected { resetParams(for: pricer) }
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
        if let pricer = selected { resetParams(for: pricer) }
    }

    func resetParams(for pricer: Pricer) {
        numericValues.removeAll()
        choiceValues.removeAll()
        for spec in pricer.params {
            switch spec.defaultValue {
            case .number(let d): numericValues[spec.key] = d
            case .string(let s): choiceValues[spec.key] = s
            }
        }
    }

    func numericBinding(_ key: String) -> Binding<Double> {
        Binding(get: { self.numericValues[key] ?? 0 },
                set: { self.numericValues[key] = $0 })
    }

    func choiceBinding(_ key: String) -> Binding<String> {
        Binding(get: { self.choiceValues[key] ?? "" },
                set: { self.choiceValues[key] = $0 })
    }

    func price() async {
        guard let pricer = selected else { return }
        isPricing = true
        errorMessage = nil
        var params: [String: BridgeValue] = [:]
        for (key, value) in numericValues { params[key] = BridgeValue(kind: .number(value)) }
        for (key, value) in choiceValues { params[key] = BridgeValue(kind: .string(value)) }
        do {
            let priced = try await client.price(pricer: pricer.id, params: params)
            result = priced
            if let first = priced.errors.first { errorMessage = first }
        } catch {
            errorMessage = error.localizedDescription
        }
        isPricing = false
    }
}
