"""Partner dossier: real reporting, scoped commerce and non-destructive edits."""
import copy
import re
import sqlite3

import pytest

import app as host
import partner_workspace as workspace
import elearning_orders as learning
import elearning_sales as sales
from test_elearning_groups import HiddenFields
from test_manuals_shop import shop, signup, login, all_data
from test_elearning_reporting import activated, seed_course, tracked, database_dump, report_url


def as_admin(client):
    with client.session_transaction() as session:
        session.clear()
        session.update(admin_logged_in=True, admin_role="super_admin", platform_role="super_admin",
                       partner_id=host.INTEGRALE_PARTNER_ID, admin_username="admin@example.test")


def create_partner(shop):
    assert signup(shop["client"]).status_code == 303
    return next(p for p in all_data(shop)["partners"] if p.get("account_type") == "manuals_only")


def url(partner, tab="overview"):
    return f"/admin/partners/{partner['id']}?tab={tab}"


def token(client, partner):
    response = client.get(url(partner, "information"))
    assert response.status_code == 200
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def test_tabs_and_empty_states_keep_account_metadata_without_legacy_subscription(shop):
    partner = create_partner(shop)
    def note(data):
        host._partner_or_404(data, partner["id"])["internal_notes"] = "Note interne du dossier"
    host._atomic_update_data(note, partner_id=partner["id"])
    as_admin(shop["client"])
    mails = len(shop["mails"])
    for tab, label in workspace.TABS:
        response = shop["client"].get(url(partner, tab))
        assert response.status_code == 200, response.text
        assert label in response.text
        assert "Modules payants disponibles" not in response.text
        assert "Abonnement et utilisation" not in response.text
        assert 'name="subscription' not in response.text
    overview = shop["client"].get(url(partner)).text
    account = shop["client"].get(url(partner, "account")).text
    assert "Note interne du dossier" in overview
    assert "Compte déjà activé" in account
    assert "Revenir à la fiche partenaire" not in account
    assert "https://localhost/admin/login?next=/admin/organisme" in account or "http://localhost/admin/login?next=/admin/organisme" in account
    assert len(shop["mails"]) == mails


def test_information_edit_preserves_modules_subscription_and_login(shop):
    partner = create_partner(shop)
    as_admin(shop["client"])
    csrf = token(shop["client"], partner)
    before = all_data(shop)
    original = next(p for p in before["partners"] if p["id"] == partner["id"])
    assert shop["client"].post(url(partner), data={"name": "Rejected"}).status_code == 400
    response = shop["client"].post(url(partner), data={"csrf_token": csrf, "name": "Nouveau nom", "internal_notes": "Suivi commercial"})
    assert response.status_code == 303
    after = all_data(shop)
    updated = next(p for p in after["partners"] if p["id"] == partner["id"])
    assert updated["name"] == "Nouveau nom"
    for key in ("enabled_modules", "subscription", "subscription_plan", "max_users", "email", "siret"):
        assert updated.get(key) == original.get(key), key
    assert after["users"] == before["users"]


@pytest.mark.parametrize("free", [False, True])
def test_four_partner_prices_save_and_reopen_without_changing_other_accounts(shop, free):
    partner = create_partner(shop)
    other_client = host.app.test_client()
    assert signup(other_client, email="other-pricing@example.test").status_code == 303
    other = next(p for p in all_data(shop)["partners"] if p.get("email") == "other-pricing@example.test")
    as_admin(shop["client"])
    client = shop["client"]
    page = client.get(url(partner, "pricing"))
    fields = HiddenFields(page.text, include_visible=True).fields
    for code in ("aps", "mac-aps", "a3p", "vtc"):
        assert f"{code}_price" in fields and f"{code}_free" in fields
    assert fields["mac-aps_price"] == "49.00" and fields["a3p_price"] == "150.00"
    assert "157 h 30 min" in page.text
    post_url = f"/admin/partners/{partner['id']}/pricing"
    payload = {"csrf_token": fields["csrf_token"], "aps_price": "59.00", "mac-aps_price": "42.50",
               "a3p_price": "79.90", "vtc_price": "150.00"}
    if free:
        payload.update({"mac-aps_free": "yes", "a3p_free": "yes"})
    before = all_data(shop)
    other = next(p for p in before["partners"] if p["id"] == other["id"])
    sales_before = sales.enabled(host)
    assert client.post(post_url, data={"mac-aps_price": "1"}).status_code == 400
    response = client.post(post_url, data=payload)
    assert response.status_code == 303 and response.location.endswith("?tab=pricing")
    after = all_data(shop)
    saved = next(p for p in after["partners"] if p["id"] == partner["id"])
    for code, cents in (("mac-aps", 4250), ("a3p", 7990)):
        assert saved["elearning_pricing"][code] == {"unit_cents": cents, "free": free}
        assert learning.prices(saved)[code]["unit_cents"] == (0 if free else cents)
    reopened = HiddenFields(client.get(url(partner, "pricing")).text, include_visible=True).fields
    assert reopened["mac-aps_price"] == "42.50" and reopened["a3p_price"] == "79.90"
    assert next(p for p in after["partners"] if p["id"] == other["id"]) == other
    assert after["users"] == before["users"] and after.get("manual_orders", []) == before.get("manual_orders", [])
    assert sales.enabled(host) is sales_before


@pytest.mark.parametrize("legacy_tracking", [False, True])
def test_real_progress_and_exports_work_for_admin_without_impersonating_or_writing(shop, legacy_tracking):
    order, root = seed_course(activated(shop))
    tracked(root, order)
    if legacy_tracking:
        # Existing tracking databases may predate optional ledgers. A report
        # must still work without invoking the learner store's migrations.
        with sqlite3.connect(root / "tracking.sqlite3") as db:
            for column in ("video_progress_json", "assessment_diagnostics_json",
                           "activity_seconds_json", "lesson_seconds_json", "aps_workload_json"):
                db.execute(f"ALTER TABLE learner_course_progress DROP COLUMN {column}")
    before = database_dump(root)
    as_admin(shop["client"])
    partner = {"id": order["partner_id"]}
    roster = shop["client"].get(f"/admin/partners/{partner['id']}/learning/order/{order['id']}")
    assert roster.status_code == 200, roster.text
    assert "100 %" in roster.text and "00 h 00 min 30 s" in roster.text
    assert "Suivi détaillé" in roster.text
    response = shop["client"].get(report_url(order) + "?embed=1")
    assert response.status_code == 200, response.text
    assert '<header class="site-header">' not in response.text
    assert "Documents du suivi" in response.text
    assert shop["client"].get(report_url(order) + "/connexions.csv").status_code == 200
    pdf = shop["client"].get(report_url(order) + "/attestation.pdf")
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf"
    assert database_dump(root) == before
    with shop["client"].session_transaction() as session:
        assert not session.get("assist_partner_id")
        assert not any(k.startswith("public_auth_") for k in session)


def test_assistance_opens_the_actual_storefront_and_returns_to_dossier(shop):
    order = activated(shop)
    pid = order["partner_id"]
    as_admin(shop["client"])
    response = shop["client"].post(f"/admin/partners/{pid}/assist", data={"next": "/admin/organisme/e-learning"})
    assert response.location == "/admin/organisme/e-learning"
    with shop["client"].session_transaction() as state:
        assert state.get("assist_partner_id") == pid, dict(state)
    for path in ("/admin/organisme", "/admin/organisme/commandes", "/admin/organisme/e-learning", report_url(order)):
        page = shop["client"].get(path)
        assert page.status_code == 200, (path, page.text)
        assert "Revenir à la fiche partenaire" in page.text
        assert "Mon espace organisme" in page.text
    response = shop["client"].post("/admin/partners/assist/exit")
    assert response.location == f"/admin/partners/{pid}"


def test_partner_and_assisting_admin_cannot_read_another_tenant_report(shop):
    order = activated(shop)
    shop["client"].get("/admin/logout")
    assert signup(shop["client"], email="other@example.test").status_code == 303
    login(shop["client"], email="other@example.test")
    other = next(p for p in all_data(shop)["partners"] if p.get("email") == "other@example.test")
    original_orders = copy.deepcopy(all_data(shop)["manual_orders"])
    assert shop["client"].get(report_url(order)).status_code == 404
    assert shop["client"].get(f"/admin/partners/{order['partner_id']}/learning/order/{order['id']}").status_code in {302, 403}
    as_admin(shop["client"])
    assert shop["client"].get(f"/admin/partners/{other['id']}/learning/order/{order['id']}").status_code == 404
    response = shop["client"].post(f"/admin/partners/{other['id']}/assist")
    assert response.status_code == 302, response.text
    with shop["client"].session_transaction() as state:
        assert state.get("assist_partner_id") == other["id"], dict(state)
    assert shop["client"].get(report_url(order)).status_code == 404
    assert shop["client"].get(f"/admin/organisme/e-learning/commandes/{order['id']}").status_code == 404
    assert shop["client"].post("/admin/partners/assist/exit").status_code == 302
    assert all_data(shop)["manual_orders"] == original_orders


def test_orders_invoices_and_counts_are_scoped_and_exclude_rosters_and_drafts(shop):
    partner = create_partner(shop)
    other_id = "another-partner"
    order = {"id": "manual-1", "partner_id": partner["id"], "reference": "MAN-OWN", "status": "received", "total_cents": 25000,
             "created_at": "2026-10-16", "items": [{"kind": "manual", "label": "Manuel APS", "quantity": 10, "unit_cents": 2500, "total_cents": 25000}],
             "commerce": {"invoice_id": "invoice-own", "invoice_number": "FAC-OWN", "invoice_url": "https://qonto.test/invoice.pdf", "payment_status": "unpaid", "remaining_cents": 25000}}
    def seed(data):
        data.setdefault("manual_orders", []).extend([order, {**order, "id": "draft-1", "reference": "DRAFT", "status": "draft"}])
    host._atomic_update_data(seed, partner_id=partner["id"])
    as_admin(shop["client"])
    with host.app.test_request_context(url(partner)):
        host.session.update(admin_logged_in=True, admin_role="super_admin", platform_role="super_admin")
        view = workspace.context(host, {"partners": [partner], "manual_orders": [order, {**order, "id": "other", "partner_id": other_id, "reference": "OTHER"}]}, partner)
        assert view["workspace_stats"]["total_cents"] == 25000
        assert len(view["workspace_invoices"]) == 1
    for tab in ("orders", "invoices"):
        response = shop["client"].get(url(partner, tab))
        assert response.status_code == 200, response.text
        assert "FAC-OWN" in response.text and "MAN-OWN" in response.text
        assert "DRAFT" not in response.text
    csrf = token(shop["client"], partner)
    response = shop["client"].post(f"/admin/partners/{partner['id']}/orders/manual-1/status", data={"csrf_token": csrf, "status": "production"})
    assert response.status_code == 400  # Payment gate remains mandatory.
    assert next(o for o in all_data(shop)["manual_orders"] if o["id"] == "manual-1")["status"] == "received"
