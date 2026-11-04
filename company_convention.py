"""Employer agreements built from the course's own Intégrale Academy Word model."""
from copy import deepcopy
from pathlib import Path
import re
import subprocess
import tempfile

from docx import Document
from docx.text.paragraph import Paragraph
from convention_design import restyle_file

COURSES = {"aps", "a3p", "desp_paris", "desp_puget", "vtc", "ssiap", "vae"}


def _write(paragraph, text):
    """Keep the original paragraph and character formatting."""
    runs = paragraph.runs
    first = next((run for run in runs if run.text.strip()), None)
    for run in runs:
        run.text = ""
    (first if first is not None else paragraph.add_run()).text = text


def _article(document, number):
    return next(p for p in document.paragraphs
                if re.match(rf"^Article\s+{number}\s*[-–]", p.text.strip()))


def build_document(template, company, values):
    doc = Document(template)
    if Path(template).stem == 'conventionvae':
        return build_vae_document(doc, company, values)
    tables = doc.tables
    title, legal = tables[0].cell(0, 0).paragraphs[:2]
    _write(title, "Convention de formation professionnelle")
    _write(legal, "(Articles L. 6353-1 et D. 6353-1 du Code du travail)")
    _write(tables[1].cell(0, 0).paragraphs[0],
           f"Entreprise acheteuse : {company['name']}\n{company['address']}\n"
           f"Représentée par {company['representative']}")
    first_article = _article(doc, 1)
    intro = next(p for p in doc.paragraphs if "ci-après nommé le stagiaire" in p.text)
    _write(intro, f"Salarié bénéficiaire : {values['nom_complet']}. "
           "L’entreprise s’engage à permettre sa participation aux dates et horaires prévus.")
    body_text = next(p for p in doc.paragraphs if "En exécution du présent contrat" in p.text)
    _write(body_text, "L’entreprise confie à Intégrale Academy la formation d’un salarié pour l’action suivante.")
    # Keep the pedagogical articles, course title, price grid and signature artwork.
    # Replace the individual financing, withdrawal and cancellation terms as a unit.
    financial_table = deepcopy(tables[3]._tbl)
    signature = next(t for t in tables if t.cell(0, 0).text == "Pour le stagiaire")
    _write(signature.cell(0, 0).paragraphs[0], "Pour l’entreprise")
    _write(signature.cell(1, 0).paragraphs[0], company['representative'])
    for p in signature.cell(2, 0).paragraphs:
        _write(p, "")
    _write(signature.cell(2, 0).paragraphs[0], "Date et signature")
    body = doc.element.body
    cutoff = body.index(_article(doc, 7)._p)
    for node in list(body)[cutoff:]:
        if node is not body.sectPr:
            body.remove(node)

    def add(prototype, text):
        node = deepcopy(prototype._p)
        body.sectPr.addprevious(node)
        paragraph = Paragraph(node, doc)
        _write(paragraph, text)
        paragraph.paragraph_format.keep_with_next = prototype is first_article or text.startswith("Fait à ")

    for p in doc.paragraphs:
        value = p.text.strip()
        if value.startswith(("En conséquence, les dispositions financières", "Lorsque le défaut d’assiduité",
                             "Le programme de l’action de formation figure en annexe")):
            body.remove(p._p)
        elif "(voir article 10)" in value:
            _write(p, value.replace(" (voir article 10)", ""))
        elif value.startswith("Lieu de la formation") and values['lieu_formation'] not in ("", "À préciser"):
            _write(p, "Lieu de la formation : " + values['lieu_formation'])

    add(first_article, "Article 7 – Participation et suivi de l’exécution")
    add(body_text, f"Part des enseignements dispensés à distance : {company['remote_rate']} %. "
        "Les horaires sont ceux du planning communiqué à l’entreprise. La présence en salle est "
        "attestée par émargement. Pour les séquences à distance, le suivi repose sur les relevés "
        "de connexion, les activités réalisées et leurs évaluations.")
    add(first_article, "Article 8 – Prix et conditions de règlement")
    body.sectPr.addprevious(financial_table)
    add(body_text, "L’entreprise prend en charge le prix indiqué ci-dessus pour le salarié désigné. "
        + company['payment'])
    add(first_article, "Article 9 – Interruption ou non-réalisation")
    add(body_text, "En cas d’interruption, les parties établissent les heures effectivement réalisées. "
        "Intégrale Academy facture les prestations assurées et restitue à l’entreprise les sommes "
        "perçues au titre des prestations non réalisées, conformément à l’article L. 6354-1 du Code du travail.")
    add(first_article, "Article 10 – Règlement des différends")
    add(body_text, "Les parties recherchent une solution amiable avant de saisir la juridiction compétente.")
    add(first_article, "Signature de la convention")
    add(body_text, f"Fait à Puget-sur-Argens, le {values['date_jour']}.")
    body.sectPr.addprevious(signature._tbl)
    return doc


def build_vae_document(doc, company, values):
    """Keep the VAE programme and limits; identify employer and beneficiary separately."""
    from docx.shared import Pt
    title = next(p for p in doc.paragraphs if 'Convention d’accompagnement' in p.text)
    _write(title, 'Convention d’accompagnement VAE – financement entreprise')
    beneficiary = doc.tables[0]
    beneficiary.cell(0, 0).paragraphs[0].insert_paragraph_before(
        f"Entreprise financeuse : {company['name']}\n{company['address']}\nReprésentée par {company['representative']}")
    _write(beneficiary.cell(0, 0).paragraphs[-1], f"Bénéficiaire de l’accompagnement : {values['nom_complet']}")
    signature = next(t for t in doc.tables if t.cell(0, 0).text == 'Pour le stagiaire')
    _write(signature.cell(0, 0).paragraphs[0], 'Pour le bénéficiaire')
    _write(signature.cell(1, 0).paragraphs[0], values['nom_complet'])
    for p in signature.cell(2, 0).paragraphs:
        _write(p, '')
    _write(signature.cell(2, 0).paragraphs[0], 'Signature du bénéficiaire')
    price_table = deepcopy(doc.tables[2]._tbl)
    body = doc.element.body
    for node in list(body)[body.index(_article(doc, 10)._p):]:
        if node is not body.sectPr:
            body.remove(node)
    doc.add_paragraph('Article 10 – Prise en charge par l’entreprise')
    body.sectPr.addprevious(price_table)
    doc.add_paragraph(f"L’entreprise prend en charge le prix total de l’accompagnement VAE indiqué ci-dessus. {company['payment']}")
    doc.add_paragraph('Aucun reste à charge personnel n’est prévu pour le bénéficiaire au titre de cette convention. Les prestations, la certification visée et les modalités d’accompagnement sont celles des articles précédents.')
    doc.add_paragraph('Article 11 – Consentement et suivi de l’accompagnement')
    doc.add_paragraph('Le bénéficiaire consent librement à la démarche VAE. L’entreprise permet sa participation aux rendez-vous convenus. La signature de la présente convention intervient après production du document attestant de la recevabilité de la demande de VAE.')
    if company.get('receivability_date'):
        doc.add_paragraph('Date du document de recevabilité : ' + company['receivability_date'])
    doc.add_paragraph(f"Part de l’accompagnement réalisée à distance : {company['remote_rate']} %. Le suivi est établi à partir des rendez-vous, échanges et travaux d’accompagnement effectivement réalisés.")
    doc.add_paragraph('Article 12 – Interruption ou non-réalisation')
    doc.add_paragraph('En cas d’interruption, les parties établissent les prestations effectivement réalisées. Intégrale Academy facture les prestations assurées et restitue à l’entreprise les sommes perçues au titre des prestations non réalisées, conformément à l’article L. 6354-1 du Code du travail.')
    doc.add_paragraph('Article 13 – Règlement des différends')
    doc.add_paragraph('Les parties recherchent une solution amiable avant de saisir la juridiction compétente.')
    doc.add_paragraph(f"Fait à Puget-sur-Argens, le {values['date_jour']}.")
    body.sectPr.addprevious(signature._tbl)
    employer = doc.add_table(rows=3, cols=1)
    employer.cell(0, 0).text = 'Pour l’entreprise'
    employer.cell(1, 0).text = company['representative']
    employer.cell(2, 0).text = 'Signature de l’entreprise'
    employer.rows[2].height = Pt(85)
    signature.rows[2].height = Pt(85)
    return doc


def render(template, company, values, replace_placeholders, validate, office, destination, *, reference_key=None):
    with tempfile.TemporaryDirectory(prefix="convention-entreprise-") as directory:
        root = Path(directory)
        source = root / "convention-entreprise.docx"
        build_document(template, company, values).save(source)
        replace_placeholders(str(source), values)
        restyle_file(source, reference_key=reference_key or (
            Path(template).stem, company.get("name"), values.get("nom_complet"), values.get("periode_formation")))
        validate(str(source))
        subprocess.run([office, "-env:UserInstallation=" + (root / "profile").as_uri(),
                        "--headless", "--convert-to", "pdf", "--outdir", directory, str(source)],
                       check=True, capture_output=True, timeout=120)
        pdf = source.with_suffix(".pdf").read_bytes()
        if not pdf.startswith(b"%PDF-"):
            raise ValueError("Le convertisseur n’a pas produit de PDF.")
        destination.write(pdf)
