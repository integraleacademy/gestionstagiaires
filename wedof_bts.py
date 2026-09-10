"""Read-only WEDOF apprenticeship API (official /api/doc.json, 2026-09-10).

Only the four supported apprenticeship financers are accepted. No URL returned by WEDOF is followed;
identifiers are validated and calls reuse the existing shared quota governor.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from urllib.parse import quote

from wedof_service import WedofApiError, WedofClient

FINANCERS = {"opcoCfaAkto": "AKTO", "opcoCfaEp": "OPCO EP",
             "opcoCfaOpcommerce": "L’Opcommerce", "opcoCfaMobilites": "OPCO Mobilités"}
STATES = {"draft": "Brouillon", "sent": "Transmis", "pendingAcceptation": "En instruction",
          "accepted": "Engagé", "cancelled": "Annulé", "refused": "Refusé",
          "broken": "Rompu", "completed": "Soldé"}


def text(value):
    return str(value).strip()[:500] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def obj(value):
    return value if isinstance(value, dict) else {}


def identifier(value):
    value = text(value)
    if not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise WedofApiError("Identifiant de contrat WEDOF invalide.", "invalid_working_contract")
    return value


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def date(value):
    try:
        return dt.date.fromisoformat(text(value)[:10]).isoformat()
    except ValueError:
        return ""


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def financer_label(value):
    return FINANCERS.get(value, "OPCO non communiqué")


def financer_filter(value=""):
    if not isinstance(value, str) or (value and value not in FINANCERS):
        raise WedofApiError("Choisissez AKTO, OPCO EP, L’Opcommerce ou OPCO Mobilités.", "invalid_financer")
    return value or ",".join(FINANCERS)


def normalize_summary(item):
    if not isinstance(item, dict) or not isinstance(item.get("financer"), str) or item["financer"] not in FINANCERS:
        raise WedofApiError("La réponse ne correspond pas à un contrat d’un OPCO pris en charge.", "invalid_working_contract")
    key = identifier(item.get("id"))
    links = obj(item.get("_links"))
    employer, folder = obj(links.get("employer")), obj(links.get("registrationFolder"))
    # Only allowlisted useful data are persisted; never NIR, IBAN, tokens or URLs.
    result = {"working_contract_id": key, "internal_number": "", "external_number": text(item.get("externalIdTrainingOrganism")),
              "deca_number": text(item.get("externalIdDeca")), "financer": item["financer"],
              "registration_id": text(folder.get("externalId")), "state": text(item.get("state")),
              "state_label": STATES.get(item.get("state"), "État non communiqué"),
              "contract_type": text(item.get("type")), "contract_start": date(item.get("startDate")),
              "contract_end": date(item.get("endDate")), "contract_conclusion": date(item.get("signedDate")),
              "contract_break_date": date(item.get("breakingDate")), "amendment_date": date(item.get("amendmentDate")),
              "employer_name": text(employer.get("name")), "employer_siret": text(employer.get("siret")),
              "source_updated_at": text(item.get("lastUpdate") or item.get("updatedOn")),
              "wedof_updated_at": text(item.get("updatedOn")),
              "engagement": item.get("amount") if isinstance(item.get("amount"), (int, float)) and not isinstance(item.get("amount"), bool) else None}
    # Reject NaN/Infinity/negative engagements instead of displaying an invented zero.
    import math
    if result["engagement"] is not None and (not math.isfinite(result["engagement"]) or result["engagement"] < 0):
        result["engagement"] = None
    result["summary_hash"] = fingerprint(result)
    return result


def folder_fields(folder, expected_id):
    if (not isinstance(folder, dict) or not expected_id or text(folder.get("externalId")) != expected_id
            or folder.get("type") not in {"opcoCfa", "opco"}):
        raise WedofApiError("Le dossier lié ne correspond pas à ce contrat d’apprentissage.", "invalid_apprenticeship_folder")
    attendee = obj(folder.get("attendee"))
    address = obj(attendee.get("address"))
    training = obj(folder.get("trainingActionInfo"))
    certification = obj(obj(folder.get("_links")).get("certification"))
    return {"apprentice_first_name": text(attendee.get("firstName")), "apprentice_last_name": text(attendee.get("lastName")),
            "apprentice_email": text(attendee.get("email")), "apprentice_phone": text(attendee.get("phoneNumber")),
            "apprentice_birth_date": date(attendee.get("dateOfBirth")),
            "apprentice_address": text(attendee.get("fullAddress") or address.get("line4")),
            "apprentice_postcode": text(address.get("zipCode")), "apprentice_city": text(address.get("city")),
            "training_title": text(training.get("title")), "rncp": text(certification.get("externalId")),
            "training_start": date(training.get("sessionStartDate")), "training_end": date(training.get("sessionEndDate")),
            "training_hours": text(training.get("hoursInCenter")), "folder_type": folder.get("type"),
            "details_checked_at": stamp(), "details_error": ""}


def raw_fields(raw, contract):
    """Accept only a recognisable, matching CFA Dock dossier. Beta stays optional."""
    if not isinstance(raw, dict) or not isinstance(raw.get("cerfa"), dict):
        raise WedofApiError("Les données OPCO ne contiennent pas de dossier CFA Dock exploitable.", "raw_format_unavailable")
    cerfa = raw["cerfa"]
    number = contract.get("external_number")
    numbers = {text(cerfa.get("numeroInterne")), text(cerfa.get("numeroExterne"))} - {""}
    deca = text(cerfa.get("numeroDeca") or obj(cerfa.get("contrat")).get("noContrat"))
    if not ((number and number in numbers) or (deca and deca == contract.get("deca_number"))):
        raise WedofApiError("L’identité du dossier OPCO n’a pas pu être vérifiée.", "raw_identity_mismatch")
    from akto_bts import normalize_contract
    normalized = normalize_contract({}, raw, [], synced_at=stamp(), detail_loaded=True)
    # Do not persist the unrestricted raw payload, disability or invented numeric defaults.
    fields = {key: normalized[key] for key in (
        "internal_number", "apprentice_first_name", "apprentice_last_name", "apprentice_email",
        "apprentice_phone", "apprentice_birth_date", "employer_name", "employer_siret", "employer_email",
        "employer_phone", "training_title", "rncp", "diploma_code", "training_start", "training_end") if normalized.get(key)}
    schedules = raw.get("echeances")
    if isinstance(schedules, list) and all(isinstance(x, dict) for x in schedules):
        allowed = {"numero", "codification", "montantTotal", "montantRegle", "montantEnCoursInstruction", "dateOuverture", "dateDebut", "dateFin"}
        fields["schedules"] = [{k: v for k, v in x.items() if k in allowed and isinstance(v, (str, int, float, type(None))) and not isinstance(v, bool)} for x in schedules]
    verified_schedules = "schedules" in fields
    fields.update(raw_attempted_at=stamp(), raw_stale=not verified_schedules,
                  raw_error="" if verified_schedules else "WEDOF ne restitue pas d’échéancier exploitable. Les éventuelles échéances précédentes restent à vérifier.")
    if verified_schedules:
        fields["raw_checked_at"] = stamp()
    return fields


class WedofBtsClient(WedofClient):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("origin", "gestionstagiaires-bts")
        super().__init__(*args, **kwargs)

    def read(self, path, *, params=None, operation="bts_read"):
        return self._get_json_response(path, params=params, timeout=(3, 8), max_attempts=1,
                                       backoff=0, operation=operation)

    def contracts_page(self, page=1, limit=100, *, financer=""):
        page, limit = int(page), int(limit)
        if not 1 <= page <= 100 or not 1 <= limit <= 100:
            raise WedofApiError("Pagination WEDOF invalide.", "invalid_pagination")
        payload, response = self.read("/workingContracts", params={"financer": financer_filter(financer), "state": "all", "page": page, "limit": limit}, operation="bts_list_contracts")
        if not isinstance(payload, list) or len(payload) > limit:
            raise WedofApiError("La liste de contrats reçue est inattendue.", "invalid_working_contract_list")
        items = [normalize_summary(item) for item in payload]
        if financer and any(item["financer"] != financer for item in items):
            raise WedofApiError("WEDOF a renvoyé un contrat d’un autre OPCO que celui choisi.", "invalid_financer")
        ids = [item["working_contract_id"] for item in items]
        if len(ids) != len(set(ids)):
            raise WedofApiError("WEDOF a renvoyé des contrats en double dans une page.", "duplicate_working_contracts")
        headers = {str(k).lower(): v for k, v in (getattr(response, "headers", {}) or {}).items()}
        total = None
        try:
            total = int(headers["x-total-count"])
            current = int(headers.get("x-current-page", page))
            per_page = int(headers.get("x-item-per-page", limit))
            if total < 0 or current != page or per_page != limit:
                raise ValueError
        except KeyError:
            pass
        except (TypeError, ValueError):
            raise WedofApiError("La pagination renvoyée par WEDOF est incohérente.", "invalid_pagination") from None
        more = page * limit < total if total is not None else len(items) == limit
        if more and not items:
            raise WedofApiError("Une page WEDOF est vide avant la fin des résultats.", "invalid_pagination")
        return items, more, total

    def contract(self, key):
        key = identifier(key)
        payload, _ = self.read(f"/workingContracts/{key}", operation="bts_get_contract")
        item = normalize_summary(payload)
        if item["working_contract_id"] != key:
            raise WedofApiError("Le contrat reçu ne correspond pas à la demande.", "invalid_working_contract")
        return item

    def folder(self, external_id):
        external_id = text(external_id)
        if not external_id or len(external_id) > 250 or any(c in external_id for c in "/\\?#\r\n"):
            raise WedofApiError("Référence de dossier WEDOF invalide.", "invalid_apprenticeship_folder")
        payload, _ = self.read("/registrationFolders/" + quote(external_id, safe=""), operation="bts_get_apprentice")
        return folder_fields(payload, external_id)

    def raw(self, key, contract):
        payload, _ = self.read(f"/workingContracts/{identifier(key)}/raw", operation="bts_get_opco_data")
        return raw_fields(payload, contract)

    def close(self):
        self._session.close()


def is_apprenticeship_event(value):
    """Exclude explicit apprenticeship events from legacy commercial CPF relays."""
    if not isinstance(value, dict):
        return False
    if text(value.get("type")).casefold() == "opcocfa" or text(value.get("financer")).startswith("opcoCfa"):
        return True
    if value.get("accessModality") == "apprentissage":
        return True
    if text(value.get("event")).casefold().startswith("workingcontract"):
        return True
    links = obj(value.get("_links"))
    if "workingContracts" in links or "workingContract" in links:
        return True
    return any(is_apprenticeship_event(value.get(key)) for key in (
        "payload", "data", "resource", "registrationFolder", "folder", "wedof_folder_details"))
