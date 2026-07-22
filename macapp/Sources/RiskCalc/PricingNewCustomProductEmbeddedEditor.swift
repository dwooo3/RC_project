import SwiftUI

/// Dense, single-surface Custom Product Engine editor intended for direct
/// placement inside Pricing_new.  It does not replace or mutate the existing
/// full-screen CustomProductsView.
struct PricingNewCustomProductEmbeddedEditor: View {
    let environmentID: String
    let onAttach: (PricingNewCustomProductAttachment) -> Void

    @State private var vm = PricingNewCustomProductIntegrationViewModel()

    init(environmentID: String = "FO",
         onAttach: @escaping (PricingNewCustomProductAttachment) -> Void) {
        self.environmentID = environmentID
        self.onAttach = onAttach
    }

    var body: some View {
        @Bindable var vm = vm
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                toolbar
                if let message = vm.core.message {
                    Label(message, systemImage: "exclamationmark.triangle.fill")
                        .font(Typography.caption)
                        .foregroundStyle(Theme.negative)
                        .textSelection(.enabled)
                }
                if vm.isLoading && vm.core.detail == nil {
                    ProgressView("Загрузка Custom Product Engine…")
                        .controlSize(.small)
                } else if let detail = vm.core.detail {
                    provenance(detail)
                    HStack(alignment: .top, spacing: Theme.s3) {
                        contractPane(detail)
                            .frame(minWidth: 310, maxWidth: .infinity,
                                   alignment: .topLeading)
                        Divider()
                        marketPane
                            .frame(minWidth: 470, maxWidth: .infinity,
                                   alignment: .topLeading)
                    }
                    contractSchedulePane(detail)
                    valuationStatePane(detail)
                    compileAndResultPane(detail)
                    if let editor = vm.core.editor {
                        PricingNewCustomASTInlineEditor(
                            vm: vm, detail: detail, editor: editor)
                    }
                } else {
                    ContentUnavailableView(
                        "Нет custom product",
                        systemImage: "point.3.connected.trianglepath.dotted",
                        description: Text("Создай продукт из шаблона или с нуля."))
                }
            }
        }
        .task {
            vm.setEnvironment(environmentID)
            await vm.load()
        }
        .onChange(of: environmentID) { _, next in
            vm.setEnvironment(next)
            Task { await vm.refreshValuationContext() }
        }
        .onChange(of: vm.core.editor?.assets ?? []) { _, _ in
            vm.synchronizeAssetDrafts(reset: false)
        }
    }

    // MARK: Toolbar and lifecycle

    private var toolbar: some View {
        HStack(spacing: Theme.s3) {
            BlockTitle("Custom product · payout engine",
                       icon: "point.3.connected.trianglepath.dotted")
            Pill(text: environmentID.uppercased(), color: Theme.accent)
            Picker("Definition", selection: Binding(
                get: { vm.core.selectedID ?? "" },
                set: { id in Task { await vm.select(id) } }
            )) {
                ForEach(vm.core.products) { product in
                    Text("\(product.name) · v\(product.version) · \(product.state)")
                        .tag(product.id)
                }
            }
            .labelsHidden().pickerStyle(.menu).neutralControlTint()
            .frame(minWidth: 210, maxWidth: 330)
            Menu {
                ForEach(vm.core.templates) { template in
                    Button(template.name) { Task { await vm.create(from: template) } }
                }
                Divider()
                Button("Advanced · с нуля") {
                    Task { await vm.createAdvanced() }
                }
            } label: {
                Label("Создать", systemImage: "plus")
            }
            .menuStyle(.borderlessButton).fixedSize()
            .disabled(vm.core.isBusy)
            lifecycleControl
            Spacer(minLength: Theme.s2)
            if let first = vm.contractIssues.first {
                Image(systemName: "exclamationmark.shield.fill")
                    .foregroundStyle(Theme.warning)
                    .help(first.message)
            } else {
                Pill(text: "ready to attach", color: Theme.positive)
            }
            Button {
                do { onAttach(try vm.makeAttachment()) }
                catch { vm.core.message = error.localizedDescription }
            } label: {
                Label("Добавить в расчёт", systemImage: "plus.rectangle.on.rectangle")
            }
            .buttonStyle(.borderedProminent).tint(Theme.accent)
            .controlSize(.small)
            .disabled(!vm.canAttach || vm.core.isBusy)
        }
    }

    @ViewBuilder
    private var lifecycleControl: some View {
        if let detail = vm.core.detail {
            switch detail.state {
            case "draft":
                Button(vm.core.isEditorDirty ? "Save + compile" : "Compile") {
                    Task {
                        if vm.core.isEditorDirty { await vm.saveAndCompile() }
                        else { await vm.compile() }
                    }
                }
                .controlSize(.small).disabled(vm.core.isBusy)
            case "tested":
                Button("Submit") { Task { await vm.submit() } }
                    .controlSize(.small).disabled(vm.core.isBusy)
            case "submitted":
                HStack(spacing: 4) {
                    TextField("checker", text: Bindable(vm.core).approver)
                        .textFieldStyle(.roundedBorder).frame(width: 92)
                    Button("Approve") { Task { await vm.approve() } }
                        .controlSize(.small).disabled(vm.core.isBusy)
                }
            case "approved":
                Button("Publish") { Task { await vm.publish() } }
                    .controlSize(.small).disabled(vm.core.isBusy)
            case "published", "deprecated":
                Button("Новая версия") { Task { await vm.newVersion() } }
                    .controlSize(.small).disabled(vm.core.isBusy)
            default:
                EmptyView()
            }
        }
    }

    private func provenance(_ detail: CustomProductDetail) -> some View {
        HStack(spacing: Theme.s3) {
            Pill(text: detail.state,
                 color: pricingNewCustomStateColor(detail.state))
            Text("v\(detail.version)").monospacedDigit()
            Text("definition \(detail.definitionHash.prefix(12))")
                .font(.system(size: 9, design: .monospaced))
            Text(vm.core.engineLabel)
                .font(.system(size: 9, design: .monospaced))
            Text("\(vm.core.assetNames.count) underlying(s)")
            if vm.core.isEditorDirty {
                Pill(text: "unsaved AST", color: Theme.warning)
            }
            Spacer()
            Text("Definition lifecycle ≠ model production eligibility")
                .foregroundStyle(.tertiary)
        }
        .font(Typography.micro).foregroundStyle(.secondary)
    }

    // MARK: Contract / payoff parameters

    private func contractPane(_ detail: CustomProductDetail) -> some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            Text("CONTRACT SLOTS")
                .font(Typography.label).foregroundStyle(Theme.accent)
            if detail.definition.slots.isEmpty {
                Text("Нет параметризованных слотов")
                    .font(Typography.caption).foregroundStyle(.tertiary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: Theme.s2,
                     verticalSpacing: 5) {
                    ForEach(detail.definition.slots.keys.sorted(), id: \.self) { key in
                        let spec = detail.definition.slots[key]!
                        GridRow {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(spec.label ?? key).font(Typography.caption)
                                Text(key).font(.system(size: 8, design: .monospaced))
                                    .foregroundStyle(.tertiary)
                            }
                            TextField("", value: slotBinding(key, spec: spec),
                                      format: .number)
                                .textFieldStyle(.roundedBorder).monospacedDigit()
                                .frame(width: 105)
                            Text(slotRange(spec))
                                .font(Typography.micro).foregroundStyle(.tertiary)
                        }
                    }
                }
            }
            if let description = detail.definition.description,
               !description.isEmpty {
                Text(description).font(Typography.micro)
                    .foregroundStyle(.secondary).fixedSize(horizontal: false,
                                                            vertical: true)
            }
            if !vm.contractIssues.isEmpty {
                Divider()
                ForEach(vm.contractIssues.prefix(4)) { issue in
                    Label(issue.message, systemImage: "exclamationmark.triangle.fill")
                        .font(Typography.micro)
                        .foregroundStyle(issue.code.contains("OVERRIDE")
                                         ? Theme.warning : Theme.negative)
                        .help("\(issue.code) · \(issue.path)")
                }
                if vm.contractIssues.count > 4 {
                    Text("Ещё \(vm.contractIssues.count - 4) issue(s)")
                        .font(Typography.micro).foregroundStyle(.tertiary)
                }
            }
        }
    }

    private func slotBinding(_ key: String, spec: CustomSlotSpec) -> Binding<Double> {
        Binding(
            get: { vm.core.slotValues[key] ?? spec.defaultValue },
            set: {
                vm.core.slotValues[key] = $0
                if vm.stateMode == .seasoned {
                    vm.seasonedState.stateSourceHash = ""
                }
            })
    }

    private func slotRange(_ spec: CustomSlotSpec) -> String {
        switch (spec.min, spec.max) {
        case let (lo?, hi?): return "\(Fmt.number(lo, digits: 3)) … \(Fmt.number(hi, digits: 3))"
        case let (lo?, nil): return "≥ \(Fmt.number(lo, digits: 3))"
        case let (nil, hi?): return "≤ \(Fmt.number(hi, digits: 3))"
        default: return ""
        }
    }

    // MARK: Trade lifecycle / seasoned state

    private func contractSchedulePane(_ detail: CustomProductDetail) -> some View {
        let scheduleIssues = vm.contractIssues.filter {
            $0.path.hasPrefix("contract_schedule")
                || $0.code.contains("CONTRACT_SCHEDULE")
        }
        return VStack(alignment: .leading, spacing: Theme.s2) {
            Divider()
            HStack(spacing: Theme.s2) {
                Text("CONTRACTUAL SCHEDULE · MOEX")
                    .font(Typography.label).foregroundStyle(Theme.accent)
                if vm.requiresExplicitContractSchedule {
                    Pill(text: "required", color: Theme.warning)
                }
                Text("explicit dates only · definition \(detail.definitionHash.prefix(10))")
                    .font(.system(size: 8, design: .monospaced))
                    .foregroundStyle(.tertiary)
                Spacer()
                Button("Очистить") { vm.resetContractSchedule() }
                    .controlSize(.mini)
            }

            HStack(alignment: .bottom, spacing: Theme.s2) {
                PricingNewCustomLabeledField(label: "Effective date") {
                    scheduleDateField(
                        vm.contractSchedule.effectiveDate,
                        placeholder: "YYYY-MM-DD") { value in
                            vm.contractSchedule.effectiveDate = value
                            vm.invalidateContractScheduleEvidence()
                        }
                }
                PricingNewCustomLabeledField(label: "Contractual maturity") {
                    scheduleDateField(
                        vm.contractSchedule.contractualMaturityDate,
                        placeholder: "YYYY-MM-DD") { value in
                            vm.contractSchedule.contractualMaturityDate = value
                            vm.invalidateContractScheduleEvidence()
                        }
                }
                PricingNewCustomLabeledField(label: "BDC") {
                    Picker("", selection: Binding(
                        get: { vm.contractSchedule.businessDayConvention },
                        set: {
                            vm.contractSchedule.businessDayConvention = $0
                            vm.invalidateContractScheduleEvidence()
                        })) {
                        ForEach(PricingNewCustomBusinessDayConvention.allCases,
                                id: \.self) { convention in
                            Text(convention.rawValue).tag(convention)
                        }
                    }
                    .labelsHidden().pickerStyle(.menu).frame(width: 185)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text("CALENDAR")
                        .font(Typography.label).foregroundStyle(.secondary)
                    HStack(spacing: 5) {
                        Text("MOEX_STOCK")
                            .font(.system(size: 9, design: .monospaced))
                        Toggle("server latest", isOn: Binding(
                            get: { vm.contractSchedule.useLatestCalendarVersion },
                            set: {
                                vm.contractSchedule.useLatestCalendarVersion = $0
                                vm.invalidateContractScheduleEvidence()
                            }))
                            .toggleStyle(.checkbox).font(Typography.micro)
                        if !vm.contractSchedule.useLatestCalendarVersion {
                            TextField("v", value: Binding(
                                get: { vm.contractSchedule.calendarVersion },
                                set: {
                                    vm.contractSchedule.calendarVersion = $0
                                    vm.invalidateContractScheduleEvidence()
                                }), format: .number)
                                .textFieldStyle(.roundedBorder).monospacedDigit()
                                .frame(width: 54)
                        }
                    }
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text("FIXED CONVENTIONS")
                        .font(Typography.label).foregroundStyle(.secondary)
                    Text("ACT/365F · POST_CLOSE_POST_EVENTS")
                        .font(.system(size: 9, design: .monospaced))
                }
                Spacer(minLength: 0)
            }

            HStack(alignment: .top, spacing: Theme.s2) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 5) {
                        Text("CONTRACTUAL OBSERVATION DATES")
                            .font(Typography.label).foregroundStyle(.secondary)
                        Text("\(vm.contractSchedule.contractualObservationDates.count) / "
                             + "\(vm.resolvedObservationCount.map(String.init) ?? "—")")
                            .font(Typography.micro).monospacedDigit()
                        Button {
                            vm.addContractualObservationDate()
                        } label: {
                            Label("blank date", systemImage: "plus")
                        }
                        .controlSize(.mini)
                    }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 5) {
                            ForEach(vm.contractSchedule.contractualObservationDates.indices,
                                    id: \.self) { index in
                                HStack(spacing: 2) {
                                    Text("\(index + 1)")
                                        .font(Typography.micro).monospacedDigit()
                                        .foregroundStyle(.tertiary)
                                    scheduleDateField(
                                        vm.contractSchedule
                                            .contractualObservationDates[index],
                                        placeholder: "YYYY-MM-DD") { value in
                                            vm.setContractualObservationDate(
                                                value, at: index)
                                        }
                                    Button {
                                        vm.removeContractualObservationDate(at: index)
                                    } label: {
                                        Image(systemName: "xmark")
                                    }
                                    .buttonStyle(.plain).foregroundStyle(.tertiary)
                                }
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            Grid(alignment: .leading, horizontalSpacing: Theme.s2,
                 verticalSpacing: 4) {
                GridRow {
                    Text("ASSET")
                    Text("SECID")
                    Text("PRICE BASIS")
                    Text("BOARD")
                    Text("SESSION")
                    Text("SOURCE / MISSING")
                }
                .font(Typography.label).foregroundStyle(.secondary)
                ForEach(vm.assetDrafts) { asset in
                    PricingNewCustomFixingBindingRow(vm: vm, asset: asset)
                }
            }

            Text(vm.contractSchedule.businessDayConvention == .unadjusted
                 ? "UNADJUSTED: UI проверяет processed observations и ACT/365F elapsed по explicit dates."
                 : "Holiday adjustment выполняет backend по versioned MOEX calendar; UI не создаёт локальные resolved dates.")
                .font(Typography.micro)
                .foregroundStyle(vm.contractSchedule.businessDayConvention == .unadjusted
                                 ? Color.secondary.opacity(0.65) : Theme.warning)
            if !scheduleIssues.isEmpty {
                PricingNewFlowLayout(spacing: 5) {
                    ForEach(scheduleIssues.prefix(6)) { issue in
                        Label(issue.message,
                              systemImage: "exclamationmark.triangle.fill")
                            .font(Typography.micro).foregroundStyle(Theme.negative)
                            .help("\(issue.code) · \(issue.path)")
                    }
                }
            }
        }
    }

    private func scheduleDateField(
        _ value: String,
        placeholder: String,
        onChange: @escaping (String) -> Void
    ) -> some View {
        TextField(placeholder, text: Binding(
            get: { value },
            set: { onChange($0.trimmingCharacters(in: .whitespacesAndNewlines)) }))
            .textFieldStyle(.roundedBorder)
            .font(.system(size: 10, design: .monospaced))
            .frame(width: 112)
    }

    private func valuationStatePane(_ detail: CustomProductDetail) -> some View {
        let stateIssues = vm.contractIssues.filter {
            $0.path.hasPrefix("valuation_state")
                || $0.code.contains("_STATE_")
        }
        return VStack(alignment: .leading, spacing: Theme.s2) {
            Divider()
            HStack(spacing: Theme.s3) {
                Text("VALUATION STATE")
                    .font(Typography.label).foregroundStyle(Theme.accent)
                Picker("Lifecycle state", selection: Binding(
                    get: { vm.stateMode },
                    set: { vm.selectStateMode($0) }
                )) {
                    Text("Inception").tag(PricingNewCustomValuationMode.inception)
                    Text("Seasoned / live trade")
                        .tag(PricingNewCustomValuationMode.seasoned)
                }
                .labelsHidden().pickerStyle(.segmented).frame(width: 260)
                if vm.stateMode == .seasoned {
                    Pill(text: "explicit path state", color: Theme.warning)
                    Text("definition \(detail.definitionHash.prefix(10))")
                        .font(.system(size: 8, design: .monospaced))
                        .foregroundStyle(.tertiary)
                } else {
                    Text("current spots become contractual reference spots")
                        .font(Typography.micro).foregroundStyle(.tertiary)
                }
                Spacer(minLength: 0)
            }

            if vm.stateMode == .seasoned {
                seasonedControls
                seasonedAssetGrid
                seasonedVariables
                if !stateIssues.isEmpty {
                    PricingNewFlowLayout(spacing: 5) {
                        ForEach(stateIssues.prefix(6)) { issue in
                            Label(issue.message,
                                  systemImage: "exclamationmark.triangle.fill")
                                .font(Typography.micro)
                                .foregroundStyle(Theme.negative)
                                .help("\(issue.code) · \(issue.path)")
                        }
                    }
                }
            }
        }
    }

    private var seasonedControls: some View {
        HStack(alignment: .bottom, spacing: Theme.s2) {
            PricingNewCustomLabeledField(label: "Processed obs") {
                TextField("", value: Binding(
                    get: { vm.seasonedState.observationIndex },
                    set: {
                        vm.seasonedState.observationIndex = $0
                        vm.seasonedState.stateSourceHash = ""
                    }), format: .number)
                    .textFieldStyle(.roundedBorder).monospacedDigit()
                    .frame(width: 72)
                    .disabled(vm.contractSchedule.businessDayConvention
                              == .unadjusted)
            }
            PricingNewCustomLabeledField(label: "Elapsed, y") {
                TextField("", value: Binding(
                    get: { vm.seasonedState.elapsedTime },
                    set: {
                        vm.seasonedState.elapsedTime = $0
                        vm.seasonedState.stateSourceHash = ""
                    }), format: .number)
                    .textFieldStyle(.roundedBorder).monospacedDigit()
                    .frame(width: 82)
                    .disabled(vm.contractSchedule.businessDayConvention
                              == .unadjusted)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text("CONTRACT SCHEDULE")
                    .font(Typography.label).foregroundStyle(.secondary)
                Text("\(vm.contractSchedule.contractualObservationDates.count) obs · "
                     + (vm.contractSchedule.contractualMaturityDate.isEmpty
                        ? "maturity —"
                        : vm.contractSchedule.contractualMaturityDate))
                    .font(Typography.caption).monospacedDigit()
            }
            Toggle("Alive", isOn: Binding(
                get: { vm.seasonedState.alive },
                set: {
                    vm.seasonedState.alive = $0
                    vm.seasonedState.stateSourceHash = ""
                }))
                .toggleStyle(.checkbox).font(Typography.caption)
            VStack(alignment: .leading, spacing: 2) {
                Text("SNAPSHOT AS-OF")
                    .font(Typography.label).foregroundStyle(.secondary)
                HStack(spacing: 4) {
                    Text(vm.seasonedState.stateAsOf.isEmpty
                         ? "unresolved" : vm.seasonedState.stateAsOf)
                        .font(Typography.caption).monospacedDigit()
                        .foregroundStyle(vm.seasonedState.stateAsOf.isEmpty
                                         ? Theme.negative : .primary)
                    if let snapshot = vm.stateSnapshotID {
                        Text(snapshot).font(.system(size: 8, design: .monospaced))
                            .foregroundStyle(.tertiary).lineLimit(1)
                    }
                }
            }
            PricingNewCustomLabeledField(label: "State source SHA-256") {
                TextField("64 hex · source fixing/state record", text: Binding(
                    get: { vm.seasonedState.stateSourceHash },
                    set: {
                        vm.seasonedState.stateSourceHash = $0
                            .trimmingCharacters(in: .whitespacesAndNewlines)
                            .lowercased()
                    }))
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 9, design: .monospaced))
                    .frame(minWidth: 250)
            }
            Button("Сбросить state") { vm.resetSeasonedState() }
                .controlSize(.mini)
        }
    }

    private var seasonedAssetGrid: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            Grid(alignment: .leading, horizontalSpacing: Theme.s2,
                 verticalSpacing: 4) {
                GridRow {
                    Text("ASSET")
                    Text("CURRENT")
                    Text("REFERENCE")
                    Text("PERF")
                    Text("RUN MIN")
                    Text("RUN MAX")
                }
                .font(Typography.label).foregroundStyle(.secondary)
                ForEach(vm.core.assetNames, id: \.self) { name in
                    GridRow {
                        Text(name).font(Typography.captionStrong).frame(width: 100,
                                                                       alignment: .leading)
                        Text(vm.currentSpot(for: name).map {
                            Fmt.number($0, digits: 6)
                        } ?? "—")
                            .font(Typography.caption).monospacedDigit()
                            .frame(width: 92, alignment: .trailing)
                        stateField(referenceBinding(name), width: 92)
                        Text(vm.currentPerformance(for: name).map {
                            Fmt.number($0, digits: 6)
                        } ?? "—")
                            .font(Typography.caption).monospacedDigit()
                            .frame(width: 82, alignment: .trailing)
                        stateField(runningMinBinding(name), width: 82)
                        stateField(runningMaxBinding(name), width: 82)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var seasonedVariables: some View {
        if let defaults = vm.definitionStateDefaults, !defaults.isEmpty {
            HStack(spacing: Theme.s2) {
                Text("STATE VARIABLES")
                    .font(Typography.label).foregroundStyle(.secondary)
                ForEach(defaults.keys.sorted(), id: \.self) { name in
                    HStack(spacing: 4) {
                        Text(name).font(.system(size: 9, design: .monospaced))
                        stateField(stateValueBinding(name), width: 82)
                    }
                }
                Spacer(minLength: 0)
            }
        } else if vm.definitionStateDefaults == nil {
            Label("State schema недоступна — attachment заблокирован",
                  systemImage: "exclamationmark.triangle.fill")
                .font(Typography.micro).foregroundStyle(Theme.negative)
        } else {
            Text("Definition не содержит mutable state variables")
                .font(Typography.micro).foregroundStyle(.tertiary)
        }
    }

    private func referenceBinding(_ name: String) -> Binding<Double> {
        stateDictionaryBinding(\.referenceSpots, name: name,
                               fallback: vm.currentSpot(for: name) ?? 0)
    }

    private func runningMinBinding(_ name: String) -> Binding<Double> {
        stateDictionaryBinding(\.runningMin, name: name, fallback: 1)
    }

    private func runningMaxBinding(_ name: String) -> Binding<Double> {
        stateDictionaryBinding(\.runningMax, name: name, fallback: 1)
    }

    private func stateValueBinding(_ name: String) -> Binding<Double> {
        stateDictionaryBinding(\.stateValues, name: name,
                               fallback: vm.definitionStateDefaults?[name] ?? 0)
    }

    private func stateDictionaryBinding(
        _ keyPath: ReferenceWritableKeyPath<PricingNewCustomSeasonedStateDraft,
                                             [String: Double]>,
        name: String,
        fallback: Double
    ) -> Binding<Double> {
        Binding(
            get: { vm.seasonedState[keyPath: keyPath][name] ?? fallback },
            set: { value in
                vm.seasonedState[keyPath: keyPath][name] = value
                vm.seasonedState.stateSourceHash = ""
            })
    }

    private func stateField(_ value: Binding<Double>, width: CGFloat)
        -> some View {
        TextField("", value: value, format: .number)
            .textFieldStyle(.roundedBorder).monospacedDigit().frame(width: width)
    }

    // MARK: Market and numerical inputs

    private var marketPane: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack {
                Text("RESOLVED MARKET INPUTS")
                    .font(Typography.label).foregroundStyle(Theme.positive)
                Spacer()
                Text("real snapshot or documented override")
                    .font(Typography.micro).foregroundStyle(.tertiary)
            }
            ForEach(vm.assetDrafts) { asset in
                PricingNewCustomAssetRow(vm: vm, asset: asset)
            }
            rateAndNumericalRow
            if vm.assetDrafts.count > 1 { correlationGrid }
        }
    }

    private var rateAndNumericalRow: some View {
        HStack(alignment: .top, spacing: Theme.s2) {
            PricingNewCustomLabeledField(label: "Risk-free r") {
                TextField("", value: Bindable(vm.core).marketR, format: .number)
                    .textFieldStyle(.roundedBorder).monospacedDigit()
                    .frame(width: 82)
            }
            PricingNewCustomLabeledField(label: "MC paths") {
                TextField("", value: Bindable(vm.core).nSims,
                          format: .number.precision(.fractionLength(0)))
                    .textFieldStyle(.roundedBorder).monospacedDigit()
                    .frame(width: 92)
            }
            PricingNewCustomLabeledField(label: "Steps") {
                TextField("", value: Bindable(vm.core).mcSteps,
                          format: .number.precision(.fractionLength(0)))
                    .textFieldStyle(.roundedBorder).monospacedDigit()
                    .frame(width: 72)
            }
            PricingNewCustomLabeledField(label: "Seed") {
                TextField("", value: Bindable(vm.core).seed,
                          format: .number.precision(.fractionLength(0)))
                    .textFieldStyle(.roundedBorder).monospacedDigit()
                    .frame(width: 72)
            }
            if vm.rateSource == .marketSnapshot {
                VStack(alignment: .leading, spacing: 2) {
                    Text("RATE EVIDENCE").font(Typography.label)
                        .foregroundStyle(.secondary)
                    Text(vm.rateSnapshotID ?? "—")
                        .font(.system(size: 9, design: .monospaced))
                    if vm.rateOverridden {
                        TextField("Причина override ставки",
                                  text: Bindable(vm).rateOverrideReason)
                            .textFieldStyle(.roundedBorder).frame(width: 180)
                    }
                }
            } else {
                PricingNewCustomLabeledField(label: "Rate override reason") {
                    TextField("обязательная причина",
                              text: Bindable(vm).rateOverrideReason)
                        .textFieldStyle(.roundedBorder).frame(width: 180)
                }
            }
            Spacer(minLength: 0)
        }
    }

    private var correlationGrid: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(vm.effectiveCorrelationMode == "historical"
                     ? "CORRELATION PRIOR · historical calibration"
                     : "CORRELATION · manual upper triangle")
                    .font(Typography.label).foregroundStyle(.secondary)
                Spacer()
                TextField("default ρ", value: Bindable(vm.core).marketRho,
                          format: .number)
                    .textFieldStyle(.roundedBorder).frame(width: 80)
                Button("Заполнить ρ") { vm.core.applyEquicorrelation() }
                    .controlSize(.mini)
            }
            HStack(spacing: Theme.s2) {
                PricingNewCustomLabeledField(label: "Mode") {
                    Picker("", selection: Bindable(vm).correlationMode) {
                        Text("Auto").tag("auto")
                        Text("Historical").tag("historical")
                        Text("Manual").tag("manual")
                    }
                    .labelsHidden().pickerStyle(.menu).frame(width: 105)
                }
                PricingNewCustomLabeledField(label: "Method") {
                    Picker("", selection: Bindable(vm).correlationMethod) {
                        Text("EWMA").tag("ewma")
                        Text("Pearson").tag("pearson")
                    }
                    .labelsHidden().pickerStyle(.menu).frame(width: 100)
                    .disabled(vm.effectiveCorrelationMode == "manual")
                }
                PricingNewCustomLabeledField(label: "Lookback") {
                    TextField("", value: Bindable(vm).correlationLookback,
                              format: .number)
                        .textFieldStyle(.roundedBorder).monospacedDigit()
                        .frame(width: 70)
                        .disabled(vm.effectiveCorrelationMode == "manual")
                }
                PricingNewCustomLabeledField(label: "Min samples") {
                    TextField("", value: Bindable(vm).correlationMinSamples,
                              format: .number)
                        .textFieldStyle(.roundedBorder).monospacedDigit()
                        .frame(width: 70)
                        .disabled(vm.effectiveCorrelationMode == "manual")
                }
                if vm.correlationMethod == "ewma" {
                    PricingNewCustomLabeledField(label: "Decay") {
                        TextField("", value: Bindable(vm).correlationDecay,
                                  format: .number)
                            .textFieldStyle(.roundedBorder).monospacedDigit()
                            .frame(width: 65)
                            .disabled(vm.effectiveCorrelationMode == "manual")
                    }
                }
                PricingNewCustomLabeledField(label: "On gaps") {
                    Picker("", selection: Bindable(vm).correlationFallbackPolicy) {
                        Text("Use prior").tag("prior")
                        Text("Fail closed").tag("error")
                    }
                    .labelsHidden().pickerStyle(.menu).frame(width: 105)
                    .disabled(vm.effectiveCorrelationMode == "manual")
                }
                Spacer(minLength: 0)
            }
            Text(vm.effectiveCorrelationMode == "historical"
                 ? "Фактическая матрица будет оценена по истории SECID as-of snapshot; сетка ниже — prior при fallback."
                 : "Сетка ниже — фактическая static correlation matrix для прайсинга.")
                .font(Typography.micro).foregroundStyle(.tertiary)
            ScrollView(.horizontal, showsIndicators: false) {
                Grid(horizontalSpacing: 4, verticalSpacing: 4) {
                    GridRow {
                        Text("").frame(width: 70)
                        ForEach(vm.assetDrafts) { asset in
                            Text(asset.assetName).lineLimit(1)
                                .font(Typography.micro).frame(width: 60)
                        }
                    }
                    ForEach(vm.assetDrafts) { row in
                        GridRow {
                            Text(row.assetName).lineLimit(1)
                                .font(Typography.micro).frame(width: 70,
                                                             alignment: .leading)
                            ForEach(vm.assetDrafts) { column in
                                correlationCell(row.index, column.index)
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func correlationCell(_ row: Int, _ column: Int) -> some View {
        if row == column {
            Text("1.000").font(Typography.micro).monospacedDigit()
                .frame(width: 60, height: 22)
                .background(Color.secondary.opacity(0.08),
                            in: RoundedRectangle(cornerRadius: 5))
        } else if column > row {
            TextField("", value: vm.core.correlationBinding(
                row: row, column: column), format: .number)
                .textFieldStyle(.roundedBorder).monospacedDigit().frame(width: 60)
        } else {
            let value = vm.core.marketCorrelation.indices.contains(row)
                && vm.core.marketCorrelation[row].indices.contains(column)
                ? vm.core.marketCorrelation[row][column] : 0
            Text(Fmt.number(value, digits: 3))
                .font(Typography.micro).monospacedDigit()
                .foregroundStyle(.secondary).frame(width: 60, height: 22)
        }
    }

    // MARK: Compile and verification result

    private func compileAndResultPane(_ detail: CustomProductDetail) -> some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            Divider()
            HStack(alignment: .top, spacing: Theme.s4) {
                if let report = detail.compileReport {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 5) {
                            Image(systemName: report.ok ? "checkmark.seal.fill"
                                                       : "xmark.seal.fill")
                            Text(report.ok ? "COMPILED · VALIDATED"
                                           : "COMPILE FAILED")
                            if let cls = report.classification {
                                Pill(text: cls.dynamics, color: Theme.accent)
                                if cls.pathDependent {
                                    Pill(text: "path-dependent", color: .secondary)
                                }
                                if cls.earlyRedemption {
                                    Pill(text: "early redemption", color: .secondary)
                                }
                            }
                        }
                        .font(Typography.label)
                        .foregroundStyle(report.ok ? Theme.positive : Theme.negative)
                        if let summary = report.summary {
                            Text(summary).font(Typography.micro)
                                .foregroundStyle(.secondary).lineLimit(3)
                        }
                        ForEach(report.issues.prefix(3)) { issue in
                            Text("\(issue.code) · \(issue.message)")
                                .font(Typography.micro).foregroundStyle(Theme.negative)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text("GENERIC ENGINE CHECK")
                            .font(Typography.label).foregroundStyle(.secondary)
                        Button {
                            Task { await vm.verifyPrice() }
                        } label: {
                            if vm.core.isPricing { ProgressView().controlSize(.mini) }
                            else { Label("Проверочный PV", systemImage: "function") }
                        }
                        .controlSize(.mini)
                        .disabled(vm.core.isPricing || vm.core.isEditorDirty
                                  || !vm.core.valuationIssues.isEmpty
                                  || vm.stateMode == .seasoned)
                    }
                    if vm.stateMode == .seasoned {
                        Text("Legacy preview не принимает valuation_state; authoritative seasoned PV рассчитывается после добавления в Pricing_new.")
                            .font(Typography.micro).foregroundStyle(Theme.warning)
                    } else if let price = vm.core.priceResult {
                        HStack(spacing: Theme.s3) {
                            Text("PV \(Fmt.number(price.value, digits: 6))")
                                .font(Typography.bodyMedium).monospacedDigit()
                            Text("± \(Fmt.number(2 * price.stderr, digits: 6))")
                                .font(Typography.micro).foregroundStyle(.secondary)
                            Text("P(early) \(Fmt.signedPercent(price.earlyRedemptionProb * 100))")
                                .font(Typography.micro)
                            Text("seed \(price.seed)").font(Typography.micro)
                        }
                    } else {
                        Text("Проверка использует тот же version/hash и MC controls; attach не зависит от preview result.")
                            .font(Typography.micro).foregroundStyle(.tertiary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

// MARK: - Resolved underlying row

private struct PricingNewCustomAssetRow: View {
    @Bindable var vm: PricingNewCustomProductIntegrationViewModel
    @Bindable var asset: PricingNewCustomAssetDraft

    private var index: Int { asset.index }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 5) {
                Text("\(index + 1). \(asset.assetName)")
                    .font(Typography.captionStrong)
                if let secid = asset.secid {
                    Pill(text: secid, color: Theme.positive)
                    Text(asset.category ?? "")
                        .font(Typography.micro).foregroundStyle(.tertiary)
                    if let board = asset.board {
                        Text(board).font(.system(size: 8, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                    Text(asset.snapshotID ?? "snapshot missing")
                        .font(.system(size: 8, design: .monospaced))
                        .foregroundStyle(asset.snapshotID == nil
                                         ? Theme.negative
                                         : Color.secondary.opacity(0.6))
                    Spacer()
                    Button("manual") { vm.useManualInput(for: asset) }
                        .buttonStyle(.plain).font(Typography.micro)
                        .foregroundStyle(.secondary)
                } else {
                    Pill(text: "manual input", color: Theme.warning)
                    Spacer()
                }
            }
            HStack(spacing: 4) {
                TextField("SECID / ISIN / issuer", text: $asset.query)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await vm.search(asset: asset) } }
                Button { Task { await vm.search(asset: asset) } } label: {
                    if asset.isSearching { ProgressView().controlSize(.mini) }
                    else { Image(systemName: "magnifyingglass") }
                }
                .buttonStyle(.bordered).controlSize(.mini)
                marketField("Spot", $asset.spot)
                marketField("σ", sigmaBinding)
                marketField(asset.category == "bonds" ? "YTM/carry" : "q",
                            carryBinding)
            }
            if !asset.hits.isEmpty {
                PricingNewFlowLayout(spacing: 4) {
                    ForEach(asset.hits.prefix(6)) { hit in
                        Button {
                            Task { await vm.resolve(hit, for: asset) }
                        } label: {
                            HStack(spacing: 3) {
                                Text(hit.secid).font(Typography.captionStrong)
                                Text(hit.issuerRu ?? hit.isin ?? "")
                                    .font(Typography.micro).lineLimit(1)
                            }
                            .padding(.horizontal, 5).padding(.vertical, 3)
                            .background(Color.primary.opacity(0.05), in: Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            if needsReason {
                HStack(spacing: 5) {
                    Image(systemName: "pencil.and.outline")
                        .foregroundStyle(Theme.warning)
                    TextField("Обязательная причина manual/override input",
                              text: $asset.overrideReason)
                        .textFieldStyle(.roundedBorder)
                    if asset.category == "bonds" {
                        Text("GBM price-index proxy")
                            .font(Typography.micro).foregroundStyle(Theme.warning)
                    }
                }
            }
        }
        .padding(6)
        .background(Color.primary.opacity(0.025),
                    in: RoundedRectangle(cornerRadius: 7))
        .onChange(of: asset.spot) { _, _ in
            if vm.stateMode == .seasoned {
                vm.seasonedState.stateSourceHash = ""
            }
        }
    }

    private var sigmaBinding: Binding<Double> {
        Binding(
            get: { vm.core.marketSigmas.indices.contains(index)
                ? vm.core.marketSigmas[index] : vm.core.marketSigma },
            set: { value in
                vm.core.synchronizeMarketInputs()
                guard vm.core.marketSigmas.indices.contains(index) else { return }
                vm.core.marketSigmas[index] = value
                if index == 0 { vm.core.marketSigma = value }
            })
    }

    private var carryBinding: Binding<Double> {
        Binding(
            get: { vm.core.marketQs.indices.contains(index)
                ? vm.core.marketQs[index] : vm.core.marketQ },
            set: { value in
                vm.core.synchronizeMarketInputs()
                guard vm.core.marketQs.indices.contains(index) else { return }
                vm.core.marketQs[index] = value
                if index == 0 { vm.core.marketQ = value }
            })
    }

    private var needsReason: Bool {
        guard let input = vm.attachmentDraft().assets.first(where: {
            $0.index == index
        }) else { return true }
        return input.source == .manualOverride || input.spotOverridden
            || input.volatilityOverridden || input.carryOverridden
    }

    private func marketField(_ label: String,
                             _ binding: Binding<Double>) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label).font(Typography.micro).foregroundStyle(.tertiary)
            TextField("", value: binding, format: .number)
                .textFieldStyle(.roundedBorder).monospacedDigit().frame(width: 72)
        }
    }
}

private struct PricingNewCustomFixingBindingRow: View {
    @Bindable var vm: PricingNewCustomProductIntegrationViewModel
    @Bindable var asset: PricingNewCustomAssetDraft

    var body: some View {
        GridRow {
            Text(asset.assetName)
                .font(Typography.captionStrong).frame(minWidth: 70,
                                                       alignment: .leading)
            Text(asset.secid ?? "unresolved")
                .font(.system(size: 9, design: .monospaced))
                .foregroundStyle(asset.secid == nil ? Theme.negative : .secondary)
                .frame(minWidth: 90, alignment: .leading)
            Picker("", selection: Binding(
                get: { asset.fixingPriceBasis },
                set: {
                    asset.fixingPriceBasis = $0
                    vm.invalidateContractScheduleEvidence()
                })) {
                ForEach(PricingNewCustomPriceBasis.allCases, id: \.self) { basis in
                    Text(basis.rawValue).tag(basis)
                }
            }
            .labelsHidden().pickerStyle(.menu).frame(width: 150)
            TextField("server default", text: Binding(
                get: { asset.board ?? "" },
                set: {
                    let value = $0.trimmingCharacters(
                        in: .whitespacesAndNewlines)
                    asset.board = value.isEmpty ? nil : value
                    vm.invalidateContractScheduleEvidence()
                }))
                .textFieldStyle(.roundedBorder)
                .font(.system(size: 9, design: .monospaced))
                .frame(width: 92)
            TextField("empty = main", text: Binding(
                get: { asset.fixingSession },
                set: {
                    asset.fixingSession = $0.trimmingCharacters(
                        in: .whitespacesAndNewlines)
                    vm.invalidateContractScheduleEvidence()
                }))
                .textFieldStyle(.roundedBorder)
                .font(.system(size: 9, design: .monospaced))
                .frame(width: 104)
            Text("MOEX · error")
                .font(.system(size: 9, design: .monospaced))
                .foregroundStyle(.secondary)
        }
    }
}

private struct PricingNewCustomLabeledField<Content: View>: View {
    let label: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased()).font(Typography.label)
                .foregroundStyle(.secondary)
            content
        }
    }
}

// MARK: - Full typed AST editor (inline, no sheet or nested tab)

private struct PricingNewCustomASTInlineEditor: View {
    @Bindable var vm: PricingNewCustomProductIntegrationViewModel
    let detail: CustomProductDetail
    @Bindable var editor: EDefinition

    private var editable: Bool {
        detail.state != "published" && detail.state != "deprecated"
    }

    var body: some View {
        DisclosureGroup(isExpanded: $vm.showPayoutEditor) {
            VStack(alignment: .leading, spacing: Theme.s3) {
                if !editable {
                    Label("Published/deprecated version неизменяема; создай новую версию.",
                          systemImage: "lock.fill")
                        .font(Typography.micro).foregroundStyle(.secondary)
                }
                ForEach(editor.localHints, id: \.self) { hint in
                    Label(hint, systemImage: "exclamationmark.triangle.fill")
                        .font(Typography.micro).foregroundStyle(Theme.warning)
                }
                HStack(alignment: .top, spacing: Theme.s4) {
                    VStack(alignment: .leading, spacing: Theme.s3) {
                        assetsSection
                        slotsSection
                        stateSection
                        scheduleSection
                    }
                    .frame(minWidth: 350, maxWidth: 460, alignment: .topLeading)
                    VStack(alignment: .leading, spacing: Theme.s3) {
                        programSection("OBSERVATION PROGRAM",
                                       program: $editor.observationProgram,
                                       allowTerminate: true)
                        programSection("MATURITY PROGRAM",
                                       program: $editor.maturityProgram,
                                       allowTerminate: false)
                    }
                    .frame(maxWidth: .infinity, alignment: .topLeading)
                }
                .disabled(!editable)
                HStack {
                    Spacer()
                    Button("Сохранить и скомпилировать") {
                        Task { await vm.saveAndCompile() }
                    }
                    .buttonStyle(.borderedProminent).tint(Theme.accent)
                    .controlSize(.small)
                    .disabled(!editable || vm.core.isBusy || !vm.core.isEditorDirty)
                }
            }
            .padding(.top, Theme.s2)
        } label: {
            HStack {
                BlockTitle("Payout graph · typed AST", icon: "function")
                if vm.core.isEditorDirty { Pill(text: "unsaved", color: Theme.warning) }
                Spacer()
                Text("assets · slots · state · schedule · conditions · payments")
                    .font(Typography.micro).foregroundStyle(.tertiary)
            }
        }
    }

    private var assetsSection: some View {
        astSection("ASSETS") {
            ForEach(Array(editor.assets.enumerated()), id: \.offset) { index, _ in
                HStack(spacing: 4) {
                    TextField("Asset \(index + 1)", text: Binding(
                        get: { editor.assets[index] },
                        set: { editor.assets[index] = $0 }
                    ))
                    .textFieldStyle(.roundedBorder)
                    if editor.assets.count > 1 {
                        Button { editor.assets.remove(at: index) } label: {
                            Image(systemName: "xmark.circle.fill")
                        }
                        .buttonStyle(.plain).foregroundStyle(.tertiary)
                    }
                }
            }
            Button {
                editor.assets.append("Asset \(editor.assets.count + 1)")
            } label: {
                Label("Актив", systemImage: "plus.circle")
            }
            .buttonStyle(.plain).font(Typography.micro)
            .foregroundStyle(Theme.accent)
        }
    }

    private var slotsSection: some View {
        astSection("SLOTS") {
            ForEach(editor.slots) { slot in
                PricingNewCustomASTSlotRow(slot: slot) {
                    editor.slots.removeAll { $0.id == slot.id }
                }
            }
            Button {
                editor.slots.append(ESlot(name: "slot\(editor.slots.count + 1)"))
            } label: { Label("Слот", systemImage: "plus.circle") }
                .buttonStyle(.plain).font(Typography.micro)
                .foregroundStyle(Theme.accent)
        }
    }

    private var stateSection: some View {
        astSection("STATE") {
            ForEach(editor.states) { state in
                HStack(spacing: 4) {
                    TextField("name", text: Bindable(state).name)
                        .textFieldStyle(.roundedBorder).frame(width: 100)
                    TextField("initial", value: Bindable(state).initial,
                              format: .number)
                        .textFieldStyle(.roundedBorder).frame(width: 72)
                    Button { editor.states.removeAll { $0.id == state.id } } label: {
                        Image(systemName: "xmark.circle.fill")
                    }.buttonStyle(.plain).foregroundStyle(.tertiary)
                }
            }
            Button {
                editor.states.append(EStateVar(
                    name: editor.states.isEmpty ? "memory"
                    : "state\(editor.states.count + 1)"))
            } label: { Label("State", systemImage: "plus.circle") }
                .buttonStyle(.plain).font(Typography.micro)
                .foregroundStyle(Theme.accent)
        }
    }

    private var scheduleSection: some View {
        astSection("SCHEDULE") {
            scheduleField("Observations", slot: $editor.obsSlot,
                          value: $editor.obsCount)
            scheduleField("Maturity, y", slot: $editor.matSlot,
                          value: $editor.matValue)
        }
    }

    private func scheduleField(_ label: String, slot: Binding<String>,
                               value: Binding<Double>) -> some View {
        HStack(spacing: 4) {
            Text(label).font(Typography.micro).frame(width: 76, alignment: .leading)
            Picker("", selection: slot) {
                Text("literal").tag("")
                ForEach(editor.slotNames, id: \.self) { Text($0).tag($0) }
            }
            .labelsHidden().pickerStyle(.menu).neutralControlTint().frame(width: 90)
            if slot.wrappedValue.isEmpty {
                TextField("", value: value, format: .number)
                    .textFieldStyle(.roundedBorder).frame(width: 72)
            }
        }
    }

    private func programSection(_ title: String,
                                program: Binding<[EAction]>,
                                allowTerminate: Bool) -> some View {
        astSection(title) {
            ForEach(program.wrappedValue) { action in
                ActionEditor(
                    action: action,
                    defn: editor,
                    allowTerminate: allowTerminate,
                    onDelete: {
                        program.wrappedValue.removeAll { $0.id == action.id }
                    },
                    onMove: { delta in move(action, in: program, by: delta) })
            }
            Menu {
                let kinds = allowTerminate
                    ? ["accumulate", "set", "pay", "terminate"]
                    : ["accumulate", "set", "pay"]
                ForEach(kinds, id: \.self) { kind in
                    Button(actionTitle(kind)) {
                        program.wrappedValue.append(EAction(kind: kind))
                    }
                }
            } label: {
                Label("Действие", systemImage: "plus.circle")
                    .font(Typography.micro)
            }
            .menuStyle(.borderlessButton).fixedSize()
            .foregroundStyle(Theme.accent)
        }
    }

    private func move(_ action: EAction, in program: Binding<[EAction]>,
                      by delta: Int) {
        guard let index = program.wrappedValue.firstIndex(where: {
            $0.id == action.id
        }) else { return }
        let target = index + delta
        guard program.wrappedValue.indices.contains(target) else { return }
        program.wrappedValue.swapAt(index, target)
    }

    private func astSection(_ title: String,
                            @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(Typography.label).foregroundStyle(.secondary)
            content()
        }
    }
}

private struct PricingNewCustomASTSlotRow: View {
    @Bindable var slot: ESlot
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: 4) {
            TextField("name", text: $slot.name)
                .textFieldStyle(.roundedBorder).frame(width: 82)
                .font(.system(size: 10, design: .monospaced))
            TextField("label", text: $slot.label)
                .textFieldStyle(.roundedBorder).frame(width: 105)
            numeric("def", $slot.def)
            numeric("min", $slot.lo)
            numeric("max", $slot.hi)
            Button { onDelete() } label: { Image(systemName: "xmark.circle.fill") }
                .buttonStyle(.plain).foregroundStyle(.tertiary)
        }
    }

    private func numeric(_ label: String, _ value: Binding<Double>) -> some View {
        TextField(label, value: value, format: .number)
            .textFieldStyle(.roundedBorder).frame(width: 58).monospacedDigit()
    }
}

private func pricingNewCustomStateColor(_ state: String) -> Color {
    switch state {
    case "tested": return Theme.accent
    case "submitted": return Theme.warning
    case "approved": return .blue
    case "published": return Theme.positive
    case "deprecated": return Theme.negative
    default: return .secondary
    }
}
