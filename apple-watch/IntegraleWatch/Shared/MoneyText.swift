import Foundation

enum MoneyText {
    static func full(_ cents: Int) -> String {
        let formatter = NumberFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.numberStyle = .currency
        formatter.currencyCode = "EUR"
        formatter.maximumFractionDigits = 0
        return formatter.string(from: NSNumber(value: Double(cents) / 100)) ?? "0 €"
    }

    static func compact(_ cents: Int) -> String {
        let euros = Double(cents) / 100
        let absolute = abs(euros)
        if absolute >= 1_000_000 {
            return localized(euros / 1_000_000, suffix: "M€")
        }
        if absolute >= 1_000 {
            return localized(euros / 1_000, suffix: "k€")
        }
        return "\(Int(euros.rounded()))€"
    }

    private static func localized(_ value: Double, suffix: String) -> String {
        let formatter = NumberFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.numberStyle = .decimal
        formatter.minimumFractionDigits = 0
        formatter.maximumFractionDigits = abs(value) >= 100 ? 0 : 1
        return "\(formatter.string(from: NSNumber(value: value)) ?? "0")\(suffix)"
    }
}
