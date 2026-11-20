"""Existing trainee identity and registration rules shared by the two services."""
import datetime
import re
import unicodedata
from typing import Any, Dict, Optional


def _norm_lastname(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")  # remove accents
    s = re.sub(r"[^a-z0-9]+", "", s)  # keep only alnum, no spaces
    return s


def _birth_to_ddmmyyyy(value: str) -> str:
    """
    Normalise une date de naissance en DDMMYYYY.

    Formats acceptés :
    - DD/MM/YYYY, D/M/YYYY
    - DD-MM-YYYY, D-M-YYYY
    - YYYY-MM-DD, YYYY-M-D
    - DDMMYYYY (saisie publique compacte)
    - YYYYMMDD (stockage/import compact)

    Les zéros de tête du jour et du mois sont toujours conservés.
    Si la date est absente ou invalide, renvoie une chaîne vide.
    """
    v = str(value or "").strip()
    if not v:
        return ""

    def _format_if_valid(day: str, month: str, year: str) -> str:
        if not (day and month and year) or len(year) != 4:
            return ""
        try:
            dt = datetime.datetime(int(year), int(month), int(day))
        except (TypeError, ValueError):
            return ""
        return dt.strftime("%d%m%Y")

    # Formats séparés explicites : pas de suppression des zéros, on reconstruit via datetime.
    match = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", v)
    if match:
        year, month, day = match.groups()
        return _format_if_valid(day, month, year)

    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", v)
    if match:
        first, second, year = match.groups()
        french = _format_if_valid(first, second, year)
        if french:
            return french
        # Compatibilité avec d'anciens imports MM/DD/YYYY lorsque le format
        # français est impossible (ex : 10/29/1979).
        return _format_if_valid(second, first, year)

    digits = re.fullmatch(r"\d{8}", v)
    if digits:
        # Le formulaire public utilise DDMMYYYY. On le privilégie pour éviter
        # qu'un jour comme 19 soit interprété comme le début d'une année.
        ddmmyyyy = _format_if_valid(v[0:2], v[2:4], v[4:8])
        if ddmmyyyy:
            return ddmmyyyy
        # Stockages/imports compacts possibles en YYYYMMDD.
        return _format_if_valid(v[6:8], v[4:6], v[0:4])

    return ""


def _public_trainee_last_names(trainee: Dict[str, Any]) -> set[str]:
    names = {
        _norm_lastname(trainee.get("last_name", "")),
        _norm_lastname(trainee.get("nom", "")),
        _norm_lastname(trainee.get("birth_name", "")),
        _norm_lastname(trainee.get("nom_naissance", "")),
        _norm_lastname(trainee.get("nom_usage", "")),
        _norm_lastname(trainee.get("name", "")),
    }
    return {name for name in names if name}


def _public_trainee_birth_dates(trainee: Dict[str, Any]) -> set[str]:
    dates = {
        _birth_to_ddmmyyyy(trainee.get("birth_date", "")),
        _birth_to_ddmmyyyy(trainee.get("date_naissance", "")),
        _birth_to_ddmmyyyy(trainee.get("dateNaissance", "")),
        _birth_to_ddmmyyyy(trainee.get("date_de_naissance", "")),
        _birth_to_ddmmyyyy(trainee.get("birthdate", "")),
        _birth_to_ddmmyyyy(trainee.get("dob", "")),
    }
    return {date for date in dates if date}


def _public_trainee_identity_matches(trainee: Dict[str, Any], last_name: str, birth: str) -> bool:
    expected_last = _norm_lastname(last_name)
    expected_birth = _birth_to_ddmmyyyy(birth)
    if not expected_last or not expected_birth:
        return False
    return expected_last in _public_trainee_last_names(trainee) and expected_birth in _public_trainee_birth_dates(trainee)


def _trainee_registration_is_cancelled(trainee: Optional[Dict[str, Any]]) -> bool:
    """Return whether a trainee record represents a cancelled registration.

    The record intentionally remains in storage and in administrative search
    results.  This predicate is the single business rule used by counters,
    dashboards and automations to exclude it from the active enrolment scope.
    """
    if not isinstance(trainee, dict):
        return False
    value = trainee.get("registration_cancelled")
    if value is None:
        value = trainee.get("registration_canceled")
    if value is None:
        value = trainee.get("inscription_annulee")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "on", "oui", "annulee", "annulée", "cancelled", "canceled",
    }
