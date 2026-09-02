import SwiftUI

struct DashboardRootView: View {
    @EnvironmentObject private var dashboardSession: DashboardSession
    @State private var showingDisconnectConfirmation = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 10) {
                    if let dashboard = dashboardSession.dashboard {
                        todayCard(dashboard)
                        monthCard(dashboard)
                        weekAndYear(dashboard)

                        NavigationLink {
                            TrainingListView(trainings: dashboard.trainings)
                        } label: {
                            Label("Détail formations", systemImage: "list.bullet.rectangle")
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }

                        freshnessLine
                    } else if dashboardSession.isLoading {
                        ProgressView("Chargement…")
                            .padding(.vertical, 28)
                    } else {
                        VStack(spacing: 8) {
                            Image(systemName: "wifi.exclamationmark")
                                .font(.title2)
                            Text("Aucune donnée disponible")
                                .font(.headline)
                        }
                        .padding(.vertical, 24)
                    }

                    if let errorMessage = dashboardSession.errorMessage {
                        Text(errorMessage)
                            .font(.caption2)
                            .multilineTextAlignment(.center)
                            .foregroundStyle(.orange)
                    }

                    Button {
                        Task { await dashboardSession.refresh() }
                    } label: {
                        if dashboardSession.isLoading {
                            ProgressView()
                        } else {
                            Label("Actualiser", systemImage: "arrow.clockwise")
                        }
                    }
                    .disabled(dashboardSession.isLoading)

                    Button(role: .destructive) {
                        showingDisconnectConfirmation = true
                    } label: {
                        Label("Dissocier", systemImage: "lock.slash")
                    }
                    .confirmationDialog(
                        "Dissocier cette montre ?",
                        isPresented: $showingDisconnectConfirmation,
                        titleVisibility: .visible
                    ) {
                        Button("Dissocier", role: .destructive) {
                            dashboardSession.disconnect()
                        }
                        Button("Annuler", role: .cancel) {}
                    }
                }
                .padding(.horizontal, 4)
            }
            .navigationTitle("Intégrale")
        }
    }

    private func todayCard(_ dashboard: DashboardEnvelope) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Label("Aujourd’hui", systemImage: "bolt.fill")
                .font(.caption.bold())
                .foregroundStyle(.cyan)
            Text(MoneyText.full(dashboard.today.revenueCents))
                .font(.system(.title2, design: .rounded, weight: .heavy))
                .minimumScaleFactor(0.65)
            Text("\(dashboard.today.salesCount) vente\(dashboard.today.salesCount > 1 ? "s" : "")")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(
            LinearGradient(
                colors: [Color.blue.opacity(0.45), Color.indigo.opacity(0.28)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            ),
            in: RoundedRectangle(cornerRadius: 16)
        )
    }

    private func monthCard(_ dashboard: DashboardEnvelope) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(dashboard.month.label)
                    .font(.headline)
                Spacer()
                Text("\(dashboard.month.salesCount) ventes")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Text(MoneyText.full(dashboard.month.revenueCents))
                .font(.title3.bold())
            ProgressView(value: min(max(dashboard.month.progressPercent, 0), 100), total: 100)
                .tint(dashboard.month.status == "ahead" ? .green : .orange)
            HStack {
                Text("\(dashboard.month.progressPercent, specifier: "%.1f") %")
                Spacer()
                if dashboard.month.objectiveCents > 0 {
                    Text("reste \(MoneyText.compact(dashboard.month.remainingCents))")
                } else {
                    Text("objectif non défini")
                }
            }
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
        .padding(11)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 16))
    }

    private func weekAndYear(_ dashboard: DashboardEnvelope) -> some View {
        HStack(spacing: 7) {
            miniCard(
                title: "Semaine",
                value: MoneyText.compact(dashboard.week.revenueCents),
                caption: "\(dashboard.week.salesCount) ventes"
            )
            miniCard(
                title: "Année",
                value: MoneyText.compact(dashboard.year.revenueCents),
                caption: "\(dashboard.year.salesCount) ventes"
            )
        }
    }

    private func miniCard(title: String, value: String, caption: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.headline).minimumScaleFactor(0.7)
            Text(caption).font(.system(size: 9)).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(9)
        .background(.quinary, in: RoundedRectangle(cornerRadius: 13))
    }

    @ViewBuilder
    private var freshnessLine: some View {
        if let lastUpdatedAt = dashboardSession.lastUpdatedAt {
            Text("Mis à jour \(lastUpdatedAt, style: .relative)")
                .font(.system(size: 9))
                .foregroundStyle(.secondary)
        }
    }
}

private struct TrainingListView: View {
    let trainings: [TrainingSummary]

    var body: some View {
        List {
            if trainings.isEmpty {
                Text("Aucune vente ce mois-ci")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(trainings) { training in
                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            Text(training.label).font(.headline)
                            Spacer()
                            Text(MoneyText.compact(training.revenueCents)).bold()
                        }
                        Text("\(training.salesCount) vente\(training.salesCount > 1 ? "s" : "")")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .navigationTitle("Formations")
    }
}

#Preview {
    DashboardRootView()
        .environmentObject(DashboardSession())
}
