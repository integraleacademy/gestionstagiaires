"""Deterministic BTS funding quotes from the official NPEC reference.

No API call and no personal data are needed. The selected rate and calculation
are included in the document package; pre-existing manual amounts stay intact.
"""
from __future__ import annotations

import datetime as dt
import calendar
import json
import gzip
import re
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

from bts_workspace_store import WorkspaceError

REFERENCE_URL = "https://www.francecompetences.fr/referentiels-et-bases-de-donnees/"
RULES_URL = "https://www.opcoep.fr/prestataire-de-formation/connaitre-la-reglementation/la-reforme-du-financement-de-l-apprentissage-2025"
CALCULATION_VERSION = "bts-npec-20260914-1"


@lru_cache(maxsize=1)
def reference():
    with gzip.open(Path(__file__).resolve().parent / "data/bts_npec.json.gz", "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    if data.get("schema") != 1:
        raise WorkspaceError("Le référentiel NPEC doit être mis à jour.")
    return data["editions"]


def automatic(settings):
    mode = settings.get("funding_mode")
    if mode:
        return mode == "npec"
    return not any(settings.get(f"npec_{n}") not in (None, "") for n in range(1, 4))


def _date(values, key, label):
    try:
        return dt.date.fromisoformat(str(values.get(key) or ""))
    except ValueError:
        raise WorkspaceError("Renseignez « " + label + " » dans l’onglet Contrat.") from None


def _anniversary(start, year):
    try:
        return start.replace(year=start.year + year)
    except ValueError:
        return start.replace(year=start.year + year, day=28)


def periods(start, end, annual_cents):
    if end < start:
        raise WorkspaceError("La fin du contrat doit suivre son début.")
    if end >= _anniversary(start, 3):
        raise WorkspaceError("Ce modèle de convention couvre au maximum trois années de financement.")
    result = []
    for year in range(3):
        first, next_year = _anniversary(start, year), _anniversary(start, year + 1)
        if first > end:
            break
        last = min(end, next_year - dt.timedelta(days=1))
        days, denominator = (last - first).days + 1, (next_year - first).days
        amount = int((Decimal(annual_cents) * days / denominator).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        result.append({"year": year + 1, "start": first.isoformat(), "end": last.isoformat(),
                       "days": days, "year_days": denominator, "opco_cents": amount})
    return result


def precontract_period(values, settings, start, conclusion, annual_cents, year_days):
    """Count confirmed L6222-12-1 training, never a prior employer's funding.

    Signature limits the eligible pre-contract period (R6332-25 VI); execution
    start limits it too, so no day is counted twice. Three calendar months are
    measured from actual CFA entry, not a rolling 90-day allowance.
    """
    decision = settings.get("precontract_training", "")
    if decision not in {"", "yes", "no"}:
        raise WorkspaceError("Choisissez si la formation a commencé sans employeur.")
    if decision == "no":
        return None
    training = _date(values, "training_start", "Début de formation")
    boundary = min(start, conclusion)
    if training >= boundary:
        if decision == "yes":
            raise WorkspaceError("La formation sans employeur doit commencer avant la signature et le début du contrat. Vérifiez les dates ou choisissez « Non ».")
        return None
    if not decision:
        raise WorkspaceError("La formation commence avant le contrat : précisez ci-dessous si cette période relève de la formation sans employeur (trois mois maximum).")
    if str(values.get("contract_type") or "") != "11":
        raise WorkspaceError("La reprise après un précédent contrat nécessite une vérification OPCO pour éviter un double financement. La période sans employeur ne peut pas être ajoutée automatiquement à ce contrat successif.")
    month_index = training.year * 12 + training.month - 1 + 3
    year, month = divmod(month_index, 12)
    month += 1
    deadline = dt.date(year, month, min(training.day, calendar.monthrange(year, month)[1]))
    if conclusion > deadline:
        raise WorkspaceError("La signature intervient plus de trois mois calendaires après l’entrée en formation. Faites confirmer cette période par l’OPCO ; aucun supplément n’est calculé automatiquement.")
    days = (boundary - training).days
    amount = int((Decimal(annual_cents) * days / year_days).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {"start": training.isoformat(), "end": (boundary - dt.timedelta(days=1)).isoformat(),
            "days": days, "year_days": year_days, "opco_cents": amount,
            "signature": conclusion.isoformat(), "deadline": deadline.isoformat(),
            "gap_days": (start - boundary).days}


def quote(values, settings, editions=None):
    """Resolve the exact RNCP × IDCC/CPNE pair as at contract conclusion."""
    conclusion = _date(values, "contract_conclusion", "Date de conclusion")
    start = _date(values, "contract_start", "Début du contrat")
    end = _date(values, "contract_end", "Fin du contrat")
    if values.get("employer_sector") == "public":
        raise WorkspaceError("Le financement d’un employeur public doit être confirmé avec son financeur ; le barème OPCO privé ne s’applique pas automatiquement.")
    if str(values.get("contract_type") or "").startswith("3"):
        raise WorkspaceError("Pour un avenant, reprenez le financement du contrat initial et faites confirmer les ajustements par l’OPCO.")
    rncp = re.fullmatch(r"(?:RNCP)?(\d{3,6})", str(values.get("rncp") or "").strip().upper())
    if not rncp:
        raise WorkspaceError("Renseignez le code RNCP du BTS dans l’onglet Contrat.")
    rncp = rncp.group(1)
    idcc = str(values.get("employer_idcc") or "").strip()
    if not re.fullmatch(r"\d{1,4}", idcc):
        raise WorkspaceError("Renseignez le code IDCC de l’entreprise dans l’onglet Entreprise.")
    idcc = idcc.zfill(4)
    eligible = [e for e in (editions if editions is not None else reference()) if e["effective_from"] <= conclusion.isoformat()]
    if not eligible:
        raise WorkspaceError("Le référentiel intégré couvre les contrats conclus depuis le 1er septembre 2025. Le barème antérieur doit être vérifié avant de chiffrer ce dossier.")
    edition = max(eligible, key=lambda e: e["effective_from"])
    certification = next((c for c in edition["certifications"] if rncp in c["codes"]), None)
    if not certification:
        raise WorkspaceError(f"Le BTS RNCP{rncp} n’a pas de NPEC dans le référentiel applicable à cette date. Vérifiez le code RNCP.")
    cpnes = edition["idcc_to_cpne"].get(idcc, [])
    if not cpnes:
        raise WorkspaceError(f"L’IDCC {idcc} n’a pas de branche identifiée dans le référentiel. Vérifiez l’IDCC auprès de l’entreprise ou de l’OPCO.")
    choices = [{"code": code, "label": edition["cpne_names"][code]} for code in cpnes]
    selected = settings.get("npec_cpne")
    if selected:
        if selected not in cpnes:
            error = WorkspaceError("La branche sélectionnée ne correspond plus à l’IDCC de l’entreprise. Sélectionnez sa branche actuelle.")
            error.cpne_choices = choices
            raise error
        cpnes = [selected]
    if len(cpnes) != 1:
        error = WorkspaceError("Plusieurs branches correspondent à cet IDCC : sélectionnez celle de l’entreprise pour calculer le NPEC.")
        error.cpne_choices = choices
        raise error
    cpne = cpnes[0]
    rate = certification["rates"].get(cpne)
    if not rate or rate[1] > conclusion.isoformat():
        raise WorkspaceError("Aucun NPEC applicable à cette date pour ce BTS et cette branche. Faites confirmer le montant par l’OPCO.")
    try:
        hours = Decimal(str(values.get("training_hours") or ""))
        remote = Decimal(str(values.get("remote_hours") if values.get("remote_hours") is not None else ""))
        if not hours.is_finite() or not remote.is_finite() or hours <= 0 or remote < 0 or remote > hours:
            raise ValueError
    except (ValueError, ArithmeticError):
        raise WorkspaceError("Renseignez les heures totales et les heures à distance dans l’onglet Contrat pour calculer la prise en charge.") from None
    reduced = remote / hours >= Decimal("0.8")
    # No BTS appears in the exemption order of 26 November 2025. All entries in
    # this reference are BTS (level 5), so the mandatory 750 € does not apply.
    annual = rate[0]
    adjusted = min(annual, max(400000, int(Decimal(annual) * Decimal("0.8")))) if reduced else annual
    annual_periods = periods(start, end, adjusted)
    prior = precontract_period(values, settings, start, conclusion, adjusted, annual_periods[0]["year_days"])
    if prior:
        # Display contract execution dates unchanged; the separate supplement is
        # assigned to year one in the convention, not to a fictitious fourth year.
        annual_periods[0]["opco_cents"] += prior["opco_cents"]
    result = {"version": CALCULATION_VERSION, "reference": edition["id"], "published_at": edition["published_at"],
            "source_url": edition["source_url"], "reference_url": REFERENCE_URL,
            "effective_from": rate[1], "conclusion": conclusion.isoformat(), "rncp": rncp,
            "title": certification["title"], "idcc": idcc, "cpne": cpne, "branch": edition["cpne_names"][cpne],
            "cpne_choices": choices if len(choices) > 1 else [],
            "annual_cents": annual, "adjusted_annual_cents": adjusted, "remote_reduction": reduced,
            "remote_percent": str((remote / hours * 100).quantize(Decimal("0.01"))),
            "periods": annual_periods, "days": sum(p["days"] for p in annual_periods),
            "total_opco_cents": sum(p["opco_cents"] for p in annual_periods)}
    if prior:
        result.update(version="bts-npec-20260914-2", precontract=prior,
                      days=result["days"] + prior["days"])
    return result


def resolve(values, settings):
    """Compute only automatic dossiers; retain the old package fingerprints."""
    if not automatic(settings):
        return settings
    result = dict(settings, funding_mode="npec")
    try:
        calculation = quote(values, result)
        result["_npec"] = calculation
        result["funding_years"] = str(len(calculation["periods"]))
        for n in range(1, 4):
            if n <= len(calculation["periods"]):
                result[f"npec_{n}"] = f"{Decimal(calculation['periods'][n - 1]['opco_cents']) / 100:.2f}"
                result[f"rac_{n}"] = result.get(f"rac_{n}") or "0.00"
            else:
                result[f"npec_{n}"] = result[f"rac_{n}"] = ""
    except WorkspaceError as exc:
        result["_npec"] = {"error": str(exc), "cpne_choices": getattr(exc, "cpne_choices", [])}
        result["funding_years"] = ""
        for n in range(1, 4):
            result[f"npec_{n}"] = ""
    return result


def context(values, settings):
    calculated = settings.get("_npec", {}) if automatic(settings) else {}
    if not automatic(settings):
        return {"automatic": False, "reference_url": REFERENCE_URL}
    return dict(calculated, automatic=True, reference_url=REFERENCE_URL)
