import SwiftUI
import WebKit

/// TradingView chart — rendered by TradingView's own open-source Lightweight
/// Charts™ (Apache 2.0, vendored in Resources/lightweight-charts.js) inside a
/// WKWebView. Native TV behaviour: high/low-aware autoscale, wheel zoom + drag
/// pan, crosshair with OHLC legend, volume histogram pane.
/// `window.render(cfg)` redraws on data change and `window.updateLast(bar)`
/// is the live-update hook for streaming refreshes.
/// Chart pane only — mode (Candles/Line/Yield) is owned by the caller, which
/// renders it in its own compact controls row. Price scale is always linear;
/// SMA/log toggles were dropped as noise.
struct TradingChart: View {
    let bars: [MDBar]
    let mode: String            // JS ids: "Candles" | "Line" | "Yield"
    let events: [ChartEvent]    // coupons / offers / dividends / maturity …
    @Environment(\.colorScheme) private var scheme

    init(bars: [MDBar], mode: String = "Candles", events: [ChartEvent] = []) {
        self.bars = bars
        self.mode = mode
        self.events = events
    }

    var body: some View {
        LWChartView(bars: bars, mode: mode, events: events,
                    dark: scheme == .dark, accentHex: Theme.accent.hexRGB)
            .frame(height: 440)
    }
}

// MARK: - WKWebView wrapper around Lightweight Charts

private struct LWChartView: NSViewRepresentable {
    let bars: [MDBar]
    let mode: String          // "Candles" | "Line" | "Yield"
    let events: [ChartEvent]
    let dark: Bool            // drive the JS palette from the app color scheme
    let accentHex: String     // brand accent (user-tunable) for line/area series

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var ready = false
        var pending: String?
        var lastSig = ""
        // last rendered series identity — for the updateLast / keepView fast-paths
        var staticSig = ""
        var dataSig = ""
        var lastCount = 0
        var firstDate = ""
        var lastDate = ""
        var firstClose: Double?

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
        let co = context.coordinator
        let dataSig = "\(bars.count)|\(bars.first?.date ?? "")|\(bars.last?.date ?? "")"
            + "|\(bars.first?.close ?? 0)|\(bars.last?.close ?? 0)|\(bars.last?.volume ?? 0)"
            + "|ev\(events.count)"
        // Theme is part of the render signature: toggling light/dark or the
        // accent must force a full re-render (not the updateLast fast-path).
        let sig = dataSig + "|\(mode)|\(dark ? "d" : "l")|\(accentHex)"
        guard sig != co.lastSig else { return }
        co.lastSig = sig

        // Fast path (live polling): same series, only the tail bar refreshed or
        // one new bar appended → stream it via updateLast so zoom/pan survive.
        // The first bar's close must be unchanged too — otherwise the whole
        // series was refetched (e.g. a total-return / vs-index transform) and
        // every bar differs, which the tail fast-path would corrupt.
        let staticSig = "\(mode)|\(bars.first?.date ?? "")|\(dark ? "d" : "l")|\(accentHex)"
        let sameSeries = co.ready && staticSig == co.staticSig && !bars.isEmpty
            && bars.first?.close == co.firstClose
            && (bars.count == co.lastCount
                || (bars.count == co.lastCount + 1 && bars.dropLast().last?.date == co.lastDate))
        // Same data, only mode/SMA/log toggled → full render but keep the viewport.
        let keepView = co.ready && dataSig == co.dataSig
        let js: String
        if sameSeries, let last = bars.last, let barJSON = barJSON(last) {
            js = "window.updateLast(\(barJSON));"
        } else {
            js = "window.render(\(configJSON(keepView: keepView)));"
        }
        co.staticSig = staticSig
        co.dataSig = dataSig
        co.lastCount = bars.count
        co.firstDate = bars.first?.date ?? ""
        co.lastDate = bars.last?.date ?? ""
        co.firstClose = bars.first?.close
        if co.ready {
            web.evaluateJavaScript(js)
        } else {
            co.pending = "window.render(\(configJSON(keepView: false)));"
        }
    }

    // MARK: config payload

    private struct LWBar: Encodable {
        let time: String
        let t: Double?        // intraday: epoch seconds (takes precedence in JS)
        let open: Double?
        let high: Double?
        let low: Double?
        let close: Double
        let volume: Double?
        let yld: Double?
    }

    private struct LWTheme: Encodable {
        let dark: Bool
        let accent: String       // series line/area + measure legend
        let text: String         // base legend / axis labels
        let textStrong: String   // bold OHLC legend values
        let textDim: String      // date / muted legend
        let grid: String
        let cross: String
        let crossLabelBg: String
        let border: String       // price/time scale borders
        let areaTop: String
        let areaBottom: String
    }

    private struct LWConfig: Encodable {
        let bars: [LWBar]
        let mode: String
        let intraday: Bool
        let keepView: Bool
        let events: [ChartEvent]
        let theme: LWTheme
    }

    private var themePayload: LWTheme {
        let a = accentHex
        if dark {
            return LWTheme(
                dark: true, accent: a,
                text: "#9aa0aa", textStrong: "#e8eaed", textDim: "#6f7680",
                grid: "rgba(255,255,255,0.05)", cross: "rgba(255,255,255,0.30)",
                crossLabelBg: "#3b4754", border: "rgba(255,255,255,0.12)",
                areaTop: hexA(a, 0.25), areaBottom: hexA(a, 0.02))
        }
        return LWTheme(
            dark: false, accent: a,
            text: "#5b616e", textStrong: "#1c1c1e", textDim: "#9aa0aa",
            grid: "rgba(0,0,0,0.06)", cross: "rgba(0,0,0,0.35)",
            crossLabelBg: "#4a5560", border: "rgba(0,0,0,0.14)",
            areaTop: hexA(a, 0.22), areaBottom: hexA(a, 0.02))
    }

    /// "#rrggbb" + alpha → an rgba(...) string the JS palette can consume.
    private func hexA(_ hex: String, _ alpha: Double) -> String {
        let h = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
        guard h.count == 6, let v = Int(h, radix: 16) else {
            return "rgba(41,98,255,\(alpha))"
        }
        let r = (v >> 16) & 0xff, g = (v >> 8) & 0xff, b = v & 0xff
        return "rgba(\(r),\(g),\(b),\(alpha))"
    }

    private func lwBar(_ b: MDBar) -> LWBar {
        LWBar(time: b.date, t: b.ts, open: b.open, high: b.high,
              low: b.low, close: b.close, volume: b.volume, yld: b.yld)
    }

    private func configJSON(keepView: Bool = false) -> String {
        let payload = LWConfig(bars: bars.map(lwBar), mode: mode,
                               intraday: bars.last?.ts != nil,
                               keepView: keepView, events: events, theme: themePayload)
        guard let data = try? JSONEncoder().encode(payload),
              let s = String(data: data, encoding: .utf8) else { return "{}" }
        return s
    }

    private func barJSON(_ b: MDBar) -> String? {
        guard let data = try? JSONEncoder().encode(lwBar(b)) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    // MARK: page (library injected inline from the vendored bundle)

    private static let libraryJS: String = {
        guard let url = Bundle.module.url(forResource: "lightweight-charts", withExtension: "js",
                                          subdirectory: "Resources"),
              let js = try? String(contentsOf: url, encoding: .utf8) else { return "" }
        return js
    }()

    private static let appJS = #"""
    let chart = null, priceSeries = null, volSeries = null;
    let lastBar = null, lastMode = 'Candles';

    // Palette is theme-driven (light/dark + brand accent) — set by applyTheme
    // from the config the app sends; these are only first-paint fallbacks.
    const UP = '#26a69a', DOWN = '#ef5350';
    let ACCENT = '#2962ff';
    let THEME = null;

    function el(id) { return document.getElementById(id); }

    function makeChart() {
        chart = LightweightCharts.createChart(el('c'), {
            autoSize: true,
            layout: { background: { type: 'solid', color: 'transparent' },
                      textColor: '#9aa0aa', fontSize: 11, attributionLogo: false,
                      fontFamily: '-apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif' },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal,
                         vertLine: { width: 1, style: 3 }, horzLine: { width: 1, style: 3 } },
            rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.24 } },
            timeScale: { rightOffset: 2 },
            localization: { locale: 'ru-RU' },
        });
        chart.subscribeCrosshairMove(onCrosshair);
    }

    // Apply the light/dark palette to chart chrome + legend CSS. Called on
    // every render so a theme toggle re-colors the whole chart.
    function applyTheme(t) {
        if (!t) return;
        THEME = t;
        ACCENT = t.accent;
        if (chart) chart.applyOptions({
            layout: { textColor: t.text },
            grid: { vertLines: { color: t.grid }, horzLines: { color: t.grid } },
            crosshair: {
                vertLine: { color: t.cross, labelBackgroundColor: t.crossLabelBg },
                horzLine: { color: t.cross, labelBackgroundColor: t.crossLabelBg },
            },
            rightPriceScale: { borderColor: t.border },
            timeScale: { borderColor: t.border },
        });
        let st = el('legendTheme');
        if (!st) { st = document.createElement('style'); st.id = 'legendTheme'; document.head.appendChild(st); }
        st.textContent = '#legend{color:' + t.text + '}'
            + '#legend b{color:' + t.textStrong + '}'
            + '#legend .d{color:' + t.textDim + '}';
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

    // intraday bars carry epoch seconds in t; daily bars a yyyy-mm-dd string
    function timeFor(b) { return (b.t !== null && b.t !== undefined) ? b.t : b.time; }

    function fmtTime(t) {
        if (typeof t !== 'number') return t;
        const d = new Date(t * 1000);   // MSK wall-clock encoded as UTC
        return d.toLocaleString('ru-RU', { timeZone: 'UTC', day: '2-digit', month: '2-digit',
                                           hour: '2-digit', minute: '2-digit' });
    }

    function legendFor(bar, mode) {
        if (!bar) { el('legend').innerHTML = ''; return; }
        const dp = (Math.abs(bar.close) >= 10000) ? 0 : 2;
        const up = bar.close >= (bar.open ?? bar.close);
        const col = up ? UP : DOWN;
        if (mode === 'Yield') {
            el('legend').innerHTML =
                `<span class="d">${fmtTime(bar.time)}</span> <b style="color:${ACCENT}">YTM ${fmtN(bar.close, 2)}%</b>`;
            return;
        }
        if (mode === 'TotalReturn') {
            el('legend').innerHTML =
                `<span class="d">${fmtTime(bar.time)}</span> <b style="color:${ACCENT}">Полная доходность ${fmtN(bar.close, 2)}</b>`;
            return;
        }
        if (mode === 'RelIndex') {
            const rc = bar.close >= 100 ? UP : DOWN;
            el('legend').innerHTML =
                `<span class="d">${fmtTime(bar.time)}</span> <b style="color:${rc}">vs IMOEX ${fmtN(bar.close, 1)}</b> <span class="d">100 = вровень</span>`;
            return;
        }
        const chg = (bar.open && bar.open !== 0) ? ((bar.close - bar.open) / bar.open * 100) : null;
        el('legend').innerHTML =
            `<span class="d">${fmtTime(bar.time)}</span>` +
            ` O <b>${fmtN(bar.open, dp)}</b> H <b>${fmtN(bar.high, dp)}</b>` +
            ` L <b>${fmtN(bar.low, dp)}</b> C <b style="color:${col}">${fmtN(bar.close, dp)}</b>` +
            (chg !== null ? ` <b style="color:${col}">${chg >= 0 ? '+' : ''}${fmtN(chg, 2)}%</b>` : '') +
            (bar.volume ? ` <span class="d">Vol ${fmtN(bar.volume, 0)}</span>` : '');
    }

    // Event markers (coupons / offers / amortizations / maturity / dividends).
    // Snap each event to the first bar on/after its date so markers land on
    // real data points; drop events outside the loaded daily window.
    const EV_ACCENT = '#cc7859', EV_POS = '#22b356', EV_WARN = '#dc9a1a', EV_NEG = '#e64540';
    function markerFor(ev, t) {
        switch (ev.type) {
            case 'coupon':       return { time: t, position: 'belowBar', color: EV_ACCENT, shape: 'circle', size: 0.9 };
            case 'amortization': return { time: t, position: 'belowBar', color: EV_ACCENT, shape: 'square', text: 'Ам', size: 1.2 };
            case 'offer':        return { time: t, position: 'aboveBar', color: EV_WARN,  shape: 'square', text: 'Оферта', size: 1.2 };
            case 'maturity':     return { time: t, position: 'aboveBar', color: EV_NEG,   shape: 'arrowDown', text: 'Погашение', size: 1.2 };
            case 'dividend':     return { time: t, position: 'belowBar', color: EV_POS,   shape: 'circle', text: 'Див', size: 1.2 };
            default:             return { time: t, position: 'belowBar', color: '#9aa0aa', shape: 'circle', size: 0.9 };
        }
    }

    function applyMarkers(events, barTimes) {
        if (!priceSeries) return;
        if (!events || !events.length || !barTimes.length) { priceSeries.setMarkers([]); return; }
        const markers = [];
        for (const ev of events) {
            let t = null;
            for (const bt of barTimes) { if (bt >= ev.date) { t = bt; break; } }  // first bar >= event date
            if (t === null) continue;                                             // event beyond loaded range
            markers.push(markerFor(ev, t));
        }
        markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
        priceSeries.setMarkers(markers);
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
        const t = param.time;
        const bar = {
            time: (typeof t === 'string' || typeof t === 'number') ? t
                  : `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`,
            open: sd.open ?? sd.value, high: sd.high ?? sd.value,
            low: sd.low ?? sd.value, close: sd.close ?? sd.value,
            volume: v ? v.value : null,
        };
        legendFor(bar, lastMode);
    }

    window.render = function (cfg) {
        const firstRender = !chart;
        if (!chart) makeChart();
        applyTheme(cfg.theme);
        // keepView: same data, only mode/sma/log toggled — preserve the viewport
        const prevRange = (!firstRender && cfg.keepView)
            ? chart.timeScale().getVisibleLogicalRange() : null;
        if (priceSeries) { chart.removeSeries(priceSeries); priceSeries = null; }
        if (volSeries)   { chart.removeSeries(volSeries);   volSeries = null; }

        const bars = cfg.bars || [];
        lastMode = cfg.mode;
        if (bars.length === 0) {
            el('legend').innerHTML =
                '<span class="d">Нет данных — торги закрыты или источник недоступен</span>';
            return;
        }

        chart.applyOptions({ timeScale: { timeVisible: !!cfg.intraday, secondsVisible: false } });

        const yieldMode = cfg.mode === 'Yield';
        const lineMode = cfg.mode === 'Line' || yieldMode
            || cfg.mode === 'TotalReturn' || cfg.mode === 'RelIndex';
        const values = yieldMode
            ? bars.filter(b => b.yld !== null && b.yld !== undefined)
                  .map(b => ({ time: timeFor(b), value: b.yld }))
            : bars.map(b => ({ time: timeFor(b), value: b.close }));
        const typical = values.length ? Math.abs(values[values.length - 1].value) : 1;
        const pf = yieldMode ? { precision: 2, minMove: 0.01 } : precisionFor(typical);

        if (lineMode) {
            priceSeries = chart.addAreaSeries({
                lineColor: ACCENT, lineWidth: 2,
                topColor: (THEME ? THEME.areaTop : 'rgba(41,98,255,0.25)'),
                bottomColor: (THEME ? THEME.areaBottom : 'rgba(41,98,255,0.02)'),
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
                return { time: timeFor(b), open: o, high: h, low: l, close: b.close };
            }));
        }

        const hasVol = bars.some(b => (b.volume ?? 0) > 0);
        if (!yieldMode && hasVol) {
            volSeries = chart.addHistogramSeries({
                priceScaleId: 'vol',
                priceFormat: { type: 'volume' },
                lastValueVisible: false, priceLineVisible: false,
            });
            chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
            volSeries.setData(bars.map(b => ({
                time: timeFor(b), value: b.volume ?? 0,
                color: (b.close >= (b.open ?? b.close)) ? 'rgba(38,166,154,0.45)' : 'rgba(239,83,80,0.45)',
            })));
        }

        // event markers on the time axis (daily windows only) — events that
        // fall on an actual price bar (e.g. past dividends)
        if (!cfg.intraday) applyMarkers(cfg.events || [], bars.map(b => b.time));
        else priceSeries.setMarkers([]);

        chart.priceScale('right').applyOptions({
            mode: LightweightCharts.PriceScaleMode.Normal,
            autoScale: true,
        });
        if (prevRange) chart.timeScale().setVisibleLogicalRange(prevRange);
        else chart.timeScale().fitContent();

        const lb = bars[bars.length - 1];
        lastBar = { time: timeFor(lb), open: lb.open ?? lb.close, high: lb.high ?? lb.close,
                    low: lb.low ?? lb.close, close: yieldMode ? (lb.yld ?? lb.close) : lb.close,
                    volume: lb.volume };
        legendFor(lastBar, lastMode);
    };

    // Live-update hook: stream a bar into the current series without a full
    // redraw (zoom/pan survive the 15s polling).
    window.updateLast = function (b) {
        if (!priceSeries || !b) return;
        const t = timeFor(b);
        if (lastMode === 'Candles') {
            const o = b.open ?? b.close;
            priceSeries.update({ time: t, open: o,
                                 high: Math.max(b.high ?? b.close, o, b.close),
                                 low: Math.min(b.low ?? b.close, o, b.close), close: b.close });
        } else {
            priceSeries.update({ time: t, value: lastMode === 'Yield' ? (b.yld ?? b.close) : b.close });
        }
        if (volSeries && b.volume !== null && b.volume !== undefined) {
            volSeries.update({ time: t, value: b.volume,
                               color: (b.close >= (b.open ?? b.close)) ? 'rgba(38,166,154,0.45)' : 'rgba(239,83,80,0.45)' });
        }
        lastBar = { time: t, open: b.open ?? b.close, high: b.high ?? b.close,
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
        #c a[id^="tv"]{display:none!important}   /* attribution logo fallback (licence kept in the vendored js) */
        </style></head><body>
        <div id="c"></div><div id="legend"></div>
        <script>\(libraryJS)</script>
        <script>\(appJS)</script>
        </body></html>
        """
    }
}
