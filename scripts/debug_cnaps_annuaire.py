#!/usr/bin/env python3
"""Manual CNAPS public annuaire diagnostic.

Usage:
    python scripts/debug_cnaps_annuaire.py --nom LARDJANE --nub 1000731
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as gestion_app  # noqa: E402


def describe_structure(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: describe_structure(value[key]) for key in list(value.keys())[:20]}
    if isinstance(value, list):
        return [describe_structure(value[0])] if value else []
    return type(value).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug CNAPS public annuaire lookup")
    parser.add_argument("--nom", required=True)
    parser.add_argument("--nub", required=True)
    args = parser.parse_args()

    endpoint = gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT
    method = "POST"
    payload = {
        "nom": " ".join(args.nom.strip().split()).upper(),
        "nub": gestion_app._normalize_cnaps_nub(args.nub),
        "numeroBeneficiaireUnique": gestion_app._normalize_cnaps_nub(args.nub),
        "typeRecherche": "AGENT",
        "page": 0,
        "size": 100,
        "limit": 100,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": gestion_app.CNAPS_PUBLIC_ANNUAIRE_PAGE_URL,
        "Origin": "https://espace-consultation.cnaps.interieur.gouv.fr",
    }
    print(f"method: {method}")
    print(f"url: {endpoint}")
    print(f"body: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")
    print(f"headers: {json.dumps(headers, ensure_ascii=False, sort_keys=True)}")
    result = gestion_app.fetch_cnaps_public_annuaire(args.nom, args.nub)
    print(f"http_status: {result.get('http_status') or ('200' if result.get('check_status') == 'success' else 'unknown')}")
    print("content_type: see CNAPS outbound content_type log")
    print(f"response_structure: {json.dumps(describe_structure(result), ensure_ascii=False)}")
    print(f"results_count: {len(result.get('results') or [])}")
    print(f"activities: {json.dumps([r.get('activite') for r in (result.get('results') or [])], ensure_ascii=False)}")
    print(f"active_titles: {json.dumps(result.get('cnaps_active_titles') or [], ensure_ascii=False)}")
    if result.get("check_status") != "success":
        print(f"error: {result.get('error')}", file=sys.stderr)
        return 2
    expected = ["AP SH ACTIF", "CP SH ACTIF"]
    if payload["nom"] == "LARDJANE" and payload["nub"] == "1000731" and result.get("cnaps_active_titles") != expected:
        print(f"unexpected LARDJANE titles: expected {expected!r}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
