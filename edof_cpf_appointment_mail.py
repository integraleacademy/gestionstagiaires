"""Accusé CPF différé : vérification EDOF fraîche, aperçu et livraison idempotente.

Aucun envoi n'est fait par la lecture de la page : seul le planificateur élu
peut émettre les e-mails automatiques. La base SQLite persiste sur le disque EDOF.
"""
from contextlib import closing
import os
import re
import time
from uuid import NAMESPACE_URL, uuid5

from flask import render_template

import edof_crm_details
import edof_directory as directory
from cpf_provider import ProviderStore
from edof_gmail import Vault

DELAY_SECONDS = 15 * 60
FRESH_SECONDS = 150
RECHECK_SECONDS = 180
SUBJECT = "Nous avons reçu votre demande d'inscription CPF – Intégrale Academy"
REPLY_TO = {"email": "cassandre@integraleacademy.com", "name": "Cassandre MENARD"}
GENERIC_BOOKING = "https://calendly.com/integraleacademy"

# Mêmes liens de rendez-vous que la configuration commerciale du CRM.
BOOKINGS = {
    "aps": "https://calendly.com/integraleacademy/aps",
    "a3p": "https://calendly.com/integraleacademy/apr",
    "ssiap": "https://calendly.com/integraleacademy/ssiap1",
    "desp": "https://calendly.com/integraleacademy/dirigeant",
    "vtc": "https://calendly.com/integraleacademy/chauffeurvtc",
    "btsmos": "https://calendly.com/integraleacademy/btsmos",
    "btsmco": "https://calendly.com/integraleacademy/btsmco",
    "btsndrc": "https://calendly.com/integraleacademy/btsndrc",
    "btsci": "https://calendly.com/integraleacademy/btsci",
    "btspi": "https://calendly.com/integraleacademy/professionsimmobilieres",
}
LABELS = {
    "queued": "E-mail prévu après 15 min",
    "sending": "Envoi en cours",
    "sent": "E-mail envoyé",
    "skipped": "Envoi annulé (statut modifié)",
    "failed": "Envoi refusé",
    "unknown": "Envoi à vérifier (ne pas renvoyer)",
}
_EMAIL = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_TERMINAL = {"sent", "unknown"}


def booking_url(title):
    value = directory.normalized(title or "")
    compact = re.sub(r"[^a-z0-9]", "", value)
    if "bts" in compact:
        if "mos" in compact or "securite" in value:
            return BOOKINGS["btsmos"]
        if "mco" in compact:
            return BOOKINGS["btsmco"]
        if "ndrc" in compact:
            return BOOKINGS["btsndrc"]
        if "commerceinternational" in compact or compact.endswith("ci"):
            return BOOKINGS["btsci"]
        if "immobili" in compact:
            return BOOKINGS["btspi"]
    if "vae" in value and ("dirigeant" in value or "desp" in value):
        return BOOKINGS["desp"]
    if "desp" in value or ("dirigeant" in value and "securite" in value):
        return BOOKINGS["desp"]
    if "a3p" in compact or "apr" in compact or "protection physique" in value or "protection rapprochee" in value:
        return BOOKINGS["a3p"]
    if "ssiap" in compact or "securite incendie" in value:
        return BOOKINGS["ssiap"]
    if "vtc" in compact or "chauffeur" in value:
        return BOOKINGS["vtc"]
    if "aps" in compact or "prevention et de securite" in value or "prevention et securite" in value:
        return BOOKINGS["aps"]
    return GENERIC_BOOKING


def tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS cpf_mail_initialized (
        owner TEXT PRIMARY KEY, checked REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS cpf_mail_seen (
        owner TEXT NOT NULL, folder TEXT NOT NULL, kind TEXT NOT NULL,
        checked REAL NOT NULL, PRIMARY KEY(owner,folder))""")
    db.execute("""CREATE TABLE IF NOT EXISTS cpf_mail_delivery (
        folder TEXT PRIMARY KEY, owner TEXT NOT NULL, first_seen REAL NOT NULL,
        due_at REAL NOT NULL, status TEXT NOT NULL, last_check REAL NOT NULL DEFAULT 0,
        claimed_at REAL NOT NULL DEFAULT 0, finished_at REAL NOT NULL DEFAULT 0,
        recipient_proof TEXT NOT NULL DEFAULT '', message_id TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'automatic')""")
    db.execute("CREATE INDEX IF NOT EXISTS cpf_mail_due ON cpf_mail_delivery(status,due_at)")


def observe_snapshot(db, owner, snapshot, classify, *, complete=False, now=None):
    """Observer une liste EDOF certifiée. Amorcer sans expédier les anciens dossiers."""
    if not owner or not snapshot:
        return []
    tables(db)
    now = time.time() if now is None else now
    checked = float(snapshot.get("checked") or now)
    initialized = db.execute(
        "SELECT 1 FROM cpf_mail_initialized WHERE owner=?", (owner,)
    ).fetchone() is not None
    queued = []
    rows = snapshot.get("rows") or {}
    if complete and not initialized:
        # Le premier export complet établit une base de référence : pas de
        # campagne rétroactive pour tous les dossiers déjà présents.
        db.execute("INSERT OR IGNORE INTO cpf_mail_initialized VALUES (?,?)", (owner, checked))
    for folder, row in rows.items():
        if not directory.ID_RE.fullmatch(str(folder)):
            continue
        kind = classify(row)
        previous = db.execute(
            "SELECT kind,checked FROM cpf_mail_seen WHERE owner=? AND folder=?",
            (owner, folder),
        ).fetchone()
        if previous and checked < previous["checked"]:
            continue
        if initialized and kind == "request" and (not previous or previous["kind"] != "request"):
            cursor = db.execute(
                """INSERT OR IGNORE INTO cpf_mail_delivery
                (folder,owner,first_seen,due_at,status)
                VALUES (?,?,?,?, 'queued')""", (folder, owner, now, now + DELAY_SECONDS)
            )
            if cursor.rowcount:
                queued.append(folder)
        db.execute(
            """INSERT INTO cpf_mail_seen(owner,folder,kind,checked) VALUES(?,?,?,?)
            ON CONFLICT(owner,folder) DO UPDATE SET
                kind=excluded.kind,checked=excluded.checked""",
            (owner,folder,kind,checked),
        )
        if kind != "request":
            db.execute(
                """UPDATE cpf_mail_delivery SET status='skipped',
                finished_at=?, error='Le dossier n’est plus à traiter.'
                WHERE folder=? AND status='queued'""", (now,folder)
            )
    if complete:
        missing = db.execute(
            """SELECT folder FROM cpf_mail_seen WHERE owner=? AND kind='request'
            AND checked<?""", (owner,checked)
        ).fetchall()
        for item in missing:
            folder = item["folder"]
            # Export complet : le dossier n'est plus présent dans les demandes.
            db.execute(
                """UPDATE cpf_mail_delivery SET status='skipped',
                finished_at=?,error='Le dossier a quitté la liste EDOF.'
                WHERE folder=? AND status='queued'""", (now,folder)
            )
            db.execute(
                "UPDATE cpf_mail_seen SET kind='missing',checked=? WHERE owner=? AND folder=?",
                (checked,owner,folder),
            )
    return queued


def statuses(folder_directory, folders):
    folders = [str(f) for f in folders if directory.ID_RE.fullmatch(str(f))]
    if not folders:
        return {}
    with closing(ProviderStore(folder_directory).connect()) as db:
        tables(db)
        result = {}
        # SQL à paramètres, lots bornés pour la limite SQLite.
        for start in range(0,len(folders),500):
            batch = folders[start:start+500]
            marks = ",".join("?" for _ in batch)
            for row in db.execute(
                "SELECT folder,status,due_at,finished_at,error,recipient_proof FROM cpf_mail_delivery WHERE folder IN (" + marks + ")",
                batch,
            ):
                result[row["folder"]] = {
                    "status": row["status"], "label": LABELS.get(row["status"],row["status"]),
                    "due_at": row["due_at"], "finished_at": row["finished_at"],
                    "recipient_verified": bool(row["recipient_proof"]), "error": row["error"],
                }
        return result


def cancel_local(folder_directory, folder, *, now=None):
    """Le traitement ou l'archivage local annule un message encore en attente."""
    now = time.time() if now is None else now
    with closing(ProviderStore(folder_directory).connect()) as db, db:
        tables(db)
        return db.execute(
            """UPDATE cpf_mail_delivery SET status='skipped', finished_at=?,
            error='Demande traitée ou archivée localement.'
            WHERE folder=? AND status='queued'""",
            (now, str(folder)),
        ).rowcount


def recipient_for(store, private, owner, row):
    """Courriel uniquement issu d'une fiche authentifiée correspondant au dossier."""
    folder = str(row["folder_id"])
    candidates = []
    detail = private.get(edof_crm_details.record_key(owner, folder), keep=True) or {}
    attendee = detail.get("attendee") or {}
    if isinstance(attendee, dict):
        candidates.append((attendee.get("email"),attendee.get("firstName"),attendee.get("lastName")))
    if hasattr(store, "successful_read"):
        previous = store.successful_read(owner, spec={
            "folder_id": folder, "first_name": row.get("first_name") or "",
            "last_name": row.get("last_name") or "",
        })
        if previous:
            fields = previous.get("fields") or {}
            candidates.append((fields.get("email"),fields.get("first_name"),fields.get("last_name")))
    for email,first,last in candidates:
        email = str(email or "").strip().lower()
        if not _EMAIL.fullmatch(email) or len(email) > 254:
            continue
        if directory.normalized(first or "") != directory.normalized(row.get("first_name") or ""):
            continue
        if directory.normalized(last or "") != directory.normalized(row.get("last_name") or ""):
            continue
        proof = row.get("email_proof")
        if proof and proof != directory.email_proof(os.environ.get("EDOF_CONNECTOR_KEY"),folder,email):
            continue
        return email
    return ""


def message_for(row, email):
    title = str(row.get("title") or "votre formation").strip()[:500]
    first = str(row.get("first_name") or "").strip()[:120]
    link = booking_url(title)
    html = render_template(
        "emails/edof_cpf_received.html", first_name=first,
        training_title=title, booking_url=link,
        email_heading="Nous avons reçu votre demande",
        email_eyebrow="VOTRE DEMANDE CPF",
        email_subtitle="Parlons de votre projet.",
        email_preheader="Votre demande est bien enregistrée. Choisissez un créneau pour en parler.",
        email_signature="cassandre",
        email_logo="https://assistance-alw9.onrender.com/static/logo.png",
    )
    plain = "\n".join([
        "Bonjour " + first + "," if first else "Bonjour,",
        "", "Nous avons bien reçu votre demande d'inscription en formation « " + title +
        " » depuis votre Compte Personnel de Formation (CPF).",
        "", "Afin que nous puissions traiter votre demande et vous accompagner dans votre projet de formation, "
        "nous vous invitons à prendre un rendez-vous téléphonique avec Cassandre.",
        "", "Choisissez le créneau qui vous convient : " + link,
        "", "Nous pourrons ainsi échanger sur votre projet, les modalités de la formation "
        "et les prochaines étapes de votre inscription.",
        "Votre demande est bien reçue, mais son acceptation n'est pas encore confirmée.",
        "", "Bien cordialement,",
        "Cassandre MENARD – Responsable commerciale",
        "Intégrale Academy – 04 22 47 07 68",
        "cassandre@integraleacademy.com",
    ])
    return {"to": email, "subject": SUBJECT, "html": html, "text": plain,
            "booking_url": link}


def _finish(store, folder, result, now):
    result = result if isinstance(result,dict) else {}
    code = result.get("status_code")
    if result.get("ok") is True:
        status = "sent"
        error = ""
    elif result.get("not_sent") is True or (
        isinstance(code,int) and 400 <= code < 500 and code != 408
    ):
        status = "failed"
        error = "Le prestataire a refusé cet envoi."
    else:
        # Brevo/SMTP peut avoir accepté le message malgré une coupure réseau.
        status = "unknown"
        error = "Réception non confirmée. Vérifier chez Brevo avant toute nouvelle tentative."
    with closing(ProviderStore(store.directory).connect()) as db, db:
        tables(db)
        db.execute(
            """UPDATE cpf_mail_delivery SET status=?,finished_at=?,error=?,
            message_id=? WHERE folder=? AND status='sending'""",
            (status,now,error,str(result.get("message_id") or "")[:200],folder),
        )
    return status


def _claim(store, owner, folder, email, *, automatic, now):
    with closing(ProviderStore(store.directory).connect()) as db, db:
        tables(db)
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """INSERT OR IGNORE INTO cpf_mail_delivery
            (folder,owner,first_seen,due_at,status,source)
            VALUES (?,?,?,?, 'queued','manual')""",
            (folder,owner,now,now),
        )
        entry = db.execute(
            "SELECT status FROM cpf_mail_delivery WHERE folder=?", (folder,)
        ).fetchone()
        if entry["status"] in _TERMINAL:
            raise ValueError("Ce courriel a déjà été envoyé ou son envoi doit être vérifié chez Brevo.")
        if entry["status"] == "sending":
            raise ValueError("Un envoi est déjà en cours pour ce dossier.")
        if automatic and entry["status"] != "queued":
            return False
        if entry["status"] not in ({"queued"} if automatic else {"queued","failed","skipped"}):
            return False
        db.execute(
            """UPDATE cpf_mail_delivery SET status='sending',claimed_at=?,
            recipient_proof=?,source=?,error='' WHERE folder=?""",
            (now,directory.email_proof(os.environ.get("EDOF_CONNECTOR_KEY"),folder,email),
             "automatic" if automatic else "manual",folder),
        )
    return True


def deliver(legacy, store, owner, row, email, *, automatic, now=None):
    now = time.time() if now is None else now
    # Générer complètement le message avant de réserver un envoi.
    with legacy.app.app_context():
        mail = message_for(row,email)
    blocked = getattr(legacy, "_is_blocked_email_recipient", None)
    if callable(blocked) and blocked(email):
        if automatic:
            with closing(ProviderStore(store.directory).connect()) as db, db:
                db.execute(
                    """UPDATE cpf_mail_delivery SET status='skipped',finished_at=?,
                    error='Adresse exclue des envois.'
                    WHERE folder=? AND status='queued'""",
                    (now, row["folder_id"]),
                )
            return "skipped"
        raise ValueError("Le destinataire est exclu des envois d'e-mails.")
    if not _claim(store,owner,row["folder_id"],email,automatic=automatic,now=now):
        return "skipped"
    try:
        result = legacy.brevo_send_email(
            mail["to"],mail["subject"],mail["html"],text_content=mail["text"],
            reply_to=REPLY_TO,metadata={
                "purpose":"edof_cpf_appointment",
                "idempotency_key":str(uuid5(NAMESPACE_URL,"edof-cpf-received-v1/" + str(row["folder_id"]))),
            },
        )
    except Exception:
        result = {"error":"Aucune confirmation du prestataire."}
    return _finish(store,row["folder_id"],result,time.time())


def manual_send(legacy, store, owner, row, private):
    if recipient := recipient_for(store, private, owner, row):
        status = deliver(legacy,store,owner,row,recipient,automatic=False)
        if status == "sent":
            return "Le courriel a été accepté par Brevo."
        if status == "failed":
            raise ValueError("L'envoi a été refusé par Brevo. Vous pourrez réessayer après vérification.")
        raise ValueError("Envoi non confirmé : vérifiez Brevo avant toute nouvelle tentative.")
    raise ValueError("Adresse e-mail EDOF non vérifiée. Actualisez la fiche du dossier avant l'envoi.")


def _current_evidence(private, owner, folder, *, due, now, classify):
    """La date de contrôle doit être postérieure au délai et proche de l'envoi."""
    evidence = []
    for key, complete in (
        (directory.record_key(owner),True),
        (directory.pending_key(owner),False),
        (directory.accepted_key(owner),False),
        (directory.validated_key(owner),False),
    ):
        snap = directory.dated_snapshot(private.get(key,keep=True))
        if not snap:
            continue
        checked = float(snap.get("checked") or 0)
        if checked < due:
            continue
        row = snap.get("rows",{}).get(folder)
        if row:
            evidence.append((checked, "request" if classify(row) == "request" else "other", row))
        elif complete:
            evidence.append((checked,"missing",None))
    if not evidence:
        return "stale",None
    checked,kind,row = sorted(evidence,key=lambda entry:entry[0])[-1]
    if now - checked > FRESH_SECONDS:
        return "stale",None
    return (kind,row)


def _request_check(store, owner, folder, now):
    # Évite de surcharger le portail EDOF quand il n'a pas encore répondu.
    with closing(ProviderStore(store.directory).connect()) as db, db:
        tables(db)
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute(
            """UPDATE cpf_mail_delivery SET last_check=? WHERE folder=?
            AND status='queued' AND last_check<?""",
            (now,folder,now-RECHECK_SECONDS),
        ).rowcount
    if changed:
        store.request_directory(owner)
        try:
            private = Vault(store.directory,store.connector_key)
            edof_crm_details.request_read(private,owner,folder)
        except Exception:
            pass


def process_due(store, legacy, selection, *, now=None):
    """Appelé uniquement par le planificateur EDOF ayant le verrou de leader."""
    if selection.get("provider") != "integrale" or selection.get("pending") or not store.connector_key:
        return None
    now = time.time() if now is None else now
    with closing(ProviderStore(store.directory).connect()) as db, db:
        tables(db)
        db.execute(
            """UPDATE cpf_mail_delivery SET status='unknown',finished_at=?,
            error='Envoi interrompu : vérifier le prestataire.'
            WHERE status='sending' AND claimed_at<?""",(now,now-180)
        )
        work = db.execute(
            """SELECT folder,owner,due_at FROM cpf_mail_delivery
            WHERE status='queued' AND due_at<=?
            ORDER BY due_at,folder LIMIT 10""",(now,)
        ).fetchall()
    for item in work:
        folder,owner,due = item["folder"],item["owner"],item["due_at"]
        private = Vault(store.directory,store.connector_key)
        from integrale_edof_dashboard import category, local_operations
        flags = local_operations(ProviderStore(store.directory)).get(folder, {})
        if flags.get("handled") or flags.get("archived"):
            cancel_local(store.directory, folder, now=now)
            continue
        state, row = _current_evidence(private,owner,folder,due=due,now=now,classify=category)
        if state == "stale":
            _request_check(store,owner,folder,now)
            continue
        if state != "request":
            with closing(ProviderStore(store.directory).connect()) as db, db:
                db.execute(
                    """UPDATE cpf_mail_delivery SET status='skipped',finished_at=?,
                    error='Le dossier n’est plus à traiter sur EDOF.'
                    WHERE folder=? AND status='queued'""",(now,folder)
                )
            continue
        email = recipient_for(store,private,owner,row)
        if not email:
            _request_check(store,owner,folder,now)
            continue
        return deliver(legacy,store,owner,row,email,automatic=True,now=now)
    return None
