import SwiftUI
import Charts
import Observation

// MARK: - Models (GET /marketrisk, /marketrisk/backtest)

struct MRMethod: Decodable, Sendable, Identifiable, Hashable {
    let method: String
    let label: String
    let modelID: String
    let varValue: Double
    let es: Double
    var id: String { method }

    enum CodingKeys: String, CodingKey {
        case method, label, es
        case modelID = "model_id"
        case varValue = "var"
    }
}

struct MRHistBin: Decodable, Sendable, Hashable {
    let x: Double
    let count: Int
}

struct MRPnlPoint: Decodable, Sendable, Hashable {
    let date: String
    let pnl: Double
}

struct MROverview: Decodable, Sendable {
    let confidence: Double
    let window: Int
    let horizon: Int
    let stress: String
    let stressPeriod: String
    let nScenarios: Int
    let portfolioValue: Double
    let positions: Int
    let varValue: Double
    let es: Double
    let methods: [MRMethod]
    let histogram: [MRHistBin]
    let varLine: Double
    let hyppl: [MRPnlPoint]
    let worst: [MRPnlPoint]
    let best: [MRPnlPoint]
    let factors: [String]
    let dataQuality: [String]

    enum CodingKeys: String, CodingKey {
        case confidence, window, horizon, stress, methods, histogram, hyppl, worst, best, factors
        case stressPeriod = "stress_period"
        case nScenarios = "n_scenarios"
        case portfolioValue = "portfolio_value"
        case positions
        case varValue = "var"
        case es
        case varLine = "var_line"
        case dataQuality = "data_quality"
    }
}

struct MRKupiec: Decodable, Sendable {
    let pValue: Double?
    let reject: Bool?

    enum CodingKeys: String, CodingKey {
        case pValue = "p_value"
        case reject
    }
}

struct MRBacktestRow: Decodable, Sendable, Hashable {
    let date: String
    let pnl: Double
    let varValue: Double
    let breach: Bool

    enum CodingKeys: String, CodingKey {
        case date, pnl, breach
        case varValue = "var"
    }
}

struct MRBacktest: Decodable, Sendable {
    let confidence: Double
    let lookback: Int
    let nObs: Int
    let nExceptions: Int
    let expectedExceptions: Double
    let kupiec: MRKupiec?
    let trafficLight: String
    let bias: String?
    let rows: [MRBacktestRow]

    enum CodingKeys: String, CodingKey {
        case confidence, lookback, kupiec, rows, bias
        case nObs = "n_obs"
        case nExceptions = "n_exceptions"
        case expectedExceptions = "expected_exceptions"
        case trafficLight = "traffic_light"
    }
}

struct MRPcaWeight: Decodable, Sendable, Hashable {
    let tenor: Double
    let w: Double
}

struct MRPcaComponent: Decodable, Sendable, Identifiable, Hashable {
    let component: String
    let varianceShare: Double
    let dv01: Double
    let volAnnualBp: Double
    let weights: [MRPcaWeight]
    var id: String { component }

    enum CodingKeys: String, CodingKey {
        case component, dv01, weights
        case varianceShare = "variance_share"
        case volAnnualBp = "vol_annual_bp"
    }
}

struct MRPcaDv01: Decodable, Sendable, Hashable {
    let tenor: Double
    let dv01: Double
}

struct MRPca: Decodable, Sendable {
    let pcaVar: Double
    let parallelVar: Double
    let varianceExplained: Double
    let components: [MRPcaComponent]
    let dv01Vector: [MRPcaDv01]
    let note: String

    enum CodingKeys: String, CodingKey {
        case components, note
        case pcaVar = "pca_var"
        case parallelVar = "parallel_var"
        case varianceExplained = "variance_explained"
        case dv01Vector = "dv01_vector"
    }
}

extension BridgeClient {
    func marketRiskPca(confidence: Double, window: Int) async throws -> MRPca {
        try await get("marketrisk/pca?confidence=\(confidence)&window=\(window)")
    }

    func marketRisk(confidence: Double, window: Int, horizon: Int,
                    stress: String = "") async throws -> MROverview {
        var path = "marketrisk?confidence=\(confidence)&window=\(window)&horizon=\(horizon)"
        if !stress.isEmpty { path += "&stress=\(stress)" }
        return try await get(path)
    }

    func marketRiskBacktest(confidence: Double, window: Int) async throws -> MRBacktest {
        try await get("marketrisk/backtest?confidence=\(confidence)&window=\(window)")
    }
}

// MARK: - View model

@MainActor
@Observable
final class MarketRiskViewModel {
    var confidence: Double = 0.99
    var window: Int = 500
    var horizon: Int = 1
    var stress: String = ""            // "" = rolling window, else named period

    var overview: MROverview?
    var backtest: MRBacktest?
    var pca: MRPca?
    var isLoading = false
    var errorMessage: String?

    private let client = BridgeClient()

    func run() async {
        isLoading = true
        errorMessage = nil
        do {
            async let ov = client.marketRisk(confidence: confidence, window: window,
                                             horizon: horizon, stress: stress)
            async let bt = client.marketRiskBacktest(confidence: confidence, window: window)
            overview = try await ov
            backtest = try await bt
            pca = try? await client.marketRiskPca(confidence: confidence, window: window)
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}

// MARK: - Pane

/// ERS-style Market Risk workstation: HypPL from full revaluation on real
/// historical factor shifts, VaR/ES by method, distribution, backtesting.
struct MarketRiskPane: View {
    @State private var vm = MarketRiskViewModel()

    var body: some View {
        ScreenScaffold {
            PageHeader("Market Risk", subtitle: "HypPL · full revaluation · VaR / ES / backtesting")
            controls
            if let message = vm.errorMessage {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.negative)
            }
            if let ov = vm.overview {
                content(ov)
            } else if vm.isLoading {
                SkeletonScreen()
            } else {
                GlassCard {
                    VStack(spacing: Theme.s3) {
                        Image(systemName: "chart.bar.fill")
                            .font(.system(size: 32)).foregroundStyle(.tertiary)
                        Text("Two-step process по Calypso: генерация исторических сдвигов (IMOEX, КБД 5Y, RVI) → полная переоценка книги на каждом сценарии.")
                            .font(.caption).foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                        Button("Рассчитать") { Task { await vm.run() } }
                            .buttonStyle(.borderedProminent)
                    }
                    .frame(maxWidth: .infinity, minHeight: 180)
                }
            }
        }
        .task { if vm.overview == nil { await vm.run() } }
    }

    private var controls: some View {
        HStack(spacing: Theme.s3) {
            Picker("Confidence", selection: $vm.confidence) {
                Text("99%").tag(0.99)
                Text("97.5%").tag(0.975)
                Text("95%").tag(0.95)
            }
            .pickerStyle(.segmented).fixedSize()
            Picker("Window", selection: $vm.window) {
                Text("250d").tag(250)
                Text("500d").tag(500)
                Text("1000d").tag(1000)
            }
            .pickerStyle(.segmented).fixedSize()
            .disabled(!vm.stress.isEmpty)
            Picker("Period", selection: $vm.stress) {
                Text("Rolling").tag("")
                Text("Stress 2022").tag("2022")
                Text("Stress 2024–25").tag("2024h2")
            }
            .pickerStyle(.segmented).fixedSize()
            Picker("Horizon", selection: $vm.horizon) {
                Text("1d").tag(1)
                Text("10d").tag(10)
            }
            .pickerStyle(.segmented).fixedSize()
            Button {
                Task { await vm.run() }
            } label: {
                if vm.isLoading {
                    ProgressView().controlSize(.small)
                } else {
                    Label("Run", systemImage: "play.fill")
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(vm.isLoading)
            Spacer()
        }
    }

    @ViewBuilder
    private func content(_ ov: MROverview) -> some View {
        KPIStrip(items: [
            KPICard(label: ov.stress.isEmpty
                        ? "VaR \(Int(ov.confidence * 100))% · \(ov.horizon)d"
                        : "Stress VaR \(Int(ov.confidence * 100))%",
                    value: Fmt.money(ov.varValue),
                    sub: ov.stress.isEmpty ? "historical full reprice" : ov.stressPeriod,
                    accent: Theme.negative, icon: "shield.lefthalf.filled"),
            KPICard(label: "Expected shortfall", value: Fmt.money(ov.es),
                    sub: "tail mean beyond VaR", accent: Theme.warning,
                    icon: "waveform.path.ecg"),
            KPICard(label: "Scenarios", value: "\(ov.nScenarios)",
                    sub: "joint historical shifts", accent: Theme.accent, icon: "clock.arrow.circlepath"),
            KPICard(label: "Portfolio", value: Fmt.money(ov.portfolioValue),
                    sub: "\(ov.positions) positions", accent: Theme.bucketColor("Equity"),
                    icon: "briefcase.fill"),
            KPICard(label: "Backtest", value: vm.backtest?.trafficLight.capitalized ?? "—",
                    sub: backtestSub, accent: zoneColor, icon: "checkmark.seal"),
        ])

        HStack(alignment: .top, spacing: Theme.s4) {
            distributionCard(ov)
            methodsCard(ov)
        }
        hypplCard(ov)
        HStack(alignment: .top, spacing: Theme.s4) {
            backtestCard
            extremesCard(ov)
        }
        if let pca = vm.pca {
            pcaCard(pca)
        }
        factorsCard(ov)
    }

    private var backtestSub: String {
        guard let bt = vm.backtest else { return "" }
        return "\(bt.nExceptions) breaches / exp \(String(format: "%.1f", bt.expectedExceptions))"
    }

    private func biasLabel(_ bias: String) -> String {
        switch bias {
        case "conservative": return "консервативна (капитал завышен)"
        case "aggressive": return "агрессивна (риск недооценён)"
        default: return "в норме"
        }
    }

    private var zoneColor: Color {
        switch vm.backtest?.trafficLight {
        case "green": return Theme.positive
        case "amber": return Theme.warning
        default: return Theme.negative
        }
    }

    private func distributionCard(_ ov: MROverview) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("HypPL distribution", icon: "chart.bar.fill")
                Chart {
                    ForEach(ov.histogram, id: \.x) { bin in
                        BarMark(x: .value("P&L", bin.x), y: .value("Count", bin.count))
                            .foregroundStyle(bin.x < ov.varLine
                                             ? Theme.negative.gradient
                                             : Theme.accent.opacity(0.7).gradient)
                    }
                    RuleMark(x: .value("VaR", ov.varLine))
                        .foregroundStyle(Theme.negative)
                        .lineStyle(StrokeStyle(lineWidth: 1.5, dash: [4]))
                        .annotation(position: .top, alignment: .leading) {
                            Text("VaR").font(.system(size: 9, weight: .semibold))
                                .foregroundStyle(Theme.negative)
                        }
                }
                .frame(height: 220)
                Text("Гипотетический P&L текущего портфеля на \(ov.nScenarios) исторических сценариях; хвост за VaR — красный.")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
    }

    private func methodsCard(_ ov: MROverview) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("VaR by method", icon: "list.number")
                VStack(spacing: 4) {
                    ForEach(ov.methods) { m in
                        HStack {
                            Text(m.label).font(.system(size: 11)).lineLimit(1)
                            Spacer()
                            VStack(alignment: .trailing, spacing: 1) {
                                Text(Fmt.money(m.varValue))
                                    .font(.system(size: 12, weight: .semibold)).monospacedDigit()
                                Text("ES \(Fmt.money(m.es))")
                                    .font(.system(size: 9)).monospacedDigit()
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 3)
                        if m.id != ov.methods.last?.id { Divider() }
                    }
                }
                Text("Один и тот же HypPL — пять методик: сравнение model risk по Calypso §2.3.")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
        .frame(width: 320)
    }

    private func hypplCard(_ ov: MROverview) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("HypPL time series", icon: "chart.xyaxis.line")
                Chart {
                    ForEach(ov.hyppl, id: \.date) { pt in
                        LineMark(x: .value("Date", pt.date), y: .value("P&L", pt.pnl))
                            .foregroundStyle(Theme.accent.opacity(0.85))
                    }
                    RuleMark(y: .value("VaR", ov.varLine))
                        .foregroundStyle(Theme.negative)
                        .lineStyle(StrokeStyle(lineWidth: 1, dash: [4]))
                    if let bt = vm.backtest {
                        ForEach(bt.rows.filter(\.breach), id: \.date) { row in
                            PointMark(x: .value("Date", row.date), y: .value("P&L", row.pnl))
                                .foregroundStyle(Theme.negative)
                                .symbolSize(40)
                        }
                    }
                }
                .chartXAxis {
                    AxisMarks(values: .automatic(desiredCount: 6))
                }
                .frame(height: 200)
                Text("Ежедневный HypPL против линии VaR; точки — пробои (backtesting against HypPL).")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
    }

    @ViewBuilder
    private var backtestCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Backtesting", icon: "checkmark.seal")
                if let bt = vm.backtest {
                    KeyValueRow(key: "Observations", value: "\(bt.nObs)")
                    KeyValueRow(key: "Exceptions",
                                value: "\(bt.nExceptions) (expected \(String(format: "%.1f", bt.expectedExceptions)))")
                    KeyValueRow(key: "Kupiec POF p-value",
                                value: bt.kupiec?.pValue.map { String(format: "%.4f", $0) } ?? "—",
                                valueColor: (bt.kupiec?.reject ?? false) ? Theme.warning : Theme.positive)
                    KeyValueRow(key: "Basel traffic light", value: bt.trafficLight.capitalized,
                                valueColor: zoneColor)
                    if let bias = bt.bias {
                        KeyValueRow(key: "Смещение модели", value: biasLabel(bias),
                                    valueColor: bias == "aggressive" ? Theme.negative
                                                : bias == "conservative" ? Theme.warning
                                                : Theme.positive)
                    }
                    KeyValueRow(key: "Rolling lookback", value: "\(bt.lookback)d")
                    Text("Kupiec reject = частота пробоев статистически не соответствует уровню доверия; направление показывает, завышает модель риск или занижает.")
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                } else {
                    Text("Нет данных").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func extremesCard(_ ov: MROverview) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Tail scenarios", icon: "exclamationmark.triangle")
                ForEach(ov.worst, id: \.date) { w in
                    HStack {
                        Text(w.date).font(.system(size: 11)).monospacedDigit()
                        Spacer()
                        Text(Fmt.money(w.pnl))
                            .font(.system(size: 11, weight: .semibold)).monospacedDigit()
                            .foregroundStyle(Theme.negative)
                    }
                }
                Divider()
                ForEach(ov.best.prefix(2), id: \.date) { b in
                    HStack {
                        Text(b.date).font(.system(size: 11)).monospacedDigit()
                        Spacer()
                        Text(Fmt.money(b.pnl))
                            .font(.system(size: 11, weight: .semibold)).monospacedDigit()
                            .foregroundStyle(Theme.positive)
                    }
                }
                Text("Даты — реальные торговые дни из истории маркет даты.")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
        .frame(width: 300)
    }

    /// PCA of the КБД curve: level/slope/curvature loadings + the book's
    /// bucketed DV01 -> PCA-VaR vs the parallel treatment.
    private func pcaCard(_ pca: MRPca) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    BlockTitle("Rate factors (PCA)", icon: "point.3.connected.trianglepath.dotted")
                    Spacer()
                    Text("\(Fmt.percent(pca.varianceExplained * 100, digits: 1)) дисперсии на 3 PC")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                HStack(alignment: .top, spacing: Theme.s4) {
                    Chart {
                        ForEach(pca.components) { comp in
                            ForEach(comp.weights, id: \.tenor) { w in
                                LineMark(x: .value("Tenor", w.tenor),
                                         y: .value("Weight", w.w),
                                         series: .value("PC", comp.component))
                                    .foregroundStyle(by: .value("PC", comp.component))
                                PointMark(x: .value("Tenor", w.tenor),
                                          y: .value("Weight", w.w))
                                    .foregroundStyle(by: .value("PC", comp.component))
                                    .symbolSize(20)
                            }
                        }
                        RuleMark(y: .value("zero", 0))
                            .foregroundStyle(.tertiary)
                            .lineStyle(StrokeStyle(lineWidth: 0.5, dash: [3]))
                    }
                    .chartXAxisLabel("Тенор КБД, лет")
                    .frame(height: 180)

                    VStack(alignment: .leading, spacing: Theme.s2) {
                        ForEach(pca.components) { comp in
                            KeyValueRow(key: comp.component,
                                        value: "\(Fmt.percent(comp.varianceShare * 100, digits: 1)) · σ \(Fmt.number(comp.volAnnualBp, digits: 0))bp")
                        }
                        Divider()
                        KeyValueRow(key: "PCA-VaR", value: Fmt.money(pca.pcaVar),
                                    valueColor: Theme.negative)
                        KeyValueRow(key: "Parallel 5Y VaR", value: Fmt.money(pca.parallelVar))
                        KeyValueRow(key: "DV01 профиль",
                                    value: pca.dv01Vector
                                        .filter { abs($0.dv01) > 1 }
                                        .map { "\(Fmt.number($0.tenor, digits: 2))y: \(Fmt.number($0.dv01, digits: 0))" }
                                        .joined(separator: "  "))
                    }
                    .frame(width: 300)
                }
                Text(pca.note).font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
    }

    private func factorsCard(_ ov: MROverview) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s2) {
                BlockTitle("Risk factors & data quality", icon: "cylinder.split.1x2")
                ForEach(ov.factors, id: \.self) { f in
                    Label(f, systemImage: "circle.fill")
                        .font(.system(size: 11))
                        .labelStyle(TinyDotLabelStyle())
                }
                ForEach(ov.dataQuality, id: \.self) { q in
                    Label(q, systemImage: "exclamationmark.triangle")
                        .font(.system(size: 10)).foregroundStyle(Theme.warning)
                }
            }
        }
    }
}

private struct TinyDotLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) {
            configuration.icon.font(.system(size: 4)).foregroundStyle(.tertiary)
            configuration.title
        }
    }
}
