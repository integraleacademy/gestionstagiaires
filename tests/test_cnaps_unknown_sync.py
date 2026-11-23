"""Non-regression tests for safe CNAPSV3 -> Gestion Stagiaires reconciliation."""
import copy

import cnaps_unknown_sync as sync


CANDIDATE = {
    "nom": "LE GLEUT", "prenom": "Adrien", "email": "adrien@example.test",
    "date_naissance": "16/08/1995", "formation": "A3P", "session_date": "2027-03-23",
}
REMOTE = {
    "nom": "LE GLEUT", "prenom": "Adrien", "email": "adrien@example.test",
    "date_naissance": "1995-08-16", "statut_cnaps": "TRANSMIS",
    "formation": "A3P", "session_date": "2027-03-23",
}


class FakeLegacy:
    def __init__(self, cnaps="INCONNU"):
        self.state = {"sessions": [{"id": "S1", "trainees": [
            {"id": "T1", "cnaps": cnaps, "email": CANDIDATE["email"],
             "first_name": CANDIDATE["prenom"], "last_name": CANDIDATE["nom"]},
        ]}]}
        self.saves = 0

    def load_data(self):
        return copy.deepcopy(self.state)

    def save_data(self, data):
        self.state = copy.deepcopy(data)
        self.saves += 1

    def _registered_trainees(self, session):
        return session["trainees"]

    def record_cnaps_status_change(self, trainee, new_status):
        trainee.setdefault("cnaps_history", []).append({"status": new_status})

    def update_data(self, mutator):
        current = self.load_data()
        updated = mutator(current)
        self.save_data(current)
        return updated

    def _collect_cnaps_unknown_trainees(self, data):
        trainee = data["sessions"][0]["trainees"][0]
        if trainee["cnaps"] != "INCONNU":
            return []
        return [{"session_id": "S1", "trainee_id": "T1",
                 "last_name": CANDIDATE["nom"], "first_name": CANDIDATE["prenom"],
                 "email": CANDIDATE["email"], "birth_date": CANDIDATE["date_naissance"],
                 "training_type": "A3P", "date_start": "2027-03-23"}]


def test_transmitted_status_updates_only_cnaps_field():
    legacy = FakeLegacy()
    before = copy.deepcopy(legacy.state["sessions"][0]["trainees"][0])
    result = sync.sync_unknown_statuses(legacy, fetcher=lambda person: [REMOTE])
    assert result["updated"] == 1 and result["errors"] == 0
    after = legacy.state["sessions"][0]["trainees"][0]
    assert after == {**before, "cnaps": "TRANSMIS", "cnaps_history": [{"status": "TRANSMIS"}]}
    assert legacy.saves == 1


def test_no_changes_for_conflicting_birthdate_even_if_email_matches():
    different = {**REMOTE, "date_naissance": "1995-08-17"}
    legacy = FakeLegacy()
    assert sync.sync_unknown_statuses(legacy, fetcher=lambda _: [different])["updated"] == 0
    assert legacy.saves == 0


def test_no_match_if_name_only_without_birth_or_email_confirmation():
    legacy = FakeLegacy()
    bare = {"nom": "LE GLEUT", "prenom": "Adrien", "statut_cnaps": "TRANSMIS"}
    assert sync.sync_unknown_statuses(legacy, fetcher=lambda _: [bare])["updated"] == 0
    assert legacy.saves == 0


def test_email_can_confirm_when_source_has_no_birthdate():
    legacy = FakeLegacy()
    no_birth = {**REMOTE, "date_naissance": "", "statut_cnaps": "ACCEPTÉ"}
    assert sync.sync_unknown_statuses(legacy, fetcher=lambda _: [no_birth])["updated"] == 1
    assert legacy.state["sessions"][0]["trainees"][0]["cnaps"] == "ACCEPTÉ"


def test_ambiguous_multiple_sessions_dont_invent_a_status():
    legacy = FakeLegacy()
    conflicts = [{**REMOTE, "statut_cnaps": "TRANSMIS", "session_date": ""},
                 {**REMOTE, "statut_cnaps": "REFUSÉ", "session_date": ""}]
    assert sync.sync_unknown_statuses(legacy, fetcher=lambda _: conflicts)["updated"] == 0
    assert legacy.saves == 0


def test_multiple_requests_select_exact_session():
    legacy = FakeLegacy()
    remote = [{**REMOTE, "statut_cnaps": "REFUSÉ", "session_date": "2026-02-01"},
              {**REMOTE, "statut_cnaps": "TRANSMIS", "session_date": "2027-03-23"}]
    assert sync.sync_unknown_statuses(legacy, fetcher=lambda _: remote)["updated"] == 1
    assert legacy.state["sessions"][0]["trainees"][0]["cnaps"] == "TRANSMIS"


def test_api_error_keeps_unknown_and_doesnt_save():
    legacy = FakeLegacy()
    def failed(_):
        raise TimeoutError("Remote unavailable")
    result = sync.sync_unknown_statuses(legacy, fetcher=failed)
    assert result["errors"] == 1 and result["updated"] == 0
    assert legacy.saves == 0


def test_manually_updated_local_status_is_preserved():
    legacy = FakeLegacy()
    def update_during_request(_):
        legacy.state["sessions"][0]["trainees"][0]["cnaps"] = "ACCEPTÉ"
        return [REMOTE]
    result = sync.sync_unknown_statuses(legacy, fetcher=update_during_request)
    assert result["updated"] == 0
    assert legacy.state["sessions"][0]["trainees"][0]["cnaps"] == "ACCEPTÉ"
    assert legacy.saves == 1


def test_already_known_status_requires_no_network_call():
    legacy = FakeLegacy("ACCEPTÉ")
    def never_called(_):
        raise AssertionError("should not fetch")
    result = sync.sync_unknown_statuses(legacy, fetcher=never_called)
    assert result["checked"] == 0 and result["updated"] == 0
    assert legacy.saves == 0


def test_not_overriding_unknown_with_unrecognized_status():
    legacy = FakeLegacy()
    assert sync.sync_unknown_statuses(legacy, fetcher=lambda _: [{**REMOTE, "statut_cnaps": "STATUT INCERTAIN"}])["updated"] == 0
    assert legacy.saves == 0


def test_different_training_cannot_override_the_trainee_status():
    legacy = FakeLegacy()
    aps_record = {**REMOTE, "formation": "APS"}
    assert sync.sync_unknown_statuses(legacy, fetcher=lambda _: [aps_record])["updated"] == 0
    assert legacy.saves == 0
