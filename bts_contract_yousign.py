"""One Yousign request, separate PDFs, document-specific signer permissions.

Every remote mutation is checkpointed before it starts. An uncertain result is
never blindly retried, and no email is sent until all exclusions are installed.
"""
from __future__ import annotations

import hashlib
import io
import re

from pypdf import PdfReader

from bts_cerfa import readiness
from bts_contract_documents import needs_guardian, signature_errors, DOC_LABELS
from bts_workspace_store import WorkspaceError, now

ACTIVE_SIGNATURE_STATUSES = {"draft", "ongoing", "uncertain", "approval", "paused", "unknown"}


class SignatureError(WorkspaceError):
    def __init__(self, message, ambiguous=False):
        super().__init__(message)
        self.ambiguous = ambiguous


def identifier(value):
    value = str(value or "")
    if not re.fullmatch(r"[a-fA-F0-9-]{36}", value):
        raise SignatureError("Identifiant Yousign inattendu.", ambiguous=True)
    return value


def items(payload):
    return payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []


class YousignClient:
    def __init__(self, legacy):
        self.legacy = legacy
        if not legacy._yousign_is_configured():
            raise SignatureError("La connexion Yousign n’est pas configurée.")

    def call(self, method, path, *, binary=False, **kwargs):
        try:
            response = self.legacy._yousign_request(method, path, allow_redirects=False, **kwargs)
            if not 200 <= response.status_code < 300:
                raise SignatureError("Réponse Yousign inattendue.", ambiguous=method != "GET")
            return response.content if binary else (response.json() if response.content else {})
        except SignatureError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            message = "Yousign n’a pas confirmé l’opération. Actualisez le suivi avant toute nouvelle tentative."
            if status in {400, 403} and "/signers" in path:
                message = ("Yousign a refusé les signataires. Vérifiez leurs coordonnées et activez la visibilité des documents "
                           "dans les paramètres de signature Yousign (offre Pro ou Scale). Aucun envoi supplémentaire n’a été lancé.")
            elif status in {401, 403}:
                message = "Yousign a refusé l’accès. Vérifiez les droits de la connexion API."
            raise SignatureError(message, ambiguous=method != "GET" and (not status or status >= 500)) from None


def signers_for(package):
    values, settings = package["values"], package["settings"]
    signers = [{"role": "employer", "first_name": settings["employer_first_name"], "last_name": settings["employer_last_name"],
                "email": settings["employer_signer_email"]},
               {"role": "apprentice", "first_name": values["apprentice_first_name"], "last_name": values["apprentice_last_name"],
                "email": values["apprentice_email"]}]
    if needs_guardian(values):
        signers.append({"role": "guardian", "first_name": settings["guardian_first_name"], "last_name": settings["guardian_last_name"],
                        "email": values["guardian_email"]})
    return signers


def ensure_files(store, package, signed=False):
    required = {"cerfa", "formation"} | ({"mobilite"} if package["settings"]["teaching_mode"] == "presentiel" else set())
    if set(package["documents"]) != required:
        raise WorkspaceError("Générez tous les documents correspondant au mode de formation.")
    for document in package["documents"].values():
        key = "signed_pdf" if signed else "pdf"
        checksum = "signed_sha256" if signed else "sha256"
        path = store.path(document.get(key, ""))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != document.get(checksum):
            raise WorkspaceError("Un document est absent ou a changé. Actualisez les signatures ou régénérez les documents.")


def send_signature(store, record_id, package, api, actor):
    errors = signature_errors(package["values"], package["settings"])
    if readiness(package["values"]):
        errors.append("Les informations obligatoires du CERFA doivent être complétées")
    if errors:
        raise WorkspaceError("À compléter avant l’envoi : " + "; ".join(errors))
    ensure_files(store, package)
    state = package["signature"]
    if state.get("status") not in {None, "", "draft"}:
        raise WorkspaceError("Cette version dispose déjà d’une demande de signature. Consultez son suivi.")
    if state.get("pending"):
        raise WorkspaceError("Une opération Yousign reste à vérifier. Actualisez le suivi ; ne renvoyez pas les documents.")
    state.setdefault("external_id", "bts-" + package["id"])
    state.setdefault("documents", {})
    state.setdefault("signers", {})

    def mutate(step, method, path, **kwargs):
        state["pending"] = step
        store.save_package(record_id, package)
        try:
            result = api.call(method, path, **kwargs)
        except SignatureError as exc:
            state["error"] = str(exc)
            state["status"] = "uncertain" if exc.ambiguous else "draft"
            if not exc.ambiguous:
                state.pop("pending", None)
            store.save_package(record_id, package)
            raise
        return result

    def checkpoint():
        state.pop("pending", None)
        state.pop("error", None)
        store.save_package(record_id, package)

    if not state.get("request_id"):
        response = mutate("create", "POST", "/signature_requests", json={
            "name": ("Apprentissage · " + package["values"]["apprentice_first_name"] + " " + package["values"]["apprentice_last_name"])[:120],
            "delivery_mode": "email", "ordered_signers": False, "timezone": "Europe/Paris",
            "external_id": state["external_id"], "audit_trail_locale": "fr"})
        state["request_id"] = identifier(response.get("id"))
        state["status"] = "draft"
        checkpoint()
    base = "/signature_requests/" + identifier(state["request_id"])
    for kind, document in package["documents"].items():
        if kind in state["documents"]:
            continue
        with store.path(document["pdf"]).open("rb") as handle:
            response = mutate("document:" + kind, "POST", base + "/documents",
                files={"file": (kind + "-" + package["id"] + ".pdf", handle, "application/pdf")}, data={"nature": "signable_document"})
        state["documents"][kind] = identifier(response.get("id"))
        checkpoint()
    for signer in signers_for(package):
        role = signer["role"]
        if role in state["signers"]:
            continue
        fields = []
        for kind, document in package["documents"].items():
            fields += [{**{k: v for k, v in field.items() if k != "role"}, "document_id": state["documents"][kind]}
                       for field in document["fields"] if field["role"] == role]
        excluded = [state["documents"]["formation"]] if role != "employer" else []
        payload = {"info": {k: signer[k] for k in ("first_name", "last_name", "email")},
                   "signature_level": "electronic_signature", "signature_authentication_mode": "otp_email", "fields": fields}
        payload["info"]["locale"] = "fr"
        if excluded:
            payload["excluded_documents"] = excluded
        response = mutate("signer:" + role, "POST", base + "/signers", json=payload)
        state["signers"][role] = {**signer, "id": identifier(response.get("id")), "status": "initiated"}
        checkpoint()
    # Re-read permissions before activation, including after a partial resume.
    verify_participants(package, api, require_signed=False)
    response = mutate("activate", "POST", base + "/activate", json={})
    if response.get("status") not in {"ongoing", "done"}:
        raise SignatureError("Yousign n’a pas confirmé l’activation. Actualisez le suivi.", ambiguous=True)
    state["status"] = response["status"]
    state["sent_at"] = now()
    checkpoint()
    store.save_package(record_id, package, event="Documents envoyés ensemble en signature Yousign", actor=actor)


def verify_participants(package, api, require_signed):
    state = package["signature"]
    base = "/signature_requests/" + identifier(state["request_id"])
    # Exact membership protects against documents/signers added in the Yousign UI.
    documents = items(api.call("GET", base + "/documents"))
    if {d.get("id") for d in documents} != set(state["documents"].values()):
        raise SignatureError("La liste des documents Yousign a changé. Vérifiez la demande.")
    people = items(api.call("GET", base + "/signers"))
    if {p.get("id") for p in people} != {p["id"] for p in state["signers"].values()}:
        raise SignatureError("La liste des signataires Yousign a changé. Vérifiez la demande.")
    for role, signer in state["signers"].items():
        person = next(p for p in people if p.get("id") == signer["id"])
        if (person.get("info", {}).get("email") or "").casefold() != signer["email"].casefold():
            raise SignatureError("L’adresse d’un signataire Yousign a changé.")
        expected = {state["documents"]["formation"]} if role != "employer" else set()
        actual = set(person.get("excluded_documents") or [])
        # Some API responses expose document exclusions on documents rather than signers.
        actual |= {d["id"] for d in documents if signer["id"] in (d.get("excluded_signers") or [])}
        if actual != expected:
            raise SignatureError("La convention de formation doit être réservée à l’entreprise. Activez la visibilité des documents dans Yousign, puis vérifiez la demande.")
        signer["status"] = person.get("status", "initiated")
        if require_signed and signer["status"] != "signed":
            raise SignatureError("Une signature reste à confirmer par Yousign.")


def refresh_signature(store, record_id, package, api, actor="Équipe"):
    state = package["signature"]
    if not state.get("request_id") and state.get("external_id"):
        found = [p for p in items(api.call("GET", "/signature_requests", params={"external_id[eq]": state["external_id"], "limit": 100}))
                 if p.get("external_id") == state["external_id"]]
        if len(found) == 1:
            state["request_id"] = identifier(found[0]["id"])
        else:
            raise SignatureError("Yousign ne permet pas encore d’identifier la demande. Ne lancez pas de nouvel envoi.")
    if not state.get("request_id"):
        raise WorkspaceError("Aucune demande Yousign n’a été créée.")
    response = api.call("GET", "/signature_requests/" + identifier(state["request_id"]))
    if response.get("id") != state["request_id"] or response.get("external_id") != state["external_id"]:
        raise SignatureError("La demande Yousign ne correspond pas à cette version.")
    state["status"] = response.get("status", "unknown")
    state["checked_at"] = now()
    # A draft with an unresolved upload must be cancelled, never resumed blindly.
    if state["status"] in {"canceled", "expired", "deleted", "declined", "rejected"}:
        state.pop("pending", None)
    if state["status"] in {"ongoing", "done"}:
        verify_participants(package, api, require_signed=state["status"] == "done")
        state.pop("pending", None)
        state.pop("error", None)
    store.save_package(record_id, package)
    if state["status"] == "done":
        for kind, document in package["documents"].items():
            if document.get("signed_pdf") and store.path(document["signed_pdf"]).is_file():
                continue
            content = api.call("GET", f"/signature_requests/{state['request_id']}/documents/{state['documents'][kind]}/download", binary=True)
            if not content.startswith(b"%PDF"):
                raise SignatureError("Un document signé renvoyé par Yousign n’est pas un PDF.")
            if len(PdfReader(io.BytesIO(content)).pages) != len(PdfReader(store.path(document["pdf"])).pages):
                raise SignatureError("Le nombre de pages du document signé est inattendu.")
            relative = package["id"] + "/" + kind + "-signe.pdf"
            path = store.path(relative)
            temporary = path.with_suffix(".tmp"); temporary.write_bytes(content); temporary.replace(path)
            document.update(signed_pdf=relative, signed_sha256=hashlib.sha256(content).hexdigest())
            store.save_package(record_id, package)
        ensure_files(store, package, signed=True)
        if not state.get("completed_at"):
            state["completed_at"] = now()
            store.save_package(record_id, package, event="Toutes les signatures Yousign sont confirmées et les PDF archivés", actor=actor)
    return state["status"]


def cancel_signature(store, record_id, package, api, actor):
    state = package["signature"]
    request_id = identifier(state.get("request_id"))
    live = api.call("GET", "/signature_requests/" + request_id)
    if live.get("status") == "draft":
        api.call("DELETE", "/signature_requests/" + request_id)
    elif live.get("status") in {"ongoing", "approval", "paused"}:
        api.call("POST", "/signature_requests/" + request_id + "/cancel", json={"reason": "errors_in_document", "custom_note": "Nouvelle version des documents d’apprentissage"})
    else:
        raise WorkspaceError("Cette demande ne peut plus être annulée. Actualisez son suivi.")
    state.update(status="canceled", canceled_at=now())
    state.pop("pending", None)
    store.save_package(record_id, package, event="Demande Yousign annulée pour préparer une nouvelle version", actor=actor)
