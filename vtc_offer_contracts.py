"""Practical VTC agreements built from the Academy's standard Chauffeur VTC contract."""
from datetime import date
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.shared import Cm

import convention_design
from exam_retakes import date_label


MODEL = Path(__file__).parent / "templates_word" / "conventionvtc.docx"
ADDRESS = "54 chemin du Carreou, 83480 Puget-sur-Argens"
EMAIL = "ecole@integraleacademy.com"
PHONE = "04 22 47 07 68"
PRACTICE_TITLE = "Formation pratique Chauffeur VTC et prêt du véhicule le jour de l’examen"
VEHICLE_TITLE = "Prêt du véhicule à double commande le jour de l’examen pratique VTC"


def _card(doc, text):
    cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = text


def _terms(doc, n, title, *paragraphs):
    doc.add_paragraph(f"Article {n} – {title}")
    for text in paragraphs:
        doc.add_paragraph(text)


def _practice_terms(doc, slot):
    _terms(doc, 1, "Objet et objectifs de la formation",
           "Intégrale Academy prépare le stagiaire à l’épreuve pratique d’admission de conducteur VTC. "
           "La formule comprend une séance de formation en présentiel et la mise à disposition d’un véhicule à double commande pour un passage à l’examen pratique.",
           "À l’issue de la séance, le stagiaire s’est entraîné à préparer une course, accueillir un client, le conduire en sécurité et établir sa facture. "
           "Le programme détaillé figure en annexe. La formation théorique, l’e-learning et les droits d’inscription à l’examen sont exclus du forfait.")
    _terms(doc, 2, "Public, prérequis et accès",
           "Cette action de formation professionnelle s’adresse aux candidats admissibles à l’épreuve pratique VTC, titulaires d’un permis B en cours de validité. "
           "Le stagiaire communique au centre sa convocation dès qu’il la reçoit.",
           "Pour préparer un aménagement de la séance, le stagiaire peut contacter le centre avant sa venue. "
           "Les aménagements de l’examen relèvent de la Chambre de métiers et de l’artisanat (CMA).")
    trainer = (slot or {}).get("trainer")
    _terms(doc, 3, "Organisation, durée et encadrement",
           "Lieu de la formation en présentiel – Intégrale Academy, " + ADDRESS + ".",
           _schedule(slot),
           ("Intervenant désigné – " + trainer.strip() + ". " if trainer else "") +
           "L’encadrement est assuré par un formateur aux métiers du transport public particulier de personnes, qualifié pour la formation Chauffeur VTC. "
           "Le temps de passage à l’examen est distinct de la durée de formation.")
    _terms(doc, 4, "Moyens pédagogiques, suivi et évaluation",
           "Le formateur utilise un véhicule à boîte automatique équipé de doubles commandes. "
           "Il présente les commandes et les consignes de sécurité, puis accompagne le stagiaire dans des mises en situation de transport de passager.",
           "Le formateur observe la préparation du trajet, la conduite, les échanges avec le client et la facturation. "
           "Un exercice de type examen blanc et un débriefing permettent d’identifier les points acquis et ceux à retravailler. "
           "La présence est suivie par émargement. Le centre remet une attestation de réalisation pour la formation effectivement suivie.")
    _terms(doc, 5, "Présentation à l’examen pratique",
           "La CMA organise l’épreuve, en fixe le lieu et les horaires, évalue le candidat et lui communique le résultat. "
           "L’inscription et le paiement des droits auprès de la CMA restent à la charge du candidat.",
           "Le candidat indique Intégrale Academy – Intégrale Sécurité Formations comme établissement fournissant le véhicule. "
           "Il transmet sa convocation au centre pour convenir du rendez-vous et se présente avec les pièces demandées par la CMA. "
           "Une nouvelle présentation après un échec ou une absence nécessite un nouvel accord.")


def _vehicle_terms(doc):
    _terms(doc, 1, "Objet de la mise à disposition",
           "Intégrale Academy réserve au candidat un véhicule à double commande pour un passage à l’épreuve pratique VTC, au centre d’examen convenu. "
           "La mise à disposition couvre la prise en main des commandes à l’arrêt, l’utilisation pendant l’épreuve et la restitution au représentant de l’école.",
           "Le forfait porte uniquement sur le véhicule. Il ne comprend aucune formation, aucun cours théorique, aucun accès e-learning, "
           "aucune séance de préparation à la conduite et aucun droit d’inscription à l’examen.")
    _terms(doc, 2, "Inscription et confirmation du rendez-vous",
           "Le candidat organise son inscription auprès de la Chambre de métiers et de l’artisanat (CMA), règle directement les droits d’examen "
           "et indique Intégrale Academy – Intégrale Sécurité Formations comme établissement mettant le véhicule à disposition.",
           "Dès réception, le candidat adresse à l’école sa convocation officielle avec la date, l’horaire et le lieu de passage. "
           "Le service est proposé à Saint-Laurent-du-Var (06) et à La Valette-du-Var (83). Le centre confirme avec le candidat le point de rencontre correspondant à son passage.")
    _terms(doc, 3, "Prise en charge du véhicule",
           "Au rendez-vous, le candidat présente sa convocation, son permis B en cours de validité et les pièces exigées par la CMA. "
           "Le représentant de l’école lui présente le véhicule, ses doubles commandes et les consignes utiles à la remise.",
           "Avant le départ, le candidat vérifie avec le représentant l’état apparent du véhicule et signale toute anomalie. "
           "Il règle son siège et ses rétroviseurs et vérifie que les conditions permettent de prendre la route en sécurité.")
    _terms(doc, 4, "Utilisation et restitution",
           "Seul le candidat désigné peut utiliser le véhicule pour le passage convenu, sous les consignes de l’examinateur et de l’accompagnateur. "
           "La mise à disposition ne permet ni trajet personnel ni prêt à un tiers.",
           "À la fin de l’épreuve, le candidat remet le véhicule et ses clés au représentant de l’école au lieu convenu. "
           "Il signale immédiatement tout incident et vérifie avec lui les éventuelles observations à consigner.")
    _terms(doc, 5, "Décision de la CMA et nouvelle présentation",
           "L’attestation de mise à disposition établit que l’école fournit le véhicule. Le candidat la présente avec la convocation officielle de la CMA. "
           "La CMA décide de l’admission à l’épreuve et de son résultat.",
           "En cas de modification par la CMA ou d’empêchement du candidat, celui-ci avertit le centre dès qu’il en a connaissance. "
           "Un nouveau passage après un échec ou une absence fait l’objet d’un accord distinct.")


def _schedule(slot):
    slot = slot or {}
    day = slot.get("day") or slot.get("date")
    if not day:
        duration = " Durée prévue de la séance : " + slot["duration"] + "." if slot.get("duration") else ""
        return "Créneau de formation à convenir avec le centre avant la séance." + duration
    result = "Séance pratique le " + date_label(day)
    if slot.get("start") and slot.get("end"):
        result += " de " + slot["start"] + " à " + slot["end"]
    if slot.get("duration"):
        result += " (" + slot["duration"] + ")"
    return result + "."


def _programme(doc):
    doc.add_paragraph("Annexe 1 – Programme de la formation pratique")
    doc.add_paragraph("Le formateur conduit la séance à partir d’une commande de transport. "
                      "Le stagiaire réalise les étapes d’une course et reçoit un retour sur ses décisions.")
    table = doc.add_table(rows=0, cols=2)
    for title, description in (
        ("Compétence travaillée", "Exercices en situation"),
        ("Préparer le parcours", "Lire la commande, repérer les lieux de prise en charge et de dépose, programmer un GPS ou utiliser un plan. Choisir et justifier un itinéraire, puis l’adapter en cas de travaux ou de ralentissement."),
        ("Accueillir et accompagner", "Préparer le véhicule, accueillir le client, vérifier la destination et prendre en compte ses demandes. Aider à l’installation et aux bagages, puis prendre congé à la dépose."),
        ("Conduire en sécurité", "Régler le poste de conduite, anticiper les risques, adapter l’allure et respecter le Code de la route. Rechercher la souplesse, la sécurité et le confort du passager jusqu’à l’arrêt."),
        ("Établir le prix d’une course", "À partir de la commande, calculer le prix de la mission, préparer un devis puis une facture. Expliquer le montant au client et simuler l’encaissement."),
    ):
        cells = table.add_row().cells
        cells[0].text, cells[1].text = title, description
    doc.add_paragraph().add_run("Bilan de la séance").bold = True
    doc.add_paragraph("Sur un parcours d’examen blanc, le stagiaire enchaîne les étapes sans guidage continu. Le formateur reprend avec lui les choix d’itinéraire, "
                      "les situations de conduite et la relation avec le client, puis précise les points à retravailler avant le passage devant la CMA.")
    return table


def _finance(doc, practice, price, payment, online_order, cpf, funding):
    _terms(doc, 7, "Prix et modalités de règlement")
    table = doc.add_table(rows=2, cols=2)
    for cells, values in zip((r.cells for r in table.rows), (("Prestation convenue", "Prix forfaitaire TTC"),
                              (PRACTICE_TITLE if practice else VEHICLE_TITLE, price))):
        cells[0].text, cells[1].text = values
    if payment:
        doc.add_paragraph("Mode de règlement convenu – " + payment + ".")
    for text in funding:
        doc.add_paragraph(text)
    if cpf:
        doc.add_paragraph("Les montants mobilisés, l’éventuelle participation personnelle et les règles de règlement figurent dans le dossier Mon Compte Formation. "
                          "Le candidat consulte son espace personnel pour toute opération sur ses droits.")
    elif practice and online_order:
        doc.add_paragraph("Aucun acompte. Le règlement intervient après la réalisation de la séance et la mise à disposition du véhicule, à l’issue du délai de rétractation.")
    elif practice:
        doc.add_paragraph("Pour un contrat individuel financé à titre personnel, aucune somme ne peut être exigée avant l’expiration du délai de rétractation. "
                          "À son issue, un versement initial éventuel est limité à 30 % du prix. Le solde est échelonné au fur et à mesure du déroulement de l’action, selon l’échéancier convenu dans le dossier.")
    else:
        doc.add_paragraph("Le candidat règle le forfait selon les modalités convenues à l’inscription et reprises sur sa facture. Les droits réclamés par la CMA sont distincts du prix du véhicule.")


def _withdrawal(doc, practice, online_order, cpf):
    paragraphs = []
    if cpf:
        paragraphs.append("Pour une commande financée sur Mon Compte Formation, le stagiaire exerce sa rétractation ou signale son annulation depuis son dossier sur la plateforme, "
                          "selon les conditions acceptées lors de la commande. Il informe également le centre afin de libérer le créneau et le véhicule.")
    elif practice:
        paragraphs.append("Pour un contrat de formation conclu à titre individuel et à ses frais, le stagiaire peut se rétracter par lettre recommandée avec avis de réception "
                          "dans les dix jours suivant la signature (article L. 6353-5 du Code du travail). Pour un contrat conclu à distance avec un consommateur, le délai est de quatorze jours à compter de sa conclusion.")
    elif online_order:
        paragraphs.append("Le centre accorde un délai de rétractation de quatorze jours à compter de la commande du véhicule, avant l’exécution de la prestation.")
    else:
        paragraphs.append("Le candidat peut demander le report ou l’annulation au centre par écrit. Pour une réservation conclue à distance ouvrant droit à rétractation, le délai est de quatorze jours à compter de la conclusion de la convention.")
    if not cpf:
        paragraphs.append("Pour la rétractation à distance, le candidat peut adresser au centre une déclaration identifiant le contrat et exprimant sans ambiguïté sa décision, par courrier ou par e-mail. " +
                          ("Il peut également utiliser le bouton de rétractation de son espace de suivi de commande. " if online_order else "") +
                          "Coordonnées de l’école – " + EMAIL + " ou " + ADDRESS + ".")
    _terms(doc, 8, "Rétractation et démarches", *paragraphs)
    if practice:
        interruption = ("Pour un dossier Mon Compte Formation, les conséquences financières d’une annulation, d’une absence ou d’un abandon sont déterminées selon les conditions du dossier sur la plateforme."
                        if cpf else "En cas d’interruption pour force majeure dûment reconnue, seules les prestations effectivement dispensées sont dues à proportion de leur réalisation.")
        if not cpf:
            interruption += " En cas d’abandon de cette formule, seules les prestations effectivement réalisées sont dues au prorata de leur valeur."
    else:
        interruption = "Si la CMA déplace le passage, le candidat transmet la nouvelle convocation avant de se rendre au rendez-vous. Le centre et le candidat confirment par écrit la disponibilité du véhicule."
    _terms(doc, 9, "Report, interruption et annulation",
           interruption, "En cas d’indisponibilité de l’établissement, celui-ci propose une nouvelle date avec l’accord du candidat ou rembourse les prestations payées et non réalisées.")


def build(*, practice, person, price, exam_day, centre, reference, slot=None, payment="", online_order=False, cpf=False, funding=()):
    """Keep the approved issuer, signature artwork and (for training) the school rules in the same Word package."""
    doc = Document(MODEL)
    tables = doc.tables
    cover = tables[0].cell(0, 0)
    identity = next(t for t in tables if t.cell(0, 0).text.startswith("Et le stagiaire"))
    signature = next(t for t in tables if t.cell(0, 0).text == "Pour le stagiaire")
    rules_title = next(t for t in tables if t.cell(0, 0).text.startswith("RÈGLEMENT INTÉRIEUR"))
    body = doc.element.body
    nodes = list(body)
    rules_end = next(n for n in nodes if n.tag == qn("w:p") and Paragraph(n, doc).text.strip() == "Signature du règlement intérieur")
    rules = nodes[nodes.index(rules_title._tbl):nodes.index(rules_end)]
    for node in nodes[nodes.index(identity._tbl) + 1:]:
        if node.tag != qn("w:sectPr"):
            body.remove(node)

    name = " ".join(filter(None, (str(person.get("first_name") or person.get("prenom") or "").strip(),
                                  str(person.get("last_name") or person.get("nom") or "").strip().upper())))
    if not name:
        raise ValueError("Renseignez le prénom et le nom du candidat avant la génération du document.")
    address = ", ".join(filter(None, (person.get("address") or person.get("adresse"),
                         " ".join(filter(None, (person.get("zip_code") or person.get("code_postal"), person.get("city") or person.get("ville")))))))
    contact = "  ·  ".join(filter(None, (person.get("email") or person.get("mail"), person.get("phone") or person.get("telephone"))))
    identity.cell(0, 0).text = "\n".join(filter(None, (("Et le stagiaire – " if practice else "Et le candidat – ") + name, address, contact)))
    if cpf and practice:
        cover.paragraphs[0].text = "Convention de formation professionnelle"
        cover.paragraphs[1].text = "Formation pratique Chauffeur VTC · Mon Compte Formation"
    if not practice:
        cover.paragraphs[0].text = "Convention de mise à disposition d’un véhicule"
        cover.paragraphs[1].text = "Examen pratique de chauffeur VTC"
        signature.cell(0, 0).text = "Pour le candidat"
        signature.cell(0, 1).text = "Pour l’établissement"
    signature.cell(1, 0).text = name
    _card(doc, (PRACTICE_TITLE if practice else VEHICLE_TITLE) + "\n" + price)
    if practice:
        doc.add_paragraph(_schedule(slot))
    doc.add_paragraph("Examen pratique – " + (date_label(exam_day) if exam_day else "date et horaire selon convocation officielle de la CMA") + ".")
    doc.add_paragraph("Centre d’examen – " + (centre or "lieu à confirmer sur la convocation de la CMA") + ".")
    if practice:
        _practice_terms(doc, slot)
    else:
        _vehicle_terms(doc)
    _terms(doc, 6, "Sécurité, incidents et responsabilité",
           "Le candidat respecte le Code de la route et les consignes du formateur, de l’accompagnateur ou de l’examinateur. "
           "Il signale immédiatement tout dommage, dysfonctionnement ou incident. Les circonstances sont relevées avec le représentant du centre.",
           "En cas de dommage imputable à une faute, une négligence, une mauvaise utilisation ou un non-respect des consignes, "
           "les frais de réparation, la franchise d’assurance ou les sommes restant à la charge de l’école peuvent être réclamés sur justificatifs. "
           "L’usure normale, les défauts techniques et les dommages non imputables au candidat sont exclus.")
    _finance(doc, practice, price, payment, online_order, cpf, funding)
    _withdrawal(doc, practice, online_order, cpf)
    _terms(doc, 10, "Réclamation et règlement des différends",
           "Le candidat peut adresser une réclamation à Intégrale Academy, " + ADDRESS + ", ou à " + EMAIL +
           ", en précisant son nom, la référence du document et les faits concernés. Le secrétariat est joignable au " + PHONE + ". "
           "L’école et le candidat recherchent une solution amiable. À défaut d’accord, le litige relève des juridictions compétentes.")
    if practice:
        doc.add_paragraph("Signature de la convention de formation" if cpf else "Signature du contrat de formation")
    else:
        doc.add_paragraph("Signature de la convention de mise à disposition")
    acceptance = doc.add_paragraph("En signant, le stagiaire accepte les conditions de formation, le programme pratique et le règlement intérieur joints en annexe."
                      if practice else "En signant, le candidat accepte les conditions de mise à disposition et le prix du véhicule pour le passage convenu.")
    doc.add_paragraph("Fait à Puget-sur-Argens, le " + date.today().strftime("%d/%m/%Y") + ".")
    body.sectPr.addprevious(signature._tbl)
    if practice:
        programme = _programme(doc)
        for node in rules:
            body.sectPr.addprevious(node)
    convention_design.style_document(doc, reference_key=reference)
    acceptance.paragraph_format.keep_with_next = True
    if practice:
        for column, width in zip(programme.columns, (5.4, 12.0)):
            column.width = Cm(width)
            for cell in column.cells:
                cell.width = Cm(width)
    return doc
