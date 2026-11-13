"""Read-only CNAPS tracking for authorised security apprenticeship candidates."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import requests
from flask import jsonify, request

from bts_inscriptions import InscriptionsClient
from crm_cnaps_tracking_api import _crm_titles


TOKEN_CONTEXT = b"bts-cnaps-tracking-v1"
SOURCE_URL = "https://gestionstagiaires-r5no.onrender.com/admin/sessions/suivi-cnaps"
CACHE_TTL = 300
MAX_CACHE_ENTRIES = 256


class TrackingError(Exception):
    def __init__(self, message, status=502, reason="tracking_unavailable"):
        super().__init__(message)
        self.status = status
        self.reason = reason


def _text(value, limit=200):
    return str(value or "").strip()[:limit]


def _birth_date(value):
    value = _text(value, 40)
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value[:10], pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def _name_key(value):
    # Use the same exact identity comparison as the CNAPSV3 read-only API.
    return "".join(character for character in unicodedata.normalize("NFKD", _text(value)).casefold()
                   if character.isalnum())


def _identity(candidate):
    return (
        _name_key(candidate.get("nom")),
        _name_key(candidate.get("prenom")),
        _text(candidate.get("email")).casefold(),
        _birth_date(candidate.get("date_naissance")),
    )


def fetch_tracking_requests(candidate, *, http_get=None):
    """Read the dedicated CNAPSV3 endpoint; never call the reminder endpoint."""
    token = os.getenv("CNAPSV3_API_TOKEN", "").strip()
    base = urlsplit(os.getenv("CNAPSV3_BASE_URL", "https://cnapsv3.onrender.com").strip())
    if not token or base.scheme != "https" or not base.netloc or base.username or base.password:
        raise TrackingError("Le suivi CNAPS n’est pas encore configuré.", 503, "integration_not_configured")
    endpoint = urlunsplit((base.scheme, base.netloc, "/api/cnaps-tracking", "", ""))
    response = None
    try:
        response = (http_get or requests.get)(
            endpoint,
            params={"nom": _text(candidate.get("nom")), "prenom": _text(candidate.get("prenom"))},
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
            timeout=(3, 12), allow_redirects=False, stream=True,
        )
        if response.status_code in (401, 403):
            raise TrackingError("La connexion au suivi CNAPS doit être vérifiée.", 503, "integration_not_configured")
        if response.status_code != 200:
            raise TrackingError("Le suivi CNAPS est momentanément indisponible.")
        if "json" not in str(response.headers.get("Content-Type", "")).lower():
            raise TrackingError("Le suivi CNAPS a renvoyé une réponse inattendue.")
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > 2 * 1024 * 1024:
                raise TrackingError("Le suivi CNAPS a renvoyé une réponse trop volumineuse.")
        payload = json.loads(content)
        if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("requests"), list):
            raise TrackingError("Le suivi CNAPS a renvoyé une réponse inattendue.")
        return [row for row in payload["requests"] if isinstance(row, dict)]
    except (requests.RequestException, ValueError, TypeError):
        raise TrackingError("Le suivi CNAPS est momentanément indisponible.") from None
    finally:
        if response is not None:
            response.close()


def select_tracking_match(candidate, rows):
    """Reject contradictory identities instead of choosing an arbitrary namesake."""
    last_name, first_name, email, birth_date = _identity(candidate)
    matches = [row for row in rows
               if _name_key(row.get("nom")) == last_name
               and _name_key(row.get("prenom")) == first_name]
    if not matches:
        return None, 0
    # A known, contradictory birth date is never overridden by a matching name.
    if birth_date:
        matches = [row for row in matches if not _birth_date(row.get("date_naissance"))
                   or _birth_date(row.get("date_naissance")) == birth_date]
    if not matches:
        raise TrackingError("L’identité du dossier CNAPS doit être vérifiée.", 409, "identity_mismatch")

    email_matches = [row for row in matches if email and _text(row.get("email")).casefold() == email]
    birth_matches = [row for row in matches if birth_date and _birth_date(row.get("date_naissance")) == birth_date]
    if email_matches:
        matches = email_matches
    elif birth_matches:
        matches = birth_matches
    elif email and any(_text(row.get("email")) for row in matches):
        raise TrackingError("L’identité du dossier CNAPS doit être vérifiée.", 409, "identity_mismatch")

    identities = {
        "email": {_text(row.get("email")).casefold() for row in matches if _text(row.get("email"))},
        "birth_date": {_birth_date(row.get("date_naissance")) for row in matches if _birth_date(row.get("date_naissance"))},
        "nub": {re.sub(r"\D", "", _text(row.get("nub"))) for row in matches if re.sub(r"\D", "", _text(row.get("nub")))},
    }
    if any(len(values) > 1 for values in identities.values()):
        raise TrackingError("Plusieurs dossiers CNAPS correspondent à des identités différentes. Vérifiez le suivi CNAPS.",
                            409, "ambiguous_match")
    if len(matches) > 1 and not any(identities.values()):
        raise TrackingError("Plusieurs dossiers CNAPS correspondent à ce nom. Leur identité doit être vérifiée.",
                            409, "ambiguous_match")
    row = max(matches, key=lambda item: (
        bool(_text(item.get("nub"))),
        _text(item.get("updated_at") or item.get("created_at")),
        int(item.get("id") or 0) if str(item.get("id") or "").isdigit() else 0,
    ))
    return row, len(matches)


def tracking_payload(candidate, row, match_count, annuaire_fetcher=None):
    if row is None:
        return {"found": False, "linked": False, "reason": "cnaps_not_found",
                "message": "Aucun dossier CNAPS correspondant à ce candidat n’a été retrouvé.",
                "source_url": SOURCE_URL, "match_count": 0}
    nub = re.sub(r"\D", "", _text(row.get("nub")))
    snapshot = {}
    if nub and callable(annuaire_fetcher):
        try:
            snapshot = annuaire_fetcher(_text(row.get("nom")), nub)
        except Exception:
            snapshot = {"check_status": "error"}
    if not isinstance(snapshot, dict):
        snapshot = {"check_status": "error"}
    unavailable = bool(snapshot.get("error")) or str(snapshot.get("check_status") or "").lower() in {"error", "unavailable", "failed"}
    payload = {
        "found": True, "linked": True, "source_url": SOURCE_URL,
        "match_count": match_count,
        "person": {"nom": _text(row.get("nom")), "prenom": _text(row.get("prenom")), "nub": nub},
        "cnaps": {
            "cnaps_status": _text(row.get("statut_cnaps"), 80) or "INCONNU",
            "nub": nub, "nub_present": bool(nub), "nub_missing": not bool(nub),
            "last_checked_at": _text(snapshot.get("checked_at"), 80) or datetime.now(timezone.utc).isoformat(),
            "titles": _crm_titles(snapshot), "cnaps_unavailable": unavailable,
        },
    }
    inscription = " · ".join(filter(None, (_text(row.get("formation")), _text(row.get("session_date")))))
    if inscription:
        payload["inscription"] = inscription
    return payload


def register_bts_cnaps_tracking_api(app, *, annuaire_fetcher=None, candidate_fetcher=None, tracking_fetcher=None):
    """Use the existing BTS shared key, with a separate derived read-only token."""
    cache = OrderedDict()
    cache_lock = threading.RLock()

    @app.get("/api/integrations/bts/candidats/<candidate_id>/cnaps-tracking")
    def bts_candidate_cnaps_tracking(candidate_id):
        key = os.getenv("BTS_IMPORT_API_KEY", "").strip()
        if len(key) < 32:
            return jsonify(error="La connexion aux admissions n’est pas configurée.", reason="integration_not_configured"), 503
        header = request.headers.get("Authorization", "").strip()
        provided = header[7:].strip() if header.lower().startswith("bearer ") else ""
        expected = hmac.new(key.encode(), TOKEN_CONTEXT, hashlib.sha256).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", provided) or not hmac.compare_digest(provided, expected):
            return jsonify(error="Authentification invalide.", reason="unauthorized"), 401
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", candidate_id):
            return jsonify(error="Candidat introuvable.", reason="invalid_candidate"), 400
        try:
            candidate = (candidate_fetcher or InscriptionsClient().candidate)(candidate_id)
        except Exception:
            app.logger.warning("Lecture du candidat BTS indisponible pour le suivi CNAPS")
            return jsonify(error="La fiche candidat n’est pas accessible pour le moment.", reason="candidate_unavailable"), 502
        if not isinstance(candidate, dict) or str(candidate.get("id")) != candidate_id:
            return jsonify(error="La fiche candidat reçue est inattendue.", reason="candidate_mismatch"), 502
        if candidate.get("bts") != "PARCOURS-SECURITE":
            return jsonify(error="Le suivi CNAPS est réservé au parcours sécurité en alternance.", reason="ineligible_candidate"), 403
        identity = _identity(candidate)
        if not identity[0] or not identity[1]:
            return jsonify(error="Renseignez le nom et le prénom du candidat.", reason="insufficient_identity"), 422
        cache_key = (candidate_id, *identity)
        force = request.args.get("refresh") == "1"
        with cache_lock:
            cached = cache.get(cache_key)
            if cached and not force and time.monotonic() - cached["stored_at"] < CACHE_TTL:
                cache.move_to_end(cache_key)
                return jsonify(**copy.deepcopy(cached["payload"]), cached=True)
        try:
            rows = (tracking_fetcher or fetch_tracking_requests)(candidate)
            row, count = select_tracking_match(candidate, rows)
            payload = tracking_payload(candidate, row, count, annuaire_fetcher)
        except TrackingError as exc:
            if cached and cached["payload"].get("found") and exc.status >= 500:
                return jsonify(**copy.deepcopy(cached["payload"]), cached=True, stale=True,
                               refresh_failed=True, refresh_error=str(exc))
            return jsonify(error=str(exc), reason=exc.reason), exc.status
        if (cached and payload.get("cnaps", {}).get("cnaps_unavailable")
                and payload["cnaps"].get("nub") == cached["payload"].get("cnaps", {}).get("nub")):
            previous_cnaps = cached["payload"].get("cnaps", {})
            if previous_cnaps.get("titles"):
                payload["cnaps"]["titles"] = copy.deepcopy(previous_cnaps["titles"])
                payload["cnaps"]["last_checked_at"] = previous_cnaps.get("last_checked_at")
                payload["cnaps"]["titles_stale"] = True
        with cache_lock:
            cache[cache_key] = {"stored_at": time.monotonic(), "payload": copy.deepcopy(payload)}
            cache.move_to_end(cache_key)
            while len(cache) > MAX_CACHE_ENTRIES:
                cache.popitem(last=False)
        return jsonify(**payload, cached=False)

