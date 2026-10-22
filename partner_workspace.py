"""Unified administration of a partner's purchases and learning spaces.

Reads are tenant-scoped, never open a learner session and never create activity.
Commercial mutations reuse the existing payment/fulfilment safeguards.
"""
from urllib.parse import urlparse

from flask import abort, flash, make_response, redirect, render_template, request, url_for

import elearning_groups as groups
import elearning_orders as learning
import elearning_reporting as reporting
import manuals_commerce as commerce
import manuals_fulfillment as fulfillment

TABS = (("overview", "Vue d’ensemble"), ("orders", "Commandes"),
        ("invoices", "Factures"), ("learning", "E-learning & stagiaires"),
        ("information", "Informations"), ("pricing", "Tarifs e-learning"),
        ("account", "Compte & activité"))
ACCESS_LABELS = {"active": "Accès activé", "draft": "À commander",
                 "waiting_payment": "En attente de paiement", "ready_to_send": "Prêt à envoyer",
                 "sending": "Envoi demandé", "closed": "Accès fermé"}
ACTIVITY_LABELS = {
    "partner_created": "Organisme créé", "partner_updated": "Informations mises à jour",
    "elearning_prices_updated": "Tarifs e-learning mis à jour",
    "manual_order_submitted": "Commande confirmée", "manual_order_status_changed": "Statut de commande modifié",
    "super_admin_assist_started": "Consultation de l’espace partenaire",
    "super_admin_assist_finished": "Fin de consultation de l’espace partenaire",
    "invitation_sent": "Invitation envoyée", "invitation_send_failed": "Échec d’envoi de l’invitation",
    "invitation_cancelled": "Invitation annulée", "partner_activated": "Compte activé",
    "partner_status_changed": "Statut de l’organisme modifié",
}


def admin_scope(data, partner_id):
    """Retain admin-only account fields while selecting exactly one tenant."""
    return {key: [item for item in data.get(key, []) if isinstance(item, dict)
                  and item.get("id" if key == "partners" else "partner_id") == partner_id]
            for key in ("partners", "users", "invitations", "activity_logs", "manual_orders", "sessions")}


def load_partner(host, partner_id):
    # Avoid loading every other organisation for a single partner dossier.
    if host._partner_postgres_active() and partner_id != host.INTEGRALE_PARTNER_ID:
        try:
            data, _ = host._load_partner_postgres_bundle(partner_id)
        except host.PartnerPostgresNotFound:
            abort(404)
    else:
        data = admin_scope(host.load_data(), partner_id)
    return data, host._partner_or_404(data, partner_id)


def safe_document_url(value):
    parsed = urlparse(str(value or ""))
    return str(value) if parsed.scheme == "https" and parsed.hostname and not parsed.username else ""


def order_view(order):
    state = order.get("commerce") or {}
    is_learning = learning.is_order(order)
    cancelled = order.get("status") == "cancelled" or state.get("invoice_status") == "canceled"
    return {
        "record": order, "id": order["id"], "learning": is_learning,
        "kind": "E-learning" if is_learning else "Manuels & clés USB",
        "date": order.get("submitted_at") or order.get("created_at") or "",
        "reference": order.get("reference") or "Brouillon",
        "cancelled": cancelled, "flow": state,
        "payment_label": "Annulée" if cancelled else "Gratuit" if order.get("free_snapshot") else
            commerce.PAYMENT_LABELS.get(state.get("payment_status"), "En préparation"),
        "invoice_url": url_for("manuals_shop.elearning_invoice", oid=order["id"])
            if is_learning and state.get("invoice_id") and not cancelled else
            safe_document_url(state.get("invoice_url")) if not cancelled else "",
        "detail_url": url_for("manuals_shop.elearning_order", oid=order["id"]) if is_learning else
            url_for("manuals_shop.admin_order", partner_id=order["partner_id"], order_id=order["id"]),
        "delivery": learning.status_view(order) if is_learning else {},
    }


def learning_cards(data, partner):
    result = []
    rosters = groups.dashboard(data, partner)
    roster_ids = {group["id"] for group in rosters}
    for group in rosters:
        result.append({**group, "kind": "group", "label": group.get("group_name") or "Groupe sans nom"})
    # Older purchases have no roster; they must remain visible and reportable.
    for order in data.get("manual_orders", []):
        if not learning.is_order(order) or order.get("group_id") in roster_ids:
            continue
        people = []
        entitled = learning.entitled(order)
        for person in order.get("learners", []):
            status = "closed" if order.get("status") == "cancelled" or order.get("commerce", {}).get("invoice_status") == "canceled" else (
                "draft" if order.get("status") == "draft" else
                "active" if entitled and person.get("activated_at") else
                "sending" if entitled and order.get("access_dispatch_requested_at") else
                "ready_to_send" if entitled else "waiting_payment")
            people.append({**person, "order_id": order["id"], "status": status})
        result.append({**order, "kind": "order", "label": order.get("group_name") or order.get("reference") or "Commande en préparation",
                       "learners": people, "orders": [order], "total_count": len(people),
                       "active_count": sum(p["status"] == "active" for p in people)})
    return sorted(result, key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)


def context(host, data, partner):
    from manuals_shop import STATUSES, csrf_token
    pid = partner["id"]
    # Defence in depth: callers cannot accidentally aggregate another tenant.
    data = admin_scope(data, pid)
    orders = sorted((order_view(order) for order in data.get("manual_orders", [])
                     if not groups.is_group(order) and order.get("status") != "draft"), key=lambda row: row["date"], reverse=True)
    invoices = [row for row in orders if row["flow"].get("invoice_id") or row["flow"].get("invoice_number") or row["flow"].get("invoice_url")]
    confirmed = [row for row in orders if row["record"].get("status") != "draft" and not row["cancelled"]]
    cards = learning_cards(data, partner)
    alerts = []
    for row in confirmed:
        if row["flow"].get("status") in {"needs_setup", "needs_review", "retry"}:
            alerts.append({"label": row["reference"] + " · Traitement à vérifier", "tab": "orders", "order": row["id"]})
        elif row["delivery"].get("can_send"):
            alerts.append({"label": row["reference"] + " · Accès prêts à envoyer", "tab": "learning"})
    logs = sorted(data.get("activity_logs", []), key=lambda row: row.get("created_at") or "", reverse=True)[:30]
    return dict(
        workspace_tabs=TABS, active_tab=request.args.get("tab") if request.args.get("tab") in dict(TABS) else "overview",
        workspace_orders=orders, workspace_invoices=invoices, workspace_cards=cards,
        workspace_sessions=data.get("sessions", []), workspace_alerts=alerts,
        workspace_logs=[{**row, "label": ACTIVITY_LABELS.get(row.get("action"), "Activité du compte"),
                         "action_label": str(row.get("action") or "").replace("_", " ")} for row in logs],
        workspace_stats={"orders": len(confirmed), "invoices": len(invoices),
                         "total_cents": sum(int(row["record"].get("total_cents") or 0) for row in confirmed),
                         "active": sum(card["active_count"] for card in cards),
                         "learners": sum(card["total_count"] for card in cards),
                         "unpaid": sum(row["flow"].get("payment_status") in {"unpaid", "partially_paid"} and not row["cancelled"] for row in invoices)},
        workspace_prices=learning.prices(partner), workspace_csrf=csrf_token(),
        order_statuses=STATUSES, access_labels=ACCESS_LABELS,
    )


def platform_context(host, data):
    """One merchant dashboard using the existing canonical orders and settings."""
    from manuals_shop import csrf_token
    tabs = (("organisations", "Organismes"), ("orders", "Commandes"),
            ("invoices", "Factures"), ("campaigns", "Campagnes e-learning"), ("settings", "Facturation et TVA"))
    active = request.args.get("tab", "organisations")
    if active not in dict(tabs):
        active = "organisations"
    partners = {p["id"]: p for p in data.get("partners", []) if isinstance(p, dict)}
    orders = []
    for order in data.get("manual_orders", []):
        if groups.is_group(order) or order.get("status") == "draft":
            continue
        row = order_view(order)
        row["partner_name"] = (partners.get(order.get("partner_id"), {}).get("name")
                               or order.get("centre", {}).get("name") or "Organisme")
        orders.append(row)
    orders.sort(key=lambda row: row["date"], reverse=True)
    invoices = [row for row in orders if any(row["flow"].get(key)
                for key in ("invoice_id", "invoice_number", "invoice_url"))]
    import partner_campaigns
    campaign_context = partner_campaigns.context(host) if active == "campaigns" else {}
    return dict(platform_tabs=tabs, platform_tab=active, platform_orders=orders,
                platform_invoices=invoices, csrf_token=csrf_token(),
                **campaign_context,
                settings=commerce.settings_from(data), errors=[],
                **commerce.configuration_status(host, data, {"items": [
                    {"kind": kind} for kind in ("manual", "usb", "elearning")]}))


def register(host):
    from manuals_shop import check_csrf
    import partner_campaigns
    partner_campaigns.register(host)

    @host.app.get("/admin/partners/<partner_id>/learning/<kind>/<record_id>")
    @host.admin_login_required
    @host.require_super_admin
    def admin_partner_learning_roster(partner_id, kind, record_id):
        data, partner = load_partner(host, partner_id)
        card = next((c for c in learning_cards(data, partner) if c["kind"] == kind and c["id"] == record_id), None)
        if not card:
            abort(404)
        reader, people = None, []
        orders = {order["id"]: order for order in card.get("orders", [])}
        for row in card.get("learners", []):
            order = orders.get(row.get("order_id"))
            person = next((p for p in (order or {}).get("learners", []) if p.get("id") == row.get("id")), None)
            report = None
            if order and person and learning.entitled(order) and person.get("activated_at"):
                reader = reader or reporting.ProgressReader(host)
                report = reader.report(order, person, detailed=False)
            mail = (order or {}).get("commerce", {}).get("emails", {}).get("learner_" + str(row.get("id")), {})
            people.append({"person": row, "report": report, "order": order, "mail": mail})
        response = make_response(render_template("partners/_learners.html", partner=partner, people=people, access_labels=ACCESS_LABELS))
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @host.app.post("/admin/partners/<partner_id>/pricing")
    @host.admin_login_required
    @host.require_super_admin
    def admin_partner_pricing(partner_id):
        check_csrf()
        try:
            pricing = learning.parse_prices(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            def save(data):
                partner = host._partner_or_404(data, partner_id)
                partner["elearning_pricing"] = pricing
                partner["updated_at"] = host._now_iso()
                host._append_activity_log(data, "elearning_prices_updated", "partner", partner_id, partner_id)
                return {}
            host._atomic_update_data(save, partner_id=partner_id)
            flash("Les tarifs e-learning sont enregistrés. Les commandes déjà confirmées conservent leur prix.", "success")
        return redirect(url_for("admin_partner_detail", partner_id=partner_id, tab="pricing"), code=303)

    @host.app.post("/admin/partners/<partner_id>/orders/<order_id>/status")
    @host.admin_login_required
    @host.require_super_admin
    def admin_partner_order_status(partner_id, order_id):
        from manuals_shop import STATUSES
        check_csrf()
        status = request.form.get("status")
        if status not in STATUSES:
            abort(400)
        def update(data):
            order = next((o for o in data.get("manual_orders", []) if o.get("id") == order_id and o.get("partner_id") == partner_id), None)
            if not order or learning.is_record(order) or order.get("status") == "draft":
                abort(404)
            if status == "cancelled" and order.get("commerce", {}).get("status") == "processing":
                abort(409, "La facturation est en cours. Réessayez après son traitement.")
            fulfillment.validate_status(order, status)
            order.update(status=status, updated_at=host._now_iso())
            if status == "cancelled" and order.get("commerce"):
                order["commerce"]["queued"] = False
            host._append_activity_log(data, "manual_order_status_changed", "manual_order", order_id, partner_id, {"status": status})
            return {}
        host._atomic_update_data(update, partner_id=partner_id)
        flash("Le statut de la commande a été enregistré.", "success")
        return redirect(url_for("admin_partner_detail", partner_id=partner_id, tab="orders", order=order_id), code=303)
