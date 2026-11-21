"""Régression des images du courriel CPF dans la prévisualisation et à la réception."""
from pathlib import Path

from flask import Flask
from PIL import Image

from scripts.build_edof_cpf_assets import make_avatar, make_wordmark
from edof_cpf_appointment_mail import message_for


ROOT = Path(__file__).resolve().parents[1]


def test_cassandre_portrait_is_generated_from_official_signature(tmp_path):
    target = tmp_path / "cassandre.png"
    assert make_avatar(dest=target) == target
    with Image.open(target) as picture:
        assert picture.format == "PNG"
        assert picture.size == (256, 256)
        assert picture.getpixel((0, 0))[3] == 0
        assert picture.getpixel((128, 128))[3] == 255


def test_academy_wordmark_is_transparent_for_blue_gradient_header(tmp_path):
    target = tmp_path / "wordmark.png"
    assert make_wordmark(dest=target) == target
    with Image.open(target) as picture:
        assert picture.format == "PNG"
        assert picture.mode == "RGBA"
        assert picture.size == (1110, 250)
        assert picture.getpixel((1105, 2))[3] == 0


def test_cpf_email_is_rendered_with_exact_crm_branding_and_signature():
    app = Flask(__name__, template_folder=str(ROOT / "templates"))
    row = {"folder_id": "123456", "first_name": "Edo", "last_name": "Exemple",
           "title": "Agent de prévention et de sécurité (APS)"}
    with app.app_context():
        html = message_for(row, "edouard@example.test")["html"]
    assert 'src="https://gestionstagiaires-r5no.onrender.com/static/images/email/crm-logo.png" width="148"' in html
    assert 'src="https://gestionstagiaires-r5no.onrender.com/static/images/email/crm-cassandre.png" width="56"' in html
    assert "assistance-alw9.onrender.com/static/logo.png" not in html
    assert "cpf-academy-wordmark.png" not in html
    assert "raw.githubusercontent.com/integraleacademy/integraleacademyofficiel" not in html
    assert "Cassandre MENARD" in html
    assert html.count("<!-- EMAIL_SIGNATURE_START -->") == 1
    assert "Nous avons bien reçu votre demande" in html
    assert "Pack Formation" not in html
    assert 'background:#102c5c;background-image:linear-gradient(135deg,#102c5c 0%,#3269da 100%)' in html
    assert "Faites le premier pas vers votre futur métier" in html
    assert "34 rue Poissonnière, 75002 Paris" in html
    assert "Serif" not in html
    assert "À très bientôt" not in html


def test_original_crm_logo_is_byte_for_byte_same_as_crm_logo():
    from hashlib import sha1
    logo = (ROOT / "static/images/email/crm-logo.png").read_bytes()
    assert sha1(f"blob {len(logo)}\0".encode() + logo).hexdigest() == (
        "d1b7315812a4a4cf3df441862171479dc73cb75d"
    )


def test_original_crm_avatar_is_served_publicly_without_login():
    app = Flask(__name__, static_folder=str(ROOT / "static"))
    client = app.test_client()
    for name in ("crm-logo.png", "crm-cassandre.png"):
        res = client.get("/static/images/email/" + name)
        assert res.status_code == 200
        assert res.mimetype == "image/png"
        assert len(res.data) > 2000
    with Image.open(ROOT / "static/images/email/crm-cassandre.png") as avatar:
        assert avatar.size == (224, 224)


def test_preview_is_sandboxed_without_scripts_but_can_read_same_origin_images():
    template = (ROOT / "templates" / "integrale_edof.html").read_text(encoding="utf-8")
    assert 'sandbox="allow-same-origin"' in template
    assert 'sandbox="allow-same-origin allow-scripts"' not in template
