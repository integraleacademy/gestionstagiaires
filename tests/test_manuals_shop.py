import io
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as host
from manuals_shop import CATALOGUE, money, quote_items


@pytest.fixture(params=["off", "active"])
def shop(request, tmp_path, monkeypatch):
    monkeypatch.setenv("PARTNER_POSTGRES_MODE", request.param)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://gestionstagiaires-test-v2.onrender.com")
    monkeypatch.setenv("PARTNER_DATABASE_URL", "postgresql://test.invalid/partners")
    for key, value in {"PERSIST_DIR": str(tmp_path), "DATA_FILE": str(tmp_path / "data.json"), "BACKUP_DIR": str(tmp_path / "backups"), "UPLOADS_DIR": str(tmp_path / "uploads")}.items():
        monkeypatch.setattr(host, key, value)
    (tmp_path / "backups").mkdir()
    (tmp_path / "uploads").mkdir()
    (tmp_path / "data.json").write_text(json.dumps({"sessions": [], "partners": [host._integrale_partner()], "users": [], "activity_logs": []}))
    monkeypatch.setitem(host.app.config, "TESTING", True)
    monkeypatch.setitem(host.app.config, "SECRET_KEY", "manuals-test-secret")
    monkeypatch.setattr(host, "ADMIN_USER", "admin@example.test")
    monkeypatch.setattr(host, "ADMIN_PASSWORD", "platform-test-pass")
    if request.param == "active":
        sys.path.insert(0, str(Path(__file__).parent))
        from test_partner_postgres_hybrid import InMemoryPartnerStore
        store = InMemoryPartnerStore()
        monkeypatch.setattr(host, "_partner_postgres_store_override", store)
    else:
        store = None
    mails = []
    def send(*args, **kwargs):
        mails.append((args, kwargs))
        return {"ok": True, "message_id": "test-message"}
    monkeypatch.setattr(host, "brevo_send_email", send)
    host._partner_login_attempts.clear()
    return {"client": host.app.test_client(), "mails": mails, "store": store}


def csrf(client, url="/creer-mon-espace"):
    response = client.get(url)
    assert response.status_code == 200
    return re.search(rb'name="csrf_token" value="([^"]+)"', response.data).group(1).decode()


def signup(client, email="centre@example.test", **updates):
    data = {"csrf_token": csrf(client), "centre": "Centre de formation test", "siret": "73282932000074", "last_name": "Martin", "first_name": "Camille", "email": email, "password": "Une phrase robuste 2026!", "password_confirmation": "Une phrase robuste 2026!"}
    data.update(updates)
    return client.post("/creer-mon-espace", data=data)


def login(client, email="centre@example.test", next_url="/admin/sessions"):
    response = client.post("/admin/login", data={"username": email, "password": "Une phrase robuste 2026!", "next": next_url})
    assert response.status_code == 302
    assert response.location == "/admin/organisme"
    return response


def order_form(client, **updates):
    form = {"csrf_token": csrf(client, "/admin/manuels"), "manual_aps": "100", "manual_sst": "50", "usb_ssiap1": "1", "recipient": "Centre test", "phone": "0400000000", "address": "1 rue Exemple", "city": "Paris", "postal_code": "75001", "country": "France", "personalization": "later", "notes": "Livraison à l’accueil"}
    form.update(updates)
    return form


def all_data(shop):
    if shop["store"] is not None:
        result = {"partners": [], "users": [], "manual_orders": []}
        for b in shop["store"].bundles.values():
            for key in result:
                result[key].extend(b.get(key, []))
        return result
    return json.loads(Path(host.DATA_FILE).read_text())


def test_registration_login_email_and_restricted_navigation(shop):
    c = shop["client"]
    assert signup(c).status_code == 303
    data = all_data(shop)
    user = data["users"][0]
    partner = next(p for p in data["partners"] if p.get("account_type") == "manuals_only")
    assert partner["enabled_modules"] == []
    assert user["role"] == "partner_admin"
    assert host._verify_password("Une phrase robuste 2026!", user["password_hash"])
    assert "Une phrase robuste" not in Path(host.DATA_FILE).read_text()
    assert len(shop["mails"]) == 1
    assert "gestionstagiaires-test-v2.onrender.com/admin/login" in shop["mails"][0][0][2]
    assert "Une phrase robuste" not in shop["mails"][0][0][2]
    assert c.get("/espace-cree").status_code == 200
    login(c, next_url="/admin/partners")
    page = c.get("/admin/manuels")
    assert page.status_code == 200
    assert "Commande Manuels de formation" in page.text
    for forbidden in ("/admin/sessions", "/admin/partners", "/admin/secretariat", "/admin/commandes-manuels", "/scotia/login", "/admin/e-learning"):
        response = c.get(forbidden)
        assert response.status_code == 302, forbidden
        assert response.location == "/admin/organisme"
    for path in ("/api/admin/trainees", "/api/new-future-module", "/admin/sessions/new", "/admin/partners/new"):
        assert c.post(path, json={"role": "super_admin"}).status_code == 403, path


def test_invalid_forms_and_duplicate_identity(shop):
    c = shop["client"]
    assert c.post("/creer-mon-espace", data={}).status_code == 400
    assert signup(c, siret="00000000000000").status_code == 400
    assert signup(c, password_confirmation="Different password").status_code == 400
    assert signup(c, email="invalid").status_code == 400
    assert signup(c, password="short", password_confirmation="short").status_code == 400
    assert signup(c, email="admin@example.test").status_code == 400
    host._partner_login_attempts.clear()
    assert signup(c).status_code == 303
    fresh = host.app.test_client()
    assert signup(fresh, email="CENTRE@example.test").status_code == 400
    assert len(all_data(shop)["users"]) == 1


def test_mail_failure_does_not_lose_the_account(shop, monkeypatch):
    monkeypatch.setattr(host, "brevo_send_email", lambda *a, **kw: {"ok": False})
    c = shop["client"]
    assert signup(c).status_code == 303
    response = c.get("/espace-cree")
    assert "n’a pas pu être envoyé" in response.text
    assert all_data(shop)["partners"][-1]["welcome_email"]["status"] == "failed"
    login(c)
    assert c.get("/admin/manuels").status_code == 200


def test_prices_tampering_isolation_durable_order_and_idempotency(shop):
    c = shop["client"]
    signup(c)
    login(c)
    response = c.post("/admin/manuels/recapitulatif", data=order_form(c, unit_cents="1", total_cents="1", partner_id="other-centre"))
    assert response.status_code == 303
    detail = response.location
    assert c.get(detail).status_code == 200
    orders = all_data(shop)["manual_orders"]
    assert len(orders) == 1
    assert orders[0]["total_cents"] == 259900  # 100 APS at 18 + 50 SST at 12 + USB at 199
    assert orders[0]["partner_id"] != "other-centre"
    token = csrf(c, detail)
    assert c.post(detail + "/confirmer", data={"csrf_token": token, "confirm": "yes"}).status_code == 303
    assert c.post(detail + "/confirmer", data={"csrf_token": token, "confirm": "yes"}).status_code == 303
    persisted = all_data(shop)["manual_orders"]
    assert len(persisted) == 1 and persisted[0]["status"] == "received"
    assert persisted[0]["reference"] in c.get("/admin/manuels").text
    assert persisted[0]["reference"] in c.get(detail).text
    second = host.app.test_client()
    signup(second, email="autre@example.test")
    login(second, email="autre@example.test")
    assert second.get(detail).status_code == 404
    assert second.get(detail + "/logo").status_code == 404
    assert persisted[0]["reference"] not in second.get("/admin/manuels").text
    assert second.post(detail + "/confirmer", data={"csrf_token": csrf(second, "/admin/manuels"), "confirm": "yes"}).status_code == 404
    c.get("/admin/logout")
    login(c)
    assert c.get(detail).status_code == 200
    admin = host.app.test_client()
    admin.post("/admin/login", data={"username": "admin@example.test", "password": "platform-test-pass"})
    assert persisted[0]["reference"] in admin.get("/admin/commandes-manuels").text
    admin_url = f"/admin/commandes-manuels/{persisted[0]['partner_id']}/{persisted[0]['id']}"
    assert admin.post(admin_url, data={"csrf_token": csrf(admin, admin_url), "status": "shipped"}).status_code == 303
    assert "Expédiée" in c.get(detail).text


def test_logo_validation_csrf_and_suspended_account(shop):
    c = shop["client"]
    signup(c)
    login(c)
    form = order_form(c, csrf_token="invalid")
    assert c.post("/admin/manuels/recapitulatif", data=form).status_code == 400
    form = order_form(c, manual_aps="49")
    assert c.post("/admin/manuels/recapitulatif", data=form).status_code == 400
    form = order_form(c, personalization="upload")
    form["logo"] = (io.BytesIO(b'<script>alert(1)</script>'), "logo.png")
    assert c.post("/admin/manuels/recapitulatif", data=form).status_code == 400
    im = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(im, format="PNG")
    im.seek(0)
    form = order_form(c, personalization="upload")
    form["logo"] = (im, "../../logo.png")
    response = c.post("/admin/manuels/recapitulatif", data=form)
    assert response.status_code == 303
    assert c.get(response.location + "/logo").status_code == 200
    pid = all_data(shop)["users"][0]["partner_id"]
    def suspend(data):
        host._partner_or_404(data, pid)["status"] = "suspended"
        return {}
    host._atomic_update_data(suspend, partner_id=pid)
    assert "error=inactive" in c.get("/admin/manuels").location


def test_restriction_survives_missing_cookie_flag(shop):
    c = shop["client"]
    signup(c)
    login(c)
    with c.session_transaction() as cookie:
        cookie.pop("manuals_only", None)
    assert c.post("/api/admin/any", json={}).status_code == 403


def test_draft_can_be_edited_without_losing_selection(shop):
    c = shop["client"]
    signup(c)
    login(c)
    response = c.post("/admin/manuels/recapitulatif", data=order_form(c))
    draft = all_data(shop)["manual_orders"][0]
    edit = c.get("/admin/manuels?draft=" + draft["id"])
    assert 'value="100"' in edit.text and 'value="1 rue Exemple"' in edit.text
    result = c.post("/admin/manuels/recapitulatif", data=order_form(c, draft_id=draft["id"], manual_aps="50"))
    assert result.location == response.location
    orders = all_data(shop)["manual_orders"]
    assert len(orders) == 1
    assert orders[0]["total_cents"] == 179900


@pytest.mark.parametrize("quantity", [50, 99, 100, 101])
def test_brochure_price_boundaries(quantity):
    for book in CATALOGUE:
        item = quote_items({"manual_" + book["code"]: str(quantity)})[0]
        assert item["unit_cents"] == (book["bulk_price"] if quantity >= 100 else book["price"])
        assert item["total_cents"] == item["unit_cents"] * quantity
    assert money(259900) == "2\u202f599,00 €"


@pytest.mark.parametrize("quantity", ["1", "49", "-1", "1.5", "abc", "10001", "99999999999"])
def test_reject_invalid_quantities(quantity):
    with pytest.raises(ValueError):
        quote_items({"manual_aps": quantity})


def test_parallel_registration_does_not_duplicate_json_account(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTNER_POSTGRES_MODE", "off")
    monkeypatch.setattr(host, "DATA_FILE", str(tmp_path / "data.json"))
    monkeypatch.setattr(host, "BACKUP_DIR", str(tmp_path / "backups"))
    (tmp_path / "backups").mkdir()
    Path(host.DATA_FILE).write_text(json.dumps({"sessions": [], "partners": [], "users": []}))
    monkeypatch.setattr(host, "brevo_send_email", lambda *a, **kw: {"ok": True})
    host._partner_login_attempts.clear()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: signup(host.app.test_client()).status_code, range(2)))
    assert sorted(results) == [303, 400]
    assert len(json.loads(Path(host.DATA_FILE).read_text())["users"]) == 1
