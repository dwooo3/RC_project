import SwiftUI

/// Data Controls — the data-quality / operations contour, kept OUT of Market Data
/// (which is a market-data showcase, not a control center). Hosts Data Health for
/// now; Coverage, Ingest Log, Validation Alerts, Lineage etc. can become sibling
/// tabs here later.
struct DataControlsScreen: View {
    @State private var tab = "health"

    private let tabs: [(String, String)] = [
        ("health", "Качество"), ("tables", "Таблицы"), ("dictionary", "Словарь"),
    ]

    var body: some View {
        VStack(spacing: 0) {
            if tabs.count > 1 {
                HStack {
                    SegmentedBar(items: tabs, selection: $tab).fixedSize()
                    Spacer()
                }
                .padding(.horizontal, Theme.s5).padding(.vertical, Theme.s3)
                Divider()
            }
            switch tab {
            case "health":     DataHealthView()
            case "tables":     RawDataView()
            case "dictionary": DataDictionaryView()
            default:           DataHealthView()
            }
        }
    }
}
