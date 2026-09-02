import Foundation

enum AppConstants {
    static let apiBaseURL = URL(string: "https://gestionstagiaires-r5no.onrender.com")!
    static let appGroupIdentifier = "group.com.integraleacademy.IntegraleWatch"
    static let keychainService = "com.integraleacademy.IntegraleWatch.api"
    static let keychainAccount = "dashboard-token"

    static var keychainAccessGroup: String? {
        guard let value = Bundle.main.object(
            forInfoDictionaryKey: "IntegraleWatchKeychainAccessGroup"
        ) as? String else {
            return nil
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !trimmed.contains("$(") else {
            return nil
        }
        return trimmed
    }
}

