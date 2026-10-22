"""Platform-only e-learning outreach: reviewed imports and explicit, resumable sends.

Separate SQLite storage on the existing persistent volume keeps prospects out of
partner authentication and billing. No email is sent by imports, reads or deploys.
"""
import csv
import io
import json
import re
import secrets
import sqlite3
import time
import unicodedata
import uuid
from contextlib import contextmanager
from email.utils import parseaddr
from functools import wraps
from pathlib import Path

from flask import abort, flash, jsonify, make_response, redirect, render_template, request, url_for

MAX_BYTES = 2 * 1024 * 1024
MAX_CONTACTS = 5000
CONTACTED_SQL = "EXISTS (SELECT 1 FROM outreach_deliveries d WHERE d.contact_id=c.id AND d.status IN ('sent','sending','uncertain'))"
PREVIOUS_TEMPLATE_COPY = {
    "subject": "Un espace e-learning pour chacun de vos stagiaires — APS & A3P",
    "intro": "Et si vos prochaines sessions commençaient avec un e-learning déjà prêt ? Nous-mêmes centre de formation, nous avons conçu des parcours concrets pour vos stagiaires et un suivi précis pour votre équipe.",
}
DEFAULT_TEMPLATE = {
    "subject": "E-learning APS & A3P : créez les accès de vos stagiaires en toute autonomie",
    "intro": "Vous formez aux métiers de la sécurité privée ? Nous aussi. Avec Intégrale Connect, proposez à vos stagiaires nos parcours e-learning APS et A3P, conçus par un centre de formation pour les centres de formation. Créez leurs accès en totale autonomie sur integraleconnect.com et suivez leur progression depuis votre espace organisme.",
    "aps_price": "59", "a3p_price": "89",
}
LABELS = {"pending": "À envoyer", "sending": "En cours", "sent": "Accepté par Brevo", "failed": "Échec", "uncertain": "À vérifier", "skipped": "Exclu (désinscrit ou bloqué)"}


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db(host, write=False):
    path = Path(host.PERSIST_DIR) / "partner_campaigns.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS outreach_contacts (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            centre TEXT NOT NULL DEFAULT '', batch_id TEXT NOT NULL,
            created_at TEXT NOT NULL, unsubscribed_at TEXT NOT NULL DEFAULT '',
            unsubscribe_token TEXT UNIQUE NOT NULL);
          CREATE TABLE IF NOT EXISTS outreach_imports (
            id TEXT PRIMARY KEY, label TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS outreach_settings (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS outreach_campaigns (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, template TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL,
            request_key TEXT UNIQUE NOT NULL);
          CREATE TABLE IF NOT EXISTS outreach_deliveries (
            campaign_id TEXT NOT NULL REFERENCES outreach_campaigns(id),
            contact_id TEXT NOT NULL REFERENCES outreach_contacts(id),
            status TEXT NOT NULL DEFAULT 'pending', started REAL, sent_at TEXT NOT NULL DEFAULT '',
            message_id TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
            attempt INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(campaign_id, contact_id));
          CREATE INDEX IF NOT EXISTS outreach_pending ON outreach_deliveries(campaign_id, status);
          CREATE INDEX IF NOT EXISTS outreach_contacted ON outreach_deliveries(contact_id, status);
        """)
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def valid_email(value):
    value = str(value or "").strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return ""
    _, address = parseaddr(value)
    address = address.lower()
    if len(address) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", address):
        return ""
    local = address.split("@", 1)[0]
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        return ""
    if value.lower() != address and not re.fullmatch(r'[^<>]*<[^<>]+>', value):
        return ""
    return address


def header(value):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode())


def parse_import(content, filename="contacts.txt"):
    if len(content) > MAX_BYTES:
        raise ValueError("Le fichier doit faire moins de 2 Mo.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")
    if "\x00" in text:
        raise ValueError("Utilisez un fichier CSV ou TXT. Dans Excel, choisissez Enregistrer sous → CSV UTF-8.")
    if filename.lower().endswith(".csv") or "\t" in text:
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
            rows = list(csv.reader(io.StringIO(text), dialect))
        except csv.Error:
            rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    else:
        rows = [[part.strip()] for part in re.split(r"[\r\n;,]+", text) if part.strip()]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) > MAX_CONTACTS + 1:
        raise ValueError("Importez au maximum 5 000 lignes à la fois.")
    if not rows:
        raise ValueError("Ajoutez un fichier ou collez des adresses e-mail.")
    headers = [header(c) for c in rows[0]]
    email_columns = [i for i, h in enumerate(headers) if h in {"email", "emails", "mail", "courriel", "adressemail", "adresseemail", "emailaddress"}]
    name_column = next((i for i, h in enumerate(headers) if h in {"centre", "organisme", "nom", "entreprise", "raisonsociale", "nomducentre"}), None)
    first_line = 2 if email_columns else 1
    if email_columns:
        rows = rows[1:]
    contacts, invalid, seen, duplicate_count = [], [], set(), 0
    for line, row in enumerate(rows, first_line):
        cells = [row[i] if i < len(row) else "" for i in email_columns] if email_columns else row
        candidates = [c for c in cells if "@" in c] or cells[:1]
        for raw in candidates:
            email = valid_email(raw)
            if not email:
                invalid.append({"line": line, "value": raw[:160]})
                continue
            if email in seen:
                duplicate_count += 1
                continue
            seen.add(email)
            centre = row[name_column].strip()[:200] if name_column is not None and name_column < len(row) else ""
            contacts.append({"email": email, "centre": centre})
    if len(contacts) > MAX_CONTACTS:
        raise ValueError("Importez au maximum 5 000 adresses à la fois.")
    return {"contacts": contacts, "invalid": invalid, "duplicates": duplicate_count}


def template_from(form):
    result = {}
    for field, limit in (("subject", 180), ("intro", 1400)):
        value = str(form.get(field) or "").strip()
        if not value or len(value) > limit or (field == "subject" and any(c in value for c in "\r\n")):
            raise ValueError("Renseignez un objet (180 caractères maximum) et une introduction (1 400 caractères maximum).")
        result[field] = value
    for field in ("aps_price", "a3p_price"):
        price = str(form.get(field) or "").strip().replace(",", ".")
        if not re.fullmatch(r"\d{1,4}(?:\.\d{1,2})?", price) or float(price) <= 0:
            raise ValueError("Renseignez des tarifs TTC valides.")
        result[field] = price.replace(".", ",")
    return result


def saved_template(conn):
    row = conn.execute("SELECT payload FROM outreach_settings WHERE id=1").fetchone()
    template = {**DEFAULT_TEMPLATE, **(json.loads(row[0]) if row else {})}
    # Refresh untouched defaults while preserving the centre's own copy and prices.
    for field, previous in PREVIOUS_TEMPLATE_COPY.items():
        if template[field] == previous:
            template[field] = DEFAULT_TEMPLATE[field]
    return template


def mail_content(host, template, contact=None, test=False):
    base = host._public_base_url().rstrip("/")
    if not base.startswith("https://"):
        base = "https://gestionstagiaires-r5no.onrender.com"
    unsubscribe = base + "/communications/desinscription/" + contact["unsubscribe_token"] if contact else ""
    demo_url = "https://integraleconnect.com"
    presentation_url = demo_url + "/e-learning"
    body = render_template("emails/partner_elearning.html", offer=template, contact=contact,
                           base=base, demo_url=demo_url, presentation_url=presentation_url,
                           unsubscribe_url=unsubscribe, test=test)
    text = (f"INTÉGRALE ACADEMY — E-LEARNING APS & A3P\n"
            "Pour les centres de formation aux métiers de la sécurité.\n\n"
            f"{template['intro']}\n\n"
            "CRÉEZ VOS ACCÈS E-LEARNING EN TOTALE AUTONOMIE\n"
            f"Tout se passe sur {demo_url}, depuis votre espace organisme :\n"
            "1. Créez votre compte centre sur Intégrale Connect.\n"
            "2. Choisissez le parcours APS ou A3P, ajoutez vos stagiaires et validez votre commande.\n"
            "3. Après confirmation du paiement, envoyez vous-même les accès à la date de votre choix. "
            "Chaque stagiaire reçoit son lien personnel par e-mail.\n\n"
            "Un espace individuel pour vos stagiaires : cours, activités et évaluations.\n"
            "Un suivi pour votre équipe : temps actif par module, progression et justificatifs.\n\n"
            f"APS : {template['aps_price']} € TTC par stagiaire — parcours de 62 h.\n"
            f"A3P : {template['a3p_price']} € TTC par stagiaire — parcours de 157 h 30.\n"
            "Séquences à distance selon le référentiel applicable. APS ADEF : 50 h 30 éligibles ; "
            "parcours à adapter au certificateur. A3P : éligibilité au distanciel à valider avec votre certificateur.\n\n"
            f"Découvrez les parcours : {presentation_url}\n"
            f"Demander une démonstration : {demo_url}\n\n"
            "Clément VAILLANT\nDirecteur général Intégrale Academy – Président Intégrale Group\n"
            "clement@integraleacademy.com — 04 22 47 07 68\n")
    if unsubscribe:
        text += "\nNe plus recevoir ces présentations : " + unsubscribe
    return body, text


def campaign_view(conn, campaign_id):
    row = conn.execute("SELECT * FROM outreach_campaigns WHERE id=?", (campaign_id,)).fetchone()
    if not row:
        abort(404)
    result = dict(row)
    result["template"] = json.loads(row["template"])
    result["counts"] = {r[0]: r[1] for r in conn.execute("SELECT status, count(*) FROM outreach_deliveries WHERE campaign_id=? GROUP BY status", (campaign_id,))}
    result["total"] = sum(result["counts"].values())
    result["remaining"] = result["counts"].get("pending", 0)
    failure = conn.execute("SELECT error FROM outreach_deliveries WHERE campaign_id=? AND status IN ('failed','uncertain') AND error!='' ORDER BY started DESC,contact_id LIMIT 1", (campaign_id,)).fetchone()
    result["last_error"] = failure[0] if failure else ""
    return result


def delivery_idempotency_key(campaign_id, contact_id, attempt):
    # Brevo requires a UUID. Keep it stable for the same delivery attempt.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"outreach-{campaign_id}-{contact_id}-{attempt}"))


def contact_scope(query="", batch=""):
    where, args = "c.unsubscribed_at=''", []
    query, batch = query.strip()[:200], batch.strip()
    if query:
        where += " AND (c.email LIKE ? ESCAPE '\\' OR c.centre LIKE ? ESCAPE '\\')"
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        args += ["%" + escaped + "%"] * 2
    if batch:
        where += " AND c.batch_id=?"
        args.append(batch)
    return where, args


def context(host):
    with db(host) as conn:
        template = saved_template(conn)
        q = (request.args.get("contacts_q") or "").strip()[:200]
        batch = (request.args.get("batch") or "").strip()
        where, args = contact_scope(q, batch)
        count = conn.execute("SELECT count(*) FROM outreach_contacts c WHERE " + where, args).fetchone()[0]
        eligible_count = conn.execute("SELECT count(*) FROM outreach_contacts c WHERE " + where + " AND NOT " + CONTACTED_SQL, args).fetchone()[0]
        page = max(1, request.args.get("contacts_page", 1, type=int))
        contacts = [dict(r) for r in conn.execute("SELECT c.*, " + CONTACTED_SQL + " AS already_contacted, (SELECT max(sent_at) FROM outreach_deliveries d WHERE d.contact_id=c.id AND d.status='sent') AS last_sent FROM outreach_contacts c WHERE " + where + " ORDER BY c.created_at DESC,c.email LIMIT 100 OFFSET ?", args + [(page-1)*100])]
        staged = None
        iid = request.args.get("import", "")
        if iid:
            row = conn.execute("SELECT * FROM outreach_imports WHERE id=? AND created>?", (iid, time.time()-3600)).fetchone()
            if row:
                staged = {**dict(row), **json.loads(row["payload"])}
                known = {r[0] for r in conn.execute("SELECT email FROM outreach_contacts")}
                staged["existing"] = sum(c["email"] in known for c in staged["contacts"])
                staged["new_count"] = len(staged["contacts"]) - staged["existing"]
        campaign = campaign_view(conn, request.args["campaign"]) if request.args.get("campaign") else None
        deliveries = [dict(r) for r in conn.execute("SELECT c.email,c.centre,d.* FROM outreach_deliveries d JOIN outreach_contacts c ON c.id=d.contact_id WHERE d.campaign_id=? ORDER BY c.email LIMIT 100", (campaign["id"],))] if campaign else []
        history = [campaign_view(conn, r[0]) for r in conn.execute("SELECT id FROM outreach_campaigns ORDER BY created_at DESC LIMIT 15")]
        total = conn.execute("SELECT count(*) FROM outreach_contacts WHERE unsubscribed_at=''").fetchone()[0]
    return dict(outreach_template=template, outreach_contacts=contacts, outreach_count=count, outreach_eligible_count=eligible_count,
                outreach_total=total, outreach_page=page, outreach_query=q, outreach_batch=batch,
                outreach_import=staged, outreach_campaign=campaign, outreach_deliveries=deliveries,
                outreach_history=history, outreach_labels=LABELS, outreach_request_key=uuid.uuid4().hex)


def register(host):
    from manuals_shop import check_csrf, SAFE_ENDPOINTS
    SAFE_ENDPOINTS.add("partner_campaign_unsubscribe")

    def admin(fn):
        @host.admin_login_required
        @host.require_super_admin
        @wraps(fn)
        def guarded(*args, **kwargs):
            if host._is_partner_data_scope_session():
                abort(403)
            if request.method == "POST":
                check_csrf()
            return fn(*args, **kwargs)
        return guarded

    def back(**kwargs):
        return redirect(url_for("admin_partners", tab="campaigns", **kwargs), code=303)

    @host.app.post("/admin/partners/campaigns/template")
    @admin
    def partner_campaign_template():
        try:
            template = template_from(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            with db(host, True) as conn:
                conn.execute("INSERT OR REPLACE INTO outreach_settings VALUES (1, ?)", (json.dumps(template),))
            flash("Votre modèle e-learning est enregistré.", "success")
        return back()

    @host.app.route("/admin/partners/campaigns/preview", methods=["GET", "POST"])
    @admin
    def partner_campaign_preview():
        with db(host) as conn:
            if request.args.get("campaign"):
                template = campaign_view(conn, request.args["campaign"])["template"]
            else:
                try:
                    template = template_from(request.form) if request.method == "POST" else saved_template(conn)
                except ValueError as exc:
                    return str(exc), 400
        body, _ = mail_content(host, template)
        response = make_response(body)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'self'"
        return response

    @host.app.post("/admin/partners/campaigns/test")
    @admin
    def partner_campaign_test():
        email = valid_email(request.form.get("test_email"))
        if not email:
            flash("Renseignez une adresse de test valide.", "error")
            return back()
        try:
            template = template_from(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return back()
        with db(host, True) as conn:
            conn.execute("INSERT OR REPLACE INTO outreach_settings VALUES (1, ?)", (json.dumps(template),))
        body, text = mail_content(host, template, test=True)
        result = host.brevo_send_email(email, "[TEST] " + template["subject"], body, text_content=text,
            metadata={"kind": "elearning_campaign_test"}, reply_to={"email": "clement@integraleacademy.com", "name": "Clément VAILLANT"})
        flash("E-mail de test accepté par le service d’envoi." if result.get("ok") else "Le test n’a pas pu être envoyé : " + str(result.get("error") or "Erreur du service d’envoi."), "success" if result.get("ok") else "error")
        return back()

    @host.app.get("/admin/partners/campaigns/import-example.csv")
    @admin
    def partner_campaign_import_example():
        response = make_response("\ufeffemail;centre\ncontact@exemple.fr;Centre Exemple\n")
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = 'attachment; filename="modele_contacts_centres.csv"'
        return response

    @host.app.post("/admin/partners/campaigns/import")
    @admin
    def partner_campaign_import():
        upload = request.files.get("contacts_file")
        try:
            if upload and upload.filename:
                if not upload.filename.lower().endswith((".csv", ".txt")):
                    raise ValueError("Utilisez un fichier CSV ou TXT (export CSV UTF-8 depuis Excel).")
                content, label = upload.stream.read(MAX_BYTES + 1), upload.filename[:180]
            else:
                content, label = request.form.get("contacts_text", "").encode(), "Adresses copiées-collées"
            parsed = parse_import(content, label)
        except (ValueError, UnicodeError, csv.Error) as exc:
            flash(str(exc), "error")
            return back()
        iid = uuid.uuid4().hex
        with db(host, True) as conn:
            conn.execute("DELETE FROM outreach_imports WHERE created<?", (time.time()-3600,))
            conn.execute("INSERT INTO outreach_imports VALUES(?,?,?,?)", (iid, label, json.dumps(parsed), time.time()))
        return back(**{"import": iid})

    @host.app.post("/admin/partners/campaigns/import/<iid>/confirm")
    @admin
    def partner_campaign_import_confirm(iid):
        with db(host, True) as conn:
            row = conn.execute("SELECT * FROM outreach_imports WHERE id=? AND created>?", (iid, time.time()-3600)).fetchone()
            if not row:
                flash("Cet import a déjà été validé ou a expiré.", "error")
                return back()
            parsed, added = json.loads(row["payload"]), 0
            for item in parsed["contacts"]:
                added += conn.execute("INSERT OR IGNORE INTO outreach_contacts(id,email,centre,batch_id,created_at,unsubscribe_token) VALUES(?,?,?,?,?,?)", (uuid.uuid4().hex, item["email"], item["centre"], iid, now(), secrets.token_urlsafe(32))).rowcount
            conn.execute("DELETE FROM outreach_imports WHERE id=?", (iid,))
        flash(f"{added} contact(s) ajouté(s). Les doublons, adresses invalides et contacts désinscrits ne sont pas réimportés. Aucun e-mail n’a été envoyé.", "success")
        return back(batch=iid)

    @host.app.post("/admin/partners/campaigns/contacts/<cid>/exclude")
    @admin
    def partner_campaign_exclude(cid):
        with db(host, True) as conn:
            conn.execute("UPDATE outreach_contacts SET unsubscribed_at=? WHERE id=?", (now(), cid))
        flash("Contact exclu des prochains envois.", "success")
        return back()

    @host.app.post("/admin/partners/campaigns/create")
    @admin
    def partner_campaign_create():
        selection = list(dict.fromkeys(request.form.getlist("contact_id")))
        request_key = request.form.get("request_key", "")
        if not re.fullmatch(r"[0-9a-f]{32}", request_key):
            abort(400)
        with db(host, True) as conn:
            existing = conn.execute("SELECT id FROM outreach_campaigns WHERE request_key=?", (request_key,)).fetchone()
            if existing:
                return back(campaign=existing[0])
            where, args = contact_scope(request.form.get("contacts_q", ""), request.form.get("batch", ""))
            if not request.form.get("include_contacted"):
                where += " AND NOT " + CONTACTED_SQL
            rows = conn.execute("SELECT c.id FROM outreach_contacts c WHERE " + where, args).fetchall()
            if request.form.get("selection") != "all":
                ids = set(selection)
                rows = [r for r in rows if r["id"] in ids]
            if not rows:
                flash("Aucun destinataire éligible dans cette sélection. Les contacts déjà sollicités sont exclus par défaut.", "error")
                return back(contacts_q=request.form.get("contacts_q", ""), batch=request.form.get("batch", ""))
            campaign_id = uuid.uuid4().hex
            template = saved_template(conn)
            name = (request.form.get("name") or "Présentation e-learning APS & A3P").strip()[:180]
            conn.execute("INSERT INTO outreach_campaigns(id,name,template,created_at,request_key) VALUES(?,?,?,?,?)", (campaign_id, name, json.dumps(template), now(), request_key))
            conn.executemany("INSERT INTO outreach_deliveries(campaign_id,contact_id) VALUES(?,?)", [(campaign_id, r["id"]) for r in rows])
        return back(campaign=campaign_id)

    @host.app.get("/admin/partners/campaigns/<campaign_id>/status")
    @admin
    def partner_campaign_status(campaign_id):
        with db(host) as conn:
            view = campaign_view(conn, campaign_id)
        return jsonify(view)

    @host.app.get("/admin/partners/campaigns/<campaign_id>/results.csv")
    @admin
    def partner_campaign_results(campaign_id):
        with db(host) as conn:
            campaign_view(conn, campaign_id)
            rows = conn.execute("SELECT c.email,c.centre,d.status,d.sent_at,d.message_id,d.error FROM outreach_deliveries d JOIN outreach_contacts c ON c.id=d.contact_id WHERE d.campaign_id=? ORDER BY c.email", (campaign_id,)).fetchall()
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(["email", "centre", "statut", "date_acceptation", "identifiant_brevo", "detail"])
        def safe_cell(value):
            value = str(value or "")
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        for row in rows:
            writer.writerow([safe_cell(row[0]), safe_cell(row[1]), LABELS.get(row[2], row[2]), row[3], safe_cell(row[4]), safe_cell(row[5])])
        response = make_response("\ufeff" + buffer.getvalue())
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = 'attachment; filename="resultats_campagne_' + campaign_id + '.csv"'
        response.headers["Cache-Control"] = "no-store"
        return response

    @host.app.post("/admin/partners/campaigns/<campaign_id>/start")
    @admin
    def partner_campaign_start(campaign_id):
        if request.form.get("confirm") != "yes":
            abort(400, "Confirmez l’envoi aux destinataires de cette campagne.")
        missing = host._missing_brevo_config()
        if missing:
            return jsonify(error="Configuration d’envoi incomplète : " + ", ".join(missing)), 400
        with db(host, True) as conn:
            campaign_view(conn, campaign_id)
            # A stale in-flight request must never be automatically resent.
            conn.execute("UPDATE outreach_deliveries SET status='uncertain',error='Envoi interrompu : vérifier dans Brevo avant toute nouvelle campagne.' WHERE campaign_id=? AND status='sending' AND started<?", (campaign_id, time.time()-120))
            if request.form.get("retry_failed") == "yes":
                conn.execute("UPDATE outreach_deliveries SET status='pending' WHERE campaign_id=? AND status='failed'", (campaign_id,))
            conn.execute("UPDATE outreach_campaigns SET status='sending' WHERE id=?", (campaign_id,))
        return jsonify(ok=True)

    @host.app.post("/admin/partners/campaigns/<campaign_id>/pause")
    @admin
    def partner_campaign_pause(campaign_id):
        with db(host, True) as conn:
            campaign_view(conn, campaign_id)
            conn.execute("UPDATE outreach_campaigns SET status='paused' WHERE id=?", (campaign_id,))
        return jsonify(ok=True)

    @host.app.post("/admin/partners/campaigns/<campaign_id>/next")
    @admin
    def partner_campaign_next(campaign_id):
        with db(host, True) as conn:
            campaign = campaign_view(conn, campaign_id)
            if campaign["status"] != "sending":
                return jsonify(done=True, **campaign)
            # One in-flight recipient per campaign, even with two browser tabs.
            if campaign["counts"].get("sending"):
                return jsonify(busy=True)
            row = conn.execute("SELECT c.*,d.attempt FROM outreach_deliveries d JOIN outreach_contacts c ON c.id=d.contact_id WHERE d.campaign_id=? AND d.status='pending' ORDER BY c.email LIMIT 1", (campaign_id,)).fetchone()
            if not row:
                conn.execute("UPDATE outreach_campaigns SET status='completed' WHERE id=?", (campaign_id,))
                return jsonify(done=True, **campaign_view(conn, campaign_id))
            contact = dict(row)
            if contact["unsubscribed_at"] or host._is_blocked_email_recipient(contact["email"]):
                conn.execute("UPDATE outreach_deliveries SET status='skipped' WHERE campaign_id=? AND contact_id=?", (campaign_id, contact["id"]))
                return jsonify(done=False, **campaign_view(conn, campaign_id))
            attempt = contact["attempt"] + 1
            conn.execute("UPDATE outreach_deliveries SET status='sending',started=?,attempt=?,error='' WHERE campaign_id=? AND contact_id=?", (time.time(), attempt, campaign_id, contact["id"]))
        try:
            body, text = mail_content(host, campaign["template"], contact)
            result = host.brevo_send_email(contact["email"], campaign["template"]["subject"], body,
                text_content=text, metadata={"kind": "elearning_campaign", "idempotency_key": delivery_idempotency_key(campaign_id, contact["id"], attempt)},
                reply_to={"email": "clement@integraleacademy.com", "name": "Clément VAILLANT"})
            # Network/5xx errors can conceal provider acceptance. Never silently retry them.
            state = "sent" if result.get("ok") else "failed" if result.get("not_sent") or (result.get("status_code") and 400 <= result["status_code"] < 500) else "uncertain"
        except Exception:
            host.app.logger.exception("outreach_delivery_failed campaign=%s", campaign_id)
            result, state = {"error": "Résultat d’envoi inconnu. Vérifiez ce destinataire dans Brevo."}, "uncertain"
        with db(host, True) as conn:
            conn.execute("UPDATE outreach_deliveries SET status=?,sent_at=?,message_id=?,error=? WHERE campaign_id=? AND contact_id=?", (state, now() if state == "sent" else "", result.get("message_id", ""), str(result.get("error") or "")[:500], campaign_id, contact["id"]))
            if state in {"failed", "uncertain"}:
                conn.execute("UPDATE outreach_campaigns SET status='paused' WHERE id=?", (campaign_id,))
            view = campaign_view(conn, campaign_id)
        return jsonify(done=view["status"] != "sending", **view)

    @host.app.route("/communications/desinscription/<token>", methods=["GET", "POST"])
    def partner_campaign_unsubscribe(token):
        if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
            abort(404)
        with db(host, request.method == "POST") as conn:
            contact = conn.execute("SELECT id,unsubscribed_at FROM outreach_contacts WHERE unsubscribe_token=?", (token,)).fetchone()
            if not contact:
                abort(404)
            done = bool(contact["unsubscribed_at"])
            if request.method == "POST":
                conn.execute("UPDATE outreach_contacts SET unsubscribed_at=? WHERE id=?", (now(), contact["id"]))
                done = True
        response = make_response(render_template("emails/partner_unsubscribe.html", done=done))
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
