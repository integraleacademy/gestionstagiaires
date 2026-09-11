"""CERFA 10103*14: explicit data entry, source prefill and completeness checks.

Codes follow notice 51649#09. This is preparation, not legal validation,
signature, salary calculation or transmission to an OPCO.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

NOTICE_URL = "https://www.formulaires.service-public.gouv.fr/gf/getNotice.do?cerfaNotice=51649&cerfaFormulaire=10103"
YES_NO = (("yes", "Oui"), ("no", "Non"))
DIPLOMAS = tuple((str(k), v) for k, v in (
    (80, "Doctorat"), (73, "Master"), (75, "Diplôme d’ingénieur"), (76, "Diplôme d’école de commerce"),
    (79, "Autre diplôme bac +5 ou plus"), (62, "Licence professionnelle"), (63, "Licence générale"),
    (64, "BUT"), (69, "Autre diplôme bac +3 ou 4"), (54, "BTS"), (55, "DUT"), (58, "Autre diplôme bac +2"),
    (41, "Baccalauréat professionnel"), (42, "Baccalauréat général"), (43, "Baccalauréat technologique"),
    (44, "Diplôme de spécialisation professionnelle"), (49, "Autre diplôme de niveau bac"), (33, "CAP"),
    (34, "BEP"), (35, "Certificat de spécialisation"), (38, "Autre diplôme CAP/BEP"),
    (25, "Brevet"), (26, "Certificat de formation générale"), (13, "Aucun diplôme ni titre professionnel")))
LEVELS = tuple((str(k), v) for k, v in ((3, "CAP / BEP"), (4, "Baccalauréat"), (5, "BTS / DUT / DEUST"),
                                        (6, "Licence / BUT / maîtrise"), (7, "Master / ingénieur"), (8, "Doctorat")))


def field(key, label, kind="text", *, required=False, options=(), limit=150, help=""):
    return {"key": key, "label": label, "kind": "select" if options else kind,
            "required": required, "options": options, "limit": limit, "help": help}


def address(prefix, *, required=True):
    return [field(prefix + "_address", "Adresse (numéro et voie)", required=required),
            field(prefix + "_address_complement", "Complément d’adresse"),
            field(prefix + "_postcode", "Code postal", required=required, limit=10),
            field(prefix + "_city", "Commune", required=required)]


def section(key, label, fields, *, help="", condition=None, optional=False):
    return {"key": key, "label": label, "fields": fields, "help": help,
            "condition": condition, "optional": optional}


SECTIONS = {
    "etudiant": [
        section("identity", "Identité et coordonnées", [
            field("apprentice_last_name", "Nom de naissance", required=True),
            field("apprentice_first_name", "Premier prénom de l’état civil", required=True),
            field("apprentice_usage_name", "Nom d’usage"),
            field("apprentice_birth_date", "Date de naissance", "date", required=True),
            field("apprentice_nir", "NIR (13 caractères, sans la clé)", required=True, limit=13,
                  help="Renseigné pour le CERFA ; absent de l’export général et de l’historique."),
            field("apprentice_sex", "Sexe indiqué sur le CERFA", required=True, options=(("M", "Masculin"), ("F", "Féminin"))),
            field("apprentice_birth_department", "Département de naissance", required=True, limit=3, help="099 pour une naissance à l’étranger."),
            field("apprentice_birth_city", "Commune de naissance", required=True),
            field("apprentice_nationality", "Nationalité", required=True,
                  options=(("1", "Française"), ("2", "Union européenne"), ("3", "Hors Union européenne"))),
            field("apprentice_social_regime", "Régime social", required=True, options=(("1", "MSA"), ("2", "URSSAF"))),
            *address("apprentice"), field("apprentice_phone", "Téléphone", "tel", required=True, limit=30),
            field("apprentice_email", "Adresse e-mail", "email", required=True)]),
        section("background", "Parcours et situation", [
            field("apprentice_previous_situation", "Situation avant ce contrat", required=True, options=tuple((str(i), v) for i, v in enumerate((
                "Scolaire", "Prépa apprentissage", "Étudiant", "Contrat d’apprentissage", "Contrat de professionnalisation",
                "Contrat aidé", "Stagiaire en CFA avant conclusion du contrat", "Stagiaire en CFA après rupture d’un contrat",
                "Autre stagiaire de la formation professionnelle", "Salarié", "En recherche d’emploi", "Inactif"), 1))),
            field("apprentice_previous_diploma", "Dernier diplôme ou titre préparé", required=True, options=DIPLOMAS),
            field("apprentice_previous_class", "Dernière classe ou année suivie", required=True, options=(
                ("01", "Dernière année validée et diplôme obtenu"), ("11", "1re année validée"), ("12", "1re année non validée"),
                ("21", "2e année validée"), ("22", "2e année non validée"), ("31", "3e année validée"), ("32", "3e année non validée"),
                ("40", "Collège achevé"), ("41", "Études interrompues en 3e"), ("42", "Études interrompues en 4e"))),
            field("apprentice_previous_diploma_title", "Intitulé du dernier diplôme ou titre préparé", required=True),
            field("apprentice_highest_diploma", "Diplôme ou titre le plus élevé obtenu", required=True, options=DIPLOMAS),
            field("apprentice_high_level_athlete", "Sportif de haut niveau", required=True, options=YES_NO),
            field("apprentice_rqth", "Reconnaissance de travailleur handicapé (RQTH)", required=True, options=YES_NO),
            field("apprentice_rqth_young", "Droits RQTH : équivalence jeunes", options=YES_NO, help="À renseigner si la réponse RQTH est Non."),
            field("apprentice_rqth_boe", "Droits RQTH : extension BOE", options=YES_NO, help="À renseigner si la réponse RQTH est Non."),
            field("apprentice_business_project", "Projet de création ou de reprise d’entreprise", required=True, options=YES_NO),
            field("apprentice_emancipated", "Si mineur : apprenti émancipé", options=YES_NO)]),
        section("guardian", "Représentant légal", [field("guardian_name", "Nom de naissance et prénom du représentant", required=True),
            *address("guardian"), field("guardian_email", "E-mail du représentant légal", "email", required=True)],
            help="Pour un apprenti mineur non émancipé à la conclusion du contrat.", condition="guardian"),
    ],
    "entreprise": [
        section("employer", "Établissement d’exécution du contrat", [
            field("employer_name", "Raison sociale ou nom de l’employeur", required=True),
            field("employer_siret", "SIRET", required=True, limit=14),
            field("employer_sector", "Secteur de l’employeur", required=True, options=(("private", "Privé"), ("public", "Public"))),
            field("employer_type", "Type d’employeur", required=True, options=tuple((str(k), v) for k, v in (
                (11, "Entreprise inscrite au répertoire des métiers"), (12, "Entreprise inscrite uniquement au RCS"),
                (13, "Entreprise relevant de la MSA"), (14, "Profession libérale"), (15, "Association"), (16, "Autre employeur privé"),
                (21, "Service de l’État"), (22, "Commune"), (23, "Département"), (24, "Région"),
                (25, "Établissement public hospitalier"), (26, "Établissement public local d’enseignement"),
                (27, "Établissement public administratif de l’État"), (28, "Établissement public administratif local"),
                (29, "Autre employeur public"), (30, "Établissement public industriel et commercial")))),
            field("employer_specific", "Employeur spécifique", required=True, options=(("0", "Aucun de ces cas"),
                ("1", "Entreprise de travail temporaire"), ("2", "Groupement d’employeurs"), ("3", "Employeur saisonnier"), ("4", "Apprentissage familial"))),
            field("employer_ape", "Code APE / NAF", required=True, limit=6),
            field("employer_headcount", "Effectif total de l’entreprise", "integer", required=True),
            field("employer_idcc", "Code IDCC", required=True, limit=4), *address("employer"),
            field("employer_phone", "Téléphone de l’entreprise", "tel", required=True, limit=30),
            field("employer_email", "E-mail de l’entreprise", "email", required=True),
            field("employer_unemployment", "Employeur public : adhésion au régime spécifique d’assurance chômage", options=YES_NO),
            field("pension_fund", "Caisse de retraite complémentaire", required=True)],
            help="Renseignez l’établissement où le contrat est exécuté."),
        *[section("tutor" + str(n), "Maître d’apprentissage n° " + str(n), [
            field(prefix + "_last_name", "Nom de naissance du maître n° " + str(n), required=True),
            field(prefix + "_first_name", "Prénom du maître n° " + str(n), required=True),
            field(prefix + "_birth_date", "Date de naissance du maître n° " + str(n), "date", required=True),
            field(prefix + "_email", "E-mail du maître n° " + str(n), "email", required=True),
            field(prefix + "_job", "Emploi occupé par le maître n° " + str(n), required=True),
            field(prefix + "_diploma", "Diplôme le plus élevé du maître n° " + str(n), required=True),
            field(prefix + "_level", "Niveau du diplôme du maître n° " + str(n), required=True, options=LEVELS)],
            optional=n == 2, condition="tutor2" if n == 2 else None)
          for n, prefix in ((1, "tutor"), (2, "tutor2"))],
    ],
    "contrat": [
        section("training", "Formation préparée", [
            field("training_title", "Intitulé du BTS", required=True), field("rncp", "Code RNCP", required=True, limit=9),
            field("diploma_code", "Code diplôme", required=True, limit=8),
            field("training_diploma_type", "Diplôme ou titre visé", required=True, options=DIPLOMAS),
            field("training_start", "Début de formation en CFA", "date", required=True),
            field("training_end", "Fin de formation", "date", help="Conservée dans le dossier ; distincte de la date des examens."),
            field("exam_end", "Date prévue de fin des épreuves ou examens", "date", required=True),
            field("training_hours", "Durée de formation (heures)", "integer", required=True),
            field("remote_hours", "Dont formation à distance (heures)", "integer", required=True)]),
        section("agreement", "Conditions du contrat", [
            field("contract_mode", "Mode contractuel de l’apprentissage", required=True, options=(("1", "À durée limitée"),
                ("2", "Dans le cadre d’un CDI"), ("3", "Travail temporaire"), ("4", "Saisonnier à deux employeurs"))),
            field("contract_type", "Type de contrat ou d’avenant", required=True, options=tuple((str(k), v) for k, v in (
                (11, "Premier contrat d’apprentissage"), (21, "Succession : même employeur"), (22, "Succession : autre employeur"),
                (23, "Nouveau contrat après rupture"), (31, "Avenant : situation juridique de l’employeur"),
                (32, "Avenant : employeur saisonnier"), (33, "Avenant : échec à l’examen"), (34, "Avenant : reconnaissance handicap"),
                (35, "Avenant : diplôme supplémentaire"), (36, "Avenant : autres changements"),
                (37, "Avenant : lieu d’exécution"), (38, "Avenant : lieu de formation théorique")))),
            field("contract_derogation", "Dérogation éventuelle", options=(("none", "Aucune dérogation"),
                ("11", "Âge inférieur à 16 ans"), ("12", "Âge supérieur à 29 ans : cas spécifiques"),
                ("21", "Réduction de durée"), ("22", "Allongement de durée"), ("50", "Cumul de dérogations"), ("60", "Autre dérogation"))),
            field("previous_contract_number", "Numéro du contrat précédent ou concerné par l’avenant", limit=50),
            field("contract_conclusion", "Date de conclusion", "date", required=True),
            field("contract_start", "Début du contrat", "date", required=True),
            field("practical_start", "Début de formation pratique chez l’employeur", "date", required=True),
            field("amendment_date", "Si avenant : date d’effet", "date"),
            field("contract_end", "Fin du contrat ou de la période d’apprentissage", "date", required=True),
            field("weekly_hours", "Durée hebdomadaire : heures", "integer", required=True),
            field("weekly_minutes", "Durée hebdomadaire : minutes", "integer", required=True),
            field("hazardous_work", "Machines dangereuses ou risques particuliers", required=True, options=YES_NO)]),
        section("salary", "Rémunération et avantages", [
            field("gross_salary", "Salaire brut mensuel à l’embauche (€)", "decimal", required=True),
            field("benefit_food", "Nourriture (€ par repas)", "decimal"), field("benefit_housing", "Logement (€ par mois)", "decimal"),
            field("benefit_other", "Autre avantage en nature", options=YES_NO)],
            help="Reprenez les montants et taux convenus avec l’employeur. Aucun salaire n’est calculé ou supposé."),
        *[section("salary" + str(year), "Rémunération · année " + str(year), [
            field(f"salary_{year}_{period}_{part}", f"Période {period} · {label}", kind, options=options)
            for period in (1, 2) for part, label, kind, options in (
                ("start", "du", "date", ()), ("end", "au", "date", ()), ("rate", "taux (%)", "decimal", ()),
                ("basis", "base de calcul", "text", (("SMIC", "SMIC"), ("SMC", "SMC"))))],
            help="Deux périodes sont prévues si le taux change en cours d’année.", optional=year > 1)
          for year in range(1, 5)],
        section("cfa", "CFA responsable", [field("cfa_company", "CFA d’entreprise", required=True, options=YES_NO),
            field("cfa_name", "Dénomination du CFA responsable", required=True),
            field("cfa_uai", "UAI du CFA", required=True, limit=8), field("cfa_siret", "SIRET du CFA", required=True, limit=14),
            *address("cfa"), field("cfa_same_site", "Le CFA responsable est le lieu principal de formation", required=True, options=YES_NO)]),
        section("site", "Lieu principal de formation distinct", [field("site_name", "Dénomination du lieu de formation", required=True),
            field("site_uai", "UAI du lieu de formation", limit=8), field("site_siret", "SIRET du lieu de formation", required=True, limit=14),
            *address("site")], condition="site", help="À compléter lorsque la formation se déroule dans un autre établissement."),
        section("statements", "Lieu et déclarations de l’employeur", [
            field("signing_city", "Fait à", required=True),
            field("tutor_attestation", "L’employeur atteste de l’éligibilité du maître d’apprentissage", "attestation", required=True),
            field("documents_attestation", "L’employeur atteste disposer des pièces justificatives nécessaires au dépôt", "attestation", required=True)],
            help="Cochez uniquement les déclarations confirmées par l’employeur. Le visa du CFA et les signatures seront recueillis sur le contrat."),
    ],
}
FIELDS = {f["key"]: {**f, "tab": tab, "section": s["key"]} for tab, groups in SECTIONS.items() for s in groups for f in s["fields"]}
PRIVATE_FIELDS = {"apprentice_nir", "apprentice_rqth", "apprentice_rqth_young", "apprentice_rqth_boe"}


class CerfaValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Vérifiez les champs signalés avant d’enregistrer.")


def clean(value):
    return "" if value is None else str(value).strip()


def source_values(record):
    payload = record.get("source_payload")
    values = prefill_opco(payload.get("cerfa")) if isinstance(payload, dict) else {}
    values.update({k: clean(v) for k, v in (record.get("cerfa_prefill") or {}).items() if k in FIELDS and k not in PRIVATE_FIELDS})
    # Existing fields are authoritative for the information already shown in the tabs.
    for key in FIELDS:
        if key not in PRIVATE_FIELDS and key in record and record[key] is not None and record[key] != "":
            values[key] = clean(record[key])
    for prefix in ("employer", "apprentice"):
        complement = values.get(prefix + "_address_complement", "")
        key = prefix + "_address"
        if complement and values.get(key, "").endswith(" " + complement):
            values[key] = values[key][:-(len(complement) + 1)]
    return values


def source_version(record):
    return hashlib.sha256(json.dumps(source_values(record), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def effective_values(record, complements):
    return {**source_values(record), **{k: clean(v) for k, v in complements.items() if k in FIELDS}}


def validate_values(submitted):
    result, errors = {}, {}
    for key, raw in submitted.items():
        if key not in FIELDS:
            continue
        f, value = FIELDS[key], clean(raw)
        if not value:
            result[key] = ""
            continue
        if len(value) > f["limit"] or any(ord(c) < 32 for c in value):
            errors[key] = "Texte trop long ou contenant des caractères non autorisés."
        elif f["kind"] == "select" and value not in dict(f["options"]):
            errors[key] = "Choisissez une valeur de la liste."
        elif f["kind"] == "attestation" and value != "yes":
            errors[key] = "Déclaration invalide."
        elif f["kind"] == "date":
            try:
                value = dt.date.fromisoformat(value).isoformat()
            except ValueError:
                errors[key] = "Date invalide."
        elif f["kind"] in {"integer", "decimal"}:
            try:
                number = Decimal(value.replace(" ", "").replace("\u00a0", "").replace(",", "."))
                if not number.is_finite() or number < 0 or number > 10000000:
                    raise InvalidOperation
                if f["kind"] == "integer" and number != number.to_integral():
                    raise InvalidOperation
                if number != number.quantize(Decimal(".01")):
                    raise InvalidOperation
                value = str(int(number)) if f["kind"] == "integer" else format(number, "f")
                if key == "weekly_minutes" and number > 59 or key == "weekly_hours" and number > 168:
                    raise InvalidOperation
                if key.endswith("_rate") and not 0 < number <= 1000:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                errors[key] = "Valeur numérique invalide."
        elif f["kind"] == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            errors[key] = "Adresse e-mail invalide."
        if key.endswith("_siret"):
            value = re.sub(r"\s", "", value)
            if not re.fullmatch(r"\d{14}", value):
                errors[key] = "Le SIRET doit contenir 14 chiffres."
        if key.endswith("_uai"):
            value = value.upper()
            if not re.fullmatch(r"\d{7}[A-Z]", value):
                errors[key] = "L’UAI doit contenir 7 chiffres et une lettre."
        if key == "apprentice_nir":
            value = re.sub(r"\s", "", value).upper()
            if not re.fullmatch(r"[0-9AB]{13}", value):
                errors[key] = "Saisissez les 13 caractères du NIR, sans la clé."
        if key == "rncp":
            value = re.sub(r"^RNCP\s*", "", value.upper())
            if not re.fullmatch(r"\d{3,5}", value):
                errors[key] = "Code RNCP attendu : 3 à 5 chiffres, avec ou sans le préfixe RNCP."
        if key == "employer_ape":
            value = value.replace(".", "").upper()
            if not re.fullmatch(r"\d{4}[A-Z]", value):
                errors[key] = "Code APE attendu : 4 chiffres et une lettre."
        if key == "employer_idcc" and not re.fullmatch(r"\d{4}", value):
            errors[key] = "Le code IDCC doit contenir 4 chiffres."
        result[key] = value
    if errors:
        raise CerfaValidationError(errors)
    return result


def active_section(section, values):
    condition = section.get("condition")
    if condition == "guardian":
        try:
            birth, signing = (dt.date.fromisoformat(values[k]) for k in ("apprentice_birth_date", "contract_conclusion"))
            age = signing.year - birth.year - ((signing.month, signing.day) < (birth.month, birth.day))
            return age < 18 and values.get("apprentice_emancipated") != "yes"
        except (KeyError, ValueError):
            return True
    if condition == "site":
        return values.get("cfa_same_site") != "yes"
    if condition == "tutor2":
        return any(values.get(f["key"]) for f in section["fields"])
    return True


def readiness(values):
    missing = {}
    for groups in SECTIONS.values():
        for s in groups:
            if not active_section(s, values):
                continue
            for f in s["fields"]:
                if f["required"] and not values.get(f["key"]):
                    missing[f["key"]] = "À compléter"
    if values.get("apprentice_rqth") == "no":
        for key in ("apprentice_rqth_young", "apprentice_rqth_boe"):
            if not values.get(key):
                missing[key] = "Précisez les droits attachés à la RQTH."
    if values.get("contract_type", "").startswith(("2", "3")) and not values.get("previous_contract_number"):
        missing["previous_contract_number"] = "Renseignez le contrat précédent ou concerné par l’avenant."
    if values.get("contract_type", "").startswith("3") and not values.get("amendment_date"):
        missing["amendment_date"] = "Date d’effet de l’avenant à compléter."
    for start, end in (("contract_start", "contract_end"), ("training_start", "training_end"), ("training_start", "exam_end")):
        if values.get(start) and values.get(end) and values[start] > values[end]:
            missing[end] = "La fin précède le début."
    try:
        if values.get("remote_hours") and values.get("training_hours") and Decimal(values["remote_hours"]) > Decimal(values["training_hours"]):
            missing["remote_hours"] = "Le distanciel dépasse la durée totale de formation."
    except InvalidOperation:
        pass
    if values.get("employer_sector") and values.get("employer_type", "").isdigit():
        is_public = int(values["employer_type"]) >= 21
        if is_public != (values["employer_sector"] == "public"):
            missing["employer_type"] = "Le type d’employeur ne correspond pas au secteur choisi."
    periods = []
    for year in range(1, 5):
        for period in (1, 2):
            prefix = f"salary_{year}_{period}_"
            keys = [prefix + k for k in ("start", "end", "rate", "basis")]
            if not any(values.get(k) for k in keys):
                continue
            for key in keys:
                if not values.get(key):
                    missing[key] = "Complétez les quatre informations de cette période."
            start, end = values.get(keys[0]), values.get(keys[1])
            if start and end:
                if start > end:
                    missing[keys[1]] = "La fin précède le début."
                if values.get("contract_start") and start < values["contract_start"] or values.get("contract_end") and end > values["contract_end"]:
                    missing[keys[0]] = "La période doit se trouver dans les dates du contrat."
                periods.append((start, end, keys[0]))
    if not periods:
        missing["salary_1_1_start"] = "Renseignez les périodes de rémunération prévues au contrat."
    else:
        periods.sort()
        if values.get("contract_start") and periods[0][0] != values["contract_start"]:
            missing[periods[0][2]] = "La rémunération doit couvrir le début du contrat."
        if values.get("contract_end") and periods[-1][1] != values["contract_end"]:
            missing[periods[-1][2]] = "La rémunération doit couvrir la fin du contrat."
        for previous, current in zip(periods, periods[1:]):
            try:
                if dt.date.fromisoformat(previous[1]) + dt.timedelta(days=1) != dt.date.fromisoformat(current[0]):
                    missing[current[2]] = "Vérifiez la continuité des périodes de rémunération."
            except ValueError:
                missing[current[2]] = "Date de période invalide."
    return missing


def cerfa_view(record, saved, *, form_values=None, errors=None):
    values = effective_values(record, saved.get("values", {}))
    if form_values is not None:
        values.update({k: clean(v) for k, v in form_values.items() if k in FIELDS})
    missing = readiness(values)
    groups = []
    for tab, label in (("etudiant", "Étudiant"), ("entreprise", "Entreprise"), ("contrat", "Contrat et formation")):
        todo = [{"key": k, "label": FIELDS[k]["label"], "message": message} for k, message in missing.items() if FIELDS[k]["tab"] == tab]
        groups.append({"tab": tab, "label": label, "missing": todo})
    return {"values": values, "source": source_values(record), "revision": saved.get("revision", 0),
            "source_version": source_version(record), "sections": SECTIONS, "groups": groups, "missing": missing,
            "errors": errors or {}, "ready": not missing, "notice_url": NOTICE_URL,
            "field_count": sum(bool(values.get(k)) for k in FIELDS),
            "saved_at": saved.get("updated_at", "")}


def prefill_opco(cerfa):
    """Explicit, non-sensitive allowlist; never copy an unrestricted source CERFA.

    NIR, health responses and employer attestations remain explicit local inputs.
    Previously imported records gain these extra defaults on targeted refresh only.
    """
    if not isinstance(cerfa, dict):
        return {}
    result = {}

    def source_object(name):
        for key in (name, name + "V2"):
            if isinstance(cerfa.get(key), dict):
                return cerfa[key]
        return {}

    mappings = {
        "apprenti": {"nomUsage": "apprentice_usage_name", "communeNaissance": "apprentice_birth_city",
            "departementNaissance": "apprentice_birth_department", "nationalite": "apprentice_nationality",
            "regimeSocial": "apprentice_social_regime", "situationAvantContrat": "apprentice_previous_situation",
            "diplomePrepare": "apprentice_previous_diploma", "intituleDiplomePrepare": "apprentice_previous_diploma_title",
            "diplome": "apprentice_highest_diploma", "derniereClasse": "apprentice_previous_class",
            "inscriptionSportifDeHautNiveau": "apprentice_high_level_athlete", "projetCreationRepriseEntreprise": "apprentice_business_project"},
        "employeur": {"typeEmployeur": "employer_type", "employeurSpecifique": "employer_specific",
            "naf": "employer_ape", "nombreDeSalaries": "employer_headcount", "codeIdcc": "employer_idcc",
            "regimeSpecifique": "employer_unemployment", "caisseComplementaire": "pension_fund"},
        "contrat": {"modeContractuel": "contract_mode", "typeContratApp": "contract_type",
            "numeroContratPrecedent": "previous_contract_number", "dateFormationPratiqueEmployeur": "practical_start",
            "dateEffetAvenant": "amendment_date", "lieuSignatureContrat": "signing_city", "typeDerogation": "contract_derogation",
            "dureeTravailHebdoHeures": "weekly_hours", "dureeTravailHebdoMinutes": "weekly_minutes",
            "travailRisque": "hazardous_work", "avantageNourriture": "benefit_food", "avantageLogement": "benefit_housing",
            "autreAvantageEnNature": "benefit_other"},
        "formation": {"typeDiplome": "training_diploma_type"},
        "organismeFormation": {"denomination": "cfa_name", "siret": "cfa_siret", "uaiCfa": "cfa_uai",
            "formationInterne": "cfa_company", "lieuFormationIdentique": "cfa_same_site"},
        "organismeFormationLieuFormationPrincipal": {"denomination": "site_name", "siret": "site_siret", "uaiCfa": "site_uai"},
    }
    for source, prefix in (("maitre1", "tutor"), ("maitre2", "tutor2")):
        mappings[source] = {"nom": prefix + "_last_name", "prenom": prefix + "_first_name", "dateNaissance": prefix + "_birth_date",
            "courriel": prefix + "_email", "emploiOccupe": prefix + "_job", "intituleDiplomeObtenu": prefix + "_diploma",
            "niveauDiplomeObtenu": prefix + "_level"}
    for source, keys in mappings.items():
        obj = source_object(source)
        for source_key, key in keys.items():
            value = obj.get(source_key)
            if value is None or isinstance(value, (dict, list)):
                continue
            result[key] = ("yes" if value else "no") if isinstance(value, bool) else clean(value)
            if FIELDS[key]["kind"] == "date":
                result[key] = result[key][:10]
    sex = source_object("apprenti").get("sexe")
    if sex in ("M", "F", 1, 2, "1", "2"):
        result["apprentice_sex"] = "M" if sex in ("M", 1, "1") else "F"
    if result.get("employer_type", "").isdigit():
        result["employer_sector"] = "public" if int(result["employer_type"]) >= 21 else "private"
    if result.get("employer_idcc", "").isdigit():
        result["employer_idcc"] = result["employer_idcc"].zfill(4)
    guardian = source_object("apprenti").get("responsableLegal")
    if isinstance(guardian, dict):
        result["guardian_name"] = " ".join(filter(None, (clean(guardian.get("nom")), clean(guardian.get("prenom")))))
        result["guardian_email"] = clean(guardian.get("courriel"))
    for source, prefix in (("employeur", "employer"), ("apprenti", "apprentice"), ("organismeFormation", "cfa"),
                           ("organismeFormationLieuFormationPrincipal", "site"), ("responsableLegal", "guardian")):
        obj = guardian if prefix == "guardian" else source_object(source)
        address = obj.get("adresse") if isinstance(obj, dict) else None
        if not isinstance(address, dict):
            continue
        result[prefix + "_address_complement"] = clean(address.get("complement") or address.get("adresse2"))
        if prefix in {"cfa", "site", "guardian"}:
            result[prefix + "_address"] = clean(address.get("adresse1")) or " ".join(filter(None, (clean(address.get("numero")), clean(address.get("voie")))))
            result[prefix + "_postcode"] = clean(address.get("codePostal"))
            result[prefix + "_city"] = clean(address.get("commune"))
    periods = source_object("contrat").get("remunerationsAnnuelles")
    for line in periods if isinstance(periods, list) else []:
        if not isinstance(line, dict) or not re.fullmatch(r"[1-4]\.[12]", clean(line.get("ordre"))):
            continue
        prefix = "salary_" + clean(line["ordre"]).replace(".", "_") + "_"
        for source_key, target in (("dateDebut", "start"), ("dateFin", "end"), ("taux", "rate"), ("typeSalaire", "basis")):
            value = clean(line.get(source_key))
            result[prefix + target] = value[:10] if target in {"start", "end"} else value
    result = {k: v for k, v in result.items() if v != ""}
    # Invalid optional defaults never prevent importing the actual OPCO dossier.
    try:
        return validate_values(result)
    except CerfaValidationError as exc:
        return validate_values({k: v for k, v in result.items() if k not in exc.errors})
