import SwiftUI

@main
struct IntegraleWatchApp: App {
    @WKExtensionDelegateAdaptor private var extensionDelegate: WatchExtensionDelegate
    @StateObject private var dashboardSession = DashboardSession()

    var body: some Scene {
        WindowGroup {
            Group {
                if dashboardSession.isPaired {
                    DashboardRootView()
                } else {
                    PairingView()
                }
            }
            .environmentObject(dashboardSession)
            .tint(Color(red: 0.30, green: 0.55, blue: 1.0))
            .task {
                await dashboardSession.start()
            }
        }
    }
}
