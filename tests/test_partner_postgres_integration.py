"""Real PostgreSQL regressions, using only an explicitly selected local test DB."""

import copy
import os
import unittest
import uuid
from urllib.parse import urlparse

from partner_postgres import (
    PartnerPostgresStore,
    PartnerPostgresDuplicateEmail,
    PartnerPostgresUnavailable,
    PartnerPostgresWriteConflict,
)


@unittest.skipUnless(os.environ.get("TEST_PARTNER_POSTGRES_URL"), "local test DB not configured")
class PartnerPostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        dsn = os.environ["TEST_PARTNER_POSTGRES_URL"]
        parsed = urlparse(dsn)
        if parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.path != "/partners_test":
            self.fail("Tests must use the disposable local partners_test database")
        self.store = PartnerPostgresStore(dsn)
        self.partner_a = "test-" + uuid.uuid4().hex
        self.partner_b = "test-" + uuid.uuid4().hex
        self.addCleanup(self.store.close)
        self.addCleanup(self.store.delete_partner, self.partner_a)
        self.addCleanup(self.store.delete_partner, self.partner_b)

    def bundle(self, partner_id):
        return {
            "partners": [{"id": partner_id, "name": "Test only", "status": "active"}],
            "users": [{
                "id": "user-" + partner_id, "partner_id": partner_id,
                "email": partner_id + "@example.invalid", "password_hash": "",
                "role": "partner_admin", "active": True,
            }],
            "invitations": [{
                "id": "invite-" + partner_id, "partner_id": partner_id,
                "user_id": "user-" + partner_id, "token_hash": "token-" + partner_id,
            }],
            "sessions": [{"id": "session-" + partner_id, "partner_id": partner_id}],
        }

    def test_import_readback_and_update_with_null_and_text_checksums(self):
        bundle = self.bundle(self.partner_a)
        self.store.import_bundle(self.partner_a, bundle, source_checksum="abc123")
        loaded, version = self.store.load_bundle(self.partner_a)
        self.assertEqual(loaded, bundle)
        updated = copy.deepcopy(bundle)
        updated["partners"][0]["name"] = "Updated"
        actual, next_version = self.store.mutate_bundle(
            self.partner_a, lambda _current: updated, expected_version=version,
        )
        self.assertEqual(actual, updated)
        self.assertEqual(next_version, version + 1)
        with self.store._transaction(partner_id=self.partner_a) as (_conn, cursor):
            cursor.execute(
                "SELECT source_checksum, imported_at FROM partner_store.tenants WHERE partner_id=%s",
                (self.partner_a,),
            )
            checksum, imported_at = cursor.fetchone()
        self.assertIsNone(checksum)
        self.assertIsNotNone(imported_at)

    def test_new_account_creation_without_import_checksum(self):
        bundle = self.bundle(self.partner_a)
        result, version = self.store.mutate_bundle(
            self.partner_a, lambda _current: bundle,
            seed_bundle={"partners": [], "users": [], "invitations": []},
        )
        self.assertEqual(result, bundle)
        self.assertEqual(version, 1)
        self.assertEqual(self.store.load_bundle(self.partner_a)[0], bundle)

    def test_stale_write_is_rejected_and_other_tenant_unchanged(self):
        for partner_id in (self.partner_a, self.partner_b):
            self.store.import_bundle(partner_id, self.bundle(partner_id), source_checksum="initial")
        before_b = self.store.load_bundle(self.partner_b)
        _bundle, version = self.store.load_bundle(self.partner_a)
        self.store.mutate_bundle(self.partner_a, lambda current: current, expected_version=version)
        with self.assertRaises(PartnerPostgresWriteConflict):
            self.store.mutate_bundle(self.partner_a, lambda current: current, expected_version=version)
        self.assertEqual(self.store.load_bundle(self.partner_b), before_b)

    def test_duplicate_email_rolls_back_whole_tenant_transaction(self):
        first = self.bundle(self.partner_a)
        self.store.import_bundle(self.partner_a, first, source_checksum="initial")
        second = self.bundle(self.partner_b)
        second["users"][0]["email"] = first["users"][0]["email"]
        with self.assertRaises(PartnerPostgresDuplicateEmail):
            self.store.import_bundle(self.partner_b, second, source_checksum="duplicate")
        with self.store._transaction(platform_admin=True) as (_conn, cursor):
            cursor.execute("SELECT count(*) FROM partner_store.tenants WHERE partner_id=%s", (self.partner_b,))
            self.assertEqual(cursor.fetchone()[0], 0)
        self.assertEqual(self.store.load_bundle(self.partner_a)[0], first)

    def test_forced_rls_blocks_cross_tenant_reads_and_writes(self):
        for partner_id in (self.partner_a, self.partner_b):
            self.store.import_bundle(partner_id, self.bundle(partner_id), source_checksum="initial")
        with self.store._transaction(partner_id=self.partner_a) as (_conn, cursor):
            cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
            self.assertEqual(cursor.fetchone(), (False, False), "RLS test must run without bypass rights")
            for table in ("tenants", "users", "invitations"):
                cursor.execute(f"SELECT DISTINCT partner_id FROM partner_store.{table}")
                self.assertEqual(cursor.fetchall(), [(self.partner_a,)])
                cursor.execute(f"DELETE FROM partner_store.{table} WHERE partner_id=%s", (self.partner_b,))
                self.assertEqual(cursor.rowcount, 0)
        with self.assertRaises(PartnerPostgresUnavailable):
            with self.store._transaction(partner_id=self.partner_a) as (_conn, cursor):
                cursor.execute(
                    "INSERT INTO partner_store.tenants (partner_id, partner) VALUES (%s, '{}'::jsonb)",
                    ("forbidden-" + uuid.uuid4().hex,),
                )
        self.assertEqual(self.store.load_bundle(self.partner_b)[0], self.bundle(self.partner_b))

    def test_auth_index_and_pool_context_do_not_expose_business_payload(self):
        bundle = self.bundle(self.partner_a)
        self.store.import_bundle(self.partner_a, bundle, source_checksum="initial")
        auth = self.store.load_auth_data()
        self.assertEqual(set(auth), {"partners", "users", "invitations"})
        self.assertTrue(any(row["id"] == "user-" + self.partner_a for row in auth["users"]))
        with self.store._transaction() as (_conn, cursor):
            cursor.execute("SELECT count(*) FROM partner_store.tenants")
            self.assertEqual(cursor.fetchone()[0], 0)
        stats = self.store.stats()
        self.assertGreaterEqual(stats["partners"], 1)
        self.assertGreaterEqual(stats["users"], 1)


if __name__ == "__main__":
    unittest.main()
