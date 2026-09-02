"""Client HTTP WEDOF : lectures résilientes et mutations sans retry."""

import logging
import os
import re
import time
import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

import requests

from wedof_governor import (
    WedofGovernorError,
    WedofQuotaExceeded,
    reserve_request,
)


WEDOF_BASE_URL = "https://www.wedof.fr/api"
_TRUE_VALUES = {"true", "1", "yes", "on"}
logger = logging.getLogger(__name__)


class WedofConfigurationError(RuntimeError):
    """Configuration WEDOF absente ou inutilisable."""


class WedofApiError(RuntimeError):
    """Erreur volontairement nettoyée renvoyée par le client WEDOF."""

    def __init__(self, message: str, code: str = "wedof_api_error", retryable: bool = False,
                 http_status: Optional[int] = None, ambiguous: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.retryable = retryable
        self.http_status = http_status
        self.ambiguous = ambiguous


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
    """Client WEDOF dont les deux seules mutations sont explicites et sans retry."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        session: Optional[requests.Session] = None,
        origin: str = "gestionstagiaires",
    ) -> None:
        key = (api_key if api_key is not None else os.environ.get("WEDOF_API_KEY", "")).strip()
        if not key:
            raise WedofConfigurationError("La variable WEDOF_API_KEY est absente.")
        self._session = session or requests.Session()
        self._origin = str(origin or "gestionstagiaires")[:80]
        self._headers = {
            "Accept": "application/json",
            "X-Api-Key": key,
            "User-Agent": "IntegraleAcademy-GestionStagiaires/2026.08",
            "X-Integrale-Application": self._origin,
        }
        self._mutation_headers = {**self._headers, "Content-Type": "application/json"}
        self._timeout = (
            _bounded_env("WEDOF_CONNECT_TIMEOUT_SECONDS", 5, 1, 30),
            _bounded_env("WEDOF_READ_TIMEOUT_SECONDS", 45, 10, 120),
        )
        self._max_attempts = _bounded_env("WEDOF_GET_MAX_ATTEMPTS", 3, 1, 4, integer=True)
        self._backoff = _bounded_env("WEDOF_GET_BACKOFF_SECONDS", 1, 0, 10)
        self._page_limit = _bounded_env("WEDOF_PAGE_LIMIT", 50, 10, 100, integer=True)

    def _reserve(
        self, method: str, path: str, *, operation: Optional[str] = None,
        allow_over_limit: bool = False,
    ) -> None:
        safe_path = re.sub(r"(/registrationFolders/)[^/]+", r"\1:id", path)
        resolved_operation = str(operation or "").strip()[:80]
        if not resolved_operation:
            if safe_path.rstrip("/").endswith("/registrationFolders"):
                resolved_operation = "list_registration_folders"
            elif "/registrationFolders/:id" in safe_path:
                resolved_operation = "registration_folder_action" if method != "GET" else "get_registration_folder"
            elif safe_path.rstrip("/").endswith("/organisms/me"):
                resolved_operation = "get_current_organism"
            else:
                resolved_operation = "wedof_request"
        try:
            reservation: Dict[str, Any] = {
                "origin": self._origin,
                "operation": resolved_operation,
                "method": method,
                "path": safe_path,
            }
            if allow_over_limit:
                reservation["allow_over_limit"] = True
            reserve_request(**reservation)
        except WedofQuotaExceeded as exc:
            raise WedofApiError(
                "Le plafond interne de requêtes WEDOF est atteint.",
                "wedof_quota_exceeded", False, 429,
            ) from exc
        except WedofGovernorError as exc:
            raise WedofApiError(
                "Le compteur WEDOF central est indisponible ; requête bloquée.",
                "wedof_governor_unavailable", True, 503,
            ) from exc

    def _get_json_response(self, path: str, *, params: Optional[Mapping[str, Any]] = None,
                           timeout: Optional[Tuple[float, float]] = None,
                           max_attempts: Optional[int] = None, backoff: Optional[float] = None,
                           operation: Optional[str] = None,
                           allow_over_limit: bool = False) -> Tuple[Any, Any]:
        response = None
        request_timeout = timeout or self._timeout
        attempts = self._max_attempts if max_attempts is None else max(1, int(max_attempts))
        retry_backoff = self._backoff if backoff is None else max(0, float(backoff))
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                self._reserve(
                    "GET", path, operation=operation,
                    allow_over_limit=allow_over_limit,
                )
                response = self._session.get(f"{WEDOF_BASE_URL}{path}", headers=self._headers,
                                             params=params, timeout=request_timeout)
            except requests.Timeout as exc:
                logger.warning("WEDOF GET path=%s etat=%s page=%s tentative=%s erreur=timeout duree=%.3f",
                               path, (params or {}).get("state"), (params or {}).get("page"), attempt,
                               time.monotonic() - started)
                if attempt == attempts:
                    raise WedofApiError("L’API WEDOF n’a pas répondu dans le délai prévu.", "wedof_timeout", True) from exc
                time.sleep(retry_backoff * (2 ** (attempt - 1)))
                continue
            except requests.ConnectionError as exc:
                logger.warning("WEDOF GET path=%s etat=%s page=%s tentative=%s erreur=connexion duree=%.3f",
                               path, (params or {}).get("state"), (params or {}).get("page"), attempt,
                               time.monotonic() - started)
                if attempt == attempts:
                    raise WedofApiError("Impossible de se connecter à l’API WEDOF.", "wedof_connection_error", True) from exc
                time.sleep(retry_backoff * (2 ** (attempt - 1)))
                continue
            except requests.RequestException as exc:
                raise WedofApiError("Impossible de se connecter à l’API WEDOF.", "wedof_connection_error") from exc

            retryable_status = response.status_code in {429, 500, 502, 503, 504}
            logger.info("WEDOF GET path=%s etat=%s page=%s tentative=%s code_http=%s duree=%.3f",
                        path, (params or {}).get("state"), (params or {}).get("page"), attempt,
                        response.status_code, time.monotonic() - started)
            if not retryable_status or attempt == attempts:
                break
            delay = retry_backoff * (2 ** (attempt - 1))
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

    def _post_json_response(
        self, path: str, payload: Mapping[str, Any], *,
        operation: Optional[str] = None, allow_over_limit: bool = False,
    ) -> Tuple[Any, Any]:
        """Envoie exactement une fois une mutation; le moteur réconcilie toute ambiguïté."""
        try:
            self._reserve(
                "POST", path, operation=operation,
                allow_over_limit=allow_over_limit,
            )
            response = self._session.post(f"{WEDOF_BASE_URL}{path}", headers=self._mutation_headers,
                                          json=dict(payload), timeout=self._timeout)
        except requests.Timeout as exc:
            raise WedofApiError("Réponse WEDOF incertaine après envoi.", "wedof_timeout", False,
                                ambiguous=True) from exc
        except requests.ConnectionError as exc:
            raise WedofApiError("Résultat WEDOF incertain après une erreur de connexion.",
                                "wedof_connection_error", False, ambiguous=True) from exc
        except requests.RequestException as exc:
            raise WedofApiError("Impossible d’envoyer la déclaration à WEDOF.",
                                "wedof_connection_error", False, ambiguous=True) from exc
        status = response.status_code
        if not 200 <= status < 300:
            codes = {400: "wedof_bad_request", 401: "wedof_unauthorized", 403: "wedof_forbidden",
                     404: "wedof_not_found", 409: "wedof_conflict", 429: "wedof_rate_limited"}
            code = codes.get(status, "wedof_server_error" if status >= 500 else "wedof_api_error")
            raise WedofApiError("La déclaration WEDOF a été refusée.", code,
                                status == 429 or status >= 500, status)
        try:
            return (response.json() if getattr(response, "content", b"") else {}), response
        except (ValueError, TypeError):
            return {}, response

    @staticmethod
    def _identifier(external_id: str) -> str:
        identifier = str(external_id or "").strip()
        if not identifier or "/" in identifier:
            raise WedofApiError("L’identifiant du dossier WEDOF est invalide.")
        return identifier

    def declare_registration_folder_in_training(self, external_id: str, date: str) -> Any:
        identifier = self._identifier(external_id)
        business_date = self._validated_date(date)
        return self._post_json_response(f"/registrationFolders/{identifier}/inTraining",
                                        {"date": business_date},
                                        operation="urgent_automation_entry_training",
                                        allow_over_limit=True)[0]

    def declare_registration_folder_service_done(self, external_id: str, date: str,
                                                  absence_duration: float = 0,
                                                  force_majeure_absence: bool = False,
                                                  training_duration: Optional[float] = None) -> Any:
        identifier = self._identifier(external_id)
        payload: Dict[str, Any] = {"absenceDuration": absence_duration,
                                  "forceMajeureAbsence": bool(force_majeure_absence),
                                  "date": self._validated_date(date)}
        if isinstance(training_duration, (int, float)) and not isinstance(training_duration, bool) and training_duration >= 0:
            payload["trainingDuration"] = training_duration
        return self._post_json_response(
            f"/registrationFolders/{identifier}/serviceDone", payload,
            operation="urgent_automation_service_done",
            allow_over_limit=True,
        )[0]

    @staticmethod
    def _validated_date(value: str) -> str:
        import datetime as dt
        try:
            return dt.date.fromisoformat(str(value)).isoformat()
        except (TypeError, ValueError) as exc:
            raise WedofApiError("La date métier WEDOF est invalide.", "invalid_business_date") from exc

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

    def list_registration_folders_interactive(
        self, state: str, *, limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Lit une seule page après une action admin explicite.

        Cette variante ne réessaie jamais la requête et ne suit aucune page
        supplémentaire. Une recherche d'identité reste ainsi bornée à quatre
        appels WEDOF au maximum, un par état associable.
        """
        if state not in {"accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated"}:
            raise ValueError("État WEDOF non autorisé pour la recherche manuelle.")
        page_limit = max(1, min(int(limit), 100))
        payload, response = self._get_json_response(
            "/registrationFolders",
            params={"state": state, "limit": page_limit, "page": 1},
            timeout=(3, 8),
            max_attempts=1,
            backoff=0,
            operation="cpf_identity_manual_search",
        )
        items = self._folder_items(payload)
        logger.info(
            "WEDOF GET dossiers manuel code_http=%s etat=%s nombre=%s",
            response.status_code, state, len(items),
        )
        return items

    def get_registration_folder(self, external_id: str) -> Dict[str, Any]:
        """Relit un dossier précis sans jamais effectuer de requête mutatrice."""
        identifier = str(external_id or "").strip()
        if not identifier or "/" in identifier:
            raise WedofApiError("L’identifiant du dossier WEDOF est invalide.")
        payload = self._get_json(f"/registrationFolders/{identifier}")
        if not isinstance(payload, dict):
            raise WedofApiError("La réponse WEDOF concernant le dossier est inattendue.")
        return payload

    def get_registration_folder_for_automation(self, external_id: str) -> Dict[str, Any]:
        """Relit un dossier dû sans que les plafonds internes annulent l’action."""
        identifier = self._identifier(external_id)
        payload = self._get_json_response(
            f"/registrationFolders/{identifier}",
            operation="urgent_automation_due_get",
            allow_over_limit=True,
        )[0]
        if not isinstance(payload, dict):
            raise WedofApiError("La réponse WEDOF concernant le dossier est inattendue.")
        return payload

    def get_registration_folder_interactive(
        self, external_id: str, *, operation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Lecture utilisateur bornée, sans retry ni attente Retry-After."""
        identifier = str(external_id or "").strip()
        if not identifier or "/" in identifier:
            raise WedofApiError("L’identifiant du dossier WEDOF est invalide.")
        payload = self._get_json_response(
            f"/registrationFolders/{identifier}", timeout=(3, 8), max_attempts=1,
            backoff=0, operation=operation,
        )[0]
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
