"""Editable terms of an EDOF inscription proposal. The catalogue and holder stay untouched."""
import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from edof_directory import FIRST_SESSION, session_date

DATES = {"sessionStartDate":"Début de session", "sessionEndDate":"Fin de session"}
HOURS = {"indicativeDuration":"Durée totale", "weeklyDuration":"Intensité hebdomadaire",
         "hoursInCenter":"Heures en centre", "hoursInCompany":"Heures en entreprise"}
PRICES = {"vat":"Montant net de TVA", "vatInclTax5":"Montant TTC à 5,5 %", "vatInclTax20":"Montant TTC à 20 %",
          "montantFraisCertificationInclus":"Frais d’examen inclus (TTC)", "additionalFees":"Frais annexes à la charge du titulaire"}
TEXTS = {"title":"Intitulé de la formation", "trainingGoal":"Objectif pédagogique",
         "expectedResult":"Résultats attendus", "content":"Contenu de la formation",
         "additionalFeesDetails":"Détail des frais annexes", "codeRNCP":"Code RNCP", "intituleRNCP":"Intitulé RNCP"}
ADDRESS = {"number":"Numéro", "repetitionIndex":"Indice de répétition", "roadType":"Type de voie", "roadName":"Nom de la voie",
           "residence":"Résidence ou bâtiment", "additionalAddress":"Complément d’adresse", "postBox":"Boîte postale",
           "zipCode":"Code postal", "city":"Commune", "countryCode":"Pays"}
ENUMS = {"typeOfTrainingCourse":"training-course-types", "teachingModalities":"teaching-modalities",
         "trainingPaces":"action-paces", "roadType":"address-road-types", "countryCode":"address-countries",
         "repetitionIndex":"address-repetition-indexes"}
EXAM = {"INCLUDED":"Inclus dans le prix", "NOT_INCLUDED":"À la charge du titulaire", "NONE":"Aucuns frais d’examen"}
# The portal PUTs its registration-folder DTO. Extra detail-response fields do not belong in an edit.
ENVELOPE = ("id","trainingActionInfo","currentState","changingStateDate","hasBeenOpened","states","trainingActionId",
            "trainingId","history","currentBillingState","billingDate","attendee","cancellation","refusedMotif",
            "idSuiviFinancement","beginDate","endDate","paymentState","codeTitulaire","minDate","ableToValidate",
            "certification","codeReconnaissance","codeReferentiel","franceCompetenceUrl","qualiopiCertification",
            "habilitationAFormer","etatBlocage","isBlocageOf","certificationSanction","doneDeclaredRevision")
HOLDER = ("civility","lastName","firstName","birthDate","birthPlace","statusPoleEmployment","displayName","degreeTitle",
          "phoneNumber","email","completeAdress","address","phoneFixed","isTitulaireMineur")
SINGLES = (*DATES, *HOURS, *PRICES, *TEXTS, *ADDRESS, "teachingModalities", "typeOfTrainingCourse","exam")
PARIS = ZoneInfo("Europe/Paris")


class InvalidTerms(ValueError):
    pass


def scalar(value):
    return str(value).strip() if isinstance(value, (str, int, float, Decimal)) and not isinstance(value, bool) else ""


def number_string(value):
    if value is None or value == "":
        return ""
    try:
        n = Decimal(scalar(value).replace(",", "."))
        if n.is_finite() and 0 <= n <= 10000000 and (not n or n.adjusted() >= -8):
            return format(n.normalize(), "f")
    except InvalidOperation:
        pass
    raise InvalidTerms("EDOF a renvoyé un montant ou une durée illisible.")


def project(raw):
    action = raw.get("trainingActionInfo") or {}
    place = action.get("address") or {}
    values = {k:scalar(action.get(k)) for k in TEXTS}
    values.update({k:scalar(place.get(k)) for k in ADDRESS})
    values.update({k:session_date(action.get(k)) for k in DATES})
    values.update({k:number_string(action.get(k)) for k in (*HOURS, *PRICES)})
    values.update({k:scalar(action.get(k)) for k in ("teachingModalities","typeOfTrainingCourse")})
    values["exam"] = scalar(action.get("doesPriceIncludeMontantFraisExam"))
    if values["exam"] not in EXAM:
        present = action.get("presenceFraisCertification")
        values["exam"] = ("NONE" if present is False else ("INCLUDED" if action.get("fraisCertificationInclus") else "NOT_INCLUDED")
                          if present is True else "")
    values["trainingPaces"] = sorted(scalar(k) for k in action.get("trainingPaces") or [])
    blocks = action.get("infosBlocsCompetences") or {}
    selected = blocks.get("blocsRetenus") or []
    options = {scalar(b.get("code")):scalar(b.get("libelle")) for b in [*selected, *(blocks.get("blocsExclus") or [])] if b.get("code")}
    values["blocks"] = sorted(scalar(b["code"]) for b in selected if b.get("code"))
    refs = [scalar(raw.get(k)) for k in ("trainingId","trainingActionId")] + [scalar(action.get("sessionId"))]
    signature = hashlib.sha256(json.dumps([raw["id"],refs,values,options,number_string(action.get("totalIncl"))],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {"values":values,"total":number_string(action.get("totalIncl")), "signature":signature,"minimum":session_date(raw.get("minDate")),
            "blocks":options,"editable_blocks":bool(blocks.get("blocsModifiables")),
            "prerequisites":scalar(action.get("conditionsPrerequisitesDetails")),
            "rncp":bool(action.get("codeRNCP") or raw.get("codeReconnaissance") == "CPF200")}


def initial(row):
    values = {k:"" for k in SINGLES}
    values.update(title=row.get("title") or "", sessionStartDate=row.get("session_start_date") or "",
                  sessionEndDate=row.get("session_end_date") or "", trainingPaces=[],blocks=[],priceTotal="")
    values.update(row.get("offer_summary") or {})
    return values


def displayed(source, row):
    values = initial(row)
    if source:
        values.update({k:v for k,v in source["values"].items() if v != ""})
        amounts = [source["values"].get(k) for k in ("vat","vatInclTax5","vatInclTax20")]
        if source.get("total"):
            values["priceTotal"] = source["total"]
        elif any(v not in ("", None) for v in amounts):
            values["priceTotal"] = number_string(sum(Decimal(v or "0") for v in amounts))
    for key in ("priceTotal","indicativeDuration","weeklyDuration"):
        if re.fullmatch(r"0+(?:[.,]0+)?", scalar(values.get(key))):
            values[key] = ""
    return values


def form_values(form):
    result = {k:form.get(k,"").strip() for k in SINGLES}
    result["priceTotal"] = form.get("priceTotal","").strip()
    for key in ("blocks","trainingPaces"):
        result[key] = sorted(set(form.getlist(key)))
    return result


def validate(values, source, options):
    """Return normalized terms or field-specific messages before either official write."""
    v = dict(values)
    for key, label in DATES.items():
        day = session_date(v[key])
        if not day or day != v[key]:
            raise InvalidTerms(f"{label} : renseignez une date valide.")
    minimum = max(FIRST_SESSION, dt.datetime.now(PARIS).date().isoformat(), source.get("minimum") or "")
    if v["sessionStartDate"] < minimum:
        raise InvalidTerms("Le début de session doit être au plus tôt le "+dt.date.fromisoformat(minimum).strftime("%d/%m/%Y")+".")
    if v["sessionEndDate"] < v["sessionStartDate"]:
        raise InvalidTerms("La fin de session doit être égale ou postérieure au début.")
    if "priceTotal" in v:
        total = v.pop("priceTotal")
        if not re.fullmatch(r"[0-9]{1,7}(?:[.,][0-9]{1,2})?",total):
            raise InvalidTerms("Renseignez le prix total TTC de la formation.")
        net = Decimal(number_string(total)) - sum(Decimal(number_string(v[k]) or "0") for k in ("vatInclTax5","vatInclTax20"))
        if net < 0:
            raise InvalidTerms("Les montants soumis à TVA dépassent le prix total.")
        v["vat"] = number_string(net) if net else ""
    for key,label in {**HOURS,**PRICES}.items():
        if v[key] and not re.fullmatch(r"[0-9]{1,7}(?:[.,][0-9]{1,2})?",v[key]):
            raise InvalidTerms(f"{label} : saisissez un nombre positif avec au maximum deux décimales.")
        v[key] = number_string(v[key])
    n = lambda k: Decimal(v[k] or "0")
    if min(n("indicativeDuration"), n("weeklyDuration")) <= 0:
        raise InvalidTerms("Renseignez une durée totale et une intensité hebdomadaire supérieures à zéro.")
    if n("hoursInCenter")+n("hoursInCompany") > n("indicativeDuration"):
        raise InvalidTerms("Les heures en centre et en entreprise dépassent la durée totale.")
    price = sum(n(k) for k in ("vat","vatInclTax5","vatInclTax20"))
    if price <= 0:
        raise InvalidTerms("Renseignez le prix de la formation dans la rubrique Montants.")
    if v["exam"] not in EXAM:
        raise InvalidTerms("Précisez si des frais d’examen sont attendus.")
    if v["exam"] == "INCLUDED" and not 0 < n("montantFraisCertificationInclus") <= price:
        raise InvalidTerms("Renseignez le montant des frais d’examen inclus dans le prix.")
    if v["exam"] != "INCLUDED":
        v["montantFraisCertificationInclus"] = ""
    if v["exam"] == "NOT_INCLUDED" and n("additionalFees") <= 0:
        raise InvalidTerms("Renseignez les frais d’examen à la charge du titulaire dans les frais annexes.")
    if bool(n("additionalFees")) != bool(v["additionalFeesDetails"]):
        raise InvalidTerms("Les frais annexes doivent avoir un montant et un détail.")
    for key in ("title","trainingGoal","expectedResult","content"):
        if len(v[key]) < (1 if key=="title" else 10):
            raise InvalidTerms(f"{TEXTS[key]} : le champ est obligatoire"+(" (10 caractères minimum)." if key!="title" else "."))
    for key in (*TEXTS,*ADDRESS):
        if len(v[key]) > (16000 if key in TEXTS else 250):
            raise InvalidTerms(f"Le champ {TEXTS.get(key) or ADDRESS[key]} est trop long.")
    for key in ENUMS:
        choices = set(options.get(key, {}))
        existing = source["values"][key]
        choices.update(existing if isinstance(existing,list) else [existing])
        items = v[key] if isinstance(v[key],list) else [v[key]]
        if any(item and item not in choices for item in items):
            raise InvalidTerms("Utilisez les choix proposés par EDOF.")
    if not all(v[k] for k in ("typeOfTrainingCourse","teachingModalities","trainingPaces")):
        raise InvalidTerms("Précisez le type de parcours, la modalité et le rythme de formation.")
    if v["teachingModalities"] != "2":
        street = v["roadName"] and v["roadType"]
        if (not v["countryCode"] or not v["city"] or not (street or v["postBox"])
                or v["countryCode"] == "FR" and not v["zipCode"]):
            raise InvalidTerms("En présentiel ou en formation mixte, renseignez l’adresse complète du lieu de formation.")
    if v["codeRNCP"] and not re.fullmatch(r"(?:RNCP)?[0-9]{1,8}",v["codeRNCP"],re.I):
        raise InvalidTerms("Le code RNCP doit contenir le numéro de la certification.")
    if v["codeRNCP"]:
        v["codeRNCP"] = "RNCP"+re.sub(r"(?i)^RNCP","",v["codeRNCP"])
    if not source["editable_blocks"]:
        v["blocks"] = source["values"]["blocks"]
    elif source["blocks"] and (not v["blocks"] or not set(v["blocks"]) <= source["blocks"].keys()):
        raise InvalidTerms("Sélectionnez au moins un bloc de compétences proposé par EDOF.")
    return v


def amended(raw, values, options):
    """Start from the fresh official document; preserve identities, locked terms and unrelated fields."""
    original = raw["trainingActionInfo"]
    action = dict(original)
    for k in TEXTS:
        if original.get(k) or values[k]:
            action[k] = values[k] or None
    for k in DATES:
        action[k] = dt.date.fromisoformat(values[k]).strftime("%d/%m/%Y")
    for k in (*HOURS,*PRICES):
        action[k] = float(values[k]) if values[k] else None
    action.update(typeOfTrainingCourse=int(values["typeOfTrainingCourse"]), teachingModalities=values["teachingModalities"],
                  trainingPaces=values["trainingPaces"],presenceFraisCertification=values["exam"]!="NONE",
                  fraisCertificationInclus=values["exam"]=="INCLUDED", doesPriceIncludeMontantFraisExam=values["exam"])
    place = {**(original.get("address") or {}), **{k:values[k] or None for k in ADDRESS}}
    if place.get("countryCode") != (original.get("address") or {}).get("countryCode"):
        place["country"] = options.get("countryCode", {}).get(values["countryCode"],values["countryCode"]) or None
    action["address"] = place
    gross = Decimal(values["vat"] or "0")
    net = gross
    for rate,key in (("1.055","5"),("1.20","20")):
        ttc = Decimal(values["vatInclTax"+key] or "0")
        ht = (ttc/Decimal(rate)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        action["vatExclTax"+key] = float(ht) if ttc else None
        gross += ttc
        net += ht
    action.update(totalIncl=float(gross), totalExcl=float(net))
    blocks = original.get("infosBlocsCompetences") or {}
    if blocks.get("blocsModifiables"):
        all_blocks = [*blocks.get("blocsRetenus",[]),*blocks.get("blocsExclus",[])]
        kept = [b for b in all_blocks if scalar(b.get("code")) in values["blocks"]]
        action["infosBlocsCompetences"] = {**blocks,"blocsRetenus":kept,"blocsExclus":[b for b in all_blocks if b not in kept],
                                          "certificationComplete":bool(kept) and len(kept)==len(all_blocks)}
    envelope = {k:raw[k] for k in ENVELOPE if k in raw}
    envelope["attendee"] = {k:raw["attendee"][k] for k in HOLDER if k in raw["attendee"]}
    envelope["trainingActionInfo"] = action
    return envelope
