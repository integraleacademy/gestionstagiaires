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

#Preview(as: .accessoryRectangular) {
    SalesComplication()
} timeline: {
    SalesComplicationEntry(date: .now, dashboard: .preview)
}
