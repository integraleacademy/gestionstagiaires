"""One electronic signature per issued employer PDF, separate from the learner's requests."""
from contextlib import contextmanager
import fcntl
import hashlib
from pathlib import Path
import re
import uuid

import fitz

from exam_retakes_workflow import unique

STOPPED = {"canceled", "cancelled", "expired", "declined", "rejected", "deleted"}
ACTIVE = {"draft", "ongoing", "activated", "approval", "paused"}


def document(trainee):
    copy = trainee.get("company_convention_copy_path")
    primary = trainee.get("company_convention") and trainee.get("convention_aps_pdf_path")
    if primary and trainee.get("company_signature_target") == "primary":
        return str(primary), False
    if primary and not (copy and (trainee.get("company_signature_target") == "copy" or trainee.get("convention_aps_signed_at"))):
        return str(primary), False
    return str(copy or primary or ""), bool(copy)


def version(path):
    return hashlib.sha256(str(path).encode()).hexdigest() if path else ""


@contextmanager
def dossier_lock(root, session_id, trainee_id):
    directory = Path(root, ".company-locks")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / version(session_id + "/" + trainee_id)).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def contact(host, form):
    person = {k: form.get(k, "").strip() for k in ("first_name", "last_name", "email", "phone")}
    if not all(0 < len(person[k]) <= 100 for k in ("first_name", "last_name")):
        raise ValueError("Renseignez le prénom et le nom du représentant.")
    if len(person["email"]) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", person["email"]):
        raise ValueError("Renseignez l’adresse e-mail du représentant qui signera la convention.")
    person["phone"] = host._normalize_yousign_sms_phone(person["phone"])
    if not person["phone"]:
        raise ValueError("Renseignez le mobile du représentant pour le code SMS.")
    return person


def signature_field(path):
    with fitz.open(path) as doc:
        for i in reversed(range(len(doc))):
            marks = doc[i].search_for("Date et signature")
            if marks:
                mark = marks[-1]
                return dict(page=i + 1, x=int(mark.x0), y=int(mark.y1 + 2), width=180, height=55)
    raise ValueError("Le cadre de signature de l’entreprise est introuvable. Régénérez le PDF.")


def send(host, row, save):
    """Resume a partially created request. Activation alone dispatches Yousign's email."""
    if not host._yousign_is_configured():
        raise ValueError("Yousign n’est pas configuré pour cet établissement.")
    source = Path(row["pdf"])
    if not source.is_file() or host._sha256_file(str(source)) != row["sha256"]:
        raise ValueError("Le PDF a changé. Vérifiez la convention avant de l’envoyer.")
    field = signature_field(source)

    def create(step, base, recover, **kwargs):
        if row.get("pending") == step:
            result = unique(recover(), "Opération Yousign non confirmée. Actualisez le suivi avant de réessayer.")
        else:
            row["pending"] = step
            save()
            try:
                result = host._yousign_json("POST", base, **kwargs)
            except Exception as exc:
                if getattr(exc, "status_code", 0) in {400, 401, 403, 404, 422, 429}:
                    row.pop("pending", None)
                    save()
                raise
        row[step] = result["id"]
        row.pop("pending", None)
        save()

    if not row.get("request_id"):
        external = row["external_id"]
        create("request_id", "/signature_requests", lambda: [
            item for item in host._list_yousign_signature_requests({"external_id": external})
            if item.get("external_id") == external], json={
                "name": ("Convention de formation – " + row["company"])[:100],
                "delivery_mode": "email", "timezone": "Europe/Paris", "external_id": external,
                "reminder_settings": {"interval_in_days": 2, "max_occurrences": 3}})
    base = "/signature_requests/" + row["request_id"]
    remote = host._yousign_json("GET", base)
    if remote.get("status") == "draft":
        if not row.get("document_id"):
            with source.open("rb") as pdf:
                create("document_id", base + "/documents", lambda: host._yousign_signature_request_items(
                    host._yousign_json("GET", base + "/documents")), files={"file": ("Convention-entreprise.pdf", pdf, "application/pdf")},
                    data={"nature": "signable_document", "parse_anchors": "false"})
        person = row["contact"]
        if not row.get("signer_id"):
            create("signer_id", base + "/signers", lambda: [
                item for item in host._yousign_signature_request_items(host._yousign_json("GET", base + "/signers"))
                if item.get("info", {}).get("email", "").casefold() == person["email"].casefold()], json={
                    "info": {"first_name": person["first_name"], "last_name": person["last_name"],
                             "email": person["email"], "phone_number": person["phone"], "locale": "fr"},
                    "signature_level": "electronic_signature", "signature_authentication_mode": "otp_sms",
                    "fields": [{"document_id": row["document_id"], "type": "signature", **field}]})
        remote = host._yousign_json("POST", base + "/activate", json={})
    status = remote.get("status")
    if status not in ACTIVE | STOPPED | {"done", "completed"}:
        raise ValueError("Yousign n’a pas confirmé le statut de la demande.")
    row["status"] = "ongoing" if status in {"done", "completed"} else status
    save()


def synchronize(host, t, s, row):
    if not row.get("request_id") or row.get("signed_pdf"):
        return
    request_id = row["request_id"]
    remote = host._yousign_json("GET", "/signature_requests/" + request_id)
    status = remote.get("status")
    if status in ACTIVE | STOPPED:
        row["status"] = status
    if status not in {"done", "completed", "signed"}:
        return
    path = host._download_yousign_signed_pdf(request_id, "entreprise-" + request_id)
    now = host._now_iso()
    row.update(status="done", signed_pdf=path, signed_at=now)
    if t.get("company_convention") and t.get("convention_aps_pdf_path") == row["pdf"]:
        state = host._yousign_state(t)
        state.update(status="done", signed_at=now, signed_pdf_path=path, signed_pdf_token=host._store_public_file_token(path))
        t.update(convention_aps_status="signed", convention_status="signed", convention_aps_signed_at=now, updated_at=now)
        host._schedule_convocation_after_convention_signed(s, t, s["id"], t["id"])
    host.append_trainee_history_event(t, "Convention signée par l’entreprise", row["company"], "action", now)


def new_row(host, path, company, person):
    return dict(pdf=path, company=company, contact=person, status="draft",
                external_id="entreprise-" + uuid.uuid4().hex, sha256=host._sha256_file(path))


def cancel(host, row):
    request_id = row.get("request_id")
    if not request_id:
        if row.get("pending"):
            raise ValueError("La création reste à vérifier. Reprenez la demande pour retrouver sa référence.")
    else:
        base = "/signature_requests/" + request_id
        status = host._yousign_json("GET", base).get("status")
        if status == "draft":
            host._yousign_request("DELETE", base)
        elif status in ACTIVE:
            host._yousign_json("POST", base + "/cancel", json={"reason": "other", "custom_note": "Annulation depuis la fiche stagiaire."})
        elif status not in STOPPED:
            raise ValueError("Cette demande ne peut plus être annulée. Actualisez son statut.")
    row["status"] = "canceled"
