"""Manual proposal delivery, with separate durable fences for the edit and the validation."""
from contextlib import closing
import json
import secrets
import time
import uuid
from urllib.parse import urlsplit

from cpf_provider import ProviderStore
import edof_automation_audit as audit
import edof_directory as directory
import edof_dispatch as dispatch
import edof_proposal as form

PENDING = {"notprocessed","not processed","tobeprocessed","to be processed","a traiter","received","non traite","dossier non traite"}
WAITING = {"validated","waitingacceptation","en attente de validation du titulaire"}
ADVANCED = {"accepted","accepte","intraining","terminated","servicedonedeclared","servicedonevalidated","billed","paid"}
BUSY = {"queued","saving","validating","checking","uncertain"}
LEGACY_READ_MESSAGE = "La réponse du dossier n’a pas été reçue. La lecture autonome reste à valider."
MESSAGES = {
    "proposal_read_unavailable":"EDOF n’a pas renvoyé les conditions de ce dossier. Vous pouvez relire l’offre depuis sa fiche.",
    "proposal_folder_missing":"EDOF ne trouve plus ce numéro de dossier pour cet établissement.",
    "proposal_response_invalid":"Le contenu renvoyé par EDOF pour ce dossier est incomplet.",
    "proposal_loaded":"Les conditions de l’offre EDOF ont été chargées.",
    "proposal_confirmed":"Proposition envoyée au titulaire et confirmée par EDOF.",
    "proposal_changed":"Le dossier a changé dans EDOF. Rechargez ses conditions avant de valider.",
    "proposal_refused":"EDOF a refusé la proposition.",
    "proposal_uncertain":"Réception à vérifier. Relisez le dossier avant toute nouvelle transmission.",
    "proposal_resume":"La demande reste à traiter. Vérifiez les conditions relues dans EDOF avant de reprendre la validation.",
}
LABELS = {"queued":"Préparation de la transmission", "saving":"Enregistrement des conditions dans EDOF",
          "validating":"Envoi de la proposition au titulaire", "checking":"Vérification de la réception",
          "confirmed":"Envoi confirmé par EDOF", "error":"Envoi à reprendre", "uncertain":"Réception à vérifier"}


def database(path):
    db = ProviderStore(path).connect()
    db.execute("""CREATE TABLE IF NOT EXISTS inscription_proposals(
        folder TEXT PRIMARY KEY, owner TEXT NOT NULL, token TEXT NOT NULL, revision INTEGER NOT NULL,
        signature TEXT NOT NULL, terms TEXT NOT NULL, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
        status TEXT NOT NULL, phase TEXT NOT NULL DEFAULT '', updated REAL NOT NULL, message TEXT NOT NULL DEFAULT '',
        receipt TEXT)""")
    if "result_code" not in {r[1] for r in db.execute("PRAGMA table_info(inscription_proposals)")}:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if "result_code" not in {r[1] for r in db.execute("PRAGMA table_info(inscription_proposals)")}:
                db.execute("ALTER TABLE inscription_proposals ADD COLUMN result_code TEXT NOT NULL DEFAULT ''")
                db.execute("UPDATE inscription_proposals SET result_code='portal_throttled' WHERE message LIKE 'EDOF ou EFP limite les requêtes.%'")
    db.execute("""CREATE TABLE IF NOT EXISTS proposal_reads (
        owner TEXT NOT NULL, folder TEXT NOT NULL, token TEXT NOT NULL, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
        status TEXT NOT NULL, updated REAL NOT NULL, message TEXT NOT NULL DEFAULT '', PRIMARY KEY(owner,folder))""")
    audit.install_proposals(db)
    return db


def request_read(path,owner,row):
    with closing(database(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT token,status,updated FROM proposal_reads WHERE owner=? AND folder=?", (owner,row["folder_id"])).fetchone()
        if old and old["status"] in {"queued","reading"} and time.time()-old["updated"] < 600:
            return old["token"]
        token = secrets.token_hex(16)
        db.execute("""INSERT OR REPLACE INTO proposal_reads VALUES(?,?,?,?,?,'queued',?,'')""",
                   (owner,row["folder_id"],token,row["first_name"],row["last_name"],time.time()))
        return token


def read_ticket(path, owner, folder, token):
    with closing(database(path)) as db:
        return db.execute("SELECT status,message FROM proposal_reads WHERE owner=? AND folder=? AND token=?",
                          (owner,folder,token)).fetchone()


def reading(path, spec):
    with closing(database(path)) as db, db:
        return db.execute("UPDATE proposal_reads SET status='reading',updated=? WHERE token=? AND status='queued'",
                          (time.time(),spec["token"])).rowcount==1


def finish_read(path,spec,note):
    with closing(database(path)) as db, db:
        db.execute("UPDATE proposal_reads SET status='finished',updated=?,message=? WHERE token=?", (time.time(),note,spec["token"]))


def read_failure_message(phase):
    if phase == "validating":
        return "L’envoi a été lancé. EDOF n’a pas confirmé sa réception. Cliquez sur « Vérifier la réception dans EDOF » avant tout nouvel envoi."
    if phase == "saving":
        return "La proposition n’a pas été envoyée au titulaire. Cliquez sur « Vérifier la réception dans EDOF » pour savoir si les modifications ont été enregistrées."
    return "Aucune proposition envoyée. L’application n’a pas pu relire le dossier avant l’envoi. Vous pouvez relancer la transmission depuis cette fiche."


def record(path, folder, owner):
    with closing(database(path)) as db:
        row = db.execute("SELECT * FROM inscription_proposals WHERE folder=? AND owner=?", (folder,owner)).fetchone()
    if not row:
        return None
    message = row["message"]
    if message == LEGACY_READ_MESSAGE:
        message = read_failure_message(row["phase"])
    return {**dict(row),"message":message,"terms":json.loads(row["terms"])}


def enqueue(path, owner, revision, row, source, values):
    with closing(database(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT status FROM inscription_proposals WHERE folder=?", (row["folder_id"],)).fetchone()
        if old and old[0] in BUSY | {"confirmed"}:
            return old[0]
        db.execute("""INSERT OR REPLACE INTO inscription_proposals(folder,owner,token,revision,signature,terms,first_name,last_name,
                   status,updated) VALUES(?,?,?,?,?,?,?,?,'queued',?)""",
                   (row["folder_id"],owner,secrets.token_hex(16),revision,source["signature"],json.dumps(values),
                    row["first_name"],row["last_name"],time.time()))
    dispatch.wake(path)
    return "queued"


def recheck(path, folder, owner):
    with closing(database(path)) as db, db:
        db.execute("""UPDATE inscription_proposals SET status='checking',updated=? WHERE folder=? AND owner=?
                   AND status='uncertain'""", (time.time(),folder,owner))
    dispatch.wake(path)


def next_job(path, selection):
    with closing(database(path)) as db, db:
        db.execute("""UPDATE inscription_proposals SET status='error',message='Le système CPF actif a changé.'
                   WHERE status='queued' AND (revision!=? OR ?!='integrale')""",(selection["revision"],selection["provider"]))
        db.execute("""UPDATE inscription_proposals SET status='error',message='Le connecteur est resté indisponible. Vérifiez la connexion puis renouvelez votre envoi.'
                   WHERE status='queued' AND updated<?""",(time.time()-1800,))
        db.execute("DELETE FROM proposal_reads WHERE updated<?", (time.time()-86400,))
        db.execute("""UPDATE proposal_reads SET status='finished',message='Lecture interrompue ou connecteur indisponible. Relancez la lecture.'
                   WHERE status IN ('queued','reading') AND updated<?""",(time.time()-600,))
        # A worker that disappeared after crossing a fence may only re-read the folder.
        db.execute("""UPDATE inscription_proposals SET status='checking' WHERE status IN ('saving','validating') AND updated<?""",
                   (time.time()-420,))
        r = db.execute("""SELECT * FROM inscription_proposals WHERE status IN ('queued','checking') ORDER BY updated LIMIT 1""").fetchone()
        if not r:
            read = db.execute("SELECT * FROM proposal_reads WHERE status='queued' ORDER BY updated LIMIT 1").fetchone()
            if not read:
                return None
            return {"mode":"proposal_read","folder_id":read["folder"],"owner":read["owner"],"token":read["token"],
                    "first_name":read["first_name"],"last_name":read["last_name"]}
        return {"mode":"proposal_check" if r["status"]=="checking" else "proposal_send","folder_id":r["folder"],
                "owner":r["owner"],"first_name":r["first_name"],"last_name":r["last_name"],"token":r["token"],"revision":r["revision"]}


def fence(path, spec, phase):
    with closing(database(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        selected = ProviderStore(path).state(db)
        if selected["provider"] != "integrale" or selected["pending"] or selected["revision"] != spec["revision"]:
            return False
        previous = ("queued",) if phase=="saving" else ("queued","saving")
        return db.execute(f"""UPDATE inscription_proposals SET status=?,phase=?,updated=?
                       WHERE token=? AND owner=? AND folder=? AND status IN ({','.join('?' for _ in previous)})""",
                       (phase,phase,time.time(),spec["token"],spec["owner"],spec["folder_id"],*previous)).rowcount==1


def complete(path, spec, result, message):
    code = result["code"]
    with closing(database(path)) as db, db:
        r = db.execute("SELECT * FROM inscription_proposals WHERE token=?", (spec["token"],)).fetchone()
        if not r or r["status"] in {"confirmed","error"}:
            return
        if code in {"read_unconfirmed", "proposal_read_unavailable"}:
            message = read_failure_message(r["phase"])
        receipt = result.get("proposal_receipt")
        if code=="proposal_confirmed" and receipt and receipt["folder_id"] == r["folder"]:
            state = "confirmed"
        elif code in {"proposal_refused","proposal_changed","proposal_resume"}:
            state = "error"
        else:
            state = "uncertain" if r["phase"] else "error"
        db.execute("UPDATE inscription_proposals SET status=?,message=?,receipt=?,updated=?,result_code=? WHERE token=?",
                   (state,message,json.dumps(receipt) if state=="confirmed" else None,time.time(),code,r["token"]))


def with_receipts(path, owner, snap):
    with closing(database(path)) as db:
        receipts = db.execute("SELECT receipt,updated FROM inscription_proposals WHERE owner=? AND status='confirmed' AND updated>?",
                              (owner,time.time()-directory.TTL)).fetchall()
    if not receipts:
        return snap
    combined = dict(snap or {"rows":{},"checked":0})
    rows, pending = dict(combined["rows"]), set(combined.get("pending_ids", ()))
    for r in receipts:
        row = json.loads(r["receipt"])
        folder = row["folder_id"]
        before = rows.get(folder)
        if before and directory.normalized(before.get("state") or "") not in PENDING:
            continue
        if not before and combined.get("scope")=="all" and combined["checked"] > r["updated"]:
            continue
        if before and not row.get("filed_at"):
            row["filed_at"] = before.get("filed_at") or before.get("state_at") or before.get("request_date") or ""
        if before and before.get("created_at") and not row.get("created_at"):
            row["created_at"] = before["created_at"]
        rows[folder] = {**row, "observed_at": r["updated"]}
        pending.discard(folder)
    if "pending_ids" in combined:
        combined["pending_ids"] = pending
    return {**combined,"rows":rows,"receipt_checked":max(r["updated"] for r in receipts)}


def source_key(owner, folder):
    return "edof-proposal-form:"+owner+":"+folder


def option_key(owner):
    return "edof-proposal-options:"+owner


def same_terms(left, right):
    return all(((left.get(k) or "0") == (v or "0")) if k in (*form.HOURS,*form.PRICES) else left.get(k) == v
               for k,v in right.items())


def remember_own_edit(vault, owner, folder, source, signature):
    """Advance the form baseline only after our exact edit was read back from EDOF."""
    vault.put(source_key(owner,folder), source, ttl=86400)
    key = "proposal-draft:"+owner+":"+folder
    draft = vault.get(key)
    if draft and draft.get("signature") == signature:
        vault.put(key, {**draft,"signature":source["signature"]}, ttl=86400)


class FolderUnavailable(Exception):
    pass


class FolderIdentityMismatch(Exception):
    pass


def perform(context, witness, spec, path, vault, prefix, origin, *, workspace_witness=False):
    """Use only the two fixed same-establishment PUTs used by the official portal."""
    from playwright.sync_api import Error as BrowserError
    folder = spec["folder_id"]
    target = "https://"+origin+prefix+folder
    if not directory.ID_RE.fullmatch(folder) or not witness or witness.method != "GET":
        return {"code":"identity_mismatch"}
    if witness.url != target:
        url = urlsplit(witness.url)
        trusted_prefix = f"/edof-api/v1/api/private/siret/{directory.SIRET}/"
        if not (workspace_witness and (url.scheme, url.netloc) == ("https", origin)
                and url.path.startswith(trusted_prefix)):
            return {"code":"identity_mismatch"}
    headers = directory.private_headers(witness)
    version = None

    def call(method, url, payload=None):
        nonlocal version
        request_headers = {**headers, "X-RequestID":str(uuid.uuid4())}
        if method=="put":
            request_headers["Current-Siret"] = directory.SIRET
            if url == target and version:
                request_headers["If-Match"] = version
        arguments = dict(headers=request_headers,max_redirects=0,timeout=12000)
        if payload is not None:
            arguments["data"] = payload
        reply = getattr(context.request, method)(url, **arguments)
        try:
            directory.check_throttling(reply)
            if reply.url != url or len(reply.body()) > 2_000_000:
                raise ValueError("Réponse EDOF non reconnue.")
            try:
                data = reply.json()
            except ValueError:
                data = {}
            if method=="get" and url==target:
                version = (getattr(reply,"headers",{}) or {}).get("etag")
            return reply.status, data
        finally:
            reply.dispose()

    def fresh():
        status, raw = call("get", target)
        if status != 200 or not isinstance(raw,dict):
            raise FolderUnavailable(status)
        row = directory.project(raw)
        if row["folder_id"] != folder or any(not row[k] or directory.normalized(row[k]) != directory.normalized(spec[k])
                                               for k in ("first_name","last_name")):
            raise FolderIdentityMismatch()
        try:
            source = form.project(raw)
        except form.InvalidTerms as exc:
            # A malformed official response is not a refusal of a submitted offer.
            raise ValueError("Conditions EDOF illisibles.") from exc
        return raw,row,source

    def reject(status, body):
        if status == 412:
            return {"code":"proposal_changed"}
        if status in {400,403,409,422}:
            explanation = body.get("message") if isinstance(body,dict) else None
            return {"code":"proposal_refused","proposal_message":directory.text_field(explanation,350)}
        return {"code":"proposal_uncertain"}

    # Only this first GET may fall back to reopening the portal. Once a write
    # has begun, its durable phase must go through read-only reconciliation.
    try:
        raw,row,source = fresh()
    except FolderUnavailable as exc:
        return {"code":"proposal_folder_missing" if exc.args == (404,) else "proposal_read_unavailable"}
    except (BrowserError, OSError):
        return {"code":"proposal_read_unavailable"}
    state = directory.normalized(row["state"])
    options = vault.get(option_key(spec["owner"])) or {}
    if spec["mode"]=="proposal_read":
        if state not in PENDING:
            return {"code":"proposal_changed"}
        for key,slug in form.ENUMS.items():
            if options.get(key):
                continue
            status, items = call("get", f"https://{origin}/edof-api/v1/api/public/{slug}")
            if status==200 and isinstance(items,list):
                options[key] = {form.scalar(i.get("code")):directory.text_field(i.get("label"),180)
                                for i in items if isinstance(i,dict) and i.get("code") is not None}
        # Some gateways only serve lists under an authenticated session. Existing official codes remain usable.
        options["teachingModalities"] = options.get("teachingModalities") or {"0":"Présentiel","1":"Mixte","2":"À distance"}
        vault.put(option_key(spec["owner"]), options, ttl=86400)
        vault.put(source_key(spec["owner"],folder), source, ttl=86400)
        return {"code":"proposal_loaded"}

    job = record(path,folder,spec["owner"])
    if not job or job["token"] != spec["token"]:
        return {"code":"proposal_changed"}
    terms = job["terms"]
    def confirmed(row, source):
        return (directory.normalized(row["state"]) in WAITING|ADVANCED and same_terms(source["values"],terms))
    if confirmed(row,source):
        return {"code":"proposal_confirmed","proposal_receipt":row}
    if spec["mode"]=="proposal_check":
        if state in PENDING and job["phase"]=="saving":
            vault.put(source_key(spec["owner"],folder),source,ttl=86400)
            return {"code":"proposal_resume"}
        return {"code":"proposal_uncertain"}
    if state not in PENDING or job["status"]!="queued":
        return {"code":"proposal_changed"}
    if source["signature"]!=job["signature"] and not same_terms(source["values"],terms):
        return {"code":"proposal_changed"}
    terms=form.validate(terms,source,options)
    if not same_terms(source["values"],terms):
        payload=form.amended(raw,terms,options)
        if not fence(path,spec,"saving"):
            return {"code":"proposal_changed"}
        status,body=call("put",target,payload)
        if not 200<=status<300:
            return reject(status,body)
        raw,row,source=fresh()
        if directory.normalized(row["state"]) not in PENDING or not same_terms(source["values"],terms):
            return {"code":"proposal_changed"}
        remember_own_edit(vault,spec["owner"],folder,source,job["signature"])
    if raw.get("ableToValidate") is False:
        return {"code":"proposal_refused","proposal_message":"Le dossier n’est pas validable selon EDOF. Vérifiez les dates et l’éligibilité de l’offre."}
    if not fence(path,spec,"validating"):
        return {"code":"proposal_changed"}
    status,body=call("put",target+"/status",{"state":"VALIDATED"})
    if not 200<=status<300:
        if status in {400,403,409,422}:
            _,row,current = fresh()
            if confirmed(row,current):
                return {"code":"proposal_confirmed","proposal_receipt":row}
            if directory.normalized(row["state"]) not in PENDING:
                return {"code":"proposal_changed"}
        return reject(status,body)
    _,row,source=fresh()
    if confirmed(row,source):
        return {"code":"proposal_confirmed","proposal_receipt":row}
    return {"code":"proposal_uncertain"}
