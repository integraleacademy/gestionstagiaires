import Foundation

struct DashboardEnvelope: Codable, Equatable, Sendable {
    let ok: Bool
    let schemaVersion: Int
    let generatedAt: String
    let timezone: String
    let currency: String
    let today: SalesPeriod
    let week: WeekSummary
    let month: MonthSummary
    let year: YearSummary
    let trainings: [TrainingSummary]

    static let preview = DashboardEnvelope(
        ok: true,
        schemaVersion: 1,
        generatedAt: "",
        timezone: "Europe/Paris",
        currency: "EUR",
        today: SalesPeriod(date: "", revenueCents: 825_000, salesCount: 5),
        week: WeekSummary(startDate: "", revenueCents: 2_145_000, salesCount: 11),
        month: MonthSummary(
            key: "",
            label: "Septembre",
            revenueCents: 12_645_000,
            salesCount: 37,
            objectiveCents: 17_500_000,
            remainingCents: 4_855_000,
            progressPercent: 72.3,
            status: "ahead"
        ),
        year: YearSummary(
            value: 2026,
            revenueCents: 83_200_000,
            salesCount: 251,
            objectiveCents: 100_000_000,
            progressPercent: 83.2
        ),
        trainings: [
            TrainingSummary(label: "A3P", salesCount: 7, revenueCents: 2_940_000),
            TrainingSummary(label: "APS", salesCount: 14, revenueCents: 2_310_000),
            TrainingSummary(label: "DIRIGEANT", salesCount: 4, revenueCents: 1_720_000)
        ]
    )
}

struct SalesPeriod: Codable, Equatable, Sendable {
    let date: String
    let revenueCents: Int
    let salesCount: Int
}

struct WeekSummary: Codable, Equatable, Sendable {
    let startDate: String
    let revenueCents: Int
    let salesCount: Int
}

struct MonthSummary: Codable, Equatable, Sendable {
    let key: String
    let label: String
    let revenueCents: Int
    let salesCount: Int
    let objectiveCents: Int
    let remainingCents: Int
    let progressPercent: Double
    let status: String
}

struct YearSummary: Codable, Equatable, Sendable {
    let value: Int
    let revenueCents: Int
    let salesCount: Int
    let objectiveCents: Int
    let progressPercent: Double
}

struct TrainingSummary: Codable, Equatable, Identifiable, Sendable {
    let label: String
    let salesCount: Int
    let revenueCents: Int

    var id: String { label }
}

struct PairingResponse: Codable, Sendable {
    let ok: Bool
    let token: String
    let tokenType: String
    let deviceID: String
    let deviceName: String
    let dashboardPath: String
}

struct APIErrorEnvelope: Codable, Sendable {
    let ok: Bool?
    let error: String?
    let retryAfter: Int?
}

