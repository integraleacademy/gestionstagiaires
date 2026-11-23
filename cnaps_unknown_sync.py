"""Rapprochement prudent des statuts CNAPSV3 pour la page « CNAPS inconnu ».

Les données ne sont jamais réécrites si l'identité est incertaine. L'API CNAPS
utilisée est en lecture seule : aucune relance de dossier n'est déclenchée.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import wraps
import re
import unicodedata


PAGE_PATH = "/admin/sessions/cnaps-inconnu"
MAX_CHECKS_PER_PAGE = 16


def _normalized(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(character for character in value if character.isalnum())


def _date(value):
    value = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value[:10], pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def _email(value):
    return str(value or "").strip().casefold()


def _status(value):
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").upper()).strip()
    mapping = {
        "TRANSMIS": "TRANSMIS",
        "ENREGISTRE": "ENREGISTRÉ",
        "INSTRUCTION": "INSTRUCTION",
        "ACCEPTE": "ACCEPTÉ",
        "REFUSE": "REFUSÉ",
        "DOCS COMPLEMENTAIRES": "DOCS COMPLEMENTAIRES",
    }
    return mapping.get(normalized)


def _unknown(value):
    return _normalized(value) in {"", "inconnu", "unknown", "nonrenseigne"}


def _training(value):
    value = _normalized(value)
    if "a3p" in value or "protectionphysique" in value or "protectionrapprochee" in value:
        return "A3P"
    if value == "aps" or "preventionetsecurite" in value or "securiteprivee" in value:
        return "APS"
    return ""


def _candidate(item):
    return {
        "nom": item.get("last_name") or "",
        "prenom": item.get("first_name") or "",
        "email": item.get("email") or "",
        "date_naissance": item.get("birth_date") or "",
        "formation": item.get("training_type") or "",
        "session_date": item.get("date_start") or "",
    }


def _verified_status(candidate, source_rows):
    """Exige nom + prénom et une concordance positive date de naissance/email."""
    surname = _normalized(candidate.get("nom"))
    firstname = _normalized(candidate.get("prenom"))
    birth = _date(candidate.get("date_naissance"))
    email = _email(candidate.get("email"))
    if not surname or not firstname or not (birth or email):
        return None
    matches = []
    for item in source_rows:
        if not isinstance(item, dict):
            continue
        if _normalized(item.get("nom")) != surname or _normalized(item.get("prenom")) != firstname:
            continue
        candidate_training = _training(candidate.get("formation"))
        source_training = _training(item.get("formation"))
        if candidate_training and source_training and candidate_training != source_training:
            continue
        remote_birth = _date(item.get("date_naissance"))
        remote_email = _email(item.get("email"))
        birth_matches = bool(birth and remote_birth and birth == remote_birth)
        email_matches = bool(email and remote_email and email == remote_email)
        if birth and remote_birth and not birth_matches:
            continue
        if email and remote_email and not email_matches and not birth_matches:
            continue
        if not (birth_matches or email_matches):
            continue
        status = _status(item.get("statut_cnaps"))
        if status:
            matches.append((item, status))
    if not matches:
        return None

    # Plusieurs demandes pour une même personne peuvent concerner des sessions
    # distinctes. On ne choisit jamais arbitrairement une demande contradictoire.
    if len(matches) > 1:
        date_start = _date(candidate.get("session_date"))
        if date_start:
            same_session = [(item, status) for item, status in matches if _date(item.get("session_date")) == date_start]
            if same_session:
                matches = same_session
        family = _training(candidate.get("formation"))
        if family and len(matches) > 1:
            same_training = [(item, status) for item, status in matches if _training(item.get("formation")) == family]
            if same_training:
                matches = same_training
    statuses = {status for _, status in matches}
    return next(iter(statuses)) if len(statuses) == 1 else None


def _lookup(item, fetcher):
    candidate = _candidate(item)
    source_rows = fetcher(candidate)
    if not isinstance(source_rows, list):
        raise ValueError("Réponse de suivi CNAPS invalide")
    return _verified_status(candidate, source_rows)


def sync_unknown_statuses(legacy, fetcher=None):
    """Ne modifie que les statuts encore inconnus, sans toucher aux autres champs."""
    if fetcher is None:
        from bts_cnaps_tracking_api import fetch_tracking_requests
        fetcher = fetch_tracking_requests
    data = legacy.load_data()
    pending = legacy._collect_cnaps_unknown_trainees(data)
    checked = pending[:MAX_CHECKS_PER_PAGE]
    result = {"checked": len(checked), "updated": 0, "errors": 0,
              "remaining": max(0, len(pending) - len(checked))}
    if not checked:
        return result

    proposed = {}
    with ThreadPoolExecutor(max_workers=min(4, len(checked))) as executor:
        futures = {executor.submit(_lookup, item, fetcher): item for item in checked}
        for future in as_completed(futures):
            item = futures[future]
            try:
                status = future.result()
            except Exception:
                # Le CNAPS est indisponible ou une identité est ambiguë : ne pas
                # modifier la fiche, ne pas exposer d'identité dans les logs.
                result["errors"] += 1
                continue
            if status:
                key = (str(item.get("session_id") or ""), str(item.get("trainee_id") or ""))
                if all(key) and key not in proposed:
                    proposed[key] = status
    if not proposed:
        return result

    # Relire après les appels réseau pour ne pas écraser un statut renseigné
    # manuellement pendant les vérifications CNAPSV3.
    current = legacy.load_data()
    for session in current.get("sessions", []):
        if not isinstance(session, dict):
            continue
        sid = str(session.get("id") or "")
        for trainee in session.get("trainees", []):
            if not isinstance(trainee, dict):
                continue
            key = (sid, str(trainee.get("id") or ""))
            if key in proposed and _unknown(trainee.get("cnaps")):
                trainee["cnaps"] = proposed[key]
                result["updated"] += 1
    if result["updated"]:
        legacy.save_data(current)
    return result


def register_cnaps_unknown_sync(legacy):
    """S'accroche à la route existante sans modifier le gigantesque app.py."""
    from flask import g, request

    app = legacy.app
    rule = next((rule for rule in app.url_map.iter_rules() if rule.rule == PAGE_PATH and "GET" in rule.methods), None)
    if rule is None:
        app.logger.error("Synchronisation CNAPS : route CNAPS inconnu introuvable")
        return False
    original_view = app.view_functions[rule.endpoint]

    @wraps(original_view)
    def view_with_cnaps_sync(*args, **kwargs):
        first_response = app.make_response(original_view(*args, **kwargs))
        if request.path != PAGE_PATH or first_response.status_code != 200 or first_response.mimetype != "text/html":
            return first_response
        try:
            result = sync_unknown_statuses(legacy)
        except Exception:
            app.logger.exception("Synchronisation CNAPSV3 indisponible sur CNAPS inconnu (sans modification)")
            result = {"updated": 0, "errors": 1, "remaining": 0}
        g.cnaps_unknown_sync = result
        if result["updated"] or result["errors"] or result["remaining"]:
            app.logger.info("CNAPS inconnu : updated=%d errors=%d remaining=%d",
                            result["updated"], result["errors"], result["remaining"])
            return original_view(*args, **kwargs)
        return first_response

    app.view_functions[rule.endpoint] = view_with_cnaps_sync
    return True
