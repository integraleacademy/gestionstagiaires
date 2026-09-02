import SwiftUI

struct PairingView: View {
    @EnvironmentObject private var dashboardSession: DashboardSession
    @State private var pairingCode = ""

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                Image(systemName: "chart.xyaxis.line")
                    .font(.system(size: 34, weight: .bold))
                    .foregroundStyle(.blue.gradient)

                Text("Intégrale")
                    .font(.title3.bold())

                Text("Génère un code dans Gestion Stagiaires, puis saisis-le ici.")
                    .font(.caption2)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)

                TextField("Code à 6 chiffres", text: $pairingCode)
                    .textContentType(.oneTimeCode)
                    .multilineTextAlignment(.center)
                    .onChange(of: pairingCode) { value in
                        pairingCode = String(value.filter(\.isNumber).prefix(6))
                    }

                Button {
                    Task { await dashboardSession.pair(code: pairingCode) }
                } label: {
                    if dashboardSession.isLoading {
                        ProgressView()
                    } else {
                        Text("Jumeler")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(pairingCode.count != 6 || dashboardSession.isLoading)

                if let errorMessage = dashboardSession.errorMessage {
                    Text(errorMessage)
                        .font(.caption2)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.red)
                }
            }
            .padding(.horizontal, 8)
        }
    }
}

#Preview {
    PairingView()
        .environmentObject(DashboardSession())
}

