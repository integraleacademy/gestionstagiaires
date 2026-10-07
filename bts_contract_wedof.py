"""Checkpointed WEDOF BETA submission, using its documented CFA Dock v1 payload.

The submit endpoint transmits CERFA data and the signature attestation, not the
PDF convention. A distinct manual deposit remains due after a successful send.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import requests

from bts_cerfa import readiness
from bts_contract_documents import needs_guardian, tuition
from bts_contract_yousign import ensure_files
from bts_workspace_store import WorkspaceError, now
from wedof_bts import FINANCERS, identifier
from wedof_service import WedofClient, WedofApiError, WEDOF_BASE_URL


def date_time(value):
    return value + "T00:00:00+00:00"


def nir_with_key(nir):
    """CERFA has 13 boxes; Convergence expects the same NIR plus its check key."""
    if not re.fullmatch(r"[12][0-9]{4}(?:[0-9]{2}|2[AB])[0-9]{6}", nir):
        raise WorkspaceError("Vérifiez le format du NIR avant la télétransmission.")
    numeric = nir[:5] + {"2A": "19", "2B": "18"}.get(nir[5:7], nir[5:7]) + nir[7:]
    return nir + f"{97 - int(numeric) % 97:02d}"


def build_cerfa(values, settings):
    if readiness(values):
        raise WorkspaceError("Complétez les informations du CERFA avant la télétransmission.")

    def address(prefix):
        return {"adresse1": values[prefix + "_address"], "adresse2": values.get(prefix + "_address_complement", ""),
                "codePostal": values[prefix + "_postcode"], "commune": values[prefix + "_city"]}

    def mapped(mapping):
        result = {}
        for target, source, kind in mapping:
            value = values.get(source)
            if value in (None, ""):
                continue
            result[target] = (value == "yes") if kind == "bool" else int(value) if kind == "int" else float(value) if kind == "float" else date_time(value) if kind == "date" else value
        return result

    employer = mapped([
        ("denomination", "employer_name", "text"), ("siret", "employer_siret", "text"), ("naf", "employer_ape", "text"),
        ("nombreDeSalaries", "employer_headcount", "int"), ("codeIdcc", "employer_idcc", "text"),
        ("telephone", "employer_phone", "text"), ("courriel", "employer_email", "text"),
        ("typeEmployeur", "employer_type", "int"), ("employeurSpecifique", "employer_specific", "int"),
        ("caisseComplementaire", "pension_fund", "text"), ("attestationEligibilite", "tutor_attestation", "bool"),
        ("attestationPieces", "documents_attestation", "bool")])
    employer.update(adresse=address("employer"), nom=settings["employer_last_name"], prenom=settings["employer_first_name"])
    if values.get("employer_sector") == "public" and values.get("employer_unemployment"):
        employer["regimeSpecifique"] = values["employer_unemployment"] == "yes"
    apprentice = mapped([
        ("nom", "apprentice_last_name", "text"), ("prenom", "apprentice_first_name", "text"), ("sexe", "apprentice_sex", "text"),
        ("nationalite", "apprentice_nationality", "int"), ("dateNaissance", "apprentice_birth_date", "date"),
        ("departementNaissance", "apprentice_birth_department", "text"), ("communeNaissance", "apprentice_birth_city", "text"),
        ("nir", "apprentice_nir", "text"), ("regimeSocial", "apprentice_social_regime", "int"), ("handicap", "apprentice_rqth", "bool"),
        ("situationAvantContrat", "apprentice_previous_situation", "int"), ("diplome", "apprentice_highest_diploma", "int"),
        ("derniereClasse", "apprentice_previous_class", "int"), ("diplomePrepare", "apprentice_previous_diploma", "int"),
        ("intituleDiplomePrepare", "apprentice_previous_diploma_title", "text"), ("telephone", "apprentice_phone", "text"),
        ("courriel", "apprentice_email", "text"), ("inscriptionSportifDeHautNiveau", "apprentice_high_level_athlete", "bool"),
        ("projetCreationRepriseEntreprise", "apprentice_business_project", "bool")])
    apprentice.update(adresse=address("apprentice"), nomUsage=values.get("apprentice_usage_name") or None)
    apprentice["nir"] = nir_with_key(values["apprentice_nir"])
    if values.get("apprentice_rqth") == "no":
        for key, source in (("droitsRqthExtensionBOE", "apprentice_rqth_boe"), ("droitsRqthEquivalenceJeune", "apprentice_rqth_young")):
            if values.get(source):
                apprentice[key] = values[source] == "yes"
    if needs_guardian(values):
        apprentice["responsableLegal"] = {"nom": settings["guardian_last_name"], "prenom": settings["guardian_first_name"],
            "courriel": values["guardian_email"], "adresse": address("guardian")}
    contract = mapped([
        ("modeContractuel", "contract_mode", "int"), ("typeContratApp", "contract_type", "int"),
        ("dateDebutContrat", "contract_start", "date"), ("dateFormationPratiqueEmployeur", "practical_start", "date"),
        ("dateConclusion", "contract_conclusion", "date"), ("dateFinContrat", "contract_end", "date"),
        ("lieuSignatureContrat", "signing_city", "text"), ("dureeTravailHebdoHeures", "weekly_hours", "int"),
        ("dureeTravailHebdoMinutes", "weekly_minutes", "int"), ("travailRisque", "hazardous_work", "bool"),
        ("salaireEmbauche", "gross_salary", "float"), ("avantageNourriture", "benefit_food", "float"),
        ("avantageLogement", "benefit_housing", "float"), ("autreAvantageEnNature", "benefit_other", "bool")])
    if values.get("contract_type", "").startswith(("2", "3")):
        contract["numeroContratPrecedent"] = values.get("previous_contract_number", "")
    if values.get("contract_type", "").startswith("3"):
        contract["dateEffetAvenant"] = date_time(values["amendment_date"])
    if values.get("contract_derogation") not in {None, "", "none"}:
        contract["typeDerogation"] = int(values["contract_derogation"])
    contract["remunerationsAnnuelles"] = []
    for year in range(1, 5):
        for period in (1, 2):
            prefix = f"salary_{year}_{period}_"
            if values.get(prefix + "start"):
                contract["remunerationsAnnuelles"].append({"ordre": f"{year}.{period}", "dateDebut": date_time(values[prefix + "start"]),
                    "dateFin": date_time(values[prefix + "end"]), "taux": float(values[prefix + "rate"]), "typeSalaire": values[prefix + "basis"]})
    formation = mapped([("rncp", "rncp", "text"), ("codeDiplome", "diploma_code", "text"), ("typeDiplome", "training_diploma_type", "int"),
        ("intituleQualification", "training_title", "text"), ("dateDebutFormation", "training_start", "date"),
        ("dateFinFormation", "exam_end", "date"), ("dureeFormation", "training_hours", "int"), ("nombreHeuresEnDistanciel", "remote_hours", "int")])
    formation["rncp"] = re.sub(r"^RNCP\s*", "", formation["rncp"], flags=re.I)
    cfa = mapped([("denomination", "cfa_name", "text"), ("formationInterne", "cfa_company", "bool"), ("siret", "cfa_siret", "text"),
                  ("uaiCfa", "cfa_uai", "text"), ("lieuFormationIdentique", "cfa_same_site", "bool")])
    cfa["adresse"] = address("cfa")
    cerfa = {"employeur": employer, "apprenti": apprentice, "formation": formation, "contrat": contract,
             "organismeFormation": cfa, "versionCERFA": "10103*14", "CERFASignatureProbante": True}
    for n, prefix in ((1, "tutor"), (2, "tutor2")):
        if n == 1 or values.get(prefix + "_last_name"):
            cerfa["maitre" + str(n)] = mapped([(dest, prefix + "_" + src, kind) for dest, src, kind in (
                ("nom", "last_name", "text"), ("prenom", "first_name", "text"), ("dateNaissance", "birth_date", "date"),
                ("courriel", "email", "text"), ("emploiOccupe", "job", "text"), ("intituleDiplomeObtenu", "diploma", "text"), ("niveauDiplomeObtenu", "level", "int"))])
    if values["cfa_same_site"] == "no":
        cerfa["organismeFormationLieuFormationPrincipal"] = {"denomination": values["site_name"], "siret": values["site_siret"], "adresse": address("site")}
        if values.get("site_uai"):
            cerfa["organismeFormationLieuFormationPrincipal"]["uaiCfa"] = values["site_uai"]
    return {"cerfa": cerfa}


class SubmissionClient(WedofClient):
    def call(self, method, path, payload=None, params=None):
        self._reserve(method, path, operation="bts_contract_submission" if method != "GET" else "bts_contract_check")
        try:
            response = self._session.request(method, WEDOF_BASE_URL + path, headers=self._mutation_headers,
                json=payload, params=params, timeout=(5, 25), allow_redirects=False)
        except requests.RequestException:
            raise WedofApiError("WEDOF n’a pas confirmé l’opération. Vérifiez son résultat avant de relancer.", ambiguous=method != "GET") from None
        if not 200 <= response.status_code < 300:
            message = f"WEDOF a refusé l’opération (HTTP {response.status_code})."
            # Validation paths are useful; do not retain raw invalid values or a
            # full server response containing NIR, contact details or credentials.
            try:
                data = response.json()
                errors = data.get("violations", data.get("errors", [])) if isinstance(data, dict) else []
                paths = []
                for err in errors if isinstance(errors, list) else []:
                    key = err.get("propertyPath", err.get("property", err.get("path", ""))) if isinstance(err, dict) else ""
                    if isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z_.\[\]0-9]{0,160}", key):
                        paths.append(key)
                if paths:
                    message += " Champs à vérifier : " + ", ".join(paths[:20])
            except ValueError:
                pass
            raise WedofApiError(message, http_status=response.status_code,
                                ambiguous=method != "GET" and response.status_code >= 500)
        try:
            return response.json()
        except ValueError:
            raise WedofApiError("La réponse WEDOF est illisible. Vérifiez le résultat avant de relancer.", ambiguous=method != "GET") from None


STEPS = ("certif_info", "training_id", "action_id", "session_id", "attendee_id", "folder_id", "contract_id", "validated", "sent")
STEP_LABELS = ("Certification", "Formation", "Action de formation", "Session", "Apprenti", "Dossier WEDOF", "Contrat WEDOF", "Validation OPCO", "Télétransmission")


def receipt(state, response):
    if response.get("state") not in {"sent", "pendingAcceptation", "accepted", "refused", "cancelled", "broken", "completed"}:
        raise WedofApiError("WEDOF n’a pas confirmé la télétransmission. Actualisez le résultat.", ambiguous=True)
    state.update(sent=True, sent_at=state.get("sent_at") or now(), remote_state=response["state"],
                 opco_reference=str(response.get("externalIdTrainingOrganism") or ""), manual_deposit=state.get("manual_deposit", False))
    state.pop("pending", None); state.pop("error", None)


def advance_submission(store, record_id, package, api, actor):
    state = package["opco"]
    if state.get("sent"):
        return {"done": True, "message": "Contrat déjà télétransmis. La convention reste à déposer sur le portail de l’OPCO."}
    if state.get("pending"):
        raise WorkspaceError("Une opération WEDOF reste à vérifier. Utilisez « Vérifier le résultat » avant de poursuivre.")
    if not package["signature"].get("completed_at") or package["signature"].get("status") != "done":
        raise WorkspaceError("Toutes les signatures doivent être confirmées avant la télétransmission.")
    ensure_files(store, package, signed=True)
    values, settings = package["values"], package["settings"]
    if settings.get("financer") not in FINANCERS:
        raise WorkspaceError("Choisissez l’OPCO destinataire et régénérez les documents avant signature.")
    raw = build_cerfa(values, settings)
    step = next(s for s in STEPS if not state.get(s))
    external = "IA-BTS-" + package["id"]
    if step == "certif_info":
        code = re.sub(r"^RNCP\s*", "", values["rncp"], flags=re.I)
        codes = api.call("GET", "/certifications/certifInfos/RNCP" + code, params={"enabled": "true"})
        if not isinstance(codes, list) or len(codes) != 1 or not str(codes[0]).isdigit():
            raise WorkspaceError("WEDOF ne renvoie pas une certification active unique pour ce RNCP. Vérifiez le code et le partenariat WEDOF.")
        state[step] = str(codes[0])
        store.save_package(record_id, package)
        return {"done": False, "message": "Certification vérifiée", "step": 1}
    requests_by_step = {
        "training_id": ("/trainings", {"title": values["training_title"], "certifInfo": state.get("certif_info"), "externalId": external}),
        "action_id": ("/trainingActions", {"trainingId": state.get("training_id"), "externalId": external,
            "teachingMethod": {"presentiel": "0", "hybride": "1", "distanciel": "2"}[settings["teaching_mode"]],
            "indicativeDuration": int(values["training_hours"]), "totalTvaTTC": tuition(settings) / 100,
            "location": {"roadName": values.get("site_address") if values.get("cfa_same_site") == "no" else values["cfa_address"],
                         "zipCode": values.get("site_postcode") if values.get("cfa_same_site") == "no" else values["cfa_postcode"],
                         "city": values.get("site_city") if values.get("cfa_same_site") == "no" else values["cfa_city"]}}),
        "session_id": ("/sessions", {"trainingActionId": state.get("action_id"), "externalId": external,
            "startDate": date_time(values["training_start"]), "endDate": date_time(values["exam_end"])}),
        "attendee_id": ("/attendees", {"lastName": values["apprentice_last_name"], "firstName": values["apprentice_first_name"],
            "email": values["apprentice_email"], "phoneNumber": values["apprentice_phone"].replace("+", "00"),
            "dateOfBirth": date_time(values["apprentice_birth_date"]), "gender": "male" if values["apprentice_sex"] == "M" else "female"}),
        "folder_id": ("/registrationFolders", {"sessionId": state.get("session_id"), "attendeeId": state.get("attendee_id"), "totalTTC": tuition(settings) / 100, "type": "opcoCfa"}),
        "contract_id": ("/workingContracts", {"registrationFolderExternalId": state.get("folder_id"), "type": values["contract_type"],
            "startDate": date_time(values["contract_start"]), "endDate": date_time(values["contract_end"]),
            "signedDate": date_time(package["signature"]["completed_at"][:10]), "financer": settings["financer"]}),
        "validated": (f"/workingContracts/{state.get('contract_id')}/submit", {"draftRawData": raw}),
        "sent": (f"/workingContracts/{state.get('contract_id')}/submit", {"draftRawData": raw}),
    }
    if step == "attendee_id":
        try:
            person = api.call("GET", "/attendees/" + quote(values["apprentice_email"], safe=""))
        except WedofApiError as exc:
            if exc.http_status != 404:
                raise
        else:
            from bts_inscriptions import normalize
            if not isinstance(person, dict) or any(normalize(person.get(k)) != normalize(values[f]) for k, f in (
                ("lastName", "apprentice_last_name"), ("firstName", "apprentice_first_name"), ("email", "apprentice_email"))):
                raise WorkspaceError("Cet e-mail est associé à une autre identité dans WEDOF. Vérifiez l’apprenti avant de poursuivre.")
            if person.get("dateOfBirth") and person["dateOfBirth"][:10] != values["apprentice_birth_date"]:
                raise WorkspaceError("La date de naissance de l’apprenti diffère dans WEDOF.")
            state[step] = int(identifier(person.get("id")))
            store.save_package(record_id, package)
            return {"done": False, "message": "Apprenti WEDOF identifié", "step": 5}
    path, payload = requests_by_step[step]
    state["pending"] = step
    store.save_package(record_id, package)
    try:
        response = api.call("POST", path, payload, params={"simulate": "true"} if step == "validated" else None)
        if not isinstance(response, dict):
            raise WedofApiError("Réponse WEDOF inattendue.", ambiguous=True)
        if step in {"validated", "sent"}:
            if str(response.get("id")) != str(state["contract_id"]) or response.get("financer") != settings["financer"]:
                raise WedofApiError("Le contrat retourné par WEDOF ne correspond pas au dossier.", ambiguous=True)
            if step == "sent" or response.get("state") != "draft":
                receipt(state, response)
            else:
                state["validated"] = True
        elif step == "folder_id":
            external_id = str(response.get("externalId") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", external_id) or response.get("type") != "opcoCfa":
                raise WedofApiError("Le dossier de formation WEDOF est inattendu.", ambiguous=True)
            state[step] = external_id
        else:
            try:
                state[step] = int(identifier(response.get("id")))
            except (WorkspaceError, WedofApiError, ValueError):
                # A successful POST with a missing id may already have created
                # the object. Keep its checkpoint instead of creating a duplicate.
                raise WedofApiError("WEDOF n’a pas renvoyé l’identifiant créé. Vérifiez le résultat avant de relancer.", ambiguous=True) from None
        state.pop("pending", None); state.pop("error", None)
        store.save_package(record_id, package, event="Contrat télétransmis via WEDOF ; convention à déposer manuellement" if state.get("sent") else None, actor=actor)
    except (WedofApiError, WorkspaceError) as exc:
        state["error"] = str(exc)
        if not getattr(exc, "ambiguous", False) or step == "validated":
            state.pop("pending", None)
        store.save_package(record_id, package)
        raise
    return {"done": bool(state.get("sent")), "message": "Contrat télétransmis. Déposez maintenant la convention sur le portail OPCO." if state.get("sent") else STEP_LABELS[STEPS.index(step)] + " : terminé", "step": STEPS.index(step) + 1}


def check_submission(store, record_id, package, api):
    state = package["opco"]
    if not state.get("contract_id"):
        raise WorkspaceError("Vérifiez dans WEDOF l’opération indiquée comme incertaine. Aucun nouvel envoi n’est lancé pour éviter un doublon.")
    response = api.call("GET", "/workingContracts/" + identifier(state["contract_id"]))
    if str(response.get("id")) != str(state["contract_id"]) or response.get("financer") != package["settings"]["financer"]:
        raise WorkspaceError("La réponse WEDOF ne correspond pas au contrat préparé.")
    state["checked_at"] = now()
    if response.get("state") != "draft":
        receipt(state, response)
        store.save_package(record_id, package, event="Résultat de télétransmission WEDOF vérifié")
        return "Télétransmission confirmée ; convention à déposer manuellement."
    store.save_package(record_id, package)
    return "WEDOF indique encore un brouillon. Un envoi incertain reste bloqué jusqu’à vérification de son résultat."
