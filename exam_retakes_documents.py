"""Academy retake agreements, exam invitations and email presentations."""
from html import escape
from io import BytesIO
from pathlib import Path

import desp_paris_venue
from training_convocations import PORTAL_URL

from exam_retakes import date_label, discount_label, financial_totals, line_items, money
from convention_design import REGISTRATION_LINES


def retake_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    regular = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if regular.is_file():
        if 'RetakeSans' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('RetakeSans', str(regular)))
            pdfmetrics.registerFont(TTFont('RetakeSans-Bold', str(regular.with_name('DejaVuSans-Bold.ttf'))))
            pdfmetrics.registerFontFamily('RetakeSans', normal='RetakeSans', bold='RetakeSans-Bold')
        return 'RetakeSans'
    return 'Helvetica'


def retake_page_frame(font, document_label, ref, heading="VOTRE RATTRAPAGE"):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    static = Path(__file__).parent / 'static'
    if document_label == 'CONVOCATION':
        logo_path = static / 'logo-integrale.png'
        logo_width, logo_height, logo_bottom = 55, 55, 77.5
    else:
        logo_path = static / 'parcours-alternance' / 'logo.png'
        logo_width, logo_height, logo_bottom = 215, 64, 86
    logo = ImageReader(str(logo_path))
    navy, gold, muted = (colors.HexColor(v) for v in ('#14283F', '#F3C65F', '#596A7D'))
    def frame(canvas,doc):
        canvas.saveState();canvas.setFillColor(navy);canvas.rect(0,A4[1]-100,A4[0],100,stroke=0,fill=1)
        canvas.drawImage(logo, 48, A4[1] - logo_bottom, width=logo_width, height=logo_height,
                         mask='auto', preserveAspectRatio=True)
        canvas.setFillColor(gold);canvas.setFont(font+'-Bold',9);canvas.drawRightString(547,A4[1]-42,heading)
        canvas.setFillColor(colors.white);canvas.setFont(font,8);canvas.drawRightString(547,A4[1]-61,document_label+' '+ref)
        canvas.setFillColor(gold);canvas.rect(0,A4[1]-103,A4[0],3,stroke=0,fill=1)
        canvas.setStrokeColor(colors.HexColor('#D5DFE9'));canvas.line(48,66 if document_label == 'CONVENTION' else 42,547,66 if document_label == 'CONVENTION' else 42)
        canvas.setFont(font,7);canvas.setFillColor(muted)
        canvas.drawString(48,53 if document_label == 'CONVENTION' else 29,'Intégrale Academy - 04 22 47 07 68 - ecole@integraleacademy.com')
        if document_label == 'CONVENTION':
            canvas.setFont(font,6.8)
            for y, line in zip((42, 31), REGISTRATION_LINES):
                canvas.drawString(48,y,line)
        canvas.drawRightString(547,29,'Page '+str(doc.page));canvas.restoreState()
    return frame


def build_convention(row, destination):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable, PageBreak
    font = retake_font()
    navy, gold = colors.HexColor('#14283F'), colors.HexColor('#F3C65F')
    pale, green = colors.HexColor('#F1F5FA'), colors.HexColor('#E8F5EE')
    body = ParagraphStyle('RetakeBody', fontName=font, fontSize=9, leading=13.5, textColor=navy, spaceAfter=7)
    title = ParagraphStyle('RetakeTitle', parent=body, fontName=font+'-Bold', fontSize=23, leading=29, spaceAfter=10)
    small = ParagraphStyle('RetakeSmall', parent=body, fontSize=8, leading=11.5)
    heading = ParagraphStyle('RetakeHeading', parent=body, fontName=font+'-Bold', fontSize=11.5, leading=16, spaceBefore=12, spaceAfter=8, keepWithNext=True)
    total_style = ParagraphStyle('RetakeAmount', parent=body, fontName=font+'-Bold', fontSize=17, leading=22, textColor=colors.HexColor('#176344'))
    p = lambda value, style=body: Paragraph(value, style)
    plain = lambda value: escape(str(value or '')).replace('\n','<br/>')
    person, ref = row['person'], row['id'][:12].upper()
    full_name = person['first_name']+' '+person['last_name']
    items, totals = line_items(row), financial_totals(row)

    story = [p('Convention de rattrapage',title),
             p(plain(row['kind'])+' - Nouvelle présentation à l’examen',body),
             p('Référence '+ref+' - Établie le '+date_label(row.get('document_date') or row.get('created_at','')[:10]),small),Spacer(1,6)]
    parties = [
        [p('<b>L’organisme de formation</b>',small),p('<b>Le stagiaire</b>',small)],
        [p('<b>Intégrale Academy</b><br/>Intégrale Sécurité Formations<br/>54 chemin du Carreou<br/>83480 PUGET SUR ARGENS<br/>SIRET : 840 899 884 00026<br/>Déclaration d’activité : 93830600283',small),
         p('<b>'+plain(full_name)+'</b><br/>'+plain(person.get('address'))+'<br/>'+plain(person.get('zip_code','')+' '+person.get('city',''))+'<br/>'+plain(person.get('email'))+'<br/>'+plain(person.get('phone'))+('<br/>Né(e) le '+date_label(person['birth_date']) if person.get('birth_date') else ''),small)]]
    table=Table(parties,colWidths=[249,250]);table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),pale),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
    story += [table,p('1. Parcours initial et examen non validé',heading),
              p('<b>Formation / session d’origine :</b> '+plain(row.get('source_name') or row['kind']))]
    if row.get('source_date_start') and row.get('source_date_end'):
        story.append(p('<b>Période de formation initiale :</b> du '+date_label(row['source_date_start'])+' au '+date_label(row['source_date_end'])))
    if row.get('failed_exam_date'):
        story.append(p('Lors de sa présentation à l’examen <b>'+plain(row['kind'])+'</b> du <b>'+date_label(row['failed_exam_date'])+'</b>, le stagiaire n’a pas obtenu la validation de l’examen. Les parties conviennent d’organiser le rattrapage décrit ci-dessous.'))
    else:
        story.append(p('La date de l’examen non réussi doit être complétée avant l’envoi en signature.'))
    if row.get('failed_exam_details'):
        story.append(p('<b>Épreuves ou compétences à retravailler :</b><br/>'+plain(row['failed_exam_details'])))
    story += [p('2. Nouvelle présentation à l’examen',heading),
              p('<b>Session d’accueil :</b> '+plain(row['target_name'])+'<br/><b>Examen :</b> '+date_label(row['exam_date'])+(' à '+plain(row['exam_time']) if row['exam_time'] else ' - horaire communiqué par l’équipe')+'<br/><b>Lieu :</b> '+plain(row['location'])),
              p('L’objet de cette convention est de préciser les modalités de cette nouvelle présentation et les prestations complémentaires acceptées par le stagiaire.'),
              p('3. Accompagnement et journées de préparation',heading)]
    if row['days']:
        story.append(p('Objectif : consolider les acquis, retravailler les points non validés et préparer le stagiaire aux épreuves à repasser. <b>'+str(len(row['days']))+' journée(s) de préparation</b> sont prévues :'))
        schedule=[[p('<b>Date</b>',small),p('<b>Horaires</b>',small),p('<b>Programme / module</b>',small)]]
        schedule += [[p(date_label(d['date']),small),p(d['start']+' - '+d['end'],small),p(plain(d['topic']),small)] for d in row['days']]
        table=Table(schedule,colWidths=[78,90,331],repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),pale),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),6),('LINEBELOW',(0,0),(-1,0),.6,gold)]))
        story.append(table)
    else:
        story.append(p('Aucune journée de cours supplémentaire n’est prévue. La prestation porte uniquement sur la nouvelle présentation à l’examen indiquée ci-dessus.'))
    if row.get('notes'):
        story += [p('Précisions d’organisation',heading),p(plain(row['notes']))]

    story += [PageBreak(),p('Conditions financières',title),p(plain(full_name)+' - '+plain(row['kind'])+' - Examen du '+date_label(row['exam_date']),small),p('4. Tarifs, remises et prestations offertes',heading)]
    cells=[[p('<b>Prestation</b>',small),p('<b>Nb</b>',small),p('<b>Prix unitaire de référence TTC</b>',small),p('<b>Prix unitaire retenu TTC</b>',small),p('<b>Remise accordée</b>',small),p('<b>Total TTC</b>',small)]]
    for item in items:
        reference=money(item['reference_unit_cents']) if item['reference_unit_cents'] is not None else 'Non précisé'
        reduction='Offert' if item['offered'] else money(item['discount_cents'])+'<br/>('+item['discount_percent'].rstrip('0').rstrip('.').replace('.',',')+' %)' if item['discount_cents'] else '-'
        cells.append([p(plain(item['label']),small),p(str(item['quantity']),small),p(reference,small),p(money(item['unit_cents']),small),p(reduction,small),p('<b>'+money(item['total_cents'])+'</b>',small)])
    table=Table(cells,colWidths=[165,28,80,80,76,70],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),pale),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,0),.7,gold),('LINEBELOW',(0,-1),(-1,-1),.5,colors.HexColor('#D5DFE9'))]))
    story += [table,Spacer(1,10)]
    breakdown=[[p('Montant avant réductions',small),p(money(totals['gross_cents']),small)]]
    if totals['discount_cents']:
        breakdown.append([p('Remises commerciales accordées',small),p('- '+money(totals['discount_cents']),small)])
    if totals['offered_cents']:
        breakdown.append([p('Prestations offertes',small),p('- '+money(totals['offered_cents']),small)])
    breakdown.append([p('<b>Total TTC à régler</b>'),p(money(row['total_cents']),total_style)])
    table=Table(breakdown,colWidths=[349,150]);table.setStyle(TableStyle([('BACKGROUND',(0,-1),(-1,-1),green),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),('LEFTPADDING',(0,0),(-1,-1),12)]))
    story += [table,Spacer(1,7)]
    if totals['discount_cents']:
        story.append(p('Les remises ci-dessus sont calculées par rapport aux tarifs de référence de la convention de formation. Elles sont déjà déduites du total à régler ; aucune nouvelle déduction ne sera appliquée lors de la facturation.',small))
    if row.get('price_reference',{}).get('note'):
        story.append(p(plain(row['price_reference']['note']),small))
    story += [p('5. Règlement et confirmation du rattrapage',heading),
              p('Après signature, le stagiaire reçoit par e-mail sa convention signée, la facture Qonto et le lien de paiement par carte bancaire. Le règlement intégral du montant indiqué ci-dessus confirme sa participation à la session d’accueil.' if row['total_cents'] else 'Les prestations sont intégralement offertes. Aucune facture ni demande de paiement n’est émise. La participation à la session d’accueil est confirmée dès la signature de la convention.'),
              p('6. Organisation, suivi et convention initiale',heading),
              p('Le stagiaire respecte les dates et horaires convenus ainsi que les consignes et le matériel à prévoir communiqués par l’équipe. Le programme des journées figure dans cette convention. Le calendrier, les documents signés et le suivi sont disponibles dans son espace stagiaire.'),
              p('Cette convention complète la convention de formation initiale pour les seules prestations de rattrapage décrites ici. Les autres dispositions de la convention initiale restent applicables.',small)]
    signature_field={}
    class SignatureBox(Flowable):
        def __init__(self):
            super().__init__();self.width,self.height=200,60
        def draw(self):
            x,y=self.canv.absolutePosition(0,0)
            signature_field.update(page=self.canv.getPageNumber(),x=round(x),y=round(A4[1]-y-60),width=200,height=60)
            self.canv.setStrokeColor(colors.HexColor('#C9D6E5'));self.canv.roundRect(0,0,200,60,6,stroke=1,fill=0)
    signature=Table([[[p('Acceptation du stagiaire',heading),p('Je confirme les informations sur l’examen non réussi, les dates de préparation, les prestations, les remises et le montant à régler. Signature électronique avec vérification par SMS.',small)],SignatureBox()]],colWidths=[285,214])
    signature.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(0,0),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]))
    story += [Spacer(1,8),signature]
    frame = retake_page_frame(font, "CONVENTION", ref)
    temporary=str(destination)+'.tmp'
    SimpleDocTemplate(temporary,pagesize=A4,rightMargin=48,leftMargin=48,topMargin=118,bottomMargin=82,
                      title='Convention de rattrapage - '+full_name,author='Intégrale Academy').build(story,onFirstPage=frame,onLaterPages=frame)
    Path(temporary).replace(destination)
    return signature_field


def exam_appointment(row):
    date = date_label(row["exam_date"])
    return date + " à " + row["exam_time"] if row.get("exam_time") else date


def build_convocation(row):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from academy_convocations import family
    from academy_convocations.drawing import PALETTES, register_fonts, standalone_panel
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    register_fonts()
    group = family(row["kind"])
    accent, tint, ink, _ = PALETTES[group]
    font = "Bar"
    navy, muted = colors.HexColor(ink), colors.HexColor("#506477")
    body = ParagraphStyle("ConvocationBody", fontName=font, fontSize=10.5, leading=15, textColor=navy)
    title = ParagraphStyle("ConvocationTitle", parent=body, fontName="Cond", fontSize=25, leading=31)
    label = ParagraphStyle("ConvocationLabel", parent=body, fontSize=9, textColor=muted)
    strong = ParagraphStyle("ConvocationValue", parent=body, fontName="BarB")
    heading = ParagraphStyle("ConvocationHeading", parent=strong, textColor=colors.HexColor(accent), fontSize=12, leading=16,
                             spaceBefore=9, spaceAfter=4, keepWithNext=True)

    def line(value, style=body):
        return Paragraph(escape(str(value or "")).replace("\n", "<br/>"), style)

    person = row["person"]
    full_name = person["first_name"] + " " + person["last_name"].upper()
    details = [
        ("Candidat", full_name), ("Votre rendez-vous", row["kind"] + " · " + exam_appointment(row)),
        ("Lieu de l’examen", row["location"]), ("Session d’accueil", row["target_name"]),
    ]
    panel = Table([[line(key, label), line(value, strong)] for key, value in details],
                  colWidths=[119, 363], hAlign="LEFT")
    panel.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor(tint), colors.white]),
        ("LINEBELOW", (0, 0), (-1, -1), .5, colors.HexColor("#D5DFE5")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor(accent)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    artwork = Path(__file__).parent / "static/images/convocations/certification.png"
    banner = Table([[[line("Session de rattrapage", heading), line("Convocation à l’examen", title)],
                     Image(str(artwork), width=92, height=48)]], colWidths=[380, 102], hAlign="LEFT")
    banner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story = [banner, Spacer(1, 15),
             line("Bonjour " + person["first_name"] + ","),
             line("Conformément à votre convention de rattrapage, vous êtes attendu(e) à la nouvelle session ci-dessous."),
             Spacer(1, 8), panel]
    if not row.get("exam_time"):
        story.extend([line("L’horaire reste à préciser. Contactez l’accueil avant le jour de l’examen."), Spacer(1, 8)])
    if row.get("source_name") or row.get("failed_exam_date") or row.get("failed_exam_details"):
        story.append(line("Votre parcours", heading))
    if row.get("source_name"):
        period = (" · du " + date_label(row["source_date_start"]) + " au " + date_label(row["source_date_end"])
                  if row.get("source_date_start") and row.get("source_date_end") else "")
        story.append(line("Session initiale · " + row["source_name"] + period))
    if row.get("failed_exam_date"):
        story.append(line("Examen non validé · " + row["kind"] + " du " + date_label(row["failed_exam_date"])))
    if row.get("failed_exam_details"):
        story.append(line("Épreuves ou compétences à retravailler · " + row["failed_exam_details"]))
    story.append(line("Votre préparation", heading))
    if row.get("days"):
        cells = [[line(text, strong) for text in ("Date", "Horaires", "Programme")]]
        for day in row["days"]:
            cells.append([line(date_label(day["date"])), line(day["start"] + " – " + day["end"]), line(day["topic"])])
        schedule = Table(cells, colWidths=[87, 100, 295], repeatRows=1, hAlign="LEFT")
        schedule.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5FA")),
            ("LINEBELOW", (0, 0), (-1, -1), .35, colors.HexColor("#D5DFE9")),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        story.append(schedule)
    else:
        story.append(line("Votre convention prévoit uniquement la présentation à l’examen."))
    story.append(line("Le jour de l’examen", heading))
    story.append(line("Présentez-vous avec cette convocation et une pièce d’identité."))
    if row.get("notes"):
        story.append(line(row["notes"]))
    story.extend([Spacer(1, 7), line("En cas de question ou d’empêchement, contactez l’équipe au "
                  "04 22 47 07 68 ou à ecole@integraleacademy.com."), Spacer(1, 6), line("L’équipe Intégrale Academy", strong)])
    from academy_convocations.agenda import Agenda, iso
    from academy_convocations.drawing import Book
    from academy_convocations.source import puget_model
    from reportlab.platypus import Flowable, KeepTogether
    pen = puget_model().blocks[1][-1].pictures[0]
    autograph = Image(BytesIO(pen.data), width=77, height=77 * pen.height / pen.width, hAlign="LEFT")
    story.append(KeepTogether([line("Clément VAILLANT", strong), line("Directeur général Intégrale Academy", label),
                                Spacer(1, 3), autograph]))
    if row.get("kind") == "DESP" and row.get("location") == desp_paris_venue.FULL_ADDRESS:
        story.extend([PageBreak(), line("Venir au centre de formation", title),
                      line(desp_paris_venue.FULL_ADDRESS, strong),
                      Spacer(1, 12), Image(str(desp_paris_venue.MAP_PATH), width=390, height=207),
                      Spacer(1, 12), line(desp_paris_venue.PRIMARY_METRO, heading),
                      line(desp_paris_venue.WALK), line("Autres accès", heading),
                      line(desp_paris_venue.OTHER_METROS), line(desp_paris_venue.SENTIER),
                      line("Bus " + desp_paris_venue.BUS), line(desp_paris_venue.PARKING),
                      Spacer(1, 8), Paragraph('<link href="' + escape(desp_paris_venue.DIRECTIONS_URL)
                                             + '"><u>Ouvrir l’itinéraire dans Google Maps</u></link>', body)])
    story.append(Paragraph(f'<link href="{PORTAL_URL}" color="{accent}"><u>{PORTAL_URL}</u></link>', label))
    dates = sorted({iso(item.get("date")) for item in row.get("days", [])} - {""})
    events = [dict(kind="centre", label="Journées de préparation", days=dates)] if dates else []
    exam_day = iso(row.get("exam_date"))
    if exam_day:
        events.append(dict(kind="exam", label="Examen de rattrapage", days=[exam_day], time=row.get("exam_time") or ""))
    agenda = Agenda(events)

    class CalendarSheet(Flowable):
        def __init__(self, months):
            super().__init__()
            self.months, self.height = months, 460

        def draw(self):
            self.canv.saveState()
            self.canv.resetTransforms()
            sheet = Book(puget_model(), None, group, canvas=self.canv)
            sheet.txt(216, 16, "CALENDRIER MENSUEL", "BarB", 9, sheet.accent)
            agenda.body(sheet, self.months)
            self.canv.restoreState()

    for months in agenda.groups:
        story.extend([PageBreak(), CalendarSheet(months)])
    out = BytesIO()
    def frame(canvas, doc):
        standout = "CONVOCATION " + row["id"][:12].upper()
        standalone_panel(canvas, group, Path(__file__).parent / 'static/logo-integrale.png',
                         [], "VOTRE RATTRAPAGE", standout)
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#DECEC1"))
        canvas.line(33,53,doc.pagesize[0]-33,53)
        canvas.setFont("Bar",9);canvas.setFillColor(navy)
        canvas.drawString(33,32,"Intégrale Academy - 04 22 47 07 68 - ecole@integraleacademy.com")
        canvas.drawRightString(doc.pagesize[0]-33,32,"Page "+str(doc.page))
        canvas.restoreState()
    SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=210, rightMargin=31, topMargin=20, bottomMargin=65,
                      title="Convocation à l’examen de rattrapage - "+full_name, author="Intégrale Academy",
                      invariant=1).build(story, onFirstPage=frame, onLaterPages=frame)
    return out.getvalue()


def email_content(host, row, kind, link):
    if kind == 'convocation':
        title = "Convocation à l’examen de rattrapage"
        person = row["person"]["first_name"]
        appointment = row["kind"] + " · " + exam_appointment(row)
        intro = "Vous trouverez en pièce jointe votre convocation nominative à l’examen de rattrapage."
        contact = "En cas d’empêchement, contactez l’équipe au 04 22 47 07 68."
        confirmed = "Votre règlement est confirmé." if row["total_cents"] else "Votre inscription au rattrapage est confirmée."
        lines = ["Bonjour " + person + ",", confirmed + " " + intro, appointment, row["location"]]
        if row.get("failed_exam_date"):
            lines.append("Cette nouvelle présentation fait suite à l’examen du " + date_label(row["failed_exam_date"]) + ".")
        if row.get("days"):
            lines.append("Vos journées de préparation sont détaillées dans la convocation jointe.")
        if not row.get("exam_time"):
            lines.append("Contactez l’accueil pour connaître l’horaire de l’examen.")
        lines.append(contact)
        content = "".join("<p>" + escape(line).replace("\n", "<br/>") + "</p>" for line in lines)
        if link:
            content += '<p><a href="' + escape(link, quote=True) + '">Consulter mon espace stagiaire</a></p>'
        return (title + " · " + appointment,
                host.render_academy_email(content, title=title, eyebrow="VOTRE EXAMEN", signature="team"),
                "\n\n".join(lines + ([link] if link else []) + ["L’équipe Intégrale Academy"]))
    name = escape(row['person']['first_name'])
    schedule = '<p><strong>Examen '+escape(row['kind'])+' :</strong> '+date_label(row['exam_date'])+(' à '+escape(row['exam_time']) if row['exam_time'] else '')+'<br/><strong>Session :</strong> '+escape(row['target_name'])+'<br/><strong>Lieu :</strong> '+escape(row['location'])+'</p>'
    if row.get('failed_exam_date'):
        schedule += '<p><strong>Examen non réussi :</strong> '+date_label(row['failed_exam_date'])+'</p>'
    if row['days']:
        schedule += '<h3>Vos journées de préparation</h3><ul>'+''.join('<li>'+date_label(d['date'])+' · '+d['start']+' - '+d['end']+'<br/>'+escape(d['topic'])+'</li>' for d in row['days'])+'</ul>'
    else:
        schedule += '<p>Aucune journée de cours supplémentaire n’est prévue.</p>'
    if row.get('notes'):
        schedule += '<p><strong>Précisions :</strong><br/>'+escape(row['notes']).replace('\n','<br/>')+'</p>'
    items,totals=line_items(row),financial_totals(row)
    price_rows=[]
    for item in items:
        detail=''
        if item['discount_cents']:
            detail='<br/><span style="font-size:12px;color:#176344">Tarif unitaire de référence : '+money(item['reference_unit_cents'])+' TTC.<br/>'+discount_label(item)+' sur cette prestation, déjà déduite.</span>'
        price_rows.append('<tr><td style="padding:12px">'+escape(item['label'])+detail+'</td><td style="padding:12px;text-align:right">'+('Offert' if item['offered'] else money(item['total_cents']))+'</td></tr>')
    if totals['discount_cents']:
        price_rows.append('<tr><td style="padding:12px;color:#176344">Remises commerciales accordées</td><td style="padding:12px;text-align:right;color:#176344">'+money(totals['discount_cents'])+'</td></tr>')
    prices='<table role="presentation" width="100%" style="border-collapse:collapse;background:#f1f5fb">'+''.join(price_rows)+'<tr><td style="padding:12px"><strong>Total TTC à régler</strong></td><td style="padding:12px;text-align:right"><strong>'+money(row['total_cents'])+'</strong></td></tr></table>'
    if kind == 'signature':
        title, intro, cta = 'Votre convention de rattrapage', 'Votre rattrapage est préparé. Consultez et signez votre convention ; un code vous sera envoyé par SMS pour confirmer votre signature.', 'Signer ma convention'
    elif kind == 'confirmed':
        title, intro, cta = 'Votre rattrapage est confirmé', 'Votre règlement est confirmé. Vous êtes attendu(e) aux dates indiquées ci-dessous.', 'Consulter mon espace stagiaire'
    elif row['total_cents']:
        title, intro, cta = 'Votre rattrapage · convention et facture', 'Votre convention est signée. Retrouvez en pièces jointes la convention signée et votre facture Qonto. Le règlement confirme votre participation.', 'Régler par carte bancaire'
    else:
        title, intro, cta = 'Votre rattrapage est confirmé', 'Votre convention est signée et jointe à ce message. Votre rattrapage est intégralement offert : aucun règlement n’est nécessaire.', 'Consulter mon espace stagiaire'
    button = '<p style="text-align:center;margin:28px 0"><a href="'+escape(link,quote=True)+'" style="display:inline-block;padding:15px 24px;background:#285ac8;color:white;border-radius:10px;text-decoration:none">'+cta+'</a></p>' if link else ''
    content = '<p>Bonjour '+name+',</p><p>'+intro+'</p>'+schedule+prices+button
    text = title+'\nBonjour '+row['person']['first_name']+',\n'+intro+'\nExamen : '+row['kind']+' · '+date_label(row['exam_date'])+' '+row['exam_time']+'\nSession : '+row['target_name']+'\nLieu : '+row['location']+'\n'
    text += '\n'.join(date_label(d['date'])+' · '+d['start']+' - '+d['end']+' · '+d['topic'] for d in row['days']) if row['days'] else 'Aucune journée de cours supplémentaire.'
    text += '\n'+(row.get('notes') or '')+'\n'+'\n'.join(i['label']+' : '+('Offert' if i['offered'] else money(i['total_cents'])) for i in items)
    if row.get('failed_exam_date'):
        text+='\nExamen non réussi : '+date_label(row['failed_exam_date'])
    text+='\n'+'\n'.join(i['label']+' : tarif de référence '+money(i['reference_unit_cents'])+' TTC ; '+discount_label(i)+', déjà déduite.' for i in items if i['discount_cents'])
    if totals['discount_cents']:
        text+='\nRemises commerciales accordées : '+money(totals['discount_cents'])
    text+='\nTotal TTC : '+money(row['total_cents'])+'\n'+link+'\nL’équipe Intégrale Academy'
    return title+' - Intégrale Academy',host.render_academy_email(content,title=title,eyebrow='VOTRE RATTRAPAGE',signature='team'),text
