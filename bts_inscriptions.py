"""Read the selected candidate from the school's inscriptions BTS service."""
from __future__ import annotations

import os
import re
import unicodedata

import requests

from bts_workspace_store import WorkspaceError

BASE_URL = "https://inscriptionsbts.onrender.com/api/gestionstagiaires"
BTS_TITLES = {"MOS": "Management opérationnel de la sécurité", "MCO": "Management commercial opérationnel",
              "NDRC": "Négociation et digitalisation de la relation client", "PI": "Professions immobilières",
              "CI": "Commerce international", "CG": "Comptabilité et gestion"}


def normalize(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value or ""))
                   if not unicodedata.combining(c)).strip().casefold()


def candidate_id(value):
    value = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise WorkspaceError("L’identifiant de la préinscription est invalide.")
    return value


class InscriptionsClient:
    def __init__(self, key=None, http=None):
        self.key = key if key is not None else os.environ.get("BTS_IMPORT_API_KEY", "").strip()
        if len(self.key) < 32:
            raise WorkspaceError("La connexion aux inscriptions BTS n’est pas encore configurée.")
        self.http = http or requests.Session()

    def request(self, method, path, *, json=None, binary=False):
        try:
            response = self.http.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + self.key, "Accept": "application/json"},
                json=json, timeout=(5, 15), allow_redirects=False, stream=True)
            if response.status_code != 200:
                if response.status_code == 404:
                    raise WorkspaceError("Cette préinscription ou cette pièce n’est plus disponible.")
                raise WorkspaceError("Les inscriptions BTS ne sont pas accessibles. Vérifiez la connexion ou réessayez.")
            limit = 20 * 1024 * 1024 if binary else 2 * 1024 * 1024
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > limit:
                    raise WorkspaceError("Le fichier ou la réponse des inscriptions BTS est trop volumineux.")
            if binary:
                return bytes(content)
            import json as json_module
            return json_module.loads(content)
        except (requests.RequestException, ValueError) as exc:
            if isinstance(exc, WorkspaceError):
                raise
            raise WorkspaceError("Impossible de lire les inscriptions BTS. Réessayez dans quelques instants.") from None
        finally:
            if 'response' in locals():
                response.close()

    def search(self, query):
        query = str(query or "").strip()
        if not 2 <= len(query) <= 100:
            return {"items": [], "more": False}
        data = self.request("POST", "/candidats/rechercher", json={"q": query})
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise WorkspaceError("La réponse des inscriptions BTS est inattendue.")
        allowed = ("id", "numero_dossier", "nom", "prenom", "email", "bts", "mode", "statut")
        return {"items": [{k: str(item.get(k) or "")[:200] for k in allowed}
                          for item in data["items"][:20] if isinstance(item, dict)],
                "more": bool(data.get("more"))}

    def candidate(self, cid):
        cid = candidate_id(cid)
        result = self.request("GET", "/candidats/" + cid)
        data = result.get("candidate") if isinstance(result, dict) else None
        if not isinstance(data, dict) or data.get("id") != cid:
            raise WorkspaceError("La réponse ne correspond pas à la préinscription sélectionnée.")
        return data

    def download(self, cid, doc_id):
        if not re.fullmatch(r"[a-f0-9]{64}", str(doc_id)):
            raise WorkspaceError("Pièce introuvable.")
        return self.request("GET", f"/candidats/{candidate_id(cid)}/documents/{doc_id}", binary=True)


def candidate_values(candidate):
    mapping = {"prenom": "apprentice_first_name", "nom": "apprentice_last_name",
        "date_naissance": "apprentice_birth_date", "ville_naissance": "apprentice_birth_city",
        "email": "apprentice_email", "tel": "apprentice_phone", "adresse": "apprentice_address",
        "cp": "apprentice_postcode", "ville": "apprentice_city", "resp_email": "guardian_email"}
    values = {dest: str(candidate.get(src) or "").strip() for src, dest in mapping.items()}
    sex = normalize(candidate.get("sexe"))
    values["apprentice_sex"] = {"m": "M", "homme": "M", "masculin": "M", "f": "F", "femme": "F", "feminin": "F"}.get(sex, "")
    nir = re.sub(r"\s", "", str(candidate.get("num_secu") or "")).upper()
    if re.fullmatch(r"[12][0-9AB]{11}\d(?:\d{2})?", nir):
        values["apprentice_nir"] = nir[:13]
    values["guardian_name"] = " ".join(str(candidate.get(k) or "").strip() for k in ("resp_nom", "resp_prenom")).strip()
    if normalize(candidate.get("nationalite")) in {"france", "francaise", "francais", "fr"}:
        values["apprentice_nationality"] = "1"
    bts = str(candidate.get("bts") or "").upper().strip()
    values["training_title"] = "BTS " + BTS_TITLES.get(bts, bts) if bts else ""
    values["training_diploma_type"] = "54"
    # CFA identity and MOS identifiers are explicitly stated in the supplied
    # school model, independently of the candidate's personal declarations.
    values.update(cfa_name="Intégrale Sécurité Formations", cfa_siret="84089988400026", cfa_uai="0831774C",
                  cfa_address="54 chemin du Carreou", cfa_postcode="83480", cfa_city="Puget-sur-Argens")
    if bts == "MOS":
        values.update(rncp="RNCP41000", diploma_code="32034401")
    # Other codes/dates are not deduced from the school year or the learner's age.
    return {k: v for k, v in values.items() if v}
