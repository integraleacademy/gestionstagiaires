import Foundation
import WatchKit
import WidgetKit

@MainActor
final class DashboardSession: ObservableObject {
    @Published private(set) var dashboard: DashboardEnvelope?
    @Published private(set) var lastUpdatedAt: Date?
    @Published private(set) var isPaired: Bool
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?

    private let apiClient = DashboardAPIClient()

    init() {
        let stored = SnapshotStore.load()
        dashboard = stored?.dashboard
        lastUpdatedAt = stored?.savedAt
        isPaired = TokenStore.read() != nil
    }

    func start() async {
        guard isPaired else { return }
        await PushNotifications.requestAuthorizationAndRegister()
        await refresh(showSpinner: dashboard == nil)
    }

    func pair(code: String) async {
        guard !isLoading else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let response = try await apiClient.pair(
                code: code,
                deviceName: WKInterfaceDevice.current().model
            )
            try TokenStore.save(response.token)
            isPaired = true
            await PushNotifications.requestAuthorizationAndRegister()
            await refresh(showSpinner: false)
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    func refresh(showSpinner: Bool = true) async {
        guard let token = TokenStore.read() else { return }
        if isLoading && showSpinner { return }
        if showSpinner { isLoading = true }
        errorMessage = nil
        defer { if showSpinner { isLoading = false } }

        do {
            let freshDashboard = try await apiClient.fetchDashboard(token: token)
            let updatedAt = Date()
            dashboard = freshDashboard
            lastUpdatedAt = updatedAt
            SnapshotStore.save(freshDashboard, at: updatedAt)
            WidgetCenter.shared.reloadAllTimelines()
        } catch DashboardAPIError.unauthorized {
            disconnect()
            errorMessage = "Cette montre a été révoquée. Recommence le jumelage."
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func disconnect() {
        if let accessToken = TokenStore.read() {
            Task { await PushNotifications.unregister(accessToken: accessToken) }
        }
        WKExtension.shared().unregisterForRemoteNotifications()
        TokenStore.delete()
        SnapshotStore.clear()
        dashboard = nil
        lastUpdatedAt = nil
        isPaired = false
        WidgetCenter.shared.reloadAllTimelines()
    }
}
