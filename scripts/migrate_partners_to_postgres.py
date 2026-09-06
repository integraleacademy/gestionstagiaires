#!/usr/bin/env python3
"""Backfill and verify the external-partner PostgreSQL store.

Examples:
    python scripts/migrate_partners_to_postgres.py --verify
    python scripts/migrate_partners_to_postgres.py --apply --verify

The command never deletes JSON data. ``--apply`` first creates a durable
``data.json`` snapshot, imports external tenants transactionally one by one,
then compares deterministic checksums after reading them back from PostgreSQL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as gestion_app  # noqa: E402


def _source_bundles():
    canonical = gestion_app._load_valid_json_payload(gestion_app.DATA_FILE)
    if not isinstance(canonical, dict):
        raise RuntimeError("data.json est absent ou illisible")
    gestion_app._ensure_multi_partner_payload(canonical)
    bundles = {}
    for partner in canonical.get("partners", []):
        if not isinstance(partner, dict):
            continue
        partner_id = str(partner.get("id") or "")
        if not partner_id or partner_id == gestion_app.INTEGRALE_PARTNER_ID:
            continue
        bundle = gestion_app._partner_bundle_from_canonical(canonical, partner_id)
        bundles[partner_id] = {
            "bundle": bundle,
            "checksum": gestion_app._partner_bundle_checksum(bundle),
        }
    return canonical, bundles


def _verification_report(source_bundles):
    store = gestion_app._get_partner_postgres_store()
    database_bundles = {}
    for bundle, version in store.load_all_bundles():
        partner = next(
            (item for item in bundle.get("partners", []) if isinstance(item, dict)),
            {},
        )
        partner_id = str(partner.get("id") or "")
        if partner_id:
            database_bundles[partner_id] = {
                "checksum": gestion_app._partner_bundle_checksum(bundle),
                "version": int(version),
            }

    rows = []
    all_match = True
    for partner_id, source in sorted(source_bundles.items()):
        target = database_bundles.get(partner_id)
        matches = bool(target and target["checksum"] == source["checksum"])
        all_match = all_match and matches
        rows.append({
            "partner_id": partner_id,
            "present": bool(target),
            "checksum_match": matches,
            "version": int((target or {}).get("version") or 0),
        })
    unexpected = sorted(set(database_bundles) - set(source_bundles))
    if unexpected:
        all_match = False
    return {
        "ok": all_match,
        "source_partner_count": len(source_bundles),
        "database_partner_count": len(database_bundles),
        "partners": rows,
        "unexpected_database_partner_ids": unexpected,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Créer une sauvegarde et importer les partenaires externes.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Relire PostgreSQL et comparer tous les checksums.",
    )
    args = parser.parse_args()

    if not os.environ.get("PARTNER_DATABASE_URL"):
        print(json.dumps({"ok": False, "error": "PARTNER_DATABASE_URL absent"}))
        return 2

    canonical, bundles = _source_bundles()
    output = {
        "ok": True,
        "dry_run": not args.apply,
        "source_partner_count": len(bundles),
        "source_partner_ids": sorted(bundles),
    }
    if args.apply:
        snapshot = gestion_app._force_backup_snapshot(
            gestion_app.DATA_FILE,
            reason="pre-partner-postgres-cli",
        )
        if not snapshot:
            print(json.dumps({"ok": False, "error": "backup_failed"}))
            return 3
        output["backup"] = os.path.basename(snapshot)
        import_report = gestion_app._sync_partner_postgres_from_canonical(
            canonical,
            strict=True,
        )
        output["import"] = import_report
        output["ok"] = bool(import_report.get("ok"))

    if args.verify or args.apply:
        verification = _verification_report(bundles)
        output["verification"] = verification
        output["ok"] = bool(output["ok"] and verification.get("ok"))

    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if output["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
