"""APS and A3P examination dossiers, using the SSIAP document visual identity.

The five common documents and the training-specific assessment grids come from
the existing APS/A3P Word models. No marks or examination outcomes are filled in.
"""
import io
import os

from PIL import Image
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics

from ssiap_exam_pdf import (
    W, H, M, WIDTH, NAVY, TEAL, MUTED, LIGHT, GOLD, BOLD,
    candidate_portrait, finish, new_pdf, official_identity, paragraph,
    signature_assets,
)

STYLE_VERSION = "ssiap-2026-v1"
CONTACT = {"contact_email": "ecole@integraleacademy.com", "contact_phone": "04 22 47 07 68"}
ADDRESS = "54 chemin du Carreou · 83480 Puget-sur-Argens (Var, 83)"
PROFILES = {
    "APS": {
        "title": "Agent de Prévention et de Sécurité",
        "cover_title": "Agent de prévention\net de sécurité",
        "hours": 175, "pages": 7,
        "theory": ["UV02 · Environnement juridique", "UV03 · Gestion des conflits",
                   "UV04 · Module stratégique", "UV05 · Incendie", "UV06 · Article 73 CPP",
                   "UV07 · Terrorisme", "UV08 · Professionnel", "UV09 · Palpation",
                   "UV11 · Gestion des risques", "UV10 / 12 / 14 · Événementiel"],
        "practice": ["Prise en compte du PCS", "Contrôle d’accès – inspection visuelle",
                     "Palpation de sécurité", "Ronde de surveillance", "Levée de doute incendie",
                     "Levée de doute intrusion", "Gestion d’un conflit",
                     "Gestion d’un conflit dégradé", "Prise en charge d’une victime"],
    },
    "A3P": {
        "title": "Agent de Protection Physique des Personnes",
        "cover_title": "Agent de protection physique\ndes personnes",
        "hours": 328, "pages": 6,
        "theory": ["UV02 · Environnement juridique", "UV03 · Gestion des conflits",
                   "UV04 · Module stratégique", "UV06 · Professionnel", "UV08 · Gestion des risques"],
        "practice": ["Préparation de mission", "Piétonnage, déplacements", "Convoi",
                     "Secourisme tactique d’urgence (STU)"],
    },
}


def _fitted(c, text, x, top, width, size=16, **kwargs):
    """Keep names on their allocated line without dropping accents or surnames."""
    fitted = min(size, width / max(pdfmetrics.stringWidth(str(text), BOLD, 1), 1))
    return paragraph(c, text, x, top, width, fitted, bold=True, **kwargs)


def _cover_illustration(c, root, training):
    # Display only the illustration from the centre's existing course cover.
    # The PDF clipping window excludes its manual title, hours and logo placeholder.
    path = os.path.join(root, "static", "manuals", training.lower() + ".jpg")
    if not os.path.isfile(path):
        return
    x, y, width, height = W - M - 190, 594, 190, 142.5
    with Image.open(path) as source:
        sw, sh = source.size
    rendered_height = height / 0.44
    rendered_width = sw / sh * rendered_height
    c.saveState()
    clip = c.beginPath()
    clip.rect(x, y, width, height)
    c.clipPath(clip, stroke=0)
    c.drawImage(path, x - (rendered_width - width) / 2, y - rendered_height * 0.12,
                rendered_width, rendered_height)
    c.restoreState()
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.7)
    c.rect(x - 1, y - 1, width + 2, height + 2, stroke=1, fill=0)


def _cover(c, training, profile, trainee, context, root, photo_path):
    c.setFillColor(colors.HexColor("#f7f9fb"))
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, 570, W, H - 570, fill=1, stroke=0)
    c.setFillColor(GOLD)
    c.rect(M, 594, 3, 130, fill=1, stroke=0)
    logo = os.path.join(root, "static", "logo-integrale.png")
    if os.path.isfile(logo):
        c.drawImage(logo, M, 756, 46, 46, preserveAspectRatio=True, mask="auto")
    paragraph(c, "INTÉGRALE ACADEMY", M + 62, 791, WIDTH - 62, 12, colors.white, bold=True)
    paragraph(c, "DOSSIER CANDIDAT · EXAMEN DE CERTIFICATION", M + 62, 770, WIDTH - 62, 7.5, GOLD)
    paragraph(c, "Dossier examen", M + 18, 729, 280, 30, colors.white, bold=True)
    paragraph(c, training, M + 18, 688, 265, 45, GOLD, bold=True)
    paragraph(c, profile["cover_title"], M + 18, 622, 265, 10, colors.white, leading=15)
    _cover_illustration(c, root, training)

    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#dce4ea"))
    c.roundRect(M, 411, WIDTH, 143, 10, fill=1, stroke=1)
    paragraph(c, "CANDIDAT", M + 18, 537, WIDTH - 156, 8, TEAL, bold=True)
    _fitted(c, context["prenom"], M + 18, 517, WIDTH - 156, 22)
    _fitted(c, context["nom"], M + 18, 485, WIDTH - 156, 22)
    paragraph(c, "Référence candidat · " + str(trainee.get("id") or ""),
              M + 18, 441, WIDTH - 156, 7.5, MUTED)
    candidate_portrait(c, photo_path, W - M - 112, 421, 102, 123)
    paragraph(c, "JOUR DE L’EXAMEN", M, 387, 240, 8, TEAL, bold=True)
    paragraph(c, context["date_examen"], M, 371, 240, 21, bold=True)
    paragraph(c, "08h00 – 18h00", M, 339, 240, 11, MUTED)
    paragraph(c, "PÉRIODE DE FORMATION", M + 265, 387, WIDTH - 265, 8, TEAL, bold=True)
    paragraph(c, f"Du {context['date_debut_formation']}\nau {context['date_fin_formation']}",
              M + 265, 367, WIDTH - 265, 12, leading=20)
    c.setFillColor(LIGHT)
    c.roundRect(M, 239, WIDTH, 78, 8, fill=1, stroke=0)
    paragraph(c, "LIEU DE L’EXAMEN", M + 16, 305, WIDTH - 32, 8, TEAL, bold=True)
    paragraph(c, "Intégrale Academy", M + 16, 288, WIDTH - 32, 11, bold=True)
    paragraph(c, ADDRESS, M + 16, 269, WIDTH - 32, 9, MUTED)
    paragraph(c, "Dans ce dossier", M, 218, size=12, bold=True)
    contents = ["Convocation en formation", "Convocation à l’examen", "Attestation EPI",
                "Attestation de fin de formation", "Suivi et évaluation continue"]
    for index, label in enumerate(contents):
        x = M + (265 if index >= 3 else 0)
        top = 192 - (index % 3) * 23
        c.setFillColor(TEAL)
        c.circle(x + 7, top - 6, 7, fill=1, stroke=0)
        paragraph(c, index + 1, x, top, 14, 7.5, colors.white, bold=True, alignment=1)
        paragraph(c, label, x + 22, top, WIDTH - 287, 8.5, MUTED)
    paragraph(c, f"Titre à Finalité Professionnelle (TFP) · {profile['hours']} heures",
              M, 106, size=9, color=TEAL, bold=True)
    c.setStrokeColor(colors.HexColor("#dce4ea"))
    c.line(M, 66, W - M, 66)
    paragraph(c, CONTACT["contact_email"] + " · " + CONTACT["contact_phone"], M, 50, size=8, color=MUTED)


def _header(c, title, subtitle, root):
    c.setFillColor(NAVY)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)
    logo = os.path.join(root, "static", "logo-integrale.png")
    if os.path.isfile(logo):
        c.drawImage(logo, M, H - 102, 62, 62, preserveAspectRatio=True, mask="auto")
    paragraph(c, "INTÉGRALE ACADEMY", M + 85, H - 51, WIDTH - 85, 12, bold=True)
    paragraph(c, "Intégrale Sécurité Formations\n54 chemin du Carreou · 83480 Puget-sur-Argens",
              M + 85, H - 71, WIDTH - 85, 8.5, MUTED)
    c.setStrokeColor(colors.HexColor("#dce4ea"))
    c.line(M, H - 125, W - M, H - 125)
    paragraph(c, title, M, 680, size=25, bold=True, alignment=1)
    paragraph(c, subtitle, M, 641, size=10, color=TEAL, bold=True, alignment=1)


def _candidate(c, context, subtitle):
    c.setFillColor(LIGHT)
    c.roundRect(M, 556, WIDTH, 63, 7, fill=1, stroke=0)
    _fitted(c, context["nom_complet"], M + 14, 607, WIDTH - 28, alignment=1)
    paragraph(c, subtitle, M + 14, 580, WIDTH - 28, 8.5, MUTED, alignment=1)


def _details(c, rows, top):
    for label, value in rows:
        height = 46 if "\n" in value else 37
        c.setFillColor(LIGHT)
        c.roundRect(M, top - height, WIDTH, height - 4, 4, fill=1, stroke=0)
        paragraph(c, label, M + 13, top - 13, 135, 8.5, TEAL, bold=True)
        paragraph(c, value, M + 158, top - 11, WIDTH - 172, 9.5, leading=13)
        top -= height
    return top


def _signature(c, date, assets, top=228):
    paragraph(c, "Fait à Puget-sur-Argens, le " + date, M, top, size=9, alignment=1)
    paragraph(c, "Clément VAILLANT", M, top - 23, size=10.5, bold=True, alignment=1)
    paragraph(c, "Directeur général Intégrale Academy", M, top - 40, size=8.5, color=MUTED, alignment=1)
    for key, x, width in [("signature", W / 2 - 190, 128), ("stamp", W / 2 + 8, 181)]:
        c.drawImage(ImageReader(io.BytesIO(assets[key])), x, top - 119, width, 68,
                    preserveAspectRatio=True, anchor="c", mask="auto")


def _footer(c, training, number, total):
    official_identity(c, CONTACT)
    paragraph(c, f"DOSSIER EXAMEN {training} · {number} / {total}", M, 22,
              size=7, color=MUTED, alignment=2)


def _convocation(c, training, profile, context, root, assets, exam=False):
    _header(c, "Convocation officielle", "À L’EXAMEN" if exam else "EN FORMATION", root)
    recipient = " ".join(filter(None, [context["code_postal"], context["ville"]]))
    _candidate(c, context, recipient)
    paragraph(c, "Nous avons le plaisir de vous convoquer à l’examen final :" if exam else
              "Nous avons le plaisir de vous confirmer votre inscription en formation :",
              M, 536, size=10, leading=15)
    paragraph(c, f"Titre à Finalité Professionnelle (TFP)\n{profile['title']} ({training})",
              M, 507, size=11, bold=True, leading=17)
    paragraph(c, "Session du " + context["periode_formation"], M, 460, size=9.5, color=MUTED)
    rows = [("Date et heure", context["date_examen"] + " à 08h00"), ("Horaires de l’examen", "De 08h00 à 18h00")] if exam else [
        ("Début de formation", context["date_debut_formation"] + " à 08h30"),
        ("Durée de formation", f"{profile['hours']} heures")]
    _details(c, rows + [("Lieu", "Intégrale Academy\n" + ADDRESS)], 434)
    if exam:
        note = ("Merci de vous présenter à l’examen en costume et cravate : chemise blanche, "
                "veste noire, pantalon noir, chaussures noires et cravate noire.")
    else:
        note = ("En cas d’indisponibilité ou de renoncement, merci de nous prévenir au "
                + CONTACT["contact_phone"] + " ou par e-mail à " + CONTACT["contact_email"] + ".")
    paragraph(c, note, M, 295, size=9.5, leading=14)
    paragraph(c, "Nous vous prions d’agréer l’expression de nos salutations distinguées.",
              M, 250, size=9)
    _signature(c, context["date_15_jours_avant_examen"] if exam else
               context["date_un_mois_avant_debut_formation"], assets)


def _attestation(c, training, profile, context, root, assets, epi=False):
    _header(c, "Attestation", "ÉQUIPIER DE PREMIÈRE INTERVENTION" if epi else "DE FIN DE FORMATION", root)
    _candidate(c, context, f"{training} · Session du {context['periode_formation']}")
    paragraph(c, "Je soussigné, Clément VAILLANT, Directeur général d’Intégrale Academy, "
              "représentant l’organisme Intégrale Sécurité Formations, atteste que le candidat "
              "désigné ci-dessus a suivi intégralement la formation :",
              M, 528, size=11, leading=18)
    title = "Équipier de Première Intervention (EPI)" if epi else f"Titre à Finalité Professionnelle (TFP)\n{profile['title']} ({training})"
    paragraph(c, title, M, 446, size=12, bold=True, color=TEAL, leading=18)
    _details(c, [
        ("Date" if epi else "Dates", context["date_formation_epi"] if epi else "Du " + context["periode_formation"]),
        ("Durée", "7 heures" if epi else f"{profile['hours']} heures"),
        ("Lieu", "Intégrale Academy\n" + ADDRESS),
    ], 389)
    _signature(c, context["date_fin_formation"], assets, 238)


def _grid(c, headings, rows, widths, top, row_height):
    c.setFillColor(NAVY)
    c.rect(M, top - 34, WIDTH, 34, fill=1, stroke=0)
    x = M
    for label, width in zip(headings, widths):
        paragraph(c, label, x + 7, top - 7, width - 14, 8, colors.white, bold=True, leading=10)
        x += width
    top -= 34
    for index, label in enumerate(rows):
        c.setFillColor(LIGHT if index % 2 == 0 else colors.white)
        c.setStrokeColor(colors.HexColor("#dce4ea"))
        c.rect(M, top - row_height, WIDTH, row_height, fill=1, stroke=1)
        paragraph(c, label, M + 8, top - 10, widths[0] - 16, 8.5, leading=12)
        x = M
        for width in widths[:-1]:
            x += width
            c.line(x, top, x, top - row_height)
        top -= row_height
    return top


def _assessment(c, training, profile, context, root, practical_only=False):
    _header(c, "Suivi et évaluation continue", "FORMATION THÉORIQUE ET PRATIQUE", root)
    _candidate(c, context, f"TFP {training} · Session du {context['periode_formation']}")
    top = 535
    if not practical_only:
        paragraph(c, "ÉVALUATION THÉORIQUE", M, top, size=9, color=TEAL, bold=True)
        top = _grid(c, ["Unité de valeur", "Note QCU\nd’entraînement", "Commentaire du formateur"],
                    profile["theory"], [220, 92, WIDTH - 312], top - 21, 31 if training == "APS" else 23)
    if training == "A3P" or practical_only:
        top -= 19 if not practical_only else 0
        paragraph(c, "ÉVALUATION PRATIQUE", M, top, size=9, color=TEAL, bold=True)
        top = _grid(c, ["Mise en situation", "Acquis", "Non\nacquis", "Commentaire du formateur"],
                    profile["practice"], [218, 49, 49, WIDTH - 316], top - 21,
                    31 if training == "APS" else 23)
        top -= 17
        paragraph(c, "Commentaire général du formateur", M, top, size=9, bold=True)
        c.setStrokeColor(colors.HexColor("#dce4ea"))
        c.roundRect(M, top - 62, WIDTH, 43, 4, fill=0, stroke=1)
        paragraph(c, "Clément VAILLANT · Directeur général Intégrale Academy", M, top - 72,
                  size=8, color=MUTED)
    else:
        paragraph(c, "Évaluation pratique et commentaire général : page suivante.", M, top - 23,
                  size=9, color=MUTED)


def dossier(training, trainee, context, root, photo_path="", *, draft=False):
    """Return the complete six-page A3P or seven-page APS candidate PDF."""
    profile = PROFILES[training]
    assets = signature_assets(root)
    c, stream = new_pdf(f"Dossier examen {training} - {context['nom_complet']}")
    def mark_draft():
        if draft:
            paragraph(c, "BROUILLON · CALENDRIER À COMPLÉTER", M, 22, 300, 7, TEAL, bold=True)

    _cover(c, training, profile, trainee, context, root, photo_path)
    mark_draft()
    c.showPage()
    for number, exam in [(2, False), (3, True)]:
        _convocation(c, training, profile, context, root, assets, exam)
        _footer(c, training, number, profile["pages"])
        mark_draft()
        c.showPage()
    for number, epi in [(4, True), (5, False)]:
        _attestation(c, training, profile, context, root, assets, epi)
        _footer(c, training, number, profile["pages"])
        mark_draft()
        c.showPage()
    _assessment(c, training, profile, context, root)
    _footer(c, training, 6, profile["pages"])
    mark_draft()
    if training == "APS":
        c.showPage()
        _assessment(c, training, profile, context, root, practical_only=True)
        _footer(c, training, 7, profile["pages"])
        mark_draft()
    raw = finish(c, stream)
    validate(raw, training)
    return raw


def validate(raw, training):
    """Reject incomplete output or PDFs missing the shared embedded typeface."""
    reader = PdfReader(io.BytesIO(raw))
    expected = PROFILES[training]["pages"]
    if len(reader.pages) != expected:
        raise RuntimeError(f"Le dossier {training} doit faire exactement {expected} pages.")
    for number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if not text or "{{" in text or "}}" in text:
            raise RuntimeError(f"Le dossier {training} contient une page incomplète (page {number}).")
        embedded = False
        for ref in (page["/Resources"].get("/Font") or {}).values():
            font = ref.get_object()
            descriptor = font.get("/FontDescriptor")
            if "DejaVuSans" in str(font.get("/BaseFont")) and descriptor:
                embedded |= bool(descriptor.get_object().get("/FontFile2"))
        if not embedded:
            raise RuntimeError(f"La police du dossier {training} n’est pas intégrée (page {number}).")
