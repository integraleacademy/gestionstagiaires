"""Durable, per-recipient CPF cancellation alerts in the WEDOF journal.

Callers hold the existing cross-process WEDOF journal lock throughout delivery.
Only new authenticated events enqueue alerts; retries never backfill history.
"""
import datetime as dt
import logging
import time
import uuid
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from wedof_matching import extract_folder
from wedof_service import ATTENDEE_CANCELLATION_STATE

RECIPIENTS = ("cassandre@integraleacademy.com", "clement@integraleacademy.com")
STATUS_LABEL = "Non réalisée annulation titulaire"
QUEUE_KEY = "cpf_cancellation_notification"
RETRY_SECONDS = 300
# Brevo retains idempotency keys for 30 minutes. Stop ambiguous retries early.
AMBIGUOUS_RETRY_SECONDS = 1200
logger = logging.getLogger(__name__)


def is_cancellation(folder):
    return (isinstance(folder, dict)
            and folder.get("state") == ATTENDEE_CANCELLATION_STATE
            and str(folder.get("type") or "cpf").casefold() == "cpf")


def find_notification(entries, folder_id):
    for entry in entries:
        item = entry.get(QUEUE_KEY) if isinstance(entry, dict) else None
        if isinstance(item, dict) and item.get("folder_id") == folder_id:
            return item
    return None


def enqueue(entries, entry, folder, message, now=None):
    """One alert per CPF folder, independently of webhook delivery identifiers."""
    folder_id = str(extract_folder(folder).get("external_id") or "")
    if not folder_id or not is_cancellation(folder):
        return None
    existing = find_notification(entries, folder_id)
    if existing:
        return existing
    timestamp = time.time() if now is None else now
    notification = {
        "folder_id": folder_id, "created_at": timestamp,
        "message": {"subject": message[0], "html": message[1], "text": message[2]},
        "recipients": {email: {"status": "pending", "attempts": 0,
                                "idempotency_key": str(uuid.uuid4())}
                       for email in RECIPIENTS},
    }
    entry[QUEUE_KEY] = notification
    return notification


def deliver(entries, notification, *, save, send, now=None):
    """Persist before each external send and immediately after its result."""
    timestamp = time.time() if now is None else now
    message = notification["message"]
    for email in RECIPIENTS:
        receipt = notification["recipients"][email]
        if receipt.get("status") in {"sent", "needs_review"}:
            continue
        last_attempt = receipt.get("last_attempt_at", 0)
        if last_attempt and timestamp - last_attempt < RETRY_SECONDS:
            continue
        uncertain_since = receipt.get("uncertain_since")
        if receipt.get("status") == "sending" and not uncertain_since:
            uncertain_since = last_attempt
        if uncertain_since and timestamp - uncertain_since >= AMBIGUOUS_RETRY_SECONDS:
            receipt.update(status="needs_review", error="Réception Brevo incertaine : vérifier avant un nouvel envoi.")
            save(entries)
            logger.error("[CPF CANCELLATION] delivery needs review folder=%s", notification["folder_id"])
            continue
        receipt.update(status="sending", last_attempt_at=timestamp,
                       uncertain_since=uncertain_since or timestamp,
                       attempts=int(receipt.get("attempts") or 0) + 1)
        save(entries)
        try:
            result = send(email, message["subject"], message["html"],
                          text_content=message["text"],
                          metadata={"purpose": "cpf_cancellation", "idempotency_key": receipt["idempotency_key"]})
        except Exception:
            logger.exception("[CPF CANCELLATION] delivery exception folder=%s", notification["folder_id"])
            result = {"ok": False, "status_code": None, "error": "Erreur de transport Brevo"}
        if not isinstance(result, dict):
            result = {"ok": bool(result), "status_code": None}
        if result.get("ok"):
            receipt.update(status="sent", sent_at=timestamp, error="",
                           message_id=str(result.get("message_id") or ""))
            receipt.pop("uncertain_since", None)
        else:
            receipt.update(status="failed", error=str(result.get("error") or "Envoi Brevo impossible")[:500])
            code = result.get("status_code")
            # Explicit rejection is safe to retry later. Unknown/5xx responses
            # may have been accepted, so keep the original deduplication window.
            if not uncertain_since and (code is not None and 400 <= code < 500
                                         or result.get("not_sent")):
                receipt.pop("uncertain_since", None)
            logger.warning("[CPF CANCELLATION] delivery failed folder=%s", notification["folder_id"])
        save(entries)


def _pick(source, *paths):
    for path in paths:
        value = source
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value is not None and value != "" and not isinstance(value, (dict, list)):
            return str(value).strip()
    return ""


def _date(value, with_time=False):
    if not value:
        return "Non renseignée"
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if with_time and parsed.tzinfo:
            parsed = parsed.astimezone(ZoneInfo("Europe/Paris"))
        return parsed.strftime("%d/%m/%Y à %H:%M" if with_time else "%d/%m/%Y")
    except ValueError:
        return str(value)


def _money(value):
    if value in (None, ""):
        return "Non renseigné"
    try:
        amount = Decimal(str(value).replace(" ", "").replace(",", "."))
        if not amount.is_finite():
            return "Non renseigné"
        return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " €"
    except (InvalidOperation, ValueError):
        return str(value)


def email_context(folder, *, received_at, base_url, local_data=None):
    """Allow-list business fields; never include raw webhooks or credentials."""
    remote = extract_folder(folder)
    data = local_data if isinstance(local_data, dict) else {}
    folder_id = str(remote.get("external_id") or "")
    link = next((item for item in data.get("wedof_links", [])
                 if isinstance(item, dict) and item.get("active") is True
                 and str(item.get("external_id") or "") == folder_id), {})
    session = next((item for item in data.get("sessions", [])
                    if isinstance(item, dict) and link.get("session_id")
                    and str(item.get("id") or "") == str(link.get("session_id"))), {})
    trainee = next((item for item in (session.get("trainees") or session.get("stagiaires") or [])
                    if isinstance(item, dict) and link.get("trainee_id")
                    and str(item.get("id") or "") == str(link.get("trainee_id"))), {})
    first_name = remote.get("first_name") or trainee.get("first_name") or trainee.get("prenom") or ""
    last_name = remote.get("last_name") or trainee.get("last_name") or trainee.get("nom") or ""
    name = " ".join(str(part) for part in (first_name, last_name) if part) or "Identité non renseignée"
    training = remote.get("training_title") or session.get("training_type") or "Formation non renseignée"
    amount = remote.get("total_amount")
    if amount in (None, ""):
        amount = _pick(folder, "trainingActionInfo.totalIncl")
    address = _pick(folder, "attendee.fullAddress") or " ".join(filter(None, [
        _pick(folder, "attendee.address.street", "attendee.address.address", "attendee.address.addressLine1"),
        _pick(folder, "attendee.address.zipCode", "attendee.address.postalCode"),
        _pick(folder, "attendee.address.city"),
    ]))
    local_url = ""
    if session and trainee:
        from urllib.parse import quote
        local_url = f"{base_url.rstrip('/')}/admin/sessions/{quote(str(session['id']), safe='')}/stagiaires/{quote(str(trainee['id']), safe='')}"
    sections = [
        {"title": "Le stagiaire", "rows": [
            ("Nom", last_name or "Non renseigné"), ("Prénom", first_name or "Non renseigné"),
            ("E-mail", remote.get("email") or trainee.get("email") or "Non renseigné"),
            ("Téléphone", remote.get("phone") or trainee.get("phone") or "Non renseigné"),
            ("Adresse", address or trainee.get("address") or "Non renseignée"),
            ("Date de naissance", _date(_pick(folder, "attendee.dateOfBirth"))),
        ]},
        {"title": "La formation", "rows": [
            ("Intitulé", training),
            ("Début prévu", _date(remote.get("start_date"))),
            ("Fin prévue", _date(remote.get("end_date"))),
            ("Durée", str(remote.get("training_duration")) + " h" if remote.get("training_duration") not in (None, "") else "Non renseignée"),
            ("Session locale", session.get("name") or session.get("title") or "Dossier non rattaché"),
            ("Lieu", _pick(folder, "trainingActionInfo.location", "trainingActionInfo.address.fullAddress") or session.get("location") or "Non renseigné"),
        ]},
        {"title": "Le financement", "rows": [
            ("Montant de la formation", _money(amount)),
            ("Financement CPF", _money(remote.get("cpf_amount"))),
            ("Financement France Travail", _money(remote.get("france_travail_amount"))),
            ("Participation du titulaire", _money(remote.get("candidate_amount"))),
            ("Facture", remote.get("invoice_number") or remote.get("qonto_invoice_number") or "Non renseignée"),
        ]},
        {"title": "L’annulation et les références", "rows": [
            ("Statut", STATUS_LABEL),
            ("Motif communiqué", _pick(folder, "cancellation.reason", "cancellationReason", "cancelReason", "reason") or "Non communiqué"),
            ("Date d’annulation", _date(_pick(folder, "canceledAt", "cancelledAt", "cancellationDate", "cancellation.date"), True)),
            ("Alerte reçue le", _date(received_at, True)),
            ("Référence du dossier", folder_id),
            ("Référence de formation", _pick(folder, "trainingActionInfo.trainingId", "trainingId") or "Non renseignée"),
            ("Référence de l’action", _pick(folder, "trainingActionInfo.externalId", "trainingActionInfo.trainingActionId", "trainingActionId") or "Non renseignée"),
            ("Dossier créé le", _date(remote.get("created_at"), True)),
            ("Dernière mise à jour WEDOF", _date(remote.get("updated_at"), True)),
        ]},
    ]
    subject = f"Annulation CPF • {name} • {training}"
    subject = " ".join(subject.split())[:240]
    url = base_url.rstrip("/") + "/admin/wedof?section=cancellations"
    text = f"ANNULATION CPF\n{STATUS_LABEL}\n\n{name}\n{training}\n"
    for section in sections:
        text += "\n" + section["title"] + "\n" + "\n".join(f"{label} : {value}" for label, value in section["rows"]) + "\n"
    text += f"\nVoir les annulations : {url}\n"
    if local_url:
        text += f"Ouvrir la fiche stagiaire : {local_url}\n"
    return {"subject": subject, "name": name, "training": training, "status": STATUS_LABEL,
            "folder_id": folder_id, "sections": sections, "amount": _money(amount),
            "received_at": _date(received_at, True), "url": url, "local_url": local_url,
            "logo_url": base_url.rstrip("/") + "/static/logo-integrale.png", "text": text}
