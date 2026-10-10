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
import uuid

from flask import abort, flash, redirect, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.datastructures import MultiDict

import elearning_orders as learning

CUSTOMER_ENDPOINTS = {"manuals_shop." + name for name in (
    "elearning_group_create", "elearning_group", "elearning_group_save",
    "elearning_group_review", "elearning_group_confirm",
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
                  total_count=len(people), can_change_course=not orders)
    return result


def dashboard(data, partner):
    groups = sorted((group_view(data, record) for record in data.get("manual_orders", [])
                     if is_group(record) and record.get("partner_id") == partner["id"]),
                    key=lambda group: group.get("updated_at", group.get("created_at", "")), reverse=True)
    return groups


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
                      and o.get("partner_id") == host._current_partner_id()), None)
        if not group:
            abort(404)
        return group

    def serializer():
        return URLSafeTimedSerializer(host.app.secret_key, salt="elearning-group-quote-v1")

    def detail(data, partner, group, *, errors=None, values=None, rows=None):
        view = group_view(data, group)
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
        billing = copy.deepcopy(group.get("billing") or {k: partner.get(k, "") for k in ("address", "postal_code", "city")})
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
                    if sum(is_group(o) and o.get("partner_id") == partner["id"] for o in records) >= MAX_GROUPS:
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
