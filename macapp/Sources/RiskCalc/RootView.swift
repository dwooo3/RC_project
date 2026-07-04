import SwiftUI

/// App shell: branded sidebar + routed detail, with a global refresh and a
/// bridge-down overlay.
struct RootView: View {
    @State private var model = AppModel()

    var body: some View {
        NavigationSplitView {
            sidebar
                .navigationSplitViewColumnWidth(min: 224, ideal: 244, max: 300)
        } detail: {
            detail
                .frame(minWidth: 640)
        }
        .task { await model.start() }
        .onChange(of: model.section) { _, new in
            Task { await model.load(new) }
        }
        .overlay {
            if model.serverDown {
                ServerDownView(message: nil) { Task { await model.refresh() } }
            }
        }
    }

    // MARK: sidebar

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            brand
            ScrollView {
                VStack(spacing: 2) {
                    ForEach(AppSection.allCases) { section in
                        NavRow(section: section, selected: model.section == section) {
                            model.section = section
                        }
                    }
                }
                .padding(.horizontal, Theme.s2)
                .padding(.top, Theme.s1)
            }
            Divider().opacity(0.5)
            footer
        }
        // Same clean surface as the content blocks: solid white, no vibrancy.
        .background(Theme.cardFill.ignoresSafeArea())
    }

    private var brand: some View {
        HStack(spacing: Theme.s3) {
            Text("R")
                .font(.system(size: 18, weight: .heavy, design: .rounded))
                .foregroundStyle(.white)
                .frame(width: 34, height: 34)
                .background(
                    LinearGradient(colors: [Theme.accent, Theme.accent.opacity(0.7)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing),
                    in: RoundedRectangle(cornerRadius: 9)
                )
            VStack(alignment: .leading, spacing: 0) {
                Text("RiskCalc").font(.system(size: 15, weight: .bold))
                Text("Market Risk Workstation")
                    .font(.system(size: 10)).foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(.horizontal, Theme.s4)
        .padding(.top, Theme.s4)
        .padding(.bottom, Theme.s2)
    }

    private var footer: some View {
        HStack(spacing: Theme.s2) {
            Circle()
                .fill(model.serverDown ? Theme.negative : (model.health?.live == true ? Theme.positive : Theme.warning))
                .frame(width: 7, height: 7)
            Text(model.serverDown ? "Не в сети"
                 : (model.health?.live == true ? "MOEX" : "Demo"))
                .font(.system(size: 11, weight: .medium))
            Spacer()
        }
        .padding(Theme.s3)
    }

    // MARK: detail

    @ViewBuilder
    private var detail: some View {
        Group {
            switch model.section {
            case .dashboard:  DashboardScreen(model: model)
            case .portfolio:  PortfolioScreen(model: model)
            case .risk:       RiskScreen(model: model)
            case .market:     MarketScreen()
            case .dataControls: DataControlsScreen()
            case .pricing:    PricingScreen()
            case .governance: GovernanceScreen(model: model)
            case .analytics:  AnalyticsScreen(model: model)
            }
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await model.startIngest() }
                } label: {
                    if model.ingestRunning {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "icloud.and.arrow.down")
                    }
                }
                .help(model.ingestRunning
                      ? "Loading today's data… \(model.ingestMessage)"
                      : "Load today's market data from MOEX + CBR")
                .disabled(model.ingestRunning)
            }
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await model.refresh() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help("Reload from bridge")
            }
        }
    }
}

/// Sidebar navigation row — a rounded accent pill when selected (matching the
/// content blocks), with a soft hover highlight otherwise.
private struct NavRow: View {
    let section: AppSection
    let selected: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: Theme.s3) {
                Image(systemName: section.icon)
                    .font(.system(size: 13))
                    .foregroundStyle(selected ? Color.white : Color.secondary)
                    .frame(width: 20)
                Text(section.title)
                    .font(.system(size: 13, weight: selected ? .semibold : .regular))
                    .foregroundStyle(selected ? Color.white : .primary)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, Theme.s3)
            .padding(.vertical, 7)
            .background {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(selected ? AnyShapeStyle(Theme.accent)
                                   : AnyShapeStyle(hovering ? Color.primary.opacity(0.06) : Color.clear))
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
    }
}

/// Standard scrollable page container with consistent padding.
struct ScreenScaffold<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s5) {
                content
            }
            .padding(Theme.s5)
            .frame(maxWidth: Theme.contentMaxWidth)   // cap reading width; cards fill it
            .frame(maxWidth: .infinity)               // centre the column on wide displays
        }
        .background(Color(nsColor: .windowBackgroundColor).ignoresSafeArea())
    }
}
