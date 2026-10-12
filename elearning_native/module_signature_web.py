"""Dedicated admin/OF pages for native module evidence and explicit signature sends."""
from __future__ import annotations

import functools
import hmac
import secrets
import sqlite3
from pathlib import Path

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, session, url_for

from .importer import CourseCatalog, CourseImportError
from .module_signatures import CLOSED_STATUSES, ModuleSignatureStore, SignatureError, YousignModuleSignatures, build_evidence
from .module_signature_pdf import date_label, duration
from .paths import assigned_modules, project_course, project_progress
from .store import NativeElearningStore
from .vtc_enrolments import effective_learner_session


CUSTOMER_ENDPOINTS = {"native_module_signatures." + endpoint for endpoint in (
    "index", "order_modules", "prepare_order", "snapshot_pdf", "send", "refresh", "signed_pdf", "audit_archive", "reissue",
)}

STATUS_LABELS = {"prepared": "Tableau préparé", "preparing": "Envoi à reprendre", "ongoing": "Signatures en attente",
                 "signed_pending_archive": "Deux signatures reçues - archivage à compléter", "signed": "Signé et archivé",
                 "expired": "Demande expirée", "declined": "Signature refusée", "canceled": "Demande annulée",
                 "rejected": "Demande rejetée", "deleted": "Demande supprimée"}


def capture_module(database_path, access, course):
    """One read transaction freezes matching time, connections and assessment logs."""
    database_path = Path(database_path).resolve()
    if not database_path.is_file():
        return project_progress({}, course), [], []
    with sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True, timeout=15) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        key = tuple(str(access[k]) for k in ("session_id", "trainee_id", "course_id", "course_version"))
        raw = db.execute("""SELECT * FROM learner_course_progress WHERE session_id=? AND trainee_id=?
            AND course_id=? AND course_version=?""", key).fetchone() if "learner_course_progress" in tables else None
        if raw:
            row = dict(raw)
            row.setdefault("video_progress_json", "{}")
            row.setdefault("assessment_diagnostics_json", "{}")
            progress = project_progress(NativeElearningStore._serialize_progress(row), course)
        else:
            progress = project_progress({}, course)
        connections = [dict(row) for row in db.execute("""SELECT created_at,last_seen_at,ended_at,credited_seconds,status
            FROM tracking_sessions WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?
            ORDER BY created_at,id""", key)] if "tracking_sessions" in tables else []
        if "learner_assessment_attempts" in tables:
            from .assessment import history_for
            selected = set(course.get("activity_order") or [])
            attempts = [a for a in history_for(db, access) if a["activity_id"] in selected]
        else:
            attempts = []
    return progress, connections, attempts


def register_module_signatures(host):
    if "native_module_signatures" in host.app.blueprints:
        return
    bp = Blueprint("native_module_signatures", __name__)

    def root():
        return Path(host.PERSIST_DIR).resolve() / "native_elearning"

    def signature_store():
        return ModuleSignatureStore(root() / "module_signatures.sqlite3")

    def tenant_id():
        return str(host._current_partner_id() or host.INTEGRALE_PARTNER_ID)

    def admin(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("admin_logged_in"):
                return redirect(url_for("admin_login", next=request.path))
            if request.method == "POST":
                if session.get("admin_role") == "viewer":
                    abort(403)
                supplied, expected = request.form.get("csrf_token", ""), session.get("module_signatures_csrf", "")
                if not supplied or not expected or not hmac.compare_digest(supplied, expected):
                    abort(400, "Le formulaire a expiré. Rechargez la page.")
            return view(*args, **kwargs)
        return wrapped

    def actor():
        return str(session.get("admin_username") or session.get("user_email") or session.get("user_id") or "administrateur")

    @bp.after_request
    def private(response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def data_and_provider():
        data = host.load_data(run_background_tasks=False)
        provider = next((p for p in data.get("partners", []) if str(p.get("id")) == tenant_id()), {})
        if not provider and tenant_id() != str(host.INTEGRALE_PARTNER_ID):
            abort(404)
        if not provider:
            provider = host._integrale_partner() if hasattr(host, "_integrale_partner") else {"id": tenant_id(), "name": "Intégrale Academy"}
        return data, provider

    def context(kind, identifier, trainee_id, *, require_active=False):
        import elearning_orders as learning
        data, provider = data_and_provider()
        if kind == "session":
            if session.get("manuals_only") or provider.get("account_type") == "manuals_only":
                abort(403)
            sess = host.find_session(data, identifier)
            if (not sess or str(sess.get("partner_id") or host.INTEGRALE_PARTNER_ID) != tenant_id()
                    or not str(sess.get("training_type", "")).upper().startswith("APS")):
                abort(404)
            person = next((p for p in host._session_trainees_list(sess) if str(p.get("id") or p.get("trainee_id")) == trainee_id), None)
            if not person or str(person.get("partner_id") or sess.get("partner_id") or host.INTEGRALE_PARTNER_ID) != tenant_id():
                abort(404)
            sess = effective_learner_session(sess, person)
            origin = {"kind": "session", "id": str(identifier)}
        elif kind == "order":
            order = next((o for o in data.get("manual_orders", []) if str(o.get("id")) == identifier
                          and o.get("partner_id") == tenant_id() and learning.is_order(o) and o.get("course_code") == "aps"), None)
            if not order:
                abort(404)
            person = next((p for p in order.get("learners", []) if str(p.get("id")) == trainee_id), None)
            if not person:
                abort(404)
            if require_active and (not learning.entitled(order) or not person.get("activated_at")):
                abort(403, "Cet accès e-learning n'est pas actif.")
            sess = {"id": "el-" + order["id"], "partner_id": tenant_id(), "name": order.get("group_name") or "Parcours APS",
                    "date_start": str(person.get("activated_at") or "")[:10], "date_end": order.get("date_end") or "",
                    "training_type": "APS", "aps_native_modules": order.get("modules", [])}
            origin = {"kind": "order", "id": str(identifier)}
        else:
            abort(404)
        cancelled = (host._trainee_registration_is_cancelled(person) if hasattr(host, "_trainee_registration_is_cancelled")
                     else person.get("registration_cancelled") or person.get("cancelled_at"))
        if require_active and cancelled:
            abort(403, "L'inscription de ce stagiaire est annulée.")
        person = {**person, "id": str(person.get("id") or person.get("trainee_id"))}
        return {"provider": provider, "session": sess, "person": person, "origin": origin,
                "modules": assigned_modules(sess), "tenant_id": tenant_id()}

    def module_course(ctx, course_id):
        assignment = next((m for m in ctx["modules"] if m.get("course_id") == course_id), None)
        if not assignment or not course_id.startswith("academy-aps62-") or not assignment.get("course_version"):
            abort(404)
        try:
            course = project_course(CourseCatalog(root()).load_course(course_id, assignment["course_version"]), assignment)
        except (CourseImportError, OSError) as exc:
            raise SignatureError("La version affectée de ce module n'est pas disponible.") from exc
        access = {"session_id": str(ctx["session"]["id"]), "trainee_id": str(ctx["person"].get("id") or ctx["person"].get("trainee_id")),
                  "course_id": course["id"], "course_version": course["version"]}
        progress, connections, attempts = capture_module(root() / "tracking.sqlite3", access, course)
        return course, progress, connections, attempts

    def back_url(ctx):
        origin = ctx["origin"]
        return url_for("native_module_signatures.order_modules", oid=origin["id"], trainee_id=str(ctx["person"]["id"])) if origin["kind"] == "order" else url_for(
            "native_module_signatures.session_modules", session_id=origin["id"], trainee_id=str(ctx["person"]["id"]))

    def snapshot_back(record):
        origin = record["evidence"]["origin"]
        if origin["kind"] == "order":
            return url_for("native_module_signatures.order_modules", oid=origin["id"], trainee_id=record["trainee_id"])
        return url_for("native_module_signatures.session_modules", session_id=origin["id"], trainee_id=record["trainee_id"])

    def page(**kwargs):
        if not session.get("module_signatures_csrf"):
            session["module_signatures_csrf"] = secrets.token_urlsafe(32)
        return render_template("native_module_signatures.html", csrf_token=session["module_signatures_csrf"],
                               read_only=session.get("admin_role") == "viewer", status_labels=STATUS_LABELS,
                               date_label=date_label, duration=duration, closed_statuses=CLOSED_STATUSES, **kwargs)

    @bp.get("/admin/elearning/signatures-modules")
    @admin
    def index():
        import elearning_orders as learning
        data, provider = data_and_provider()
        groups = []
        if not session.get("manuals_only") and provider.get("account_type") != "manuals_only":
            for sess in data.get("sessions", []):
                if (str(sess.get("partner_id") or host.INTEGRALE_PARTNER_ID) != tenant_id()
                        or not str(sess.get("training_type", "")).upper().startswith("APS")
                        or not any(str(m.get("course_id", "")).startswith("academy-aps62-") for m in assigned_modules(sess))):
                    continue
                people = [{"name": " ".join(str(p.get(k) or "") for k in ("first_name", "last_name")),
                           "url": url_for("native_module_signatures.session_modules", session_id=sess["id"], trainee_id=p["id"])}
                          for p in host._session_trainees_list(sess) if p.get("id")
                          and str(p.get("partner_id") or sess.get("partner_id") or host.INTEGRALE_PARTNER_ID) == tenant_id()]
                groups.append({"name": sess.get("name") or "Session APS", "people": people})
        for order in data.get("manual_orders", []):
            if order.get("partner_id") != tenant_id() or not learning.is_order(order) or order.get("course_code") != "aps":
                continue
            people = [{"name": " ".join(str(p.get(k) or "") for k in ("first_name", "last_name")),
                       "url": url_for("native_module_signatures.order_modules", oid=order["id"], trainee_id=p["id"])}
                      for p in order.get("learners", []) if p.get("id")]
            groups.append({"name": order.get("group_name") or "Accès APS", "people": people})
        return page(provider=provider, groups=groups, ctx=None, modules=[], records=[], defaults={}, ready=False)

    def detail(ctx):
        modules = []
        for assignment in ctx["modules"]:
            cid = str(assignment.get("course_id", ""))
            if not cid.startswith("academy-aps62-"):
                continue
            try:
                course, progress, _, _ = module_course(ctx, cid)
                modules.append({"id": cid, "title": course["title"], "version": course["version"], "progress": progress, "error": "",
                                "prepare_url": url_for("native_module_signatures.prepare_order", oid=ctx["origin"]["id"], trainee_id=ctx["person"]["id"], course_id=cid)
                                if ctx["origin"]["kind"] == "order" else url_for("native_module_signatures.prepare_session", session_id=ctx["origin"]["id"], trainee_id=ctx["person"]["id"], course_id=cid)})
            except SignatureError as exc:
                modules.append({"id": cid, "title": assignment.get("title") or cid, "error": str(exc)})
        records = signature_store().list_for(tenant_id(), ctx["session"]["id"], ctx["person"]["id"])
        for record in records:
            record["has_signed_pdf"] = bool(signature_store().artifact(tenant_id(), record["id"], "tableau-signe"))
        provider, person = ctx["provider"], ctx["person"]
        defaults = {"responsible_first_name": provider.get("contact_first_name", ""), "responsible_last_name": provider.get("contact_last_name", ""),
                    "responsible_email": provider.get("contact_email") or provider.get("email") or "", "responsible_phone": provider.get("phone", ""),
                    "cnaps_number": next((str(person[k]) for k in ("pre_number", "cnaps_authorization_number", "cnaps_card_number", "carte_professionnelle") if person.get(k)), ""),
                    "session_end": ctx["session"].get("date_end") or ""}
        if records:
            previous = records[0]["evidence"]
            responsible_keys = ("first_name", "last_name", "email", "phone")
            # Contact coordinates form one identity. Never fill a new person's
            # missing phone/email from a previous signer's frozen identity.
            if not any(str(defaults["responsible_" + key] or "").strip() for key in responsible_keys):
                for key in responsible_keys:
                    defaults["responsible_" + key] = previous["responsible"][key]
            defaults["cnaps_number"] = defaults["cnaps_number"] or previous["learner"]["cnaps_number"]
            defaults["session_end"] = defaults["session_end"] or previous["session"]["date_end"]
        return page(provider=provider, ctx=ctx, modules=modules, records=records, defaults=defaults, groups=[], ready=host._yousign_is_configured())

    @bp.get("/admin/elearning/signatures-modules/sessions/<session_id>/stagiaires/<trainee_id>")
    @admin
    def session_modules(session_id, trainee_id):
        return detail(context("session", session_id, trainee_id))

    @bp.get("/admin/elearning/signatures-modules/commandes/<oid>/stagiaires/<trainee_id>")
    @admin
    def order_modules(oid, trainee_id):
        return detail(context("order", oid, trainee_id))

    def prepare(ctx, course_id):
        try:
            course, progress, connections, attempts = module_course(ctx, course_id)
            responsible = {key: request.form.get("responsible_" + key, "") for key in ("first_name", "last_name", "email", "phone")}
            evidence = build_evidence(tenant_id=tenant_id(), session_obj=ctx["session"], trainee=ctx["person"], provider=ctx["provider"],
                course=course, progress=progress, connections=connections, attempts=attempts, responsible=responsible,
                cnaps_number=request.form.get("cnaps_number"), session_end=request.form.get("session_end"), origin=ctx["origin"])
            record = signature_store().prepare(evidence, actor=actor())
            if record["status"] in CLOSED_STATUSES:
                flash("Ce suivi possède déjà un tableau clôturé. Utilisez « Rééditer ce tableau » pour préparer une nouvelle demande.", "info")
            else:
                flash("Le tableau du module est disponible. Vérifiez le PDF et ses deux destinataires avant l'envoi.", "success")
            return redirect(back_url(ctx) + "#tableau-" + record["id"], code=303)
        except SignatureError as exc:
            flash(str(exc), "error")
        return redirect(back_url(ctx), code=303)

    @bp.post("/admin/elearning/signatures-modules/sessions/<session_id>/stagiaires/<trainee_id>/modules/<course_id>/preparer")
    @admin
    def prepare_session(session_id, trainee_id, course_id):
        return prepare(context("session", session_id, trainee_id, require_active=True), course_id)

    @bp.post("/admin/elearning/signatures-modules/commandes/<oid>/stagiaires/<trainee_id>/modules/<course_id>/preparer")
    @admin
    def prepare_order(oid, trainee_id, course_id):
        return prepare(context("order", oid, trainee_id, require_active=True), course_id)

    def owned(snapshot_id):
        try:
            return signature_store().get(tenant_id(), snapshot_id)
        except SignatureError:
            abort(404)

    def pdf_response(content, filename):
        return Response(content, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @bp.get("/admin/elearning/signatures-modules/tableaux/<snapshot_id>.pdf")
    @admin
    def snapshot_pdf(snapshot_id):
        record = owned(snapshot_id)
        return pdf_response(bytes(record["pdf"]), "tableau-aps-" + record["id"] + ".pdf")

    @bp.post("/admin/elearning/signatures-modules/tableaux/<snapshot_id>/envoyer")
    @admin
    def send(snapshot_id):
        record = owned(snapshot_id)
        if request.form.get("confirm_send") != "yes":
            abort(400, "Vérifiez les deux destinataires et confirmez l'envoi.")
        origin = record["evidence"]["origin"]
        context(origin["kind"], origin["id"], record["trainee_id"], require_active=True)
        try:
            result = YousignModuleSignatures(host, signature_store()).send(tenant_id(), snapshot_id, actor=actor())
            flash("Demande envoyée aux deux signataires." if result["status"] == "ongoing" else STATUS_LABELS.get(result["status"], "Demande actualisée."), "success")
        except SignatureError as exc:
            flash(str(exc), "error")
        return redirect(snapshot_back(record), code=303)

    @bp.post("/admin/elearning/signatures-modules/tableaux/<snapshot_id>/actualiser")
    @admin
    def refresh(snapshot_id):
        record = owned(snapshot_id)
        try:
            result = YousignModuleSignatures(host, signature_store()).refresh(tenant_id(), snapshot_id)
            flash(STATUS_LABELS.get(result["status"], "État actualisé."), "success")
        except (SignatureError, RuntimeError) as exc:
            message = host._sanitize_yousign_error(str(exc)) if hasattr(host, "_sanitize_yousign_error") else str(exc)[:800]
            flash(message, "error")
        return redirect(snapshot_back(record), code=303)

    @bp.post("/admin/elearning/signatures-modules/tableaux/<snapshot_id>/reediter")
    @admin
    def reissue(snapshot_id):
        record = owned(snapshot_id)
        origin = record["evidence"]["origin"]
        context(origin["kind"], origin["id"], record["trainee_id"], require_active=True)
        try:
            replacement = signature_store().reissue(tenant_id(), snapshot_id, actor=actor())
            flash("Une nouvelle édition reprend les traces et destinataires du tableau clôturé. Vérifiez son PDF puis confirmez son envoi.", "success")
            return redirect(snapshot_back(record) + "#tableau-" + replacement["id"], code=303)
        except SignatureError as exc:
            flash(str(exc), "error")
        return redirect(snapshot_back(record), code=303)

    @bp.get("/admin/elearning/signatures-modules/tableaux/<snapshot_id>/signe.pdf")
    @admin
    def signed_pdf(snapshot_id):
        record = owned(snapshot_id)
        content = signature_store().artifact(tenant_id(), snapshot_id, "tableau-signe")
        if not content or not record["state"].get("two_signatures_confirmed_at"):
            abort(404)
        return pdf_response(content, "tableau-aps-" + record["id"] + "-signe.pdf")

    @bp.get("/admin/elearning/signatures-modules/tableaux/<snapshot_id>/archive.zip")
    @admin
    def audit_archive(snapshot_id):
        record = owned(snapshot_id)
        return Response(signature_store().archive(tenant_id(), snapshot_id), mimetype="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="preuves-module-aps-{record["id"]}.zip"'})

    host.app.register_blueprint(bp)
    host.app.config["NATIVE_MODULE_SIGNATURES_ENABLED"] = True
