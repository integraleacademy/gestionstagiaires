from concurrent.futures import ThreadPoolExecutor
import json
import re
import sqlite3
from pathlib import Path
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
    assert "Bonjour," in args[2] and "<Luc>" not in args[2]
    for message in (args[2], kwargs["text_content"]):
        passages = ("par manque de places disponibles", "financée par France Travail du mois de novembre 2026",
                    "En raison des restrictions budgétaires", "Nous avons deux solutions",
                    "Option 1", "Comment financer l’APS ?", "Option 2", "Ce parcours d’un an est réservé aux moins de 29 ans.",
                    "rendez-vous téléphonique APS avec Cassandre", "Bien cordialement,")
        offsets = [message.index(passage) for passage in passages]
        assert offsets == sorted(offsets)
        assert message.count(host.EDOF_TRAININGS["APS"]["calendly"]) == 1
    assert "Du 4 au 14 janvier 2027" in kwargs["text_content"]
    assert "moins de 29 ans" in args[2] and "26 ans" not in args[2]
    assert "9 février 2027" in args[2] and "1 700 €" in args[2]
    assert kwargs["reply_to"] == mail.CONTACT
    assert host.EDOF_TRAININGS["APS"]["calendly"] in args[2] and host.EDOF_TRAININGS["APS"]["calendly"] in kwargs["text_content"]
    assert "Aurélie" not in args[2] and "aurelie@" not in kwargs["text_content"]
    assert all(f"{n}. {title}" in kwargs["text_content"] for n, title in enumerate(
        (mail.DEFAULT_COPY["cpf_title"], mail.DEFAULT_COPY["employer_title"], mail.DEFAULT_COPY["personal_title"]), 1))
    assert "data-copy" not in args[2]
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
    assert client.post("/admin/afc/formations-2027/texte").status_code == 403
    assert "Modifier le texte" not in client.get("/admin/afc/formations-2027").get_data(as_text=True)
    with client.session_transaction() as session:
        session.clear()
    assert client.post(endpoint).status_code == 302
    assert client.get("/api/admin/afc/formations-2027/suivi").status_code == 401
    sender.assert_not_called()


def test_edit_save_preview_and_version_sent(setup):
    people, sender, client = setup
    people.append(candidate("luc", prenom="Luc"))
    path = "/admin/afc/formations-2027"
    preview = client.get(path).get_data(as_text=True)
    assert "Modifier le texte" in preview
    with client.session_transaction() as session:
        csrf = session["manuals_csrf"]
    with mail.ledger(host) as db:
        first_version, _ = mail.draft(db)
        first_digest = mail.selection(db, mail.audience(host))[1]
    text = {**mail.DEFAULT_COPY, "subject": "Notre rendez-vous APS",
            "intro": "Préparez votre appel\navec <Cassandre>.", "greeting": "Bienvenue {prenom} !"}
    edit = {"csrf_token": csrf, "version": first_version, "fields": json.dumps(text)}
    assert client.post(path + "/texte", data={**edit, "csrf_token": ""}).status_code == 400
    assert client.post(path + "/texte", data={**edit, "fields": json.dumps({**text, "booking_label": ""})}).status_code == 400
    assert client.post(path + "/texte", data=edit).json == {"ok": True}
    assert client.post(path + "/texte", data=edit).status_code == 409
    assert client.post(path + "/envoyer", data={"csrf_token": csrf, "audience": first_digest}).status_code == 409
    assert "Notre rendez-vous APS" in client.get(path).get_data(as_text=True)
    with mail.ledger(host) as db:
        second_version, _ = mail.draft(db)
        _, digest = mail.selection(db, mail.audience(host))
    assert client.post(path + "/envoyer", data={"csrf_token": csrf, "audience": digest}).status_code == 303
    third = {**text, "subject": "Pour les prochains destinataires"}
    assert client.post(path + "/texte", data={**edit, "version": second_version, "fields": json.dumps(third)}).status_code == 200
    sender.assert_not_called()
    with host.app.app_context():
        mail.process_queue(host)
        rendered, plain = mail.render_message(host, text, "Luc", preview=True)
        editable = set(re.findall('data-copy="([a-z0-9_]+)"', rendered))
        assert editable | {"subject", "preheader"} == text.keys()
        assert "avec <Cassandre>." in plain
    args, kwargs = sender.call_args
    assert args[1] == text["subject"]
    assert "Bienvenue Luc !" in args[2] and "avec &lt;Cassandre&gt;." in args[2]
    assert text["intro"] in kwargs["text_content"]
    assert "data-copy" not in args[2]
    assert "{prenom}" not in args[2]


def test_pending_delivery_from_before_editor_keeps_its_approved_message(setup):
    people, sender, _ = setup
    person = candidate("legacy")
    people.append(person)
    # The original campaign schema has no version or draft tables.
    path = Path(host.PERSIST_DIR) / "afc_formations_janvier_2027.sqlite3"
    with sqlite3.connect(path) as old_db:
        old_db.execute("""CREATE TABLE deliveries (email TEXT PRIMARY KEY, candidate TEXT NOT NULL,
            status TEXT NOT NULL, error TEXT DEFAULT '', message_id TEXT DEFAULT '', updated INTEGER DEFAULT 0)""")
        old_db.execute("INSERT INTO deliveries(email,candidate,status) VALUES (?,?,'pending')", (person["email"], person["id"]))
    old_db.close()
    with host.app.app_context():
        mail.process_queue(host)
    args, _ = sender.call_args
    assert args[1] == mail.LEGACY_SUBJECT and "aurelie@" in args[2]


def test_publication_keeps_queued_versions_and_subsequent_edits(setup):
    people, sender, _ = setup
    people.append(candidate("ancienne"))
    old_fields = {**mail.DEFAULT_COPY, "subject": "Objet précédemment confirmé",
                  "eyebrow": "Côte d’Azur", "heading": "Ancien bandeau", "subtitle": "Janvier",
                  "booking_label": "Ancien rendez-vous", "closing": "Ancienne conclusion"}
    old_fields.pop("choices")
    path = Path(host.PERSIST_DIR) / "afc_formations_janvier_2027.sqlite3"
    with sqlite3.connect(path) as old_db:
        old_db.execute("CREATE TABLE mail_versions(version INTEGER PRIMARY KEY, fields TEXT NOT NULL)")
        old_db.execute("CREATE TABLE delivery_versions(email TEXT PRIMARY KEY, version INTEGER NOT NULL)")
        old_db.execute("CREATE TABLE deliveries(email TEXT PRIMARY KEY, candidate TEXT, status TEXT, "
                       "error TEXT, message_id TEXT, updated INTEGER DEFAULT 0)")
        old_db.execute("INSERT INTO mail_versions VALUES (2, ?)", (json.dumps(old_fields),))
        old_db.execute("INSERT INTO delivery_versions VALUES ('ancienne@example.test', 2)")
        old_db.execute("INSERT INTO deliveries(email,candidate,status) VALUES ('ancienne@example.test','ancienne','pending')")
    old_db.close()

    def open_campaign():
        with mail.ledger(host) as db:
            return mail.draft(db)

    with ThreadPoolExecutor(max_workers=3) as executor:
        revisions = list(executor.map(lambda _: open_campaign(), range(3)))
    assert all(revision == (3, mail.DEFAULT_COPY) for revision in revisions)
    with mail.ledger(host) as db:
        assert db.execute("SELECT count(*) FROM mail_versions").fetchone()[0] == 2
        updated = {**mail.DEFAULT_COPY, "subject": "Correction de l’équipe"}
        db.execute("INSERT INTO mail_versions(fields) VALUES (?)", (json.dumps(updated),))
    assert open_campaign() == (4, updated)
    sender.assert_not_called()

    with host.app.app_context():
        mail.process_queue(host)
    args, kwargs = sender.call_args
    assert args[1] == old_fields["subject"]
    assert "Ancien bandeau" in args[2]
    assert kwargs["text_content"].index("Ancien rendez-vous") < kwargs["text_content"].index(old_fields["apprentice_title"])
