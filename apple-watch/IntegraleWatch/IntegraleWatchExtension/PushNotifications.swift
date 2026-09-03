import Foundation
import SwiftUI
import UserNotifications
import WatchKit
import WidgetKit

enum PushNotifications {
    @MainActor
    static func requestAuthorizationAndRegister() async {
        let center = UNUserNotificationCenter.current()
        let settings = await center.notificationSettings()
        let isAuthorized: Bool

        switch settings.authorizationStatus {
        case .authorized, .provisional:
            isAuthorized = true
        case .notDetermined:
            isAuthorized = (try? await center.requestAuthorization(options: [.alert, .sound])) == true
        case .denied:
            isAuthorized = false
        @unknown default:
            isAuthorized = false
        }

        guard isAuthorized else { return }
        WKExtension.shared().registerForRemoteNotifications()
    }

    static func upload(_ deviceToken: Data) async {
        guard let accessToken = TokenStore.read() else { return }
        let hexadecimalToken = deviceToken.map { String(format: "%02x", $0) }.joined()
        try? await DashboardAPIClient().registerPushToken(
            hexadecimalToken,
            environment: AppConstants.pushEnvironment,
            token: accessToken
        )
    }

    static func unregister(accessToken: String) async {
        try? await DashboardAPIClient().unregisterPushToken(token: accessToken)
    }

    static func refreshSnapshot() async -> WKBackgroundFetchResult {
        guard let accessToken = TokenStore.read() else { return .noData }
        do {
            let previous = SnapshotStore.load()?.dashboard
            let fresh = try await DashboardAPIClient().fetchDashboard(token: accessToken)
            SnapshotStore.save(fresh)
            WidgetCenter.shared.reloadAllTimelines()
            return previous == fresh ? .noData : .newData
        } catch {
            return .failed
        }
    }
}

final class WatchExtensionDelegate: NSObject, WKExtensionDelegate {
    func didRegisterForRemoteNotifications(withDeviceToken deviceToken: Data) {
        Task { await PushNotifications.upload(deviceToken) }
    }

    func didFailToRegisterForRemoteNotificationsWithError(_ error: Error) {
        // L'app et les complications restent utilisables sans notifications.
    }

    func didReceiveRemoteNotification(
        _ userInfo: [AnyHashable: Any],
        fetchCompletionHandler completionHandler: @escaping (WKBackgroundFetchResult) -> Void
    ) {
        Task {
            completionHandler(await PushNotifications.refreshSnapshot())
        }
    }
}
