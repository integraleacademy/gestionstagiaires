"""Selective recovery of a missing trainee; never restore the whole database."""
import copy
import hashlib
import json
import mmap
import re
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from backup_chronology import backup_chronology_key


def backup_inventory(backup_dir):
    paths = [p.name for p in sorted((p for p in Path(backup_dir).glob("data_json.*.json")
                                   if p.is_file() and not p.is_symlink()), key=backup_chronology_key)]
    return {"count": len(paths), "oldest": paths[0] if paths else "", "newest": paths[-1] if paths else ""}


def find_original_conventions(persist_dir, query):
    """Read existing originals only; never generate or send a new convention."""
    def normalize(value):
        return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))

    terms = re.findall(r"[a-z0-9]{3,}", normalize(str(query or "")[:80]))
    if not terms:
        return []
    root = Path(persist_dir) / "generated_documents" / "conventions_aps"
    matches = [p for p in root.glob("convention_formation_aps_*.docx")
               if p.is_file() and not p.is_symlink() and all(term in normalize(p.stem) for term in terms)]
    originals = []
    for path in sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.getinfo("word/document.xml").file_size > 2_000_000:
                    continue
                document = ElementTree.fromstring(archive.read("word/document.xml"))
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = ["".join(p.itertext()) for p in document.iter(ns + "p")]
            originals.append({"name": path.name, "text": "\n".join(paragraphs)[:20000]})
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
            continue
    return originals


def _trainees(session):
    rows = session.get("trainees", session.get("stagiaires", []))
    return rows if isinstance(rows, list) else []


def find_backup(backup_dir, trainee_id, partner_id, source=None):
    if not re.fullmatch(r"TRN-[A-F0-9]{8}", trainee_id):
        raise ValueError("Identifiant stagiaire invalide.")
    root = Path(backup_dir)
    if source:
        if Path(source).name != source:
            raise ValueError("Sauvegarde invalide.")
        if source.startswith("data_json.") and source.endswith(".json"):
            paths = [root / source]
        elif source.startswith("data.json.corrupt."):
            paths = [root.parent / source]
        else:
            raise ValueError("Sauvegarde invalide.")
    else:
        paths = sorted(list(root.glob("data_json.*.json")) + list(root.parent.glob("data.json.corrupt.*")),
                       key=backup_chronology_key, reverse=True)
    needle = ('"' + trainee_id + '"').encode()
    for path in paths:
        if path.is_symlink():
            continue
        try:
            # Most snapshots do not contain the missing ID. Avoid parsing or
            # retaining hundreds of full databases in memory.
            with path.open("rb") as handle:
                with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
                    if data.find(needle) < 0:
                        continue
                    payload = json.loads(data[:])
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        for session in payload.get("sessions", []):
            if not isinstance(session, dict) or (session.get("partner_id") or partner_id) != partner_id:
                continue
            for trainee in _trainees(session):
                if not isinstance(trainee, dict) or trainee.get("id") != trainee_id:
                    continue
                related = {}
                for key in ("billing_lines", "wedof_links"):
                    rows = payload.get(key) if isinstance(payload.get(key), list) else []
                    related[key] = [copy.deepcopy(row) for row in rows
                                    if isinstance(row, dict) and row.get("trainee_id") == trainee_id
                                    and row.get("session_id") == session.get("id")]
                bundle = {"trainee": copy.deepcopy(trainee), "related": related,
                          "session_id": session.get("id"), "partner_id": partner_id,
                          "session_name": session.get("name") or session.get("nom") or session.get("id"),
                          "source": path.name}
                bundle["fingerprint"] = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()
                return bundle
    return None


def restore_missing(payload, bundle):
    trainee = bundle["trainee"]
    trainee_id = trainee["id"]
    sessions = payload.get("sessions", [])
    for session in sessions:
        if isinstance(session, dict) and any(isinstance(t, dict) and t.get("id") == trainee_id for t in _trainees(session)):
            raise ValueError("Ce dossier existe déjà. Aucune donnée n’a été remplacée.")
    target = next((s for s in sessions if isinstance(s, dict) and s.get("id") == bundle["session_id"]
                   and (s.get("partner_id") or bundle["partner_id"]) == bundle["partner_id"]), None)
    if target is None:
        raise ValueError("La session d’origine n’existe plus ou appartient à un autre organisme.")
    additions = {}
    for key, rows in bundle.get("related", {}).items():
        existing = payload.get(key, [])
        if not isinstance(existing, list):
            raise ValueError("Collection de données invalide : " + key)
        additions[key] = []
        for row in rows:
            # Never resurrect a link now assigned elsewhere, or overwrite a
            # financial row whose status changed after the snapshot.
            conflicts = [r for r in existing if isinstance(r, dict) and
                         ((row.get("id") and r.get("id") == row.get("id")) or
                          (key == "wedof_links" and row.get("external_id") and r.get("external_id") == row.get("external_id")))]
            if conflicts:
                if any(r.get("trainee_id") != trainee_id or r.get("session_id") != bundle["session_id"] for r in conflicts):
                    raise ValueError("Une donnée liée appartient désormais à un autre dossier.")
                continue
            additions[key].append(copy.deepcopy(row))
    target["trainees"] = list(_trainees(target)) + [copy.deepcopy(trainee)]
    target.pop("stagiaires", None)
    for key, rows in additions.items():
        if rows:
            payload.setdefault(key, []).extend(rows)
    return {"session_id": bundle["session_id"], "trainee_id": trainee_id}
