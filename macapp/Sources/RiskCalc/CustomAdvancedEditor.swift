import SwiftUI

// MARK: - Advanced mode (spec §16.1 mode 2, §16.3)
//
// The payout graph is edited as a typed tree over the server allowlist:
// only type-compatible node kinds are offered at each position, so illegal
// graphs are unrepresentable in the UI (typed inputs/outputs by construction);
// the server compiler stays the authority on everything else.

enum ExprType { case number, bool }

struct ExprKindInfo {
    let label: String
    let args: [ExprType]
    let result: ExprType
}

let exprKindOrder: [String] = [
    "const", "param", "state", "perf", "time", "accrual",
    "path_min", "path_max",
    "asset", "worst_of", "best_of", "basket_avg", "nth_worst",
    "worst_path_min",
    "add", "sub", "mul", "div", "neg", "min", "max", "if",
    "ge", "gt", "le", "lt", "and", "or", "not",
]

let exprKinds: [String: ExprKindInfo] = [
    "const":    .init(label: "число", args: [], result: .number),
    "param":    .init(label: "слот", args: [], result: .number),
    "state":    .init(label: "state", args: [], result: .number),
    "perf":     .init(label: "perf S/S₀", args: [], result: .number),
    "time":     .init(label: "t, лет", args: [], result: .number),
    "accrual":  .init(label: "Δt периода", args: [], result: .number),
    "path_min": .init(label: "min по пути", args: [], result: .number),
    "path_max": .init(label: "max по пути", args: [], result: .number),
    "asset":    .init(label: "актив i", args: [], result: .number),
    "worst_of": .init(label: "худший актив", args: [], result: .number),
    "best_of":  .init(label: "лучший актив", args: [], result: .number),
    "basket_avg": .init(label: "среднее корзины", args: [], result: .number),
    "nth_worst": .init(label: "n-й худший", args: [], result: .number),
    "worst_path_min": .init(label: "min худшего по пути", args: [],
                            result: .number),
    "add":      .init(label: "a + b", args: [.number, .number], result: .number),
    "sub":      .init(label: "a − b", args: [.number, .number], result: .number),
    "mul":      .init(label: "a × b", args: [.number, .number], result: .number),
    "div":      .init(label: "a ÷ b", args: [.number, .number], result: .number),
    "neg":      .init(label: "−a", args: [.number], result: .number),
    "min":      .init(label: "min(a,b)", args: [.number, .number], result: .number),
    "max":      .init(label: "max(a,b)", args: [.number, .number], result: .number),
    "ge":       .init(label: "a ≥ b", args: [.number, .number], result: .bool),
    "gt":       .init(label: "a > b", args: [.number, .number], result: .bool),
    "le":       .init(label: "a ≤ b", args: [.number, .number], result: .bool),
    "lt":       .init(label: "a < b", args: [.number, .number], result: .bool),
    "and":      .init(label: "a и b", args: [.bool, .bool], result: .bool),
    "or":       .init(label: "a или b", args: [.bool, .bool], result: .bool),
    "not":      .init(label: "не a", args: [.bool], result: .bool),
    "if":       .init(label: "если(усл; a; b)", args: [.bool, .number, .number],
                      result: .number),
]

// MARK: - Editable AST node

@MainActor
@Observable
final class ENode: Identifiable {
    let id = UUID()
    var kind: String
    var value: Double
    var name: String
    var children: [ENode]

    init(_ kind: String, value: Double = 1.0, name: String = "",
         children: [ENode] = []) {
        self.kind = kind
        self.value = value
        self.name = name
        self.children = children
    }

    static func leaf(_ type: ExprType) -> ENode {
        type == .bool
            ? ENode("ge", children: [ENode("perf"), ENode("const", value: 1.0)])
            : ENode("const", value: 1.0)
    }

    /// Change the node kind preserving type-compatible children.
    func setKind(_ newKind: String) {
        guard let info = exprKinds[newKind] else { return }
        let old = children
        kind = newKind
        if newKind == "asset" { value = 0 }
        if newKind == "nth_worst" { value = 1 }
        children = info.args.enumerated().map { index, type in
            if index < old.count, let oldInfo = exprKinds[old[index].kind],
               oldInfo.result == type {
                return old[index]
            }
            return ENode.leaf(type)
        }
    }

    func toJSON() -> [String: Any] {
        switch kind {
        case "const":
            return ["node": "const", "value": value]
        case "param", "state":
            return ["node": kind, "name": name]
        case "asset":
            return ["node": "asset", "index": Int(value)]
        case "nth_worst":
            return ["node": "nth_worst", "rank": Int(value)]
        default:
            var out: [String: Any] = ["node": kind]
            if !children.isEmpty { out["args"] = children.map { $0.toJSON() } }
            return out
        }
    }

    static func fromJSON(_ dict: [String: Any]) -> ENode {
        let node = ENode(dict["node"] as? String ?? "const")
        node.value = (dict["value"] as? NSNumber)?.doubleValue ?? 1.0
        if let index = dict["index"] as? NSNumber { node.value = index.doubleValue }
        if let rank = dict["rank"] as? NSNumber { node.value = rank.doubleValue }
        node.name = dict["name"] as? String ?? ""
        node.children = (dict["args"] as? [[String: Any]])?.map(fromJSON) ?? []
        return node
    }
}

// MARK: - Editable action / slot / state / definition

@MainActor
@Observable
final class EAction: Identifiable {
    let id = UUID()
    var kind: String              // set | accumulate | pay | terminate
    var stateName: String = ""
    var hasWhen = false
    var when: ENode = ENode.leaf(.bool)
    var body: ENode = ENode.leaf(.number)   // value / amount / payout

    init(kind: String) { self.kind = kind }

    var bodyLabel: String {
        switch kind {
        case "pay": return "сумма"
        case "terminate": return "выплата при погашении"
        default: return "значение"
        }
    }

    func toJSON() -> [String: Any] {
        switch kind {
        case "set", "accumulate":
            return ["action": kind, "name": stateName, "value": body.toJSON()]
        case "terminate":
            return ["action": "terminate", "when": when.toJSON(),
                    "payout": body.toJSON()]
        default:
            var out: [String: Any] = ["action": "pay", "amount": body.toJSON()]
            if hasWhen { out["when"] = when.toJSON() }
            return out
        }
    }

    static func fromJSON(_ dict: [String: Any]) -> EAction {
        let action = EAction(kind: dict["action"] as? String ?? "pay")
        action.stateName = dict["name"] as? String ?? ""
        if let value = dict["value"] as? [String: Any] {
            action.body = ENode.fromJSON(value)
        }
        if let amount = dict["amount"] as? [String: Any] {
            action.body = ENode.fromJSON(amount)
        }
        if let payout = dict["payout"] as? [String: Any] {
            action.body = ENode.fromJSON(payout)
        }
        if let when = dict["when"] as? [String: Any] {
            action.when = ENode.fromJSON(when)
            action.hasWhen = true
        }
        return action
    }
}

@MainActor
@Observable
final class ESlot: Identifiable {
    let id = UUID()
    var name: String
    var label: String
    var def: Double
    var lo: Double
    var hi: Double

    init(name: String, label: String = "", def: Double = 1.0,
         lo: Double = 0.0, hi: Double = 10.0) {
        self.name = name
        self.label = label.isEmpty ? name : label
        self.def = def
        self.lo = lo
        self.hi = hi
    }
}

@MainActor
@Observable
final class EStateVar: Identifiable {
    let id = UUID()
    var name: String
    var initial: Double

    init(name: String, initial: Double = 0.0) {
        self.name = name
        self.initial = initial
    }
}

@MainActor
@Observable
final class EDefinition {
    var name = ""
    var about = ""
    var author = ""
    var assets: [String] = ["S"]
    var slots: [ESlot] = []
    var states: [EStateVar] = []
    var obsSlot = ""              // empty → literal obsCount
    var obsCount: Double = 4
    var matSlot = ""              // empty → literal matValue
    var matValue: Double = 1.0
    var observationProgram: [EAction] = []
    var maturityProgram: [EAction] = []

    var slotNames: [String] { slots.map(\.name) }
    var stateNames: [String] { states.map(\.name) }

    /// Local incremental hints (spec §16.3) — the server compiler remains
    /// authoritative; these just catch the obvious before a round-trip.
    var localHints: [String] {
        var hints: [String] = []
        if !maturityProgram.contains(where: { $0.kind == "pay" && !$0.hasWhen }) {
            hints.append("В программе погашения нет безусловной выплаты — компилятор откажет.")
        }
        var seen = Set<String>()
        for slot in slots where !seen.insert(slot.name).inserted {
            hints.append("Дублируется слот «\(slot.name)».")
        }
        if maturityProgram.contains(where: { $0.kind == "terminate" }) {
            hints.append("terminate в программе погашения не имеет смысла.")
        }
        return hints
    }

    func toJSON() -> [String: Any] {
        var slotsJSON: [String: Any] = [:]
        for slot in slots {
            slotsJSON[slot.name] = ["label": slot.label, "default": slot.def,
                                    "min": slot.lo, "max": slot.hi]
        }
        var stateJSON: [String: Any] = [:]
        for state in states { stateJSON[state.name] = state.initial }
        return [
            "name": name,
            "description": about,
            "author": author,
            "assets": assets.filter { !$0.isEmpty },
            "slots": slotsJSON,
            "state": stateJSON,
            "schedule": [
                "observations": obsSlot.isEmpty ? Int(obsCount) as Any
                                                : ["slot": obsSlot],
                "maturity": matSlot.isEmpty ? matValue as Any
                                            : ["slot": matSlot],
            ],
            "observation_program": observationProgram.map { $0.toJSON() },
            "maturity_program": maturityProgram.map { $0.toJSON() },
        ]
    }

    static func fromJSON(_ dict: [String: Any]) -> EDefinition {
        let defn = EDefinition()
        defn.name = dict["name"] as? String ?? ""
        defn.about = dict["description"] as? String ?? ""
        defn.author = dict["author"] as? String ?? ""
        if let assets = dict["assets"] as? [String], !assets.isEmpty {
            defn.assets = assets
        }
        for (name, raw) in (dict["slots"] as? [String: [String: Any]] ?? [:])
                .sorted(by: { $0.key < $1.key }) {
            defn.slots.append(ESlot(
                name: name,
                label: raw["label"] as? String ?? name,
                def: (raw["default"] as? NSNumber)?.doubleValue ?? 1.0,
                lo: (raw["min"] as? NSNumber)?.doubleValue ?? 0.0,
                hi: (raw["max"] as? NSNumber)?.doubleValue ?? 10.0))
        }
        for (name, raw) in (dict["state"] as? [String: Any] ?? [:])
                .sorted(by: { $0.key < $1.key }) {
            defn.states.append(EStateVar(
                name: name, initial: (raw as? NSNumber)?.doubleValue ?? 0.0))
        }
        let sched = dict["schedule"] as? [String: Any] ?? [:]
        if let slotRef = sched["observations"] as? [String: Any],
           let slot = slotRef["slot"] as? String {
            defn.obsSlot = slot
        } else {
            defn.obsCount = (sched["observations"] as? NSNumber)?.doubleValue ?? 4
        }
        if let slotRef = sched["maturity"] as? [String: Any],
           let slot = slotRef["slot"] as? String {
            defn.matSlot = slot
        } else {
            defn.matValue = (sched["maturity"] as? NSNumber)?.doubleValue ?? 1.0
        }
        defn.observationProgram = (dict["observation_program"] as? [[String: Any]] ?? [])
            .map(EAction.fromJSON)
        defn.maturityProgram = (dict["maturity_program"] as? [[String: Any]] ?? [])
            .map(EAction.fromJSON)
        return defn
    }
}

// MARK: - Expression tree editor

struct ExprTreeEditor: View {
    @Bindable var node: ENode
    let required: ExprType
    let defn: EDefinition
    var depth: Int = 0

    private var compatible: [String] {
        exprKindOrder.filter { exprKinds[$0]?.result == required }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: Theme.s2) {
                if depth > 0 {
                    Image(systemName: "arrow.turn.down.right")
                        .font(.system(size: 8)).foregroundStyle(.quaternary)
                }
                Menu {
                    ForEach(compatible, id: \.self) { kind in
                        Button(exprKinds[kind]!.label) { node.setKind(kind) }
                    }
                } label: {
                    Text(exprKinds[node.kind]?.label ?? node.kind)
                        .font(.system(size: 11, weight: .medium))
                }
                .menuStyle(.borderlessButton)
                .fixedSize()

                inlineEditor

                Text(required == .bool ? "усл." : "число")
                    .font(.system(size: 8))
                    .foregroundStyle(.quaternary)
                Spacer(minLength: 0)
            }
            if !node.children.isEmpty, let info = exprKinds[node.kind] {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(Array(node.children.enumerated()), id: \.element.id) { index, child in
                        ExprTreeEditor(node: child,
                                       required: info.args[index],
                                       defn: defn, depth: depth + 1)
                    }
                }
                .padding(.leading, 18)
            }
        }
    }

    @ViewBuilder
    private var inlineEditor: some View {
        switch node.kind {
        case "const":
            TextField("", value: $node.value, format: .number)
                .textFieldStyle(.roundedBorder).monospacedDigit()
                .frame(width: 76)
        case "param":
            namePicker(options: defn.slotNames, missing: "нет слотов")
        case "state":
            namePicker(options: defn.stateNames, missing: "нет state")
        case "asset":
            Picker("", selection: Binding(
                get: { min(max(Int(node.value), 0), defn.assets.count - 1) },
                set: { node.value = Double($0) }
            )) {
                ForEach(Array(defn.assets.enumerated()), id: \.offset) { index, name in
                    Text(name).tag(index)
                }
            }
            .labelsHidden().pickerStyle(.menu).fixedSize()
        case "nth_worst":
            TextField("", value: Binding(
                get: { Int(node.value) },
                set: { node.value = Double(min(max($0, 1), defn.assets.count)) }
            ), format: .number)
                .textFieldStyle(.roundedBorder).monospacedDigit()
                .frame(width: 44)
        default:
            EmptyView()
        }
    }

    @ViewBuilder
    private func namePicker(options: [String], missing: String) -> some View {
        if options.isEmpty {
            Text(missing).font(.system(size: 10)).foregroundStyle(Theme.negative)
        } else {
            Picker("", selection: Binding(
                get: { options.contains(node.name) ? node.name : options[0] },
                set: { node.name = $0 }
            )) {
                ForEach(options, id: \.self) { Text($0).tag($0) }
            }
            .labelsHidden().pickerStyle(.menu).fixedSize()
            .onAppear { if !options.contains(node.name) { node.name = options[0] } }
        }
    }
}

// MARK: - Action editor

struct ActionEditor: View {
    @Bindable var action: EAction
    let defn: EDefinition
    let allowTerminate: Bool
    let onDelete: () -> Void
    let onMove: (Int) -> Void

    private var kinds: [String] {
        allowTerminate ? ["accumulate", "set", "pay", "terminate"]
                       : ["accumulate", "set", "pay"]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack(spacing: Theme.s2) {
                Menu {
                    ForEach(kinds, id: \.self) { kind in
                        Button(actionTitle(kind)) { action.kind = kind }
                    }
                } label: {
                    Text(actionTitle(action.kind))
                        .font(.system(size: 11, weight: .semibold))
                }
                .menuStyle(.borderlessButton).fixedSize()

                if action.kind == "set" || action.kind == "accumulate" {
                    statePicker
                }
                if action.kind == "pay" {
                    Toggle("условие", isOn: $action.hasWhen)
                        .toggleStyle(.checkbox).font(.system(size: 10))
                }
                Spacer()
                Button { onMove(-1) } label: { Image(systemName: "chevron.up") }
                    .buttonStyle(.plain).foregroundStyle(.tertiary)
                Button { onMove(1) } label: { Image(systemName: "chevron.down") }
                    .buttonStyle(.plain).foregroundStyle(.tertiary)
                Button { onDelete() } label: {
                    Image(systemName: "xmark.circle.fill")
                }
                .buttonStyle(.plain).foregroundStyle(.tertiary)
            }
            if action.kind == "terminate" || (action.kind == "pay" && action.hasWhen) {
                labeled("когда:") {
                    ExprTreeEditor(node: action.when, required: .bool, defn: defn)
                }
            }
            labeled(action.bodyLabel + ":") {
                ExprTreeEditor(node: action.body, required: .number, defn: defn)
            }
        }
        .padding(Theme.s2)
        .background(Color.primary.opacity(0.03),
                    in: RoundedRectangle(cornerRadius: 8))
    }

    private var statePicker: some View {
        Group {
            if defn.stateNames.isEmpty {
                Text("объяви state ниже")
                    .font(.system(size: 10)).foregroundStyle(Theme.negative)
            } else {
                Picker("", selection: Binding(
                    get: { defn.stateNames.contains(action.stateName)
                           ? action.stateName : defn.stateNames[0] },
                    set: { action.stateName = $0 }
                )) {
                    ForEach(defn.stateNames, id: \.self) { Text($0).tag($0) }
                }
                .labelsHidden().pickerStyle(.menu).fixedSize()
            }
        }
    }

    private func labeled(_ title: String,
                         @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.system(size: 9)).foregroundStyle(.tertiary)
            content()
        }
        .padding(.leading, 14)
    }
}

func actionTitle(_ kind: String) -> String {
    switch kind {
    case "accumulate": return "Накопить в state"
    case "set": return "Записать в state"
    case "pay": return "Выплатить"
    case "terminate": return "Досрочно погасить"
    default: return kind
    }
}
