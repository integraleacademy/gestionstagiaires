"""Verified, read-only CRM details on the existing EDOF browser session."""
from decimal import Decimal, InvalidOperation
import json
import re
import time
from urllib.parse import urlsplit

import edof_directory as directory
import edof_dossier_dates as dates

DAY = 86400


def scalar(value, limit=250):
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value).strip()[:limit]
    return ""


def number(value):
    try:
        n = Decimal(scalar(value).replace(",", "."))
        return format(n, "f") if n.is_finite() and 0 <= n <= 100000000 and n.as_tuple().exponent >= -8 and n.adjusted() < 10 else ""
    except InvalidOperation:
        return ""


def address(value):
    if not isinstance(value, dict):
        return scalar(value)
    return " ".join(filter(None, (scalar(value.get(k)) for k in (
        "number", "repetitionIndex", "roadType", "roadName", "streetAddress", "additionalAddress", "zipCode", "postalCode", "city"))))


def project(raw, row, now):
    verified = directory.project(raw)
    if verified["folder_id"] != row["folder_id"] or any(
        not row.get(k) or directory.normalized(row[k]) != directory.normalized(verified[k])
        for k in ("first_name", "last_name")
    ):
        return None
    action = raw.get("trainingActionInfo") or {}
    person = raw.get("attendee") or {}
    info = {k: number(action.get(k)) for k in (
        "totalIncl", "totalExcl", "indicativeDuration", "weeklyDuration", "hoursInCenter",
        "hoursInCompany", "teachingFees", "additionalFees", "montantFraisCertificationInclus")}
    # In unprocessed requests the DTO may initialize the total to zero while
    # retaining the tax-inclusive components of the offer.
    breakdown = [number(action.get(k)) for k in ("vat", "vatInclTax5", "vatInclTax20")]
    if not Decimal(info["totalIncl"] or 0) and any(Decimal(v or 0) > 0 for v in breakdown):
        info["totalIncl"] = str(sum(Decimal(v or 0) for v in breakdown))
    info.update({k: scalar(action.get(k), 5000) for k in ("trainingGoal", "expectedResult", "content", "conditionsPrerequisitesDetails")})
    info["address"] = address(action.get("address"))
    modality = scalar(action.get("teachingModalities"))
    info["teachingModalities"] = {"0":"Présentiel", "1":"Mixte", "2":"À distance"}.get(modality, modality)
    cert = raw.get("certification")
    cert = cert if isinstance(cert, dict) else {"name":scalar(cert) if isinstance(cert, str) else ""}
    qualification = {"name":scalar(action.get("intituleRNCP") or cert.get("name") or cert.get("title"), 600),
                     "externalId":scalar(action.get("codeRNCP") or cert.get("externalId")),
                     "certifInfo":scalar(cert.get("certifInfo")), "recognitionCode":scalar(raw.get("codeReconnaissance")),
                     "referenceCode":scalar(raw.get("codeReferentiel"))}
    if not qualification["externalId"] and re.fullmatch(r"(?:RNCP|RS)\s*\d+", scalar(raw.get("codeReferentiel")), re.I):
        qualification["externalId"] = scalar(raw["codeReferentiel"])
    learner = {k:scalar(person.get(k)) for k in ("email", "phoneNumber", "phoneFixed", "degreeTitle")}
    learner.update(firstName=verified["first_name"], lastName=verified["last_name"],
                   dateOfBirth=dates.stamp(person.get("birthDate")), fullAddress=address(person.get("completeAdress") or person.get("address")))
    events = list(dates.from_history(raw, lambda s: re.sub(r"Date$", "", s)))
    if verified.get("filed_at") and not any(d == verified["filed_at"] and directory.normalized(s) in directory.REQUEST_STATES for s,d in events):
        events.append(("Demande déposée", verified["filed_at"]))
    if verified.get("state_at") and verified.get("state"):
        events.append((verified["state"], verified["state_at"]))
    result = {"readAt":now, "attendee":{k:v for k,v in learner.items() if v},
              "trainingActionInfo":{k:v for k,v in info.items() if v != ""},
              "certification":{k:v for k,v in qualification.items() if v},
              "history":[{"state":s,"date":d} for s,d in dict.fromkeys(events)][:100]}
    files = next((raw[k] for k in ("files","documents","attachments") if isinstance(raw.get(k),list)), None)
    if files is not None:
        # Signed downloads and portal credentials must stay inside EDOF.
        result["files"] = [{"name":name} for item in files[:100] if isinstance(item,dict)
                           if (name := scalar(item.get("name") or item.get("filename") or item.get("label")))]
    return result


def record_key(owner, folder):
    return f"crm-edof-detail:{owner}:{folder}"


def queue_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS crm_detail_queue (
        owner TEXT NOT NULL, folder TEXT NOT NULL, priority INTEGER NOT NULL, requested REAL NOT NULL,
        attempted REAL NOT NULL DEFAULT 0, checked REAL NOT NULL DEFAULT 0, PRIMARY KEY(owner,folder))""")


def request_read(private, owner, folder):
    with private.connect() as db:
        queue_table(db)
        db.execute("""INSERT INTO crm_detail_queue(owner,folder,priority,requested) VALUES(?,?,1,?)
            ON CONFLICT(owner,folder) DO UPDATE SET priority=1,requested=excluded.requested""",
                   (owner,folder,time.time()))


def known_details(private, owner):
    prefix = record_key(owner, "")
    with private.connect() as db:
        return {name[len(prefix):] for name, in db.execute("SELECT name FROM private_records WHERE name GLOB ?", (prefix+"*",))}


def fill(context, witness, private, owner, pending, origin, prefix):
    # The caller has just completed a verified directory poll. Never start
    # authentication or follow a redirect to satisfy a CRM detail request.
    if not witness or witness.method != "GET":
        return []
    source = urlsplit(witness.url)
    workspace = f"/edof-api/v1/api/private/siret/{directory.SIRET}/"
    if source.scheme != "https" or source.netloc != origin or not source.path.startswith(workspace) or prefix != workspace+"organisms/current/registration-folders/":
        return []
    now = time.time()
    with private.connect() as db:
        queue_table(db)
        db.execute("DELETE FROM crm_detail_queue WHERE owner=? AND requested<?", (owner, now-30*DAY))
        db.executemany("""INSERT INTO crm_detail_queue(owner,folder,priority,requested) VALUES(?,?,0,?)
            ON CONFLICT(owner,folder) DO UPDATE SET requested=excluded.requested""",
                       ((owner,folder,now) for folder in pending if directory.ID_RE.fullmatch(folder)))
        folders = [r[0] for r in db.execute("""SELECT folder FROM crm_detail_queue WHERE owner=? AND checked<?
            AND attempted<? AND (priority=1 OR requested=?) ORDER BY priority DESC,attempted,folder LIMIT 2""",
                                            (owner,now-DAY,now-600,now))]
    rows = pending
    if any(folder not in rows for folder in folders):
        full = private.get(directory.record_key(owner), keep=True)
        combined = directory.with_accepted(directory.with_pending(full, {"rows":pending, "checked":now}), private.get(directory.accepted_key(owner)))
        rows = (combined or {}).get("rows", {})
    reads = []
    for folder in folders:
        with private.connect() as db:
            db.execute("UPDATE crm_detail_queue SET attempted=? WHERE owner=? AND folder=?", (now,owner,folder))
        if folder not in rows or not directory.ID_RE.fullmatch(folder):
            continue
        target = "https://" + origin + prefix + folder
        headers = {**directory.private_headers(witness), "Current-Siret":directory.SIRET}
        reply = context.request.get(target, headers=headers, max_redirects=0, timeout=5500)
        try:
            directory.check_throttling(reply)
            if reply.url != target or reply.status != 200:
                continue
            body = reply.body()
            if len(body) > 2_000_000:
                continue
            detail = project(json.loads(body), rows[folder], time.time())
        finally:
            reply.dispose()
        if detail:
            private.put(record_key(owner, folder), detail, ttl=30*DAY)
            with private.connect() as db:
                db.execute("UPDATE crm_detail_queue SET checked=?,priority=0 WHERE owner=? AND folder=?", (now,owner,folder))
            info = detail["trainingActionInfo"]
            reads.append({"folder":folder, "price":bool(Decimal(info.get("totalIncl") or 0)),
                          "duration":bool(Decimal(info.get("indicativeDuration") or 0)),
                          "contact":bool(detail["attendee"].get("email") or detail["attendee"].get("phoneNumber")),
                          "certification":bool(detail["certification"]), "events":len(detail["history"])})
    return reads
