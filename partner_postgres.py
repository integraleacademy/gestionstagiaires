"""PostgreSQL persistence dedicated to external partner tenants.

The historical Intégrale dataset deliberately remains in ``data.json``.  This
module stores one isolated business payload per external partner and keeps the
small authentication records in indexed tables.  It has no Flask dependency so
the migration tooling can exercise it independently from the web application.

``psycopg`` is imported lazily: deployments where the feature flag is disabled
must keep the exact same startup and storage behaviour as before.
"""

from __future__ import annotations

import copy
import json
import re
import threading
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple


class PartnerPostgresError(RuntimeError):
    """Base exception for the partner PostgreSQL store."""


class PartnerPostgresUnavailable(PartnerPostgresError):
    """The configured database or driver cannot currently be reached."""


class PartnerPostgresValidationError(PartnerPostgresError):
    """A tenant bundle is unsafe or structurally invalid."""


class PartnerPostgresDuplicateEmail(PartnerPostgresValidationError):
    """An e-mail address is already attached to another partner account."""


class PartnerPostgresNotFound(PartnerPostgresError):
    """The requested tenant does not exist in PostgreSQL."""


class PartnerPostgresWriteConflict(PartnerPostgresError):
    """A stale request attempted to replace a newer tenant version."""


_PARTNER_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
_ALLOWED_ROLES = {"partner_admin", "viewer"}


SCHEMA_SQL = r"""
CREATE SCHEMA IF NOT EXISTS partner_store;

CREATE TABLE IF NOT EXISTS partner_store.tenants (
    partner_id TEXT PRIMARY KEY,
    partner JSONB NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    version BIGINT NOT NULL DEFAULT 1,
    source_checksum TEXT,
    imported_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tenants_partner_id_format
        CHECK (partner_id ~ '^[A-Za-z0-9_-]{8,64}$')
);

CREATE TABLE IF NOT EXISTS partner_store.users (
    id TEXT PRIMARY KEY,
    partner_id TEXT NOT NULL
        REFERENCES partner_store.tenants(partner_id) ON DELETE CASCADE,
    email_normalized TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    record JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_partner_role CHECK (role IN ('partner_admin', 'viewer'))
);

CREATE INDEX IF NOT EXISTS users_partner_id_idx
    ON partner_store.users(partner_id);

CREATE TABLE IF NOT EXISTS partner_store.invitations (
    id TEXT PRIMARY KEY,
    partner_id TEXT NOT NULL
        REFERENCES partner_store.tenants(partner_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    token_hash TEXT,
    record JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT invitations_user_fk
        FOREIGN KEY (user_id) REFERENCES partner_store.users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS invitations_partner_id_idx
    ON partner_store.invitations(partner_id);
CREATE UNIQUE INDEX IF NOT EXISTS invitations_token_hash_uidx
    ON partner_store.invitations(token_hash)
    WHERE token_hash IS NOT NULL AND token_hash <> '';

ALTER TABLE partner_store.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE partner_store.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE partner_store.invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE partner_store.tenants FORCE ROW LEVEL SECURITY;
ALTER TABLE partner_store.users FORCE ROW LEVEL SECURITY;
ALTER TABLE partner_store.invitations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope ON partner_store.tenants;
CREATE POLICY tenant_scope ON partner_store.tenants
    USING (
        COALESCE(current_setting('app.platform_admin', TRUE), '') = 'on'
        OR partner_id = COALESCE(current_setting('app.partner_id', TRUE), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.platform_admin', TRUE), '') = 'on'
        OR partner_id = COALESCE(current_setting('app.partner_id', TRUE), '')
    );

DROP POLICY IF EXISTS tenant_scope ON partner_store.users;
CREATE POLICY tenant_scope ON partner_store.users
    USING (
        COALESCE(current_setting('app.platform_admin', TRUE), '') = 'on'
        OR partner_id = COALESCE(current_setting('app.partner_id', TRUE), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.platform_admin', TRUE), '') = 'on'
        OR partner_id = COALESCE(current_setting('app.partner_id', TRUE), '')
    );

DROP POLICY IF EXISTS tenant_scope ON partner_store.invitations;
CREATE POLICY tenant_scope ON partner_store.invitations
    USING (
        COALESCE(current_setting('app.platform_admin', TRUE), '') = 'on'
        OR partner_id = COALESCE(current_setting('app.partner_id', TRUE), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.platform_admin', TRUE), '') = 'on'
        OR partner_id = COALESCE(current_setting('app.partner_id', TRUE), '')
    );
"""


def canonical_json(value: Any) -> str:
    """Return a deterministic JSON representation used by migration checks."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _copy_dict(value: Any) -> Dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _copy_dict_list(value: Any) -> List[Dict[str, Any]]:
    return [copy.deepcopy(item) for item in value or [] if isinstance(item, dict)]


class PartnerPostgresStore:
    """Small pooled repository with forced tenant row-level security."""

    def __init__(
        self,
        database_url: str,
        *,
        min_pool_size: int = 0,
        max_pool_size: int = 4,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.database_url = str(database_url or "").strip()
        if not self.database_url:
            raise PartnerPostgresValidationError("PARTNER_DATABASE_URL absent")
        self.min_pool_size = max(0, int(min_pool_size))
        self.max_pool_size = max(1, int(max_pool_size))
        if self.min_pool_size > self.max_pool_size:
            self.min_pool_size = self.max_pool_size
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._pool: Any = None
        self._jsonb: Any = None
        self._pool_lock = threading.RLock()
        self._schema_lock = threading.RLock()
        self._schema_ready = False

    def _ensure_pool(self) -> Any:
        with self._pool_lock:
            if self._pool is not None:
                return self._pool
            try:
                from psycopg.types.json import Jsonb
                from psycopg_pool import ConnectionPool
            except Exception as exc:  # pragma: no cover - depends on deployment
                raise PartnerPostgresUnavailable(
                    "Le pilote PostgreSQL partenaire n'est pas installé."
                ) from exc
            try:
                pool = ConnectionPool(
                    conninfo=self.database_url,
                    min_size=self.min_pool_size,
                    max_size=self.max_pool_size,
                    timeout=self.timeout_seconds,
                    kwargs={"autocommit": False},
                    open=False,
                    name="gestionstagiaires-partners",
                )
                pool.open(wait=True, timeout=self.timeout_seconds)
            except Exception as exc:
                raise PartnerPostgresUnavailable(
                    "Connexion à PostgreSQL partenaires impossible."
                ) from exc
            self._pool = pool
            self._jsonb = Jsonb
            return pool

    def close(self) -> None:
        with self._pool_lock:
            pool, self._pool = self._pool, None
            self._schema_ready = False
        if pool is not None:
            try:
                pool.close()
            except Exception:
                pass

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            pool = self._ensure_pool()
            try:
                with pool.connection(timeout=self.timeout_seconds) as connection:
                    with connection.transaction():
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                                ("gestionstagiaires-partner-store-schema-v1",),
                            )
                            # Psycopg's extended protocol deliberately rejects
                            # multi-command prepared statements on some server
                            # versions. The schema contains only plain DDL, so
                            # execute each statement explicitly and portably.
                            for statement in SCHEMA_SQL.split(";"):
                                statement = statement.strip()
                                if statement:
                                    cursor.execute(statement)
                self._schema_ready = True
            except Exception as exc:
                raise PartnerPostgresUnavailable(
                    "Initialisation du schéma PostgreSQL partenaires impossible."
                ) from exc

    @contextmanager
    def _transaction(
        self,
        *,
        partner_id: str = "",
        platform_admin: bool = False,
    ) -> Iterator[Tuple[Any, Any]]:
        self.ensure_schema()
        pool = self._ensure_pool()
        try:
            with pool.connection(timeout=self.timeout_seconds) as connection:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT set_config('app.platform_admin', %s, TRUE)",
                            ("on" if platform_admin else "off",),
                        )
                        cursor.execute(
                            "SELECT set_config('app.partner_id', %s, TRUE)",
                            (str(partner_id or ""),),
                        )
                        yield connection, cursor
        except PartnerPostgresError:
            raise
        except Exception as exc:
            # Do not include the DSN or driver message: both can expose secrets.
            raise PartnerPostgresUnavailable(
                "Opération PostgreSQL partenaires indisponible."
            ) from exc

    @staticmethod
    def _validate_partner_id(partner_id: str) -> str:
        normalized = str(partner_id or "").strip()
        if not _PARTNER_ID_RE.fullmatch(normalized):
            raise PartnerPostgresValidationError("partner_id invalide")
        return normalized

    @staticmethod
    def _validated_bundle(bundle: Dict[str, Any], partner_id: str) -> Dict[str, Any]:
        if not isinstance(bundle, dict):
            raise PartnerPostgresValidationError("bundle partenaire invalide")
        partners = [
            item for item in bundle.get("partners", [])
            if isinstance(item, dict) and str(item.get("id") or "") == partner_id
        ]
        if len(partners) != 1:
            raise PartnerPostgresValidationError(
                "le bundle doit contenir exactement son partenaire"
            )

        users = []
        seen_emails = set()
        for item in bundle.get("users", []) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("partner_id") or "") != partner_id:
                raise PartnerPostgresValidationError(
                    "utilisateur rattaché à un autre partenaire"
                )
            user_id = str(item.get("id") or "").strip()
            email = str(item.get("email") or "").strip().lower()
            role = str(item.get("role") or "partner_admin").strip()
            if not user_id or not email or role not in _ALLOWED_ROLES:
                raise PartnerPostgresValidationError(
                    "utilisateur partenaire invalide"
                )
            if email in seen_emails:
                raise PartnerPostgresDuplicateEmail(
                    "adresse e-mail partenaire dupliquée"
                )
            seen_emails.add(email)
            safe_user = copy.deepcopy(item)
            safe_user["partner_id"] = partner_id
            safe_user["email"] = email
            safe_user["role"] = role
            users.append(safe_user)

        user_ids = {str(item.get("id") or "") for item in users}
        invitations = []
        for item in bundle.get("invitations", []) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("partner_id") or "") != partner_id:
                raise PartnerPostgresValidationError(
                    "invitation rattachée à un autre partenaire"
                )
            invitation_id = str(item.get("id") or "").strip()
            user_id = str(item.get("user_id") or "").strip()
            if not invitation_id or user_id not in user_ids:
                raise PartnerPostgresValidationError("invitation partenaire invalide")
            invitations.append(copy.deepcopy(item))

        validated = copy.deepcopy(bundle)
        validated["partners"] = [copy.deepcopy(partners[0])]
        validated["users"] = users
        validated["invitations"] = invitations
        return validated

    @staticmethod
    def _business_payload(bundle: Dict[str, Any]) -> Dict[str, Any]:
        payload = copy.deepcopy(bundle)
        payload.pop("partners", None)
        payload.pop("users", None)
        payload.pop("invitations", None)
        payload.pop("_partner_postgres_version", None)
        return payload

    def _load_bundle_cursor(
        self,
        cursor: Any,
        partner_id: str,
        *,
        for_update: bool = False,
    ) -> Optional[Tuple[Dict[str, Any], int]]:
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            "SELECT partner, payload, version FROM partner_store.tenants "
            "WHERE partner_id = %s" + suffix,
            (partner_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        partner, payload, version = row
        cursor.execute(
            "SELECT record FROM partner_store.users "
            "WHERE partner_id = %s ORDER BY id",
            (partner_id,),
        )
        users = [_copy_dict(item[0]) for item in cursor.fetchall()]
        cursor.execute(
            "SELECT record FROM partner_store.invitations "
            "WHERE partner_id = %s ORDER BY id",
            (partner_id,),
        )
        invitations = [_copy_dict(item[0]) for item in cursor.fetchall()]
        bundle = _copy_dict(payload)
        bundle["partners"] = [_copy_dict(partner)]
        bundle["users"] = users
        bundle["invitations"] = invitations
        return bundle, int(version or 0)

    def _write_bundle_cursor(
        self,
        cursor: Any,
        partner_id: str,
        bundle: Dict[str, Any],
        *,
        source_checksum: Optional[str] = None,
        create_only: bool = False,
    ) -> int:
        validated = self._validated_bundle(bundle, partner_id)
        partner = validated["partners"][0]
        payload = self._business_payload(validated)
        jsonb = self._jsonb

        if create_only:
            cursor.execute(
                "INSERT INTO partner_store.tenants "
                "(partner_id, partner, payload, version, source_checksum, imported_at) "
                "VALUES (%s, %s, %s, 1, %s, CASE WHEN %s IS NULL THEN NULL ELSE NOW() END) "
                "RETURNING version",
                (
                    partner_id,
                    jsonb(partner),
                    jsonb(payload),
                    source_checksum,
                    source_checksum,
                ),
            )
        else:
            cursor.execute(
                "INSERT INTO partner_store.tenants "
                "(partner_id, partner, payload, version, source_checksum, imported_at) "
                "VALUES (%s, %s, %s, 1, %s, CASE WHEN %s IS NULL THEN NULL ELSE NOW() END) "
                "ON CONFLICT (partner_id) DO UPDATE SET "
                "partner = EXCLUDED.partner, payload = EXCLUDED.payload, "
                "version = partner_store.tenants.version + 1, "
                "source_checksum = EXCLUDED.source_checksum, "
                "imported_at = CASE WHEN EXCLUDED.source_checksum IS NULL "
                "THEN partner_store.tenants.imported_at ELSE NOW() END, "
                "updated_at = NOW() RETURNING version",
                (
                    partner_id,
                    jsonb(partner),
                    jsonb(payload),
                    source_checksum,
                    source_checksum,
                ),
            )
        row = cursor.fetchone()
        version = int(row[0] if row else 1)

        cursor.execute(
            "DELETE FROM partner_store.invitations WHERE partner_id = %s",
            (partner_id,),
        )
        cursor.execute(
            "DELETE FROM partner_store.users WHERE partner_id = %s",
            (partner_id,),
        )
        for user in validated["users"]:
            try:
                cursor.execute(
                    "INSERT INTO partner_store.users "
                    "(id, partner_id, email_normalized, password_hash, role, active, record) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        str(user.get("id") or ""),
                        partner_id,
                        str(user.get("email") or "").strip().lower(),
                        str(user.get("password_hash") or ""),
                        str(user.get("role") or "partner_admin"),
                        bool(user.get("active", True)),
                        jsonb(user),
                    ),
                )
            except Exception as exc:
                if getattr(exc, "sqlstate", "") == "23505":
                    raise PartnerPostgresDuplicateEmail(
                        "adresse e-mail déjà utilisée par un partenaire"
                    ) from exc
                raise
        for invitation in validated["invitations"]:
            cursor.execute(
                "INSERT INTO partner_store.invitations "
                "(id, partner_id, user_id, token_hash, record) "
                "VALUES (%s, %s, %s, NULLIF(%s, ''), %s)",
                (
                    str(invitation.get("id") or ""),
                    partner_id,
                    str(invitation.get("user_id") or ""),
                    str(invitation.get("token_hash") or ""),
                    jsonb(invitation),
                ),
            )
        return version

    def load_bundle(self, partner_id: str) -> Tuple[Dict[str, Any], int]:
        partner_id = self._validate_partner_id(partner_id)
        with self._transaction(partner_id=partner_id) as (_connection, cursor):
            loaded = self._load_bundle_cursor(cursor, partner_id)
            if loaded is None:
                raise PartnerPostgresNotFound("partenaire PostgreSQL introuvable")
            return loaded

    def load_all_bundles(self) -> List[Tuple[Dict[str, Any], int]]:
        with self._transaction(platform_admin=True) as (_connection, cursor):
            cursor.execute(
                "SELECT partner_id FROM partner_store.tenants ORDER BY partner_id"
            )
            partner_ids = [str(row[0]) for row in cursor.fetchall()]
            bundles = []
            for partner_id in partner_ids:
                loaded = self._load_bundle_cursor(cursor, partner_id)
                if loaded is not None:
                    bundles.append(loaded)
            return bundles

    def load_auth_data(self) -> Dict[str, List[Dict[str, Any]]]:
        """Read indexed authentication data without tenant business payloads."""

        with self._transaction(platform_admin=True) as (_connection, cursor):
            cursor.execute(
                "SELECT partner FROM partner_store.tenants ORDER BY partner_id"
            )
            partners = [_copy_dict(row[0]) for row in cursor.fetchall()]
            cursor.execute("SELECT record FROM partner_store.users ORDER BY id")
            users = [_copy_dict(row[0]) for row in cursor.fetchall()]
            cursor.execute(
                "SELECT record FROM partner_store.invitations ORDER BY id"
            )
            invitations = [_copy_dict(row[0]) for row in cursor.fetchall()]
        return {
            "partners": partners,
            "users": users,
            "invitations": invitations,
        }

    def import_bundle(
        self,
        partner_id: str,
        bundle: Dict[str, Any],
        *,
        source_checksum: str,
    ) -> int:
        partner_id = self._validate_partner_id(partner_id)
        with self._transaction(platform_admin=True) as (_connection, cursor):
            return self._write_bundle_cursor(
                cursor,
                partner_id,
                bundle,
                source_checksum=str(source_checksum or ""),
            )

    def create_bundle(self, partner_id: str, bundle: Dict[str, Any]) -> int:
        partner_id = self._validate_partner_id(partner_id)
        with self._transaction(partner_id=partner_id) as (_connection, cursor):
            if self._load_bundle_cursor(cursor, partner_id, for_update=True):
                raise PartnerPostgresValidationError(
                    "ce partenaire existe déjà dans PostgreSQL"
                )
            return self._write_bundle_cursor(
                cursor, partner_id, bundle, create_only=True
            )

    def mutate_bundle(
        self,
        partner_id: str,
        mutator: Callable[[Dict[str, Any]], Dict[str, Any]],
        *,
        seed_bundle: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """Lock one tenant row and atomically apply a pure in-memory mutation."""

        partner_id = self._validate_partner_id(partner_id)
        with self._transaction(partner_id=partner_id) as (_connection, cursor):
            loaded = self._load_bundle_cursor(cursor, partner_id, for_update=True)
            if loaded is None:
                if seed_bundle is None:
                    raise PartnerPostgresNotFound(
                        "partenaire PostgreSQL introuvable"
                    )
                current = copy.deepcopy(seed_bundle)
                create_only = True
            else:
                current, _version = loaded
                create_only = False
                if expected_version is not None and int(expected_version) != int(_version):
                    raise PartnerPostgresWriteConflict(
                        "les données du partenaire ont été modifiées par une autre requête"
                    )
            updated = mutator(copy.deepcopy(current))
            if not isinstance(updated, dict):
                raise PartnerPostgresValidationError(
                    "la mutation partenaire doit retourner un dictionnaire"
                )
            version = self._write_bundle_cursor(
                cursor,
                partner_id,
                updated,
                create_only=create_only,
            )
            return copy.deepcopy(updated), version

    def delete_partner(self, partner_id: str) -> bool:
        partner_id = self._validate_partner_id(partner_id)
        with self._transaction(platform_admin=True) as (_connection, cursor):
            cursor.execute(
                "DELETE FROM partner_store.tenants WHERE partner_id = %s",
                (partner_id,),
            )
            return bool(cursor.rowcount)

    def stats(self) -> Dict[str, Any]:
        with self._transaction(platform_admin=True) as (_connection, cursor):
            cursor.execute("SELECT COUNT(*) FROM partner_store.tenants")
            partners = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM partner_store.users")
            users = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM partner_store.invitations")
            invitations = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT partner_id, version, source_checksum "
                "FROM partner_store.tenants ORDER BY partner_id"
            )
            tenant_rows = [
                {
                    "partner_id": str(row[0]),
                    "version": int(row[1]),
                    "source_checksum": str(row[2] or ""),
                }
                for row in cursor.fetchall()
            ]
        return {
            "partners": partners,
            "users": users,
            "invitations": invitations,
            "tenants": tenant_rows,
        }
