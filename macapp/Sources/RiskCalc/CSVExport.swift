import AppKit
import UniformTypeIdentifiers

/// Minimal CSV export via a save panel. Used by Market Data tables (instrument
/// lists, history) — the doc's P0 "Export" without a heavy import/export module.
enum CSVExport {
    @MainActor
    static func save(suggestedName: String, header: [String], rows: [[String]]) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = suggestedName.hasSuffix(".csv") ? suggestedName : suggestedName + ".csv"
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        var text = header.map(escape).joined(separator: ",") + "\n"
        for r in rows { text += r.map(escape).joined(separator: ",") + "\n" }
        try? text.data(using: .utf8)?.write(to: url)
    }

    private static func escape(_ s: String) -> String {
        guard s.contains(",") || s.contains("\"") || s.contains("\n") else { return s }
        return "\"" + s.replacingOccurrences(of: "\"", with: "\"\"") + "\""
    }
}
