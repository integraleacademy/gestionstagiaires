"""A single agreement and Yousign request per order, including pre-existing VTC contracts."""
import hashlib
import shutil

import exam_retakes
import exam_retakes_workflow as provider
from vtc_order_documents import document

STOPPED = {"canceled", "cancelled", "expired", "declined", "rejected", "deleted"}

LABELS = {"none": "À préparer", "draft": "Générée", "queued": "Envoi en cours", "sent": "À signer",
          "signed": "Signée", "stopped": "Signature interrompue"}


def state(row):
    if row.get("agreement_state"):
        return row["agreement_state"]
    if row["stage"] == "stopped":
        return "stopped"
    if row.get("signed_day") and row["stage"] != "contract":
        return "signed"
    if row.get("request_id") or row.get("pending"):
        return "sent" if row.get("signature_url") else "queued"
    if row["stage"] == "contract":
        return "queued"
    return "draft" if row.get("pdf_sha256") else "none"


def locked(row):
    return state(row) not in {"none", "draft"}


def generate(store, row):
    path = store.document(row["id"], "convention")
    row["signature_field"] = document(row, path, contract=True)
    row["pdf_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def validate_for_signature(row):
    if row["offer"] != "vehicule" and not row.get("slot"):
        raise ValueError("Renseignez le créneau de formation et le formateur avant l’envoi.")
    if row["offer"] == "formation" and not all(row["person"].get(k) for k in ("address", "zip_code", "city")):
        raise ValueError("Complétez l’adresse postale du candidat avant l’envoi.")


def restart(host, store, row, expected_version):
    version = row.get("agreement_version", 1)
    if (str(version) != expected_version or state(row) not in {"queued", "sent", "stopped"}
            or row["stage"] == "withdrawn" or store.document(row["id"], "signed").is_file()):
        raise ValueError("Cette demande a changé. Actualisez le dossier avant de reprendre la convention.")
    request_id = row.get("request_id")
    if request_id:
        path = "/signature_requests/" + request_id
        status = host._yousign_json("GET", path).get("status")
        if status in {"ongoing", "activated", "approval"}:
            host._yousign_json("POST", path + "/cancel", json={"reason": "errors_in_document",
                               "custom_note": "Nouvelle version de la convention VTC demandée par le centre."})
            status = host._yousign_json("GET", path).get("status")
        if status not in STOPPED:
            raise ValueError("Actualisez la signature. La demande précédente doit être terminée ou annulée dans Yousign.")
    elif row.get("pending"):
        raise ValueError("Actualisez la signature pour retrouver la demande Yousign en cours.")
    current_pdf = store.document(row["id"], "convention")
    if current_pdf.is_file():
        archive = current_pdf.with_suffix(f".v{version}.pdf")
        shutil.copyfile(current_pdf, archive)
    row.setdefault("agreement_history", []).append({"version": version, "request_id": request_id,
        "sha256": row.get("pdf_sha256"), "closed_at": exam_retakes.now()})
    for key in ("request_id", "document_id", "signer_id", "signature_url", "pending", "agreement_reminder",
                "agreement_queued_at"):
        row.pop(key, None)
    if row["stage"] in {"contract", "stopped"}:
        row["stage"] = "planning"
    row.update(agreement_state="draft", agreement_error="", agreement_version=version + 1)
    generate(store, row)


def delivery_key(row, name):
    version = row.get("agreement_version", 1)
    return name if version == 1 else f"{name}-v{version}"


def sync(host, store, row, notify, vehicle_receipt):
    current = state(row)
    if current not in {"queued", "sent"} or row["stage"] == "withdrawn":
        return -1
    if not row.get("pdf_sha256"):
        validate_for_signature(row)
        generate(store, row)
        provider.checkpoint(store, row, agreement_state="queued")
    path = store.document(row["id"], "convention")
    vehicle = row["offer"] == "vehicule"
    title = "Convention de mise à disposition du véhicule VTC" if vehicle else "Convention de formation pratique VTC"
    remote = provider.ensure_signature(host, store, row, name=title, prefix=delivery_key(row, "vtc"),
                                       filename="Convention-VTC.pdf", notify=False)
    if remote.get("status") in STOPPED:
        row["agreement_state"] = "stopped"
        if row["stage"] == "contract":
            row["stage"] = "stopped"
        return -1
    if remote.get("status") in {"done", "completed"}:
        signed = store.document(row["id"], "signed")
        if not signed.is_file():
            result = host._yousign_request("GET", "/signature_requests/" + row["request_id"] + "/documents/download",
                                           params={"version":"completed","archive":"false"}, headers={"Accept":"application/pdf"})
            provider.store_pdf(signed, result.content)
        row.setdefault("signed_day", exam_retakes.today())
        files = [("Convention-VTC-signee.pdf", signed)]
        if row["offer"] == "formation" and row["stage"] == "contract":
            files.append(vehicle_receipt(store, row))
        notify(host, store, row, "signed", "Votre convention VTC signée",
               "Retrouvez votre exemplaire signé en pièce jointe et dans votre dossier VTC.", files, delivery_key=delivery_key(row, "signed"))
        row.update(agreement_state="signed", signature_url="")
        if row["stage"] == "contract":
            row["stage"] = "delivery"
        return -1
    notify(host, store, row, "signature", "Votre convention VTC est prête",
           "Retrouvez votre convention dans votre dossier VTC pour la consulter et la signer en ligne.",
           [("Convention-VTC.pdf", path)], delivery_key=delivery_key(row, "signature"))
    row["agreement_state"] = "sent"
    reminder = row.get("agreement_reminder")
    if reminder:
        notify(host, store, row, "reminder", "Rappel de signature de votre convention VTC",
               "Votre convention attend votre signature. Retrouvez le lien dans votre dossier VTC.",
               delivery_key=delivery_key(row, "vtc-reminder-" + reminder))
        row.pop("agreement_reminder", None)
    return 180
