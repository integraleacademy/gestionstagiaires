"""API de lecture du suivi CNAPS destinée au CRM Intégrale Connect."""

from __future__ import annotations

import hmac
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from flask import jsonify, request


TrackingFetcher = Callable[[], Tuple[List[Dict[str, str]], Optional[str]]]
AnnuaireFetcher = Callable[..., Dict[str, Any]]


def _provided_token() -> str:
    authorization = str(request.headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return str(request.headers.get("X-API-Key") or "").strip()


def _normalize_person_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = normalized.casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _first_name_matches(source: Any, expected: Any) -> bool:
    source_name = _normalize_person_name(source)
    expected_name = _normalize_person_name(expected)
    if not source_name or not expected_name:
        return source_name == expected_name
    if source_name == expected_name:
        return True
    return source_name.startswith(expected_name + " ") or expected_name.startswith(source_name + " ")


def _find_tracking_matches(
    rows: Iterable[Dict[str, str]], last_name: str, first_name: str
) -> List[Dict[str, str]]:
    expected_last_name = _normalize_person_name(last_name)
    if not expected_last_name:
        return []

    same_last_name = [
        row
        for row in rows
        if _normalize_person_name(row.get("last_name")) == expected_last_name
    ]
    exact = [
        row
        for row in same_last_name
        if _first_name_matches(row.get("first_name"), first_name)
    ]
    if exact:
        return exact

    missing_first_name = [
        row for row in same_last_name if not _normalize_person_name(row.get("first_name"))
    ]
    return missing_first_name if len(missing_first_name) == 1 else []


def _pick_best_match(matches: List[Dict[str, str]]) -> Dict[str, str]:
    def score(row: Dict[str, str]) -> Tuple[int, int]:
        status = str(row.get("cnaps_status") or "").strip().upper()
        return (
            1 if str(row.get("nub") or "").strip() else 0,
            1 if status not in {"", "INCONNU"} else 0,
        )

    return sorted(matches, key=score, reverse=True)[0]


def _title_value(item: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return ""


def _crm_titles(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_titles = snapshot.get("titles")
    if not isinstance(raw_titles, list) or not raw_titles:
        raw_titles = snapshot.get("active_titles")
    if not isinstance(raw_titles, list) or not raw_titles:
        raw_titles = snapshot.get("results")
    if not isinstance(raw_titles, list):
        return []

    titles: List[Dict[str, Any]] = []
    seen = set()
    for item in raw_titles:
        if not isinstance(item, dict):
            continue
        title_type = str(
            _title_value(
                item,
                "code",
                "display_status",
                "label",
                "activity",
                "activite",
                "typeActivite",
                "type",
                "title",
            )
            or "Titre CNAPS"
        ).strip()
        state = str(
            _title_value(
                item,
                "status",
                "validity",
                "validite_titre",
                "agrementStatutEs",
                "state",
                "etat",
            )
            or "INCONNU"
        ).strip().upper()
        expires_at = str(
            _title_value(
                item,
                "date_fin_validite",
                "valid_until",
                "date_validite_titre",
                "dateFinValidite",
                "expires_at",
                "expiration_date",
            )
            or ""
        ).strip()
        key = (title_type, state, expires_at)
        if key in seen:
            continue
        seen.add(key)
        titles.append(
            {
                "type": title_type,
                "state": state,
                "expires_at": expires_at or None,
            }
        )
    return titles


def _annuaire_snapshot(
    fetch_public_annuaire: Optional[AnnuaireFetcher], last_name: str, nub: str
) -> Dict[str, Any]:
    if not callable(fetch_public_annuaire) or not last_name or not nub:
        return {}
    try:
        snapshot = fetch_public_annuaire(last_name, nub)
    except TypeError:
        snapshot = fetch_public_annuaire(last_name, nub, None)
    except Exception:
        return {"check_status": "error"}
    return snapshot if isinstance(snapshot, dict) else {}


def register_crm_cnaps_tracking_api(
    app,
    *,
    fetch_tracking_requests: TrackingFetcher,
    fetch_public_annuaire: Optional[AnnuaireFetcher] = None,
) -> None:
    """Expose une API sécurisée fondée sur la même source que la page de suivi CNAPS."""

    def crm_cnaps_tracking_by_identity():
        configured_token = str(os.environ.get("CRM_INTEGRATION_TOKEN") or "").strip()
        provided_token = _provided_token()
        if not configured_token:
            app.logger.error("CRM_INTEGRATION_TOKEN non configuré")
            return jsonify({"error": "integration_not_configured"}), 503
        if not provided_token or not hmac.compare_digest(provided_token, configured_token):
            return jsonify({"error": "unauthorized"}), 401

        last_name = str(
            request.args.get("nom") or request.args.get("last_name") or ""
        ).strip()
        first_name = str(
            request.args.get("prenom") or request.args.get("first_name") or ""
        ).strip()
        if not last_name:
            return jsonify({"error": "nom_required"}), 400

        rows, fetch_error = fetch_tracking_requests()
        if fetch_error:
            app.logger.warning("Suivi CNAPS indisponible pour le CRM: %s", fetch_error)
            return jsonify(
                {
                    "error": "cnaps_tracking_unavailable",
                    "detail": str(fetch_error),
                }
            ), 502

        matches = _find_tracking_matches(rows, last_name, first_name)
        if not matches:
            return jsonify(
                {
                    "found": False,
                    "linked": False,
                    "message": "Aucune demande CNAPS trouvée pour ce prospect dans le suivi CNAPS.",
                    "source": "/admin/sessions/suivi-cnaps",
                }
            ), 404

        row = _pick_best_match(matches)
        nub = str(row.get("nub") or "").strip()
        status = str(row.get("cnaps_status") or "INCONNU").strip() or "INCONNU"
        snapshot = _annuaire_snapshot(
            fetch_public_annuaire,
            str(row.get("last_name") or last_name),
            nub,
        )
        checked_at = str(snapshot.get("checked_at") or "").strip()
        if not checked_at:
            checked_at = datetime.now(timezone.utc).isoformat()

        check_status = str(
            snapshot.get("check_status") or snapshot.get("status") or ""
        ).lower()
        cnaps_unavailable = check_status in {
            "error",
            "unavailable",
            "failed",
        } or bool(snapshot.get("error"))

        return jsonify(
            {
                "found": True,
                "linked": True,
                "source": "/admin/sessions/suivi-cnaps",
                "source_url": request.url_root.rstrip("/")
                + "/admin/sessions/suivi-cnaps",
                "match_count": len(matches),
                "person": {
                    "nom": str(row.get("last_name") or last_name).strip(),
                    "prenom": str(row.get("first_name") or first_name).strip(),
                    "nub": nub,
                },
                "cnaps": {
                    "cnaps_status": status,
                    "nub": nub,
                    "nub_present": bool(nub),
                    "nub_missing": not bool(nub),
                    "last_checked_at": checked_at,
                    "titles": _crm_titles(snapshot),
                    "cnaps_unavailable": cnaps_unavailable,
                },
            }
        )

    route_path = "/api/integrations/crm/cnaps-tracking"
    existing_rule = next(
        (rule for rule in app.url_map.iter_rules() if rule.rule == route_path),
        None,
    )
    if existing_rule is not None:
        app.view_functions[existing_rule.endpoint] = crm_cnaps_tracking_by_identity
        return
    app.add_url_rule(
        route_path,
        endpoint="api_integration_crm_cnaps_tracking_by_identity",
        view_func=crm_cnaps_tracking_by_identity,
        methods=["GET"],
    )
