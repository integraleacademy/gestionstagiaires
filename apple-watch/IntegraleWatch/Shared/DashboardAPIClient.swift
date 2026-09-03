import Foundation

enum DashboardAPIError: LocalizedError, Equatable {
    case invalidResponse
    case unauthorized
    case pairingCodeInvalid
    case rateLimited(seconds: Int)
    case server(statusCode: Int)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Réponse du serveur illisible."
        case .unauthorized:
            return "Cette montre n’est plus autorisée."
        case .pairingCodeInvalid:
            return "Le code est invalide ou a expiré."
        case .rateLimited(let seconds):
            return "Trop d’essais. Réessaie dans \(max(1, seconds / 60)) min."
        case .server:
            return "Gestion Stagiaires est momentanément indisponible."
        }
    }
}

struct DashboardAPIClient: Sendable {
    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    func pair(code: String, deviceName: String) async throws -> PairingResponse {
        let endpoint = AppConstants.apiBaseURL.appendingPathComponent("api/watch/v1/pair")
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "code": code,
            "device_name": deviceName
        ])
        return try await perform(request, as: PairingResponse.self)
    }

    func fetchDashboard(token: String) async throws -> DashboardEnvelope {
        let endpoint = AppConstants.apiBaseURL.appendingPathComponent("api/watch/v1/dashboard")
        var request = URLRequest(url: endpoint)
        request.httpMethod = "GET"
        request.timeoutInterval = 15
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return try await perform(request, as: DashboardEnvelope.self)
    }

    func registerPushToken(
        _ deviceToken: String,
        environment: String,
        token: String
    ) async throws {
        let endpoint = AppConstants.apiBaseURL.appendingPathComponent("api/watch/v1/push-token")
        var request = URLRequest(url: endpoint)
        request.httpMethod = "PUT"
        request.timeoutInterval = 15
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "token": deviceToken,
            "environment": environment
        ])
        _ = try await perform(request, as: PushTokenResponse.self)
    }

    func unregisterPushToken(token: String) async throws {
        let endpoint = AppConstants.apiBaseURL.appendingPathComponent("api/watch/v1/push-token")
        var request = URLRequest(url: endpoint)
        request.httpMethod = "DELETE"
        request.timeoutInterval = 15
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        _ = try await perform(request, as: PushTokenResponse.self)
    }

    private func perform<Response: Decodable>(
        _ request: URLRequest,
        as responseType: Response.Type
    ) async throws -> Response {
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw DashboardAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            let errorEnvelope = try? Self.decoder.decode(APIErrorEnvelope.self, from: data)
            switch (httpResponse.statusCode, errorEnvelope?.error) {
            case (401, _):
                throw DashboardAPIError.unauthorized
            case (_, "pairing_code_invalid"):
                throw DashboardAPIError.pairingCodeInvalid
            case (429, _):
                let retryAfter = errorEnvelope?.retryAfter
                    ?? Int(httpResponse.value(forHTTPHeaderField: "Retry-After") ?? "")
                    ?? 600
                throw DashboardAPIError.rateLimited(seconds: retryAfter)
            default:
                throw DashboardAPIError.server(statusCode: httpResponse.statusCode)
            }
        }
        do {
            return try Self.decoder.decode(responseType, from: data)
        } catch {
            throw DashboardAPIError.invalidResponse
        }
    }

    private static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}
