import datetime
import unittest
from unittest import mock

import app


class SalesTrackingPriceTests(unittest.TestCase):
    def test_recorded_prices_override_catalogue_prices_for_each_course(self):
        for training_type, recorded_price in (
            ("DIRIGEANT initial", 600),
            ("APS", 950),
            ("A3P", 4250),
            ("CHAUFFEUR VTC", 1200),
            ("DIRIGEANT VAE", 3850),
            ("SSIAP 1", 1230),
        ):
            with self.subTest(training_type=training_type):
                self.assertEqual(
                    app._sales_trainee_price(
                        {"training_price": recorded_price},
                        training_type,
                        app._sales_training_label(training_type),
                    ),
                    recorded_price,
                )

    def test_zero_recorded_price_is_not_replaced_by_the_catalogue_price(self):
        for value in (0, "0", "0.00"):
            with self.subTest(value=value):
                self.assertEqual(app._sales_trainee_price({"training_price": value}, "APS", "APS"), 0)

    def test_missing_or_invalid_price_keeps_the_legacy_catalogue_fallback(self):
        for value in (None, "", "  ", "invalid", "NaN", "Infinity", -10):
            with self.subTest(value=value):
                self.assertEqual(app._sales_trainee_price({"training_price": value}, "APS", "APS"), 1650)

    def test_explicit_sales_adjustment_is_preserved(self):
        self.assertEqual(
            app._sales_trainee_price({"training_price": 600, "sales_tracking_amount": "500,50"}, "DIRIGEANT initial", "DIRIGEANT INITIAL"),
            500.5,
        )
        self.assertEqual(
            app._sales_trainee_price({"training_price": 600, "sales_tracking_amount": "0"}, "DIRIGEANT initial", "DIRIGEANT INITIAL"),
            600,
        )

    def test_decimal_and_formatted_prices_are_not_multiplied_by_one_hundred(self):
        for value in (600.5, "600.50", "600,50", "600,50 €", " 600,50 "):
            with self.subTest(value=value):
                self.assertEqual(app._sales_trainee_price({"training_price": value}, "APS", "APS"), 600.5)
        self.assertEqual(app._sales_trainee_price({"training_price": "1\u202f230,50 €"}, "SSIAP 1", "SSIAP 1"), 1230.5)

    def test_dashboard_and_daily_recap_use_the_same_recorded_prices(self):
        day = datetime.date(2026, 10, 21)
        data = {
            "sessions": [
                {"id": "S1", "training_type": "DIRIGEANT initial", "trainees": [{"id": "T1", "created_at": day.isoformat(), "training_price": "600"}]},
                {"id": "S2", "training_type": "SSIAP 1", "trainees": [{"id": "T2", "created_at": day.isoformat(), "training_price": "1230"}]},
                {"id": "S3", "training_type": "CHAUFFEUR VTC", "trainees": [{"id": "T3", "created_at": day.isoformat(), "training_price": "1500"}]},
            ],
            "sales_tracking": {"objectives": {"2026": {"annual": 720000, "months": {"10": 60000}}}},
            "billing_lines": [],
        }
        metrics = app._build_sales_tracking_metrics(data, day.year, today=day, include_trainee_details=False)
        for key in ("today_revenue", "week_revenue", "current_month_revenue", "annual_revenue"):
            with self.subTest(key=key):
                self.assertEqual(metrics[key], 3330)
        self.assertEqual(metrics["current_month_remaining"], 56670)
        self.assertEqual(metrics["today_inscriptions"], 3)
        self.assertEqual(metrics["monthly_rows"][9]["revenue"], 3330)
        with mock.patch.object(app, "fetch_cnapsv3_tracking_requests", return_value=([], None)):
            report = app.build_daily_recap_data(data, day)
        self.assertEqual(report["sales"]["revenue"], 3330)
        self.assertEqual(report["month_kpi"]["revenue"], 3330)

        data["sessions"][0]["trainees"][0]["training_price"] = "600,50"
        metrics = app._build_sales_tracking_metrics(data, day.year, today=day, include_trainee_details=False)
        self.assertEqual(metrics["today_revenue"], 3330.5)
        self.assertEqual(metrics["current_month_revenue"], 3330.5)
        self.assertEqual(metrics["current_month_remaining"], 56669.5)


if __name__ == "__main__":
    unittest.main()
