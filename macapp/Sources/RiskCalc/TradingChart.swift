import SwiftUI
import Charts

/// TradingView-style price chart: candle/line/yield, SMA overlay, log scale,
/// crosshair OHLC readout, and a volume sub-pane. The range selector lives in the
/// parent (it drives the history fetch); this renders whatever bars it's given.
struct TradingChart: View {
    let bars: [MDBar]
    var isBond: Bool = false

    enum Mode: String, CaseIterable, Identifiable { case candle = "Candles", line = "Line", yield = "Yield"; var id: String { rawValue } }

    @State private var mode: Mode = .candle
    @State private var showSMA = true
    @State private var logScale = false
    @State private var hover: MDBar?

    private var smaPeriod: Int { 20 }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            controls
            readout
            priceChart.frame(height: 280)
            volumeChart.frame(height: 60)
        }
    }

    // MARK: controls

    private var controls: some View {
        HStack(spacing: Theme.s3) {
            Picker("", selection: $mode) {
                ForEach(isBond ? Mode.allCases : [.candle, .line]) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented).fixedSize().labelsHidden()
            Toggle("SMA\(smaPeriod)", isOn: $showSMA).toggleStyle(.button).controlSize(.small)
            Toggle("Log", isOn: $logScale).toggleStyle(.button).controlSize(.small)
            Spacer()
        }
        .font(.system(size: 11))
    }

    // MARK: crosshair readout

    private var readout: some View {
        let b = hover ?? bars.last
        return HStack(spacing: Theme.s3) {
            if let b {
                Text(b.date).foregroundStyle(.secondary)
                if mode == .yield, let y = b.yld {
                    Text("Yield \(Fmt.percent(y, digits: 2))")
                } else {
                    label("O", b.open); label("H", b.high); label("L", b.low)
                    label("C", b.close)
                    if let v = b.volume { Text("Vol \(Fmt.money(v))").foregroundStyle(.secondary) }
                }
            }
            Spacer()
        }
        .font(.system(size: 11, weight: .medium)).monospacedDigit().frame(height: 14)
    }

    private func label(_ t: String, _ v: Double?) -> some View {
        Text("\(t) \(v.map { Fmt.number($0, digits: 2) } ?? "—")")
    }

    // MARK: price chart

    private var seriesValues: [Double] {
        mode == .yield ? bars.compactMap { $0.yld } : bars.map { $0.close }
    }

    private var yDomain: ClosedRange<Double> {
        let vs = seriesValues
        guard let lo = vs.min(), let hi = vs.max(), hi > lo else { return 0...1 }
        let pad = (hi - lo) * 0.08
        let low = logScale ? max(lo * 0.98, 0.0001) : lo - pad
        return low...(hi + pad)
    }

    @ViewBuilder
    private var priceChart: some View {
        Chart {
            if mode == .candle {
                ForEach(bars) { b in
                    let up = b.close >= (b.open ?? b.close)
                    RuleMark(x: .value("d", b.dateValue),
                             yStart: .value("l", b.low ?? b.close), yEnd: .value("h", b.high ?? b.close))
                        .foregroundStyle(up ? Theme.positive : Theme.negative).lineStyle(.init(lineWidth: 1))
                    RectangleMark(x: .value("d", b.dateValue),
                                  yStart: .value("o", b.open ?? b.close), yEnd: .value("c", b.close),
                                  width: .fixed(bars.count > 160 ? 2 : 5))
                        .foregroundStyle(up ? Theme.positive : Theme.negative)
                }
            } else {
                ForEach(bars) { b in
                    let v = mode == .yield ? (b.yld ?? 0) : b.close
                    AreaMark(x: .value("d", b.dateValue), yStart: .value("f", yDomain.lowerBound), yEnd: .value("v", v))
                        .foregroundStyle(.linearGradient(colors: [Theme.accent.opacity(0.20), Theme.accent.opacity(0.02)],
                                                         startPoint: .top, endPoint: .bottom))
                        .interpolationMethod(.monotone)
                    LineMark(x: .value("d", b.dateValue), y: .value("v", v))
                        .foregroundStyle(Theme.accent).lineStyle(.init(lineWidth: 1.8)).interpolationMethod(.monotone)
                }
            }
            if showSMA && mode != .yield {
                ForEach(sma()) { p in
                    LineMark(x: .value("d", p.date), y: .value("sma", p.value), series: .value("s", "SMA"))
                        .foregroundStyle(Theme.warning).lineStyle(.init(lineWidth: 1.2))
                }
            }
            if let h = hover {
                RuleMark(x: .value("d", h.dateValue)).foregroundStyle(.secondary.opacity(0.4)).lineStyle(.init(lineWidth: 1))
            }
        }
        .chartYScale(domain: yDomain, type: logScale ? .log : .linear)
        .chartXAxis { AxisMarks(values: .automatic(desiredCount: 6)) }
        .chartOverlay { proxy in crosshairOverlay(proxy) }
    }

    private func crosshairOverlay(_ proxy: ChartProxy) -> some View {
        GeometryReader { geo in
            Rectangle().fill(.clear).contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0)
                    .onChanged { v in
                        guard let plot = proxy.plotFrame else { return }
                        let x = v.location.x - geo[plot].origin.x
                        if let d: Date = proxy.value(atX: x) { hover = nearest(d) }
                    }
                    .onEnded { _ in hover = nil })
        }
    }

    private func nearest(_ d: Date) -> MDBar? {
        bars.min(by: { abs($0.dateValue.timeIntervalSince(d)) < abs($1.dateValue.timeIntervalSince(d)) })
    }

    // MARK: volume sub-pane

    @ViewBuilder
    private var volumeChart: some View {
        Chart(bars) { b in
            let up = b.close >= (b.open ?? b.close)
            BarMark(x: .value("d", b.dateValue), y: .value("vol", b.volume ?? 0))
                .foregroundStyle((up ? Theme.positive : Theme.negative).opacity(0.45))
        }
        .chartYAxis { AxisMarks(values: .automatic(desiredCount: 2)) }
        .chartXAxis(.hidden)
    }

    // MARK: SMA

    private struct SMAPoint: Identifiable { let date: Date; let value: Double; var id: Date { date } }

    private func sma() -> [SMAPoint] {
        let closes = bars.map { $0.close }
        guard closes.count >= smaPeriod else { return [] }
        var out: [SMAPoint] = []
        var window = 0.0
        for i in closes.indices {
            window += closes[i]
            if i >= smaPeriod { window -= closes[i - smaPeriod] }
            if i >= smaPeriod - 1 { out.append(.init(date: bars[i].dateValue, value: window / Double(smaPeriod))) }
        }
        return out
    }
}
