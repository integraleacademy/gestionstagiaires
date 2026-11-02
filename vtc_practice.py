"""Scheduling for the two optional VTC practical training groups."""
import datetime as dt
import re
from copy import deepcopy


KEY = "vtc_practice_groups"
MIN_SPLIT_SIZE = 9


def supported(session):
    return "VTC" in str(session.get("training_type") or session.get("type_formation") or "").upper()


def assignments(config, registered):
    """Keep assigned places, then fill the smaller group in registration order."""
    members = dict(config.get("members") or {})
    ordered = sorted(registered, key=lambda t: (str(t.get("created_at") or ""), str(t.get("id") or "")))
    ids = list(dict.fromkeys(str(t["id"]) for t in ordered if t.get("id")))
    sizes = {group: sum(members.get(key) == group for key in ids) for group in (1, 2)}
    for key in ids:
        if members.get(key) not in (1, 2):
            group = 1 if sizes[1] <= sizes[2] else 2
            members[key] = group
            sizes[group] += 1
    return members


def configure(session, registered, slots, common_date):
    if not supported(session):
        raise ValueError("Les groupes de pratique sont réservés aux sessions VTC.")
    if slots is None:
        return None
    current = session.get(KEY) or {}
    if not current and len(registered) < MIN_SPLIT_SIZE:
        raise ValueError("Il faut au moins 9 stagiaires inscrits pour créer deux groupes.")
    if not isinstance(slots, list) or len(slots) != 2:
        raise ValueError("Renseignez les deux créneaux de formation pratique.")
    clean = []
    for group, slot in enumerate(slots, 1):
        if not isinstance(slot, dict):
            raise ValueError(f"Créneau invalide pour le groupe {group}.")
        day = (slot.get("date") or common_date) if group == 2 else common_date
        try:
            if not isinstance(day, str) or dt.date.fromisoformat(day).isoformat() != day:
                raise ValueError
        except ValueError:
            raise ValueError(f"Indiquez une date valide pour le groupe {group}.") from None
        start, end = slot.get("start"), slot.get("end")
        if not all(isinstance(t, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in (start, end)):
            raise ValueError(f"Indiquez les heures de début et de fin du groupe {group}.")
        if end <= start:
            raise ValueError(f"La fin du groupe {group} doit être postérieure au début.")
        clean.append({"date": day if group == 1 or day != common_date else "", "start": start, "end": end})
    first, second = clean
    if not second["date"] and first["start"] < second["end"] and second["start"] < first["end"]:
        raise ValueError("Les deux créneaux de pratique se chevauchent.")
    return {"slots": clean, "members": assignments(current, registered)}


def reconcile(data, registered, canonical=None):
    """Schedules are edited atomically. Preserve them across ordinary whole-store saves."""
    saved = {s.get("id"): s[KEY] for s in (canonical or {}).get("sessions", [])
             if isinstance(s, dict) and s.get(KEY)}
    for session in data.get("sessions", []):
        if not isinstance(session, dict):
            continue
        if canonical is not None:
            if session.get("id") in saved:
                session[KEY] = deepcopy(saved[session["id"]])
                session["practice_training_date"] = session[KEY]["slots"][0]["date"]
            else:
                session.pop(KEY, None)
        config = session.get(KEY)
        if config:
            config["members"] = assignments(config, registered(session))


def appointment(session, trainee, registered):
    day = session.get("practice_training_date") or ""
    config = session.get(KEY) if supported(session) else None
    group = None
    if config and trainee.get("id"):
        key = str(trainee["id"])
        group = config["members"].get(key) or assignments(config, registered(session)).get(key)
    if group:
        slot = config["slots"][group - 1]
        start, end = slot["start"], slot["end"]
        day = slot["date"] or config["slots"][0]["date"]
    else:
        raw = str(session.get("practice_training_time") or "08:30").strip().lower().replace("h", ":")
        try:
            parsed = dt.datetime.strptime(raw, "%H:%M")
        except ValueError:
            parsed = dt.datetime.strptime("08:30", "%H:%M")
        start = parsed.strftime("%H:%M")
        end = (parsed + dt.timedelta(hours=3, minutes=30)).strftime("%H:%M")
    first = dt.time.fromisoformat(start)
    last = dt.time.fromisoformat(end)
    minutes = (last.hour * 60 + last.minute - first.hour * 60 - first.minute) % (24 * 60)
    hours, rest = divmod(minutes, 60)
    return {"group": group, "date": day, "start": start.replace(":", "h"), "end": end.replace(":", "h"),
            "duration": f"{hours} h {rest:02d}" if rest else f"{hours} h"}
