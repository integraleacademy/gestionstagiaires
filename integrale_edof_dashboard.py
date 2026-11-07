"""CPF operations sourced from Intégrale Academy's authenticated EDOF directory."""
import datetime as dt
from collections import Counter
from contextlib import closing
from functools import lru_cache, wraps
import json
import hmac
import math
from pathlib import Path
import secrets
from zoneinfo import ZoneInfo

from flask import g, jsonify, Blueprint, abort, flash, get_flashed_messages, redirect, render_template, request, session, url_for

import integrale_edof_associations as associations
import integrale_edof_views as views
import integrale_edof_history as history_view
import edof_directory as directory
import edof_dossier_dates as dossier_dates
from integrale_edof_sync import dates_for_view
from edof_schedule import scheduled_at
import edof_throttle as throttle
import edof_declarations as declarations
import edof_proposal as proposal_form
import edof_proposal_jobs as proposals
from cpf_provider import PROVIDERS, ProviderStore, ProviderUnavailable, on_test_service, on_production_service, provider_operation
from cpf_entry_pilot import active_holds, blocks_pilot
from cpf_provider_bridge import coordinated_switch, production_request
from edof_matching import build_comparison, manual_options
from edof_readonly_test import ID_RE
from edof_server_browser import DETAIL_PREFIX
from integrale_edof_registration import create_registration, eligible_sessions
from integrale_edof_transfers import TARGETS, receipt, transfer
from wedof_links import save_manual_wedof_link

PARIS = ZoneInfo("Europe/Paris")
SECTIONS = {"state": "Dossiers CPF", "automations": "Automatisations",
            "consumption": "Historique des automatisations", "technical": "Connexion et paramètres techniques"}
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
REQUEST_TABS = {"request":"À traiter", "waiting":"En attente de validation du titulaire",
                "ft":"Financement FT en cours", "ft_refused":"Financement FT refusé", "accepted":"Accepté", "refused":"Refusé", "canceled":"Annulé"}
AUTOMATION_TABS = {"due":"Automatisations prévues", "training":"En formation", "entry":"Entrée déclarée",
                   "out":"Sortie déclarée", "declared":"Service fait déclaré", "billable":"À facturer (service fait validé)",
                   "invoiced":"Facturé", "paid":"Payé"}
SECTION_TABS = {"requests": REQUEST_TABS, "automations": AUTOMATION_TABS}
LABELS.update({**REQUEST_TABS, **AUTOMATION_TABS})
LABELS.update({"accepted": "Accepté / À démarrer", "entry": "En formation",
               "invoiced": "Facturé · En attente de paiement"})
STATE_KEYS.update({
    "entry":{"intraining", "in training", "entree declaree", "entree en formation declaree"},
    "declared":{"servicedonedeclared", "service done declared", "service done declared revised", "servicedonedeclaredrevised", "service fait declare", "service fait declare revise"},
    "billable":{"servicedonevalidated", "service done validated", "service done validated revision vsf", "servicedonevalidatedrevisionvsf", "service fait valide"},
    "paid":{"paid", "paye", "payee"},
    "ft_refused":{"financement ft refuse", "financement france travail refuse", "demande de financement france travail refusee", "demande de financement ft refusee"},
    "ft":{"financement ft en cours", "financement france travail en cours", "waitingforfrancetravailvalidation", "pendingfrancetravail", "demande de financement ft en cours", "demande de financement france travail en cours"},
})
STATE_KEYS["waiting"].update({"waitingforattendeevalidation", "en attente de validation du titulaire"})
STATE_KEYS["out"].add("terminated")
STATE_KEYS["canceled"].update({"canceledbycdc", "abandonnedbyattendeeatstepvalidated"})
STATE_KEYS["refused"].update({"rejectedwithouttitulairesuite", "rejectedwithoutcdcsuite", "rejectedwithoutofsuite"})
STATES = {raw: key for key, aliases in STATE_KEYS.items() for raw in aliases}
SIMULATION = {"planned": "Échéance à venir", "ready": "Déclaration préparée",
              "unconfirmed": "Déclaration à compléter", "blocked": "Blocage administrateur", "missing": "Date à vérifier"}
ACTIONS = {"accepted": "entry_training", "training": "service_done", "entry": "service_done", "out": "service_done"}
ACTION_LABELS = {"entry_training": "Entrée en formation", "service_done": "Sortie et service fait", "both": "Entrée et sortie"}
BLOCK_REASONS = {"no_show": "Absence", "postponed": "Report", "abandonment": "Abandon",
                 "partial_completion": "Parcours partiel", "administrative_issue": "Vérification administrative", "other": "Autre motif"}


def category(row):
    raw = directory.normalized(row.get("state") or "")
    billing = directory.normalized(row.get("billing_state") or "")
    payment = directory.normalized(row.get("payment_state") or "")
    if raw in STATE_KEYS["paid"] or billing in STATE_KEYS["paid"] or payment in STATE_KEYS["paid"] | {"issued"}:
        return "paid"
    if raw in STATE_KEYS["invoiced"] or billing in STATE_KEYS["invoiced"]:
        return "invoiced"
    if raw in STATE_KEYS["billable"] or row.get("service_done_validated") is True:
        return "billable"
    if raw in STATE_KEYS["waiting"] | STATE_KEYS["request"] | STATE_KEYS["ft"]:
        if row.get("ft_pending"):
            return "ft"
        if row.get("ft_refused"):
            return "ft_refused"
    if raw.startswith(("annule par ", "annulee par ", "annulation par ")):
        return "canceled"
    return STATES.get(raw, "unknown")


ASSOCIABLE_KINDS = {"accepted", "training", "entry", "declared", "billable"}


def associable(row):
    return (category(row) in ASSOCIABLE_KINDS
            and STATES.get(directory.normalized(row.get("state") or "")) in ASSOCIABLE_KINDS)


def apply_confirmed_entries(snapshot, directory_path, owner):
    if not snapshot:
        return snapshot
    with closing(declarations.database(directory_path)) as db:
        verified = db.execute("""SELECT folder, action, intent, changed FROM cpf_declarations
            WHERE owner=? AND status='confirmed' AND changed>?
            ORDER BY changed""", (owner, snapshot.get("checked") or 0)).fetchall()
    rows = dict(snapshot["rows"])
    for record in verified:
        row = rows.get(record["folder"])
        intent = json.loads(record["intent"])
        if (not row or not declarations.same_enrolment(row, intent)
                or (row.get("observed_at") or 0) > record["changed"]):
            continue
        kind = category(row)
        if record["action"] == "entry_training" and kind == "accepted":
            # Older entry receipts predate storage of the exact state from EDOF.
            state = intent.get("confirmed_state") or "Entrée déclarée"
            extra = {"entry_confirmed_on": intent["actual_date"]}
        elif (record["action"] == "service_done" and intent.get("confirmed_state")
              and kind in {"accepted", "training", "entry", "out"}):
            state = intent["confirmed_state"]
            extra = {"end_date": intent["actual_date"], "completion_rate": intent["rate"]}
        else:
            continue
        rows[record["folder"]] = {**row, **extra, "state": state,
                                  "filed_at": dossier_dates.source_dates(row, category)[0],
                                  "state_at": "", "request_date": "", "observed_at": record["changed"]}
    return {**snapshot, "rows": rows}


def folder_for_matching(row):
    return {"external_id": row["folder_id"], "type": "cpf", "first_name": row.get("first_name"),
            "last_name": row.get("last_name"), "email": row.get("email"), "training_title": row.get("title"),
            "state": {"accepted": "accepted", "training": "inTraining", "entry":"inTraining"}.get(category(row), row.get("state")),
            "start_date": row.get("session_start_date"), "end_date": row.get("session_end_date")}


def active_blocks(data):
    return {(str(x.get("external_id")), x.get("action")): x for x in data.get("wedof_automation_blocks", [])
            if isinstance(x, dict) and x.get("active")}


def scheduled_time(kind, date):
    return scheduled_at(ACTIONS.get(kind), date)


def simulate(kind, date, block, draft, now):
    if kind not in ACTIONS:
        return None
    if block:
        return "blocked"
    scheduled = scheduled_time(kind, date)
    if scheduled is None:
        return "missing"
    if scheduled > now:
        return "planned"
    return "ready"



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
        if kind == "entry":
            tags.add("training")
        if kind in {"declared", "billable"}:
            tags.add("service")
        if kind == "request" and "pending_ids" in snapshot and folder not in snapshot["pending_ids"]:
            tags.discard("request")
        if evaluation in {"planned", "unconfirmed", "ready"}:
            tags.add("due")
        if folder not in links:
            if flags.get("association_ignored"):
                tags.add("association_ignored")
            elif associable(record):
                tags.add("unlinked")
        if block or kind == "unknown" or (action and not date):
            tags.add("anomaly")
        counts.update(tags)
        rows.append({**record, "kind": kind, "label": LABELS[kind] if kind != "unknown" else record.get("state") or LABELS[kind],
                     "scheduled": scheduled_time(kind, date), "action": action, "due": due, "evaluation": evaluation, "block": block, "tags": tags, "link": links.get(folder),
                     "associable": associable(record), "association_ignored": bool(flags.get("association_ignored")), "handled": bool(flags.get("handled")), "archived": bool(flags.get("archived")),
                     "draft": flags.get("draft"), "official_url": DETAIL_PREFIX + folder})
    return rows, counts


def prioritize_rows(rows, now):
    """Sort pending declarations by their Paris deadline before slicing a page."""
    instant = now.timestamp()

    def deadline_order(row):
        scheduled = row["scheduled"]
        if scheduled is not None and not row["block"]:
            timestamp = scheduled.timestamp()
            return (0, abs(timestamp - instant), timestamp, row["folder_id"])

        waiting = row["kind"] in {"request", "waiting", "ft"}
        date = row.get("session_start_date") if waiting else row.get("session_end_date") or row.get("session_start_date")
        if date:
            day = dt.date.fromisoformat(date)
            if waiting:
                return (1, abs((day - now.date()).days), day.toordinal(), row["folder_id"])
            return (2, -day.toordinal(), 0, row["folder_id"])
        return (3, 0, 0, row["folder_id"])

    rows.sort(key=deadline_order)


def operations_db(store):
    db = store.connect()
    db.execute("""CREATE TABLE IF NOT EXISTS dossier_work (folder TEXT PRIMARY KEY, handled INTEGER DEFAULT 0,
                  archived INTEGER DEFAULT 0, draft TEXT, updated TEXT, actor TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS dossier_association_preferences
                  (folder TEXT PRIMARY KEY, ignored INTEGER NOT NULL DEFAULT 0, updated TEXT, actor TEXT)""")
    return db


def ignored_associations(store):
    with closing(operations_db(store)) as db:
        return {row[0] for row in db.execute("SELECT folder FROM dossier_association_preferences WHERE ignored=1")}


def record_association_preference(store, folder, actor, ignored):
    with closing(operations_db(store)) as db, db:
        db.execute("""INSERT INTO dossier_association_preferences VALUES(?,?,?,?)
                      ON CONFLICT(folder) DO UPDATE SET ignored=excluded.ignored, updated=excluded.updated, actor=excluded.actor""",
                   (folder, int(ignored), dt.datetime.now(PARIS).isoformat(), actor))


def local_operations(store):
    with closing(operations_db(store)) as db:
        result = {}
        for row in db.execute("SELECT * FROM dossier_work"):
            draft = json.loads(row["draft"]) if row["draft"] else None
            # Legacy exercise drafts cannot establish a different start date.
            result[row["folder"]] = {**dict(row), "draft": None if draft and draft.get("source") == "lms" else draft}
        for row in db.execute("SELECT folder,ignored FROM dossier_association_preferences"):
            result.setdefault(row["folder"], {})["association_ignored"] = bool(row["ignored"])
        return result


def record_work(store, folder, actor, **changes):
    if not changes or not set(changes) <= {"handled", "archived", "draft"}:
        raise ValueError("Action CPF inconnue.")
    with closing(operations_db(store)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if changes.get("draft") and db.execute("SELECT 1 FROM sqlite_master WHERE name='cpf_declarations'").fetchone():
            draft = json.loads(changes["draft"])
            if draft.get("source") == "admin":
                db.execute("""UPDATE cpf_declarations SET status='paused', changed=?
                    WHERE folder=? AND action=? AND status='queued' AND json_extract(intent,'$.source')='edof_schedule'
                      AND json_extract(intent,'$.exit_confirmed') IS NULL""",
                    (dt.datetime.now(PARIS).timestamp(), folder, draft["action"]))
        db.execute("INSERT OR IGNORE INTO dossier_work(folder) VALUES (?)", (folder,))
        updates = {**changes, "updated": dt.datetime.now(PARIS).isoformat(), "actor": actor}
        db.execute("UPDATE dossier_work SET " + ", ".join(k + "=?" for k in updates) + " WHERE folder=?",
                   (*updates.values(), folder))


def declaration_draft(row, fields, *, require_reference=False):
    action = ACTIONS.get(category(row))
    if not action or fields.get("action") != action or fields.get("attested") != "yes":
        raise ValueError("Le dossier doit être déclarable et sa réalisation effective confirmée.")
    date = row.get("session_start_date" if action == "entry_training" else "session_end_date")
    if not date or fields.get("actual_date") != date:
        raise ValueError("La date doit correspondre à celle du dossier EDOF. Actualisez la fiche.")
    if dt.date.fromisoformat(date) > dt.datetime.now(PARIS).date():
        raise ValueError("La date du dossier EDOF ne peut pas être future.")
    if action == "service_done" and (str(fields.get("rate")) != "100" or fields.get("motif")
                                     or (fields.get("reason") or "").strip()):
        raise ValueError(declarations.REASONS["declaration_terms_mismatch"])
    evidence = fields.get("evidence", "").strip()
    if (evidence or require_reference) and not 3 <= len(evidence) <= 250:
        raise ValueError("Indiquez la référence du justificatif (3 à 250 caractères).")
    result = {"action": action, "actual_date": date, "evidence": evidence, "operator_confirmed": True}
    if action == "service_done":
        result["rate"] = 100
    return result


def entry_choice(row):
    # Bind the selection to the person and session dates shown on the page.
    return json.dumps([row.get(k) for k in ("folder_id","first_name","last_name","session_start_date","session_end_date")],
                      ensure_ascii=False, separators=(",",":"))


def register_dashboard(app, legacy, store, *, results_owner, vault, gmail_status, admin_required, check_csrf):
    bp = Blueprint("integrale_edof", __name__, url_prefix="/admin/integrale-edof" if on_production_service() else "/admin/edof-test")
    selection = ProviderStore(store.directory)
    partner_id = getattr(legacy, "INTEGRALE_PARTNER_ID", "integrale")
    is_cancelled = getattr(legacy, "_trainee_registration_is_cancelled", lambda t: bool(t.get("registration_cancelled")))

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
                if request.accept_mimetypes.best == "application/json":
                    return jsonify(message=str(exc)), 409
                flash(str(exc), "error")
                return back(request.form.get("section") or "state")
        return admin_required(guarded)

    def back(section="state", **kwargs):
        return redirect(url_for("integrale_edof.index", section=section if section in {*SECTIONS, "requests", "cancellations"} else "state", **kwargs), code=303)

    def snapshot(owner):
        saved = vault().get(directory.record_key(owner), keep=True) if store.connector_key else None
        # Previously synchronized dossiers also contain French display dates.
        pending = vault().get(directory.pending_key(owner)) if store.connector_key else None
        accepted = vault().get(directory.accepted_key(owner)) if store.connector_key else None
        combined = directory.with_accepted(directory.with_pending(saved, pending), accepted)
        return proposals.with_receipts(store.directory, owner, apply_confirmed_entries(combined, store.directory, owner))

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
        for group in associations.eligible_groups(data, partner_id, is_cancelled, include_cancelled=True):
            summary = {key:group[key] for key in ("id", "name", "training_type", "date_start", "date_end",
                  "date_debut", "date_fin", "partner_id", "archived", "is_archived", "status") if key in group}
            summary["trainees"] = [{**{key:t[key] for key in ("id","first_name","last_name","prenom","nom","email","mail")
                                    if key in t}, "registration_cancelled": is_cancelled(t)} for t in (group.get("trainees") or group.get("stagiaires") or []) if isinstance(t,dict)]
            sessions.append(summary)
        return {"sessions": sessions, "wedof_links": data.get("wedof_links", []),
                "wedof_automation_blocks": data.get("wedof_automation_blocks", [])}

    def local_data(*, include_cancelled=False):
        try:
            st = Path(legacy.DATA_FILE).stat()
        except FileNotFoundError:
            return {}
        data = local_projection((st.st_ino, st.st_mtime_ns, st.st_size))
        return data if include_cancelled else {**data, "sessions": list(associations.eligible_groups(data, partner_id, is_cancelled))}

    def enrich(owner, row):
        previous = store.successful_read(owner, spec={"folder_id": row["folder_id"], "first_name": "", "last_name": ""})
        fields = previous["fields"] if previous else {}
        if fields and all(directory.normalized(fields.get(k) or "") == directory.normalized(row.get(k) or "")
                          for k in ("first_name", "last_name")):
            enriched = {**row, "email": fields.get("email", "")}
            start = fields.get("session_start_date")
            if category(row) == "request" and (not start or start >= directory.FIRST_SESSION) and not any(
                row.get(k) and fields.get(k) and row[k] != fields[k]
                for k in ("session_start_date", "session_end_date", "title")
            ):
                summary = {key:fields[k] for k,key in (("total_incl","priceTotal"), ("duration_hours","indicativeDuration"),
                                                       ("center_hours","hoursInCenter")) if fields.get(k) is not None}
                enriched["offer_summary"] = {**summary, **(row.get("offer_summary") or {})}
                for k in ("session_start_date", "session_end_date"):
                    enriched[k] = row.get(k) or fields.get(k) or ""
            return enriched
        return row

    def find_matches(data, records):
        ignored = ignored_associations(selection)
        return associations.match_unlinked(data, {k:r for k,r in records.items() if associable(r) and k not in ignored}, partner_id, is_cancelled, folder_for_matching, store.connector_key)

    def reconcile(records):
        matches = find_matches(local_data(), records)
        if not any(m["status"] == "exact_match" for m in matches.values()):
            return len(matches), 0
        # Recheck both sides of every association under the application's write lock.
        outcome = {}
        def apply(data):
            current = find_matches(data, records)
            outcome.update(examined=len(current), created=associations.synchronize(data, current))
            return {}
        legacy._atomic_update_data(apply)
        return outcome["examined"], outcome["created"]

    def nightly_associations(now):
        with provider_operation("integrale"):
            return associations.nightly(store, now, snapshot, reconcile)

    @bp.get("/inscriptions/<session_id>/<trainee_id>/recherche-cpf")
    @admin_required
    def trainee_search(session_id, trainee_id):
        owner = results_owner()
        data = local_data()
        group = next((g for g in data.get("sessions", []) if str(g.get("id")) == session_id), None)
        trainee = next((t for t in (group or {}).get("trainees", []) if str(t.get("id")) == trainee_id), None)
        if not trainee:
            abort(404)
        snap = snapshot(owner)
        records = associations.observed_rows(store, owner, snap)
        csrf = session.setdefault("edof_server_csrf", secrets.token_urlsafe(32))
        query = request.args.get("q", "").strip()[:120]
        results = []
        # Compare only this registration, while keeping every existing CPF link for conflict checks.
        subset = {"sessions": [{**group, "trainees":[trainee]}], "wedof_links": [
            l for l in data.get("wedof_links", []) if l.get("active") and str(l.get("session_id")) == session_id
            and str(l.get("trainee_id")) == trainee_id]}
        linked = {str(l.get("external_id")) for l in data.get("wedof_links", []) if l.get("active")}
        ignored = ignored_associations(selection)
        for folder, row in records.items():
            if not associable(row) or folder in ignored:
                continue
            words = directory.normalized(" ".join(str(row.get(k) or "") for k in ("folder_id","first_name","last_name","title")))
            if query and not all(w in words.split() for w in directory.normalized(query).split()):
                continue
            observed = {**row, "email": associations.verified_email(row, [trainee], store.connector_key)}
            checks = manual_options(subset, observed, pair=(session_id, trainee_id))[0]
            if query or checks["identity_match"] or checks["email_match"]:
                results.append({"row":row, "checks":checks, "linked":folder in linked})
        results.sort(key=lambda r: (not r["checks"]["concordant"], not r["checks"]["identity_match"],
                                    not r["checks"]["dates_match"], r["row"]["folder_id"]))
        pages = max(1, math.ceil(len(results) / 25))
        page = max(1, min(request.args.get("page", 1, type=int) or 1, pages))
        return render_template("edof_trainee_search.html", title="Recherche CPF · Intégrale EDOF",
            group=group, trainee=trainee, results=results[(page-1)*25:page*25], page=page, pages=pages,
            query=query, csrf=csrf, synced=bool(snap), active=selection.state()["provider"]=="integrale")

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
        state = store.live_connection(owner, saved)
        if request.args.get("catchup") == "1":
            state["catchup"] = store.catchup_status(owner)
        return jsonify(state)

    @bp.get("")
    @admin_required
    def index():
        owner = results_owner()
        g.edof_nonce = secrets.token_urlsafe(24)
        csrf = session.setdefault("edof_server_csrf", secrets.token_urlsafe(32))
        section, group, tabs, tab = views.navigation(request.args)
        if section not in SECTIONS:
            abort(404)
        snap = snapshot(owner)
        if snap:
            store.use_directory(owner)
        now = dt.datetime.now(PARIS)
        today = now.date().isoformat()
        data = local_data() if snap and section in {"state", "automations", "consumption"} else {}
        data = dict(data)
        held = declarations.folder_holds(store.directory)
        if held:
            data["wedof_automation_blocks"] = [*data.get("wedof_automation_blocks", []),
                *({"external_id":f,"action":"both","active":True,"reason_code":"administrative_issue"} for f in held)]
        rows, counts = dashboard_rows(snap, data, local_operations(selection), now)
        unlinked_count = counts["unlinked"]
        ignored_count = counts["association_ignored"]
        all_rows = rows
        folder = request.args.get("folder", "")
        if rows and (section == "state" or folder):
            with closing(selection.connect()) as db:
                saved_dates = dates_for_view(db, owner, rows, snap.get("checked", 0), category)
            dossier_dates.annotate(rows, saved_dates, snap.get("checked", 0), category)
        selected_row = next((r for r in rows if r["folder_id"] == folder), None) if folder else None
        previewing = section == "state" and request.args.get("matching") == "1"
        matches = find_matches(data, associations.observed_rows(store, owner, snap)) if previewing else {}
        if previewing:
            rows = [r for r in rows if r["folder_id"] in matches]
        testing = section == "state" and request.args.get("simulation") == "1"
        simulation = Counter(r["evaluation"] for r in rows if r["evaluation"])
        if testing:
            rows = [r for r in rows if r["evaluation"]]
        q = directory.normalized(request.args.get("q", "")[:140])
        course = request.args.get("course", "")[:500]
        period = request.args.get("period", "")[:40]
        courses = sorted({r.get("title") or "" for r in rows if r.get("title")})
        periods = sorted({views.period_key(r) for r in rows if (not course or r.get("title") == course)
                          and (r.get("session_start_date") or r.get("session_end_date"))}, reverse=True)
        rows = [r for r in rows if (not course or r.get("title") == course)
                and (not period or views.period_key(r) == period)]
        if q:
            rows = [r for r in rows if q in directory.normalized(" ".join(str(r.get(k) or "") for k in
                    ("folder_id", "first_name", "last_name", "last_name", "first_name", "title", "label")))]
        groups_count = views.group_counts(rows)
        # Dossier counts describe dossiers. Operation counts are computed from the ledger below.
        if section == "state":
            rows = [r for r in rows if views.in_group(r, group)]
            counts = Counter(tag for r in rows for tag in r["tags"])
            rows = [r for r in rows if tab in r["tags"]]
        detail = None
        if folder:
            if not ID_RE.fullmatch(folder) or not selected_row:
                abort(404)
            record = enrich(owner, snap["rows"][folder])
            if not data:
                data = local_data()
            detail = {"record": record, "display": selected_row, "comparison": build_comparison(data, record)}
            detail["query"] = request.args.get("inscription","")[:120].strip()
            if detail["query"]:
                detail["comparison"] = {**detail["comparison"], "status":"manual_search",
                                        "candidates":manual_options(data, record, query=detail["query"])}
            detail["key"] = directory.link_key(owner, folder)
            detail["draft"] = local_operations(selection).get(folder, {}).get("draft")
            detail["action"] = ACTIONS.get(category(record))
            detail["request"] = category(record) == "request"
            detail["proposal_job"] = proposals.record(store.directory,folder,owner)
            if detail["proposal_job"] and detail["proposal_job"].get("result_code") == "portal_throttled" and store.connector_key:
                detail["proposal_job"]["message"] = throttle.message(vault())
            if detail["proposal_job"]:
                detail["proposal_status_url"] = url_for("integrale_edof.proposal_send_status", folder=folder,
                                                       ticket=detail["proposal_job"]["token"])
            if detail["request"]:
                detail["proposal_values"] = proposal_form.initial(record)
                detail["proposal_connector"] = bool(store.connector_key)
            if detail["request"] and store.connector_key:
                private = vault()
                source = private.get(proposals.source_key(owner,folder))
                detail["proposal_source"] = source
                detail["proposal_options"] = private.get(proposals.option_key(owner)) or {}
                stored = private.get("proposal-draft:"+owner+":"+folder) or {}
                values = proposal_form.displayed(source,record)
                if not stored.get("signature") or source and stored["signature"] == source["signature"]:
                    values.update(stored.get("values",{}))
                detail["proposal_values"] = values
                read_job = request.args.get("proposal_read", "")
                if read_job:
                    read = proposals.read_ticket(store.directory,owner,folder,read_job)
                    if read:
                        detail["proposal_reading"] = read["status"] in {"queued","reading"}
                        detail["proposal_poll_url"] = url_for("integrale_edof.proposal_read_status", folder=folder, ticket=read_job)
                        detail["proposal_read_note"] = read["message"] or "Lecture des conditions de l’offre en attente du connecteur EDOF."
                detail["proposal_auto_load"] = request.args.get("prepare")=="1" and not read_job and not source

            detail["held"] = folder in held
            detail["transfers"] = {target:receipt(selection, folder, target) for target in TARGETS} if detail["request"] else {}
            detail["official"] = DETAIL_PREFIX + folder
            detail["accepted"] = category(record) == "accepted"
            if detail["accepted"]:
                job = store.successful_read(owner, spec={"folder_id":folder,"first_name":"","last_name":""})
                detail["import_error"] = job and job.get("import_error")
                options = eligible_sessions(data, getattr(legacy, "INTEGRALE_PARTNER_ID", "integrale"))
                def session_order(group):
                    day = directory.session_date(group.get("date_start") or group.get("date_debut"))
                    return (day != record.get("session_start_date"), day, group.get("name") or "")
                detail["sessions"] = sorted(options, key=session_order)
                detail["link"] = next((r for r in data.get("wedof_links", []) if r.get("active") and str(r.get("external_id")) == folder), None)
        gmail = gmail_status()
        selected = selection.state()
        from edof_server_test import MESSAGES
        dispatches = declarations.records(store.directory)
        visible_folders = (snap or {}).get("rows", {})
        dispatches = [d for d in dispatches if d["folder"] in visible_folders]
        catchup = None
        history, history_alerts = None, Counter()
        if section == "consumption" and not detail:
            history = history_view.page(store, owner, snap, request.args)
            catchup = store.catchup_status(owner, include_outcomes=True)
            operations = views.operation_rows(all_rows, dispatches, now, selected["revision"], (catchup or {}).get("outcomes"))
            history_alerts = Counter(r["operation_bucket"] for r in operations
                                     if r["operation_bucket"] in {"overdue", "attention", "blocked"})
        if section == "automations" and not detail:
            catchup = store.catchup_status(owner, include_outcomes=True)
            rows = views.operation_rows(rows, dispatches, now, selected["revision"], (catchup or {}).get("outcomes"))
            counts = Counter(r["operation_bucket"] for r in rows)
            counts["today"] = sum(r["scheduled_today"] for r in rows)
            if tab == "today":
                rows = sorted((r for r in rows if r["scheduled_today"]), key=lambda r: (r["scheduled"], r["folder_id"]))
            elif tab == "due":
                rows = [r for r in rows if "due" in r["tags"] and r["operation_bucket"] != "history"]
                prioritize_rows(rows, now)  # Preserve the scope/order of old bookmarked links.
            else:
                rows = [r for r in rows if r["operation_bucket"] == tab]
                views.sort_operations(rows)
            for row in rows:
                if (row["kind"] == "accepted" and row["action"] == "entry_training"
                        and row["operation_bucket"] == "overdue" and not row["dispatch_status"]
                        and row["evaluation"] == "ready" and row["catchup_outcome"] not in {"blocked", "review"}):
                    row["entry_choice"] = entry_choice(row)
        elif section == "state":
            dossier_dates.newest_first(rows)
        pages = max(1, math.ceil(len(rows) / 25))
        page = max(1, min(request.args.get("page", 1, type=int) or 1, pages))
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
        if detail and aligned and selected["provider"] == "wedof" and (on_test_service() or on_production_service()):
            try:
                pilot = declarations.pilot_state(folder)
                detail["pilot"] = pilot
                detail["pilot_ready"] = declarations.matches_pilot(detail["record"], pilot)
                proof = pilot.get("proof") or {}
                if declarations.same_enrolment(detail["record"], proof) and proof.get("entry_training"):
                    detail["pilot_proof"] = proof["entry_training"]
            except (ValueError, ProviderUnavailable) as exc:
                detail["pilot_error"] = str(exc)
        return render_template("integrale_edof.html", proposal_fields=proposal_form, proposal_status=proposals.LABELS, title="Intégrale EDOF · Pilotage CPF",
            selection=selected, production=production, bridge_error=bridge_error, aligned=aligned, providers=PROVIDERS, sections=SECTIONS, section=section, tabs=tabs, tab=tab,
            unlinked_count=unlinked_count, ignored_count=ignored_count, has_snapshot=bool(snap), groups=views.GROUPS, group=group, group_counts=groups_count, course=course, courses=courses,
            period=period, periods=periods, operation_tabs=views.AUTOMATION_TABS,
            dispatch_labels=declarations.LABELS, dispatch_reasons=MESSAGES, motifs=declarations.MOTIFS,
            inspection=check, dispatches=dispatches, csrf=csrf, flashes=get_flashed_messages(with_categories=True), previewing=previewing, matches=matches,
            match_counts=Counter(m["status"] for m in matches.values()), total=len(rows), counts=counts,
            rows=rows[(page-1)*25:page*25], page=page, pages=pages, query=request.args.get("q", "")[:140], simulation=simulation, testing=testing, simulation_labels=SIMULATION,
            catchup=catchup, history=history, history_alerts=history_alerts,
            detail=detail, labels=LABELS, checked=(directory.stamp({"checked":snap["pending_checked"]}) if snap and snap.get("pending_checked") and tab=="request" else directory.stamp({"checked":snap["accepted_checked"]}) if snap and snap.get("accepted_checked") and tab=="accepted" else directory.stamp(snap) if snap and snap.get("checked") else directory.stamp({"checked":snap["receipt_checked"]}) if snap and snap.get("receipt_checked") and tab!="request" else None), today=today,
            live=store.live_connection(owner, gmail["saved_session"], snapshot=snap), nonce=g.edof_nonce, jobs=store.latest(owner), efp=store.connection_status(owner, gmail["saved_session"]), gmail=gmail,
            scope=(snap or {}).get("scope", "open"), directory_enabled=store.directory_enabled(owner), snapshot_count=len((snap or {}).get("rows", {})),
            held=held, block_reasons=BLOCK_REASONS, action_labels=ACTION_LABELS,
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
            return back("technical")
        # Exactly one initial refresh per deliberate activation, including
        # after several weeks away. A failed sign-in cannot reschedule itself.
        if target == "integrale" and result["revision"] != revision:
            store.request_directory(owner)
        flash(f"{PROVIDERS[target]} est actif pour votre établissement. Bascule confirmée.", "success")
        return back("technical")

    @bp.post("/automatisations/rattraper")
    @native_action
    def catch_up(owner):
        selected = selection.state()
        if selected["revision"] != request.form.get("revision", type=int):
            raise ValueError("Le système CPF a changé. Actualisez la page avant de relancer.")
        if not store.connector_key or not gmail_status()["connected"]:
            raise ValueError("Connectez EFP et Gmail avant de lancer le rattrapage.")
        store.queue_sync(owner, "all", catchup_revision=selected["revision"])
        if request.accept_mimetypes.best == "application/json":
            return jsonify(requested=store.catchup_status(owner)["requested"], message="Rattrapage demandé. La liste EDOF sera vérifiée avant les déclarations."), 202
        return back("automations", tab="overdue", _anchor="rattrapage")

    @bp.post("/automatisations/entrees-effectives")
    @native_action
    def confirm_entries(owner):
        revision = selection.state()["revision"]
        if request.form.get("revision", type=int) != revision:
            raise ValueError("Le système CPF a changé. Actualisez la liste.")
        choices = set(request.form.getlist("entry"))
        if request.form.get("attested") != "yes" or not 1 <= len(choices) <= 25:
            raise ValueError("Sélectionnez les stagiaires ayant commencé à la date affichée.")
        snap = snapshot(owner) or {}
        blocks = active_blocks(local_data())
        now = dt.datetime.now(PARIS)
        actor = session.get("admin_username") or owner
        pending = 0
        for row in snap.get("rows", {}).values():
            if entry_choice(row) not in choices or category(row) != "accepted":
                continue
            folder, start = row["folder_id"], row.get("session_start_date")
            blocked = blocks.get((folder,"both")) or blocks.get((folder,"entry_training"))
            if simulate("accepted",start,blocked,None,now) != "ready":
                continue
            try:
                draft = declaration_draft(row, {"action":"entry_training","actual_date":start,"attested":"yes"})
                status = declarations.enqueue(store.directory,owner,revision,row,draft,actor,automatic=True)
            except ValueError:
                continue
            pending += status == "queued"
        flash(f"Entrées en file de transmission : {pending}. Déjà traitées, bloquées ou à revoir : {len(choices)-pending}.", "success")
        return back("automations", tab="overdue", page=request.form.get("page", 1, type=int), q=request.form.get("q","")[:140])

    @bp.post("/associate-reliable")
    @native_action
    def associate_reliable(owner):
        snap = snapshot(owner)
        if snap is None:
            raise ValueError("Synchronisez d’abord la liste EDOF.")
        examined, created = reconcile(associations.observed_rows(store, owner, snap))
        flash(f"{created} association(s) créée(s) sur {examined} dossier(s) examinés.", "success")
        return back()

    @bp.post("/dossiers/<folder>/association-preference")
    @native_action
    def association_preference(owner, folder):
        folder_record(owner, folder)
        if request.form.get("ignore") not in {None, "1"}:
            abort(400)
        ignored = request.form.get("ignore") == "1"
        record_association_preference(selection, folder, session.get("admin_username") or owner, ignored)
        message = ("Dossier masqué de À associer et exclu du rapprochement automatique."
                   if ignored else "Dossier réintégré aux associations selon son statut.")
        if request.accept_mimetypes.best == "application/json":
            return jsonify(ok=True, ignored=ignored, message=message)
        flash(message, "success")
        return back(group="all", tab="association_ignored" if not ignored else "unlinked")

    @bp.get("/dossiers/<folder>/inscriptions")
    @admin_required
    def association_options(folder):
        owner = results_owner()
        try:
            row = enrich(owner, folder_record(owner, folder))
        except ValueError as exc:
            return jsonify(message=str(exc)), 404
        if folder in ignored_associations(selection):
            return jsonify(message="Réaffichez ce dossier dans À associer avant de l’associer."), 409
        if not associable(row):
            return jsonify(message="Ce statut ne permet pas d’associer le dossier."), 409
        data = local_data(include_cancelled=True)
        query = request.args.get("q", "").strip()[:120]
        choices = (manual_options(data, row, query=query) if query else build_comparison(data, row)["candidates"])
        items = []
        for c in choices:
            items.append({**c, "session_archived":c["archived"], "session_training_type":c["training_type"],
                          "session_date_start":c["start_date"], "session_date_end":c["end_date"],
                          "match_reason":" · ".join([*c["issues"], *(check["label"] for check in c["checks"])]),
                          "blocked":bool([issue for issue in c["issues"] if issue != "Cette session est archivée."])})
        return jsonify(items=items, total=len(items))

    @bp.post("/dossiers/<folder>/associate")
    @native_action
    def associate(owner, folder):
        if folder in ignored_associations(selection):
            raise ValueError("Réaffichez ce dossier dans À associer avant de l’associer.")
        row = enrich(owner, folder_record(owner, folder))
        if not associable(row):
            raise ValueError("Ce statut ne permet pas d’associer le dossier.")
        sid, tid = request.form.get("session_id"), request.form.get("trainee_id")
        outcome = []
        def apply(data):
            scoped = {**data, "sessions": list(associations.eligible_groups(data, partner_id, is_cancelled))}
            choices = manual_options(scoped, row, pair=(sid, tid))
            if len(choices) != 1 or any(i != "Cette session est archivée." for i in choices[0]["issues"]) or request.form.get("verified") != "yes":
                raise ValueError("Vérifiez l’identité, la session et les éventuels conflits avant d’associer.")
            choice = choices[0]
            if (choice["dates_match"] is not True or choice["archived"]) and request.form.get("confirm_date_mismatch") != "1":
                raise ValueError("Confirmez les dates différentes ou la session archivée avant d’associer.")
            result = save_manual_wedof_link(data, external_id=folder, session_id=sid, trainee_id=tid,
                       state=folder_for_matching(row)["state"], date_start=row.get("session_start_date"), date_end=row.get("session_end_date"))
            if result == "conflict":
                raise ValueError("Ce dossier ou cette inscription possède déjà une autre association.")
            outcome.append(result)
            return data
        legacy._atomic_update_data(apply)
        if request.accept_mimetypes.best == "application/json":
            return jsonify(ok=True, message="Association locale enregistrée.")
        flash("Association locale enregistrée." if outcome == ["created"] else "Association déjà enregistrée.", "success")
        if request.form.get("return_to_trainee") == "1":
            return redirect(url_for("admin_trainee_page", session_id=sid, trainee_id=tid, _anchor="cpfTracking"), code=303)
        return back(folder=folder)

    def proposal_back(folder, **extra):
        return back("requests",tab="request",folder=folder,_anchor="proposition-edof", **extra)

    def proposal_progress(owner, folder, work):
        status = work["status"]
        message = work["message"] or {
            "queued":"La transmission démarre dès que la connexion EDOF est disponible.",
            "saving":"Les conditions de formation sont en cours d’enregistrement sur EDOF.",
            "validating":"La proposition est transmise au titulaire. Nous attendons la réponse d’EDOF.",
            "checking":"La réception est vérifiée sur EDOF, sans renvoyer la proposition.",
            "confirmed":"La proposition a été envoyée et sa réception confirmée par EDOF.",
            "error":"La transmission n’a pas abouti. Vérifiez les informations du dossier.",
            "uncertain":"La réponse n’est pas certaine. Vérifiez la réception avant tout nouvel envoi.",
        }[status]
        if work.get("result_code") == "portal_throttled":
            message = throttle.message(vault())
        if status == "queued":
            with closing(store.connect()) as db:
                active_job = db.execute("SELECT mode FROM jobs WHERE finished IS NULL ORDER BY created DESC LIMIT 1").fetchone()
            if active_job:
                message = ("Connexion et vérification des conditions du dossier sur EDOF." if active_job["mode"] in {"proposal_send","proposal_check"}
                           else "Une opération EDOF est déjà en cours. Votre dossier sera transmis dès qu’elle se termine.")
        stopped_before_send = status == "error" and not work["phase"] and (
            work["result_code"] in {"read_unconfirmed", "proposal_read_unavailable"} or message == proposals.read_failure_message(""))
        return dict(status=status, label=proposals.LABELS[status], message=message, updated=work["updated"],
                    stopped_before_send=stopped_before_send,
                    poll_url=url_for("integrale_edof.proposal_send_status",folder=folder,ticket=work["token"]),
                    detail_url=url_for("integrale_edof.index",section="requests",tab="waiting" if status=="confirmed" else "request",folder=folder))

    @bp.get("/dossiers/<folder>/proposal/status/<ticket>")
    @admin_required
    def proposal_send_status(folder, ticket):
        owner = results_owner()
        work = proposals.record(store.directory,folder,owner)
        if not work or not ticket.isascii() or not hmac.compare_digest(work["token"],ticket):
            abort(404)
        response = jsonify(proposal_progress(owner,folder,work))
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.post("/dossiers/<folder>/proposal/read")
    @admin_required
    def load_proposal(folder):
        owner = results_owner()
        if session.get("admin_role") == "viewer":
            abort(403)
        check_csrf()
        try:
            row = folder_record(owner,folder)
            if category(row) != "request" or not store.connector_key:
                raise ValueError("Cette proposition ne peut pas être chargée.")
            if throttle.status(vault()):
                raise ValueError(throttle.message(vault()))
            jid = proposals.request_read(store.directory,owner,row)
            from edof_dispatch import wake
            wake(store.directory)
            if request.accept_mimetypes.best == "application/json":
                return jsonify(poll_url=url_for("integrale_edof.proposal_read_status", folder=folder, ticket=jid))
            return proposal_back(folder, proposal_read=jid)
        except (ValueError,ProviderUnavailable) as exc:
            if request.accept_mimetypes.best == "application/json":
                return jsonify(message=str(exc)), 409
            flash(str(exc),"error")
        return proposal_back(folder)

    @bp.get("/dossiers/<folder>/proposal/read/<ticket>")
    @admin_required
    def proposal_read_status(folder, ticket):
        read = proposals.read_ticket(store.directory, results_owner(), folder, ticket)
        if not read:
            abort(404)
        return jsonify(status=read["status"], message=read["message"], detail_url=url_for(
            "integrale_edof.index", section="requests", tab="request", folder=folder, proposal_read=ticket))

    @bp.post("/dossiers/<folder>/proposal/draft")
    @admin_required
    def save_proposal_draft(folder):
        if request.content_length and request.content_length > 192000:
            abort(413)
        owner = results_owner()
        if session.get("admin_role") == "viewer":
            abort(403)
        check_csrf()
        row = folder_record(owner,folder)
        if category(row) != "request" or not store.connector_key:
            abort(409)
        private = vault()
        source = private.get(proposals.source_key(owner,folder))
        signature = request.form.get("signature") or ""
        if signature and (not source or signature!=source["signature"]):
            flash("Les conditions ont changé. Rechargez la proposition EDOF.","error")
        else:
            values = proposal_form.form_values(request.form)
            original = proposal_form.displayed(source if signature else None, enrich(owner,row))
            changes = {k:v for k,v in values.items() if v!=original.get(k)}
            if any(isinstance(v,str) and len(v)>16000 for v in changes.values()):
                abort(400)
            private.put("proposal-draft:"+owner+":"+folder,{"signature":signature,"values":changes},ttl=86400)
            flash("Brouillon enregistré dans la plateforme.","success")
        return proposal_back(folder)

    @bp.post("/dossiers/<folder>/proposal/submit")
    @native_action
    def send_proposal(owner, folder):
        if request.content_length and request.content_length > 192000:
            abort(413)
        row = folder_record(owner,folder)
        private = vault()
        source = private.get(proposals.source_key(owner,folder))
        try:
            if category(row) != "request":
                raise ValueError("Ce dossier n’est plus à traiter.")
            if not source or request.form.get("signature") != source["signature"]:
                raise ValueError("Rechargez la proposition officielle. Les données ont changé ou ont expiré.")
            values = proposal_form.form_values(request.form)
            private.put("proposal-draft:"+owner+":"+folder,{"signature":source["signature"],"values":values},ttl=86400)
            terms = proposal_form.validate(values,source,private.get(proposals.option_key(owner)) or {})
            if request.form.get("confirm") != "yes":
                raise ValueError("Vérifiez puis confirmez l’envoi de ces conditions au titulaire.")
            if throttle.status(private):
                raise ValueError(throttle.message(private))
            state = proposals.enqueue(store.directory,owner,selection.state()["revision"],row,source,terms)
            if request.accept_mimetypes.best == "application/json":
                return jsonify(proposal_progress(owner,folder,proposals.record(store.directory,folder,owner))), 202
            flash(proposals.LABELS[state],"success")
        except ValueError as exc:
            if request.accept_mimetypes.best == "application/json":
                return jsonify(message=str(exc)), 409
            flash(str(exc),"error")
        return proposal_back(folder)

    @bp.post("/dossiers/<folder>/proposal/recheck")
    @admin_required
    def recheck_proposal(folder):
        owner = results_owner()
        if session.get("admin_role") == "viewer":
            abort(403)
        check_csrf()
        folder_record(owner,folder)
        proposals.recheck(store.directory,folder,owner)
        if request.accept_mimetypes.best == "application/json":
            work = proposals.record(store.directory,folder,owner)
            if not work:
                abort(404)
            return jsonify(proposal_progress(owner,folder,work)), 202
        return proposal_back(folder)

    @bp.post("/dossiers/<folder>/create-trainee")
    @admin_required
    def create_trainee(folder):
        from edof_server_test import start_job
        owner = results_owner()
        if session.get("admin_role") == "viewer":
            abort(403)
        check_csrf()
        try:
            row = folder_record(owner, folder)
            sid = request.form.get("session_id", "")
            if category(row) != "accepted" or not any(str(s["id"]) == sid for s in
                    eligible_sessions(local_data(), getattr(legacy, "INTEGRALE_PARTNER_ID", "integrale"))):
                raise ValueError("Choisissez une session disponible pour ce dossier accepté.")
            job = store.successful_read(owner, spec={"folder_id":folder, "first_name":"", "last_name":""})
            if job and "birth_date" in job["fields"] and declarations.same_enrolment(row, job["fields"]) and category(job["fields"]) == "accepted":
                create_registration(legacy, folder, sid, job["fields"])
                flash("Stagiaire enregistré et associé au dossier EDOF.", "success")
            else:
                start_job(store, owner, {"mode":"read", "folder_id":folder, "owner":owner, "first_name":row["first_name"],
                                         "last_name":row["last_name"], "import_session":sid})
                flash("Lecture de la fiche complète lancée. Le stagiaire sera créé dans la session choisie dès la lecture confirmée. Actualisez cette fiche pour vérifier le résultat.", "success")
        except (ValueError, ProviderUnavailable) as exc:
            flash(str(exc), "error")
        return back("requests", tab="accepted", folder=folder, _anchor="dossier")

    @bp.post("/dossiers/<folder>/hold")
    @admin_required
    def dossier_hold(folder):
        owner = results_owner()
        if session.get("admin_role") == "viewer":
            abort(403)
        check_csrf()
        folder_record(owner, folder)
        held = request.form.get("hold") == "yes"
        try:
            declarations.hold_folder(store.directory, folder, held)
            flash("Automatisations du dossier bloquées." if held else "Automatisations du dossier autorisées.", "success")
        except ValueError as exc:
            flash(str(exc), "warning")
        return back(request.form.get("section"), tab=request.form.get("tab"), folder=folder, _anchor="dossier")

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
                db.execute("BEGIN IMMEDIATE")
                pending = db.execute(
                    "SELECT action,status FROM cpf_declarations WHERE folder=?", (folder,)).fetchall()
                if any(x["action"] in (action,) or action == "both" for x in pending if x["status"] in {"sending", "uncertain"}):
                    raise ValueError("Un envoi est déjà parti. Vérifiez sa réception dans cette fiche.")
                db.execute("""UPDATE cpf_declarations SET status=CASE WHEN json_extract(intent,'$.source')='edof_schedule'
                              THEN 'paused' ELSE 'review' END, detail='declaration_blocked'
                              WHERE folder=? AND (action=? OR ?='both') AND status='queued'""", (folder, action, action))
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
        if session.get("admin_role") == "viewer" or not (on_test_service() or on_production_service()):
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
                    if any(blocks_pilot(b, state["ticket"]) for b in active_holds(local_data(), folder)):
                        raise ValueError("Une suspension est en cours sur ce dossier.")
                    draft = declaration_draft(row, request.form, require_reference=True)
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
        draft = declaration_draft(row, request.form)
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
        draft.update(source="admin", **{k:row[k] for k in ("first_name","last_name","session_start_date","session_end_date")})
        record_work(selection, folder, session.get("admin_username") or owner, draft=json.dumps(draft, ensure_ascii=False))
        flash("Déclaration préparée. Vous pouvez la transmettre depuis cette fiche.", "success")
        return back(folder=folder)

    if on_production_service():
        from integrale_edof_crm import register_crm_feed
        register_crm_feed(app, store, vault, snapshot, category, legacy._crm_integration_token_required,
                          lambda: selection.state()["provider"] == "integrale")
    app.register_blueprint(bp)
    if on_production_service():
        # Previously saved links and the technical console still use this path.
        app.register_blueprint(bp, name="integrale_edof_legacy", url_prefix="/admin/edof-test")
    return nightly_associations
