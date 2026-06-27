import SwiftUI
import Observation

/// Data Health: the *computed* validation status of the active snapshot
/// (completeness / freshness / production-eligibility) + recent ingest runs and
/// failures — so partial loads and ingest errors are visible instead of hiding
/// behind a metadata quality=OK. Backed by GET /md/health.
@MainActor
@Observable
final class DataHealthVM {
    var health: DataHealth?
    var loading = false
    var serverDown = false
    private let client = BridgeClient()

    func load() async {
        loading = true
        do { health = try await client.dataHealth(); serverDown = false }
        catch { serverDown = true }
        loading = false
    }
}

struct DataHealthView: View {
    @State private var vm = DataHealthVM()

    var body: some View {
        ScreenScaffold {
            if vm.serverDown {
                ContentUnavailableView("Bridge offline", systemImage: "bolt.horizontal.circle")
                    .frame(height: 200)
            } else if let h = vm.health, h.available {
                statusCard(h)
                metricsCard(h)
                if let alerts = h.alerts, !alerts.isEmpty { alertsCard(alerts) }
                ingestCard(h)
            } else if vm.loading {
                ProgressView().frame(maxWidth: .infinity, minHeight: 200)
            } else {
                Text("Нет данных о качестве. Запусти ingest.")
                    .font(.caption).foregroundStyle(.secondary).frame(height: 120)
            }
        }
        .task { await vm.load() }
    }

    // MARK: status

    private func statusCard(_ h: DataHealth) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack(alignment: .firstTextBaseline, spacing: Theme.s2) {
                    Text(h.snapshotID ?? "—").font(.system(size: 17, weight: .bold))
                    Text([h.source, h.valuationDate].compactMap { $0 }.joined(separator: " · "))
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                    Spacer()
                    statusBadge(h.status ?? "?")
                }
                HStack(spacing: Theme.s2) {
                    eligibilityBadge(h.productionEligible ?? false, isDemo: h.isDemo ?? false)
                    Spacer()
                }
            }
        }
    }

    private func statusBadge(_ status: String) -> some View {
        let c = statusColor(status)
        return Text(status)
            .font(.system(size: 12, weight: .bold))
            .padding(.horizontal, Theme.s3).padding(.vertical, 4)
            .background(c.opacity(0.18), in: Capsule())
            .foregroundStyle(c)
    }

    private func eligibilityBadge(_ eligible: Bool, isDemo: Bool) -> some View {
        let (txt, c, icon) = eligible
            ? ("Пригодно для расчётов", Theme.positive, "checkmark.seal.fill")
            : (isDemo ? "DEMO — не для production" : "Не пригодно без override",
               Theme.negative, "exclamationmark.triangle.fill")
        return Label(txt, systemImage: icon)
            .font(.system(size: 11, weight: .medium))
            .padding(.horizontal, Theme.s2).padding(.vertical, 3)
            .background(c.opacity(0.14), in: RoundedRectangle(cornerRadius: 7))
            .foregroundStyle(c)
    }

    // MARK: metrics

    private func metricsCard(_ h: DataHealth) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Полнота и свежесть", icon: "checklist")
                HStack(spacing: Theme.s4) {
                    metric("Полнота", h.completenessPct.map { Fmt.percent($0, digits: 1) } ?? "—",
                           color: (h.completenessPct ?? 0) >= 99.9 ? Theme.positive : Theme.warning)
                    metric("Свежесть", h.stalenessDays.map { "\($0) дн" } ?? "—",
                           color: (h.stalenessDays ?? 0) <= 4 ? Theme.positive : Theme.warning)
                    metric("Vol points", h.checks?.volPoints.map { "\($0)" } ?? "—")
                    metric("Базовые активы", h.checks?.volUnderlyings.map { "\($0)" } ?? "—")
                    metric("Облигации", h.checks?.bondQuotes.map { "\($0)" } ?? "—")
                    Spacer()
                }
                if let cm = h.checks?.curvesMissing, !cm.isEmpty {
                    Text("Нет кривых: \(cm.joined(separator: ", "))")
                        .font(.system(size: 10)).foregroundStyle(Theme.negative)
                }
                if let fm = h.checks?.fxMissing, !fm.isEmpty {
                    Text("Нет FX: \(fm.joined(separator: ", "))")
                        .font(.system(size: 10)).foregroundStyle(Theme.negative)
                }
            }
        }
    }

    private func metric(_ label: String, _ value: String, color: Color = .primary) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased()).font(.system(size: 9, weight: .semibold)).foregroundStyle(.tertiary)
            Text(value).font(.system(size: 16, weight: .semibold)).monospacedDigit().foregroundStyle(color)
        }
    }

    // MARK: alerts

    private func alertsCard(_ alerts: [String]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s2) {
                BlockTitle("Предупреждения", icon: "exclamationmark.triangle")
                ForEach(alerts, id: \.self) { a in
                    Label(a, systemImage: "circle.fill")
                        .font(.system(size: 11)).foregroundStyle(Theme.warning)
                        .labelStyle(.titleAndIcon)
                }
            }
        }
    }

    // MARK: ingest

    private func ingestCard(_ h: DataHealth) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Theme.s3) {
                BlockTitle("Загрузка данных (ingest)", icon: "icloud.and.arrow.down")
                if let g = h.ingest {
                    HStack(spacing: Theme.s4) {
                        metric("OK", "\(g.ok)", color: Theme.positive)
                        metric("Ошибки", "\(g.error)", color: g.error > 0 ? Theme.negative : .primary)
                        metric("Пропущено", "\(g.skipped)")
                        Spacer()
                    }
                }
                if let fails = h.failures, !fails.isEmpty {
                    Divider().opacity(0.3)
                    Text("Последние ошибки").font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                    ForEach(fails) { f in
                        VStack(alignment: .leading, spacing: 1) {
                            HStack {
                                Text(f.endpoint).font(.system(size: 11, weight: .medium))
                                Spacer()
                                if let at = f.at {
                                    Text(at).font(.system(size: 9)).foregroundStyle(.tertiary)
                                }
                            }
                            Text(f.error).font(.system(size: 10)).foregroundStyle(Theme.negative)
                                .lineLimit(2)
                        }
                        .padding(.vertical, 2)
                        Divider().opacity(0.2)
                    }
                } else {
                    Text("Ошибок загрузки нет").font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func statusColor(_ s: String) -> Color {
        switch s {
        case "OK": return Theme.positive
        case "WARN": return Theme.warning
        case "FAIL", "REJECTED": return Theme.negative
        default: return .secondary
        }
    }
}
