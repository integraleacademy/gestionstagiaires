"""Fictional Digiforma-style exports, including Word's borderless striped rows."""
import io
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle


def attendance_pdf(*, trainee_name='ALICE MARTIN', complete=True, completion_rate=100,
                   effective_duration='62 heures', completed_paths=8, completed_evaluations=8,
                   striped=True, split_course=False, long_label=False, connection_count=3):
    output=io.BytesIO()
    pdf=canvas.Canvas(output,pagesize=(595,842))
    pdf.setTitle('Attestation source fictive')
    pdf.setFont('Helvetica',10)
    lines=["Attestation d'assiduité", f'atteste que : {trainee_name}',
           'a suivi la formation : TFP APS SEPTEMBRE 2026',
           'Dates de la formation : du 23 juillet 2026 au 3 septembre 2026.',
           'Lieu de la formation : à distance.', 'Durée de la formation : 62 heures',
           "Type d'action de formation : Action de formation"]
    if complete:
        lines += ["Suivi détaillé de l'assiduité e-learning",
                  f'Durée effectivement suivie sur la plateforme : {effective_duration}',
                  f'taux de réalisation de {completion_rate} %',
                  "Durée totale de connexion à l'extranet : 62h",
                  "Nombre de jour(s) d'accès à l'extranet : 8"]
    for i,line in enumerate(lines): pdf.drawString(40,790-i*24,line)
    if not complete:
        pdf.save();return output.getvalue()
    pdf.showPage()
    style=ParagraphStyle('fixture',fontName='Helvetica',fontSize=7.5,leading=9)
    headers=['N°','Type','Nom','Durée prévue','Première connexion','Dernière connexion','Avancée pédagogique','Résultats']
    widths=[14,42,142,56,66,66,60,69]

    def draw_table(rows, top, with_header=True):
        data=([headers] if with_header else [])+rows
        formatted=[[Paragraph(str(v).replace('\n','<br/>'),style) for v in row] for row in data]
        table=Table(formatted,colWidths=widths)
        commands=[('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),2),
                  ('RIGHTPADDING',(0,0),(-1,-1),2),('TOPPADDING',(0,0),(-1,-1),3),
                  ('BOTTOMPADDING',(0,0),(-1,-1),3),('BOX',(0,0),(-1,-1),.5,(0,0,0))]
        if striped:
            for r in range(len(data)):
                if r%2==0 or r==len(data)-1:
                    for c in range(8): commands.append(('BACKGROUND',(c,r),(c,r),(.92,.94,.95)))
        else: commands.append(('GRID',(0,0),(-1,-1),.5,(0,0,0)))
        for r,row in enumerate(data):
            if row[0]=='Total': commands.append(('SPAN',(0,r),(2,r)))
        table.setStyle(TableStyle(commands));_,h=table.wrap(515,700);table.drawOn(pdf,40,top-h)

    for n in range(1,9):
        pdf.setFont('Helvetica',10)
        pdf.drawString(40,790,f'Parcours {n} - Prévention et sécurité {n}')
        for i,line in enumerate(['Durée totale de la séquence','7 heures et 45 minutes',
                                 "Durée réalisée par l'apprenant selon sa progression et la durée des activités",'7 heures et 45 minutes',
                                 'Statut','Terminé' if n<=completed_paths else 'En cours',
                                 'Progression','100 %' if n<=completed_paths else '0 %']):
            pdf.drawString(40,764-i*14,line)
        name=f'P{n}M1 Prévention des risques'
        if long_label and n==1: name+=' - '+('Description détaillée et consignes à respecter. '*20)+'FIN-MODULE-LONG'
        rows=[['1','SCORM',name,'7 heures','07/09/2026\n08h30m01s','08/09/2026\n17h15m02s','100 %','SCORE-SECRET-83'],
              ['2','Évaluation',f'Evaluation Parcours {n}','45 minutes','07/09/2026\n10h30m03s','08/09/2026\n17h35m04s',
               '100 %' if n<=completed_evaluations else '0 %','100% 1 passage' if n<=completed_evaluations else '0% 0 passage'],
              ['Total','','','7 heures et 45 minutes','07/09/2026\n08h30m01s','08/09/2026\n17h35m04s','100 %','SCORE-TOTAL']]
        if split_course and n==1:
            draw_table(rows[:1],620);pdf.showPage();draw_table(rows[1:],790,with_header=False)
        else: draw_table(rows,620)
        pdf.showPage()
    pdf.setFont('Helvetica',10)
    pdf.drawString(40,790,"Relevé de connexions à l'extranet")
    pdf.drawString(40,770,'Adresse email utilisée : alice.martin@example.test')
    log_headers=['Date de connexion','Date de déconnexion','Durée de connexion','IP']
    for start in range(0,connection_count,32):
        rows=[log_headers]
        for i in range(start,min(start+32,connection_count)):
            rows.append([f'Le 07/09/2026 à 08h{i%60:02}m01s',f'Le 07/09/2026 à 09h{i%60:02}m02s',
                         '1 heure et 1 seconde',f'192.0.2.{i%250+1}'])
        if start+32>=connection_count: rows.append(['Total','62 heures','',''])
        table=Table(rows,colWidths=[165,165,105,80]);table.setStyle(TableStyle([
            ('GRID',(0,0),(-1,-1),.5,(0,0,0)),('FONTNAME',(0,0),(-1,-1),'Helvetica'),('FONTSIZE',(0,0),(-1,-1),8)]))
        _,h=table.wrap(515,700);table.drawOn(pdf,40,740-h)
        if start+32<connection_count: pdf.showPage()
    pdf.setFont('Helvetica',10);pdf.drawString(40,70,'Fait à Puget-sur-Argens, le 31 août 2026')
    pdf.save();return output.getvalue()
