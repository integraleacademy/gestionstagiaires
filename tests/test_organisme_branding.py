"""A centre's current visual identity reaches only its own learner surfaces."""
import copy
import io
from html.parser import HTMLParser
from urllib.parse import urlsplit

from PIL import Image

import app as host
import elearning_orders as learning
from test_elearning_groups import HiddenFields, create
from test_elearning_orders import mark_paid, submit
from test_manuals_commerce import merchant, retry, run
from test_manuals_shop import all_data, login, shop, signup


PROFILE = "/admin/organisme/mon-organisme"


class ImageSources(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.sources = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.sources.append(dict(attrs).get("src", ""))


def logo_file(color):
    content = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(content, format="PNG")
    content.seek(0)
    return content


def edit_profile(client, *, name, color=None, email=None):
    page = client.get(PROFILE)
    assert page.status_code == 200, page.text
    fields = HiddenFields(page.text, include_visible=True).fields
    fields.update(name=name, phone="01 80 12 34 56", address="20 rue de la Formation", postal_code="75001", city="Paris")
    if email is not None:
        fields["email"] = email
    fields.pop("logo", None)
    fields.pop("remove_logo", None)
    if color:
        fields["logo"] = (logo_file(color), "centre.png")
    response = client.post(PROFILE, data=fields, content_type="multipart/form-data")
    assert response.status_code == 303, response.text


def order_by_id(shop, oid):
    return next(order for order in all_data(shop)["manual_orders"] if order["id"] == oid)


def partner_by_id(shop, pid):
    return next(partner for partner in all_data(shop)["partners"] if partner["id"] == pid)


def another_centre(shop, *, name="Autre organisme", color="red"):
    client = host.app.test_client()
    assert signup(client, email="other@example.test").status_code == 303
    login(client, email="other@example.test")
    edit_profile(client, name=name, color=color)
    partner = next(partner for partner in all_data(shop)["partners"] if partner.get("email") == "other@example.test")
    return client, partner


def test_late_current_logo_and_identity_brand_own_learners_without_changing_purchase_or_merchant(shop, merchant):
    order = submit(shop)
    historical = copy.deepcopy(order["centre"])
    tariff = copy.deepcopy(learning.prices(partner_by_id(shop, order["partner_id"])))
    assert not order["centre"].get("logo_url")
    edit_profile(shop["client"], name="École Horizon", color="blue")
    _, other = another_centre(shop)
    current = order_by_id(shop, order["id"])
    assert current["centre"] == historical and current["total_cents"] == order["total_cents"]
    assert learning.prices(partner_by_id(shop, order["partner_id"])) == tariff
    assert not learning.entitled(current) and not current.get("activated_at")

    brand = learning.learner_brand(all_data(shop), current, host=host)
    own_logo = brand.get("logo_url")
    assert brand["name"] == "École Horizon" and own_logo
    assert own_logo.startswith("https://gestionstagiaires-test-v2.onrender.com/organisme-assets/logos/")
    other_brand = learning.learner_brand(all_data(shop), {"partner_id": other["id"], "centre": {}}, host=host)
    assert other_brand["logo_url"] != own_logo
    asset = host.app.test_client().get(urlsplit(own_logo).path)
    other_asset = host.app.test_client().get(urlsplit(other_brand["logo_url"]).path)
    assert asset.status_code == other_asset.status_code == 200
    assert asset.mimetype == other_asset.mimetype == "image/png" and asset.data != other_asset.data

    run(order)
    assert not order_by_id(shop, order["id"]).get("activated_at")
    mark_paid(merchant)
    retry(order)
    current = order_by_id(shop, order["id"])
    learner_messages = [mail for mail in shop["mails"] if mail[0][0] in {"camille@example.test", "alex@example.test"}]
    assert len(learner_messages) == 2
    for args, kwargs in learner_messages:
        assert own_logo in ImageSources(args[2]).sources
        assert other_brand["logo_url"] not in args[2] and "Autre organisme" not in args[2]
        assert "École Horizon" in args[1] and "École Horizon" in kwargs["text_content"]
        assert kwargs["sender_name"] == "École Horizon"
        assert kwargs["reply_to"]["email"] == "centre@example.test"
    merchant_messages = [mail for mail in shop["mails"] if mail[0][0] == "centre@example.test" and mail[1].get("metadata", {}).get("purpose", "").startswith("elearning_")]
    assert any(mail[1]["metadata"]["purpose"] == "elearning_invoice_paid" for mail in merchant_messages)
    for args, kwargs in merchant_messages:
        assert "INTÉGRALE ACADEMY" in args[2] and "clement@integraleacademy.com" in args[2]
        assert own_logo not in ImageSources(args[2]).sources
        assert not {"sender_name", "sender_email", "reply_to"}.intersection(kwargs)

    token = learning.access_token(host, current, current["learners"][0])
    landing = host.app.test_client().get("/apprendre/" + token)
    assert landing.status_code == 200
    assert own_logo in ImageSources(landing.text).sources
    assert "École Horizon" in landing.text and other_brand["logo_url"] not in landing.text
    assert current["centre"] == historical and current["total_cents"] == order["total_cents"]


def test_centre_without_logo_never_borrows_another_tenants_logo(shop):
    order = submit(shop, free=True)
    edit_profile(shop["client"], name="Centre sans logo")
    _, other = another_centre(shop, name="Centre avec logo")
    data = all_data(shop)
    other_brand = learning.learner_brand(data, {"partner_id": other["id"], "centre": {}}, host=host)
    assert other_brand.get("logo_url")
    # Test lookup independently of tenant ordering in the merged data store.
    data["partners"].sort(key=lambda partner: partner["id"] != other["id"])
    brand = learning.learner_brand(data, order, host=host)
    assert brand["name"] == "Centre sans logo" and not brand.get("logo_url")
    run(order)
    for args, _ in shop["mails"]:
        if args[0] in {"camille@example.test", "alex@example.test"}:
            assert "Centre sans logo" in args[2] and other_brand["logo_url"] not in args[2]
            assert not ImageSources(args[2]).sources
    current = order_by_id(shop, order["id"])
    token = learning.access_token(host, current, current["learners"][0])
    landing = host.app.test_client().get("/apprendre/" + token)
    assert landing.status_code == 200 and "Centre sans logo" in landing.text
    assert not ImageSources(landing.text).sources
    assert other_brand["logo_url"] not in landing.text


def test_an_order_cannot_select_foreign_branding_by_forging_its_snapshot(shop):
    order = submit(shop, free=True)
    edit_profile(shop["client"], name="Centre propriétaire", color="blue")
    _, other = another_centre(shop, name="Centre étranger", color="red")
    data = all_data(shop)
    own = learning.learner_brand(data, order, host=host)
    foreign = learning.learner_brand(data, {"partner_id": other["id"], "centre": {}}, host=host)
    forged = copy.deepcopy(order)
    forged["centre"] = {**copy.deepcopy(other), "logo_url": foreign["logo_url"]}
    resolved = learning.learner_brand(data, forged, host=host)
    assert resolved["name"] == own["name"] == "Centre propriétaire"
    assert resolved["email"] == own["email"] == "centre@example.test"
    assert resolved["logo_url"] == own["logo_url"] != foreign["logo_url"]
    assert order_by_id(shop, order["id"])["centre"] == order["centre"]


def test_login_shows_available_elearning_and_saved_groups_are_not_a_numbered_wizard(shop):
    login_page = host.app.test_client().get("/admin/login")
    assert login_page.status_code == 200
    assert "prochainement" not in login_page.text.casefold()
    assert "APS" in login_page.text and "VTC" in login_page.text
    assert "Disponible" in login_page.text
    assert signup(shop["client"]).status_code == 303
    login(shop["client"])
    url = create(shop["client"])
    group_page = shop["client"].get(url)
    assert group_page.status_code == 200
    assert 'class="el-steps"' not in group_page.text
    assert 'aria-label="Étapes' not in group_page.text


def test_profile_email_replaces_legacy_contact_on_learner_mail_and_landing(shop):
    order = submit(shop, free=True)
    historical = copy.deepcopy(order["centre"])
    legacy = "old-office@example.test"
    current_email = "new-office@example.test"
    host._atomic_update_data(lambda data: host._partner_or_404(data, order["partner_id"]).update(contact_email=legacy), partner_id=order["partner_id"])
    edit_profile(shop["client"], name="Centre actualisé", email=current_email)
    partner = partner_by_id(shop, order["partner_id"])
    assert partner["email"] == current_email and partner["contact_email"] == legacy
    run(order)
    learner_messages = [mail for mail in shop["mails"] if mail[0][0] in {"camille@example.test", "alex@example.test"}]
    assert len(learner_messages) == 2
    for args, kwargs in learner_messages:
        assert kwargs["reply_to"]["email"] == current_email
        assert current_email in args[2] and current_email in kwargs["text_content"]
        assert legacy not in args[2] and legacy not in kwargs["text_content"]
    current = order_by_id(shop, order["id"])
    token = learning.access_token(host, current, current["learners"][0])
    landing = host.app.test_client().get("/apprendre/" + token)
    assert landing.status_code == 200 and current_email in landing.text and legacy not in landing.text
    assert current["centre"] == historical
