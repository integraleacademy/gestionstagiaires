"""Attach the planning catalogue to the academy's administrative sessions."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hmac
import logging
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
         "ssiap-3": "SSIAP 3", "desp-dssp": "DIRIGEANT initial", "afc": "APS", "general": "Général"}
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
    elif kind == "general" and training.get(STATE):
        slug = "general"
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
    if not same_group(a, b):
        return False
    starts = {b.get("start"), b.get("standard_start")} if b["slug"] == "ssiap-1" else {b.get("start")}
    return sum((bool(a.get("start")) and a["start"] in starts, bool(a.get("end")) and a["end"] == b.get("end"),
                bool(a.get("exam")) and a["exam"] == b.get("exam"))) >= 2


def overlaps(a, b):
    return same_group(a, b) and all(x.get(k) for x in (a, b) for k in ("start", "end")) and a["start"] <= b["end"] and b["start"] <= a["end"]


def own(host, training):
    return training.get("partner_id") in (None, "", host.INTEGRALE_PARTNER_ID) and not host._is_wedof_leads_session(training)


def signature(row):
    return {k: row.get(k, "") for k in (*FIELDS, "standard_start")}


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
    candidates = [(s, key) for s, key in candidates if not s.get(STATE)]
    keys = [row, *row.get("aliases", [])]
    matches = [s for s, key in candidates if not s.get("archived") and any(correspondence(key, k) for k in keys)]
    if len(matches) == 1 and not matches[0].get(STATE):
        return matches[0]
    if row.get("deleted"):
        return None
    if matches or any(not s.get("archived") and not s.get(STATE) and any(overlaps(key, k) for k in keys) for s, key in candidates):
        raise ValueError("Dates proches ou plusieurs fiches possibles. Précisez la fiche Gestion Stagiaires dans Plateforme Gestion.")
    return None


def projected_ssiap_settings(host, row, training, previous, new_start):
    config = host.ssiap_pathways.settings({**training, "date_start": new_start, "date_end": row["end"]})
    old_source = previous.get("source", {})
    old_start = old_source.get("standard_start") or old_source.get("start")
    if old_start and old_start != new_start:
        offset = date.fromisoformat(new_start) - date.fromisoformat(old_start)
        original = host.ssiap_pathways.settings(training)
        for field in ("recyclage_dates", "remise_a_niveau_dates", "sst_dates"):
            days = original.get(field, [])
            if days:
                config[field] = [(date.fromisoformat(d) + offset).isoformat() for d in days]
    return config


def updates(host, row, training, previous):
    result = dict(date_start=row["start"], date_end=row["end"], crm_center=CITIES.get(row["centre"], ""),
                  exam_date=row["exam"])
    if previous.get("id") == row["id"] and row.get("edited"):
        # A saved change to this linked session is the administrator's scheduling decision.
        # The native editor keeps WeDoF references and external dates independently.
        result["confirm_wedof_date_change"] = True
    if row["slug"] == "ssiap-1":
        new_start = row.get("standard_start") or row["start"]
        result["date_start"] = new_start
        config = projected_ssiap_settings(host, row, training, previous, new_start)
        if row.get("standard_start"):
            first = date.fromisoformat(row["start"])
            gap = (date.fromisoformat(new_start) - first).days
            days = [first + timedelta(days=i) for i in range(gap)] if 0 < gap <= 7 else []
            sst = [d.isoformat() for d in days if d.weekday() < 5]
            if len(sst) == 2 and (not config["sst_dates"] or previous or config["sst_dates"] == sst):
                config["sst_dates"] = sst
        if host.ssiap_pathways.enabled(training) or config["sst_dates"]:
            result["ssiap_pathways"] = config
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
    if row.get("name"):
        result["name"] = row["name"]
    elif previous.get("generated_name") and training.get("name") == previous["generated_name"]:
        result["name"] = label(row)
    return result


def label(row):
    if row.get("name"):
        return row["name"]
    kind = "AFC France Travail APS + SSIAP 1" if row["slug"] == "afc" else TYPES[row["slug"]]
    return f"{kind} · {CITIES.get(row['centre'], '')} · {row['start'][8:]}/{row['start'][5:7]}/{row['start'][:4]}"


class NoChange(Exception):
    pass


def withdrawn(training):
    return bool(training.get("catalogue_mask") or training.get(STATE, {}).get("source", {}).get("deleted"))


def archive(host, training, state):
    if not training.get("archived"):
        training.update(archived=True, archived_at=host._now_iso())
        state["archived_by_catalogue"] = True


def reconcile(host, data, rows, present_ids=None):
    trainings = data.setdefault("sessions", [])
    candidates = [(s, local_identity(host, s)) for s in trainings if not s.get("catalogue_mask") and own(host, s)]
    masks = {s[STATE]["id"]: s for s in trainings if s.get("catalogue_mask")}
    conflicts, changed = [], False
    # Withdraw first. An administrator can delete and recreate an offer with the
    # same dates between two refreshes. Each record must keep its own enrolments.
    present = set(present_ids) if present_ids is not None else {r["id"] for r in rows}
    for training, _ in candidates:
        state = training.get(STATE)
        if state and state["id"] not in present and (not withdrawn(training) or not training.get("archived")):
            if present_ids is None:
                if state["source"]["visibility"] != "closed":
                    state["source"] = {**state["source"], "visibility": "closed"}
                    changed = True
                continue
            state["source"] = {**state["source"], "visibility": "closed", "deleted": True}
            archive(host, training, state)
            changed = True
    for sid, mask in masks.items():
        source = mask[STATE]["source"]
        if present_ids is not None and sid not in present and not source.get("deleted"):
            source["deleted"] = True
            changed = True
    for row in sorted(rows, key=lambda item: not item.get("deleted", False)):
        training = None
        try:
            if not row["centre"] and row["visibility"] != "closed" and not row.get("unscheduled"):
                raise ValueError("Renseignez le centre dans Plateforme Gestion.")
            training = choose(row, candidates)
            if training is None and row["visibility"] == "closed" and not row.get("deleted"):
                continue
            previous = training.get(STATE, {}) if training else {}
            if training and row["id"] in masks:
                trainings.remove(masks.pop(row["id"]))
                changed = True
            if (training and previous.get("source") == row
                    and (not row.get("name") or training.get("name") == row["name"])
                    and (row["visibility"] != "closed" or training.get("archived"))):
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
            # Only the scheduling fields are shared. Run normal date protections
            # for enrolled trainees and for sessions already linked to WeDoF.
            if row["visibility"] != "closed":
                draft = deepcopy(training)
                if previous.get("archived_by_catalogue"):
                    draft["archived"] = False
                    draft.pop("archived_at", None)
                draft["training_type"] = TYPES[row["slug"]]
                if row.get("unscheduled"):
                    draft.update(name=label(row), date_start=row["start"], date_end=row["end"],
                                 exam_date=row["exam"], crm_center=CITIES.get(row["centre"], ""))
                else:
                    projection = updates(host, row, draft, previous)
                    check = host._apply_session_update({**data, "sessions": [draft]}, draft["id"], projection, from_catalogue=True)
                    response, status = check if isinstance(check, tuple) else (check, 200)
                    if status != 200:
                        raise ValueError(response.get_json().get("error", "Vérifiez les dates de la fiche."))
                if row.get("edited"):
                    draft["date_start"] = (row.get("standard_start") or row["start"]) if row["slug"] == "ssiap-1" else row["start"]
                    draft["date_end"] = row["end"]
                    draft["exam_date"] = row["exam"]
                for legacy, canonical in (("nom", "name"), ("date_debut", "date_start"), ("date_fin", "date_end"),
                                          ("date_examen", "exam_date"), ("type_formation", "training_type")):
                    if legacy in draft:
                        draft[legacy] = draft.get(canonical, "")
                training.update(draft)
                if not draft.get("archived"):
                    training.pop("archived_at", None)
            elif row.get("name"):
                training["name"] = row["name"]
            generated = training["name"] if new or previous.get("generated_name") else ""
            training[STATE] = dict(id=row["id"], source=row, aliases=aliases, generated_name=generated)
            if row["visibility"] == "closed":
                if previous.get("archived_by_catalogue"):
                    training[STATE]["archived_by_catalogue"] = True
                archive(host, training, training[STATE])
            if row["id"] in masks:
                trainings.remove(masks.pop(row["id"]))
            if new:
                trainings.insert(0, training)
                candidates.append((training, signature(row)))
            changed = True
        except ValueError as exc:
            if training is not None and training.get(STATE, {}).get("id") == row["id"]:
                state = training[STATE]
                if row.get("name") and training.get("name") != row["name"]:
                    training["name"] = row["name"]
                    changed = True
                metadata = {k:row[k] for k in ("name", "custom_name", "gestion_only", "visibility", "capacity", "venue") if k in row}
                safe = {**state["source"], **metadata}
                if safe != state["source"]:
                    state["source"] = safe
                    changed = True
            elif row.get("gestion_only") or row["visibility"] in ("closed", "internal"):
                # Hide former calendar offers even when multiple legacy rosters require manual attachment.
                source = {**row, "visibility": "closed"}
                mask = masks.get(row["id"])
                if mask is None:
                    mask = dict(id="catalogue-mask-" + row["id"], catalogue_mask=True, archived=True,
                                partner_id=host.INTEGRALE_PARTNER_ID, training_type=TYPES[row["slug"]], trainees=[])
                    trainings.append(mask)
                    masks[row["id"]] = mask
                state = dict(id=row["id"], source=source, aliases=row.get("aliases", []))
                if mask.get(STATE) != state:
                    mask[STATE] = state
                    changed = True
            conflicts.append({**signature(row), "id": row["id"], "reason": str(exc)})
    if data.get("session_catalogue_conflicts", []) != conflicts:
        data["session_catalogue_conflicts"] = conflicts
        changed = True
    if not changed:
        raise NoChange(len(conflicts))
    return {"conflicts": len(conflicts)}


def feed(host, trainings):
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    result = []
    for training in trainings:
        if not own(host, training):
            continue
        state = training.get(STATE, {})
        row = dict(state.get("source") or local_identity(host, training))
        aliases = state.get("aliases", [])
        if row.get("unscheduled"):
            anchor = next((key for key in reversed(aliases) if key.get("start") and key.get("end")), None)
            if anchor:
                row.update(anchor, visibility="closed")
        if not row.get("start") or not row.get("end") or not row.get("slug"):
            continue
        if max([row["end"], *(k.get("end", "") for k in aliases)]) < today:
            continue
        if not state and (row["slug"] == "afc" or training.get("archived") or training.get("exclude_from_sales_tracking")):
            continue
        if training.get("archived") or row.get("gestion_only"):
            row["visibility"] = "closed"
        # Only enumerated schedule fields and aggregate sales leave the service.
        entry = {**{k: row.get(k, "") for k in (*FIELDS, "standard_start", "remote_start", "remote_end", "onsite_start", "onsite_end")},
                       "id": "platform-" + state["id"] if state else "gestion-" + str(training["id"]),
                       "visibility": row.get("visibility", "match"), "aliases": aliases,
                       "deleted": bool(row.get("deleted")), "managed": bool(state), "edited": bool(row.get("edited")),
                       "name": row.get("name", "") if row.get("custom_name") and row.get("visibility") not in ("closed","internal") else "",
                       "venue": row.get("venue", "") if row.get("visibility") not in ("closed","internal") else "",
                       "capacity": row.get("capacity") if state else None, "sold": len(host._registered_trainees(training))}
        result.append(entry)
        ssiap_periods = [k for k in [row, *aliases] if k.get("slug") == "ssiap-1" and k.get("start") and k.get("end")]
        if ssiap_periods:
            current_ssiap = row["slug"] == "ssiap-1"
            options = host.ssiap_pathways.settings(training) if current_ssiap else {}
            for path, code in (("recyclage", "recyclage-ssiap-1"), ("remise_a_niveau", "remise-a-niveau-ssiap-1")):
                days = sorted(options.get(path + "_dates", []))
                periods = [{k: period[k] for k in ("centre", "start", "end")} for period in ssiap_periods]
                result.append({**entry, "id": entry["id"] + "-" + path, "slug": code, "exam": "", "standard_start": "",
                               "start": days[0] if days else ssiap_periods[0]["start"], "end": days[-1] if days else ssiap_periods[0]["end"],
                               "deleted": entry["deleted"] or not current_ssiap,
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
        if (not row.get("start") or not row.get("end")) and row.get("unscheduled") is not True:
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
                    payload = reply.json()
                    rows = validate(payload)
                    present_ids = payload.get("present_ids")
                    if present_ids is not None and (not isinstance(present_ids, list) or not all(isinstance(sid, str) for sid in present_ids)):
                        raise ValueError("Liste des sessions de planning invalide")
                    result = {}
                    with host.app.app_context():
                        try:
                            def apply(current):
                                stats = reconcile(host, current, rows, present_ids)
                                linked = [s for s in current["sessions"] if s.get(STATE) and not s.get("catalogue_mask")]
                                stats["withdrawn"] = sum(withdrawn(s) and bool(s.get("archived")) for s in linked)
                                stats["names"] = sum(bool(s[STATE]["source"].get("name")) and
                                                     s.get("name") == s[STATE]["source"]["name"] for s in linked if not withdrawn(s))
                                return stats
                            result = host._atomic_update_data(apply)
                            logging.getLogger("gunicorn.error").info(
                                "Calendrier appliqué : %d entrées, %d noms conformes, %d retraits archivés, %d conflits.",
                                len(rows), result["names"], result["withdrawn"], result["conflicts"])
                        except NoChange as stable:
                            result = {"conflicts": stable.args[0]}
                    etag = reply.headers.get("ETag", "") if not result.get("conflicts") else ""
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
