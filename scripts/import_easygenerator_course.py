#!/usr/bin/env python3
"""Import an Easygenerator manual SCORM export into the native course catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from elearning_native.importer import CourseImportError, import_easygenerator_course


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convertit un export SCORM manuel Easygenerator en cours natif Intégrale."
    )
    parser.add_argument("archive", type=Path, help="Chemin du fichier ZIP Easygenerator")
    parser.add_argument(
        "--persist-dir",
        type=Path,
        default=Path(os.environ["PERSIST_DIR"]) if os.environ.get("PERSIST_DIR") else None,
        help="Dossier persistant de l’application (ou variable PERSIST_DIR)",
    )
    parser.add_argument(
        "--catalog-root",
        type=Path,
        help="Dossier du catalogue natif; remplace --persist-dir/native_elearning",
    )
    parser.add_argument(
        "--without-source-archive",
        action="store_true",
        help="Ne conserve pas une copie du ZIP source avec la version importée",
    )
    args = parser.parse_args()

    if args.catalog_root is not None:
        catalog_root = args.catalog_root
    elif args.persist_dir is not None:
        catalog_root = args.persist_dir / "native_elearning"
    else:
        parser.error("Renseignez --persist-dir, --catalog-root ou la variable PERSIST_DIR.")

    try:
        course = import_easygenerator_course(
            args.archive,
            catalog_root,
            archive_source=not args.without_source_archive,
        )
    except CourseImportError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "course_id": course.get("id"),
                "version": course.get("version"),
                "title": course.get("title"),
                "counts": course.get("counts", {}),
                "warnings": course.get("import_warnings", []),
                "catalog_root": str(catalog_root.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
