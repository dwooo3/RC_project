import SwiftUI
import WebKit

/// TradingView chart — rendered by TradingView's own open-source Lightweight
/// Charts™ (Apache 2.0, vendored in Resources/lightweight-charts.js) inside a
/// WKWebView. Native TV behaviour: high/low-aware autoscale, wheel zoom + drag
/// pan, crosshair with OHLC legend, volume histogram pane, SMA overlay, log
/// scale. `window.render(cfg)` redraws on data change and `window.updateLast(bar)`
/// is the live-update hook for streaming refreshes.
struct TradingChart: View {
    let bars: [MDBar]
    let isBond: Bool
    let preferLine: Bool

    enum Mode: String, CaseIterable, Identifiable {
        case candle = "Candles", line = "Line", yield = "Yield"
        var id: String { rawValue }
    }

    @State private var mode: Mode
    @State private var showSMA = true
    @State private var logScale = false

    init(bars: [MDBar], isBond: Bool = false, preferLine: Bool = false) {
        self.bars = bars
        self.isBond = isBond
        self.preferLine = preferLine
        _mode = State(initialValue: preferLine ? .line : .candle)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            controls
            LWChartView(bars: bars, mode: mode.rawValue, showSMA: showSMA, logScale: logScale)
                .frame(height: 380)
        }
    }

    private var controls: some View {
        HStack(spacing: Theme.s3) {
            Picker("", selection: $mode) {
                ForEach(isBond ? Mode.allCases : [.candle, .line]) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented).fixedSize().labelsHidden()
            Toggle("SMA20", isOn: $showSMA).toggleStyle(.button).controlSize(.small)
            Toggle("Log", isOn: $logScale).toggleStyle(.button).controlSize(.small)
            Spacer()
        }
        .font(.system(size: 11))
    }
}

// MARK: - WKWebView wrapper around Lightweight Charts

private struct LWChartView: NSViewRepresentable {
    let bars: [MDBar]
    let mode: String          // "Candles" | "Line" | "Yield"
    let showSMA: Bool
    let logScale: Bool

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var ready = false
        var pending: String?
        var lastSig = ""

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            ready = true
            if let js = pending {
                pending = nil
                webView.evaluateJavaScript(js)
            }
        }
    }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        web.setValue(false, forKey: "drawsBackground")   // transparent over the app card
        web.loadHTMLString(Self.html, baseURL: nil)
        return web
    }

    func updateNSView(_ web: WKWebView, context: Context) {
        let sig = "\(bars.count)|\(bars.first?.date ?? "")|\(bars.last?.date ?? "")"
            + "|\(bars.first?.close ?? 0)|\(bars.last?.close ?? 0)|\(bars.last?.volume ?? 0)"
            + "|\(mode)|\(showSMA)|\(logScale)"
        guard sig != context.coordinator.lastSig else { return }
        context.coordinator.lastSig = sig
        let js = "window.render(\(configJSON()));"
        if context.coordinator.ready {
            web.evaluateJavaScript(js)
        } else {
            context.coordinator.pending = js
        }
    }

    // MARK: config payload

    private struct LWBar: Encodable {
        let time: String
        let open: Double?
        let high: Double?
        let low: Double?
        let close: Double
        let volume: Double?
        let yld: Double?
    }

    private struct LWConfig: Encodable {
        let bars: [LWBar]
        let mode: String
        let sma: Bool
        let log: Bool
    }

    private func configJSON() -> String {
        let payload = LWConfig(
            bars: bars.map { LWBar(time: $0.date, open: $0.open, high: $0.high,
                                   low: $0.low, close: $0.close, volume: $0.volume, yld: $0.yld) },
            mode: mode, sma: showSMA, log: logScale)
        guard let data = try? JSONEncoder().encode(payload),
              let s = String(data: data, encoding: .utf8) else { return "{}" }
        return s
    }

    // MARK: page (library injected inline from the vendored bundle)

    private static let libraryJS: String = {
        guard let url = Bundle.module.url(forResource: "lightweight-charts", withExtension: "js",
                                          subdirectory: "Resources"),
              let js = try? String(contentsOf: url, encoding: .utf8) else { return "" }
        return js
    }()

    private static let appJS = #"""
    let chart = null, priceSeries = null, volSeries = null, smaSeries = null;
    let lastBar = null, lastMode = 'Candles';

    const UP = '#26a69a', DOWN = '#ef5350', ACCENT = '#2962ff', SMA = '#f5a623';

    function el(id) { return document.getElementById(id); }

    function makeChart() {
        chart = LightweightCharts.createChart(el('c'), {
            autoSize: true,
            layout: { background: { type: 'solid', color: 'transparent' },
                      textColor: '#9aa0aa', fontSize: 11,
                      fontFamily: '-apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif' },
            grid: { vertLines: { color: 'rgba(255,255,255,0.05)' },
                    horzLines: { color: 'rgba(255,255,255,0.05)' } },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: { color: 'rgba(255,255,255,0.3)', width: 1, style: 3,
                            labelBackgroundColor: '#3b4754' },
                horzLine: { color: 'rgba(255,255,255,0.3)', width: 1, style: 3,
                            labelBackgroundColor: '#3b4754' },
            },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.12)',
                               scaleMargins: { top: 0.08, bottom: 0.24 } },
            timeScale: { borderColor: 'rgba(255,255,255,0.12)', rightOffset: 2 },
            localization: { locale: 'ru-RU' },
        });
        chart.subscribeCrosshairMove(onCrosshair);
    }

    function precisionFor(v) {
        if (v >= 10000) return { precision: 0, minMove: 1 };
        if (v >= 100)   return { precision: 2, minMove: 0.01 };
        if (v >= 1)     return { precision: 2, minMove: 0.01 };
        return { precision: 4, minMove: 0.0001 };
    }

    function fmtN(v, dp) {
        if (v === null || v === undefined) return '—';
        return v.toLocaleString('ru-RU', { minimumFractionDigits: dp, maximumFractionDigits: dp });
    }

    function legendFor(bar, mode) {
        if (!bar) { el('legend').innerHTML = ''; return; }
        const dp = (Math.abs(bar.close) >= 10000) ? 0 : 2;
        const up = bar.close >= (bar.open ?? bar.close);
        const col = up ? UP : DOWN;
        if (mode === 'Yield') {
            el('legend').innerHTML =
                `<span class="d">${bar.time}</span> <b style="color:${ACCENT}">YTM ${fmtN(bar.close, 2)}%</b>`;
            return;
        }
        const chg = (bar.open && bar.open !== 0) ? ((bar.close - bar.open) / bar.open * 100) : null;
        el('legend').innerHTML =
            `<span class="d">${bar.time}</span>` +
            ` O <b>${fmtN(bar.open, dp)}</b> H <b>${fmtN(bar.high, dp)}</b>` +
            ` L <b>${fmtN(bar.low, dp)}</b> C <b style="color:${col}">${fmtN(bar.close, dp)}</b>` +
            (chg !== null ? ` <b style="color:${col}">${chg >= 0 ? '+' : ''}${fmtN(chg, 2)}%</b>` : '') +
            (bar.volume ? ` <span class="d">Vol ${fmtN(bar.volume, 0)}</span>` : '');
    }

    function onCrosshair(param) {
        if (!priceSeries) return;
        if (!param || !param.time || !param.seriesData || param.seriesData.size === 0) {
            legendFor(lastBar, lastMode);
            return;
        }
        const sd = param.seriesData.get(priceSeries);
        if (!sd) { legendFor(lastBar, lastMode); return; }
        const v = param.seriesData.get(volSeries);
        const bar = {
            time: typeof param.time === 'string' ? param.time
                  : `${param.time.year}-${String(param.time.month).padStart(2, '0')}-${String(param.time.day).padStart(2, '0')}`,
            open: sd.open ?? sd.value, high: sd.high ?? sd.value,
            low: sd.low ?? sd.value, close: sd.close ?? sd.value,
            volume: v ? v.value : null,
        };
        legendFor(bar, lastMode);
    }

    window.render = function (cfg) {
        if (!chart) makeChart();
        if (priceSeries) { chart.removeSeries(priceSeries); priceSeries = null; }
        if (volSeries)   { chart.removeSeries(volSeries);   volSeries = null; }
        if (smaSeries)   { chart.removeSeries(smaSeries);   smaSeries = null; }

        const bars = cfg.bars || [];
        lastMode = cfg.mode;
        if (bars.length === 0) { el('legend').innerHTML = ''; return; }

        const yieldMode = cfg.mode === 'Yield';
        const lineMode = cfg.mode === 'Line' || yieldMode;
        const values = yieldMode
            ? bars.filter(b => b.yld !== null && b.yld !== undefined)
                  .map(b => ({ time: b.time, value: b.yld }))
            : bars.map(b => ({ time: b.time, value: b.close }));
        const typical = values.length ? Math.abs(values[values.length - 1].value) : 1;
        const pf = yieldMode ? { precision: 2, minMove: 0.01 } : precisionFor(typical);

        if (lineMode) {
            priceSeries = chart.addAreaSeries({
                lineColor: ACCENT, lineWidth: 2,
                topColor: 'rgba(41,98,255,0.25)', bottomColor: 'rgba(41,98,255,0.02)',
                priceFormat: { type: 'price', ...pf },
                crosshairMarkerRadius: 3,
            });
            priceSeries.setData(values);
        } else {
            priceSeries = chart.addCandlestickSeries({
                upColor: UP, downColor: DOWN, borderVisible: false,
                wickUpColor: UP, wickDownColor: DOWN,
                priceFormat: { type: 'price', ...pf },
            });
            priceSeries.setData(bars.map(b => {
                const o = b.open ?? b.close;
                const h = Math.max(b.high ?? b.close, o, b.close);
                const l = Math.min(b.low ?? b.close, o, b.close);
                return { time: b.time, open: o, high: h, low: l, close: b.close };
            }));
        }

        if (!yieldMode) {
            volSeries = chart.addHistogramSeries({
                priceScaleId: 'vol',
                priceFormat: { type: 'volume' },
                lastValueVisible: false, priceLineVisible: false,
            });
            chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
            volSeries.setData(bars.map(b => ({
                time: b.time, value: b.volume ?? 0,
                color: (b.close >= (b.open ?? b.close)) ? 'rgba(38,166,154,0.45)' : 'rgba(239,83,80,0.45)',
            })));
        }

        if (cfg.sma && !yieldMode) {
            const closes = bars.map(b => b.close);
            const pts = [];
            let acc = 0;
            for (let i = 0; i < closes.length; i++) {
                acc += closes[i];
                if (i >= 20) acc -= closes[i - 20];
                if (i >= 19) pts.push({ time: bars[i].time, value: acc / 20 });
            }
            smaSeries = chart.addLineSeries({
                color: SMA, lineWidth: 1.5,
                lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
            });
            smaSeries.setData(pts);
        }

        chart.priceScale('right').applyOptions({
            mode: cfg.log ? LightweightCharts.PriceScaleMode.Logarithmic
                          : LightweightCharts.PriceScaleMode.Normal,
            autoScale: true,
        });
        chart.timeScale().fitContent();

        const lb = bars[bars.length - 1];
        lastBar = { time: lb.time, open: lb.open ?? lb.close, high: lb.high ?? lb.close,
                    low: lb.low ?? lb.close, close: yieldMode ? (lb.yld ?? lb.close) : lb.close,
                    volume: lb.volume };
        legendFor(lastBar, lastMode);
    };

    // Live-update hook: stream a bar into the current series without a full redraw.
    window.updateLast = function (b) {
        if (!priceSeries || !b) return;
        if (lastMode === 'Candles') {
            const o = b.open ?? b.close;
            priceSeries.update({ time: b.time, open: o,
                                 high: Math.max(b.high ?? b.close, o, b.close),
                                 low: Math.min(b.low ?? b.close, o, b.close), close: b.close });
        } else {
            priceSeries.update({ time: b.time, value: lastMode === 'Yield' ? (b.yld ?? b.close) : b.close });
        }
        if (volSeries && b.volume !== null && b.volume !== undefined) {
            volSeries.update({ time: b.time, value: b.volume,
                               color: (b.close >= (b.open ?? b.close)) ? 'rgba(38,166,154,0.45)' : 'rgba(239,83,80,0.45)' });
        }
        lastBar = { time: b.time, open: b.open ?? b.close, high: b.high ?? b.close,
                    low: b.low ?? b.close, close: b.close, volume: b.volume };
        legendFor(lastBar, lastMode);
    };
    """#

    private static var html: String {
        """
        <!doctype html><html><head><meta charset="utf-8">
        <style>
        html,body{margin:0;padding:0;background:transparent;overflow:hidden;height:100%;-webkit-user-select:none}
        #c{position:absolute;inset:0}
        #legend{position:absolute;top:6px;left:8px;z-index:10;pointer-events:none;
                font:500 11px -apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;
                color:#9aa0aa;font-variant-numeric:tabular-nums;white-space:nowrap}
        #legend b{color:#e8eaed;font-weight:600}
        #legend .d{color:#6f7680}
        </style></head><body>
        <div id="c"></div><div id="legend"></div>
        <script>\(libraryJS)</script>
        <script>\(appJS)</script>
        </body></html>
        """
    }
}
