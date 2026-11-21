"""Lecture serveur à serveur, strictement limitée, des RDV téléphoniques du CRM.

Le navigateur ne reçoit jamais les clés d'intégration. L'appel est en lecture
seule, avec authentification HMAC et sans réutilisation d'identités approximatives.
"""
import hmac
import json
import os
import re

import requests

URL = "https://assistance-alw9.onrender.com/api/integrations/edof-appointments"
CONTEXT = b"integrale-edof-appointments-v1\0"
HEADER = "X-Integrale-EDOF-Appointment-Signature"
IDENTIFIER = re.compile(r"[0-9]{6,20}\Z")


class CRMAppointmentsUnavailable(RuntimeError):
    pass


def _keys():
    # Les deux variables couvrent les configurations historiques des deux sens
    # de la passerelle CRM ↔ Gestion Stagiaires, sans afficher les valeurs.
    values = [
        os.getenv("CRM_INTEGRATION_API_TOKEN", "").strip(),
        os.getenv("GESTION_STAGIAIRES_API_TOKEN", "").strip(),
    ]
    return list(dict.fromkeys(value for value in values if value))


def lookup(folder_ids):
    if (not isinstance(folder_ids, list) or not 1 <= len(folder_ids) <= 30
            or len(set(folder_ids)) != len(folder_ids)
            or any(not isinstance(s, str) or not IDENTIFIER.fullmatch(s) for s in folder_ids)):
        raise ValueError("Liste de dossiers EDOF invalide.")
    keys = _keys()
    if not keys:
        raise CRMAppointmentsUnavailable("Connexion au CRM non configurée.")
    body = json.dumps({"folder_ids": folder_ids}, separators=(",", ":")).encode("utf-8")
    response = None
    for secret in keys:
        signature = hmac.digest(secret.encode("utf-8"), CONTEXT + body, "sha256").hex()
        try:
            response = requests.post(URL, data=body, timeout=(3, 6), allow_redirects=False,
                                     headers={"Content-Type": "application/json", "Accept": "application/json",
                                              HEADER: signature})
        except requests.RequestException:
            raise CRMAppointmentsUnavailable("Connexion au CRM temporairement indisponible.") from None
        if response.status_code != 401:
            break
    if response is None or response.status_code != 200:
        raise CRMAppointmentsUnavailable("Le CRM ne confirme pas la lecture des rendez-vous.")
    try:
        document = response.json()
    except ValueError:
        raise CRMAppointmentsUnavailable("Réponse du CRM invalide.") from None
    if not isinstance(document, dict) or document.get("ok") is not True:
        raise CRMAppointmentsUnavailable("Rendez-vous CRM indisponibles.")
    received = document.get("appointments")
    if not isinstance(received, dict) or set(received) != set(folder_ids):
        raise CRMAppointmentsUnavailable("Résultat des rendez-vous CRM incomplet.")
    safe = {}
    for folder in folder_ids:
        record = received[folder]
        if not isinstance(record, dict) or record.get("status") not in ("scheduled", "none", "unmatched"):
            raise CRMAppointmentsUnavailable("Statut CRM inattendu.")
        status = record["status"]
        item = {"status": status}
        if status == "scheduled":
            starts = record.get("start_at")
            if not isinstance(starts, str) or len(starts) > 48 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})",starts):
                raise CRMAppointmentsUnavailable("Horaire CRM invalide.")
            item["start_at"] = starts
            item["host"] = str(record.get("host") or "")[:80]
        url = record.get("crm_url")
        if isinstance(url, str) and url.startswith("https://assistance-alw9.onrender.com/crm/contacts?fiche=") and len(url) < 450:
            item["crm_url"] = url
        safe[folder] = item
    return safe
