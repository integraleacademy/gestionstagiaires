"""Identify training requests without confusing them with WEDOF resources.

The webhook journal remains intact. Its admin view groups only notifications
about the same registration folder, never people with the same email/name.
"""
import copy
import re
from urllib.parse import urlparse


ENVELOPES = ("registrationFolder", "folder", "resource", "data", "payload")


def _text(value):
    return str(value).strip() if isinstance(value, (str, int)) else ""


def _link(payload, relation):
    links = payload.get("_links")
    value = links.get(relation) if isinstance(links, dict) else None
    return _text(value.get("href")) if isinstance(value, dict) else ""


def notification_kind(payload, event=""):
    """Use the resource itself before any loosely named id or related link."""
    if not isinstance(payload, dict):
        return "technical"
    event = _text(event or payload.get("event")).casefold()
    self_path = urlparse(_link(payload, "self")).path
    if (event.startswith("certification")
            or "/certificationFolders/" in self_path):
        return "certification"
    if ("fileName" in payload or "fileType" in payload
            or "document" in event or "file" in event):
        return "document"
    # A registration folder can itself link to a certification folder. Only
    # document-shaped payloads or the self link identify a different resource.
    if re.fullmatch(r"/api/registrationFolders/[^/]+/?", self_path):
        return "registration"
    if self_path:
        return "technical"
    for key in ENVELOPES:
        if isinstance(payload.get(key), dict):
            nested = notification_kind(payload[key], event)
            if nested != "technical":
                return nested
    if event.startswith(("registrationfolder.", "registrationfolderbilling.",
                         "cpf.", "edof.", "dossier.")):
        return "registration" if any(payload.get(key) for key in (
            "externalId", "id", "dataProviderId", "registrationFolderId",
            "registration_folder_id", "folderId", "dossierId", "attendee",
            "trainingActionInfo", "email")) else "technical"
    if event:
        return "technical"
    if (isinstance(payload.get("trainingActionInfo"), dict)
            or any(payload.get(key) for key in (
                "registrationFolderId", "registration_folder_id", "folderId"))
            or (payload.get("externalId") and any(payload.get(key) for key in (
                "attendee", "email", "state", "type")))):
        return "registration"
    return "technical"


def registration_id(payload, event=""):
    if notification_kind(payload, event) != "registration":
        return ""
    for key in ENVELOPES:
        nested = payload.get(key)
        if isinstance(nested, dict):
            identifier = registration_id(nested, event)
            if identifier:
                return identifier
    # Explicit folder identifiers outrank the id of an event envelope.
    for key in ("externalId", "registrationFolderId", "registration_folder_id",
                "folderId", "dataProviderId", "dossierId", "id"):
        value = _text(payload.get(key))
        if value:
            return value
    match = re.fullmatch(r"/api/registrationFolders/([^/]+)/?",
                         urlparse(_link(payload, "self")).path)
    return match.group(1) if match else ""


def entry_kind(entry):
    event = entry.get("event") or ""
    payload = entry.get("payload") or {}
    kind = notification_kind(payload, event)
    if kind != "technical" or payload or event:
        return kind
    return notification_kind(entry.get("wedof_folder_details") or {})


def registration_payload(payload, event=""):
    """Unwrap complete or partial registration updates with a canonical id."""
    if notification_kind(payload, event) != "registration":
        return {}
    for key in ENVELOPES:
        nested = payload.get(key)
        if isinstance(nested, dict):
            result = registration_payload(nested, event)
            if result:
                return result
    result = dict(payload)
    identifier = registration_id(payload, event)
    if identifier:
        result["externalId"] = identifier
    return result


def entry_folder_id(entry):
    if entry_kind(entry) != "registration":
        return ""
    return (registration_id(entry.get("payload") or {}, entry.get("event") or "")
            or registration_id(entry.get("wedof_folder_details") or {})
            or _text(entry.get("folder_id")))


def related_entries(entries, entry):
    identifier = entry_folder_id(entry)
    if not identifier:
        return [entry]
    return [item for item in entries if isinstance(item, dict)
            and entry_folder_id(item) == identifier]


def merge_folder(newer, older):
    """Fill missing fields in a partial update, preserving explicit false/zero."""
    result = copy.deepcopy(older) if isinstance(older, dict) else {}
    if not isinstance(newer, dict):
        return result
    for key, value in newer.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_folder(value, result[key])
        elif value not in (None, ""):
            result[key] = copy.deepcopy(value)
    return result


def grouped_requests(entries):
    """Build a non-destructive view over all history, before page limits."""
    groups = {}
    technical_count = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if entry_kind(entry) != "registration":
            technical_count += 1
            continue
        key = entry_folder_id(entry) or f"entry:{entry.get('id') or index}"
        groups.setdefault(key, []).append(entry)
    rows = []
    for events in groups.values():
        if any(item.get("archived") for item in events):
            continue
        events = sorted(events, key=lambda item: _text(item.get("received_at")), reverse=True)
        row = dict(events[0])
        row["folder_id"] = entry_folder_id(row)
        row["related_entries"] = events
        row["event_count"] = len(events)
        row["processed"] = any(item.get("processed") for item in events)
        for target in ("salesforce", "crm"):
            successes = [item for item in events if item.get(f"{target}_sent")]
            if successes:
                last_success = max(successes, key=lambda item: _text(item.get(f"{target}_sent_at")))
                for suffix in ("sent", "sent_at"):
                    row[f"{target}_{suffix}"] = last_success.get(f"{target}_{suffix}")
                row[f"{target}_send_count"] = sum(int(item.get(f"{target}_send_count") or 0) for item in successes)
                # An old failed attempt must not replace a later success.
                if _text(row.get(f"{target}_last_attempt_at")) <= _text(last_success.get(f"{target}_sent_at")):
                    row.pop(f"{target}_last_error", None)
        rows.append(row)
    rows.sort(key=lambda item: _text(item.get("received_at")), reverse=True)
    return rows, technical_count
