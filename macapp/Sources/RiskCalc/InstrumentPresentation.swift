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

/// Chart event kinds (marked on the price axis — wired in the chart phase).
enum InstrumentEventType: String {
    case coupon, offer, call, put, amortization, maturity   // bonds
    case dividend, earnings, split, buyback                 // equities
}

// MARK: - Composition

enum InstrumentPresentation {

    /// "Торги за день" figures for the instrument's type.
    static func dayMetrics(_ e: MDEntity, category: String) -> [MetricItem] {
        guard let d = e.day else { return [] }
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
            items.append(MetricItem(id: "chg", title: "Δ%",
                                    value: e.changePct.map { Fmt.signedPercent($0, digits: 2) } ?? "—",
                                    color: e.changePct.map { Theme.changeColor($0) } ?? .primary))
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
        let nonEmpty = e.fields.filter { !($0.value ?? "").isEmpty }
        let reference = nonEmpty.filter { keyNames.contains($0.name) }.map(attr)
        let extra     = nonEmpty.filter { !keyNames.contains($0.name) }.map(attr)

        return InstrumentDetail(analytics: analytics, reference: reference, extra: extra)
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
