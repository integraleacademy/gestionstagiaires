"""Attach the planning catalogue to the academy's administrative sessions."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hmac
import os
import re
import threading
import time
import unicodedata
import uuid
from zoneinfo import ZoneInfo

import ijson
import requests
from flask import abort, jsonify, request

SOURCE = "https://plateformegestion.onrender.com/api/integrations/session-catalogue"
TYPES = {"aps": "APS", "a3p-apr": "A3P", "ssiap-1": "SSIAP 1", "ssiap-2": "SSIAP 2",
         "ssiap-3": "SSIAP 3", "desp-dssp": "DIRIGEANT initial", "afc": "APS"}
FIELDS = ("slug", "centre", "start", "end", "exam")
CITIES = {"paris": "Paris", "puget": "Puget-sur-Argens"}
STATE = "platform_catalogue"


def normal(value):
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()


def local_identity(host, training):
    get = host._session_get
    kind, name = normal(get(training, "training_type")), normal(get(training, "name"))
    if host.afc_schedule.enabled(training):
        slug = "afc"
    elif "vae" in kind:
        slug = "desp-vae" if "dirigeant" in kind or "desp" in kind else ""
    elif "dirigeant" in kind or "desp" in kind:
        slug = "desp-dssp"
    elif kind.startswith("ssiap"):
        level = re.search(r"ssiap\s*[- ]?([123])", kind + " " + name)
        slug = "ssiap-" + (level[1] if level else "1")
    elif kind in ("aps", "tfp aps", "cqp aps"):
        slug = "aps"
    elif kind in ("a3p", "apr"):
        slug = "a3p-apr"
    elif kind == "vtc":
        slug = "vtc"
    else:
        return {}
    location = normal(training.get("crm_center") or training.get("centre") or name)
    if re.search(r"aurillac|auvergne|arpajon|cantal", location):
        centre = "auvergne"
    elif "paris" in location:
        centre = "paris"
    elif slug == "desp-dssp" and not re.search(r"puget|azur|^var$", location):
        centre = host.desp_kickoff.location(host, training) or ""
    else:
        centre = "puget"
    def day(field):
        value = host._parse_iso_date(get(training, field))
        return value.isoformat() if value else ""
    return dict(slug=slug, centre=centre, start=day("date_start"), end=day("date_end"), exam=day("exam_date"))


def same_group(a, b):
    return a.get("slug") == b.get("slug") and bool(a.get("centre")) and a["centre"] == b.get("centre")


def correspondence(a, b):
    return same_group(a, b) and sum(bool(a.get(key)) and a[key] == b.get(key) for key in ("start", "end", "exam")) >= 2


def overlaps(a, b):
    return same_group(a, b) and all(x.get(k) for x in (a, b) for k in ("start", "end")) and a["start"] <= b["end"] and b["start"] <= a["end"]


def own(host, training):
    return training.get("partner_id") in (None, "", host.INTEGRALE_PARTNER_ID) and not host._is_wedof_leads_session(training)


def signature(row):
    return {k: row.get(k, "") for k in FIELDS}


def choose(row, candidates):
    linked = [s for s, key in candidates if s.get(STATE, {}).get("id") == row["id"]]
    requested = row.get("target")
    if linked:
        if len(linked) != 1 or requested and requested != linked[0]["id"]:
            raise ValueError("Rattachement existant à vérifier")
        return linked[0]
    if requested:
        matches = [s for s, key in candidates if s.get("id") == requested and not s.get(STATE)
                   and key.get("slug") == row["slug"] and not s.get("archived")]
        if len(matches) != 1:
            raise ValueError("Identifiant de rattachement incompatible")
        return matches[0]
    keys = [row, *row.get("aliases", [])]
    matches = [s for s, key in candidates if not s.get("archived") and any(correspondence(key, k) for k in keys)]
    if len(matches) == 1 and not matches[0].get(STATE):
        return matches[0]
    if matches or any(not s.get("archived") and not s.get(STATE) and any(overlaps(key, k) for k in keys) for s, key in candidates):
        raise ValueError("Dates proches ou plusieurs fiches possibles. Précisez la fiche Gestion Stagiaires dans Plateforme Gestion.")
    return None


def updates(host, row, training, previous):
    result = dict(date_start=row["start"], date_end=row["end"], crm_center=CITIES.get(row["centre"], ""),
                  exam_date=row["exam"])
    if row["slug"] == "ssiap-1" and row.get("standard_start"):
        result["date_start"] = row["standard_start"]
        first = date.fromisoformat(row["start"])
        gap = (date.fromisoformat(row["standard_start"]) - first).days
        days = [first + timedelta(days=i) for i in range(gap)] if 0 < gap <= 7 else []
        sst = [d.isoformat() for d in days if d.weekday() < 5]
        if len(sst) == 2:
            existing = host.ssiap_pathways.settings(training)
            # Keep an established individual timetable. For new groups the two
            # published SST days precede the common SSIAP training period.
            if not existing["sst_dates"] or existing["sst_dates"] == sst:
                result["ssiap_pathways"] = {**host.ssiap_pathways.settings({**training, **result}), "sst_dates": sst}
            elif previous and previous["source"].get("standard_start") != row["standard_start"]:
                raise ValueError("Les journées SST enregistrées doivent être vérifiées avant le report.")
    if row["slug"] == "afc":
        result.update(afc_enabled=True, ssiap_exam_date=row.get("ssiap_exam", ""))
    prefix = {"aps": "aps", "desp-dssp": "dirigeant"}.get(row["slug"])
    if prefix:
        before = previous.get("source", {})
        moved = bool(before) and (before.get("start"), before.get("end")) != (row["start"], row["end"])
        for old, new in (("remote", "remote"), ("onsite", "in_person")):
            for boundary in ("start", "end"):
                source = old + "_" + boundary
                if row.get(source) or before.get(source) or moved:
                    result[f"{prefix}_{new}_{boundary}"] = row.get(source, "")
    if prefix == "aps" and (not previous or moved):
        # The native editor derives global dates from these two boundary fields.
        # Clear old intermediate dates on a reschedule and keep explicit planning dates.
        result["aps_remote_start"] = row.get("remote_start") or row["start"]
        result["aps_in_person_end"] = row.get("onsite_end") or row["end"]
    if previous.get("generated_name") and training.get("name") == previous["generated_name"]:
        result["name"] = label(row)
    return result


def label(row):
    kind = "AFC France Travail APS + SSIAP 1" if row["slug"] == "afc" else TYPES[row["slug"]]
    return f"{kind} · {CITIES.get(row['centre'], '')} · {row['start'][8:]}/{row['start'][5:7]}/{row['start'][:4]}"


class NoChange(Exception):
    pass


def reconcile(host, data, rows):
    trainings = data.setdefault("sessions", [])
    candidates = [(s, local_identity(host, s)) for s in trainings if own(host, s)]
    seen, conflicts, changed = set(), [], False
    for row in rows:
        seen.add(row["id"])
        try:
            if not row["centre"] and row["visibility"] != "closed":
                raise ValueError("Renseignez le centre dans Plateforme Gestion.")
            training = choose(row, candidates)
            if training is None and row["visibility"] == "closed":
                continue
            previous = training.get(STATE, {}) if training else {}
            if training and previous.get("source") == row:
                continue
            new = training is None
            if new:
                training = dict(id=uuid.uuid4().hex[:10], name=label(row), training_type=TYPES[row["slug"]],
                                partner_id=host.INTEGRALE_PARTNER_ID, trainees=[], archived=False, created_at=host._now_iso())
            local = local_identity(host, training)
            aliases = list(previous.get("aliases", []))
            # A second SSIAP start identifies a formula, not a rescheduled full group.
            local_keys = [] if row.get("standard_start") and local.get("start") == row["standard_start"] else [local]
            for key in [*local_keys, previous.get("source", {}), *row.get("aliases", []), row]:
                key = signature(key)
                if key["start"] and key not in aliases:
                    aliases.append(key)
            projection = updates(host, row, training, previous)
            # Only the scheduling fields are shared. Run normal date protections
            # for enrolled trainees and for sessions already linked to WeDoF.
            if row["visibility"] != "closed":
                draft = deepcopy(training)
                draft["training_type"] = TYPES[row["slug"]]
                check = host._apply_session_update({**data, "sessions": [draft]}, draft["id"], projection)
                response, status = check if isinstance(check, tuple) else (check, 200)
                if status != 200:
                    raise ValueError(response.get_json().get("error", "Vérifiez les dates de la fiche."))
                training.update(draft)
            generated = training["name"] if new or previous.get("generated_name") else ""
            training[STATE] = dict(id=row["id"], source=row, aliases=aliases, generated_name=generated)
            if new:
                trainings.insert(0, training)
                candidates.append((training, signature(row)))
            changed = True
        except ValueError as exc:
            conflicts.append({**signature(row), "id": row["id"], "reason": str(exc)})
    for training, _ in candidates:
        state = training.get(STATE)
        if state and state["id"] not in seen and state["source"]["visibility"] != "closed":
            state["source"] = {**state["source"], "visibility": "closed"}
            changed = True
    if data.get("session_catalogue_conflicts", []) != conflicts:
        data["session_catalogue_conflicts"] = conflicts
        changed = True
    if not changed:
        raise NoChange
    return {"conflicts": len(conflicts)}


def feed(host, trainings):
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    result = []
    for training in trainings:
        if not own(host, training):
            continue
        state = training.get(STATE, {})
        row = dict(state.get("source") or local_identity(host, training))
        if not row.get("start") or not row.get("end") or not row.get("slug"):
            continue
        aliases = state.get("aliases", [])
        if max([row["end"], *(k.get("end", "") for k in aliases)]) < today:
            continue
        if not state and (row["slug"] == "afc" or training.get("archived") or training.get("exclude_from_sales_tracking")):
            continue
        if training.get("archived"):
            row["visibility"] = "closed"
        # Only enumerated schedule fields and aggregate sales leave the service.
        entry = {**{k: row.get(k, "") for k in (*FIELDS, "standard_start", "remote_start", "remote_end", "onsite_start", "onsite_end")},
                       "id": "platform-" + state["id"] if state else "gestion-" + str(training["id"]),
                       "visibility": row.get("visibility", "match"), "aliases": aliases,
                       "capacity": row.get("capacity") if state else None, "sold": len(host._registered_trainees(training))}
        result.append(entry)
        if row["slug"] == "ssiap-1":
            options = host.ssiap_pathways.settings(training)
            for path, code in (("recyclage", "recyclage-ssiap-1"), ("remise_a_niveau", "remise-a-niveau-ssiap-1")):
                days = sorted(options.get(path + "_dates", []))
                periods = [{"centre": k["centre"], "start": k["start"], "end": k["end"]} for k in [row, *aliases] if k.get("start") and k.get("end")]
                result.append({**entry, "id": entry["id"] + "-" + path, "slug": code, "exam": "", "standard_start": "",
                               "start": days[0] if days else row["start"], "end": days[-1] if days else row["end"],
                               "onsite_start": days[0] if days else "", "onsite_end": days[-1] if days else "",
                               "remote_start": "", "remote_end": "", "group_periods": periods, "aliases": [],
                               "visibility": entry["visibility"] if days else "closed"})

    return result


def validate(payload):
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("sessions"), list):
        raise ValueError("Format de calendrier invalide")
    seen = set()
    for row in payload["sessions"]:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in seen
                or row.get("slug") not in TYPES or row.get("visibility") not in ("public", "internal", "closed", "match")
                or row.get("centre") not in ("", *CITIES) or type(row.get("capacity")) is not int or not 1 <= row["capacity"] <= 12):
            raise ValueError("Session de planning invalide")
        for key in ("start", "end", "exam", "remote_start", "remote_end", "onsite_start", "onsite_end", "ssiap_exam", "standard_start"):
            if row.get(key):
                datetime.strptime(row[key], "%Y-%m-%d")
        if not row.get("start") or not row.get("end"):
            raise ValueError("Période de planning manquante")
        seen.add(row["id"])
    return payload["sessions"]


def start_worker(host):
    token = os.getenv("SESSION_CATALOG_TOKEN")
    if not token or "session_catalogue_worker" in host.app.extensions:
        return
    stop = threading.Event()
    def run():
        etag = ""
        while not stop.is_set():
            try:
                headers = {"Authorization": "Bearer " + token, "If-None-Match": etag}
                reply = requests.get(SOURCE, headers=headers, timeout=(3, 15), allow_redirects=False)
                if reply.status_code != 304:
                    reply.raise_for_status()
                    rows = validate(reply.json())
                    with host.app.app_context():
                        try:
                            host._atomic_update_data(lambda current: reconcile(host, current, rows))
                        except NoChange:
                            pass
                    etag = reply.headers.get("ETag", "")
            except Exception as exc:
                host.app.logger.warning("Synchronisation des sessions en attente (%s)", type(exc).__name__)
            stop.wait(45)
    thread = threading.Thread(target=run, daemon=True, name="planning-sessions")
    host.app.extensions["session_catalogue_worker"] = {"thread": thread, "stop": stop}
    thread.start()


def register(host):
    lock = threading.Lock()
    cached = {}
    @host.app.get("/api/integrations/session-availability")
    def session_availability():
        token = os.getenv("SESSION_CATALOG_TOKEN")
        if not token or not hmac.compare_digest(request.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()):
            abort(401)
        with lock:
            # Parse one session at a time, and never expand external partner databases.
            with open(host.DATA_FILE, "rb") as stream:
                st = os.fstat(stream.fileno())
                rev = (st.st_ino, st.st_mtime_ns, datetime.now(ZoneInfo("Europe/Paris")).date())
                if rev != cached.get("revision") and time.monotonic() >= cached.get("next_read", 0):
                    rows = feed(host, ijson.items(stream, "sessions.item"))
                    cached.update(revision=rev, rows=rows, next_read=time.monotonic()+10)
            response = jsonify(version=1, sessions=cached["rows"])
            response.headers["Cache-Control"] = "private, no-store"
            return response
