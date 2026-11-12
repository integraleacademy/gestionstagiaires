"""Tenant-scoped contact corrections and individual access-link deliveries."""
import hashlib
import re
import secrets
import time

from flask import abort, flash, redirect, request, session, url_for

import elearning_groups as groups
import elearning_orders as learning


def find(data, partner_id, record_id, learner_id):
    record = next((row for row in data.get("manual_orders", [])
                   if row.get("id") == record_id and row.get("partner_id") == partner_id
                   and learning.is_record(row) and not row.get("deleted_at")), None)
    person = next((row for row in (record or {}).get("learners", [])
                   if row.get("id") == learner_id), None)
    if not record or not person:
        abort(404)
    return record, person


def update(host, data, partner_id, record_id, learner_id, *, action, email, expected_email):
    """Called inside the partner transaction, before waking the existing worker."""
    partner = host._partner_or_404(data, partner_id)
    if partner.get("status") not in {"active", "trial"}:
        abort(403)
    record, person = find(data, partner_id, record_id, learner_id)
    old_email = str(person.get("email") or "").strip().casefold()
    if expected_email.strip().casefold() != old_email:
        raise ValueError("L’adresse a été modifiée entre-temps. Vérifiez la nouvelle adresse avant de réessayer.")
    if action not in {"save_email", "resend"}:
        abort(400)
    email = email.strip().casefold() if action == "save_email" else old_email
    if len(email) > 254 or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", email):
        raise ValueError("Saisissez une adresse e-mail valide.")
    group = record if groups.is_group(record) else next((row for row in data.get("manual_orders", [])
        if groups.is_group(row) and row.get("id") == record.get("group_id")
        and row.get("partner_id") == partner_id), None)
    if group and (group.get("deleted_at") or group.get("deletion_requested_at") or group.get("roster_amendment")):
        raise ValueError("Une modification du groupe est en cours. Réessayez après son traitement.")
    roster_person = next((p for p in (group or {}).get("learners", []) if p.get("id") == learner_id), None)
    if group and not roster_person:
        raise ValueError("La liste du groupe a changé. Rechargez la page avant de réessayer.")
    if groups.is_group(record):
        row = next(p for p in groups.group_view(data, record)["learners"] if p["id"] == learner_id)
        if row["locked"]:
            raise ValueError("Ce stagiaire a déjà une commande. Modifiez son e-mail depuis la liste de cette commande.")
    else:
        state = record.get("commerce", {})
        if record.get("status") == "cancelled" or record.get("cancellation_requested_at") or state.get("invoice_status") == "canceled":
            raise ValueError("Cette commande est annulée ou en cours d’annulation.")
        # Never let a worker send its old snapshot while we change the recipient.
        if state.get("lease_until", 0) > time.time():
            raise ValueError("Un envoi ou un traitement est en cours. Réessayez dans quelques instants.")
    for source in (record, group or {}):
        if any(p.get("id") != learner_id and str(p.get("email") or "").strip().casefold() == email
               for p in source.get("learners", [])):
            raise ValueError("Cette adresse e-mail est déjà utilisée par un autre stagiaire du groupe.")
    active = learning.is_order(record) and learning.entitled(record) and bool(person.get("activated_at"))
    if action == "resend" and not active:
        raise ValueError("Le lien pourra être renvoyé après le règlement et l’activation de l’accès.")
    changed = email != old_email
    now_epoch = time.time()
    if active and not changed and now_epoch - person.get("access_resend_requested_epoch", 0) < 60:
        return {"queued": False, "message": "Le renvoi du lien vient déjà d’être demandé. Patientez une minute avant de réessayer."}
    now = host._now_iso()
    if changed:
        person["email"] = email
        if person.get("activated_at"):
            # Revoke a link potentially delivered to the wrong person, retaining
            # the enrolment ID used by all progress, time and exam records.
            person["access_token_version"] = secrets.token_hex(16)
            token = learning.access_token(host, record, person)
            person["token_hash"] = hashlib.sha256(token.encode()).hexdigest()
        if group and group is not record:
            roster_person["email"] = email
        if group:
            group.update(revision=group.get("revision", 0) + 1, updated_at=now)
        record["updated_at"] = now
    if active:
        person.update(access_resend_requested_at=now, access_resend_requested_epoch=now_epoch)
        state = record.setdefault("commerce", {})
        # Only this delivery key is reset: receipts and other learners stay sent.
        state.setdefault("emails", {})["learner_" + learner_id] = {"status": "pending", "requested_at": now}
        state.update(queued=True, next_attempt=0)
    if changed or active:
        host._append_activity_log(data, "elearning_learner_email_updated" if changed else "elearning_learner_link_requested",
                                  "manual_order", record_id, partner_id,
                                  {"learner_id": learner_id, "previous_email": old_email, "email": email, "link_requested": active})
    message = ("Adresse e-mail enregistrée. Le renvoi du lien à la nouvelle adresse est demandé." if changed and active else
               "Le renvoi du lien d’accès est demandé." if active else
               "Adresse e-mail enregistrée. Elle sera utilisée lors de l’envoi des accès." if changed else
               "L’adresse e-mail est déjà à jour.")
    return {"queued": active, "message": message}


def register_routes(host, bp, *, partner_data, check_csrf, kick_worker):
    @bp.post("/admin/organisme/e-learning/dossiers/<record_id>/stagiaires/<learner_id>/contact")
    @host.admin_login_required
    def elearning_learner_contact(record_id, learner_id):
        check_csrf()
        staff = host._is_super_admin_session() and not session.get("assist_partner_id")
        assisting = host._is_super_admin_session() and bool(session.get("assist_partner_id"))
        if session.get("admin_role") == "viewer" or not (staff or host._is_external_partner_session() or assisting):
            abort(403)
        if staff:
            data = host.load_data(run_background_tasks=False)
            record = next((r for r in data.get("manual_orders", []) if r.get("id") == record_id and learning.is_record(r)), None)
            if not record:
                abort(404)
            partner_id = record["partner_id"]
        else:
            data, partner = partner_data()
            partner_id = partner["id"]
        record, _ = find(data, partner_id, record_id, learner_id)
        group_id = record_id if groups.is_group(record) else record.get("group_id")
        if staff and request.form.get("return_to") == "partner":
            destination = url_for("admin_partner_detail", partner_id=partner_id, tab="learning", learning_record=group_id or record_id)
        elif group_id and request.form.get("return_to") != "order":
            destination = url_for("manuals_shop.elearning_group", gid=group_id)
        else:
            destination = url_for("manuals_shop.elearning_order", oid=record_id)
        try:
            result = host._atomic_update_data(lambda current: update(
                host, current, partner_id, record_id, learner_id,
                action=request.form.get("action", ""), email=request.form.get("email", ""),
                expected_email=request.form.get("expected_email", "")), partner_id=partner_id)
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            if result["queued"]:
                kick_worker()
            flash(result["message"], "success")
        return redirect(destination, code=303)
