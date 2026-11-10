"""Return evidence for a linked enrolment from the production filesystem."""
import datetime as dt
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo


def iso(raw):
    if not isinstance(raw, str):
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def hours(raw):
    try:
        value = Decimal(str(raw).replace(",", "."))
        return value if value.is_finite() and value > 0 else None
    except (InvalidOperation, ValueError):
        return None


def linked_enrolments(data, requested):
    """Resolve only unique two-way CPF links to an actual registration."""
    sessions = {str(s.get("id")): s for s in data.get("sessions", []) if isinstance(s, dict)}
    links = {}
    registrations = {}
    for x in data.get("wedof_links", []):
        if isinstance(x, dict) and x.get("active") and x.get("wedof_type", "cpf") == "cpf":
            links.setdefault(str(x.get("external_id")), []).append(x)
            pair = (str(x.get("session_id")), str(x.get("trainee_id")))
            registrations[pair] = registrations.get(pair, 0)+1
    resolved = {}
    for folder in requested:
        matches = links.get(folder, [])
        if len(matches) != 1:
            continue
        link = matches[0]
        pair = str(link.get("session_id")), str(link.get("trainee_id"))
        if registrations[pair] != 1:
            continue
        session = sessions.get(pair[0]) or {}
        trainees = [t for t in (session.get("trainees") or session.get("stagiaires") or [])
                    if isinstance(t, dict) and t.get("id") and str(t["id"]) == pair[1]]
        if len(trainees) == 1:
            resolved[folder] = (link, session, trainees[0])
    return resolved


def linked_identity(link, trainee):
    return {"first_name": trainee.get("first_name") or trainee.get("prenom"),
            "last_name": trainee.get("last_name") or trainee.get("nom"),
            "linked_session": str(link.get("session_id") or ""), "linked_trainee": str(link.get("trainee_id") or ""),
            "identity_confirmation": (link.get("edof_identity_confirmation") or {}).get("key")}


def read_evidence(legacy, requested, *, data=None):
    if data is None:
        data = legacy.load_data()
    enrolments = linked_enrolments(data, requested)
    blocks = {str(x["external_id"]): set() for x in data.get("wedof_automation_blocks", [])
              if isinstance(x, dict) and x.get("active") and x.get("external_id")}
    for x in data.get("wedof_automation_blocks", []):
        if isinstance(x, dict) and x.get("active") and str(x.get("external_id")) in blocks:
            blocks[str(x["external_id"])].add(x.get("action"))
    result = {}
    paris = ZoneInfo("Europe/Paris")
    today = dt.datetime.now(paris).date().isoformat()
    path = Path(legacy.DATA_FILE).parent/"native_elearning"/"tracking.sqlite3"
    db = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=2) if path.is_file() else None
    try:
        has_tracking = db and db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tracking_events'").fetchone()
        for folder in requested:
            # Include production block flags even for dossiers without a linked enrolment.
            item = {"blocks": sorted(k for k in blocks.get(folder, set()) if k in {
                                     "both", "entry_training", "service_done"})}
            result[folder] = item
            if folder not in enrolments:
                continue
            link, session, t = enrolments[folder]
            target = str(t["id"])
            start = iso(session.get("date_start") or session.get("date_debut"))
            end = iso(session.get("date_end") or session.get("date_fin"))
            item.update(**linked_identity(link, t),
                        session_start_date=start, session_end_date=end)
            if not start or not end or start > today:
                continue
            vtc_period = re.fullmatch(r"(?:du\s+)?(\d{1,2}/\d{1,2}/\d{4})\s+au\s+(\d{1,2}/\d{1,2}/\d{4})",
                                      str(t.get("vtc_real_training_dates") or "").strip(), re.I)
            vtc_start, vtc_end = (iso(d) for d in vtc_period.groups()) if vtc_period else ("","")
            if not (start <= vtc_start <= vtc_end <= end):
                vtc_start = vtc_end = ""
            day = iso(t.get("actual_training_start_date") or t.get("real_training_start_date")
                      or t.get("certificate_realization_start_date")) or vtc_start
            proof = "Date d’entrée effective renseignée dans la fiche de production"
            if not day and has_tracking:
                after = (dt.date.fromisoformat(start)-dt.timedelta(days=1)).isoformat()
                for key, at in db.execute("""SELECT id,event_at FROM tracking_events WHERE session_id=? AND trainee_id=?
                    AND event_type IN ('content_completed','answer_submitted') AND activity_id!='' AND event_at>=?
                    ORDER BY event_at,id LIMIT 50""", (str(link["session_id"]), target, after)):
                    try:
                        stamp = dt.datetime.fromisoformat(at)
                        actual = stamp.astimezone(paris).date().isoformat() if stamp.tzinfo else ""
                    except (TypeError, ValueError):
                        continue
                    if actual == start:
                        day, proof = start, f"Activité pédagogique enregistrée en production, événement {key}"
                        break
            if start <= day <= min(today, end):
                item["entry_training"] = {"action": "entry_training",
                                          "actual_date": day, "evidence": proof, "source": "production"}
            end_record = t.get("actual_training_end_date") or t.get("real_training_end_date") or t.get("certificate_realization_end_date")
            actual_end = iso(end_record) if end_record else vtc_end
            certificate = (t.get("deliverables") or {}).get("attestation_fin_formation")
            done = hours(t.get("realized_training_hours") or t.get("realised_training_hours")
                         or t.get("hours_completed") or t.get("certificate_realization_hours"))
            if not end_record and not actual_end and not t.get("vtc_real_training_dates") and certificate and done:
                # The completion certificate and recorded hours support using the
                # course end date. The browser verifies those hours before sending.
                actual_end = end
            if start <= actual_end <= min(today, end) and certificate and done:
                # The consumer compares these actual hours with the contracted duration from the official detail.
                item["service_done"] = {"action": "service_done", "actual_date": actual_end, "evidence": "Attestation de fin et heures réalisées dans la fiche de production",
                                        "rate": 100, "reason": "", "source": "production", "actual_hours": str(done)}
    finally:
        if db:
            db.close()
    return result
