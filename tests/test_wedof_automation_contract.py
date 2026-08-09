import datetime as dt
import inspect
import unittest

from wedof_automation import build_automation_candidate


def folder(*, state="accepted", start="2026-09-07", end="2026-10-09"):
    return {
        "externalId": "WEDOF-TEST-001", "state": state, "type": "cpf",
        "trainingActionInfo": {"startDate": start, "endDate": end},
    }


class WedofAutomationContractTests(unittest.TestCase):
    def test_unlinked_and_mismatched_local_data_cannot_affect_entry_eligibility(self):
        now = dt.datetime(2026, 9, 7, 12, tzinfo=dt.timezone.utc)
        baseline = build_automation_candidate(folder(), "entry", now=now)
        self.assertTrue(baseline["eligible"])
        self.assertEqual(baseline["local_link_status"], "independent")
        self.assertEqual(baseline["wedof_date"], "2026-09-07")
        parameters = inspect.signature(build_automation_candidate).parameters
        self.assertFalse({"session_id", "trainee_id", "date_start", "date_end"} & set(parameters))

    def test_entry_catches_up_with_the_original_wedof_date(self):
        result = build_automation_candidate(
            folder(start="2026-09-01"), "entry",
            now=dt.datetime(2026, 9, 10, 8, tzinfo=dt.timezone.utc),
        )
        self.assertTrue(result["eligible"])
        self.assertEqual(result["wedof_date"], "2026-09-01")
        self.assertTrue(result["requires_remote_reread"])

    def test_service_done_waits_until_the_end_of_the_paris_day_and_catches_up(self):
        remote = folder(state="inTraining", end="2026-10-09")
        during_day = build_automation_candidate(
            remote, "service_done", now=dt.datetime(2026, 10, 9, 21, tzinfo=dt.timezone.utc)
        )
        after_day = build_automation_candidate(
            remote, "service_done", now=dt.datetime(2026, 10, 9, 22, 1, tzinfo=dt.timezone.utc)
        )
        self.assertFalse(during_day["eligible"])
        self.assertTrue(after_day["eligible"])
        self.assertEqual(after_day["wedof_date"], "2026-10-09")

    def test_server_exception_is_external_id_based_not_local_date_based(self):
        result = build_automation_candidate(
            folder(), "entry", now=dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc),
            exceptions=[{"external_id": "WEDOF-TEST-001", "active": True, "reason": "reportée"}],
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["automation_status"], "excepted")
        self.assertEqual(result["wedof_state"], "accepted")


if __name__ == "__main__":
    unittest.main()
