"""Durable editable rosters, separate from immutable e-learning purchase batches.

Group records share the existing tenant-scoped manual_orders collection so both
JSON and PostgreSQL stores persist them without a second storage migration. They
stay in draft status, never enter the merchant queue and never grant access.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
import secrets
import time
import unicodedata
import uuid

from flask import abort, flash, redirect, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.datastructures import MultiDict

import elearning_orders as learning
import manuals_commerce as commerce

CUSTOMER_ENDPOINTS = {"manuals_shop." + name for name in (
    "elearning_group_create", "elearning_group", "elearning_group_save",
    "elearning_group_review", "elearning_group_confirm", "elearning_group_delete",
)}
MAX_GROUPS = 300


def is_group(record):
    return record.get("order_type") == "elearning_group"


def group_orders(data, group):
    return sorted((o for o in data.get("manual_orders", [])
                   if learning.is_order(o) and o.get("partner_id") == group["partner_id"]
                   and o.get("group_id") == group["id"]),
                  key=lambda o: o.get("created_at", ""), reverse=True)


def group_view(data, group):
    """Derive payment state from purchase snapshots, never from roster input."""
    orders = group_orders(data, group)
    reservations = {}
    for order in orders:
        if order.get("status") in {"draft", "cancelled"} or order.get("commerce", {}).get("invoice_status") == "canceled":
            continue
        for person in order.get("learners", []):
            reservations.setdefault(person["id"], (order, person))
    result = copy.deepcopy(group)
    people = []
    for person in group.get("learners", []):
        row = copy.deepcopy(person)
        order, enrolled = reservations.get(person["id"], (None, None))
        row.update(locked=bool(order), order_id=order["id"] if order else None,
                   status="active" if order and learning.entitled(order) and enrolled.get("activated_at") else "waiting_payment" if order else "draft")
        people.append(row)
    pending = [p for p in people if not p["locked"]]
    result.update(learners=people, pending_learners=pending, orders=orders,
                  pending_count=len(pending), active_count=sum(p["status"] == "active" for p in people),
                  waiting_count=sum(p["status"] == "waiting_payment" for p in people),
                  total_count=len(people), can_change_course=not orders,
                  deletion_pending=bool(group.get("deletion_requested_at")), deletion_error=group.get("deletion_error", ""),
                  can_delete=not group.get("deletion_requested_at") and not deletion_block_reason(orders),
                  delete_block_reason=deletion_block_reason(orders))
    return result


def dashboard(data, partner):
    groups = sorted((group_view(data, record) for record in data.get("manual_orders", [])
                     if is_group(record) and not record.get("deleted_at") and record.get("partner_id") == partner["id"]),
                    key=lambda group: group.get("updated_at", group.get("created_at", "")), reverse=True)
    return groups




def deletion_block_reason(orders):
    if any(order.get("activated_at") or any(p.get("activated_at") for p in order.get("learners", [])) for order in orders):
        return "Un accès a déjà été activé : ce groupe ne peut plus être supprimé."
    for order in orders:
        state = order.get("commerce", {})
        if state.get("invoice_status") == "paid" or state.get("payment_status") in {"paid", "partially_paid", "processing"} or state.get("paid_cents", 0) > 0:
            return "Un paiement a été reçu ou est en cours. Ce groupe ne peut pas être supprimé."
        if state.get("lease_until", 0) > time.time():
            return "La commande est en cours de traitement. Réessayez dans quelques instants."
    return ""


def _cancel_locally(order, now):
    order.update(status="cancelled", cancelled_at=now)
    order.pop("cancellation_requested_at", None)
    order.setdefault("commerce", {}).update(queued=False, status="cancelled", payment_url="", error="", lease_until=0,
                                            lease_token=str(uuid.uuid4()))


def _remote_billing(order):
    state = order.get("commerce", {})
    return any(state.get(key) for key in ("invoice_id", "invoice_creation_started", "payment_id", "payment_creation_started"))


class CancellationBlocked(Exception):
    """A confirmed or in-flight payment must remain attached to the customer."""


def process_cancellation(host, order):
    """Cancel under the merchant lease; archive only after provider confirmation.

    Qonto API: POST client_invoices/{id}/mark_as_canceled (unpaid only),
    PATCH payment_links/{id}/deactivate. No provider call is made in a tenant
    request; all invoice/link identities and amounts are checked before mutation.
    """
    def payment_guard(link):
        if link.get("invoice_id") != order["commerce"].get("invoice_id") or commerce._money_cents(link.get("amount")) != order["total_cents"]:
            raise commerce.ReviewRequired("Le lien de paiement ne correspond pas à cette commande.")
        if link.get("status") in {"paid", "processing"}:
            raise CancellationBlocked("Un paiement est reçu ou en cours. La suppression n’a pas été effectuée.")
        if link.get("status") not in {"open", "expired", "canceled"}:
            raise commerce.ReviewRequired("Le statut du lien de paiement doit être vérifié avant suppression.")
        for page in range(1, 51):
            response = host._qonto_request("GET", f"/v2/payment_links/{link['id']}/payments", params={"page": page, "per_page": 100})
            if not isinstance(response, dict) or not ({"payments", "payment_link_payments"} & response.keys()):
                raise commerce.ReviewRequired("La liste des paiements n’a pas pu être vérifiée avant suppression.")
            payments = response.get("payments", response.get("payment_link_payments"))
            if not isinstance(payments, list) or any(not isinstance(payment, dict) for payment in payments):
                raise commerce.ReviewRequired("La liste des paiements doit être vérifiée avant suppression.")
            if any(payment.get("status") not in {"failed", "canceled", "expired"} for payment in payments):
                raise CancellationBlocked("Un règlement est en cours ou a été reçu. La suppression n’a pas été effectuée.")
            if not host._qonto_invoice_list_has_next_page(response, page, len(payments), 100):
                return
        raise commerce.ReviewRequired("La liste complète des paiements n’a pas pu être vérifiée.")

    def invoice_guard(invoice):
        commerce._assert_invoice(order, invoice)
        normalized = host.normalize_qonto_invoice_payment_data(invoice)
        commerce._save(host, order, invoice_status=invoice.get("status"), invoice_number=invoice.get("number", ""),
                       payment_status=normalized["qonto_payment_status"], paid_cents=normalized["qonto_amount_paid_cents"],
                       remaining_cents=normalized["qonto_remaining_amount_cents"])
        if invoice.get("status") == "paid" or normalized["qonto_amount_paid_cents"] > 0:
            raise CancellationBlocked("Un paiement a été reçu. La suppression n’a pas été effectuée ; votre commande reste disponible.")
        if invoice.get("status") not in {"draft", "unpaid", "canceled"}:
            raise commerce.ReviewRequired("La facture doit être vérifiée avant suppression.")

    def terminate_request(message):
        # Release the whole group request; already-cancelled snapshots remain
        # canceled, while a paid order resumes its normal delivery workflow.
        def update(data):
            current = commerce._find(data, order["partner_id"], order["id"])
            if not current or current.get("commerce", {}).get("lease_token") != order["commerce"]["lease_token"]:
                return {}
            group = next((g for g in data.get("manual_orders", []) if is_group(g) and g.get("id") == order.get("group_id") and g.get("partner_id") == order["partner_id"]), None)
            if group:
                group.pop("deletion_requested_at", None)
                group.update(deletion_error=message, revision=group["revision"] + 1, updated_at=host._now_iso())
                for item in group_orders(data, group):
                    if item.pop("cancellation_requested_at", None):
                        item.setdefault("commerce", {}).update(queued=True, next_attempt=0, lease_until=0, lease_token=str(uuid.uuid4()))
            return {}
        host._atomic_update_data(update, partner_id=order["partner_id"])

    try:
        state = order["commerce"]
        invoice = None
        if state.get("invoice_id"):
            try:
                invoice = host._qonto_invoice_payload(host.get_qonto_invoice(state["invoice_id"]))
            except host.QontoApiError as exc:
                if exc.status_code != 404 or not state.get("invoice_deletion_started"):
                    raise
                # A previous draft DELETE succeeded remotely but its response
                # or local save was lost. A subsequent GET proves absence.
                commerce._save(host, order, invoice_status="canceled", invoice_cancelled_at=host._now_iso())
        elif state.get("invoice_creation_started"):
            invoice = commerce._recover_invoice(host, order)
            if not invoice:
                # An ambiguous earlier POST may still complete remotely.
                raise commerce.ReviewRequired("La création de facture doit être vérifiée avant suppression. Aucun accès n’est activé.")
            commerce._save(host, order, invoice_id=invoice["id"])
        if invoice:
            invoice_guard(invoice)
        elif state.get("payment_id") or state.get("payment_creation_started"):
            raise commerce.ReviewRequired("Le paiement doit être rapproché de sa facture avant suppression.")
        links = []
        state = order["commerce"]
        if state.get("payment_id"):
            response = host._qonto_request("GET", "/v2/payment_links/" + state["payment_id"])
            link = response.get("payment_link") or response
            if link.get("id") != state["payment_id"]:
                raise commerce.ReviewRequired("L’identifiant du lien de paiement ne correspond pas.")
            links = [link]
        elif state.get("payment_creation_started"):
            for page in range(1, 51):
                response = host._qonto_request("GET", "/v2/payment_links", params={"page": page, "per_page": 100})
                if not isinstance(response, dict) or not isinstance(response.get("payment_links"), list) or any(not isinstance(link, dict) for link in response["payment_links"]):
                    raise commerce.ReviewRequired("La liste des liens de paiement n’a pas pu être vérifiée.")
                page_links = response["payment_links"]
                links.extend(link for link in page_links if link.get("invoice_id") == state.get("invoice_id"))
                if not host._qonto_invoice_list_has_next_page(response, page, len(page_links), 100):
                    break
            else:
                raise commerce.ReviewRequired("La liste complète des liens de paiement n’a pas pu être vérifiée.")
            if not links:
                raise commerce.ReviewRequired("La création du lien de paiement doit être vérifiée avant suppression.")
        for link in links:
            payment_guard(link)
        for link in links:
            if link.get("status") == "open":
                commerce._save(host, order, status="cancellation_pending")
                host._qonto_request("PATCH", f"/v2/payment_links/{link['id']}/deactivate", idempotency_key="elearning-cancel-link-" + link["id"])
            response = host._qonto_request("GET", "/v2/payment_links/" + link["id"])
            current_link = response.get("payment_link") or response
            if current_link.get("id") != link["id"]:
                raise commerce.ReviewRequired("Le lien annulé n’a pas pu être vérifié.")
            payment_guard(current_link)
            if current_link.get("status") not in {"canceled", "expired"}:
                raise commerce.ReviewRequired("La désactivation du lien de paiement reste à confirmer.")
            commerce._save(host, order, payment_url="", payment_link_status=current_link["status"])
        if invoice and invoice.get("status") == "draft":
            # Draft invoices have no accounting effect and cannot be marked canceled.
            commerce._save(host, order, invoice_deletion_started=host._now_iso())
            host._qonto_request("DELETE", "/v2/client_invoices/" + invoice["id"], idempotency_key="elearning-cancel-draft-" + order["id"])
            commerce._save(host, order, invoice_status="canceled", invoice_cancelled_at=host._now_iso())
        elif invoice:
            # Re-read after closing checkout links to catch payment races.
            invoice = host._qonto_invoice_payload(host.get_qonto_invoice(invoice["id"]))
            invoice_guard(invoice)
            if invoice.get("status") == "unpaid":
                commerce._save(host, order, status="cancellation_pending")
                host._qonto_request("POST", f"/v2/client_invoices/{invoice['id']}/mark_as_canceled", idempotency_key="elearning-cancel-invoice-" + order["id"])
            invoice = host._qonto_invoice_payload(host.get_qonto_invoice(invoice["id"]))
            invoice_guard(invoice)
            if invoice.get("status") != "canceled":
                raise commerce.ReviewRequired("L’annulation de la facture reste à confirmer.")
        def finish(data):
            current = commerce._find(data, order["partner_id"], order["id"])
            if not current or current.get("commerce", {}).get("lease_token") != order["commerce"]["lease_token"] or not current.get("cancellation_requested_at"):
                raise commerce.ReviewRequired("La suppression a été reprise par un autre traitement.")
            if current.get("activated_at") or any(p.get("activated_at") for p in current.get("learners", [])):
                raise CancellationBlocked("Un accès est déjà activé. La suppression n’a pas été effectuée.")
            now = host._now_iso()
            _cancel_locally(current, now)
            group = next((g for g in data.get("manual_orders", []) if is_group(g) and g.get("id") == order.get("group_id") and g.get("partner_id") == order["partner_id"]), None)
            if group and group.get("deletion_requested_at"):
                remaining = group_orders(data, group)
                if all(o.get("status") == "cancelled" for o in remaining):
                    group.update(deleted_at=now, updated_at=now, revision=group["revision"] + 1, deletion_error="")
                    group.pop("deletion_requested_at", None)
                else:
                    following = next((item for item in remaining if item.get("cancellation_requested_at")), None)
                    if following:
                        following["commerce"].update(queued=True, next_attempt=0)
            return {}
        host._atomic_update_data(finish, partner_id=order["partner_id"])
    except CancellationBlocked as exc:
        terminate_request(str(exc))
    except Exception as exc:
        message = str(exc) if isinstance(exc, commerce.ReviewRequired) else "La suppression est en attente de vérification du paiement. Elle sera réessayée automatiquement."
        commerce._save(host, order, status="cancellation_pending", error=message, queued=True,
                       next_attempt=time.time() + min(60 * 2 ** min(order["commerce"].get("attempts", 1), 6), 3600), lease_until=0)
        def note(data):
            group = next((g for g in data.get("manual_orders", []) if is_group(g) and g.get("id") == order.get("group_id") and g.get("partner_id") == order["partner_id"]), None)
            if group and group.get("deletion_requested_at"):
                group["deletion_error"] = message
            return {}
        host._atomic_update_data(note, partner_id=order["partner_id"])

def billing_defaults(data, partner, group=None):
    """Reuse a complete own-tenant address; never mix fields across customers."""
    keys = ("address", "postal_code", "city")
    billing = {key: str(partner.get(key) or "") for key in keys}
    prior = sorted((order for order in data.get("manual_orders", [])
                    if order.get("partner_id") == partner["id"] and not is_group(order)
                    and order.get("status") not in {"draft", "cancelled"}
                    and not order.get("deleted_at")
                    and order.get("commerce", {}).get("invoice_status") != "canceled"),
                   key=lambda order: order.get("submitted_at") or order.get("created_at", ""), reverse=True)
    for order in prior:
        saved = order.get("billing") or {}
        delivery = order.get("delivery") or {}
        # Legacy manuals orders sometimes contain only a delivery address.
        candidate = {key: str(saved.get(key) or delivery.get(key) or "").strip() for key in keys}
        if all(candidate.values()):
            billing.update(candidate)
            break
    for key, value in ((group or {}).get("billing") or {}).items():
        if key in keys:
            # An explicitly stored empty field is a choice, not missing data.
            billing[key] = str(value or "")
    return billing


def dashboard_filter(groups, values):
    state = values.get("state", "all")
    if state not in {"all", "draft", "waiting", "active"}:
        state = "all"
    query = str(values.get("q", ""))[:200].strip()
    def normalized(value):
        return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))
    words = normalized(query).split()
    counts = {"draft": "pending_count", "waiting": "waiting_count", "active": "active_count"}
    def matches(group):
        state_match = (state == "all" or bool(group[counts[state]])
                       or (state == "draft" and not group["total_count"]))
        subjects = [group.get("group_name", "") + " " + group.get("course_code", "")]
        subjects.extend(" ".join(str(person.get(key, "")) for key in ("first_name", "last_name", "email")) for person in group.get("learners", []))
        return state_match and (not words or any(all(word in normalized(subject) for word in words) for subject in subjects))
    visible = {group["id"] for group in groups if matches(group)}
    return {"group_ids_visible": visible, "filter_state": state, "filter_query": query, "visible_count": len(visible)}

def _roster(form, group, locked):
    columns = [form.getlist(k) for k in ("learner_id", "last_name", "first_name", "email")]
    if len({len(c) for c in columns}) != 1 or len(columns[0]) > learning.MAX_LEARNERS:
        raise ValueError("Vérifiez la liste des participants (100 personnes maximum).")
    editable_ids = {p["id"] for p in group.get("learners", [])} - {p["id"] for p in locked}
    people, seen_ids, seen_emails = [], set(), {p["email"].casefold() for p in locked}
    for learner_id, last, first, email in zip(*columns):
        learner_id = learner_id.strip()
        if not learner_id and not any(v.strip() for v in (last, first, email)):
            continue
        if learner_id and (learner_id not in editable_ids or learner_id in seen_ids):
            raise ValueError("Un participant a déjà été commandé ou a été modifié. Rechargez le groupe.")
        person = learning.parse_learners(MultiDict({"last_name": last, "first_name": first, "email": email}))[0]
        if person["email"] in seen_emails:
            raise ValueError("Cette adresse e-mail figure déjà dans ce groupe : " + person["email"])
        person["id"] = learner_id or person["id"]
        seen_ids.add(person["id"])
        seen_emails.add(person["email"])
        people.append(person)
    if len(people) + len(locked) > learning.MAX_LEARNERS:
        raise ValueError("Un groupe peut contenir jusqu’à 100 personnes.")
    if group.get("mode") == "individual" and len(people) + len(locked) > 1:
        raise ValueError("Un accès individuel est réservé à une seule personne. Créez un groupe pour plusieurs participants.")
    return people


def _revision(form):
    value = str(form.get("revision", ""))
    if not re.fullmatch(r"[0-9]{1,10}", value):
        abort(400, "Rechargez le groupe avant de l’enregistrer.")
    return int(value)


def _name(value, mode):
    value = str(value or "").strip()
    if not value and mode == "individual":
        return "Accès individuel"
    if not 1 <= len(value) <= 150 or any(ord(c) < 32 for c in value):
        raise ValueError("Indiquez un nom de groupe de 1 à 150 caractères.")
    return value


def register_routes(host, bp, *, page, customer, partner_data, check_csrf, kick_worker):
    def find(data, gid):
        # Every operation is bound to the authenticated tenant, including atomic
        # callbacks. A submitted partner ID can never select another tenant.
        group = next((o for o in data.get("manual_orders", [])
                      if is_group(o) and o.get("id") == gid
                      and not o.get("deleted_at") and o.get("partner_id") == host._current_partner_id()), None)
        if not group:
            abort(404)
        return group

    def serializer():
        return URLSafeTimedSerializer(host.app.secret_key, salt="elearning-group-quote-v1")

    def detail(data, partner, group, *, errors=None, values=None, rows=None):
        view = group_view(data, group)
        from elearning_reporting import group_progress
        view["progress"] = group_progress(host, view)
        return page("elearning_group.html", partner=partner, courses=learning.prices(partner), group=view,
                    errors=errors or [], values=values if values is not None else group,
                    rows=rows if rows is not None else view["pending_learners"])

    def review(data, partner, group, *, errors=None, values=None, status=200):
        view = group_view(data, group)
        price = learning.prices(partner)[group["course_code"]]
        request_id = secrets.token_hex(16)
        payload = {"group_id": group["id"], "partner_id": partner["id"], "revision": group["revision"],
                   "request_id": request_id, "learner_ids": [p["id"] for p in view["pending_learners"]],
                   "unit_cents": price["unit_cents"], "free": price["free"]}
        billing = billing_defaults(data, partner, group)
        if values is not None:
            billing.update(values)
        return page("elearning_group_review.html", partner=partner, courses=learning.prices(partner), group=view,
                    learners=view["pending_learners"], price=price, quantity=view["pending_count"],
                    total_cents=price["unit_cents"] * view["pending_count"] if price["configured"] else None,
                    request_id=request_id, quote_token=serializer().dumps(payload), values=billing, errors=errors or []), status

    @bp.route("/admin/organisme/e-learning/nouveau", methods=["GET", "POST"])
    @customer
    def elearning_group_create():
        data, partner = partner_data()
        values = request.form.to_dict() if request.method == "POST" else {"mode": request.args.get("mode", "group"), "course_code": request.args.get("course", "aps")}
        errors = []
        if request.method == "POST":
            check_csrf()
            try:
                mode, code = values.get("mode", "group"), values.get("course_code", "")
                if mode not in {"group", "individual"} or code not in learning.COURSES:
                    raise ValueError("Choisissez un accès individuel ou un groupe, puis le parcours APS ou VTC.")
                name = _name(values.get("group_name"), mode)
                token = values.get("request_id", "")
                if not re.fullmatch(r"[a-f0-9]{32}", token):
                    raise ValueError("Rechargez le formulaire avant de créer le groupe.")
                now, gid = host._now_iso(), str(uuid.uuid4())
                record = {"id": gid, "order_type": "elearning_group", "status": "draft", "partner_id": partner["id"],
                          "created_by": session.get("user_id"), "created_at": now, "updated_at": now,
                          "request_id": token, "group_name": name, "course_code": code, "mode": mode,
                          "revision": 1, "learners": []}
                def persist(current):
                    records = current.setdefault("manual_orders", [])
                    existing = next((o for o in records if is_group(o) and o.get("partner_id") == partner["id"] and o.get("request_id") == token), None)
                    if existing:
                        return {"id": existing["id"]}
                    if sum(is_group(o) and not o.get("deleted_at") and o.get("partner_id") == partner["id"] for o in records) >= MAX_GROUPS:
                        abort(429, "Vous avez atteint la limite de groupes. Contactez-nous pour continuer.")
                    records.append(record)
                    return {"id": gid}
                result = host._atomic_update_data(persist, partner_id=partner["id"])
                flash("Votre groupe est enregistré. Vous pouvez le compléter maintenant ou revenir plus tard." if mode == "group" else "Votre accès individuel est enregistré. Ajoutez le participant à votre rythme.", "success")
                return redirect(url_for("manuals_shop.elearning_group", gid=result["id"]), code=303)
            except ValueError as exc:
                errors = [str(exc)]
        return page("elearning_group_create.html", partner=partner, courses=learning.prices(partner), values=values,
                    request_id=values.get("request_id") or secrets.token_hex(16), errors=errors), 400 if errors else 200

    @bp.get("/admin/organisme/e-learning/groupes/<gid>")
    @customer
    def elearning_group(gid):
        data, partner = partner_data()
        return detail(data, partner, find(data, gid))

    @bp.post("/admin/organisme/e-learning/groupes/<gid>/supprimer")
    @customer
    def elearning_group_delete(gid):
        check_csrf()
        _, partner = partner_data()
        expected = _revision(request.form)
        if request.form.get("confirm") != "yes":
            abort(400)
        def remove(data):
            group = find(data, gid)
            if group.get("revision") != expected:
                return {"error": "Le groupe a changé. Vérifiez sa version actuelle avant de le supprimer."}
            if group.get("deletion_requested_at"):
                return {"pending": True}
            orders = group_orders(data, group)
            blocked = deletion_block_reason(orders)
            if blocked:
                return {"error": blocked}
            now = host._now_iso()
            pending = False
            for order in orders:
                if order.get("status") == "cancelled":
                    continue
                if _remote_billing(order):
                    pending = True
                    order["cancellation_requested_at"] = now
                    order.setdefault("commerce", {}).update(queued=True, status="cancellation_pending", next_attempt=0,
                                                            lease_until=0, lease_token=str(uuid.uuid4()))
                else:
                    _cancel_locally(order, now)
            group.update(revision=expected + 1, updated_at=now, deletion_error="")
            if pending:
                # Only one cancellation batch per group may reach Qonto at a
                # time, including across multiple application workers.
                queued_one = False
                for order in orders:
                    if order.get("cancellation_requested_at"):
                        order["commerce"]["queued"] = not queued_one
                        queued_one = True
                group["deletion_requested_at"] = now
            else:
                group["deleted_at"] = now
            return {"pending": pending}
        result = host._atomic_update_data(remove, partner_id=partner["id"])
        if result.get("error"):
            data, partner = partner_data()
            return detail(data, partner, find(data, gid), errors=[result["error"]]), 409
        if result.get("pending"):
            kick_worker()
            flash("La suppression est en cours. Nous vérifions l’absence de paiement et annulons la facture avant de supprimer le groupe.", "success")
            return redirect(url_for("manuals_shop.elearning_group", gid=gid), code=303)
        flash("Le groupe ou l’accès individuel a été supprimé. Aucun accès ne sera activé.", "success")
        return redirect(url_for("manuals_shop.elearning_soon"), code=303)

    @bp.post("/admin/organisme/e-learning/groupes/<gid>/enregistrer")
    @customer
    def elearning_group_save(gid):
        check_csrf()
        _, partner = partner_data()
        expected = _revision(request.form)
        def save(data):
            group = find(data, gid)
            if group.get("revision") != expected:
                return {"conflict": True}
            if group.get("deletion_requested_at"):
                raise ValueError("La suppression de ce groupe est en cours de vérification.")
            view = group_view(data, group)
            name = _name(request.form.get("group_name"), group["mode"])
            code = request.form.get("course_code", group["course_code"])
            if code not in learning.COURSES:
                raise ValueError("Choisissez le parcours APS ou VTC.")
            if code != group["course_code"] and not view["can_change_course"]:
                raise ValueError("Le parcours d’un groupe déjà commandé ne peut plus être modifié.")
            locked = [p for p in group["learners"] if p["id"] in {r["id"] for r in view["learners"] if r["locked"]}]
            people = _roster(request.form, group, locked)
            group.update(group_name=name, course_code=code, learners=locked + people,
                         revision=expected + 1, updated_at=host._now_iso())
            return {"id": gid}
        try:
            result = host._atomic_update_data(save, partner_id=partner["id"])
            if result.get("conflict"):
                data, partner = partner_data()
                return detail(data, partner, find(data, gid), errors=["Ce groupe a été modifié dans un autre onglet. La version enregistrée est affichée ci-dessous. Vérifiez-la avant de reprendre vos modifications."]), 409
        except ValueError as exc:
            data, partner = partner_data()
            rows = [{"id": i, "last_name": l, "first_name": f, "email": e} for i, l, f, e in zip(*(request.form.getlist(k) for k in ("learner_id", "last_name", "first_name", "email")))]
            return detail(data, partner, find(data, gid), errors=[str(exc)], values=request.form.to_dict(), rows=rows), 400
        if request.form.get("next") == "review":
            return redirect(url_for("manuals_shop.elearning_group_review", gid=gid), code=303)
        flash("Vos modifications sont enregistrées. Vous pourrez créer les accès quand vous serez prêt.", "success")
        return redirect(url_for("manuals_shop.elearning_group", gid=gid), code=303)

    @bp.route("/admin/organisme/e-learning/groupes/<gid>/recapitulatif", methods=["GET", "POST"])
    @customer
    def elearning_group_review(gid):
        data, partner = partner_data()
        group = find(data, gid)
        if request.method == "POST":
            check_csrf()
            if _revision(request.form) != group.get("revision"):
                return detail(data, partner, group, errors=["Le groupe a été modifié. Vérifiez sa liste actuelle avant de créer les accès."]), 409
        view = group_view(data, group)
        if view["deletion_pending"]:
            return detail(data, partner, group, errors=["La suppression de ce groupe est en cours de vérification."]), 409
        if not view["pending_count"]:
            flash("Ajoutez au moins un participant avant de créer les espaces e-learning.", "error")
            return redirect(url_for("manuals_shop.elearning_group", gid=gid), code=303)
        return review(data, partner, group)

    @bp.post("/admin/organisme/e-learning/groupes/<gid>/creer-espaces")
    @customer
    def elearning_group_confirm(gid):
        check_csrf()
        data, partner = partner_data()
        group = find(data, gid)
        if request.form.get("confirm") != "yes":
            abort(400)
        try:
            quote = serializer().loads(request.form.get("quote_token", ""), max_age=86400)
        except SignatureExpired:
            return review(data, partner, group, errors=["Ce récapitulatif a expiré. Vérifiez le tarif actualisé avant de confirmer."], status=409)
        except BadSignature:
            abort(400, "Le récapitulatif est invalide. Revenez au groupe et réessayez.")
        if not isinstance(quote, dict) or quote.get("group_id") != gid or quote.get("partner_id") != partner["id"] or quote.get("request_id") != request.form.get("request_id"):
            abort(400, "Le récapitulatif ne correspond pas à ce groupe.")
        expected = _revision(request.form)
        if expected != quote.get("revision"):
            abort(400, "Le récapitulatif ne correspond pas à cette version du groupe.")
        billing = {k: request.form.get(k, "").strip() for k in ("address", "postal_code", "city")}
        billing.update(country="France", country_code="FR")
        def confirm(current):
            current_group = find(current, gid)
            if current_group.get("deletion_requested_at"):
                raise ValueError("La suppression de ce groupe est en cours de vérification.")
            orders = current.setdefault("manual_orders", [])
            existing = next((o for o in orders if learning.is_order(o) and o.get("partner_id") == partner["id"]
                             and o.get("group_id") == gid and o.get("request_id") == quote["request_id"]), None)
            if existing:
                return {"id": existing["id"]}
            if current_group["revision"] != expected:
                return {"error": "Le groupe a changé depuis votre récapitulatif. Vérifiez les participants avant de confirmer à nouveau."}
            view = group_view(current, current_group)
            people = [{k: p[k] for k in ("id", "last_name", "first_name", "email")} for p in view["pending_learners"]]
            if not people or [p["id"] for p in people] != quote.get("learner_ids"):
                return {"error": "La liste des participants à commander a changé. Vérifiez le nouveau récapitulatif."}
            current_partner = host._partner_or_404(current, partner["id"])
            price = learning.prices(current_partner)[current_group["course_code"]]
            if not price["configured"]:
                raise ValueError("Contactez-nous pour définir votre tarif pour ce parcours. Votre groupe reste enregistré.")
            if (price["unit_cents"], price["free"]) != (quote.get("unit_cents"), quote.get("free")):
                return {"error": "Votre tarif a changé. Le nouveau total est affiché ci-dessous. Vérifiez-le avant de confirmer."}
            if not price["free"] and any(not 1 <= len(billing[k]) <= limit or any(ord(c) < 32 for c in billing[k]) for k, limit in (("address", 200), ("postal_code", 20), ("city", 100))):
                raise ValueError("Complétez l’adresse de facturation de votre organisme.")
            oid, now = str(uuid.uuid4()), host._now_iso()
            unit, quantity = price["unit_cents"], len(people)
            order = {"id": oid, "order_type": "elearning", "partner_id": partner["id"], "group_id": gid,
                     "created_by": session.get("user_id"), "status": "received", "created_at": now, "submitted_at": now,
                     "reference": "EL-" + str(dt.date.today().year) + "-" + oid[:8].upper(),
                     "request_id": quote["request_id"], "course_code": current_group["course_code"],
                     "group_name": current_group["group_name"], "learners": people,
                     "modules": learning.curriculum(current_group["course_code"]), "billing": copy.deepcopy(billing),
                     "free_snapshot": price["free"], "unit_cents": unit, "total_cents": unit * quantity, "shipping_cents": 0,
                     "items": [{"kind": "elearning", "code": current_group["course_code"], "label": "Accès e-learning " + current_group["course_code"].upper(),
                                "quantity": quantity, "unit_cents": unit, "total_cents": unit * quantity}],
                     "centre": {k: current_partner.get(k, "") for k in ("name", "siret", "email", "contact_first_name", "contact_last_name")},
                     "commerce": {"queued": True, "status": "pending", "flow": "elearning_invoice_first", "attempts": 0, "emails": {}}}
            orders.append(order)
            current_group.update(revision=expected + 1, updated_at=now, billing=copy.deepcopy(billing))
            return {"id": oid}
        try:
            result = host._atomic_update_data(confirm, partner_id=partner["id"])
        except ValueError as exc:
            data, partner = partner_data()
            return review(data, partner, find(data, gid), errors=[str(exc)], values=billing, status=400)
        if result.get("error"):
            data, partner = partner_data()
            return review(data, partner, find(data, gid), errors=[result["error"]], values=billing, status=409)
        kick_worker()
        return redirect(url_for("manuals_shop.elearning_order", oid=result["id"]), code=303)
