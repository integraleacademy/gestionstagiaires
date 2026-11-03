"""Return evidence for a linked enrolment from the production filesystem."""
import datetime as dt
from decimal import Decimal, InvalidOperation
from pathlib import Path
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


def read_evidence(legacy, requested, *, data=None):
    if data is None:
        data = legacy.load_data()
    sessions = {str(s.get("id")): s for s in data.get("sessions", []) if isinstance(s, dict)}
    links = {}
    registrations = {}
    for x in data.get("wedof_links", []):
        if isinstance(x, dict) and x.get("active") and x.get("wedof_type", "cpf") == "cpf":
            links.setdefault(str(x.get("external_id")), []).append(x)
            pair = (str(x.get("session_id")), str(x.get("trainee_id")))
            registrations[pair] = registrations.get(pair, 0)+1
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
            matches = links.get(folder, [])
            if len(matches) != 1:
                continue
            link = matches[0]
            if registrations[(str(link.get("session_id")), str(link.get("trainee_id")))] != 1:
                continue
            session = sessions.get(str(link.get("session_id"))) or {}
            target = str(link.get("trainee_id") or "")
            trainees = [t for t in (session.get("trainees") or session.get(
                "stagiaires") or []) if isinstance(t, dict) and str(t.get("id")) == target]
            if len(trainees) != 1:
                continue
            t = trainees[0]
            start = iso(session.get("date_start") or session.get("date_debut"))
            end = iso(session.get("date_end") or session.get("date_fin"))
            item.update(first_name=t.get("first_name") or t.get("prenom"), last_name=t.get("last_name") or t.get("nom"),
                        session_start_date=start, session_end_date=end)
            if not start or not end or start > today:
                continue
            day = iso(t.get("actual_training_start_date") or t.get("real_training_start_date")
                      or t.get("certificate_realization_start_date"))
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
                    if start <= actual <= min(today, end):
                        if not day or actual < day:
                            day, proof = actual, f"Activité pédagogique enregistrée en production, événement {key}"
                        break
            if start <= day <= min(today, end):
                item["entry_training"] = {"action": "entry_training",
                                          "actual_date": day, "evidence": proof, "source": "production"}
            actual_end = iso(t.get("actual_training_end_date") or t.get(
                "real_training_end_date") or t.get("certificate_realization_end_date"))
            certificate = (t.get("deliverables") or {}).get("attestation_fin_formation")
            done = hours(t.get("realized_training_hours") or t.get("realised_training_hours")
                         or t.get("hours_completed") or t.get("certificate_realization_hours"))
            if start <= actual_end <= min(today, end) and certificate and done:
                # The consumer compares these actual hours with the contracted duration from the official detail.
                item["service_done"] = {"action": "service_done", "actual_date": actual_end, "evidence": "Attestation de fin et heures réalisées dans la fiche de production",
                                        "rate": 100, "reason": "", "source": "production", "actual_hours": str(done)}
    finally:
        if db:
            db.close()
    return result
