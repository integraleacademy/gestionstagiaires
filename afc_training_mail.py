"""Manually reviewed AFC follow-up for the January 2027 intake."""
import hashlib
import json
import re
import sqlite3
import threading
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from flask import abort, flash, jsonify, redirect, render_template, request, url_for

from afc_import import normalize_ft_id
from partner_campaigns import valid_email


# Deliveries from before the editor retain the subject approved at the time.
LEGACY_SUBJECT = "Votre candidature AFC · Deux parcours en sécurité pour janvier 2027"
SUBJECT = "Suite à votre candidature pour devenir agent de sécurité privé"
CONTACT = {"email": "cassandre@integraleacademy.com", "name": "Cassandre Ménard"}
DEFAULT_COPY = {
    "subject": SUBJECT,
    "preheader": "Le point sur le financement de la formation par France Travail en 2027.",
    "greeting": "Bonjour,",
    "intro": "Je me permets de revenir vers vous concernant la formation agent de sécurité privée (APS) et agent de sécurité incendie (SSIAP 1). Malheureusement, par manque de places disponibles, vous n'avez pas pu intégrer la formation financée par France Travail du mois de novembre 2026.",
    "collective": "En raison des restrictions budgétaires, France Travail ne financera pas de nouvelle session collective de cette formation chez Intégrale Academy en 2027.",
    "transition": "Nous avons deux solutions à vous proposer pour poursuivre votre projet à Puget-sur-Argens dès janvier 2027.",
    "choices": "Vous pouvez suivre notre formation APS de 175 heures ou, si vous avez moins de 29 ans, choisir le parcours sécurité en alternance pendant un an.",
    "aps_kicker": "Option 1",
    "aps_title": "La formation APS de 175 heures",
    "aps_description": "Vous préparez le titre d’agent de prévention et de sécurité. Vous apprenez à contrôler les accès, à effectuer des rondes et à intervenir en cas d’incident.",
    "remote_label": "À distance",
    "remote_dates": "Du 4 au 14 janvier 2027",
    "onsite_label": "À Puget-sur-Argens",
    "onsite_dates": "Du 15 janvier au 8 février 2027",
    "exam_label": "Examen",
    "exam_date": "Le 9 février 2027",
    "funding_title": "Comment financer l’APS ?",
    "cpf_title": "Votre compte personnel de formation (CPF)",
    "cpf_text": "Vous pouvez utiliser vos droits CPF pour couvrir tout ou partie du coût de la formation.",
    "employer_title": "Une promesse d’embauche",
    "employer_text": "Si une entreprise souhaite vous embaucher à l’issue de la formation, nous pouvons étudier avec elle et votre conseiller France Travail un financement individuel avant l’embauche (POEI). L’accord de France Travail est nécessaire avant le début des cours.",
    "personal_title": "Un financement personnel",
    "personal_text": "Le tarif est de 1 700 € TTC. Si vous souhaitez financer vous-même la formation, je peux vous envoyer un devis et vous préciser les modalités de règlement.",
    "apprentice_kicker": "Option 2",
    "apprentice_title": "Le parcours sécurité en alternance",
    "apprentice_age": "Ce parcours d’un an est réservé aux moins de 29 ans.",
    "apprentice_description": "De janvier à décembre 2027, vous alternez les cours à Puget-sur-Argens et le travail en entreprise. Vous préparez trois qualifications au cours de l’année.",
    "qualification_aps": "Agent de prévention et de sécurité (APS)",
    "qualification_a3p": "Agent de protection physique des personnes (A3P, protection rapprochée)",
    "qualification_ssiap": "Agent de sécurité incendie et d’assistance à personnes (SSIAP 1)",
    "contract": "Avec un contrat d’apprentissage, vous percevez un salaire et vos frais de formation sont pris en charge.",
    "booking_intro": "Pour échanger sur la formation APS, son financement ou le parcours en alternance, je vous propose un rendez-vous téléphonique. Choisissez le créneau qui vous convient et je vous appellerai au numéro indiqué lors de la réservation.",
    "booking_label": "Réserver un rendez-vous téléphonique APS avec Cassandre",
    "closing": "Bien cordialement,"
}
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
        db.execute("""CREATE TABLE IF NOT EXISTS mail_versions (
            version INTEGER PRIMARY KEY, fields TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS delivery_versions (
            email TEXT PRIMARY KEY, version INTEGER NOT NULL REFERENCES mail_versions(version))""")
        publish_reviewed_copy(db)
        yield db


def publish_reviewed_copy(db):
    # Append one revision so previously queued deliveries retain their original fields.
    # user_version belongs to this campaign's dedicated SQLite file.
    if db.execute("PRAGMA user_version").fetchone()[0] >= 1:
        return
    db.execute("BEGIN IMMEDIATE")
    if db.execute("PRAGMA user_version").fetchone()[0] == 0:
        db.execute("INSERT INTO mail_versions(fields) VALUES (?)",
                   (json.dumps(DEFAULT_COPY, ensure_ascii=False),))
        db.execute("PRAGMA user_version = 1")
    db.commit()


def draft(db):
    row = db.execute("SELECT version, fields FROM mail_versions ORDER BY version DESC LIMIT 1").fetchone()
    return row["version"], json.loads(row["fields"])


def render_message(host, fields, first_name="", *, preview=False):
    greeting = fields["greeting"]
    if "{prenom}" in greeting:
        greeting = greeting.replace("{prenom}", first_name) if first_name else re.sub(r"[ \t]*\{prenom\}", "", greeting)
    context = dict(words=fields, greeting=greeting, preview=preview,
                   booking_url=host.EDOF_TRAININGS["APS"]["calendly"])
    templates = host.app.jinja_env
    # Only pre-publication snapshots carry the editable hero heading.
    name = "afc_training_message" if "heading" in fields else "afc_training_reviewed"
    return (templates.get_template(f"emails/{name}.html").render(**context),
            templates.get_template(f"emails/{name}.txt").render(**context))


def edited_fields(raw):
    if not isinstance(raw, dict) or raw.keys() != DEFAULT_COPY.keys():
        raise ValueError("Le contenu du message est incomplet. Rouvrez l’éditeur.")
    fields = {}
    for key, value in raw.items():
        if not isinstance(value, str) or len(value) > 6000:
            raise ValueError("Un passage est trop long. Chaque texte peut contenir jusqu’à 6 000 caractères.")
        fields[key] = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    subject = fields["subject"]
    if not subject or len(subject) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in subject):
        raise ValueError("Saisissez un objet sur une seule ligne, de 1 à 200 caractères.")
    if not fields["booking_label"]:
        raise ValueError("Saisissez le texte du bouton de réservation.")
    return fields


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
    version, _ = draft(db)
    digest = hashlib.sha256(json.dumps([version, pairs], ensure_ascii=False).encode()).hexdigest()
    return remaining, digest


def progress(db):
    counts = {row[0]: row[1] for row in db.execute(
        "SELECT status, count(*) FROM deliveries GROUP BY status")}
    return {"counts": counts, "active": bool(counts.get("pending") or counts.get("sending"))}


def queue(db, contacts, preview):
    db.execute("BEGIN IMMEDIATE")
    remaining, digest = selection(db, contacts)
    if not remaining or preview != digest:
        abort(409, "Le texte du mail ou la liste des destinataires a changé. Rouvrez l’aperçu avant de confirmer.")
    version, _ = draft(db)
    db.executemany("""INSERT INTO deliveries(email, candidate, status) VALUES (?, ?, 'pending')
        ON CONFLICT(email) DO UPDATE SET candidate=excluded.candidate, status='pending',
            error='', updated=unixepoch() WHERE deliveries.status IN ('failed','skipped')""",
        ((email, person["id"]) for email, person in remaining.items()))
    db.executemany("""INSERT INTO delivery_versions(email, version) VALUES (?, ?)
        ON CONFLICT(email) DO UPDATE SET version=excluded.version""", ((email, version) for email in remaining))


def deliver_one(host, db, contacts):
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT d.*, v.fields FROM deliveries d
            LEFT JOIN delivery_versions dv ON dv.email=d.email
            LEFT JOIN mail_versions v ON v.version=dv.version
            WHERE d.status='pending' ORDER BY d.email LIMIT 1""").fetchone()
        if not row:
            return False
        email = row["email"]
        person = contacts.get(email)
        if not person or person["id"] != row["candidate"]:
            db.execute("UPDATE deliveries SET status='skipped', updated=unixepoch() WHERE email=?", (email,))
            return True
        db.execute("UPDATE deliveries SET status='sending', updated=unixepoch() WHERE email=?", (email,))

    try:
        first_name = str(person.get("prenom") or "").strip()
        if row["fields"] is not None:
            fields = json.loads(row["fields"])
            subject = fields["subject"]
            body, plain = render_message(host, fields, first_name)
        else:
            # Only pre-editor deliveries can be unversioned. Honour their approved message.
            subject = LEGACY_SUBJECT
            kwargs = {"first_name": first_name, "subject": subject}
            body = host.app.jinja_env.get_template("emails/afc_formations_2027.html").render(**kwargs)
            plain = host.app.jinja_env.get_template("emails/afc_formations_2027.txt").render(**kwargs)
    except Exception:
        # No external request has been made if the template could not be rendered.
        result = {"not_sent": True, "error": "Le message n’a pas pu être préparé."}
    else:
        try:
            result = host.brevo_send_email(email, subject, body, text_content=plain, reply_to=CONTACT,
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
    host.PARTNER_SPACE_FORBIDDEN_ENDPOINTS.add("admin_afc_training_mail_edit")
    @host.app.get("/admin/afc/formations-2027")
    @host.admin_login_required
    def admin_afc_training_mail():
        contacts = audience(host)
        with ledger(host) as db:
            db.execute("BEGIN")
            remaining, digest = selection(db, contacts)
            version, fields = draft(db)
            report = progress(db)
            issues = db.execute("""SELECT email, status, error FROM deliveries
                WHERE status IN ('failed','uncertain') ORDER BY email""").fetchall()
        response = host.make_response(render_template("admin_afc_training_mail.html",
            recipients=remaining, digest=digest, report=report, issues=issues, labels=LABELS,
            subject=fields["subject"], csrf=host.manuals_shop.csrf_token(), fields=fields, version=version,
            message=render_message(host, fields, preview=True)[0]))
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @host.app.post("/admin/afc/formations-2027/texte")
    @host.admin_login_required
    @host.admin_write_required
    def admin_afc_training_mail_edit():
        host.manuals_shop.check_csrf()
        try:
            raw = json.loads(request.form.get("fields", ""))
            fields = edited_fields(raw)
        except json.JSONDecodeError:
            return jsonify(error="Le texte du mail est illisible."), 400
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        with ledger(host) as db:
            db.execute("BEGIN IMMEDIATE")
            version, current = draft(db)
            if request.form.get("version", type=int) != version:
                return jsonify(error="Une autre modification a été enregistrée. Copiez vos changements puis rechargez l’aperçu."), 409
            if fields != current:
                db.execute("INSERT INTO mail_versions(fields) VALUES (?)", (json.dumps(fields, ensure_ascii=False),))
        flash("Le texte de l’e-mail a été enregistré.", "success")
        return jsonify(ok=True)

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
