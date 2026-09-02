import Foundation

struct StoredDashboard: Codable, Sendable {
    let dashboard: DashboardEnvelope
    let savedAt: Date
}

enum SnapshotStore {
    private static let key = "integrale-watch-dashboard-v1"

    static func load() -> StoredDashboard? {
        guard let data = defaults.data(forKey: key) else {
            return nil
        }
        return try? JSONDecoder().decode(StoredDashboard.self, from: data)
    }

    static func save(_ dashboard: DashboardEnvelope, at date: Date = Date()) {
        let stored = StoredDashboard(dashboard: dashboard, savedAt: date)
        guard let data = try? JSONEncoder().encode(stored) else {
            return
        }
        defaults.set(data, forKey: key)
    }

    static func clear() {
        defaults.removeObject(forKey: key)
    }

    private static var defaults: UserDefaults {
        UserDefaults(suiteName: AppConstants.appGroupIdentifier) ?? .standard
    }
}

