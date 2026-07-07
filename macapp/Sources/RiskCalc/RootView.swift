import SwiftUI

/// App shell: branded sidebar + routed detail, with a global refresh and a
/// bridge-down overlay.
struct RootView: View {
    @State private var model = AppModel()
    // Market Data mode expands as sub-rows under the Market Data sidebar item.
    @SceneStorage("mdMode") private var marketMode = "overview"
    // Global search (toolbar command palette)
    @State private var searchOpen = false
    @FocusState private var searchFocused: Bool
    // Fullscreen: the titlebar becomes a separate auto-hiding window, so the
    // overlay pill raised into it would be clipped — track and reposition.
    @State private var isFullscreen = false

    /// Second-level Market Data modes (shown nested under "Market Data").
    private let marketModes: [(key: String, title: String, icon: String)] = [
        ("overview", "Обзор", "square.grid.2x2"),
        ("instruments", "Инструменты", "list.bullet.rectangle"),
        ("curves", "Кривые", "chart.xyaxis.line"),
        ("volatility", "Волатильность", "waveform"),
        ("history", "История", "clock"),
    ]

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
        .overlay {
            if searchOpen { searchOverlay }
        }
    }

    // MARK: global search overlay (glass command palette)

    private func openSearch()  { withAnimation(.snappy(duration: 0.2)) { searchOpen = true }; searchFocused = true }
    private func closeSearch() { withAnimation(.snappy(duration: 0.2)) { searchOpen = false }; model.searchText = ""; model.searchHits = [] }

    private func open(_ hit: SearchHit) {
        guard let cat = hit.category else { return }
        marketMode = "instruments"
        model.requestOpen(category: cat, secid: hit.secid)
        closeSearch()
    }

    private var searchOverlay: some View {
        ZStack(alignment: .top) {
            Rectangle().fill(.black.opacity(0.12)).ignoresSafeArea()
                .onTapGesture { closeSearch() }
            VStack(spacing: 0) {
                HStack(spacing: Theme.s3) {
                    Image(systemName: "magnifyingglass").font(.system(size: 15)).foregroundStyle(.secondary)
                    TextField("Поиск: тикер · ISIN · эмитент", text: $model.searchText)
                        .textFieldStyle(.plain).font(.system(size: 16))
                        .focused($searchFocused)
                        .onSubmit { if let h = model.searchHits.first { open(h) } }
                    if !model.searchText.isEmpty {
                        Button { model.searchText = "" } label: {
                            Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, Theme.s4).padding(.vertical, 14)
                if !model.searchHits.isEmpty {
                    Divider().opacity(0.4)
                    ScrollView {
                        LazyVStack(spacing: 0) {
                            ForEach(model.searchHits.prefix(12)) { hit in
                                searchResultRow(hit)
                                Divider().opacity(0.15)
                            }
                        }
                    }
                    .frame(maxHeight: 380)
                }
            }
            .frame(width: 580)
            .glassPanel(cornerRadius: 18)
            .shadow(color: .black.opacity(0.25), radius: 30, x: 0, y: 12)
            .padding(.top, 78)
        }
        .onChange(of: model.searchText) { _, q in model.runSearch(q) }
        .onExitCommand { closeSearch() }
        .transition(.opacity)
    }

    private func searchResultRow(_ hit: SearchHit) -> some View {
        Button { open(hit) } label: {
            HStack(spacing: Theme.s3) {
                Text(searchCategoryLabel(hit.category))
                    .font(.system(size: 9, weight: .semibold)).foregroundStyle(Theme.accent)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(Theme.accent.opacity(0.14), in: Capsule())
                    .frame(width: 92, alignment: .leading)
                VStack(alignment: .leading, spacing: 0) {
                    Text(hit.issuerRu ?? hit.secid).font(.system(size: 13, weight: .medium)).lineLimit(1)
                    Text(hit.isin ?? hit.secid).font(.system(size: 10)).foregroundStyle(.tertiary).lineLimit(1)
                }
                Spacer()
                if let l = hit.last {
                    Text(Fmt.number(l, digits: 2)).font(.system(size: 13, weight: .semibold)).monospacedDigit()
                }
                if let c = hit.changePct {
                    Text(Fmt.signedPercent(c, digits: 2)).font(.system(size: 11)).monospacedDigit()
                        .foregroundStyle(c >= 0 ? Theme.positive : Theme.negative)
                }
            }
            .padding(.horizontal, Theme.s4).padding(.vertical, 8).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func searchCategoryLabel(_ cat: String?) -> String {
        switch cat {
        case "bonds": "Облигация"; case "equities": "Акция"; case "futures": "Фьючерс"
        case "options": "Опцион"; case "indices": "Индекс"; case "fx": "Валюта"
        case "commodities": "Товар"; default: cat ?? "?"
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
                        // Market Data expands its modes as nested sub-rows.
                        if section == .market && model.section == .market {
                            ForEach(marketModes, id: \.key) { m in
                                MDModeSubRow(title: m.title, icon: m.icon,
                                             selected: marketMode == m.key) {
                                    marketMode = m.key
                                }
                            }
                            .transition(.opacity)
                        }
                    }
                }
                .padding(.horizontal, Theme.s2)
                .padding(.top, Theme.s1)
                .animation(.snappy(duration: 0.2), value: model.section)
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
            case .market:     MarketScreen(group: $marketMode, model: model)
            case .dataControls: DataControlsScreen()
            case .pricing:    PricingScreen()
            case .governance: GovernanceScreen(model: model)
            case .analytics:  AnalyticsScreen(model: model)
            }
        }
        .navigationTitle("")               // suppress the default "RiskCalc" window title
        // The system toolbar pins its glass items at a fixed inset that SwiftUI
        // padding/offset can't move, so the title pill is drawn in the content
        // layer instead (manual glass renders cleanly here — the halo only
        // appears when stacking glass inside the glass toolbar) and raised into
        // the toolbar row. Leading = Theme.s4, matching the content indent.
        // In fullscreen the titlebar is a separate auto-hiding window (the
        // raised pill would be clipped), so it gets its own row instead.
        .overlay(alignment: .topLeading) {
            if !isFullscreen { titlePill.offset(y: -43) }
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            if isFullscreen {
                HStack {
                    titlePill
                    Spacer()
                }
                .padding(.top, Theme.s2)
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didEnterFullScreenNotification)) { _ in
            isFullscreen = true
        }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.willExitFullScreenNotification)) { _ in
            isFullscreen = false
        }
        .onAppear {
            isFullscreen = NSApp.windows.contains { $0.styleMask.contains(.fullScreen) }
        }
        .toolbar {
            // Right group: search (leftmost) · ingest · refresh.
            ToolbarItem(placement: .primaryAction) {
                Button { openSearch() } label: { Image(systemName: "magnifyingglass") }
                    .help("Поиск (⌘F)")
                    .keyboardShortcut("f", modifiers: .command)
            }
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
                      ? "Загрузка данных за сегодня… \(model.ingestMessage)"
                      : "Загрузить рыночные данные MOEX + CBR")
                .disabled(model.ingestRunning)
            }
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await model.refresh() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help("Обновить с моста")
            }
        }
    }

    /// Glass section-name pill, aligned to the content gutter (Theme.s4).
    private var titlePill: some View {
        Text(model.section.title)
            .font(.system(size: 14, weight: .semibold))
            .padding(.horizontal, 15).padding(.vertical, 7)
            .glassCapsule()
            .padding(.leading, Theme.s4)
    }
}

// MARK: - Liquid Glass helpers (macOS 26+, material fallback)

extension View {
    @ViewBuilder func glassCapsule() -> some View {
        if #available(macOS 26, *) {
            self.glassEffect(.regular, in: .capsule)
        } else {
            self.background(.regularMaterial, in: Capsule())
                .overlay(Capsule().strokeBorder(Color.primary.opacity(0.06), lineWidth: 1))
        }
    }

    @ViewBuilder func glassPanel(cornerRadius: CGFloat) -> some View {
        if #available(macOS 26, *) {
            self.glassEffect(.regular, in: .rect(cornerRadius: cornerRadius))
        } else {
            self.background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
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

/// Nested Market Data mode row — indented under the Market Data item, lighter
/// than a top-level NavRow but sharing the accent-pill selection.
private struct MDModeSubRow: View {
    let title: String
    let icon: String
    let selected: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: Theme.s2) {
                Image(systemName: icon)
                    .font(.system(size: 11))
                    .foregroundStyle(selected ? Theme.accent : .secondary)
                    .frame(width: 16)
                Text(title)
                    .font(.system(size: 12, weight: selected ? .semibold : .regular))
                    .foregroundStyle(selected ? Theme.accent : .secondary)
                Spacer(minLength: 0)
            }
            .padding(.leading, Theme.s5 + Theme.s1)   // indent under the parent icon
            .padding(.trailing, Theme.s3)
            .padding(.vertical, 5)
            .background {
                // No accent fill for sub-items — active state is orange text only.
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(hovering && !selected ? Color.primary.opacity(0.06) : Color.clear)
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
            // Horizontal gutter = Theme.s4, one line with the title pill and
            // the Market Data tabs/list ("ровно всё").
            .padding(.horizontal, Theme.s4).padding(.vertical, Theme.s5)
            .frame(maxWidth: Theme.contentMaxWidth)   // cap reading width; cards fill it
            .frame(maxWidth: .infinity)               // centre the column on wide displays
        }
        .background(Color(nsColor: .windowBackgroundColor).ignoresSafeArea())
    }
}
