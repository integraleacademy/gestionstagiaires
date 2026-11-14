from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from werkzeug.exceptions import Conflict

import afc_training_mail as mail
import app as host


def candidate(key, **fields):
    return {"id": key, "prenom": key, "nom": "Exemple", "email": f"{key}@example.test", **fields}


@pytest.fixture
def setup(monkeypatch, tmp_path):
    data_file = tmp_path / "data.json"
    data_file.write_text("{}")
    monkeypatch.setattr(host, "DATA_FILE", str(data_file))
    monkeypatch.setattr(host, "PERSIST_DIR", str(tmp_path))
    people = []
    monkeypatch.setattr(host, "load_data", lambda *a, **kw: {"afc": {"candidates": people}, "sessions": []})
    sender = Mock(return_value={"ok": True, "message_id": "fake-accepted"})
    monkeypatch.setattr(host, "brevo_send_email", sender)
    monkeypatch.setattr(mail, "start_worker", Mock())
    client = host.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    return people, sender, client


def test_audience_matches_active_afc_and_vetoes_shared_addresses_and_ids(setup, monkeypatch):
    people, _, _ = setup
    monkeypatch.setattr(host, "_is_blocked_email_recipient", lambda value: value == "blocked@example.test")
    people.extend([
        candidate("attente"), candidate("non", decision="NON RETENU", presence_afc_status="ABSENT"),
        candidate("retenue", decision=" RETENUE "), candidate("refuse", cnaps_status="Dossier refusé"),
        candidate("archive", archived=True), candidate("sans", email=""), candidate("incorrect", email="x@y"),
        candidate("copie", email="  ATTENTE@example.test  "), candidate("blocked"),
        candidate("copie-refus", email="REFUSE@example.test"), candidate("meme-personne", identifiant_ft="1234567A"),
        candidate("autre-fiche", email="", decision="RETENU", identifiant_ft="1234567A - 001"),
    ])
    assert set(mail.audience(host)) == {"attente@example.test", "non@example.test"}


def test_preview_post_and_worker_recheck_actual_recipients(setup):
    people, sender, client = setup
    people.extend([candidate("un", prenom="<Luc>"), candidate("deux"), candidate("trois")])
    page = client.get("/admin/afc/formations-2027")
    assert page.status_code == 200
    assert "Envoyer à 3 destinataires" in page.get_data(as_text=True)
    assert client.get("/api/admin/afc/formations-2027/suivi").json == {"active": False, "counts": {}}
    sender.assert_not_called()
    with client.session_transaction() as session:
        token = session["manuals_csrf"]
    with mail.ledger(host) as db:
        _, digest = mail.selection(db, mail.audience(host))
    url = "/admin/afc/formations-2027/envoyer"
    assert client.post(url, data={"audience": digest}).status_code == 400
    assert client.post(url, data={"csrf_token": token, "audience": "stale"}).status_code == 409
    assert client.post(url, data={"csrf_token": token, "audience": digest}).status_code == 303
    assert client.post(url, data={"csrf_token": token, "audience": digest}).status_code == 409
    sender.assert_not_called()
    people[1]["decision"] = "RETENU"
    people[2]["cnaps_status"] = "REFUSÉ"
    people.append(candidate("nouveau"))
    with host.app.app_context():
        mail.process_queue(host)
        mail.process_queue(host)
    sender.assert_called_once()
    args, kwargs = sender.call_args
    assert args[:2] == ("un@example.test", mail.SUBJECT)
    assert "Bonjour &lt;Luc&gt;," in args[2]
    assert "du 4 au 14 janvier 2027" in kwargs["text_content"]
    assert "moins de 29 ans" in args[2] and "26 ans" not in args[2]
    assert "9 février 2027" in args[2] and "1 700 €" in args[2]
    assert kwargs["reply_to"] == mail.CONTACT
    assert client.get("/api/admin/afc/formations-2027/suivi").json["counts"] == {"accepted": 1, "skipped": 2}
    with mail.ledger(host) as db:
        assert set(mail.selection(db, mail.audience(host))[0]) == {"nouveau@example.test"}


def test_parallel_send_and_failure_recovery(setup):
    people, sender, _ = setup
    people.extend(candidate(key) for key in ("ok", "declined", "timeout", "crash"))
    contacts = mail.audience(host)
    with mail.ledger(host) as db:
        _, digest = mail.selection(db, contacts)

    def confirm():
        with mail.ledger(host) as db:
            try:
                mail.queue(db, contacts, digest)
            except Conflict:
                return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: confirm(), range(2))) == [False, True]
    with mail.ledger(host) as db:
        db.execute("UPDATE deliveries SET status='sending', updated=0 WHERE email='crash@example.test'")

    def transport(address, *args, **kwargs):
        return {"ok": address.startswith("ok"), "status_code": 400 if address.startswith("declined") else None}

    sender.side_effect = transport
    with host.app.app_context():
        mail.process_queue(host)
    assert sender.call_count == 3
    with mail.ledger(host) as db:
        assert mail.progress(db)["counts"] == {"accepted": 1, "failed": 1, "uncertain": 2}
        assert set(mail.selection(db, contacts)[0]) == {"declined@example.test"}


def test_authentication_and_read_only_role(setup):
    _, sender, client = setup
    endpoint = "/admin/afc/formations-2027/envoyer"
    with client.session_transaction() as session:
        session["admin_role"] = "viewer"
    assert client.post(endpoint).status_code == 403
    with client.session_transaction() as session:
        session.clear()
    assert client.post(endpoint).status_code == 302
    assert client.get("/api/admin/afc/formations-2027/suivi").status_code == 401
    sender.assert_not_called()
