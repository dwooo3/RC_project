import SwiftUI
import Charts
import Observation

// MARK: - Models (GET /pnl/explain)

struct PXEffect: Decodable, Sendable, Identifiable, Hashable {
    let key: String
    let label: String
    let value: Double
    var id: String { key }
}

struct PXFactor: Decodable, Sendable, Hashable {
    let factor: String
    let pnl: Double
}

struct PXPosition: Decodable, Sendable, Hashable {
    let position: String
    let pnl: Double
}

struct PXMoves: Decodable, Sendable {
    let equity: Double
    let ratesBp: Double
    let volPts: Double
    let fx: Double

    enum CodingKeys: String, CodingKey {
        case equity, fx
        case ratesBp = "rates_bp"
        case volPts = "vol_pts"
    }
}

struct PXActualVsHyp: Decodable, Sendable {
    let available: Bool
    let date: String
    let actualPnl: Double?
    let hypotheticalPnl: Double?
    let gap: Double?
    let source: String?
    let note: String?

    enum CodingKeys: String, CodingKey {
        case available, date, gap, source, note
        case actualPnl = "actual_pnl"
        case hypotheticalPnl = "hypothetical_pnl"
    }
}

struct PXLifecycle: Decodable, Sendable, Hashable {
    let position: String
    let tYears: Double
    let note: String

    enum CodingKeys: String, CodingKey {
        case position, note
        case tYears = "T_years"
    }
}

struct PnlExplain: Decodable, Sendable {
    let asOf: String
    let moves: PXMoves
    let totalPnl: Double
    let explained: Double
    let residual: Double
    let effects: [PXEffect]
    let byFactor: [PXFactor]
    let byPosition: [PXPosition]
    let actualVsHypothetical: PXActualVsHyp?
    let lifecycle: [PXLifecycle]
    let note: String
    let warnings: [String]

    enum CodingKeys: String, CodingKey {
        case moves, effects, note, warnings, explained, residual, lifecycle
        case asOf = "as_of"
        case totalPnl = "total_pnl"
        case byFactor = "by_factor"
        case byPosition = "by_position"
        case actualVsHypothetical = "actual_vs_hypothetical"
    }
}

struct PXActualImport: Encodable {
    let date: String
    let pnl: Double
    let source: String
    let note: String
}

struct PXActualImportResult: Decodable, Sendable {
    let imported: Int
    let total: Int
}

extension BridgeClient {
    func pnlExplain() async throws -> PnlExplain { try await get("pnl/explain") }

    func importActualPnl(date: String, pnl: Double, note: String = "")
        async throws -> PXActualImportResult {
        let body = try JSONEncoder().encode(
            PXActualImport(date: date, pnl: pnl, source: "manual", note: note))
        return try await post("pnl/actual", body: body)
    }

    func deleteActualPnl(date: String) async throws {
        try await delete("pnl/actual/\(date)")
    }
}

// MARK: - Pane

/// P&L Explained (Calypso §2.4): the latest day's actual factor moves, the
/// full-reprice total, greek-attributed market-data/time effects, residual.
struct PnlExplainPane: View {
    @State private var data: PnlExplain?
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var actualInput = ""
    @State private var importMessage: String?
    @State private var isImporting = false
    private let client = BridgeClient()

    var body: some View {
        ScreenScaffold {
            PageHeader("P&L Explain",
                       subtitle: "actual vs hypothetical · market data effect · time effect · residual")
            if let message = errorMessage {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.negative)
            }
            if let d = data {
                content(d)
            } else if isLoading {
                SkeletonScreen()
            }
        }
        .task { await load() }
    }

    private func load() async {
        isLoading = true
        errorMessage = nil
        do {
            data = try await client.pnlExplain()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func importActual(asOf: String) async {
        guard let value = Double(actualInput.replacingOccurrences(of: " ", with: "")
                                            .replacingOccurrences(of: ",", with: ".")) else {
            importMessage = "Не число: \(actualInput)"
            return
        }
        isImporting = true
        importMessage = nil
        do {
            _ = try await client.importActualPnl(date: asOf, pnl: value,
                                                 note: "ручной ввод из P&L Explain")
            actualInput = ""
            data = try await client.pnlExplain()
        } catch {
            importMessage = error.localizedDescription
        }
        isImporting = false
    }

    private func deleteActual(asOf: String) async {
        isImporting = true
        importMessage = nil
        do {
            try await client.deleteActualPnl(date: asOf)
            data = try await client.pnlExplain()
        } catch {
            importMessage = error.localizedDescription
        }
        isImporting = false
    }

    @ViewBuilder
    private func content(_ d: PnlExplain) -> some View {
        KPIStrip(items: [
            KPICard(label: "Total P&L (\(d.asOf))", value: Fmt.money(d.totalPnl),
                    sub: "full reprice", accent: Theme.trendColor(d.totalPnl),
                    icon: "sum"),
            KPICard(label: "Explained", value: Fmt.money(d.explained),
                    sub: "greek attribution", accent: Theme.accent,
                    icon: "checkmark.circle"),
            KPICard(label: "Residual", value: Fmt.money(d.residual),
                    sub: "nonlinear + FX + cross", accent: Theme.warning,
                    icon: "questionmark.circle"),
            KPICard(label: "IMOEX", value: Fmt.signedPercent(d.moves.equity * 100),
                    sub: "equity move", accent: Theme.bucketColor("Equity"),
                    icon: "chart.line.uptrend.xyaxis"),
            KPICard(label: "КБД 5Y", value: String(format: "%+.1f bp", d.moves.ratesBp),
                    sub: "rate move", accent: Theme.bucketColor("Rates"),
                    icon: "percent"),
        ])

        actualVsHypCard(d)
        HStack(alignment: .top, spacing: Theme.s4) {
            waterfallCard(d)
            positionsCard(d)
        }
        if !d.lifecycle.isEmpty {
            lifecycleCard(d)
        }
        if !d.note.isEmpty {
            Label(d.note, systemImage: "info.circle")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    /// APL vs HypPL (A3): фактический P&L против модельного гипотетического;
    /// разрыв = новые сделки/интрадей/lifecycle/theta. Импорт actual — тут же.
    private func actualVsHypCard(_ d: PnlExplain) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Actual vs Hypothetical P&L", icon: "arrow.triangle.2.circlepath")
                if let avh = d.actualVsHypothetical, avh.available,
                   let actual = avh.actualPnl, let hyp = avh.hypotheticalPnl,
                   let gap = avh.gap {
                    HStack(spacing: Theme.s5) {
                        pnlColumn("Actual P&L", actual, Theme.trendColor(actual))
                        pnlColumn("Hypothetical P&L", hyp, Theme.accent)
                        pnlColumn("Gap (APL − HypPL)", gap,
                                  abs(gap) < 1 ? Theme.positive : Theme.warning)
                        Spacer()
                        Button(role: .destructive) {
                            Task { await deleteActual(asOf: d.asOf) }
                        } label: {
                            Label("Удалить", systemImage: "trash")
                                .font(.system(size: 11))
                        }
                        .buttonStyle(.bordered)
                        .disabled(isImporting)
                    }
                    if let note = avh.note {
                        Text(note).font(.system(size: 10)).foregroundStyle(.tertiary)
                    }
                } else {
                    HStack(spacing: Theme.s3) {
                        Text("Фактический P&L за \(d.asOf) не импортирован")
                            .font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        TextField("Actual P&L, ₽", text: $actualInput)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 140)
                            .onSubmit { Task { await importActual(asOf: d.asOf) } }
                        Button {
                            Task { await importActual(asOf: d.asOf) }
                        } label: {
                            if isImporting {
                                ProgressView().controlSize(.small)
                            } else {
                                Label("Импорт", systemImage: "square.and.arrow.down")
                                    .font(.system(size: 11))
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(isImporting || actualInput.isEmpty)
                    }
                    Text("Basel APL должен быть очищен от комиссий; разрыв с HypPL покажет вклад сделок/интрадея/lifecycle/theta.")
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                }
                if let message = importMessage {
                    Text(message).font(.system(size: 10)).foregroundStyle(Theme.negative)
                }
            }
        }
    }

    private func pnlColumn(_ label: String, _ value: Double, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 10)).foregroundStyle(.secondary)
            Text(Fmt.money(value))
                .font(.system(size: 18, weight: .bold)).monospacedDigit()
                .foregroundStyle(color)
        }
    }

    /// Lifecycle v1 (A3): позиции у экспирации, чей эффект скоро осядет в
    /// разрыве APL/HypPL (полное старение книги пока не моделируется).
    private func lifecycleCard(_ d: PnlExplain) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s2) {
                BlockTitle("Lifecycle · позиции у экспирации", icon: "calendar.badge.exclamationmark")
                ForEach(d.lifecycle, id: \.position) { lc in
                    HStack {
                        Text(lc.position).font(.system(size: 11)).lineLimit(1)
                        Spacer()
                        Text("T = \(Fmt.number(lc.tYears * 252, digits: 1)) т.д.")
                            .font(.system(size: 10)).monospacedDigit()
                            .foregroundStyle(Theme.warning)
                    }
                }
                Text("Полное старение книги (купоны/фиксинги/экспирации между датами) требует трейд-дат позиций — пока предупреждение.")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
    }

    private func waterfallCard(_ d: PnlExplain) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("P&L attribution", icon: "chart.bar.doc.horizontal")
                let rows = d.effects + [PXEffect(key: "residual", label: "Residual",
                                                 value: d.residual)]
                Chart(rows) { e in
                    BarMark(x: .value("P&L", e.value), y: .value("Effect", e.label))
                        .foregroundStyle(e.key == "residual"
                                         ? Theme.warning.gradient
                                         : Theme.trendColor(e.value).gradient)
                        .annotation(position: .trailing) {
                            Text(Fmt.money(e.value))
                                .font(.system(size: 9)).monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                }
                .chartXAxis(.hidden)
                .frame(height: CGFloat(rows.count) * 34 + 16)
                Text("Дневное движение факторов через гриэки книги; time effect = theta за 1 день.")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
    }

    private func positionsCard(_ d: PnlExplain) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("By position", icon: "list.bullet.indent")
                let rows = d.byPosition.sorted { abs($0.pnl) > abs($1.pnl) }
                ForEach(rows.prefix(10), id: \.position) { p in
                    HStack {
                        Text(p.position).font(.system(size: 11)).lineLimit(1)
                        Spacer()
                        Text(Fmt.money(p.pnl))
                            .font(.system(size: 11, weight: .semibold)).monospacedDigit()
                            .foregroundStyle(Theme.trendColor(p.pnl))
                    }
                    .padding(.vertical, 2)
                }
                if !d.byFactor.isEmpty {
                    Divider()
                    Text("BY FACTOR").font(.system(size: 9, weight: .semibold))
                        .tracking(0.5).foregroundStyle(.tertiary)
                    ForEach(d.byFactor.sorted { abs($0.pnl) > abs($1.pnl) }.prefix(6),
                            id: \.factor) { f in
                        HStack {
                            Text(f.factor).font(.system(size: 10)).foregroundStyle(.secondary)
                            Spacer()
                            Text(Fmt.money(f.pnl))
                                .font(.system(size: 10)).monospacedDigit()
                                .foregroundStyle(Theme.trendColor(f.pnl))
                        }
                    }
                }
            }
        }
        .frame(width: 320)
    }
}
