"""Contrat d'envoi des accusés CPF : délai, statut, identité, sécurité et aperçu."""
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock
import sqlite3
import time

import pytest
from flask import Flask

import edof_cpf_appointment_mail as mail
from edof_gmail import Vault, connector_key
from cpf_provider import ProviderStore


def row(folder="123456", *, state="notProcessed", title="Formation A3P"):
    return {
        "folder_id": folder, "first_name": "Cassie", "last_name": "Exemple",
        "state": state, "title": title,
        "session_start_date": "2027-02-01", "session_end_date": "2027-03-01",
    }


def snapshot(at, *items):
    return {"checked": float(at), "rows": {r["folder_id"]: r for r in items}}


def category(r):
    return "request" if r["state"] == "notProcessed" else "waiting"


def observe(db, owner, stamp, *rows, complete):
    with db:
        return mail.observe_snapshot(db, owner, snapshot(stamp, *rows), category,
                                     complete=complete, now=stamp)


@pytest.fixture
def setup(tmp_path):
    db = ProviderStore(tmp_path).connect()
    mail.tables(db)
    yield tmp_path, db
    db.close()


def test_new_request_is_queued_only_after_baseline_with_fifteen_minutes(setup):
    directory, db = setup
    assert observe(db, "owner", 1000, row("111111"), complete=True) == []
    assert observe(db, "owner", 1010, row("111111"), complete=False) == []
    assert observe(db, "owner", 1020, row("222222"), complete=False) == ["222222"]
    work = mail.statuses(directory, ["111111", "222222"])
    assert "111111" not in work
    assert work["222222"]["due_at"] == 1020 + 900
    assert observe(db, "owner", 1060, row("222222"), complete=False) == []
    assert mail.statuses(directory, ["222222"])["222222"]["due_at"] == 1920


def test_cancelled_before_due_never_sends_and_is_not_requeued(setup):
    directory, db = setup
    observe(db, "owner", 1000, complete=True)
    assert observe(db, "owner", 1001, row("222222"), complete=False) == ["222222"]
    observe(db, "owner", 1005, row("222222", state="accepted"), complete=False)
    assert mail.statuses(directory, ["222222"])["222222"]["status"] == "skipped"
    # Si une seconde demande arrive avec le même numéro, pas d'envoi doublon.
    assert observe(db, "owner", 1100, row("222222"), complete=False) == []
    assert mail.statuses(directory, ["222222"])["222222"]["status"] == "skipped"


def test_local_handled_flag_cancels_queued_mail(setup):
    directory, db = setup
    observe(db, "owner", 1000, complete=True)
    observe(db, "owner", 1010, row(), complete=False)
    assert mail.cancel_local(directory, "123456", now=1015) == 1
    assert mail.statuses(directory, ["123456"])["123456"]["status"] == "skipped"
    assert mail.cancel_local(directory, "123456", now=1020) == 0


def test_disappearing_from_full_directory_cancels_delivery(setup):
    directory, db = setup
    observe(db, "owner", 1000, complete=True)
    observe(db, "owner", 1100, row("333333"), complete=False)
    observe(db, "owner", 1110, complete=True)
    assert mail.statuses(directory, ["333333"])["333333"]["status"] == "skipped"


def test_operator_can_send_once_after_request_reopens(setup):
    directory, db = setup
    observe(db, "owner", 1000, complete=True)
    observe(db, "owner", 1001, row(), complete=False)
    observe(db, "owner", 1002, row(state="accepted"), complete=False)
    assert mail.statuses(directory, ["123456"])["123456"]["status"] == "skipped"
    # Un nouvel état À traiter doit permettre une correction manuelle,
    # sans rouvrir l'envoi automatique déjà annulé.
    observe(db, "owner", 1003, row(), complete=False)
    store = SimpleNamespace(directory=directory)
    assert mail._claim(store, "owner", "123456", "cassie@example.test", automatic=False, now=1004)
    assert mail._finish(store, "123456", {"ok": True}, 1005) == "sent"
    with pytest.raises(ValueError):
        mail._claim(store, "owner", "123456", "cassie@example.test",
                    automatic=False, now=1006)


def test_send_requires_fresh_edof_evidence_after_due(setup, monkeypatch):
    directory, db = setup
    observe(db, "owner", 1000, complete=True)
    observe(db, "owner", 1001, row(), complete=False)
    private = Mock()
    # Toujours le dossier "À traiter", mais sa lecture a précédé les 15 minutes.
    private.get.side_effect = lambda name, keep=False: {
        "edof-directory-v1-owner": snapshot(1800, row()),
    }.get(name)
    state, detail = mail._current_evidence(
        private, "owner", "123456", due=1901, now=1910, classify=category)
    assert state == "stale" and detail is None
    private.get.side_effect = lambda name, keep=False: {
        "edof-directory-v1-owner": snapshot(1906, row("123456", state="accepted")),
    }.get(name)
    state, detail = mail._current_evidence(
        private, "owner", "123456", due=1901, now=1910, classify=category)
    assert state == "other" and detail["state"] == "accepted"


def test_claim_prevents_double_sending_even_with_concurrent_requests(setup):
    directory, _ = setup
    store = SimpleNamespace(directory=directory)
    assert mail._claim(store, "owner", "123456", "cassie@example.test",
                       automatic=False, now=1000)
    with pytest.raises(ValueError, match="déjà en cours"):
        mail._claim(store, "owner", "123456", "cassie@example.test",
                    automatic=False, now=1000)
    status = mail._finish(store, "123456", {"ok": True, "message_id": "mail"}, 1001)
    assert status == "sent"
    with pytest.raises(ValueError, match="déjà été envoyé"):
        mail._claim(store, "owner", "123456", "cassie@example.test",
                    automatic=False, now=1002)


def test_booking_links_match_real_commercial_appointment_types():
    assert mail.booking_url("Formation APS") == "https://calendly.com/integraleacademy/aps"
    assert mail.booking_url("Agent de protection physique des personnes") == "https://calendly.com/integraleacademy/apr"
    assert mail.booking_url("SSIAP 1") == "https://calendly.com/integraleacademy/ssiap1"
    assert mail.booking_url("Dirigeant d'entreprise de sécurité privée") == "https://calendly.com/integraleacademy/dirigeant"
    assert mail.booking_url("Accompagnement VAE DESP") == "https://calendly.com/integraleacademy/dirigeant"
    assert mail.booking_url("Chauffeur VTC") == "https://calendly.com/integraleacademy/chauffeurvtc"
    assert mail.booking_url("Formation inconnue") == mail.GENERIC_BOOKING


def test_verified_edof_identity_required_for_recipient(tmp_path, monkeypatch):
    private = Vault(tmp_path, connector_key("cle-synthetique-de-test-suffisamment-longue"))
    folder, owner = "123456", "owner"
    private.put("crm-edof-detail:owner:123456", {
        "attendee": {"email": "cassie@example.test",
                     "firstName": "Cassie", "lastName": "Exemple"}
    })
    stub = SimpleNamespace(successful_read=lambda *args, **kwargs: None)
    assert mail.recipient_for(stub, private, owner, row()) == "cassie@example.test"
    assert mail.recipient_for(stub, private, owner, row(state="notProcessed") | {"last_name":"Un autre"}) == ""


def test_email_preview_uses_cassandre_and_crm_legal_footer():
    from pathlib import Path
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    with app.app_context():
        data = mail.message_for(row(title="Agent de prévention et de sécurité APS"),"cassie@example.test")
    assert "Cassandre MENARD" in data["html"]
    assert "34 rue Poissonnière" in data["html"]
    assert "Prendre mon rendez-vous téléphonique" in data["html"]
    assert "Agent de prévention" in data["html"]
    assert data["booking_url"] in data["html"]
    assert "Déclaration d’activité" not in data["subject"]
    assert "cassie@example.test" == data["to"]
