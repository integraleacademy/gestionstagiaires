"""Defaults from the academy's 2026 EDOF sheet. Quoted and individual terms stay on the offer."""
import re

from edof_directory import normalized
from integrale_edof_registration import training_family

# TTC price for a 2026 start, total hours, classroom hours, EDOF teaching modality.
COURSES = {
    "APS": (1650, 175, 124, "1"), "A3P": (4200, 328, 328, "0"),
    "DIRIGEANT initial": (4300, 245, 70, "1"), "DIRIGEANT VAE": (3800, None, 0, "2"),
    "SSIAP 1": (980, 67, 67, "0"), "SSIAP 1 + SST": (1230, 81, 81, "0"),
    "SSIAP 2": (None, 70, 70, "0"), "SSIAP 3": (None, 216, 216, "0"),
    "CPSP": (None, 70, 70, "0"), "SST": (None, 14, 14, "0"),
    "VTC": (1500, 105, None, "1"), "VTC pratique": (600, None, None, "0"),
}
for level, recycling, refresher in ((1, 14, 21), (2, 14, 21), (3, 21, 35)):
    for mode, hours in (("Recyclage", recycling), ("Remise à niveau", refresher)):
        COURSES[f"{mode} SSIAP {level}"] = (None, hours, hours, "0")


def course_key(title):
    label = normalized(title or "")
    family = training_family(label)
    if family.startswith("SSIAP ") and family[-1] in "123":
        if re.search(r"recyclage|\brec\b", label):
            return "Recyclage " + family
        if re.search(r"remise a niveau|\bran\b", label):
            return "Remise à niveau " + family
        if family == "SSIAP 1" and re.search(r"\bsst\b|sauveteur secouriste", label):
            return "SSIAP 1 + SST"
    if family == "VTC":
        if re.search(r"pratique|vehicule", label) and not re.search(r"complet|theori", label):
            return "VTC pratique" if "pratique" in label else ""
    if not family and re.search(r"\bsst\b|sauveteur secouriste du travail", label):
        return "SST"
    return family


def option_codes(options, key, *patterns):
    choices = options.get(key, {})
    result = []
    for pattern in patterns:
        matches = [code for code, label in choices.items() if re.search(pattern, normalized(label))]
        if len(matches) == 1 and matches[0] not in result:
            result.append(matches[0])
    return result


def fill(values, options, session_terms=None):
    values["weeklyDuration"] = "35"
    values["exam"] = "INCLUDED"
    if values.get("additionalFees") in ("0", "0.00") and not values.get("additionalFeesDetails"):
        values["additionalFees"] = ""
    key = course_key(values.get("title"))
    if key not in COURSES:
        return values
    price, total, centre, modality = COURSES[key]
    session_terms = session_terms or {}
    total = session_terms.get("hours") or total
    if modality == "0":
        centre = total
    if not values.get("priceTotal"):
        if session_terms.get("price"):
            values["priceTotal"] = str(session_terms["price"])
        elif price and str(values.get("sessionStartDate") or "").startswith("2026-"):
            values["priceTotal"] = str(price)
    if not values.get("indicativeDuration") and total is not None:
        values["indicativeDuration"] = str(total)
    if values.get("hoursInCenter") in (None, "", "0") and centre is not None:
        # Classroom-only contracts can specify 70/84 hours instead of the reference 67/81.
        if modality == "0":
            centre = values.get("indicativeDuration") or centre
        values["hoursInCenter"] = str(centre)
    values["hoursInCompany"] = values.get("hoursInCompany") or "0"
    values["teachingModalities"] = values.get("teachingModalities") or modality
    individual = key in {"VTC", "VTC pratique", "DIRIGEANT VAE"}
    if individual or not values.get("typeOfTrainingCourse"):
        choice = option_codes(options, "typeOfTrainingCourse", r"individu" if individual else r"collectif")
        if choice:
            values["typeOfTrainingCourse"] = choice[0]
    if not values.get("trainingPaces"):
        rhythms = ((r"plusieurs rythmes",) if individual else (r"en journee", r"en semaine"))
        values["trainingPaces"] = option_codes(options, "trainingPaces", *rhythms)
    # Use the single-campus address only when the offer has no conflicting address.
    title = normalized(values.get("title") or "")
    single_campus = key not in {"VTC", "VTC pratique", "DIRIGEANT initial", "DIRIGEANT VAE"}
    if (single_campus or "puget" in title) and not re.search(r"paris|aurillac|arpajon", title):
        local_city = normalized(values.get("city") or "") in {"", "puget sur argens"}
        local_postcode = values.get("zipCode") in (None, "", "83480")
        local_road = normalized(values.get("roadName") or "") in {"", "du carreou", "carreou"}
        if local_city and local_postcode and local_road and not values.get("postBox") and values.get("countryCode") in ("", "FR", None):
            for field, value in (("number", "54"), ("roadName", "du Carreou"), ("zipCode", "83480"), ("city", "Puget-sur-Argens")):
                values[field] = values.get(field) or value
            for field, label in (("roadType", r"^chemin$"), ("countryCode", r"^france$")):
                if not values.get(field):
                    choices = option_codes(options, field, label)
                    if choices:
                        values[field] = choices[0]
    if key == "VTC" and str(values.get("sessionStartDate") or "").startswith("2026-"):
        if values.get("montantFraisCertificationInclus") in (None, "", "0"):
            values["montantFraisCertificationInclus"] = "241"
    return values
