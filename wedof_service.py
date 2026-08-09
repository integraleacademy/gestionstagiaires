"""Client en lecture seule pour vérifier la connexion à l'API WEDOF."""

import logging
import os
import time
import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

import requests


WEDOF_BASE_URL = "https://www.wedof.fr/api"
_TRUE_VALUES = {"true", "1", "yes", "on"}
logger = logging.getLogger(__name__)


class WedofConfigurationError(RuntimeError):
    """Configuration WEDOF absente ou inutilisable."""


class WedofApiError(RuntimeError):
    """Erreur volontairement nettoyée renvoyée par le client WEDOF."""

    def __init__(self, message: str, code: str = "wedof_api_error", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.retryable = retryable


def _bounded_env(name: str, default: float, minimum: float, maximum: float, *, integer: bool = False):
    """Lit un nombre borné sans rendre le démarrage dépendant de l'environnement."""
    try:
        value = int(os.environ[name]) if integer else float(os.environ[name])
        if not minimum <= value <= maximum:
            raise ValueError
        return value
    except (KeyError, TypeError, ValueError):
        return int(default) if integer else default


def read_env_bool(name: str, default: bool = False) -> bool:
    """Lit un booléen d'environnement en mode fail-closed."""

    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


class WedofClient:
    """Client WEDOF strictement limité aux lectures nécessaires."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        key = (api_key if api_key is not None else os.environ.get("WEDOF_API_KEY", "")).strip()
        if not key:
            raise WedofConfigurationError("La variable WEDOF_API_KEY est absente.")
        self._session = session or requests.Session()
        self._headers = {"Accept": "application/json", "X-Api-Key": key}
        self._timeout = (
            _bounded_env("WEDOF_CONNECT_TIMEOUT_SECONDS", 5, 1, 30),
            _bounded_env("WEDOF_READ_TIMEOUT_SECONDS", 45, 10, 120),
        )
        self._max_attempts = _bounded_env("WEDOF_GET_MAX_ATTEMPTS", 3, 1, 4, integer=True)
        self._backoff = _bounded_env("WEDOF_GET_BACKOFF_SECONDS", 1, 0, 10)
        self._page_limit = _bounded_env("WEDOF_PAGE_LIMIT", 50, 10, 100, integer=True)

    def _get_json_response(self, path: str, *, params: Optional[Mapping[str, Any]] = None) -> Tuple[Any, Any]:
        response = None
        for attempt in range(1, self._max_attempts + 1):
            started = time.monotonic()
            try:
                response = self._session.get(f"{WEDOF_BASE_URL}{path}", headers=self._headers,
                                             params=params, timeout=self._timeout)
            except requests.Timeout as exc:
                logger.warning("WEDOF GET path=%s etat=%s page=%s tentative=%s erreur=timeout duree=%.3f",
                               path, (params or {}).get("state"), (params or {}).get("page"), attempt,
                               time.monotonic() - started)
                if attempt == self._max_attempts:
                    raise WedofApiError("L’API WEDOF n’a pas répondu dans le délai prévu.", "wedof_timeout", True) from exc
                time.sleep(self._backoff * (2 ** (attempt - 1)))
                continue
            except requests.ConnectionError as exc:
                logger.warning("WEDOF GET path=%s etat=%s page=%s tentative=%s erreur=connexion duree=%.3f",
                               path, (params or {}).get("state"), (params or {}).get("page"), attempt,
                               time.monotonic() - started)
                if attempt == self._max_attempts:
                    raise WedofApiError("Impossible de se connecter à l’API WEDOF.", "wedof_connection_error", True) from exc
                time.sleep(self._backoff * (2 ** (attempt - 1)))
                continue
            except requests.RequestException as exc:
                raise WedofApiError("Impossible de se connecter à l’API WEDOF.", "wedof_connection_error") from exc

            retryable_status = response.status_code in {429, 500, 502, 503, 504}
            logger.info("WEDOF GET path=%s etat=%s page=%s tentative=%s code_http=%s duree=%.3f",
                        path, (params or {}).get("state"), (params or {}).get("page"), attempt,
                        response.status_code, time.monotonic() - started)
            if not retryable_status or attempt == self._max_attempts:
                break
            delay = self._backoff * (2 ** (attempt - 1))
            if response.status_code in {429, 503}:
                try:
                    delay = min(15, max(0, float((getattr(response, "headers", {}) or {}).get("Retry-After"))))
                except (TypeError, ValueError):
                    pass
            time.sleep(delay)

        if response.status_code == 401:
            raise WedofApiError("La clé API WEDOF est invalide ou refusée.", "wedof_unauthorized")
        if response.status_code == 403:
            if path == "/registrationFolders":
                raise WedofApiError("L’abonnement ou le jeton ne permet pas d’accéder aux dossiers WEDOF.", "wedof_forbidden")
            raise WedofApiError("La clé API WEDOF ne permet pas d’accéder à cet organisme.", "wedof_forbidden")
        if response.status_code == 404:
            raise WedofApiError("La ressource WEDOF demandée est introuvable.", "wedof_not_found")
        if response.status_code == 429:
            raise WedofApiError("L’API WEDOF reçoit trop de demandes. Réessayez plus tard.", "wedof_rate_limited", True)
        if response.status_code >= 500:
            raise WedofApiError("L’API WEDOF est temporairement indisponible.", "wedof_server_error", True)
        if not 200 <= response.status_code < 300:
            raise WedofApiError("L’API WEDOF a refusé la demande de vérification.")
        try:
            return response.json(), response
        except (ValueError, TypeError) as exc:
            raise WedofApiError("L’API WEDOF a renvoyé une réponse non JSON.", "wedof_invalid_response") from exc

    def _get_json(self, path: str, *, params: Optional[Mapping[str, Any]] = None) -> Any:
        return self._get_json_response(path, params=params)[0]

    @staticmethod
    def _folder_items(payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = next((payload[key] for key in ("items", "member", "hydra:member", "registrationFolders") if isinstance(payload.get(key), list)), None)
            if items is None:
                raise WedofApiError("La réponse WEDOF concernant les dossiers est inattendue.")
        else:
            raise WedofApiError("La réponse WEDOF concernant les dossiers est inattendue.")
        return [item for item in items if isinstance(item, dict)]

    def list_registration_folders(self, state: str, *, limit: Optional[int] = None, max_pages: int = 100) -> List[Dict[str, Any]]:
        """Liste paginée en lecture seule les dossiers d'un état WEDOF."""
        if state not in {"accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated"}:
            raise ValueError("État WEDOF non autorisé pour la prévisualisation.")
        limit = self._page_limit if limit is None else max(1, min(int(limit), 100))
        results: List[Dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            payload, response = self._get_json_response(
                "/registrationFolders", params={"state": state, "limit": limit, "page": page}
            )
            items = self._folder_items(payload)
            results.extend(items)
            logger.info("WEDOF GET dossiers code_http=%s page=%s nombre=%s", response.status_code, page, len(items))

            headers = getattr(response, "headers", {}) or {}
            try:
                current = int(headers.get("x-current-page", page))
                per_page = int(headers.get("x-item-per-page", limit))
                total = int(headers["x-total-count"])
                last_page = max(1, math.ceil(total / per_page))
                should_continue = current < last_page
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                should_continue = len(items) >= limit
            if not should_continue:
                break
            # Une cadence modeste évite une rafale de requêtes sur l'API distante.
            time.sleep(0.1)
        return results

    def get_registration_folder(self, external_id: str) -> Dict[str, Any]:
        """Relit un dossier précis sans jamais effectuer de requête mutatrice."""
        identifier = str(external_id or "").strip()
        if not identifier or "/" in identifier:
            raise WedofApiError("L’identifiant du dossier WEDOF est invalide.")
        payload = self._get_json(f"/registrationFolders/{identifier}")
        if not isinstance(payload, dict):
            raise WedofApiError("La réponse WEDOF concernant le dossier est inattendue.")
        return payload

    def get_current_organism(self) -> Dict[str, str]:
        payload = self._get_json("/organisms/me")
        if not isinstance(payload, dict):
            raise WedofApiError("La réponse WEDOF concernant l’organisme est inattendue.")
        name = payload.get("name") or payload.get("legalName") or payload.get("raisonSociale")
        siret = payload.get("siret") or payload.get("siretNumber")
        if not isinstance(name, str) or not isinstance(siret, (str, int)):
            raise WedofApiError("La réponse WEDOF concernant l’organisme est inattendue.")
        return {"name": name.strip(), "siret": str(siret).strip()}

    def check_registration_folders_access(self) -> Dict[str, Any]:
        payload = self._get_json("/registrationFolders", params={"limit": 1, "page": 1})
        items = self._folder_items(payload)
        return {"accessible": True, "result_count": len(items)}

    def test_connection(self) -> Dict[str, Any]:
        organism = self.get_current_organism()
        folders = self.check_registration_folders_access()
        return {
            "ok": True,
            "organism": organism,
            "registration_folders_access": folders["accessible"],
            "registration_folders_sample_count": folders["result_count"],
            "automation_enabled": read_env_bool("WEDOF_AUTOMATION_ENABLED", default=False),
            "dry_run": read_env_bool("WEDOF_DRY_RUN", default=True),
        }
