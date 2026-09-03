import SwiftUI
import WidgetKit

@main
struct IntegraleWatchWidgetBundle: WidgetBundle {
    var body: some Widget {
        SalesComplication()
        MonthComplication()
        GoalComplication()
    }
}
