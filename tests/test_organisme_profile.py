"""Self-service profile writes stay tenant scoped and only publish safe rasters."""
import copy
import io
import random
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from PIL import Image, PngImagePlugin

import app as host
import organisme_profile as profile
from test_elearning_groups import HiddenFields
from test_manuals_shop import all_data, login, shop, signup

PROFILE = "/admin/organisme/mon-organisme"


def start(shop):
    client = shop["client"]
    assert signup(client).status_code == 303
    login(client)
    return client


def partner(shop, email="centre@example.test"):
    pid = next(user["partner_id"] for user in all_data(shop)["users"] if user["email"] == email)
    return next(item for item in all_data(shop)["partners"] if item["id"] == pid)


def fields(client, **updates):
    page = client.get(PROFILE)
    assert page.status_code == 200
    values = HiddenFields(page.text, include_visible=True).fields
    values.pop("logo", None)
    values.pop("remove_logo", None)
    values.update(updates)
    return values


def raster(fmt="PNG", color="blue"):
    result = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    info.add_text("private-comment", "Should never become public")
    Image.new("RGB", (180, 90), color).save(result, format=fmt, pnginfo=info)
    return result.getvalue()


def upload(client, content=None, **updates):
    form = fields(client, **updates)
    form["logo"] = (io.BytesIO(raster() if content is None else content), "../../centre-original.png")
    return client.post(PROFILE, data=form, content_type="multipart/form-data")


def public_url(item):
    return urlsplit(profile.logo_url(host, item)).path


def test_profile_updates_contact_but_preserves_login_roles_prices_and_other_tenant(shop):
    client = start(shop)
    other = host.app.test_client()
    signup(other, email="other@example.test")
    client.get(PROFILE)  # exercise canonical record normalization before snapshots
    before_other = copy.deepcopy(partner(shop, "other@example.test"))
    before_users = copy.deepcopy(all_data(shop)["users"])
    original = partner(shop)
    response = client.post(PROFILE, data=fields(client, name="École Horizon", email="CONTACT@HORIZON.EXAMPLE.TEST",
        phone="01 80 12 34 56", address="22 rue du Centre", address_extra="Bâtiment A", postal_code="75001", city="Paris",
        partner_id=before_other["id"], status="suspended", enabled_modules="all", max_users="999", elearning_prices="0", role="super_admin", password="new password"))
    assert response.status_code == 303
    changed = partner(shop)
    assert changed["name"] == "École Horizon" and changed["email"] == "contact@horizon.example.test"
    assert changed["address"] == "22 rue du Centre" and changed["address_extra"] == "Bâtiment A"
    for key in ("status", "enabled_modules", "max_users", "account_type", "subscription_plan"):
        assert changed.get(key) == original.get(key)
    assert all_data(shop)["users"] == before_users
    assert partner(shop, "other@example.test") == before_other
    client.get("/admin/logout")
    login(client)
    assert "centre@example.test" in client.get(PROFILE).text
    assert "ne change pas votre identifiant" in client.get(PROFILE).text


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_valid_logo_is_reencoded_opaque_public_and_metadata_free(shop, fmt):
    client = start(shop)
    assert upload(client, raster(fmt)).status_code == 303
    saved = partner(shop)
    path = profile.logo_path(host, saved)
    assert path.parent == Path(host.PERSIST_DIR) / "partners" / saved["id"] / "logos"
    assert profile.MANAGED_NAME.fullmatch(path.name)
    assert saved["logo_filename"] == "centre-original.png"
    url = public_url(saved)
    assert saved["id"] not in url and "centre@example.test" not in url
    asset = host.app.test_client().get(url)
    assert asset.status_code == 200 and asset.mimetype == "image/png"
    assert asset.headers["X-Content-Type-Options"] == "nosniff"
    assert b"Should never become public" not in asset.data
    with Image.open(io.BytesIO(asset.data)) as result:
        assert result.format == "PNG" and result.size == (180, 90)
        assert not result.info
    assert client.get(PROFILE + "/logo").status_code == 200


def test_replace_and_remove_only_revoke_own_generated_logo(shop):
    client = start(shop)
    assert upload(client).status_code == 303
    old = partner(shop)
    old_path, old_url = profile.logo_path(host, old), public_url(old)
    other = host.app.test_client()
    signup(other, email="other@example.test")
    login(other, email="other@example.test")
    assert upload(other, raster(color="red")).status_code == 303
    foreign = partner(shop, "other@example.test")
    assert upload(client, raster(color="green")).status_code == 303
    current = partner(shop)
    current_path, current_url = profile.logo_path(host, current), public_url(current)
    assert not old_path.exists() and client.get(old_url).status_code == 404
    assert client.post(PROFILE, data=fields(client, remove_logo="1")).status_code == 303
    assert not current_path.exists() and client.get(current_url).status_code == 404
    assert not profile.logo_url(host, partner(shop))
    assert host.app.test_client().get(public_url(foreign)).status_code == 200


@pytest.mark.parametrize("bad", [b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', b"not an image", b"x" * (profile.MAX_BYTES + 1)], ids=["svg", "not-image", "over-limit"])
def test_invalid_or_oversized_upload_preserves_profile_and_no_orphan(shop, bad):
    client = start(shop)
    client.get(PROFILE)
    before = copy.deepcopy(partner(shop))
    result = upload(client, bad, name="Change refused")
    assert result.status_code == 400 and 'value="Change refused"' in result.text
    assert partner(shop) == before
    assert not list(Path(host.PERSIST_DIR).glob("partners/*/logos/organisme-*.png"))


def test_csrf_and_viewer_block_profile_and_asset_preview_is_tenant_bound(shop):
    client = start(shop)
    values = fields(client, csrf_token="incorrect", name="Not allowed")
    assert client.post(PROFILE, data=values).status_code == 400
    assert upload(client).status_code == 303
    own = client.get(PROFILE + "/logo").data
    other = host.app.test_client()
    signup(other, email="other@example.test")
    login(other, email="other@example.test")
    assert other.get(PROFILE + "/logo").status_code == 404
    assert upload(other, raster(color="red")).status_code == 303
    assert other.get(PROFILE + "/logo?partner_id=" + partner(shop)["id"]).data != own
    values = fields(client)
    with client.session_transaction() as cookie:
        cookie["admin_role"] = "viewer"
    assert client.get(PROFILE).status_code == 200
    assert client.post(PROFILE, data=values).status_code == 403
    assert host.app.test_client().get(PROFILE).status_code == 302
    assert client.get("/organisme-assets/logos/../../data.json.png").status_code in {302, 404}
    assert client.get("/organisme-assets/logos/" + "a" * 64 + ".png").status_code == 404


def test_concurrent_profile_change_rejects_stale_upload_and_preserves_current_logo(shop):
    client = start(shop)
    stale = fields(client, name="Stale edits")
    assert upload(client, name="Current version").status_code == 303
    saved = partner(shop)
    path = profile.logo_path(host, saved)
    stale["logo"] = (io.BytesIO(raster(color="red")), "stale.png")
    result = client.post(PROFILE, data=stale, content_type="multipart/form-data")
    assert result.status_code == 409
    assert "Current version" in result.text
    assert partner(shop) == saved and path.exists()
    assert list(path.parent.glob("organisme-*.png")) == [path]


def test_legacy_logo_is_previewed_privately_and_migrated_on_profile_save(shop):
    client = start(shop)
    original = partner(shop)
    root = Path(host.get_partner_storage_path(original["id"], "logos"))
    legacy = root / "legacy.jpg"
    legacy.write_bytes(raster("JPEG"))
    token = str(legacy.relative_to(Path(host.PERSIST_DIR)))
    def attach(data):
        host._partner_or_404(data, original["id"]).update(logo_url=token, logo_path=token, logo_filename="legacy.jpg")
        return {}
    host._atomic_update_data(attach, partner_id=original["id"])
    assert not profile.logo_url(host, partner(shop))
    assert client.get(PROFILE + "/logo").mimetype == "image/png"
    assert client.post(PROFILE, data=fields(client)).status_code == 303
    assert legacy.exists()  # historical documents may still refer to it
    assert public_url(partner(shop))
    assert host.app.test_client().get(public_url(partner(shop))).status_code == 200


def test_safe_logo_paths_reject_other_tenant_traversal_remote_and_symlinks(shop):
    client = start(shop)
    assert upload(client).status_code == 303
    item = partner(shop)
    own = profile.logo_path(host, item)
    other_pid = "another-centre"
    foreign_root = Path(host.PERSIST_DIR) / "partners" / other_pid / "logos"
    foreign_root.mkdir(parents=True)
    foreign = foreign_root / own.name
    foreign.write_bytes(raster())
    for value in ("https://other.invalid/logo.png", str(own), "partners/" + other_pid + "/logos/" + own.name,
                  "partners/" + item["id"] + "/logos/../secret.png"):
        forged = dict(item, logo_url=value, logo_path=value)
        assert profile.logo_path(host, forged) is None
    link = own.parent / "symlink.png"
    link.symlink_to(foreign)
    forged = dict(item, logo_url=str(link.relative_to(Path(host.PERSIST_DIR))), logo_path="")
    assert profile.logo_path(host, forged) is None
    profile._cleanup(host, item["id"], foreign)
    assert foreign.exists()


def test_pixel_limit_and_output_size_for_compressed_images():
    large = io.BytesIO()
    Image.new("RGB", (4001, 4000), "white").save(large, format="PNG")
    with pytest.raises(ValueError, match="16 mégapixels"):
        profile._png(large.getvalue())
    image = Image.frombytes("RGB", (1600, 1600), random.Random(42).randbytes(1600 * 1600 * 3))
    compressed = io.BytesIO()
    image.save(compressed, format="JPEG", quality=85)
    assert len(compressed.getvalue()) < profile.MAX_BYTES
    normalized = profile._png(compressed.getvalue())
    assert len(normalized) <= profile.MAX_BYTES
    with Image.open(io.BytesIO(normalized)) as result:
        assert result.format == "PNG" and result.width < 1600


def test_failure_cleaning_old_logo_never_removes_new_committed_logo(shop, monkeypatch):
    client = start(shop)
    assert upload(client).status_code == 303
    old_path = profile.logo_path(host, partner(shop))
    real_unlink = Path.unlink
    def unavailable(path, *args, **kwargs):
        if path == old_path:
            raise PermissionError("old file temporarily locked")
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", unavailable)
    assert upload(client, raster(color="red")).status_code == 303
    current = partner(shop)
    assert profile.logo_path(host, current).exists()
    assert profile.logo_path(host, current) != old_path
    assert host.app.test_client().get(public_url(current)).status_code == 200
