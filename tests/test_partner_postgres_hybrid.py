import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gestion_app
from partner_postgres import SCHEMA_SQL, PartnerPostgresWriteConflict


class InMemoryPartnerStore:
    def __init__(self, bundles=None):
        self.bundles = copy.deepcopy(bundles or {})
        self.versions = {partner_id: 1 for partner_id in self.bundles}
        self.source_checksums = {}
        self.load_calls = []

    def close(self):
        return None

    def load_bundle(self, partner_id):
        self.load_calls.append(partner_id)
        if partner_id not in self.bundles:
            raise gestion_app.PartnerPostgresNotFound("missing")
        return copy.deepcopy(self.bundles[partner_id]), self.versions[partner_id]

    def load_all_bundles(self):
        return [
            (copy.deepcopy(self.bundles[key]), self.versions[key])
            for key in sorted(self.bundles)
        ]

    def load_auth_data(self):
        partners, users, invitations = [], [], []
        for bundle in self.bundles.values():
            partners.extend(copy.deepcopy(bundle.get("partners", [])))
            users.extend(copy.deepcopy(bundle.get("users", [])))
            invitations.extend(copy.deepcopy(bundle.get("invitations", [])))
        return {"partners": partners, "users": users, "invitations": invitations}

    def mutate_bundle(self, partner_id, mutator, *, seed_bundle=None, expected_version=None):
        if partner_id not in self.bundles:
            if seed_bundle is None:
                raise gestion_app.PartnerPostgresNotFound("missing")
            current = copy.deepcopy(seed_bundle)
            version = 0
        else:
            current = copy.deepcopy(self.bundles[partner_id])
            version = self.versions[partner_id]
        if expected_version is not None and expected_version != version:
            raise PartnerPostgresWriteConflict("stale")
        updated = mutator(current)
        self.bundles[partner_id] = copy.deepcopy(updated)
        self.versions[partner_id] = version + 1
        self.source_checksums[partner_id] = ""
        return copy.deepcopy(updated), self.versions[partner_id]

    def import_bundle(self, partner_id, bundle, *, source_checksum):
        self.bundles[partner_id] = copy.deepcopy(bundle)
        self.versions[partner_id] = self.versions.get(partner_id, 0) + 1
        self.source_checksums[partner_id] = source_checksum
        return self.versions[partner_id]

    def stats(self):
        return {
            "partners": len(self.bundles),
            "users": sum(len(bundle.get("users", [])) for bundle in self.bundles.values()),
            "invitations": sum(len(bundle.get("invitations", [])) for bundle in self.bundles.values()),
            "tenants": [
                {
                    "partner_id": partner_id,
                    "version": self.versions[partner_id],
                    "source_checksum": self.source_checksums.get(partner_id, ""),
                }
                for partner_id in sorted(self.bundles)
            ],
        }

    def delete_partner(self, partner_id):
        existed = partner_id in self.bundles
        self.bundles.pop(partner_id, None)
        self.versions.pop(partner_id, None)
        self.source_checksums.pop(partner_id, None)
        return existed


class PartnerPostgresMigrationDiagnosticsTests(unittest.TestCase):
    def test_duplicate_email_diagnostics_are_safe_and_actionable(self):
        email = "Duplicate@Example.com"
        bundle = {
            "users": [
                {
                    "id": "user-old",
                    "partner_id": "partner-test",
                    "email": email,
                    "role": "partner_admin",
                    "active": True,
                    "password_hash": "",
                    "created_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": "user-live",
                    "partner_id": "partner-test",
                    "email": email.lower(),
                    "role": "partner_admin",
                    "active": True,
                    "password_hash": "secret-hash",
                    "last_login_at": "2026-09-01T00:00:00Z",
                },
            ],
            "invitations": [{"id": "invite-old", "user_id": "user-old"}],
        }

        diagnostics = gestion_app._partner_duplicate_email_diagnostics(bundle)
        rendered = json.dumps(diagnostics, sort_keys=True)

        self.assertEqual(len(diagnostics), 1)
        self.assertNotIn(email.lower(), rendered.lower())
        self.assertEqual(
            [item["id"] for item in diagnostics[0]["records"]],
            ["user-old", "user-live"],
        )
        self.assertEqual(diagnostics[0]["records"][0]["invitation_count"], 1)
        self.assertFalse(diagnostics[0]["records"][0]["has_password_hash"])
        self.assertTrue(diagnostics[0]["records"][1]["has_password_hash"])
        self.assertIn("password_hash", diagnostics[0]["differing_fields"])


class UnavailablePartnerStore:
    def stats(self):
        raise gestion_app.PartnerPostgresUnavailable("unavailable")

    def load_auth_data(self):
        raise gestion_app.PartnerPostgresUnavailable("unavailable")

    def load_bundle(self, _partner_id):
        raise gestion_app.PartnerPostgresUnavailable("unavailable")


class PartnerPostgresHybridTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.originals = {
            "DATA_FILE": gestion_app.DATA_FILE,
            "BACKUP_DIR": gestion_app.BACKUP_DIR,
            "PERSIST_DIR": gestion_app.PERSIST_DIR,
            "UPLOADS_DIR": gestion_app.UPLOADS_DIR,
            "store_override": gestion_app._partner_postgres_store_override,
            "secret_key": gestion_app.app.secret_key,
        }
        self.original_env = {
            key: os.environ.get(key)
            for key in (
                "PARTNER_POSTGRES_MODE",
                "PARTNER_DATABASE_URL",
                "PARTNER_POSTGRES_AUTO_MIGRATE",
                "PARTNER_POSTGRES_REPAIR_EXACT_USER_DUPLICATES",
                "PARTNER_POSTGRES_VERIFY_INITIAL_CUTOVER",
            )
        }
        gestion_app.PERSIST_DIR = self.temp_dir.name
        gestion_app.DATA_FILE = os.path.join(self.temp_dir.name, "data.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        gestion_app.UPLOADS_DIR = os.path.join(self.temp_dir.name, "uploads")
        os.makedirs(gestion_app.BACKUP_DIR, exist_ok=True)
        os.makedirs(gestion_app.UPLOADS_DIR, exist_ok=True)
        gestion_app.app.secret_key = "partner-postgres-test"
        self.partner_a = "partner-a-uuid"
        self.partner_b = "partner-b-uuid"
        payload = {
            "partners": [
                {"id": gestion_app.INTEGRALE_PARTNER_ID, "name": "Intégrale", "status": "active"},
                {"id": self.partner_a, "name": "Partenaire A", "status": "active", "internal_notes": "secret-a"},
                {"id": self.partner_b, "name": "Partenaire B", "status": "active", "internal_notes": "secret-b"},
            ],
            "users": [
                {
                    "id": "user-a",
                    "partner_id": self.partner_a,
                    "email": "a-postgres@example.com",
                    "role": "partner_admin",
                    "active": True,
                    "password_hash": gestion_app._hash_password("Password1234"),
                },
                {
                    "id": "user-b",
                    "partner_id": self.partner_b,
                    "email": "b-postgres@example.com",
                    "role": "partner_admin",
                    "active": True,
                    "password_hash": gestion_app._hash_password("Password1234"),
                },
            ],
            "invitations": [],
            "sessions": [
                {
                    "id": "session-a",
                    "partner_id": self.partner_a,
                    "name": "Session A",
                    "trainees": [{"id": "trainee-a", "partner_id": self.partner_a}],
                },
                {
                    "id": "session-b",
                    "partner_id": self.partner_b,
                    "name": "Session B",
                    "trainees": [{"id": "trainee-b", "partner_id": self.partner_b}],
                },
            ],
            "activity_logs": [],
        }
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.environ["PARTNER_POSTGRES_MODE"] = "off"
        canonical = gestion_app.load_data(run_background_tasks=False)
        bundles = {
            self.partner_a: gestion_app._partner_bundle_from_canonical(canonical, self.partner_a),
            self.partner_b: gestion_app._partner_bundle_from_canonical(canonical, self.partner_b),
        }
        self.store = InMemoryPartnerStore(bundles)
        gestion_app._partner_postgres_store_override = self.store
        os.environ["PARTNER_DATABASE_URL"] = "postgresql://test.invalid/partners"
        os.environ["PARTNER_POSTGRES_MODE"] = "active"
        self.client = gestion_app.app.test_client()

    def tearDown(self):
        gestion_app._partner_postgres_store_override = self.originals["store_override"]
        gestion_app.DATA_FILE = self.originals["DATA_FILE"]
        gestion_app.BACKUP_DIR = self.originals["BACKUP_DIR"]
        gestion_app.PERSIST_DIR = self.originals["PERSIST_DIR"]
        gestion_app.UPLOADS_DIR = self.originals["UPLOADS_DIR"]
        gestion_app.app.secret_key = self.originals["secret_key"]
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp_dir.cleanup()

    def _partner_session(self, partner_id=None):
        with self.client.session_transaction() as flask_session:
            flask_session.clear()
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "partner_admin"
            flask_session["partner_id"] = partner_id or self.partner_a
            flask_session["admin_username"] = "a-postgres@example.com"

    def test_partner_read_uses_only_its_postgres_row(self):
        before = Path(gestion_app.DATA_FILE).read_bytes()
        with gestion_app.app.test_request_context("/admin/sessions"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            with mock.patch.object(
                gestion_app,
                "_load_valid_json_payload",
                side_effect=AssertionError("external tenant must not load data.json"),
            ):
                data = gestion_app.load_data(run_background_tasks=False)
                self.assertEqual(getattr(gestion_app.g, "load_data_disk_read_count", 0), 0)
                self.assertEqual(gestion_app.g.partner_postgres_read_count, 1)

        self.assertEqual([item["id"] for item in data["partners"]], [self.partner_a])
        self.assertEqual([item["id"] for item in data["sessions"]], ["session-a"])
        self.assertNotIn("password_hash", data["users"][0])
        self.assertNotIn("internal_notes", data["partners"][0])
        self.assertEqual(Path(gestion_app.DATA_FILE).read_bytes(), before)

    def test_partner_write_updates_only_its_postgres_row(self):
        before_json = Path(gestion_app.DATA_FILE).read_bytes()
        before_b = copy.deepcopy(self.store.bundles[self.partner_b])
        with gestion_app.app.test_request_context("/admin/sessions", method="POST"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            data = gestion_app.load_data(run_background_tasks=False)
            data["sessions"][0]["name"] = "Session A PostgreSQL"
            gestion_app.save_data(data)

        self.assertEqual(
            self.store.bundles[self.partner_a]["sessions"][0]["name"],
            "Session A PostgreSQL",
        )
        self.assertEqual(self.store.bundles[self.partner_b], before_b)
        self.assertEqual(Path(gestion_app.DATA_FILE).read_bytes(), before_json)

    def test_stale_partner_write_is_rejected_instead_of_overwriting(self):
        with gestion_app.app.test_request_context("/admin/sessions", method="POST"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            stale = gestion_app.load_data(run_background_tasks=False)
            self.store.versions[self.partner_a] += 1
            stale["sessions"][0]["name"] = "Stale overwrite"
            with self.assertRaises(PartnerPostgresWriteConflict):
                gestion_app.save_data(stale)
        self.assertNotEqual(
            self.store.bundles[self.partner_a]["sessions"][0]["name"],
            "Stale overwrite",
        )

    def test_partner_login_reads_auth_index_and_records_login_in_postgres(self):
        before_json = Path(gestion_app.DATA_FILE).read_bytes()
        response = self.client.post(
            "/admin/login",
            data={
                "username": "a-postgres@example.com",
                "password": "Password1234",
                "next": "/admin/sessions",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/sessions")
        user = self.store.bundles[self.partner_a]["users"][0]
        self.assertTrue(user.get("last_login_at"))
        self.assertTrue(any(
            item.get("action") == "login"
            for item in self.store.bundles[self.partner_a].get("activity_logs", [])
        ))
        self.assertEqual(Path(gestion_app.DATA_FILE).read_bytes(), before_json)

    def test_create_activate_and_login_partner_stays_entirely_in_postgres(self):
        with self.client.session_transaction() as flask_session:
            flask_session.clear()
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"
            flask_session["platform_role"] = "super_admin"
            flask_session["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
        before_json = Path(gestion_app.DATA_FILE).read_bytes()
        with mock.patch.object(
            gestion_app,
            "_send_partner_invitation_email",
            return_value={"ok": True, "status_code": 201, "message_id": "msg-test"},
        ):
            created = self.client.post(
                "/admin/partners/new",
                data={
                    "name": "Nouveau partenaire PostgreSQL",
                    "email": "new-postgres@example.com",
                    "status": "trial",
                    "max_users": "5",
                },
                follow_redirects=False,
            )
        self.assertEqual(created.status_code, 302)
        new_partner_ids = set(self.store.bundles) - {self.partner_a, self.partner_b}
        self.assertEqual(len(new_partner_ids), 1)
        new_partner_id = new_partner_ids.pop()
        invitation = self.store.bundles[new_partner_id]["invitations"][0]
        raw_token = gestion_app._decrypt_invitation_token(invitation["token_encrypted"])
        self.assertTrue(raw_token)

        activated = self.client.post(
            "/activate-account",
            data={
                "token": raw_token,
                "password": "Password5678",
                "confirm": "Password5678",
            },
            follow_redirects=False,
        )
        self.assertEqual(activated.status_code, 302)
        self.assertIn("activated=1", activated.headers["Location"])
        user = self.store.bundles[new_partner_id]["users"][0]
        self.assertTrue(user["password_hash"])
        self.assertTrue(self.store.bundles[new_partner_id]["invitations"][0]["used_at"])

        logged_in = self.client.post(
            "/admin/login",
            data={
                "username": "new-postgres@example.com",
                "password": "Password5678",
                "next": "/admin/sessions",
            },
            follow_redirects=False,
        )
        self.assertEqual(logged_in.status_code, 302)
        self.assertEqual(logged_in.headers["Location"], "/admin/sessions")
        self.assertEqual(Path(gestion_app.DATA_FILE).read_bytes(), before_json)

    def test_public_trainee_save_updates_changed_postgres_tenant_only(self):
        before_b = copy.deepcopy(self.store.bundles[self.partner_b])
        with gestion_app.app.test_request_context("/espace/public-token", method="POST"):
            data = gestion_app.load_data(run_background_tasks=False)
            session_a = next(item for item in data["sessions"] if item["id"] == "session-a")
            session_a["trainees"][0]["phone"] = "0601020304"
            gestion_app.save_data(data)

        trainee = self.store.bundles[self.partner_a]["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["phone"], "0601020304")
        self.assertEqual(self.store.bundles[self.partner_b], before_b)

    def test_public_atomic_mutation_is_forwarded_to_postgres(self):
        with gestion_app.app.test_request_context("/public/callback", method="POST"):
            def mark_received(data):
                target = next(item for item in data["sessions"] if item["id"] == "session-b")
                target["public_callback_received"] = True
                return {"ok": True}

            result = gestion_app._atomic_update_data(mark_received)

        self.assertTrue(result["ok"])
        self.assertTrue(
            self.store.bundles[self.partner_b]["sessions"][0]["public_callback_received"]
        )

    def test_super_admin_assistance_reads_only_selected_postgres_tenant(self):
        with gestion_app.app.test_request_context("/admin/sessions"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "admin"
            gestion_app.session["platform_role"] = "super_admin"
            gestion_app.session["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
            gestion_app.session["assist_partner_id"] = self.partner_b
            data = gestion_app.load_data(run_background_tasks=False)
        self.assertEqual([item["id"] for item in data["partners"]], [self.partner_b])
        self.assertEqual([item["id"] for item in data["sessions"]], ["session-b"])

    def test_shadow_import_round_trip_matches_checksums(self):
        os.environ["PARTNER_POSTGRES_MODE"] = "shadow"
        self.store = InMemoryPartnerStore()
        gestion_app._partner_postgres_store_override = self.store
        canonical = gestion_app._load_valid_json_payload(gestion_app.DATA_FILE)
        report = gestion_app._sync_partner_postgres_from_canonical(canonical, strict=True)
        self.assertTrue(report["ok"])
        self.assertEqual(set(report["imported"]), {self.partner_a, self.partner_b})
        self.assertNotIn(gestion_app.INTEGRALE_PARTNER_ID, self.store.bundles)
        self.assertEqual(report["stats"]["partners"], 2)
        self.assertEqual(report["stats"]["users"], 2)
        self.assertEqual(report["stats"]["checksums_verified"], 2)

    def test_guarded_shadow_repair_keeps_one_exact_user_and_its_invitation(self):
        canonical = gestion_app._load_valid_json_payload(gestion_app.DATA_FILE)
        target_user = next(
            item for item in canonical["users"] if item["id"] == "user-a"
        )
        canonical["users"] = [
            item for item in canonical["users"] if item["id"] != "user-a"
        ] + [copy.deepcopy(target_user) for _index in range(8)]
        canonical["invitations"] = [{
            "id": "invite-a",
            "partner_id": self.partner_a,
            "user_id": "user-a",
            "token_hash": "preserved-token-hash",
        }]
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as handle:
            json.dump(canonical, handle)

        email_hash = gestion_app.hashlib.sha256(
            target_user["email"].lower().encode("utf-8")
        ).hexdigest()[:16]
        os.environ["PARTNER_POSTGRES_MODE"] = "shadow"
        os.environ["PARTNER_POSTGRES_AUTO_MIGRATE"] = "true"
        os.environ["PARTNER_POSTGRES_REPAIR_EXACT_USER_DUPLICATES"] = (
            f"{self.partner_a}:user-a:{email_hash}:8"
        )
        self.store = InMemoryPartnerStore()
        gestion_app._partner_postgres_store_override = self.store
        original_bootstrap_done = gestion_app._partner_postgres_bootstrap_done
        gestion_app._partner_postgres_bootstrap_done = False
        try:
            report = gestion_app._bootstrap_partner_postgres_shadow()
        finally:
            gestion_app._partner_postgres_bootstrap_done = original_bootstrap_done

        persisted = gestion_app._load_valid_json_payload(gestion_app.DATA_FILE)
        repaired_users = [
            item for item in persisted["users"] if item.get("id") == "user-a"
        ]
        self.assertEqual(repaired_users, [target_user])
        self.assertEqual(persisted["invitations"][0]["token_hash"], "preserved-token-hash")
        self.assertEqual(report["repair"]["removed"], 7)
        self.assertEqual(len(self.store.bundles[self.partner_a]["users"]), 1)
        self.assertEqual(len(self.store.bundles[self.partner_a]["invitations"]), 1)
        self.assertTrue(any(Path(gestion_app.BACKUP_DIR).iterdir()))

    def test_guarded_shadow_repair_refuses_non_identical_users(self):
        canonical = gestion_app._load_valid_json_payload(gestion_app.DATA_FILE)
        target_user = next(
            item for item in canonical["users"] if item["id"] == "user-a"
        )
        changed_user = copy.deepcopy(target_user)
        changed_user["active"] = False
        canonical["users"].append(changed_user)
        before = copy.deepcopy(canonical)

        email_hash = gestion_app.hashlib.sha256(
            target_user["email"].lower().encode("utf-8")
        ).hexdigest()[:16]
        with self.assertRaises(gestion_app.PartnerPostgresValidationError):
            gestion_app._repair_exact_partner_user_duplicates(
                canonical,
                (self.partner_a, "user-a", email_hash, 2),
            )
        self.assertEqual(canonical, before)

    def test_schema_forces_row_level_security_on_every_partner_table(self):
        self.assertIn("ALTER TABLE partner_store.tenants FORCE ROW LEVEL SECURITY", SCHEMA_SQL)
        self.assertIn("ALTER TABLE partner_store.users FORCE ROW LEVEL SECURITY", SCHEMA_SQL)
        self.assertIn("ALTER TABLE partner_store.invitations FORCE ROW LEVEL SECURITY", SCHEMA_SQL)
        self.assertEqual(SCHEMA_SQL.count("CREATE POLICY tenant_scope"), 3)

    def test_initial_cutover_verifies_every_partner_without_writing(self):
        os.environ["PARTNER_POSTGRES_VERIFY_INITIAL_CUTOVER"] = "true"
        before_json = Path(gestion_app.DATA_FILE).read_bytes()
        before_db = copy.deepcopy(self.store.bundles)
        with mock.patch.object(self.store, "import_bundle", side_effect=AssertionError("read-only gate")):
            report = gestion_app._verify_partner_postgres_initial_cutover()
        self.assertEqual(report, {"ok": True, "partners_verified": 2})
        self.assertEqual(Path(gestion_app.DATA_FILE).read_bytes(), before_json)
        self.assertEqual(self.store.bundles, before_db)

    def test_initial_cutover_refuses_a_stale_mirror(self):
        os.environ["PARTNER_POSTGRES_VERIFY_INITIAL_CUTOVER"] = "true"
        self.store.bundles[self.partner_a]["users"][0]["active"] = False
        with self.assertRaises(gestion_app.PartnerPostgresValidationError):
            gestion_app._verify_partner_postgres_initial_cutover()

    def test_initial_cutover_disabled_after_first_activation(self):
        os.environ["PARTNER_POSTGRES_VERIFY_INITIAL_CUTOVER"] = "false"
        with mock.patch.object(gestion_app, "_load_valid_json_payload", side_effect=AssertionError("no JSON")):
            report = gestion_app._verify_partner_postgres_initial_cutover()
        self.assertEqual(report["skipped"], "initial_cutover_check_disabled")

    def test_shadow_database_outage_never_interrupts_json_save(self):
        os.environ["PARTNER_POSTGRES_MODE"] = "shadow"
        gestion_app._partner_postgres_store_override = UnavailablePartnerStore()
        data = gestion_app._load_valid_json_payload(gestion_app.DATA_FILE)
        data["shadow_outage_write"] = "preserved"
        gestion_app.save_data(data)
        persisted = gestion_app._load_valid_json_payload(gestion_app.DATA_FILE)
        self.assertEqual(persisted["shadow_outage_write"], "preserved")

    def test_active_database_outage_fails_closed_for_partner(self):
        gestion_app._partner_postgres_store_override = UnavailablePartnerStore()
        self._partner_session()
        response = self.client.get("/admin/sessions", follow_redirects=False)
        self.assertEqual(response.status_code, 503)
        self.assertIn("temporairement indisponible", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
