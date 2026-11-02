"""Minimal, account-scoped directory from the official EDOF dossier list."""
from datetime import datetime
import hmac
import re
import time
import unicodedata
from zoneinfo import ZoneInfo

from edof_readonly_test import ID_RE, SIRET

TTL = 86400
REFRESH_INTERVAL = 15 * 60
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
