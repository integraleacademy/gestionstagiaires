"""Standalone AKTO/CFADock V2 connector for the BTS administration area.

The module deliberately does not import the Flask application and does not use
``data.json``.  AKTO data lives in its own SQLite database so the BTS area can
evolve independently from the historical training-session features.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests


AKTO_REQUIRED_ENV = (
    "AKTO_API_BASE_URL",
    "AKTO_OAUTH_TOKEN_URL",
    "AKTO_OAUTH_CLIENT_ID",
    "AKTO_OAUTH_CLIENT_SECRET",
    "AKTO_API_KEY",
)

AKTO_ENV_LABELS = {
    "AKTO_API_BASE_URL": "URL de l’API AKTO",
    "AKTO_OAUTH_TOKEN_URL": "URL OAuth AKTO",
    "AKTO_OAUTH_CLIENT_ID": "Client ID du logiciel",
    "AKTO_OAUTH_CLIENT_SECRET": "Client Secret du logiciel",
    "AKTO_API_KEY": "Clé API du CFA",
}

AKTO_STATE_LABELS = {
    "TRANSMIS": "Transmis",
    "EN_COURS_INSTRUCTION": "En cours d’instruction",
    "ENGAGE": "Engagé",
    "REFUSE": "Refusé",
    "ANNULE": "Annulé",
    "SOLDE": "Soldé",
    "RUPTU": "Rompu",
}


class AktoConfigurationError(RuntimeError):
    """Raised when the AKTO software credentials are incomplete."""

    def __init__(self, missing: Sequence[str]):
        self.missing = tuple(missing)
        super().__init__("Configuration AKTO incomplète : " + ", ".join(self.missing))


class AktoApiError(RuntimeError):
    """Safe API error that never contains credentials or response bodies."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, code: str = "akto_api_error"):
        self.status_code = status_code
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AktoConfig:
    api_base_url: str
    oauth_token_url: str
    oauth_client_id: str
    oauth_client_secret: str
    api_key: str
    oauth_scope: str = ".default"
    editor: str = "Intégrale Academy"
    software: str = "Gestion Stagiaires · Espace BTS"
    software_version: str = "1.0"
    timeout_seconds: int = 45
    max_pages: int = 1000

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "AktoConfig":
        env = os.environ if environ is None else environ

        def value(name: str, default: str = "") -> str:
            return str(env.get(name, default) or "").strip()

        def positive_int(name: str, default: int) -> int:
            try:
                parsed = int(value(name, str(default)))
            except (TypeError, ValueError):
                return default
            return parsed if parsed > 0 else default

        return cls(
            api_base_url=value("AKTO_API_BASE_URL").rstrip("/"),
            oauth_token_url=value("AKTO_OAUTH_TOKEN_URL"),
            oauth_client_id=value("AKTO_OAUTH_CLIENT_ID"),
            oauth_client_secret=value("AKTO_OAUTH_CLIENT_SECRET"),
            api_key=value("AKTO_API_KEY"),
            oauth_scope=value("AKTO_OAUTH_SCOPE", ".default"),
            editor=value("AKTO_API_EDITOR", "Intégrale Academy"),
            software=value("AKTO_API_SOFTWARE", "Gestion Stagiaires · Espace BTS"),
            software_version=value("AKTO_API_VERSION", "1.0"),
            timeout_seconds=positive_int("AKTO_REQUEST_TIMEOUT_SECONDS", 45),
            max_pages=positive_int("AKTO_MAX_PAGES", 1000),
        )

    @property
    def missing(self) -> List[str]:
        values = {
            "AKTO_API_BASE_URL": self.api_base_url,
            "AKTO_OAUTH_TOKEN_URL": self.oauth_token_url,
            "AKTO_OAUTH_CLIENT_ID": self.oauth_client_id,
            "AKTO_OAUTH_CLIENT_SECRET": self.oauth_client_secret,
            "AKTO_API_KEY": self.api_key,
        }
        return [name for name in AKTO_REQUIRED_ENV if not values[name]]

    @property
    def ready(self) -> bool:
        return not self.missing

    def require_ready(self) -> None:
        if self.missing:
            raise AktoConfigurationError(self.missing)
        for name, raw_url in (
            ("AKTO_API_BASE_URL", self.api_base_url),
            ("AKTO_OAUTH_TOKEN_URL", self.oauth_token_url),
        ):
            parsed = urlparse(raw_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise AktoConfigurationError([name])

    def diagnostics(self) -> Dict[str, Any]:
        missing = self.missing
        return {
            "ready": not missing,
            "missing": missing,
            "missing_labels": [AKTO_ENV_LABELS.get(name, name) for name in missing],
            "api_key_present": bool(self.api_key),
            "oauth_client_present": bool(self.oauth_client_id and self.oauth_client_secret),
            "api_url_present": bool(self.api_base_url),
            "token_url_present": bool(self.oauth_token_url),
        }


class AktoClient:
    """Minimal client for the read-only CFADock V2 endpoints used by AKTO."""

    def __init__(self, config: AktoConfig, *, http_session: Optional[requests.Session] = None):
        config.require_ready()
        self.config = config
        self.http = http_session or requests.Session()
        self._access_token = ""
        self._token_valid_until = 0.0

    def _safe_error_description(self, response: Any) -> str:
        description = ""
        try:
            payload = response.json()
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            for key in ("description", "message", "error_description", "error"):
                if isinstance(payload.get(key), str) and payload.get(key).strip():
                    description = payload[key].strip()
                    break
            if not description and isinstance(payload.get("errors"), list) and payload["errors"]:
                first = payload["errors"][0]
                if isinstance(first, dict):
                    description = str(first.get("description") or first.get("message") or "").strip()
        description = re.sub(r"[\r\n\t]+", " ", description)[:240]
        for secret in (self.config.oauth_client_secret, self.config.api_key, self._access_token):
            if secret:
                description = description.replace(secret, "[secret masqué]")
        return description

    def _get_access_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._access_token and time.monotonic() < self._token_valid_until:
            return self._access_token

        data = {
            "grant_type": "client_credentials",
            "client_id": self.config.oauth_client_id,
            "client_secret": self.config.oauth_client_secret,
        }
        if self.config.oauth_scope:
            data["scope"] = self.config.oauth_scope
        try:
            response = self.http.post(
                self.config.oauth_token_url,
                data=data,
                headers={"Accept": "application/json"},
                timeout=(5, self.config.timeout_seconds),
            )
        except requests.RequestException as exc:
            raise AktoApiError(
                "Le serveur d’authentification AKTO est momentanément inaccessible.",
                code="oauth_unavailable",
            ) from exc

        if not 200 <= int(response.status_code) < 300:
            detail = self._safe_error_description(response)
            message = "Authentification du logiciel refusée par AKTO."
            if detail:
                message += " " + detail
            raise AktoApiError(message, status_code=int(response.status_code), code="oauth_rejected")

        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise AktoApiError("Réponse OAuth AKTO illisible.", code="oauth_invalid_response") from exc
        token = str(payload.get("access_token") or "").strip() if isinstance(payload, dict) else ""
        if not token:
            raise AktoApiError("Le serveur OAuth AKTO n’a renvoyé aucun jeton.", code="oauth_missing_token")
        try:
            expires_in = max(60, int(payload.get("expires_in") or 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        self._access_token = token
        self._token_valid_until = time.monotonic() + max(30, expires_in - 60)
        return token

    def _request_json(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self.config.api_base_url + "/" + path.lstrip("/")
        for attempt in range(2):
            token = self._get_access_token(force_refresh=attempt > 0)
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "X-Api-Key": self.config.api_key,
                "EDITEUR": self.config.editor,
                "LOGICIEL": self.config.software,
                "VERSION": self.config.software_version,
            }
            try:
                response = self.http.get(
                    url,
                    params=params or {},
                    headers=headers,
                    timeout=(5, self.config.timeout_seconds),
                )
            except requests.RequestException as exc:
                raise AktoApiError(
                    "L’API AKTO est momentanément inaccessible. Le cache existant est conservé.",
                    code="api_unavailable",
                ) from exc

            status_code = int(response.status_code)
            if status_code == 401 and attempt == 0:
                self._access_token = ""
                self._token_valid_until = 0.0
                continue
            if not 200 <= status_code < 300:
                detail = self._safe_error_description(response)
                if status_code == 403:
                    message = "Accès AKTO refusé : vérifiez la clé API CFA et ses habilitations."
                elif status_code == 429:
                    message = "Limite de requêtes AKTO atteinte. Réessayez plus tard."
                else:
                    message = f"AKTO a refusé la requête (HTTP {status_code})."
                if detail:
                    message += " " + detail
                raise AktoApiError(message, status_code=status_code)
            try:
                return response.json()
            except (ValueError, TypeError) as exc:
                raise AktoApiError("Réponse AKTO illisible. Le cache existant est conservé.", code="invalid_json") from exc
        raise AktoApiError("Authentification AKTO expirée.", status_code=401)

    @staticmethod
    def _page_container(payload: Any) -> Dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
            return payload[0]
        raise AktoApiError("Format de pagination AKTO inattendu.", code="invalid_pagination")

    def _paginate(self, path: str, item_key: str, *, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        seen_pages = set()
        expected_total: Optional[int] = None
        for page_number in range(1, self.config.max_pages + 1):
            query = dict(params or {})
            query["numeroPage"] = page_number
            container = self._page_container(self._request_json(path, params=query))
            raw_items = container.get(item_key)
            items = [item for item in (raw_items or []) if isinstance(item, dict)]
            try:
                expected_total = int(container.get("total"))
            except (TypeError, ValueError):
                pass
            fingerprint = json.dumps(items, ensure_ascii=False, sort_keys=True, default=str)
            if fingerprint in seen_pages and items:
                raise AktoApiError("AKTO a renvoyé deux fois la même page ; synchronisation arrêtée par sécurité.", code="repeated_page")
            seen_pages.add(fingerprint)
            collected.extend(items)
            if not items or (expected_total is not None and len(collected) >= expected_total):
                return collected[:expected_total] if expected_total is not None else collected
        if expected_total is not None and len(collected) >= expected_total:
            return collected[:expected_total]
        raise AktoApiError("Le nombre maximal de pages AKTO a été atteint avant la fin des données.", code="page_limit")

    def list_dossier_states(self) -> List[Dict[str, Any]]:
        return self._paginate("/v2/dossiers/etats", "EtatDossierResult")

    def get_dossier(self, internal_number: str) -> Dict[str, Any]:
        payload = self._request_json("/v2/dossiers", params={"numeroInterne": internal_number})
        if not isinstance(payload, dict):
            raise AktoApiError("Format du dossier AKTO inattendu.", code="invalid_dossier")
        return payload

    def list_invoice_states(self) -> List[Dict[str, Any]]:
        return self._paginate("/v2/factures/etats", "factures")


_SENSITIVE_KEY_PARTS = {
    "nir",
    "iban",
    "bic",
    "apikey",
    "clientsecret",
    "accesstoken",
    "refreshtoken",
    "password",
    "motdepasse",
}


def redact_sensitive_payload(value: Any) -> Any:
    """Return a JSON-compatible copy with secrets and bank/NIR fields removed."""
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
                redacted[str(key)] = "[MASQUÉ]"
            else:
                redacted[str(key)] = redact_sensitive_payload(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_sensitive_payload(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _date(value: Any) -> str:
    return _text(value)[:10]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def normalize_invoice(invoice: Dict[str, Any], *, synced_at: str) -> Dict[str, Any]:
    invoice_number = _text(invoice.get("numeroInterneFacture"))
    links = []
    for link in _list(invoice.get("dossiers")):
        if not isinstance(link, dict):
            continue
        links.append({
            "internal_number": _text(link.get("numeroInterneDossier")),
            "external_number": _text(link.get("numeroExterneDossier")),
            "amount": _number(link.get("montant")),
        })
    return {
        "internal_number": invoice_number,
        "reference": _text(invoice.get("referenceFactureCFA")),
        "state": _text(invoice.get("etatFacture")),
        "amount": _number(invoice.get("montantFacture")),
        "payment_reference": _text(invoice.get("referenceVirement")),
        "payment_date": _date(invoice.get("dateReglement")),
        "comment": _text(invoice.get("commentaire")),
        "dossier_links": links,
        "payload": redact_sensitive_payload(invoice),
        "synced_at": synced_at,
    }


def _invoices_for_contract(
    invoices: Sequence[Dict[str, Any]], internal_number: str, external_number: str,
) -> List[Dict[str, Any]]:
    matches = []
    for invoice in invoices:
        allocations = []
        for link in invoice.get("dossier_links", []):
            if (
                internal_number and link.get("internal_number") == internal_number
            ) or (
                external_number and link.get("external_number") == external_number
            ):
                allocations.append(link)
        if allocations:
            item = dict(invoice)
            item["allocated_amount"] = sum(_number(link.get("amount")) for link in allocations)
            item.pop("payload", None)
            item.pop("dossier_links", None)
            matches.append(item)
    return matches


def normalize_contract(
    state_row: Dict[str, Any],
    dossier: Dict[str, Any],
    invoices: Sequence[Dict[str, Any]],
    *,
    synced_at: str,
    detail_loaded: bool,
) -> Dict[str, Any]:
    cerfa = _dict(dossier.get("cerfa"))
    apprentice = _dict(cerfa.get("apprenti"))
    employer = _dict(cerfa.get("employeur") or cerfa.get("employeurV2"))
    training = _dict(cerfa.get("formation"))
    contract = _dict(cerfa.get("contrat"))
    internal_number = _text(cerfa.get("numeroInterne") or state_row.get("numeroInterne"))
    external_number = _text(cerfa.get("numeroExterne") or state_row.get("numeroExterne"))
    state = _text(cerfa.get("etat") or state_row.get("etat"))
    schedules = [redact_sensitive_payload(item) for item in _list(dossier.get("echeances")) if isinstance(item, dict)]
    extra_costs = [
        redact_sensitive_payload(item)
        for item in _list(dossier.get("engagementsFraisAnnexe"))
        if isinstance(item, dict)
    ]
    contract_invoices = _invoices_for_contract(invoices, internal_number, external_number)
    total_due = sum(_number(item.get("montantTotal")) for item in schedules)
    total_paid = sum(_number(item.get("montantRegle")) for item in schedules)
    total_pending = sum(_number(item.get("montantEnCoursInstruction")) for item in schedules)
    invoice_total = sum(_number(item.get("allocated_amount")) for item in contract_invoices)
    invoice_paid = sum(
        _number(item.get("allocated_amount"))
        for item in contract_invoices
        if item.get("state") == "REGLE"
    )
    payload = redact_sensitive_payload({"etat": state_row, "dossier": dossier})
    return {
        "internal_number": internal_number,
        "external_number": external_number,
        "deca_number": _text(cerfa.get("numeroDeca") or state_row.get("numeroDeca") or contract.get("noContrat")),
        "state": state,
        "state_comment": _text(cerfa.get("commentaireEtat") or dossier.get("comment")),
        "apprentice_first_name": _text(apprentice.get("prenom")),
        "apprentice_last_name": _text(apprentice.get("nom")),
        "apprentice_email": _text(apprentice.get("courriel")),
        "apprentice_phone": _text(apprentice.get("telephone")),
        "apprentice_birth_date": _date(apprentice.get("dateNaissance")),
        "apprentice_handicap": 1 if apprentice.get("handicap") is True else 0,
        "employer_name": _text(employer.get("denomination") or " ".join(filter(None, [_text(employer.get("prenom")), _text(employer.get("nom"))]))),
        "employer_siret": _text(employer.get("siret")),
        "employer_email": _text(employer.get("courriel")),
        "employer_phone": _text(employer.get("telephone")),
        "training_title": _text(training.get("intituleQualification")),
        "rncp": _text(training.get("rncp")),
        "diploma_code": _text(training.get("codeDiplome")),
        "training_start": _date(training.get("dateDebutFormation")),
        "training_end": _date(training.get("dateFinFormation")),
        "training_hours": _number(training.get("dureeFormation")),
        "remote_hours": _number(training.get("nombreHeuresEnDistanciel")),
        "contract_number": _text(contract.get("noContrat")),
        "contract_type": _text(contract.get("typeContratApp")),
        "contract_conclusion": _date(contract.get("dateConclusion")),
        "contract_start": _date(contract.get("dateDebutContrat")),
        "contract_end": _date(contract.get("dateFinContrat")),
        "contract_break_date": _date(contract.get("dateRupture")),
        "gross_salary": _number(contract.get("salaireEmbauche")),
        "engagement": _number(dossier.get("engagement")),
        "total_due": total_due,
        "total_paid": total_paid,
        "total_pending": total_pending,
        "invoice_total": invoice_total,
        "invoice_paid": invoice_paid,
        "schedules": schedules,
        "extra_costs": extra_costs,
        "billing_details": redact_sensitive_payload(_dict(dossier.get("detailsFacturation"))),
        "invoices": contract_invoices,
        "payload": payload,
        "detail_loaded": 1 if detail_loaded else 0,
        "synced_at": synced_at,
    }


class AktoBtsStore:
    """Dedicated SQLite persistence for the independent BTS/AKTO area."""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS contracts (
                    internal_number TEXT PRIMARY KEY,
                    external_number TEXT NOT NULL DEFAULT '',
                    deca_number TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT '',
                    state_comment TEXT NOT NULL DEFAULT '',
                    apprentice_first_name TEXT NOT NULL DEFAULT '',
                    apprentice_last_name TEXT NOT NULL DEFAULT '',
                    apprentice_email TEXT NOT NULL DEFAULT '',
                    apprentice_phone TEXT NOT NULL DEFAULT '',
                    apprentice_birth_date TEXT NOT NULL DEFAULT '',
                    apprentice_handicap INTEGER NOT NULL DEFAULT 0,
                    employer_name TEXT NOT NULL DEFAULT '',
                    employer_siret TEXT NOT NULL DEFAULT '',
                    employer_email TEXT NOT NULL DEFAULT '',
                    employer_phone TEXT NOT NULL DEFAULT '',
                    training_title TEXT NOT NULL DEFAULT '',
                    rncp TEXT NOT NULL DEFAULT '',
                    diploma_code TEXT NOT NULL DEFAULT '',
                    training_start TEXT NOT NULL DEFAULT '',
                    training_end TEXT NOT NULL DEFAULT '',
                    training_hours REAL NOT NULL DEFAULT 0,
                    remote_hours REAL NOT NULL DEFAULT 0,
                    contract_number TEXT NOT NULL DEFAULT '',
                    contract_type TEXT NOT NULL DEFAULT '',
                    contract_conclusion TEXT NOT NULL DEFAULT '',
                    contract_start TEXT NOT NULL DEFAULT '',
                    contract_end TEXT NOT NULL DEFAULT '',
                    contract_break_date TEXT NOT NULL DEFAULT '',
                    gross_salary REAL NOT NULL DEFAULT 0,
                    engagement REAL NOT NULL DEFAULT 0,
                    total_due REAL NOT NULL DEFAULT 0,
                    total_paid REAL NOT NULL DEFAULT 0,
                    total_pending REAL NOT NULL DEFAULT 0,
                    invoice_total REAL NOT NULL DEFAULT 0,
                    invoice_paid REAL NOT NULL DEFAULT 0,
                    schedules_json TEXT NOT NULL DEFAULT '[]',
                    extra_costs_json TEXT NOT NULL DEFAULT '[]',
                    billing_details_json TEXT NOT NULL DEFAULT '{}',
                    invoices_json TEXT NOT NULL DEFAULT '[]',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    detail_loaded INTEGER NOT NULL DEFAULT 0,
                    synced_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_akto_contracts_state ON contracts(state);
                CREATE INDEX IF NOT EXISTS idx_akto_contracts_apprentice ON contracts(apprentice_last_name, apprentice_first_name);

                CREATE TABLE IF NOT EXISTS invoices (
                    internal_number TEXT PRIMARY KEY,
                    reference TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT '',
                    amount REAL NOT NULL DEFAULT 0,
                    payment_reference TEXT NOT NULL DEFAULT '',
                    payment_date TEXT NOT NULL DEFAULT '',
                    comment TEXT NOT NULL DEFAULT '',
                    dossier_links_json TEXT NOT NULL DEFAULT '[]',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    synced_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_akto_invoices_state ON invoices(state);

                CREATE TABLE IF NOT EXISTS sync_runs (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    contracts_total INTEGER NOT NULL DEFAULT 0,
                    details_loaded INTEGER NOT NULL DEFAULT 0,
                    invoices_total INTEGER NOT NULL DEFAULT 0,
                    errors_count INTEGER NOT NULL DEFAULT 0,
                    error_summary TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_akto_sync_runs_started ON sync_runs(started_at DESC);
                """
            )

    def start_run(self, run_id: str, *, started_at: Optional[str] = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sync_runs (id, started_at, status) VALUES (?, ?, 'running')",
                (run_id, started_at or _utc_now_iso()),
            )

    def fail_run(self, run_id: str, message: str) -> None:
        safe_message = re.sub(r"[\r\n\t]+", " ", _text(message))[:500]
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sync_runs
                   SET status = 'error', finished_at = ?, errors_count = 1, error_summary = ?
                 WHERE id = ?
                """,
                (_utc_now_iso(), safe_message, run_id),
            )

    def replace_snapshot(
        self,
        run_id: str,
        contracts: Sequence[Dict[str, Any]],
        invoices: Sequence[Dict[str, Any]],
        *,
        errors: Sequence[str],
    ) -> None:
        contract_columns = (
            "internal_number", "external_number", "deca_number", "state", "state_comment",
            "apprentice_first_name", "apprentice_last_name", "apprentice_email", "apprentice_phone",
            "apprentice_birth_date", "apprentice_handicap", "employer_name", "employer_siret",
            "employer_email", "employer_phone", "training_title", "rncp", "diploma_code",
            "training_start", "training_end", "training_hours", "remote_hours", "contract_number",
            "contract_type", "contract_conclusion", "contract_start", "contract_end",
            "contract_break_date", "gross_salary", "engagement", "total_due", "total_paid",
            "total_pending", "invoice_total", "invoice_paid", "schedules_json", "extra_costs_json",
            "billing_details_json", "invoices_json", "payload_json", "detail_loaded", "synced_at",
        )
        invoice_columns = (
            "internal_number", "reference", "state", "amount", "payment_reference", "payment_date",
            "comment", "dossier_links_json", "payload_json", "synced_at",
        )

        def contract_values(item: Dict[str, Any]) -> Tuple[Any, ...]:
            row = dict(item)
            row["schedules_json"] = _json(row.pop("schedules", []))
            row["extra_costs_json"] = _json(row.pop("extra_costs", []))
            row["billing_details_json"] = _json(row.pop("billing_details", {}))
            row["invoices_json"] = _json(row.pop("invoices", []))
            row["payload_json"] = _json(row.pop("payload", {}))
            return tuple(row.get(column, "") for column in contract_columns)

        def invoice_values(item: Dict[str, Any]) -> Tuple[Any, ...]:
            row = dict(item)
            row["dossier_links_json"] = _json(row.pop("dossier_links", []))
            row["payload_json"] = _json(row.pop("payload", {}))
            return tuple(row.get(column, "") for column in invoice_columns)

        status = "partial" if errors else "success"
        error_summary = " · ".join(_text(item) for item in errors if _text(item))[:1000]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM contracts")
            connection.execute("DELETE FROM invoices")
            if contracts:
                placeholders = ",".join("?" for _ in contract_columns)
                connection.executemany(
                    f"INSERT INTO contracts ({','.join(contract_columns)}) VALUES ({placeholders})",
                    [contract_values(item) for item in contracts],
                )
            if invoices:
                placeholders = ",".join("?" for _ in invoice_columns)
                connection.executemany(
                    f"INSERT INTO invoices ({','.join(invoice_columns)}) VALUES ({placeholders})",
                    [invoice_values(item) for item in invoices],
                )
            connection.execute(
                """
                UPDATE sync_runs
                   SET status = ?, finished_at = ?, contracts_total = ?, details_loaded = ?,
                       invoices_total = ?, errors_count = ?, error_summary = ?
                 WHERE id = ?
                """,
                (
                    status,
                    _utc_now_iso(),
                    len(contracts),
                    sum(1 for item in contracts if item.get("detail_loaded")),
                    len(invoices),
                    len(errors),
                    error_summary,
                    run_id,
                ),
            )
            connection.commit()

    @staticmethod
    def _decode_contract_row(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        for source, target, fallback in (
            ("schedules_json", "schedules", []),
            ("extra_costs_json", "extra_costs", []),
            ("billing_details_json", "billing_details", {}),
            ("invoices_json", "invoices", []),
        ):
            try:
                item[target] = json.loads(item.pop(source))
            except (TypeError, ValueError):
                item[target] = fallback
        item.pop("payload_json", None)
        item["state_label"] = AKTO_STATE_LABELS.get(item.get("state"), item.get("state") or "Sans état")
        return item

    def dashboard(self, *, query: str = "", state: str = "", page: int = 1, per_page: int = 40) -> Dict[str, Any]:
        query = _text(query)[:120]
        state = _text(state)[:80]
        per_page = min(max(int(per_page or 40), 10), 100)
        page = max(int(page or 1), 1)
        with self._connect() as connection:
            stats_row = connection.execute(
                """
                SELECT COUNT(*) AS contracts_total,
                       COALESCE(SUM(engagement), 0) AS engagement_total,
                       COALESCE(SUM(total_due), 0) AS due_total,
                       COALESCE(SUM(total_paid), 0) AS paid_total,
                       COALESCE(SUM(total_pending), 0) AS pending_total,
                       COALESCE(SUM(invoice_total), 0) AS invoiced_total,
                       COALESCE(SUM(invoice_paid), 0) AS invoices_paid_total,
                       COALESCE(SUM(CASE WHEN detail_loaded = 0 THEN 1 ELSE 0 END), 0) AS details_missing
                  FROM contracts
                """
            ).fetchone()
            invoice_stats = connection.execute(
                """
                SELECT COUNT(*) AS invoices_total,
                       COALESCE(SUM(CASE WHEN state = 'REGLE' THEN 1 ELSE 0 END), 0) AS invoices_paid_count
                  FROM invoices
                """
            ).fetchone()
            state_rows = connection.execute(
                "SELECT state, COUNT(*) AS count FROM contracts GROUP BY state ORDER BY count DESC, state"
            ).fetchall()

            clauses: List[str] = []
            parameters: List[Any] = []
            if state:
                clauses.append("state = ?")
                parameters.append(state)
            if query:
                needle = "%" + query.casefold() + "%"
                searchable_columns = (
                    "apprentice_first_name", "apprentice_last_name", "apprentice_email",
                    "employer_name", "employer_siret", "training_title", "rncp",
                    "internal_number", "external_number", "deca_number", "contract_number",
                )
                clauses.append("(" + " OR ".join(f"LOWER({column}) LIKE ?" for column in searchable_columns) + ")")
                parameters.extend([needle] * len(searchable_columns))
            where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
            filtered_total = int(connection.execute(
                "SELECT COUNT(*) FROM contracts" + where_sql, parameters,
            ).fetchone()[0])
            pages = max(1, int(math.ceil(filtered_total / per_page)))
            page = min(page, pages)
            offset = (page - 1) * per_page
            rows = connection.execute(
                """
                SELECT * FROM contracts
                """ + where_sql + """
                 ORDER BY contract_start DESC, apprentice_last_name COLLATE NOCASE,
                          apprentice_first_name COLLATE NOCASE, internal_number
                 LIMIT ? OFFSET ?
                """,
                [*parameters, per_page, offset],
            ).fetchall()
            last_run_row = connection.execute(
                "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()

        stats = dict(stats_row or {})
        stats.update(dict(invoice_stats or {}))
        last_run = dict(last_run_row) if last_run_row else None
        if last_run and last_run.get("status") == "running":
            try:
                started = datetime.datetime.fromisoformat(str(last_run["started_at"]).replace("Z", "+00:00"))
                last_run["stale"] = datetime.datetime.now(datetime.timezone.utc) - started > datetime.timedelta(hours=2)
            except (TypeError, ValueError):
                last_run["stale"] = False
        return {
            "stats": stats,
            "states": [
                {
                    "value": row["state"],
                    "label": AKTO_STATE_LABELS.get(row["state"], row["state"] or "Sans état"),
                    "count": row["count"],
                }
                for row in state_rows
            ],
            "contracts": [self._decode_contract_row(row) for row in rows],
            "pagination": {
                "page": page,
                "pages": pages,
                "per_page": per_page,
                "total": filtered_total,
                "has_previous": page > 1,
                "has_next": page < pages,
            },
            "last_run": last_run,
        }

    def export_snapshot(self) -> Dict[str, Any]:
        with self._connect() as connection:
            contract_rows = connection.execute(
                "SELECT internal_number, payload_json, synced_at FROM contracts ORDER BY internal_number"
            ).fetchall()
            invoice_rows = connection.execute(
                "SELECT internal_number, payload_json, synced_at FROM invoices ORDER BY internal_number"
            ).fetchall()
            last_run = connection.execute(
                "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()

        def payload_rows(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
            result = []
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                except (TypeError, ValueError):
                    payload = {}
                result.append({
                    "numeroInterne": row["internal_number"],
                    "synchroniseLe": row["synced_at"],
                    "donnees": payload,
                })
            return result

        return {
            "exported_at": _utc_now_iso(),
            "source": "AKTO · API Convergence CFA/OPCO V2",
            "privacy": "Les NIR, IBAN et secrets sont masqués avant stockage.",
            "last_sync": dict(last_run) if last_run else None,
            "contracts": payload_rows(contract_rows),
            "invoices": payload_rows(invoice_rows),
        }


def sync_akto_bts(store: AktoBtsStore, client: AktoClient, run_id: str) -> Dict[str, Any]:
    """Fetch a complete snapshot and atomically replace the standalone cache."""
    synced_at = _utc_now_iso()
    state_rows = client.list_dossier_states()
    raw_invoices = client.list_invoice_states()

    invoices_by_number: Dict[str, Dict[str, Any]] = {}
    skipped_invoices = 0
    for raw_invoice in raw_invoices:
        invoice = normalize_invoice(raw_invoice, synced_at=synced_at)
        if not invoice["internal_number"]:
            skipped_invoices += 1
            continue
        invoices_by_number[invoice["internal_number"]] = invoice
    invoices = list(invoices_by_number.values())

    states_by_number: Dict[str, Dict[str, Any]] = {}
    skipped_states = 0
    for state_row in state_rows:
        internal_number = _text(state_row.get("numeroInterne"))
        if not internal_number:
            skipped_states += 1
            continue
        states_by_number[internal_number] = state_row

    errors: List[str] = []
    if skipped_states:
        errors.append(f"{skipped_states} état(s) sans numéro interne ignoré(s)")
    if skipped_invoices:
        errors.append(f"{skipped_invoices} facture(s) sans numéro interne ignorée(s)")

    contracts = []
    for internal_number, state_row in states_by_number.items():
        detail: Dict[str, Any] = {}
        detail_loaded = False
        try:
            detail = client.get_dossier(internal_number)
            detail_loaded = True
        except AktoApiError as exc:
            if exc.status_code in {401, 403, 429} or (exc.status_code and exc.status_code >= 500) or exc.status_code is None:
                raise
            errors.append(f"Dossier {internal_number} : détail indisponible")
        contracts.append(normalize_contract(
            state_row,
            detail,
            invoices,
            synced_at=synced_at,
            detail_loaded=detail_loaded,
        ))

    store.replace_snapshot(run_id, contracts, invoices, errors=errors)
    return {
        "status": "partial" if errors else "success",
        "contracts_total": len(contracts),
        "details_loaded": sum(1 for item in contracts if item.get("detail_loaded")),
        "invoices_total": len(invoices),
        "errors": errors,
    }


def new_sync_run_id() -> str:
    return uuid.uuid4().hex
