import SwiftUI

/// Data Controls — the data-quality / operations contour, kept OUT of Market Data
/// (which is a market-data showcase, not a control center). Hosts Data Health for
/// now; Coverage, Ingest Log, Validation Alerts, Lineage etc. can become sibling
/// tabs here later.
struct DataControlsScreen: View {
    @State private var tab = "health"

    private let tabs: [(String, String)] = [
        ("health", "Качество"),
    ]

    var body: some View {
        VStack(spacing: 0) {
            if tabs.count > 1 {
                Picker("", selection: $tab) {
                    ForEach(tabs, id: \.0) { Text($0.1).tag($0.0) }
                }
                .pickerStyle(.segmented).labelsHidden()
                .padding(.horizontal, Theme.s5).padding(.vertical, Theme.s3)
                Divider()
            }
            switch tab {
            case "health": DataHealthView()
            default:       DataHealthView()
            }
        }
        .navigationTitle("Контроль данных")
    }
}
