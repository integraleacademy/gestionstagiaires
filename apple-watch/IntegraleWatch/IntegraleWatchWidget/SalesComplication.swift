import SwiftUI
import WidgetKit

struct SalesComplicationEntry: TimelineEntry {
    let date: Date
    let dashboard: DashboardEnvelope?
}

struct SalesComplicationProvider: TimelineProvider {
    func placeholder(in context: Context) -> SalesComplicationEntry {
        SalesComplicationEntry(date: Date(), dashboard: .preview)
    }

    func getSnapshot(
        in context: Context,
        completion: @escaping (SalesComplicationEntry) -> Void
    ) {
        let dashboard = context.isPreview
            ? DashboardEnvelope.preview
            : SnapshotStore.load()?.dashboard
        completion(SalesComplicationEntry(date: Date(), dashboard: dashboard))
    }

    func getTimeline(
        in context: Context,
        completion: @escaping (Timeline<SalesComplicationEntry>) -> Void
    ) {
        Task {
            var dashboard = SnapshotStore.load()?.dashboard
            if let token = TokenStore.read(),
               let freshDashboard = try? await DashboardAPIClient().fetchDashboard(token: token) {
                dashboard = freshDashboard
                SnapshotStore.save(freshDashboard)
            }
            let entry = SalesComplicationEntry(date: Date(), dashboard: dashboard)
            let requestedRefresh = Calendar.current.date(
                byAdding: .minute,
                value: 15,
                to: Date()
            ) ?? Date().addingTimeInterval(900)
            completion(Timeline(entries: [entry], policy: .after(requestedRefresh)))
        }
    }
}

struct SalesComplication: Widget {
    private let kind = "IntegraleSalesComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SalesComplicationProvider()) { entry in
            SalesComplicationView(entry: entry)
                .containerBackground(.clear, for: .widget)
                .widgetURL(URL(string: "integralewatch://dashboard"))
        }
        .configurationDisplayName("Ventes Intégrale")
        .description("CA et ventes issus de Gestion Stagiaires.")
        .supportedFamilies([
            .accessoryCircular,
            .accessoryCorner,
            .accessoryInline,
            .accessoryRectangular
        ])
    }
}

struct MonthComplication: Widget {
    private let kind = "IntegraleMonthComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SalesComplicationProvider()) { entry in
            MonthComplicationView(entry: entry)
                .containerBackground(.clear, for: .widget)
                .widgetURL(URL(string: "integralewatch://dashboard"))
        }
        .configurationDisplayName("CA du mois")
        .description("Chiffre d’affaires, ventes et objectif du mois.")
        .supportedFamilies([
            .accessoryCircular,
            .accessoryCorner,
            .accessoryInline,
            .accessoryRectangular
        ])
    }
}

struct GoalComplication: Widget {
    private let kind = "IntegraleGoalComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SalesComplicationProvider()) { entry in
            GoalComplicationView(entry: entry)
                .containerBackground(.clear, for: .widget)
                .widgetURL(URL(string: "integralewatch://dashboard"))
        }
        .configurationDisplayName("Objectif mensuel")
        .description("Progression et reste à vendre sur l’objectif du mois.")
        .supportedFamilies([
            .accessoryCircular,
            .accessoryCorner,
            .accessoryInline,
            .accessoryRectangular
        ])
    }
}

private struct SalesComplicationView: View {
    @Environment(\.widgetFamily) private var family
    let entry: SalesComplicationEntry

    var body: some View {
        if let dashboard = entry.dashboard {
            switch family {
            case .accessoryInline:
                Text("CA \(MoneyText.compact(dashboard.today.revenueCents)) · \(dashboard.today.salesCount) ventes")

            case .accessoryCircular:
                VStack(spacing: 0) {
                    Image(systemName: "eurosign")
                        .font(.caption2.bold())
                    Text(MoneyText.compact(dashboard.today.revenueCents))
                        .font(.system(size: 12, weight: .heavy, design: .rounded))
                        .minimumScaleFactor(0.55)
                }

            case .accessoryCorner:
                Text(MoneyText.compact(dashboard.today.revenueCents))
                    .font(.system(size: 13, weight: .heavy, design: .rounded))
                    .widgetLabel {
                        Text("\(dashboard.today.salesCount) ventes")
                    }

            default:
                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Label("CA du jour", systemImage: "bolt.fill")
                            .font(.caption2.bold())
                        Spacer()
                        Text("\(dashboard.today.salesCount) ventes")
                            .font(.system(size: 9))
                    }
                    Text(MoneyText.full(dashboard.today.revenueCents))
                        .font(.system(size: 18, weight: .heavy, design: .rounded))
                        .minimumScaleFactor(0.65)
                    Text("Mois : \(MoneyText.compact(dashboard.month.revenueCents)) · \(dashboard.month.progressPercent, specifier: "%.0f") %")
                        .font(.system(size: 9))
                        .foregroundStyle(.secondary)
                }
            }
        } else {
            VStack(spacing: 2) {
                Image(systemName: "lock.fill")
                Text("Ouvre Intégrale")
                    .font(.caption2)
                    .multilineTextAlignment(.center)
            }
        }
    }
}

private struct MonthComplicationView: View {
    @Environment(\.widgetFamily) private var family
    let entry: SalesComplicationEntry

    var body: some View {
        if let dashboard = entry.dashboard {
            switch family {
            case .accessoryInline:
                Text("Mois \(MoneyText.compact(dashboard.month.revenueCents)) · \(dashboard.month.salesCount) ventes")

            case .accessoryCircular:
                VStack(spacing: 0) {
                    Image(systemName: "calendar")
                        .font(.caption2.bold())
                    Text(MoneyText.compact(dashboard.month.revenueCents))
                        .font(.system(size: 11, weight: .heavy, design: .rounded))
                        .minimumScaleFactor(0.5)
                }

            case .accessoryCorner:
                Text(MoneyText.compact(dashboard.month.revenueCents))
                    .font(.system(size: 13, weight: .heavy, design: .rounded))
                    .widgetLabel {
                        Text("\(dashboard.month.salesCount) ventes")
                    }

            default:
                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Label(dashboard.month.label, systemImage: "calendar")
                            .font(.caption2.bold())
                        Spacer()
                        Text("\(dashboard.month.salesCount) ventes")
                            .font(.system(size: 9))
                    }
                    Text(MoneyText.full(dashboard.month.revenueCents))
                        .font(.system(size: 18, weight: .heavy, design: .rounded))
                        .minimumScaleFactor(0.65)
                    Text("Objectif : \(dashboard.month.progressPercent, specifier: "%.0f") %")
                        .font(.system(size: 9))
                        .foregroundStyle(.secondary)
                }
            }
        } else {
            LockedComplicationView()
        }
    }
}

private struct GoalComplicationView: View {
    @Environment(\.widgetFamily) private var family
    let entry: SalesComplicationEntry

    var body: some View {
        if let dashboard = entry.dashboard {
            let hasObjective = dashboard.month.objectiveCents > 0
            let percentage = hasObjective
                ? Int(dashboard.month.progressPercent.rounded())
                : 0

            switch family {
            case .accessoryInline:
                if hasObjective {
                    Text("Objectif \(percentage) % · reste \(MoneyText.compact(dashboard.month.remainingCents))")
                } else {
                    Text("Objectif mensuel à définir")
                }

            case .accessoryCircular:
                if hasObjective {
                    ZStack {
                        Circle()
                            .stroke(Color.secondary.opacity(0.25), lineWidth: 4)
                        Circle()
                            .trim(
                                from: 0,
                                to: CGFloat(min(max(dashboard.month.progressPercent, 0), 100) / 100)
                            )
                            .stroke(Color.accentColor, style: StrokeStyle(lineWidth: 4, lineCap: .round))
                            .rotationEffect(.degrees(-90))
                        Text("\(percentage)%")
                            .font(.system(size: 11, weight: .heavy, design: .rounded))
                            .minimumScaleFactor(0.6)
                    }
                    .padding(2)
                } else {
                    Image(systemName: "target")
                }

            case .accessoryCorner:
                Text(hasObjective ? "\(percentage)%" : "—")
                    .font(.system(size: 13, weight: .heavy, design: .rounded))
                    .widgetLabel {
                        Text(hasObjective ? "reste \(MoneyText.compact(dashboard.month.remainingCents))" : "Objectif")
                    }

            default:
                VStack(alignment: .leading, spacing: 3) {
                    Label("Objectif du mois", systemImage: "target")
                        .font(.caption2.bold())
                    if hasObjective {
                        HStack(alignment: .firstTextBaseline) {
                            Text("\(percentage) %")
                                .font(.system(size: 18, weight: .heavy, design: .rounded))
                            Spacer()
                            Text("reste \(MoneyText.compact(dashboard.month.remainingCents))")
                                .font(.system(size: 9))
                        }
                        ProgressView(
                            value: min(max(dashboard.month.progressPercent, 0), 100),
                            total: 100
                        )
                        .tint(dashboard.month.status == "ahead" ? .green : .orange)
                    } else {
                        Text("À définir dans Gestion Stagiaires")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        } else {
            LockedComplicationView()
        }
    }
}

private struct LockedComplicationView: View {
    var body: some View {
        VStack(spacing: 2) {
            Image(systemName: "lock.fill")
            Text("Ouvre Intégrale")
                .font(.caption2)
                .multilineTextAlignment(.center)
        }
    }
}

#Preview(as: .accessoryRectangular) {
    SalesComplication()
} timeline: {
    SalesComplicationEntry(date: .now, dashboard: .preview)
}
