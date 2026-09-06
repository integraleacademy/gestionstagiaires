#!/usr/bin/env python3
"""Rebuild the JSON partner mirror from PostgreSQL for a controlled rollback.

The default command is a dry run. ``--apply`` creates a durable snapshot of
``data.json`` before replacing only external partner-owned records. Intégrale's
historical records and global integrations are never sourced from PostgreSQL.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as gestion_app  # noqa: E402


def _integrale_checksum(data):
    partner_id = gestion_app.INTEGRALE_PARTNER_ID
    scoped = gestion_app._filter_data_for_partner(data, partner_id)
    return hashlib.sha256(
        gestion_app._partner_canonical_json(scoped).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Mettre à jour le miroir JSON après création d’une sauvegarde.",
    )
    args = parser.parse_args()
    if not os.environ.get("PARTNER_DATABASE_URL"):
        print(json.dumps({"ok": False, "error": "PARTNER_DATABASE_URL absent"}))
        return 2

    canonical = gestion_app._load_valid_json_payload(gestion_app.DATA_FILE)
    if not isinstance(canonical, dict):
        print(json.dumps({"ok": False, "error": "data_json_unreadable"}))
        return 3
    before_integrale = _integrale_checksum(canonical)
    rebuilt = copy.deepcopy(canonical)
    partner_ids = []
    for bundle, _version in gestion_app._get_partner_postgres_store().load_all_bundles():
        partner = next(
            (item for item in bundle.get("partners", []) if isinstance(item, dict)),
            {},
        )
        partner_id = str(partner.get("id") or "")
        if not partner_id or partner_id == gestion_app.INTEGRALE_PARTNER_ID:
            continue
        gestion_app._overlay_partner_bundle(rebuilt, bundle, partner_id)
        partner_ids.append(partner_id)

    if _integrale_checksum(rebuilt) != before_integrale:
        print(json.dumps({"ok": False, "error": "integrale_data_changed"}))
        return 4

    output = {
        "ok": True,
        "dry_run": not args.apply,
        "partner_count": len(partner_ids),
        "partner_ids": sorted(partner_ids),
    }
    if args.apply:
        snapshot = gestion_app._force_backup_snapshot(
            gestion_app.DATA_FILE,
            reason="pre-partner-postgres-rollback",
        )
        if not snapshot:
            print(json.dumps({"ok": False, "error": "backup_failed"}))
            return 5
        gestion_app.save_data(rebuilt, force_global=True)
        output["backup"] = os.path.basename(snapshot)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
