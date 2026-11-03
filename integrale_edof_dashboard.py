"""CPF operations sourced from Intégrale Academy's authenticated EDOF directory."""
import datetime as dt
from collections import Counter
from contextlib import closing
from functools import lru_cache, wraps
import json
import math
from pathlib import Path
import secrets
from zoneinfo import ZoneInfo

from flask import g, jsonify, Blueprint, abort, flash, get_flashed_messages, redirect, request, session, url_for

from edof_day_session import working_hours
import edof_directory as directory
import edof_declarations as declarations
from cpf_provider import PROVIDERS, ProviderStore, ProviderUnavailable, on_test_service, provider_operation
from cpf_provider_bridge import coordinated_switch, production_request
from edof_matching import build_comparison, manual_options
from edof_readonly_test import ID_RE
from edof_server_browser import DETAIL_PREFIX
from integrale_edof_sync import event_tables
from integrale_edof_transfers import TARGETS, receipt, transfer
from wedof_links import save_manual_wedof_link, sync_exact_wedof_links
from wedof_matching import match_folder

PARIS = ZoneInfo("Europe/Paris")
SECTIONS = {"consumption": "Consommation Intégrale EDOF", "state": "État des dossiers",
            "technical": "Connexion et paramètres techniques", "requests": "Demandes entrantes", "cancellations": "Annulations"}
TABS = {"all": "Tous", "due": "Automatisations prévues", "request": "Nouvelle demande", "accepted": "Acceptés", "training": "En formation",
        "service": "Services faits", "invoiced": "Facturés", "unlinked": "À associer", "anomaly": "Anomalies"}
LABELS = {"accepted": "Accepté", "training": "En formation", "service": "Service fait",
          "invoiced": "Facturé", "request": "À traiter", "waiting": "En attente", "canceled": "Annulé",
          "out": "Sortie déclarée", "refused": "Refusé", "unknown": "État à vérifier"}
STATE_KEYS = {
    "accepted": {"accepted", "accepte", "dossier accepte", "accepte par le titulaire"},
    "training": {"intraining", "en formation", "entree declaree", "entree en formation declaree"},
    "service": {"servicedonedeclared", "servicedonevalidated", "service fait declare", "service fait valide"},
    "invoiced": {"billed", "invoiced", "paid", "facture", "facturee", "paye"},
    "request": {"notprocessed", "tobeprocessed", "received", "a traiter", "demande recue", "demande d inscription", "non traite", "dossier non traite", "not processed", "to be processed"},
    "waiting": {"validated", "waiting", "waitingacceptation", "en attente", "proposition de commande envoyee"},
    "canceled": {"canceled", "cancelled", "cancelledbyattendee", "canceledbyattendee", "canceledbyorganism",
                 "annule", "annulee", "annulation", "canceledbyattendeenotrealized", "non realisee annulation titulaire", "annule par le titulaire", "annule par l organisme"},
    "out": {"outtraining", "outoftraining", "sortie declaree"},
    "refused": {"refused", "refusedbyattendee", "refusedbyorganism", "rejected", "refuse", "refusee"},
}
STATES = {raw: key for key, aliases in STATE_KEYS.items() for raw in aliases}
SIMULATION = {"planned": "Échéance à venir", "ready": "Justificatif disponible",
              "unconfirmed": "Justificatif à renseigner", "blocked": "Blocage administrateur", "missing": "Date à vérifier"}
ACTIONS = {"accepted": "entry_training", "training": "service_done"}
ACTION_LABELS = {"entry_training": "Entrée en formation", "service_done": "Sortie et service fait", "both": "Entrée et sortie"}
BLOCK_REASONS = {"no_show": "Absence", "postponed": "Report", "abandonment": "Abandon",
                 "partial_completion": "Parcours partiel", "administrative_issue": "Vérification administrative", "other": "Autre motif"}


def category(row):
    if directory.normalized(row.get("billing_state") or "") in STATE_KEYS["invoiced"]:
        return "invoiced"
    raw = directory.normalized(row.get("state") or "")
    if raw.startswith(("annule par ", "annulee par ", "annulation par ")):
        return "canceled"
    return STATES.get(raw, "unknown")


def apply_confirmed_entries(snapshot, directory_path, owner):
    if not snapshot:
        return snapshot
    with closing(declarations.database(directory_path)) as db:
        verified = db.execute("""SELECT folder, intent FROM cpf_declarations
            WHERE owner=? AND action='entry_training' AND status='confirmed' AND changed>?
            ORDER BY changed""", (owner, snapshot.get("checked") or 0)).fetchall()
    rows = dict(snapshot["rows"])
    for record in verified:
        row = rows.get(record["folder"])
        intent = json.loads(record["intent"])
        if row and category(row) == "accepted" and declarations.same_enrolment(row, intent):
            # Older receipts certify entry, even if their precise portal state wasn't stored.
            rows[record["folder"]] = {**row, "state": intent.get("confirmed_state") or "Entrée déclarée",
                                      "entry_confirmed_on": intent["actual_date"]}
    return {**snapshot, "rows": rows}


def folder_for_matching(row):
    return {"external_id": row["folder_id"], "type": "cpf", "first_name": row.get("first_name"),
            "last_name": row.get("last_name"), "email": row.get("email"), "training_title": row.get("title"),
            "state": {"accepted": "accepted", "training": "inTraining"}.get(category(row), row.get("state")),
            "start_date": row.get("session_start_date"), "end_date": row.get("session_end_date")}


def active_blocks(data):
    return {(str(x.get("external_id")), x.get("action")): x for x in data.get("wedof_automation_blocks", [])
            if isinstance(x, dict) and x.get("active")}


def simulate(kind, date, block, draft, now):
    if kind not in ACTIONS:
        return None
    if block:
        return "blocked"
    try:
        scheduled = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(18 if kind == "accepted" else 23), PARIS)
    except (TypeError, ValueError):
        return "missing"
    if scheduled > now:
        return "planned"
    if draft and draft.get("action") == ACTIONS[kind] and draft.get("actual_date") and draft.get("evidence"):
        return "ready"
    return "unconfirmed"


def dashboard_rows(snapshot, data, operations, now):
    links = {str(x.get("external_id")): x for x in data.get("wedof_links", []) if isinstance(x, dict) and x.get("active")}
    blocked = active_blocks(data)
    rows, counts = [], Counter()
    for record in (snapshot or {}).get("rows", {}).values():
        folder = record["folder_id"]
        kind = category(record)
        action = ACTIONS.get(kind)
        date = (record.get("session_start_date") if kind == "accepted" else record.get("session_end_date")) or ""
        block = blocked.get((folder, action)) or blocked.get((folder, "both"))
        flags = operations.get(folder, {})
        evaluation = simulate(kind, date, block, flags.get("draft"), now)
        due = evaluation in {"unconfirmed","ready"}
        tags = {kind, "all"}
        if kind == "request" and "pending_ids" in snapshot and folder not in snapshot["pending_ids"]:
            tags.discard("request")
        if evaluation in {"planned", "unconfirmed", "ready"}:
            tags.add("due")
        if folder not in links and action:
            tags.add("unlinked")
        if block or kind == "unknown" or (action and not date):
            tags.add("anomaly")
        counts.update(tags)
        rows.append({**record, "kind": kind, "label": LABELS[kind] if kind != "unknown" else record.get("state") or LABELS[kind],
                     "action": action, "due": due, "evaluation": evaluation, "block": block, "tags": tags, "link": links.get(folder),
                     "handled": bool(flags.get("handled")), "archived": bool(flags.get("archived")),
                     "draft": flags.get("draft"), "official_url": DETAIL_PREFIX + folder})
    return rows, counts


def operations_db(store):
    db = store.connect()
    db.execute("""CREATE TABLE IF NOT EXISTS dossier_work (folder TEXT PRIMARY KEY, handled INTEGER DEFAULT 0,
                  archived INTEGER DEFAULT 0, draft TEXT, updated TEXT, actor TEXT)""")
    return db


def local_operations(store):
    with closing(operations_db(store)) as db:
        return {x["folder"]: {**dict(x), "draft": json.loads(x["draft"]) if x["draft"] else None}
                for x in db.execute("SELECT * FROM dossier_work")}


def record_work(store, folder, actor, **changes):
    if not changes or not set(changes) <= {"handled", "archived", "draft"}:
        raise ValueError("Action CPF inconnue.")
    with closing(operations_db(store)) as db, db:
        db.execute("INSERT OR IGNORE INTO dossier_work(folder) VALUES (?)", (folder,))
        updates = {**changes, "updated": dt.datetime.now(PARIS).isoformat(), "actor": actor}
        db.execute("UPDATE dossier_work SET " + ", ".join(k + "=?" for k in updates) + " WHERE folder=?",
                   (*updates.values(), folder))


def declaration_draft(row, fields):
    action = ACTIONS.get(category(row))
    if not action or fields.get("action") != action or fields.get("attested") != "yes":
        raise ValueError("Vérifiez le statut du dossier et confirmez le justificatif.")
    try:
        date = dt.date.fromisoformat(fields.get("actual_date", ""))
    except (TypeError, ValueError):
        raise ValueError("Renseignez la date effective.") from None
    if date > dt.datetime.now(PARIS).date():
        raise ValueError("La date effective ne peut pas être future.")
    if row.get("session_start_date") and date.isoformat() < row["session_start_date"]:
        raise ValueError("La date effective précède le début de la session.")
    if row.get("session_end_date") and date.isoformat() > row["session_end_date"]:
        raise ValueError("La date effective dépasse la fin de la session EDOF.")
    evidence = fields.get("evidence", "").strip()
    if not 3 <= len(evidence) <= 250:
        raise ValueError("Indiquez la référence du justificatif (3 à 250 caractères).")
    result = {"action": action, "actual_date": date.isoformat(), "evidence": evidence}
    if action == "service_done":
        try:
            rate = int(fields.get("rate", ""))
        except (TypeError, ValueError):
            rate = -1
        reason = fields.get("reason", "").strip()
        if not 0 <= rate <= 100 or (rate < 100 and not 3 <= len(reason) <= 250):
            raise ValueError("Vérifiez le taux réalisé et le motif en cas de parcours partiel.")
        result.update(rate=rate, reason=reason[:250] if rate < 100 else "")
        if fields.get("motif") in declarations.MOTIFS and rate < 100:
            result["motif"] = fields["motif"]
    return result


def register_dashboard(app, legacy, store, *, results_owner, vault, gmail_status, admin_required, check_csrf):
    bp = Blueprint("integrale_edof", __name__, url_prefix="/admin/edof-test")
    selection = ProviderStore(store.directory)

    def native_action(view):
        @wraps(view)
        def guarded(*args, **kwargs):
            owner = results_owner()
            if session.get("admin_role") == "viewer":
                abort(403)
            check_csrf()
            try:
                with provider_operation("integrale"):
                    return view(owner, *args, **kwargs)
            except (ProviderUnavailable, ValueError) as exc:
                flash(str(exc), "error")
                return back(request.form.get("section") or "state")
        return admin_required(guarded)

    def back(section="state", **kwargs):
        return redirect(url_for("integrale_edof.index", section=section if section in SECTIONS else "state", **kwargs), code=303)

    def snapshot(owner):
        saved = vault().get(directory.record_key(owner)) if store.connector_key else None
        # Previously synchronized dossiers also contain French display dates.
        pending = vault().get(directory.pending_key(owner)) if store.connector_key else None
        full = apply_confirmed_entries(directory.dated_snapshot(saved), store.directory, owner)
        return directory.with_pending(full, pending)

    def folder_record(owner, folder):
        if not ID_RE.fullmatch(folder):
            abort(404)
        raw = (snapshot(owner) or {}).get("rows", {}).get(folder)
        if not raw:
            raise ValueError("Dossier absent de la liste EDOF synchronisée. Actualisez la liste.")
        return raw

    @lru_cache(maxsize=1)
    def local_projection(version):
        with open(legacy.DATA_FILE, encoding="utf-8") as source:
            data = json.load(source)
        sessions = []
        for group in data.get("sessions", []):
            if not isinstance(group,dict):
                continue
            summary = {key:group[key] for key in ("id", "name", "training_type", "date_start", "date_end",
                  "date_debut", "date_fin", "archived", "is_archived", "status") if key in group}
            summary["trainees"] = [{key:t[key] for key in ("id","first_name","last_name","prenom","nom","email","mail")
                                    if key in t} for t in (group.get("trainees") or group.get("stagiaires") or []) if isinstance(t,dict)]
            sessions.append(summary)
        return {"sessions": sessions, "wedof_links": data.get("wedof_links", []),
                "wedof_automation_blocks": data.get("wedof_automation_blocks", [])}

    def local_data():
        try:
            st = Path(legacy.DATA_FILE).stat()
        except FileNotFoundError:
            return {}
        return local_projection((st.st_ino, st.st_mtime_ns, st.st_size))

    def enrich(owner, row):
        previous = store.successful_read(owner, spec={"folder_id": row["folder_id"], "first_name": "", "last_name": ""})
        fields = previous["fields"] if previous else {}
        if fields and all(directory.normalized(fields.get(k) or "") == directory.normalized(row.get(k) or "")
                          for k in ("first_name", "last_name")):
            return {**row, "email": fields.get("email", "")}
        return row

    def matching_rows(owner, snapshot, data):
        with closing(store.connect()) as db:
            reads = db.execute("""SELECT result FROM jobs WHERE owner=? AND mode='read'
                       AND json_extract(result,'$.code')='read_success' ORDER BY finished DESC""", (owner,)).fetchall()
        contacts = {}
        for item in reads:
            fields = json.loads(item[0]).get("fields", {})
            contacts.setdefault(fields.get("folder_id"), fields)
        results = {}
        for row in (snapshot or {}).get("rows", {}).values():
            if category(row) not in ACTIONS:
                continue
            detail = contacts.get(row["folder_id"], {})
            if detail and all(directory.normalized(detail.get(k) or "") == directory.normalized(row.get(k) or "")
                              for k in ("first_name","last_name")):
                row = {**row, "email":detail.get("email", "")}
            results[row["folder_id"]] = match_folder(folder_for_matching(row), data.get("sessions", []))
        return results

    @bp.after_request
    def private(response):
        script_policy = "'nonce-" + g.edof_nonce + "'" if hasattr(g, "edof_nonce") else "'none'"
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                 "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": f"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src {script_policy}; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
        return response

    @bp.get("/connection-status")
    @admin_required
    def connection_badge():
        owner = results_owner()
        saved = gmail_status()["saved_session"]
        return jsonify(store.live_connection(owner, saved))

    @bp.get("")
    @admin_required
    def index():
        owner = results_owner()
        g.edof_nonce = secrets.token_urlsafe(24)
        csrf = session.setdefault("edof_server_csrf", secrets.token_urlsafe(32))
        section = request.args.get("section", "state")
        if section not in SECTIONS:
            abort(404)
        tab = request.args.get("tab", "all")
        if tab not in TABS:
            tab = "all"
        snap = snapshot(owner)
        if snap:
            store.use_directory(owner)
        now = dt.datetime.now(PARIS)
        today = now.date().isoformat()
        data = local_data() if snap and section in {"state", "requests", "cancellations"} else {}
        rows, counts = dashboard_rows(snap, data, local_operations(selection), now)
        previewing = section == "state" and request.args.get("matching") == "1"
        matches = matching_rows(owner, snap, data) if previewing else {}
        if previewing:
            rows = [r for r in rows if r["folder_id"] in matches]
        testing = section == "state" and request.args.get("simulation") == "1"
        simulation = Counter(r["evaluation"] for r in rows if r["evaluation"])
        if testing:
            rows = [r for r in rows if r["evaluation"]]
        q = directory.normalized(request.args.get("q", "")[:140])
        if section in {"requests", "cancellations"}:
            kind = "request" if section == "requests" else "canceled"
            rows = [row for row in rows if kind in row["tags"] and not row["archived"]]
        else:
            rows = [row for row in rows if tab in row["tags"]]
        if q:
            rows = [r for r in rows if q in directory.normalized(" ".join(str(r.get(k) or "") for k in
                    ("folder_id", "first_name", "last_name", "last_name", "first_name", "title", "label")))]
        rows.sort(key=lambda r: (r.get("session_start_date") or "", r["folder_id"]), reverse=True)
        pages = max(1, math.ceil(len(rows) / 25))
        page = max(1, min(request.args.get("page", 1, type=int) or 1, pages))
        detail = None
        folder = request.args.get("folder", "")
        if folder:
            if not ID_RE.fullmatch(folder) or folder not in (snap or {}).get("rows", {}):
                abort(404)
            record = folder_record(owner, folder)
            if not data:
                data = local_data()
            detail = {"record": record, "comparison": build_comparison(data, enrich(owner, record))}
            detail["query"] = request.args.get("inscription","")[:120].strip()
            if detail["query"]:
                detail["comparison"] = {**detail["comparison"], "status":"manual_search",
                                        "candidates":manual_options(data, enrich(owner, record), query=detail["query"])}
            detail["key"] = directory.link_key(owner, folder)
            detail["draft"] = local_operations(selection).get(folder, {}).get("draft")
            detail["action"] = ACTIONS.get(category(record))
            detail["request"] = category(record) == "request"
            detail["transfers"] = {target:receipt(selection, folder, target) for target in TARGETS} if detail["request"] else {}
            detail["official"] = DETAIL_PREFIX + folder
        with closing(store.connect()) as db:
            metrics = dict(db.execute("SELECT mode, COUNT(*) FROM jobs WHERE owner=? GROUP BY mode", (owner,)))
        with closing(selection.connect()) as db:
            event_tables(db)
            cursor = db.execute("SELECT checked FROM directory_cursor WHERE id=1").fetchone()
            events = [dict(x) for x in db.execute("SELECT * FROM directory_events ORDER BY id DESC LIMIT 12")
                      if x["folder"] in (snap or {}).get("rows", {})]
        gmail = gmail_status()
        selected = selection.state()
        from edof_server_test import MESSAGES
        dispatches = declarations.records(store.directory)
        visible_folders = (snap or {}).get("rows", {})
        dispatches = [d for d in dispatches if d["folder"] in visible_folders]
        if detail:
            detail["dispatches"] = [d for d in dispatches if d["folder"] == folder]
        with closing(store.connect()) as db:
            inspection = db.execute(
                "SELECT result,finished FROM jobs WHERE owner=? AND mode='inspect_forms' ORDER BY created DESC LIMIT 1", (owner,)).fetchone()
        check = json.loads(inspection["result"]) if inspection else None
        if check:
            check["message"] = MESSAGES.get(check["code"], "Contrôle à reprendre.")
        production, bridge_error = None, ""
        if on_test_service():
            try:
                production = production_request()
            except ProviderUnavailable as exc:
                bridge_error = str(exc)
        aligned = not selected["pending"] and not bridge_error and (
            production is None or selected["provider"] == production["provider"])
        if detail and aligned and selected["provider"] == "wedof" and on_test_service():
            try:
                pilot = declarations.pilot_state(folder)
                detail["pilot"] = pilot
                detail["pilot_ready"] = declarations.matches_pilot(detail["record"], pilot)
                proof = pilot.get("proof") or {}
                if declarations.same_enrolment(detail["record"], proof) and proof.get("entry_training"):
                    detail["pilot_proof"] = proof["entry_training"]
            except (ValueError, ProviderUnavailable) as exc:
                detail["pilot_error"] = str(exc)
        return app.jinja_env.get_template("integrale_edof.html").render(
            selection=selected, production=production, bridge_error=bridge_error, aligned=aligned, providers=PROVIDERS, sections=SECTIONS, section=section, tabs=TABS, tab=tab,
            dispatch_labels=declarations.LABELS, dispatch_reasons=MESSAGES, motifs=declarations.MOTIFS,
            inspection=check, dispatches=dispatches, csrf=csrf, flashes=get_flashed_messages(with_categories=True), previewing=previewing, matches=matches,
            match_counts=Counter(m["status"] for m in matches.values()), total=len(rows), counts=counts,
            rows=rows[(page-1)*25:page*25], page=page, pages=pages, query=request.args.get("q", "")[:140], simulation=simulation, testing=testing, simulation_labels=SIMULATION,
            detail=detail, events=events, full_checked=directory.stamp(snap) if snap and snap.get("checked") else None, analysis_checked=directory.stamp({"checked":cursor[0]}) if cursor else None, labels=LABELS, checked=(directory.stamp({"checked":snap["pending_checked"]}) if snap and snap.get("pending_checked") and (tab=="request" or section=="requests") else directory.stamp(snap) if snap and snap.get("checked") else None), today=today, metrics=metrics,
            live=store.live_connection(owner, gmail["saved_session"]), nonce=g.edof_nonce, jobs=store.latest(owner), efp=store.connection_status(owner, gmail["saved_session"]), gmail=gmail,
            scope=(snap or {}).get("scope", "open"), day_open=working_hours(now), directory_enabled=store.directory_enabled(owner), snapshot_count=len((snap or {}).get("rows", {})),
            block_reasons=BLOCK_REASONS, action_labels=ACTION_LABELS,
            changed=dt.datetime.fromtimestamp(selected["changed"], PARIS).strftime("%d/%m/%Y à %H h %M") if selected["changed"] else None)

    @bp.post("/provider")
    @admin_required
    def switch():
        owner = results_owner()
        if session.get("admin_role") == "viewer":
            abort(403)
        check_csrf()
        target = request.form.get("provider")
        if target not in PROVIDERS:
            abort(400)
        try:
            revision = int(request.form.get("revision", ""))
        except ValueError:
            abort(400)
        try:
            def check_production(body=None):
                # coordinated_switch holds the exclusive provider lock while making this check.
                if target == "wedof" and body is None:
                    with closing(declarations.database(store.directory)) as db:
                        outstanding = db.execute("SELECT folder FROM cpf_declarations WHERE status IN ('sending','uncertain') ORDER BY changed LIMIT 1").fetchone()
                    if outstanding:
                        raise ProviderUnavailable(f"Vérifiez d’abord la réception du dossier {outstanding['folder']} dans sa fiche pour éviter un double envoi.")
                return production_request(body)

            result = coordinated_switch(selection, target, revision, session.get("admin_username") or owner,
                                        remote=check_production if on_test_service() else None)
        except ProviderUnavailable as exc:
            flash(str(exc), "warning")
            return back()
        # Exactly one initial refresh per deliberate activation, including
        # after several weeks away. A failed sign-in cannot reschedule itself.
        if target == "integrale" and result["revision"] != revision:
            store.request_directory(owner)
        flash(f"{PROVIDERS[target]} est actif pour votre établissement. Bascule confirmée.", "success")
        return back()

    @bp.post("/associate-reliable")
    @native_action
    def associate_reliable(owner):
        snap = snapshot(owner)
        if snap is None:
            raise ValueError("Synchronisez d’abord la liste EDOF.")
        summary = {}
        def apply(data):
            results = matching_rows(owner, snap, data)
            summary.update(sync_exact_wedof_links(data, results.values()))
            return data
        legacy._atomic_update_data(apply)
        flash(f"{summary['created']} association(s) créée(s), {summary['already_linked']} déjà présente(s), "
              f"{summary['conflicts']} conflit(s). Le rapprochement automatique exige aussi un contact vérifié.", "success")
        return back()

    @bp.post("/dossiers/<folder>/associate")
    @native_action
    def associate(owner, folder):
        row = enrich(owner, folder_record(owner, folder))
        sid, tid = request.form.get("session_id"), request.form.get("trainee_id")
        outcome = []
        def apply(data):
            choices = manual_options(data, row, pair=(sid, tid))
            if len(choices) != 1 or choices[0]["issues"] or request.form.get("verified") != "yes":
                raise ValueError("Vérifiez l’identité, la session et les éventuels conflits avant d’associer.")
            result = save_manual_wedof_link(data, external_id=folder, session_id=sid, trainee_id=tid,
                       state=folder_for_matching(row)["state"], date_start=row.get("session_start_date"), date_end=row.get("session_end_date"))
            if result == "conflict":
                raise ValueError("Ce dossier ou cette inscription possède déjà une autre association.")
            outcome.append(result)
            return data
        legacy._atomic_update_data(apply)
        flash("Association locale enregistrée." if outcome == ["created"] else "Association déjà enregistrée.", "success")
        return back(folder=folder)

    @bp.post("/dossiers/<folder>/block")
    @native_action
    def block(owner, folder):
        row = folder_record(owner, folder)
        action = request.form.get("action")
        reason = request.form.get("reason", "")
        clear = request.form.get("release") == "yes"
        if action not in ACTION_LABELS or (not clear and (action != ACTIONS.get(category(row)) or reason not in BLOCK_REASONS)):
            abort(400)
        if not clear:
            with closing(declarations.database(store.directory)) as db, db:
                pending = db.execute(
                    "SELECT action,status FROM cpf_declarations WHERE folder=?", (folder,)).fetchall()
                if any(x["action"] in (action,) or action == "both" for x in pending if x["status"] in {"sending", "uncertain"}):
                    raise ValueError("Un envoi est déjà parti. Vérifiez sa réception dans cette fiche.")
                db.execute("UPDATE cpf_declarations SET status='review',detail='declaration_blocked' WHERE folder=? AND (action=? OR ?='both') AND status='queued'", (folder, action, action))
        now = dt.datetime.now(PARIS).isoformat()
        def apply(data):
            blocks = data.setdefault("wedof_automation_blocks", [])
            block = next((x for x in blocks if x.get("external_id") == folder and x.get("action") == action), None)
            if block:
                block.update(active=not clear, updated_at=now)
                if not clear:
                    block["reason_code"] = reason
            elif not clear:
                blocks.append({"id": "CPF-" + secrets.token_hex(8), "external_id": folder, "action": action,
                    "active": True, "reason_code": reason, "comment": "", "created_at": now, "updated_at": now})
            return data
        legacy._atomic_update_data(apply)
        flash("Blocage levé." if clear else "Automatisation bloquée pour ce dossier.", "success")
        return back()

    @bp.post("/dossiers/<folder>/follow-up")
    @native_action
    def follow_up(owner, folder):
        row = folder_record(owner, folder)
        if category(row) != "request":
            raise ValueError("Cette demande n’est plus à traiter dans la liste synchronisée.")
        change = request.form.get("change")
        if change not in {"handled", "archived", "reopen"}:
            abort(400)
        record_work(selection, folder, session.get("admin_username") or owner, **(
            {"handled": 0, "archived": 0} if change == "reopen" else {change: 1}))
        flash("Suivi local de la demande mis à jour.", "success")
        return back("requests")

    @bp.post("/dossiers/<folder>/refresh")
    @native_action
    def read_folder(owner, folder):
        from edof_server_test import configuration, start_job
        row = folder_record(owner, folder)
        if not configuration()["credentials_configured"]:
            raise ValueError("Configurez le compte EFP avant de relire la fiche.")
        start_job(store, owner, {"mode":"read", "folder_id":folder, "first_name":row.get("first_name") or "",
                                 "last_name":row.get("last_name") or ""})
        return redirect(url_for("edof_server_test.index"), code=303)

    @bp.post("/dossiers/<folder>/transfer/<target>")
    @native_action
    def send_request(owner, folder, target):
        if target not in TARGETS:
            abort(404)
        row = enrich(owner, folder_record(owner, folder))
        if category(row) != "request" or request.form.get("verified") != "yes":
            raise ValueError("Vérifiez la demande et ses destinataires avant de la transmettre.")
        note = transfer(selection, legacy, row, target, DETAIL_PREFIX + folder)
        flash(note, "success")
        return back("requests",folder=folder)

    @bp.post("/inspect-forms")
    @admin_required
    def inspect_forms():
        owner = results_owner()
        if session.get("admin_role") == "viewer":
            abort(403)
        check_csrf()
        probes = {}
        rows = (snapshot(owner) or {}).get("rows", {}).values()
        today = dt.datetime.now(PARIS).date().isoformat()
        def priority(row):
            date = row.get("session_start_date" if category(row) == "accepted" else "session_end_date") or "9999-12-31"
            return (date > today, abs((dt.date.fromisoformat(date) - dt.date.fromisoformat(today)).days))
        for row in sorted(rows, key=priority):
            action = ACTIONS.get(category(row))
            if action and action not in probes:
                probes[action] = row["folder_id"]
            if len(probes) == 2:
                break
        if not probes:
            flash("Aucun dossier accepté ou en formation dans la dernière liste.", "warning")
        else:
            try:
                from edof_server_test import start_job
                start_job(store, owner, {"mode": "inspect_forms", "probes": probes, "owner": owner})
                flash("Contrôle lancé. Actualisez pour voir le résultat.", "success")
            except ValueError as exc:
                flash(str(exc), "warning")
        return back("technical")

    @bp.post("/dossiers/<folder>/recheck")
    @native_action
    def recheck(owner, folder):
        folder_record(owner, folder)
        declarations.request_recheck(store.directory, folder, request.form.get("action"))
        flash("Relecture demandée. Le connecteur vérifiera la réception sans renvoyer la déclaration.", "success")
        return back(folder=folder)

    @bp.post("/dossiers/<folder>/entry-pilot")
    @admin_required
    def pilot_entry(folder):
        owner = results_owner()
        if session.get("admin_role") == "viewer" or not on_test_service():
            abort(403)
        check_csrf()
        actor = session.get("admin_username") or owner
        try:
            with provider_operation("wedof"):
                row = folder_record(owner, folder)
                mode = request.form.get("mode")
                if mode == "recheck":
                    declarations.request_recheck(store.directory, folder, "entry_training")
                    flash("Relecture demandée pour cette entrée.", "success")
                    return back(folder=folder)
                state = declarations.pilot_state(folder)
                if mode == "release":
                    declarations.pilot_state(folder, "release", actor=actor)
                    flash("Réservation levée pour cette entrée.", "success")
                elif category(row) != "accepted" or not declarations.matches_pilot(row, state):
                    raise ValueError("L’état ou les dates du dossier ne permettent pas de réserver cette entrée.")
                elif mode == "reserve":
                    if not declarations.pilot_state(folder, "reserve", actor=actor).get("reserved"):
                        raise ValueError("L’exclusion de cette entrée n’est pas confirmée.")
                    flash("L’entrée de ce dossier est exclue de l’automatisation WeDoF de production.", "success")
                elif mode == "submit" and state["reserved"] and state.get("ticket"):
                    action = "entry_training"
                    if any((folder, k) in active_blocks(local_data()) for k in (action, "both")):
                        raise ValueError("Une suspension est en cours sur ce dossier.")
                    draft = declaration_draft(row, request.form)
                    proof = state.get("proof") or {}
                    automatic = proof.get(action)
                    if automatic and declarations.same_enrolment(row, proof):
                        if draft["actual_date"] != automatic["actual_date"]:
                            raise ValueError("La date saisie diffère du justificatif de production.")
                        draft = dict(automatic)
                    draft["pilot_ticket"] = state["ticket"]
                    result = declarations.enqueue(store.directory, owner, selection.state()["revision"], row, draft, actor)
                    flash(declarations.LABELS[result], "success")
                else:
                    raise ValueError("Réservez d’abord l’entrée de ce dossier en production.")
        except (ValueError, ProviderUnavailable) as exc:
            flash(str(exc), "error")
        return back(folder=folder)

    @bp.post("/dossiers/<folder>/submit")
    @native_action
    def submit(owner, folder):
        row = folder_record(owner, folder)
        action = ACTIONS.get(category(row))
        blocks = active_blocks(local_data())
        if (folder, action) in blocks or (folder, "both") in blocks:
            raise ValueError("Une suspension est en cours sur ce dossier.")
        fields = request.form.to_dict()
        if fields.get("motif") in declarations.MOTIFS and not fields.get("reason", "").strip():
            fields["reason"] = declarations.MOTIFS[fields["motif"]]
        draft = declaration_draft(row, fields)
        state = declarations.enqueue(store.directory, owner, selection.state()[
                                     "revision"], row, draft, session.get("admin_username") or owner)
        flash(declarations.LABELS[state], "success")
        return back(folder=folder)

    @bp.post("/dossiers/<folder>/prepare")
    @native_action
    def prepare(owner, folder):
        row = folder_record(owner, folder)
        action = ACTIONS.get(category(row))
        blocks = active_blocks(local_data())
        if (folder, action) in blocks or (folder, "both") in blocks:
            raise ValueError("Le dossier est bloqué. Vérifiez le motif avant de préparer sa déclaration.")
        draft = declaration_draft(row, request.form)
        record_work(selection, folder, session.get("admin_username") or owner, draft=json.dumps(draft, ensure_ascii=False))
        flash("Déclaration préparée. Vous pouvez la transmettre depuis cette fiche.", "success")
        return back(folder=folder)

    app.register_blueprint(bp)
