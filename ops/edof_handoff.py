"""One-shot private-network handoff for the two named Render services; prints only counts."""
import base64
from contextlib import closing, ExitStack
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import sys
import tempfile
import time

from cryptography.fernet import Fernet
from cpf_provider import current_store
from edof_gmail import connector_key, account_binding

SOURCE = "srv-d928tc19rddc7388qie0"
DEST = "srv-d5oss66id0rc73avvne0"
RETIRED = "0c6fa447a110cadeb7cb4386dc9a4f9f60f711d9"
HOST = "gestionstagiaires-r5no"
PORT = 29467
DBS = ("edof_server_test.sqlite3", "edof_readonly_test.sqlite3", "edof_traffic.sqlite3",
       "edof_connector_private.sqlite3", "cpf-providers.sqlite3")
VAULT, LEDGER = DBS[-2:]
LIMIT = 32 * 1024 * 1024

def require(ok, msg):
    if not ok:
        raise RuntimeError(msg)

def digest(key, *args):
    return hmac.digest(key, b"\x00".join(args), "sha256")

def config():
    bridge = os.environ["CPF_PROVIDER_BRIDGE_KEY"].encode()
    secret = os.environ["SECRET_KEY"]
    user = os.environ["ADMIN_USER"].strip().lower().encode()
    names = ("EDOF_EFP_USERNAME", "EDOF_EFP_PASSWORD", "EDOF_GOOGLE_CLIENT_ID", "EDOF_GOOGLE_CLIENT_SECRET")
    require(len(bridge) >= 20 and user and all(os.environ.get(n) for n in names), "Missing environment configuration")
    return (digest(bridge,b"Nov05/EDOF/cutover/v1"), secret, user, [os.environ[n].encode() for n in names])

def recv_exact(sock, length):
    out = bytearray()
    while len(out) < length:
        part = sock.recv(min(length - len(out), 131072))
        require(part, "Transfer interrupted")
        out.extend(part)
    return bytes(out)

def send_message(sock, cipher, message):
    raw = cipher.encrypt(json.dumps(message,separators=(",",":")).encode())
    require(len(raw) <= LIMIT, "Payload limit")
    sock.sendall(struct.pack(">I", len(raw)) + raw)

def receive_message(sock, cipher):
    size, = struct.unpack(">I",recv_exact(sock,4))
    require(1 <= size <= LIMIT, "Payload limit")
    return json.loads(cipher.decrypt(recv_exact(sock,size),ttl=240))

def exchange(sock, source, phase, cfg):
    key = cfg[0]
    op = phase.encode()
    if source:
        a = os.urandom(32)
        sock.sendall(a)
        b, proof = recv_exact(sock,32), recv_exact(sock,32)
        require(hmac.compare_digest(proof,digest(key,b"destination",op,a,b)), "Target authentication")
        sock.sendall(digest(key,b"source",op,a,b))
    else:
        a, b = recv_exact(sock,32), os.urandom(32)
        sock.sendall(b+digest(key,b"destination",op,a,b))
        require(hmac.compare_digest(recv_exact(sock,32),digest(key,b"source",op,a,b)), "Source authentication")
    session = digest(key,b"session",op,a,b)
    return Fernet(base64.urlsafe_b64encode(session)), session

def profile(cfg, session):
    _,secret,user,params = cfg
    return {"credentials":digest(session,b"environment",*params).hex(),
            "secret":digest(session,b"app-compare",secret.encode()).hex(),
            "admin":digest(session,b"admin-compare",user).hex(),
            "owner":hmac.digest(secret.encode(), b"edof-test-results-v1\0"+user, "sha256").hex()}

def backup(original, candidate):
    require(original.is_file() and not candidate.exists(), "Invalid backup paths")
    with closing(sqlite3.connect(original.as_uri()+"?mode=ro",uri=True)) as src, closing(sqlite3.connect(candidate)) as dest:
        src.backup(dest)
        dest.execute("PRAGMA journal_mode=DELETE")
        require(dest.execute("PRAGMA quick_check").fetchall()==[("ok",)],"SQLite validation failed")

def vault_process(path, old, new, oldowner, newowner):
    visits = {"dossiers":0,"gmail":False,"navigateur":False,"annuaires":0,"coffre":0}
    with closing(sqlite3.connect(path)) as db, db:
        for name,sealed in db.execute("SELECT name,sealed FROM private_records").fetchall():
            plain=old.decrypt(sealed)
            d=json.loads(plain)
            live=(d["binding"]==account_binding() and (not d["expires"] or d["expires"]>time.time()))
            if live:
                if name.startswith("edof-directory-v1-"):
                    visits["dossiers"]+=len(d["value"]["rows"])
                    visits["annuaires"]+=1
                    if oldowner!=newowner:
                        require(name.endswith(oldowner),"Directory identity mismatch")
                if name=="gmail":
                    visits["gmail"]=bool(d["value"].get("refresh_token"))
                if name=="browser":
                    visits["navigateur"]=bool(d["value"])
            if oldowner!=newowner:
                plain=plain.replace(oldowner.encode(),newowner.encode())
            db.execute("UPDATE private_records SET name=?,sealed=? WHERE name=?",
                       (name.replace(oldowner,newowner),new.encrypt(plain),name))
            visits["coffre"]+=1
    return visits

def snapshot(d,folder,cfg,cipher,session):
    srcdata=json.loads((d/"data.json").read_bytes())
    require(not any(x.get("active") for x in srcdata.get("wedof_links",[]))
        and not any(str(x.get("id","")).startswith("CPF-") or x.get("active") for x in srcdata.get("wedof_automation_blocks",[]))
        and not any(t.get("edof_registration") for s in srcdata.get("sessions",[]) for t in (s.get("trainees") or s.get("stagiaires") or [])), "CRM records require manual reconciliation")
    me=profile(cfg,session)
    files={}
    for name in DBS:
        path=folder/name
        backup(d/name,path)
        if name==VAULT:
            visits=vault_process(path,Fernet(connector_key(cfg[1])),cipher,me["owner"],me["owner"])
        files[name]=base64.b64encode(path.read_bytes()).decode()
    return {"profile":me,"data":files,"checks":visits}

def validate_count(path):
    with closing(sqlite3.connect(path)) as db:
        require(db.execute("PRAGMA integrity_check").fetchall()==[("ok",)],"Integrity check failed")
        names=tables(db,"main")
        return {n:db.execute('SELECT count(*) FROM "'+n.replace('"','""')+'"').fetchone()[0] for n in sorted(names)}

def map_owner(path,old,new):
    # Account ids appear in owner columns and JSON scope fields. Do not modify a folder id, token or receipt.
    if old==new:
        return
    with closing(sqlite3.connect(path)) as db, db:
        for name in tables(db,"main"):
            for col in db.execute('PRAGMA table_info("'+name+'")').fetchall():
                field=col[1]
                if str(col[2]).upper()=="TEXT":
                    db.execute(f'UPDATE "{name}" SET "{field}"=replace("{field}",?,?) WHERE instr("{field}",?)>0',(old,new,old))

def target(d,folder,payload,cfg,cipher,session,phase):
    mine=profile(cfg,session)
    theirs=payload["profile"]
    require(hmac.compare_digest(mine["credentials"],theirs["credentials"]),"EDOF environments do not match")
    same_secret = hmac.compare_digest(mine["secret"],theirs["secret"])
    same_admin = hmac.compare_digest(mine["admin"],theirs["admin"])
    require(same_admin or theirs["owner"]!=mine["owner"],"Admin identity")
    old,new=theirs["owner"],mine["owner"]
    require(set(payload["data"])==set(DBS),"Unexpected file set")
    require(not (d/"edof-production.ready").exists(),"Production is already active")
    require(not any((d/name).exists() for name in DBS if name!=LEDGER),"Production EDOF files already exist")
    require(not any((d/(LEDGER+ext)).exists() for ext in ("-wal","-shm","-journal")),"Production has live SQLite journaling")
    before=folder/"production-original.sqlite3"
    backup(d/LEDGER,before)
    for name in DBS:
        f=folder/name
        f.write_bytes(base64.b64decode(payload["data"][name],validate=True))
        validate_count(f)
        if name==VAULT:
            visits=vault_process(f,cipher,Fernet(connector_key(cfg[1])),old,new)
            require(visits["dossiers"]>0 and visits["gmail"] and visits["dossiers"]==payload["checks"]["dossiers"],"Gmail or directory failed verification")
        else:
            map_owner(f,old,new)
    candidate=folder/"merged.sqlite3"
    merge_snapshot(folder/LEDGER,before,candidate)
    old_counts=validate_count(folder/LEDGER)
    merged=validate_count(candidate)
    require(all(merged.get(k,0)>=v for k,v in old_counts.items() if k not in CONTROL),"Incomplete native ledger")
    candidate.replace(folder/LEDGER)
    counts={name:validate_count(folder/name) for name in DBS}
    summary={"phase":phase,**visits,"same_admin":same_admin,"same_key":same_secret,"tables":counts[LEDGER],
             "jobs":counts[DBS[0]].get("jobs",0)}
    if phase=="apply":
        guard=d/"edof-cutover-20261105"
        guard.mkdir(mode=0o700)
        backup(d/LEDGER,guard/"production-before.sqlite3")
        (guard/"summary.json").write_text(json.dumps(summary))
        installed=[]
        try:
            for name in DBS:
                os.chmod(folder/name,0o600)
                os.replace(folder/name,d/name)
                installed.append(name)
            for name in DBS:
                require(validate_count(d/name)==counts[name],"Published counts mismatch")
            require(current_store().state()["provider"]=="integrale","Unexpected selection")
            marker=folder/"ready"
            marker.write_text(json.dumps(summary))
            os.replace(marker,d/"edof-production.ready")
        except BaseException:
            for name in reversed(installed):
                if name==LEDGER:
                    restore=folder/"restore.sqlite3"
                    backup(guard/"production-before.sqlite3",restore)
                    os.replace(restore,d/name)
                else:
                    os.replace(d/name,guard/(name+".unpublished"))
            raise
    return summary

def run():
    side,phase=sys.argv[1:3]
    require(phase in ("preview","apply") and side in ("send","receive"),"Invalid command")
    send=side=="send"
    require(os.environ.get("RENDER_SERVICE_ID")== (SOURCE if send else DEST),"Incorrect service")
    cfg=config()
    os.umask(0o077)
    store=current_store()
    d=store.directory
    with ExitStack() as stack:
        if send:
            sock=stack.enter_context(socket.create_connection((HOST,PORT),timeout=15))
        else:
            server=stack.enter_context(socket.socket())
            server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            server.bind(("",PORT));server.listen(1);server.settimeout(240)
            print("READY",phase,flush=True)
            sock=stack.enter_context(server.accept()[0])
        sock.settimeout(90)
        cipher,session=exchange(sock,send,phase,cfg)
        folder=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix=".edof-stage-",dir=d)))
        if phase=="apply":
            stack.callback(os.close,store.lock(exclusive=True))
            if send:
                require(os.environ.get("RENDER_GIT_COMMIT")==RETIRED,"Source worker is not retired")
                for name in ("edof_day_leader.lock","edof_server_test.lock"):
                    lock=stack.enter_context(open(d/name,"a"))
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if send:
            send_message(sock,cipher,snapshot(d,folder,cfg,cipher,session))
            result=receive_message(sock,cipher)
        else:
            result=target(d,folder,receive_message(sock,cipher),cfg,cipher,session,phase)
            send_message(sock,cipher,result)
        print("VERIFIED",json.dumps(result,sort_keys=True),flush=True)
"""Assemble a candidate provider database from consistent offline SQLite backups."""
from contextlib import closing
from pathlib import Path
import sqlite3

CONTROL = {"selections", "pending_provider_switch", "applied_provider_switch", "cpf_transfers"}

def tables(db, schema):
    return {row[0] for row in db.execute(
        f"SELECT name FROM {schema}.sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}

def merge_snapshot(test_backup, production_backup, candidate):
    if Path(candidate).exists():
        raise ValueError("New output path required")
    with closing(sqlite3.connect(f"file:{test_backup}?mode=ro", uri=True)) as source, closing(sqlite3.connect(candidate, uri=True)) as db:
        source.backup(db)
        db.execute("ATTACH DATABASE ? AS prod", (f"file:{production_backup}?mode=ro",))
        with db:
            production_tables = tables(db, "prod")
            if production_tables - CONTROL:
                raise ValueError("Existing production EDOF business tables require comparison")
            for schema in ("main", "prod"):
                if db.execute(f"SELECT 1 FROM {schema}.pending_provider_switch LIMIT 1").fetchone():
                    raise ValueError("Complete the pending provider change first")
            def active(schema):
                return db.execute(f"SELECT revision,provider FROM {schema}.selections ORDER BY revision DESC LIMIT 1").fetchone() or (0, "wedof")
            if active("main") != active("prod"):
                raise ValueError("Reconcile the two provider revisions before activation")
            db.execute("DELETE FROM main.selections")
            db.execute("INSERT INTO main.selections SELECT * FROM prod.selections")
            if "applied_provider_switch" in production_tables:
                db.execute("""CREATE TABLE IF NOT EXISTS main.applied_provider_switch (
                    id INTEGER PRIMARY KEY CHECK(id=1), operation TEXT NOT NULL, target TEXT NOT NULL)""")
                db.execute("DELETE FROM main.applied_provider_switch")
                db.execute("INSERT INTO main.applied_provider_switch SELECT * FROM prod.applied_provider_switch")
            if "cpf_transfers" in production_tables:
                from cpf_transfer_history import receipts
                receipts(db)
                db.execute("""INSERT INTO main.cpf_transfers SELECT * FROM prod.cpf_transfers WHERE TRUE
                    ON CONFLICT(folder,target) DO UPDATE SET state =
                      CASE WHEN 'sent' IN (excluded.state,cpf_transfers.state) THEN 'sent'
                           WHEN 'uncertain' IN (excluded.state,cpf_transfers.state) THEN 'uncertain'
                           WHEN 'processing' IN (excluded.state,cpf_transfers.state) THEN 'processing'
                           ELSE cpf_transfers.state END,
                      changed = max(excluded.changed,cpf_transfers.changed)""")
        if db.execute("PRAGMA main.integrity_check").fetchone() != ("ok",):
            raise ValueError("Assembled database failed integrity check")

if __name__=="__main__":
    run()
