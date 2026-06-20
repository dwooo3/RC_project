import SwiftUI
import Charts

struct GovernanceScreen: View {
    @Bindable var model: AppModel

    var body: some View {
        ScreenScaffold {
            PageHeader("Governance", subtitle: AppSection.governance.subtitle)
            LoadableView(state: model.governance,
                         retry: { Task { await model.load(.governance, force: true) } }) { d in
                content(d)
            }
        }
        .navigationTitle("Governance")
    }

    private struct StatusSlice: Identifiable {
        let status: String
        let count: Int
        var id: String { status }
    }

    @ViewBuilder
    private func content(_ d: GovernanceData) -> some View {
        let total = d.counts.values.reduce(0, +)
        let order = ["Validated", "Approximation", "Prototype", "Placeholder", "Broken"]
        let slices = order.compactMap { s -> StatusSlice? in
            guard let n = d.counts[s], n > 0 else { return nil }
            return StatusSlice(status: s, count: n)
        }

        KPIStrip(items: [
            KPICard(label: "Total models", value: "\(total)", sub: "registry", accent: Theme.accent, icon: "square.stack.3d.up.fill"),
            KPICard(label: "Validated", value: "\(d.counts["Validated"] ?? 0)", sub: "production", accent: Theme.positive, icon: "checkmark.seal.fill"),
            KPICard(label: "Approximation", value: "\(d.counts["Approximation"] ?? 0)", sub: "documented", accent: Theme.accent, icon: "function"),
            KPICard(label: "Prototype", value: "\(d.counts["Prototype"] ?? 0)", sub: "research", accent: Theme.warning, icon: "hammer.fill"),
            KPICard(label: "Broken", value: "\(d.counts["Broken"] ?? 0)", sub: "blocked", accent: Theme.negative, icon: "xmark.octagon.fill"),
        ])

        HStack(alignment: .top, spacing: Theme.s4) {
            donutCard(slices, total: total)
            registryCard(d.models)
        }
        limitationsCard(d.limitations)
    }

    private func donutCard(_ slices: [StatusSlice], total: Int) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Status mix", icon: "chart.pie.fill")
                Chart(slices) { s in
                    SectorMark(angle: .value("Count", s.count), innerRadius: .ratio(0.62), angularInset: 1.5)
                        .foregroundStyle(Theme.statusColor(s.status))
                        .cornerRadius(3)
                }
                .chartLegend(.hidden)
                .frame(width: 168, height: 168)
                .overlay {
                    VStack(spacing: 0) {
                        Text("\(total)").font(.system(size: 22, weight: .bold)).monospacedDigit()
                        Text("models").font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                }
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(slices) { s in
                        HStack(spacing: Theme.s2) {
                            Circle().fill(Theme.statusColor(s.status)).frame(width: 8, height: 8)
                            Text(s.status).font(.system(size: 11))
                            Spacer()
                            Text("\(s.count)").font(.system(size: 11, weight: .semibold)).monospacedDigit()
                        }
                    }
                }
            }
        }
        .frame(width: 240)
    }

    private func registryCard(_ models: [ModelRow]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Model registry", icon: "tablecells")
                Table(sortedModels(models)) {
                    TableColumn("ID") { m in
                        Text(m.modelID).font(.system(size: 12, weight: .medium))
                    }
                    TableColumn("Name") { m in
                        Text(m.name).foregroundStyle(.secondary).lineLimit(1)
                    }
                    TableColumn("Status") { m in
                        Text(m.status).font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(Theme.statusColor(m.status))
                    }
                    TableColumn("Domain") { m in Text(m.domain) }
                    TableColumn("Prod") { m in
                        Image(systemName: m.productionAllowed ? "checkmark.circle.fill" : "minus.circle")
                            .foregroundStyle(m.productionAllowed ? Theme.positive : .secondary)
                    }
                }
                .frame(minHeight: 420)
            }
        }
    }

    private func sortedModels(_ models: [ModelRow]) -> [ModelRow] {
        let rank = ["Validated": 0, "Approximation": 1, "Prototype": 2, "Placeholder": 3, "Broken": 4]
        return models.sorted {
            let a = rank[$0.status] ?? 9, b = rank[$1.status] ?? 9
            return a != b ? a < b : $0.modelID < $1.modelID
        }
    }

    private func limitationsCard(_ limitations: [LimitationRow]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Model limitations", icon: "exclamationmark.triangle")
                ForEach(limitations.prefix(20)) { l in
                    HStack(alignment: .top, spacing: Theme.s2) {
                        Text(l.modelID)
                            .font(.system(size: 11, weight: .semibold)).monospacedDigit()
                            .frame(width: 120, alignment: .leading)
                        Text(l.limitation).font(.system(size: 11)).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Divider()
                }
            }
        }
    }
}
