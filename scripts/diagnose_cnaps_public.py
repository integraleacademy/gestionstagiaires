#!/usr/bin/env python3
"""Diagnostic léger pour l'annuaire public CNAPS (sans navigateur complet)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gestion_app


def main() -> int:
    nom = sys.argv[1] if len(sys.argv) > 1 else "LARDJANE"
    nub = sys.argv[2] if len(sys.argv) > 2 else "1000731"
    print(f"method=POST")
    print(f"url={gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT}")
    result = gestion_app.fetch_cnaps_public_annuaire(nom, nub)
    print(f"status={result.get('check_status')}")
    if result.get("http_status"):
        print(f"http_status={result.get('http_status')}")
    print(f"rows={len(result.get('results') or [])}")
    print(f"matched={len(result.get('results') or [])}")
    print("activities=" + json.dumps([row.get("activite") for row in (result.get("results") or [])], ensure_ascii=False))
    print("active_titles=" + json.dumps([title.get("code") for title in (result.get("active_titles") or [])], ensure_ascii=False))
    if result.get("error"):
        print(f"error={result.get('error')}")
    return 0 if result.get("check_status") == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
