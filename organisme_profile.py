"""Self-service centre identity and tightly scoped raster logo publication."""
from __future__ import annotations

import hashlib
import io
import json
import re
import secrets
from pathlib import Path

from flask import abort, flash, redirect, request, send_file, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename

CUSTOMER_ENDPOINTS = {"manuals_shop.organisme_profile", "manuals_shop.organisme_logo_preview"}
PUBLIC_ENDPOINTS = {"manuals_shop.organisme_logo_asset"}
FIELDS = ("name", "siret", "contact_first_name", "contact_last_name", "email", "phone", "address", "address_extra", "postal_code", "city")
MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 16_000_000
MANAGED_NAME = re.compile(r"organisme-([a-f0-9]{64})\.png")
PARTNER_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")


def revision(partner):
    value = {key: partner.get(key, "") for key in (*FIELDS, "logo_url", "logo_path", "logo_filename")}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def logo_path(host, partner):
    """Resolve only a local raster in this centre's own persistent logos folder."""
    pid = str((partner or {}).get("id") or "")
    if not PARTNER_ID.fullmatch(pid):
        return None
    root = Path(host.PERSIST_DIR).resolve() / "partners" / pid / "logos"
    # Reject symlinked tenant directories as well as symlinked image files.
    if root.resolve() != root:
        return None
    for key in ("logo_url", "logo_path"):
        token = str((partner or {}).get(key) or "")
        if not token or "\\" in token or token.startswith("/") or ":" in token:
            continue
        parts = Path(token).parts
        if parts[:3] != ("partners", pid, "logos") or len(parts) != 4 or ".." in parts:
            continue
        candidate = root / parts[3]
        if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        if candidate.resolve() != candidate or not candidate.is_file():
            continue
        return candidate
    return None


def logo_url(host, partner, _external=True):
    """Publish only images decoded and re-encoded by this dedicated uploader."""
    path = logo_path(host, partner)
    match = MANAGED_NAME.fullmatch(path.name) if path else None
    if not match:
        return ""
    relative = "/organisme-assets/logos/" + match.group(1) + ".png"
    if not _external:
        return relative
    from manuals_shop import base_url
    return base_url(host) + relative


def _png(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("Le logo doit peser moins de 5 Mo.")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > MAX_PIXELS:
                raise ValueError("Choisissez un logo PNG, JPEG ou WebP de 16 mégapixels maximum.")
            image.seek(0)
            image.load()
            image = ImageOps.exif_transpose(image).convert("RGBA")
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            # Rebuild pixels so EXIF, ICC and arbitrary upload metadata cannot
            # become public. The first frame is used for animated formats.
            clean = Image.new("RGBA", image.size)
            clean.paste(image)
            while True:
                output = io.BytesIO()
                clean.save(output, format="PNG", optimize=True)
                content = output.getvalue()
                if len(content) <= MAX_BYTES:
                    return content
                # Compressed JPEG/WebP uploads can become much larger as PNG.
                clean.thumbnail((max(1, int(clean.width * .8)), max(1, int(clean.height * .8))), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Ce fichier n’est pas une image valide. Choisissez un logo PNG, JPEG ou WebP.") from exc


def _write_logo(host, pid, raw):
    content = _png(raw)
    root = Path(host.get_partner_storage_path(pid, "logos"))
    expected = Path(host.PERSIST_DIR).resolve() / "partners" / pid / "logos"
    if root.resolve() != expected or expected.resolve() != expected:
        raise ValueError("Le stockage de votre logo n’est pas disponible.")
    destination = root / ("organisme-" + secrets.token_hex(32) + ".png")
    try:
        with destination.open("xb") as stream:
            stream.write(content)
    except OSError:
        _cleanup(host, pid, destination)
        raise
    return destination


def _cleanup(host, pid, path):
    """Delete only our own generated version; never legacy files or other data."""
    if not path:
        return
    path = Path(path)
    expected = Path(host.PERSIST_DIR).resolve() / "partners" / pid / "logos"
    if MANAGED_NAME.fullmatch(path.name) and path.parent == expected and path.resolve() == path:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Cleanup is best effort. A failed old-file deletion must never
            # roll back a committed profile or remove its newly current logo.
            host.app.logger.warning("Unable to remove superseded centre logo")


def _values(form):
    from manuals_shop import valid_siret
    values = {key: str(form.get(key) or "").strip() for key in FIELDS}
    values["email"] = values["email"].lower()
    values["siret"] = re.sub(r"\s", "", values["siret"])
    limits = {"name": 160, "siret": 14, "contact_first_name": 100, "contact_last_name": 100,
              "email": 254, "phone": 40, "address": 200, "address_extra": 200, "postal_code": 20, "city": 100}
    if any(len(value) > limits[key] or any(ord(char) < 32 for char in value) for key, value in values.items()):
        raise ValueError("Certains champs sont trop longs ou contiennent des caractères non autorisés.")
    if len(values["name"]) < 2:
        raise ValueError("Indiquez le nom de votre organisme (2 caractères minimum).")
    if not valid_siret(values["siret"]):
        raise ValueError("Vérifiez votre SIRET : il doit comporter 14 chiffres valides.")
    if not values["contact_first_name"] or not values["contact_last_name"]:
        raise ValueError("Renseignez le prénom et le nom de votre contact.")
    if any(char in values["email"] for char in "?#&") or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", values["email"]):
        raise ValueError("Indiquez une adresse e-mail de contact valide.")
    if values["phone"] and not re.fullmatch(r"[+0-9(). /-]{5,40}", values["phone"]):
        raise ValueError("Vérifiez le numéro de téléphone de votre organisme.")
    return values


def register_routes(host, bp, *, page, customer, partner_data, check_csrf):
    def render(data, partner, *, values=None, errors=None, status=200):
        current_user = next((user for user in data.get("users", []) if user.get("id") == session.get("user_id") and user.get("partner_id") == partner["id"]), {})
        return page("organisme_profile.html", partner=partner, values=partner if values is None else values, errors=errors or [],
                    profile_revision=revision(partner), login_email=current_user.get("email", ""),
                    logo_preview=url_for("manuals_shop.organisme_logo_preview") if logo_path(host, partner) else "",
                    readonly=session.get("admin_role") == "viewer"), status

    @bp.route("/admin/organisme/mon-organisme", methods=["GET", "POST"])
    @customer
    def organisme_profile():
        data, partner = partner_data()
        if request.method == "GET":
            return render(data, partner)
        check_csrf()
        raw_values = {key: str(request.form.get(key) or "").strip() for key in FIELDS}
        uploaded = None
        committed = False
        pid = partner["id"]
        try:
            values = _values(request.form)
            expected = request.form.get("revision", "")
            if not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise ValueError("Rechargez la page avant d’enregistrer vos informations.")
            remove = request.form.get("remove_logo") == "1"
            upload = request.files.get("logo")
            if remove and upload and upload.filename:
                raise ValueError("Choisissez soit de remplacer le logo, soit de le supprimer.")
            original_name = ""
            if upload and upload.filename:
                uploaded = _write_logo(host, pid, upload.stream.read(MAX_BYTES + 1))
                original_name = secure_filename(upload.filename)[:120] or "logo.png"
            elif not remove:
                existing = logo_path(host, partner)
                if existing and not MANAGED_NAME.fullmatch(existing.name):
                    # Upgrade legacy logos safely when the centre saves its profile.
                    uploaded = _write_logo(host, pid, existing.read_bytes() if existing.stat().st_size <= MAX_BYTES else b"")
                    original_name = secure_filename(partner.get("logo_filename") or existing.name)[:120]
            def save(current):
                target = host._partner_or_404(current, pid)
                if target.get("status") not in {"active", "trial"}:
                    abort(403)
                if revision(target) != expected:
                    return {"conflict": True}
                old_logo = logo_path(host, target)
                changed = [key for key in FIELDS if target.get(key, "") != values[key]]
                target.update(values)
                if remove:
                    target.update(logo_url="", logo_path="", logo_filename="")
                    changed.append("logo")
                elif uploaded:
                    token = str(uploaded.relative_to(Path(host.PERSIST_DIR).resolve())).replace("\\", "/")
                    target.update(logo_url=token, logo_path=token, logo_filename=original_name)
                    changed.append("logo")
                target["updated_at"] = host._now_iso()
                host._append_activity_log(current, "organisme_profile_updated", "partner", pid, pid,
                                          {"fields": changed, "logo_action": "removed" if remove else "replaced" if uploaded else "unchanged"})
                return {"old_logo": str(old_logo) if old_logo and (remove or uploaded) else ""}
            result = host._atomic_update_data(save, partner_id=pid)
            if result.get("conflict"):
                _cleanup(host, pid, uploaded)
                data, partner = partner_data()
                return render(data, partner, errors=["Votre organisme a été modifié dans un autre onglet. La version enregistrée est affichée ci-dessous ; vérifiez-la avant de reprendre vos modifications."], status=409)
            committed = True
            _cleanup(host, pid, result.get("old_logo"))
            flash("Les informations de votre organisme ont été enregistrées.", "success")
            return redirect(url_for("manuals_shop.organisme_profile"), code=303)
        except ValueError as exc:
            if not committed:
                _cleanup(host, pid, uploaded)
            return render(data, partner, values=raw_values, errors=[str(exc)], status=400)
        except Exception:
            if not committed:
                _cleanup(host, pid, uploaded)
            raise

    @bp.get("/admin/organisme/mon-organisme/logo")
    @customer
    def organisme_logo_preview():
        _, partner = partner_data()
        path = logo_path(host, partner)
        if not path or path.stat().st_size > MAX_BYTES:
            abort(404)
        try:
            content = _png(path.read_bytes())
        except ValueError:
            abort(404)
        return send_file(io.BytesIO(content), mimetype="image/png", download_name="logo-organisme.png", max_age=0)

    @bp.get("/organisme-assets/logos/<token>.png")
    def organisme_logo_asset(token):
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            abort(404)
        root = Path(host.PERSIST_DIR).resolve() / "partners"
        if root.resolve() != root:
            abort(404)
        # The unguessable filename is a bearer reference to a logo only. No
        # partner profile, auth index, learner or invoice is loaded or returned.
        for path in root.glob("*/logos/organisme-" + token + ".png"):
            pid = path.parent.parent.name
            if not PARTNER_ID.fullmatch(pid) or path.resolve() != path or not path.is_file():
                continue
            if path.stat().st_size > MAX_BYTES:
                continue
            with path.open("rb") as image_file:
                if image_file.read(8) != b"\x89PNG\r\n\x1a\n":
                    continue
            response = send_file(path, mimetype="image/png", download_name="logo-organisme.png", max_age=0)
            response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        abort(404)
