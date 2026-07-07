import SwiftUI

// MARK: - Universal instrument model (doc §10)
//
// The detail area is built around one presentation model, not per-type views.
// The layout (day-trades card, "Об инструменте" block, chart) is identical for
// every asset class — only the set of metrics/attributes and their labels
// change, and that composition lives here rather than as inline `if category ==`
// branches scattered across the views.

/// Broad instrument class, derived from the Market Data category id.
enum InstrumentType: String {
    case bond, equity, futures, option, index, fx, commodity, unknown

    init(category: String?) {
        switch category {
        case "bonds":       self = .bond
        case "equities":    self = .equity
        case "futures":     self = .futures
        case "options":     self = .option
        case "indices":     self = .index
        case "fx":          self = .fx
        case "commodities": self = .commodity
        default:            self = .unknown
        }
    }
}

/// One labelled figure in the day-trades card.
struct MetricItem: Identifiable {
    let id: String
    let title: String
    let value: String
    var color: Color = .primary
}

/// One characteristic in the "Об инструменте" block.
struct InstrumentAttribute: Identifiable {
    let id: String
    let title: String
    let value: String
    /// Analytics rows are emphasised (accent + semibold) above plain reference.
    var strong: Bool = false
}

/// The composed detail content: emphasised analytics, primary reference fields,
/// and the long tail of reference fields (folded away).
struct InstrumentDetail {
    var analytics: [InstrumentAttribute]
    var reference: [InstrumentAttribute]
    var extra: [InstrumentAttribute]
}

/// Chart event kinds (marked on the price axis).
enum InstrumentEventType: String {
    case coupon, offer, call, put, amortization, maturity   // bonds
    case dividend, earnings, split, buyback                 // equities
}

/// A dated event to mark on the price chart's time axis.
struct ChartEvent: Encodable, Identifiable {
    let id: String
    let date: String        // yyyy-MM-dd
    let type: String        // InstrumentEventType.rawValue
}

/// An upcoming dated event shown as a chip beside the chart (coupon schedules
/// are forward-looking, so these live off-axis).
struct UpcomingEvent: Identifiable {
    let id: String
    let type: InstrumentEventType
    let title: String
    let date: String
    let detail: String
}

// MARK: - Composition

enum InstrumentPresentation {

    /// "Торги за день" figures for the instrument's type. Pass `day` to show a
    /// live intraday session instead of the stored EOD day; `changePct`
    /// overrides the Δ% (e.g. the realtime quote's change vs previous close).
    static func dayMetrics(_ e: MDEntity, category: String, day: MDDay? = nil,
                           changePct: Double? = nil) -> [MetricItem] {
        guard let d = day ?? e.day else { return [] }
        let type = InstrumentType(category: category)
        func px(_ v: Double?) -> String { v.map { Fmt.number($0, digits: 2) } ?? "—" }

        var items: [MetricItem] = [
            MetricItem(id: "last", title: "Последняя", value: px(d.close)),
            MetricItem(id: "open", title: "Открытие",  value: px(d.open)),
            MetricItem(id: "high", title: "Максимум",  value: px(d.high)),
            MetricItem(id: "low",  title: "Минимум",   value: px(d.low)),
        ]
        // Bonds lead with yield; everything else with the daily change.
        if type == .bond {
            items.append(MetricItem(id: "yield", title: "Доходность",
                                    value: d.yield.map { Fmt.percent($0, digits: 2) } ?? "—"))
        } else {
            // quote's Δ% vs prev close when given, else vs the day's own open
            let chg: Double? = changePct ?? {
                if let c = d.close, let o = d.open, o != 0 { return (c - o) / o * 100 }
                return e.changePct
            }()
            items.append(MetricItem(id: "chg", title: "Δ%",
                                    value: chg.map { Fmt.signedPercent($0, digits: 2) } ?? "—",
                                    color: chg.map { Theme.changeColor($0) } ?? .primary))
        }
        items.append(MetricItem(id: "vol",    title: "Объём",  value: d.volume.map { Fmt.money($0) } ?? "—"))
        items.append(MetricItem(id: "val",    title: "Оборот", value: d.value.map { Fmt.money($0) } ?? "—"))
        items.append(MetricItem(id: "trades", title: "Сделки", value: d.numtrades.map { Fmt.number($0, digits: 0) } ?? "—"))
        return items
    }

    /// Analytics + reference attributes for the "Об инструменте" block.
    static func detail(_ e: MDEntity, category: String) -> InstrumentDetail {
        let type = InstrumentType(category: category)

        var analytics: [InstrumentAttribute] = []
        switch type {
        case .bond:
            append(&analytics, "ytm",     "Доходность к погашению", e.ytm.map { Fmt.percent($0, digits: 2) })
            append(&analytics, "gspread", "G-spread к КБД",         e.gSpreadBp.map { "\(Fmt.number($0, digits: 0)) б.п." })
            append(&analytics, "nkd",     "НКД",                    e.accrued.map { Fmt.number($0, digits: 2) })
            append(&analytics, "wap",     "Средневзв. цена",        e.wap.map { Fmt.number($0, digits: 2) })
        case .equity:
            append(&analytics, "divy",    "Див. доходность (12м)",  e.divYieldPct.map { Fmt.percent($0, digits: 2) })
        default:
            break
        }

        let keyNames = referenceKeys(type)
        func attr(_ f: MDField) -> InstrumentAttribute {
            InstrumentAttribute(id: f.name, title: f.title ?? f.name, value: f.value ?? "—")
        }
        // Boolean ISS flags decode to "0"/"1" — show them as Нет/Да. Only the
        // folded spec carries flags; the promoted reference keys are never bools.
        func attrBool(_ f: MDField) -> InstrumentAttribute {
            let v = f.value ?? "—"
            let mapped = v == "1" ? "Да" : (v == "0" ? "Нет" : v)
            return InstrumentAttribute(id: f.name, title: f.title ?? f.name, value: mapped)
        }
        let nonEmpty = e.fields.filter { !($0.value ?? "").isEmpty }
        let reference = nonEmpty.filter { keyNames.contains($0.name) }.map(attr)
        let extra     = nonEmpty.filter { !keyNames.contains($0.name) }.map(attrBool)

        return InstrumentDetail(analytics: analytics, reference: reference, extra: extra)
    }

    /// Dated events (coupons / offers / amortizations / maturity / dividends)
    /// to mark on the chart's time axis. Only those inside the loaded window
    /// actually render — snapping is done chart-side.
    static func chartEvents(_ e: MDEntity) -> [ChartEvent] {
        var out: [ChartEvent] = []
        for c in e.schedule?.coupons ?? [] {
            out.append(ChartEvent(id: "c-\(c.couponDate)", date: c.couponDate, type: InstrumentEventType.coupon.rawValue))
        }
        for a in e.schedule?.amortizations ?? [] {
            out.append(ChartEvent(id: "a-\(a.amortDate)", date: a.amortDate, type: InstrumentEventType.amortization.rawValue))
        }
        for o in e.schedule?.offers ?? [] {
            out.append(ChartEvent(id: "o-\(o.offerDate)", date: o.offerDate, type: InstrumentEventType.offer.rawValue))
        }
        for d in e.dividends ?? [] {
            out.append(ChartEvent(id: "d-\(d.registryDate)", date: d.registryDate, type: InstrumentEventType.dividend.rawValue))
        }
        if let mat = e.fields.first(where: { $0.name == "MATDATE" })?.value,
           mat.count >= 10 {
            out.append(ChartEvent(id: "m-\(mat)", date: String(mat.prefix(10)), type: InstrumentEventType.maturity.rawValue))
        }
        return out
    }

    /// The next few dated events (coupon / offer / amortization / maturity /
    /// dividend) after `today`, sorted by date. Surfaced as chips near the
    /// chart since forward-looking coupon schedules can't mark past bars.
    static func upcomingEvents(_ e: MDEntity, today: String, limit: Int = 4) -> [UpcomingEvent] {
        var out: [UpcomingEvent] = []
        for c in e.schedule?.coupons ?? [] where c.couponDate > today {
            out.append(.init(id: "c-\(c.couponDate)", type: .coupon, title: "Купон",
                             date: c.couponDate, detail: c.value.map { Fmt.number($0, digits: 2) } ?? ""))
        }
        for o in e.schedule?.offers ?? [] where o.offerDate > today {
            out.append(.init(id: "o-\(o.offerDate)", type: .offer, title: "Оферта",
                             date: o.offerDate, detail: o.offerType ?? ""))
        }
        for a in e.schedule?.amortizations ?? [] where a.amortDate > today {
            out.append(.init(id: "a-\(a.amortDate)", type: .amortization, title: "Амортизация",
                             date: a.amortDate, detail: a.value.map { Fmt.number($0, digits: 2) } ?? ""))
        }
        if let mat = e.fields.first(where: { $0.name == "MATDATE" })?.value,
           mat.count >= 10, String(mat.prefix(10)) > today {
            out.append(.init(id: "m", type: .maturity, title: "Погашение",
                             date: String(mat.prefix(10)), detail: ""))
        }
        for dv in e.dividends ?? [] where dv.registryDate > today {
            out.append(.init(id: "d-\(dv.registryDate)", type: .dividend, title: "Дивиденд",
                             date: dv.registryDate, detail: dv.value.map { Fmt.number($0, digits: 2) } ?? ""))
        }
        return Array(out.sorted { $0.date < $1.date }.prefix(limit))
    }

    // MARK: helpers

    private static func append(_ list: inout [InstrumentAttribute], _ id: String, _ title: String, _ value: String?) {
        guard let value, !value.isEmpty else { return }
        list.append(InstrumentAttribute(id: id, title: title, value: value, strong: true))
    }

    /// Reference fields promoted above the folded spec, per instrument type.
    private static func referenceKeys(_ type: InstrumentType) -> Set<String> {
        switch type {
        case .bond:
            return ["ISSUENAME", "MATDATE", "COUPONPERCENT", "COUPONVALUE", "COUPONFREQUENCY",
                    "FACEVALUE", "FACEUNIT", "LISTLEVEL", "ISSUESIZE", "BOND_TYPE"]
        case .fx:
            return ["pair", "code", "source"]
        default:
            return ["ISSUENAME", "LATNAME", "ISSUESIZE", "LISTLEVEL", "FACEVALUE", "FACEUNIT", "ISSUEDATE"]
        }
    }
}
