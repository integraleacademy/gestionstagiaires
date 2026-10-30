"""Compact convention and the shared Academy email presentation."""
from html import escape
from pathlib import Path

from exam_retakes import date_label, line_items, money


def build_convention(row, destination):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable
    regular = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    bold = regular.with_name('DejaVuSans-Bold.ttf')
    if regular.is_file():
        if 'RetakeSans' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('RetakeSans', str(regular)))
            pdfmetrics.registerFont(TTFont('RetakeSans-Bold', str(bold)))
            pdfmetrics.registerFontFamily('RetakeSans', normal='RetakeSans', bold='RetakeSans-Bold')
        font = 'RetakeSans'
    else:
        font = 'Helvetica'
    navy, blue = colors.HexColor('#102c5c'), colors.HexColor('#285ac8')
    body = ParagraphStyle('RetakeBody', fontName=font, fontSize=9, leading=14, textColor=navy, spaceAfter=7)
    title = ParagraphStyle('RetakeTitle', parent=body, fontName=font+'-Bold', fontSize=23, leading=29, spaceAfter=12)
    small = ParagraphStyle('RetakeSmall', parent=body, fontSize=8, leading=12)
    heading = ParagraphStyle('RetakeHeading', parent=body, fontName=font+'-Bold', fontSize=12, leading=17, spaceBefore=12, spaceAfter=9)
    p = lambda text, style=body: Paragraph(text, style)
    person = row['person']
    full_name = person['first_name']+' '+person['last_name']
    story = [p('INTÉGRALE ACADEMY', heading), p('Convention de rattrapage', title),
             p(escape(row['kind'])+' · Référence '+row['id'][:12].upper(), small), Spacer(1, 10)]
    parties = [
        [p('<b>L’organisme de formation</b>', small), p('<b>Le stagiaire</b>', small)],
        [p('Intégrale Sécurité Formations - Intégrale Academy<br/>54 chemin du Carreou, 83480 Puget-sur-Argens<br/>SIRET : 840 899 884 00026<br/>Déclaration d’activité : 93830600283', small),
         p(escape(full_name)+'<br/>'+escape(person.get('address',''))+'<br/>'+escape(person.get('zip_code','')+' '+person.get('city',''))+'<br/>'+escape(person.get('email',''))+'<br/>'+escape(person.get('phone','')), small)]]
    table = Table(parties, colWidths=[250, 249])
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f1f5fb')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story += [table, p('1. Objet et organisation', heading),
              p('À la suite de la formation '+escape(row.get('source_name') or row['kind'])+', les parties conviennent d’une nouvelle présentation à l’examen et, le cas échéant, de journées de préparation.'),
              p('<b>Session d’accueil :</b> '+escape(row['target_name'])+'<br/><b>Examen :</b> '+date_label(row['exam_date'])+(' à '+escape(row['exam_time']) if row['exam_time'] else ' - horaire communiqué par l’équipe')+'<br/><b>Lieu :</b> '+escape(row['location']))]
    story.append(p('2. Journées de préparation', heading))
    if row['days']:
        for day in row['days']:
            story.append(p('<b>'+date_label(day['date'])+' · '+day['start']+' - '+day['end']+'</b><br/>'+escape(day['topic'])))
    else:
        story.append(p('Aucune journée de cours supplémentaire. Le rattrapage porte uniquement sur la nouvelle présentation à l’examen.'))
    story.append(p('3. Conditions financières', heading))
    cells = [[p('<b>Prestation</b>', small),p('<b>Quantité</b>',small),p('<b>Tarif TTC</b>',small),p('<b>Total TTC</b>',small)]]
    for item in line_items(row):
        cells.append([p(escape(item['label']),small),p(str(item['quantity']),small),p(money(item['unit_cents']),small),p('Offert' if item['offered'] else money(item['total_cents']),small)])
    cells.append([p('<b>Total à régler</b>'),'', '',p('<b>'+money(row['total_cents'])+'</b>')])
    table = Table(cells, colWidths=[275,55,80,89], repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0ff')),('BACKGROUND',(0,-1),(-1,-1),colors.HexColor('#edf6f2')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,0),0.5,blue)]))
    story.append(table)
    story += [Spacer(1,10),p('Une facture est émise après signature de cette convention. Le règlement intégral confirme le rattrapage dans la session d’accueil.' if row['total_cents'] else 'Les prestations sont intégralement offertes. Aucune facture n’est émise ; le rattrapage est confirmé dès la signature.',small)]
    if row.get('price_reference',{}).get('note'):
        story.append(p(escape(row['price_reference']['note']),small))
    if row.get('notes'):
        story += [p('Précisions convenues',heading),p(escape(row['notes']).replace('\n','<br/>'))]
    story += [p('Les autres dispositions de la convention de formation initiale restent applicables. Cette convention décrit les prestations complémentaires acceptées par les parties.',small)]
    signature_field = {}
    class SignatureBox(Flowable):
        def __init__(self):
            super().__init__()
            self.width, self.height = 200, 60
        def draw(self):
            x, y = self.canv.absolutePosition(0, 0)
            signature_field.update(page=self.canv.getPageNumber(), x=round(x), y=round(A4[1]-y-60), width=200, height=60)
            self.canv.setStrokeColor(colors.HexColor('#d7e1f0'))
            self.canv.roundRect(0,0,200,60,6,stroke=1,fill=0)
    signature = Table([[[p('Acceptation du stagiaire',heading),p('Je confirme les dates, les prestations et les montants indiqués ci-dessus. Signature électronique avec vérification par SMS.',small)],SignatureBox()]], colWidths=[285,214])
    signature.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(0,0),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]))
    story += [Spacer(1,8),signature]
    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor('#d7e1f0')); canvas.line(48,42,547,42)
        canvas.setFont(font,7); canvas.setFillColor(navy)
        canvas.drawString(48,29,'Intégrale Academy · 04 22 47 07 68 · ecole@integraleacademy.com')
        canvas.drawRightString(547,29,str(doc.page))
    temporary = str(destination)+'.tmp'
    SimpleDocTemplate(temporary,pagesize=A4,rightMargin=48,leftMargin=48,topMargin=32,bottomMargin=58,
                      title='Convention de rattrapage - '+full_name,author='Intégrale Academy').build(story,onFirstPage=footer,onLaterPages=footer)
    Path(temporary).replace(destination)
    return signature_field


def email_content(host, row, kind, link):
    name = escape(row['person']['first_name'])
    schedule = '<p><strong>Examen '+escape(row['kind'])+' :</strong> '+date_label(row['exam_date'])+(' à '+escape(row['exam_time']) if row['exam_time'] else '')+'<br/><strong>Session :</strong> '+escape(row['target_name'])+'<br/><strong>Lieu :</strong> '+escape(row['location'])+'</p>'
    if row['days']:
        schedule += '<h3>Vos journées de préparation</h3><ul>'+''.join('<li>'+date_label(d['date'])+' · '+d['start']+' - '+d['end']+'<br/>'+escape(d['topic'])+'</li>' for d in row['days'])+'</ul>'
    else:
        schedule += '<p>Aucune journée de cours supplémentaire n’est prévue.</p>'
    if row.get('notes'):
        schedule += '<p><strong>Précisions :</strong><br/>'+escape(row['notes']).replace('\n','<br/>')+'</p>'
    prices = '<table role="presentation" width="100%" style="border-collapse:collapse;background:#f1f5fb">'+''.join('<tr><td style="padding:12px">'+escape(i['label'])+'</td><td style="padding:12px;text-align:right">'+('Offert' if i['offered'] else money(i['total_cents']))+'</td></tr>' for i in line_items(row))+'<tr><td style="padding:12px"><strong>Total TTC</strong></td><td style="padding:12px;text-align:right"><strong>'+money(row['total_cents'])+'</strong></td></tr></table>'
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
    text += '\n'+(row.get('notes') or '')+'\n'+'\n'.join(i['label']+' : '+('Offert' if i['offered'] else money(i['total_cents'])) for i in line_items(row))+'\nTotal TTC : '+money(row['total_cents'])+'\n'+link+'\nL’équipe Intégrale Academy'
    return title+' - Intégrale Academy',host.render_academy_email(content,title=title,eyebrow='VOTRE RATTRAPAGE',signature='team'),text
