import SwiftUI
import AppKit

@main
struct RiskCalcApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            RootView()
                .frame(minWidth: 1120, minHeight: 740)
                .tint(Theme.accent)
        }
        .windowToolbarStyle(.unified)
    }
}

/// Brings the window to front when launched via `swift run` (a SwiftPM
/// executable starts as an accessory process otherwise).
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        // No hairline under the titlebar (it showed over the sidebar).
        DispatchQueue.main.async {
            NSApp.windows.forEach { $0.titlebarSeparatorStyle = .none }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}
