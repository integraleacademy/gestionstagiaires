"""Minimal, account-scoped directory from the official EDOF dossier list."""
from datetime import datetime
import hmac
import time
import unicodedata
from zoneinfo import ZoneInfo

from edof_readonly_test import ID_RE, SIRET

TTL = 86400
REFRESH_INTERVAL = 15 * 60
IDLE_REFRESH_INTERVAL = 6 * 3600
MAX_ROWS = 30000


class IncompleteDirectory(ValueError):
    pass


def normalized(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(c if c.isalnum() else " " for c in value
                            if not unicodedata.combining(c)).split())


def text_field(value, limit):
    if isinstance(value, str):
        return " ".join(value.split())[:limit]
    return ""


def project(row):
    if not isinstance(row, dict) or not ID_RE.fullmatch(str(row.get("id", ""))):
        raise IncompleteDirectory()
    attendee = row.get("attendee") or {}
    info = row.get("trainingActionInfo") or {}
    if not isinstance(attendee, dict) or not isinstance(info, dict):
        raise IncompleteDirectory()
    for ref in (row.get("trainingId"), row.get("trainingActionId"), info.get("sessionId")):
        if ref and (not isinstance(ref, str) or not ref.startswith(SIRET + "_")):
            raise IncompleteDirectory()
    return {"folder_id": str(row["id"]), "first_name": text_field(attendee.get("firstName"), 120),
            "last_name": text_field(attendee.get("lastName"), 120),
            "state": text_field(row.get("currentState"), 80),
            "title": text_field(info.get("title") or row.get("title") or row.get("trainingTitle"), 500),
            "session_start_date": text_field(info.get("sessionStartDate") or row.get("beginDate"), 10),
            "session_end_date": text_field(info.get("sessionEndDate") or row.get("endDate"), 10)}


def from_pages(pages, progress=None):
    """Publish only an entire list with a stable total and distinct identifiers."""
    rows = {}
    progress = progress if progress is not None else {}
    total = None
    for page in pages:
        progress["pages"] = progress.get("pages", 0) + 1
        count = page.get("numberOfItems") if isinstance(page, dict) else None
        if type(count) is not int or not 0 <= count <= MAX_ROWS or (total is not None and total != count):
            raise IncompleteDirectory()
        total = count
        progress["expected"] = count
        items = page.get("items")
        if not isinstance(items, list) or (not items and count > len(rows)):
            raise IncompleteDirectory()
        for item in items:
            fields = project(item)
            key = fields["folder_id"]
            if key in rows:
                raise IncompleteDirectory()
            rows[key] = fields
            progress["seen"] = len(rows)
        if len(rows) == total:
            if total and not any(row["first_name"] and row["last_name"] for row in rows.values()):
                raise IncompleteDirectory()
            return {"checked": time.time(), "rows": rows}
        if len(rows) > total:
            break
    raise IncompleteDirectory()


def record_key(owner):
    return "edof-directory-v1-" + owner


def stamp(snapshot):
    return datetime.fromtimestamp(snapshot["checked"], ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H h %M")


def matches(snapshot, spec):
    rows = snapshot["rows"]
    if spec["folder_id"]:
        fields = rows.get(spec["folder_id"])
        candidates = [fields] if fields else []
    else:
        candidates = rows.values()
    if not spec["first_name"]:
        return list(candidates)
    surname, first = normalized(spec["last_name"]), normalized(spec["first_name"])
    if not surname or not first:
        return []
    return [row for row in candidates if normalized(row["last_name"]) == surname and normalized(row["first_name"]) == first]


def link_key(owner, folder_id):
    return hmac.digest(owner.encode(), ("edof-directory/" + folder_id).encode(), "sha256").hex()[:32]


def csv_snapshot(content, first, progress):
    """Accept only an official export matching the witnessed list size and first page."""
    import csv
    import io

    if not 0 < len(content) <= 24_000_000:
        raise IncompleteDirectory()
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        data = content.decode("utf-16")
    else:
        try:
            data = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            data = content.decode("cp1252")
    lines = data.splitlines()
    if not lines:
        raise IncompleteDirectory()
    delimiter = max((";", "\t", ","), key=lambda sep: max((line.count(sep) for line in lines[:4]), default=0))
    reader = csv.reader(io.StringIO(data), delimiter=delimiter)

    def indexes(cells):
        columns = {}
        for i, cell in enumerate(cells):
            label = normalized(cell)
            words = set(label.split())
            identity_column = not words & {"financeur", "organisme", "commercial", "structure", "formateur", "certificateur",
                                          "formation", "session", "certification", "ville", "lieu"}
            if (("dossier" in words and words & {"id", "identifiant", "numero", "num", "n", "no", "ref", "reference"})
                    or label in {"numero cpf", "identifiant cpf", "n cpf", "dossier", "registrationfolderid", "externalid"}):
                columns.setdefault("folder_id", i)
            elif identity_column and ("prenom" in words or label == "firstname"):
                columns.setdefault("first_name", i)
            elif identity_column and ("nom" in words or label == "lastname"):
                columns.setdefault("last_name", i)
            elif (words & {"intitule", "titre", "libelle"} and "formation" in words) or label in {"formation", "trainingtitle"}:
                columns.setdefault("title", i)
            elif ((words & {"statut", "etat"} and "dossier" in words and not "facturation" in words)
                  or label in {"statut", "etat", "currentstate"}):
                columns.setdefault("state", i)
            elif "debut" in words and words & {"formation", "session"}:
                columns.setdefault("session_start_date", i)
            elif "fin" in words and words & {"formation", "session"}:
                columns.setdefault("session_end_date", i)
        return columns

    for _ in range(5):
        columns = indexes(next(reader, []))
        progress["export_fields"] = sorted(set(progress.get("export_fields", ())) | columns.keys())
        if {"folder_id", "first_name", "last_name"} <= columns.keys():
            break
    else:
        raise IncompleteDirectory()
    total = first.get("numberOfItems")
    if type(total) is not int or not 0 <= total <= MAX_ROWS:
        raise IncompleteDirectory()
    rows = {}
    for cells in reader:
        if not any(cell.strip() for cell in cells):
            continue
        if max(columns.values()) >= len(cells):
            raise IncompleteDirectory()
        item = {k: text_field(cells[i], 500 if k == "title" else 120) for k, i in columns.items()}
        key = item["folder_id"]
        if key.startswith('="') and key.endswith('"'):
            key = key[2:-1]
        if not ID_RE.fullmatch(key) or key in rows or len(rows) >= total:
            raise IncompleteDirectory()
        item["folder_id"] = key
        for field in ("state", "title", "session_start_date", "session_end_date"):
            item.setdefault(field, "")
        for field in ("session_start_date", "session_end_date"):
            value = item[field]
            item[field] = ""
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    item[field] = datetime.strptime(value[:10], fmt).date().isoformat()
                    break
                except ValueError:
                    continue
        rows[key] = item
        progress["export_rows"] = len(rows)
    if len(rows) != total or (total and not any(row["first_name"] and row["last_name"] for row in rows.values())):
        raise IncompleteDirectory()
    for witness in first.get("items", []):
        sample = project(witness)
        row = rows.get(sample["folder_id"])
        if not row or any(sample[k] and normalized(row[k]) != normalized(sample[k]) for k in ("first_name", "last_name")):
            raise IncompleteDirectory()
    progress.update(method="csv", expected=total, seen=total)
    return {"checked": time.time(), "rows": rows}
