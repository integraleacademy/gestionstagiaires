"""Manually reviewed AFC follow-up for the January 2027 intake."""
import hashlib
import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from flask import abort, jsonify, redirect, render_template, request, url_for

from afc_import import normalize_ft_id
from partner_campaigns import valid_email


SUBJECT = "Votre candidature AFC · Deux parcours en sécurité pour janvier 2027"
CONTACT = {"email": "cassandre@integraleacademy.com", "name": "Cassandre Ménard"}
LABELS = {
    "accepted": "Acceptés par Brevo", "pending": "En attente d’envoi",
    "sending": "En cours d’envoi", "failed": "Échecs confirmés",
    "uncertain": "À vérifier dans Brevo", "skipped": "Écartés avant l’envoi",
}
_worker_lock = threading.Lock()


@contextmanager
def ledger(host):
    path = Path(host.PERSIST_DIR) / "afc_formations_janvier_2027.sqlite3"
    with closing(sqlite3.connect(path, timeout=15)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
            email TEXT PRIMARY KEY, candidate TEXT NOT NULL, status TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '', message_id TEXT NOT NULL DEFAULT '',
            updated INTEGER NOT NULL DEFAULT (unixepoch()))""")
        yield db


def audience(host):
    candidates = (host.load_data().get("afc") or {}).get("candidates", [])
    rows, excluded_addresses, excluded_ids = [], set(), set()
    for person in candidates:
        if not isinstance(person, dict) or person.get("archived"):
            continue
        email = valid_email(person.get("email"))
        ft_id = normalize_ft_id(person.get("identifiant_ft"))[0]
        decision = host._normalize_afc_cnaps_status(person.get("decision"))
        cnaps = host._normalize_afc_cnaps_status(person.get("cnaps_status"))
        if decision in {"RETENU", "RETENUE"} or "REFUS" in cnaps:
            if ft_id:
                excluded_ids.add(ft_id)
            excluded_addresses.add(email)
        elif person.get("id") and email and not host._is_blocked_email_recipient(email):
            rows.append((email, ft_id, person))
    contacts = {}
    for email, ft_id, person in rows:
        if email not in excluded_addresses and ft_id not in excluded_ids and email not in contacts:
            contacts[email] = person
            if ft_id:
                excluded_ids.add(ft_id)
    return contacts


def selection(db, contacts):
    rows = db.execute("SELECT email,candidate FROM deliveries WHERE status NOT IN ('failed','skipped')").fetchall()
    attempted, candidates = {r["email"] for r in rows}, {r["candidate"] for r in rows}
    remaining = {email: contacts[email] for email in sorted(contacts.keys() - attempted)
                 if contacts[email]["id"] not in candidates}
    # The submitted preview must still describe the exact same people and addresses.
    pairs = [(email, person["id"]) for email, person in remaining.items()]
    digest = hashlib.sha256(json.dumps(pairs, ensure_ascii=False).encode()).hexdigest()
    return remaining, digest


def progress(db):
    counts = {row[0]: row[1] for row in db.execute(
        "SELECT status, count(*) FROM deliveries GROUP BY status")}
    return {"counts": counts, "active": bool(counts.get("pending") or counts.get("sending"))}


def queue(db, contacts, preview):
    db.execute("BEGIN IMMEDIATE")
    remaining, digest = selection(db, contacts)
    if not remaining or preview != digest:
        abort(409, "La liste des destinataires a changé. Rouvrez l’aperçu avant de confirmer.")
    db.executemany("""INSERT INTO deliveries(email, candidate, status) VALUES (?, ?, 'pending')
        ON CONFLICT(email) DO UPDATE SET candidate=excluded.candidate, status='pending',
            error='', updated=unixepoch() WHERE deliveries.status IN ('failed','skipped')""",
        ((email, person["id"]) for email, person in remaining.items()))


def deliver_one(host, db, contacts):
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM deliveries WHERE status='pending' ORDER BY email LIMIT 1").fetchone()
        if not row:
            return False
        email = row["email"]
        person = contacts.get(email)
        if not person or person["id"] != row["candidate"]:
            db.execute("UPDATE deliveries SET status='skipped', updated=unixepoch() WHERE email=?", (email,))
            return True
        db.execute("UPDATE deliveries SET status='sending', updated=unixepoch() WHERE email=?", (email,))

    try:
        kwargs = {"first_name": str(person.get("prenom") or "").strip(), "subject": SUBJECT}
        body = host.app.jinja_env.get_template("emails/afc_formations_2027.html").render(**kwargs)
        plain = host.app.jinja_env.get_template("emails/afc_formations_2027.txt").render(**kwargs)
    except Exception:
        # No external request has been made if the template could not be rendered.
        result = {"not_sent": True, "error": "Le message n’a pas pu être préparé."}
    else:
        try:
            result = host.brevo_send_email(email, SUBJECT, body, text_content=plain, reply_to=CONTACT,
                metadata={"purpose": "afc_formations_2027", "idempotency_key":
                          str(uuid5(NAMESPACE_URL, f"afc-janvier-2027/{email}"))})
        except Exception:
            result = {"error": "Aucune confirmation du service d’envoi."}
    if result.get("ok"):
        status = "accepted"
    elif result.get("not_sent") or 400 <= (result.get("status_code") or 0) < 500:
        status = "failed"
    else:
        status = "uncertain"
    with db:
        db.execute("UPDATE deliveries SET status=?, error=?, message_id=?, updated=unixepoch() WHERE email=?",
                   (status, (result.get("error") or "")[:350], result.get("message_id") or "", email))
    return True


def process_queue(host, stop=None):
    with ledger(host) as db:
        # After a lost process, an in-flight call may already have reached Brevo.
        with db:
            db.execute("""UPDATE deliveries SET status='uncertain', error='Envoi interrompu.'
                WHERE status='sending' AND updated < unixepoch()-180""")
        if not db.execute("SELECT 1 FROM deliveries WHERE status='pending' LIMIT 1").fetchone():
            return
        version, contacts = None, {}
        while stop is None or not stop.is_set():
            # Keep just the current AFC contacts and reload after any canonical data change.
            info = Path(host.DATA_FILE).stat()
            current_version = (info.st_ino, info.st_mtime_ns, info.st_size)
            if current_version != version:
                fresh = audience(host)
                verified = Path(host.DATA_FILE).stat()
                if (verified.st_ino, verified.st_mtime_ns, verified.st_size) != current_version:
                    continue
                contacts, version = fresh, current_version
            if not deliver_one(host, db, contacts):
                return


def start_worker(host):
    """Resume only deliveries already confirmed, including after a deployment."""
    with _worker_lock:
        state = host.app.extensions.get("afc_training_mail_worker")
        if state:
            state["wake"].set()
            return
        if not (Path(host.PERSIST_DIR) / "afc_formations_janvier_2027.sqlite3").is_file():
            return
        with ledger(host) as db:
            if not progress(db)["active"]:
                return
        stop, wake = threading.Event(), threading.Event()

        def run():
            while not stop.is_set():
                wake.clear()
                try:
                    with host.app.app_context():
                        process_queue(host, stop)
                except Exception:
                    host.app.logger.exception("AFC training mail worker interrupted")
                wake.wait(45)

        thread = threading.Thread(target=run, name="afc-training-mail", daemon=True)
        host.app.extensions["afc_training_mail_worker"] = {"thread": thread, "wake": wake, "stop": stop}
        thread.start()


def register(host):
    @host.app.get("/admin/afc/formations-2027")
    @host.admin_login_required
    def admin_afc_training_mail():
        with ledger(host) as db:
            remaining, digest = selection(db, audience(host))
            report = progress(db)
            issues = db.execute("""SELECT email, status, error FROM deliveries
                WHERE status IN ('failed','uncertain') ORDER BY email""").fetchall()
        response = host.make_response(render_template("admin_afc_training_mail.html",
            recipients=remaining, digest=digest, report=report, issues=issues, labels=LABELS,
            subject=SUBJECT, csrf=host.manuals_shop.csrf_token(),
            message=host.app.jinja_env.get_template("emails/afc_formations_2027.html").render(
                first_name="", subject=SUBJECT)))
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @host.app.get("/api/admin/afc/formations-2027/suivi")
    @host.admin_login_required
    def api_afc_training_mail_status():
        with ledger(host) as db:
            response = jsonify(progress(db))
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @host.app.post("/admin/afc/formations-2027/envoyer")
    @host.admin_login_required
    @host.admin_write_required
    def admin_afc_training_mail_send():
        host.manuals_shop.check_csrf()
        contacts = audience(host)
        with ledger(host) as db:
            queue(db, contacts, request.form.get("audience"))
        start_worker(host)
        return redirect(url_for("admin_afc_training_mail"), code=303)
