"""Platform header stays fixed; the home welcome block uses the centre's logo."""
import io
from html.parser import HTMLParser
from urllib.parse import urlsplit

from PIL import Image

import app as host
from test_manuals_shop import all_data, login, shop, signup
from test_organisme_branding import PROFILE, edit_profile


PREVIEW = PROFILE + "/logo"


class HeaderIdentity(HTMLParser):
    """Read only .site-header a.logo; ignore unrelated footer and content images."""
    def __init__(self, html):
        super().__init__()
        self.in_header = False
        self.in_logo = False
        self.images = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "header" and "site-header" in classes:
            self.in_header = True
        if self.in_header and tag == "a" and "logo" in classes:
            self.in_logo = True
        if self.in_logo and tag == "img":
            self.images.append(attributes)

    def handle_endtag(self, tag):
        if tag == "a":
            self.in_logo = False
        if tag == "header":
            self.in_header = False

    def handle_data(self, data):
        if self.in_logo:
            self.text.append(data)


class WelcomeIdentity(HTMLParser):
    """Read only .portal-welcome; exclude platform, footer and manual images."""
    def __init__(self, html):
        super().__init__()
        self.in_welcome = False
        self.found = False
        self.images = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "section" and "portal-welcome" in attributes.get("class", "").split():
            self.in_welcome = self.found = True
        if self.in_welcome and tag == "img":
            self.images.append(attributes)

    def handle_endtag(self, tag):
        if tag == "section":
            self.in_welcome = False

    def handle_data(self, data):
        if self.in_welcome:
            self.text.append(data)


def header(client, path):
    page = client.get(path)
    assert page.status_code == 200, page.text
    return HeaderIdentity(page.text)


def welcome(client, path="/admin/organisme"):
    page = client.get(path)
    assert page.status_code == 200, page.text
    return WelcomeIdentity(page.text)


def centre(shop, *, name="Centre Horizon", color=None):
    client = shop["client"]
    assert signup(client).status_code == 303
    login(client)
    edit_profile(client, name=name, color=color)
    return client


def rgb(response):
    assert response.status_code == 200 and response.mimetype == "image/png"
    with Image.open(io.BytesIO(response.data)) as image:
        return image.convert("RGB").getpixel((image.width // 2, image.height // 2))


def test_platform_header_stays_fixed_and_own_logo_appears_in_home_welcome_only(shop):
    client = centre(shop, color="blue")
    for path in ("/admin/organisme", "/admin/organisme/e-learning", PROFILE):
        identity = header(client, path)
        assert len(identity.images) == 1
        assert identity.images[0]["alt"] == "Intégrale Connect"
        assert urlsplit(identity.images[0]["src"]).path == "/static/logoic.png"
        if path != "/admin/organisme":
            assert not welcome(client, path).found
    identity = welcome(client)
    assert identity.found and len(identity.images) == 1
    assert identity.images[0]["alt"] == "Logo de Centre Horizon"
    assert urlsplit(identity.images[0]["src"]).path == PREVIEW
    assert rgb(client.get(identity.images[0]["src"])) == (0, 0, 255)


def test_no_centre_logo_uses_name_in_welcome_and_keeps_platform_header(shop):
    client = centre(shop, name="Horizon Formation")
    for path in ("/admin/organisme", "/admin/organisme/e-learning", PROFILE):
        identity = header(client, path)
        assert len(identity.images) == 1
        assert identity.images[0]["alt"] == "Intégrale Connect"
        assert urlsplit(identity.images[0]["src"]).path == "/static/logoic.png"
    identity = welcome(client)
    assert identity.found and not identity.images
    visible = [value.strip() for value in identity.text if value.strip()]
    assert "Horizon Formation" in visible
    assert "CONNECT" not in visible and "ic" not in visible
    assert client.get(PREVIEW).status_code == 404


def test_logo_preview_and_home_welcome_never_use_another_tenants_image(shop):
    owner = centre(shop, name="Centre bleu", color="blue")
    other = host.app.test_client()
    assert signup(other, email="other@example.test").status_code == 303
    login(other, email="other@example.test")
    edit_profile(other, name="Centre rouge", color="red")
    partners = all_data(shop)["partners"]
    own_partner = next(partner for partner in partners if partner.get("email") == "centre@example.test")
    other_partner = next(partner for partner in partners if partner.get("email") == "other@example.test")
    identity = welcome(owner, "/admin/organisme?partner_id=" + other_partner["id"])
    assert identity.images[0]["alt"] == "Logo de Centre bleu"
    assert rgb(owner.get(PREVIEW + "?partner_id=" + other_partner["id"])) == (0, 0, 255)
    assert welcome(other).images[0]["alt"] == "Logo de Centre rouge"
    assert rgb(other.get(PREVIEW)) == (255, 0, 0)
    assert host.app.test_client().get(PREVIEW).status_code == 302

    # Even a stale or malformed stored logo reference cannot borrow another
    # centre's image; the welcome block falls back to its own textual identity.
    host._atomic_update_data(lambda data: host._partner_or_404(data, own_partner["id"]).update(
        logo_url=other_partner["logo_url"], logo_path=other_partner["logo_path"]), partner_id=own_partner["id"])
    fallback = welcome(owner)
    assert not fallback.images and "Centre bleu" in " ".join(fallback.text)
    assert owner.get(PREVIEW).status_code == 404
    assert rgb(other.get(PREVIEW)) == (255, 0, 0)


def test_public_registration_and_login_keep_platform_identity_after_logout(shop):
    client = centre(shop, color="blue")
    client.get("/admin/logout")
    registration = header(client, "/creer-mon-espace")
    assert len(registration.images) == 1
    assert registration.images[0]["alt"] == "Intégrale Connect"
    assert urlsplit(registration.images[0]["src"]).path == "/static/logoic.png"
    login_page = client.get("/admin/login")
    assert login_page.status_code == 200
    assert 'class="brand-logo" src="/static/logoic.png" alt="Intégrale Connect"' in login_page.text
    assert PREVIEW not in login_page.text


def test_staff_header_keeps_platform_identity_when_viewing_a_partner(shop):
    centre(shop, name="Centre Horizon", color="blue")
    pid = next(partner["id"] for partner in all_data(shop)["partners"] if partner.get("email") == "centre@example.test")
    staff = host.app.test_client()
    login_response = staff.post("/admin/login", data={"username": "admin@example.test", "password": "platform-test-pass"})
    assert login_response.status_code == 302
    identity = header(staff, "/admin/commandes-elearning?partner_id=" + pid)
    assert len(identity.images) == 1
    assert identity.images[0]["alt"] == "Intégrale Connect"
    assert urlsplit(identity.images[0]["src"]).path == "/static/logoic.png"
