"""Print-friendly formative evaluation with clearly separated question blocks."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Flowable, KeepTogether, PageBreak

NAVY = colors.HexColor('#182f49')
BLUE = colors.HexColor('#285d83')
GOLD = colors.HexColor('#c5a15a')
MUTED = colors.HexColor('#607389')
LINE = colors.HexColor('#dce5ee')


def fonts():
    for root in (Path('/usr/share/fonts/truetype/dejavu'), Path('/usr/share/fonts/dejavu')):
        regular, bold = root/'DejaVuSans.ttf', root/'DejaVuSans-Bold.ttf'
        if regular.exists() and bold.exists():
            if 'UVSans' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('UVSans', str(regular)))
                pdfmetrics.registerFont(TTFont('UVSansBold', str(bold)))
            return 'UVSans', 'UVSansBold'
    return 'Helvetica', 'Helvetica-Bold'


class Question(Flowable):
    def __init__(self, index, question, normal, bold, small, selected=None, correction=False):
        super().__init__()
        self.index, self.question, self.selected, self.correction = index, question, selected, correction
        self.normal, self.bold, self.small = normal, bold, small

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.prompt = Paragraph(escape(self.question['prompt']), self.bold)
        self.prompt_h = self.prompt.wrap(availWidth-42, 1000)[1]
        self.options = []
        for option in self.question['options']:
            text = option['text']
            if self.correction and option['id'] == self.question['answer']:
                text += '  •  Bonne réponse'
            if self.selected == option['id']:
                text += '  •  Votre réponse'
            p = Paragraph(escape(text), self.normal)
            self.options.append((option, p, max(17, p.wrap(availWidth-64, 1000)[1]+4)))
        self.height = 18+self.prompt_h+10+sum(x[2] for x in self.options)+12
        self.explanation = None
        if self.correction:
            text = self.question['explanation']
            if self.selected == '':
                text = 'Sans réponse (temps écoulé). '+text
            self.explanation = Paragraph(escape(text), self.small)
            self.height += self.explanation.wrap(availWidth-30,1000)[1]+16
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setStrokeColor(LINE); c.setFillColor(colors.white)
        c.roundRect(0, 0, self.width, self.height, 8, fill=1, stroke=1)
        c.setFillColor(BLUE); c.roundRect(12,self.height-34,23,23,6,fill=1,stroke=0)
        c.setFillColor(colors.white); c.setFont(self.bold.fontName,9)
        c.drawCentredString(23.5,self.height-26,f'{self.index:02}.')
        y=self.height-15-self.prompt_h
        self.prompt.drawOn(c,42,y)
        y-=12
        for option,p,h in self.options:
            y-=h
            c.setStrokeColor(MUTED); c.setLineWidth(.7)
            c.roundRect(18,y+h-14,8,8,1.5,fill=0,stroke=1)
            if self.selected == option['id']:
                c.setFillColor(BLUE); c.roundRect(19.5,y+h-12.5,5,5,1,fill=1,stroke=0)
            p.drawOn(c,36,y+h-4-p.height)
        if self.explanation:
            y-=10
            c.setStrokeColor(LINE);c.line(15,y,self.width-15,y)
            self.explanation.drawOn(c,15,y-8-self.explanation.height)


def build(training, trainee, course, row, result=None, correction=False, *, title, notice):
    normal_font, bold_font = fonts()
    output = BytesIO()
    doc = SimpleDocTemplate(output,pagesize=(210*mm,297*mm),rightMargin=17*mm,leftMargin=17*mm,
                            topMargin=41*mm,bottomMargin=20*mm,title=title,author='Intégrale Academy')
    normal = ParagraphStyle('uvbody',fontName=normal_font,fontSize=9,leading=13,textColor=NAVY)
    bold = ParagraphStyle('uvbold',parent=normal,fontName=bold_font,fontSize=10,leading=14)
    small = ParagraphStyle('uvsmall',parent=normal,fontSize=8,leading=12,textColor=MUTED)
    def p(text,style=normal): return Paragraph(escape(str(text)),style)
    name=' '.join(str(trainee.get(k) or '') for k in ('first_name','last_name')).strip()
    mode='Réponses et correction' if result else 'Corrigé formateur' if correction else 'Questionnaire vierge'
    topic=p(row['title'],ParagraphStyle('uvtopic',parent=bold,fontSize=13,leading=17,spaceAfter=12))
    info=[topic,p(f'Stagiaire : {name}   •   Dossier : {trainee.get("id", "")}'),Spacer(1,5),
          p(f'Session : {training.get("name", "")}'),Spacer(1,10)]
    if result:
        info.extend([p(f'Score : {result["score"]}/20   •   Remis le {result["submitted_at"]}',bold),Spacer(1,8)])
    else:
        info.extend([p('Date : ____________________    Formateur : ____________________'),Spacer(1,6),
                     p('Signature du stagiaire : ______________________________________'),Spacer(1,10)])
    info += [p('20 questions   •   1 seule réponse   •   1 point par bonne réponse',bold),Spacer(1,5),
             p(notice,small),Spacer(1,14)]
    story=[KeepTogether(info)]
    for i,q in enumerate(row['questions'],1):
        if not (correction or result) and i > 1 and (i-1) % 4 == 0:
            story.append(PageBreak())
        selected=result.get('answers',{}).get(q['id']) if result else None
        story += [Question(i,q,normal,bold,small,selected,correction or bool(result)),Spacer(1,10)]
    def page(c,d):
        w,h=d.pagesize
        c.setFillColor(NAVY);c.rect(0,h-9*mm,w,9*mm,fill=1,stroke=0)
        c.setFont(bold_font,8);c.setFillColor(colors.white)
        c.drawString(17*mm,h-6*mm,'INTÉGRALE ACADEMY')
        c.drawRightString(w-17*mm,h-6*mm,f'{course.upper()}  /  UV {row["number"]:02}')
        c.drawImage(str(Path(__file__).with_name('static')/'logo-integrale.png'),
                    17*mm,h-33*mm,width=21*mm,height=21*mm,preserveAspectRatio=True,mask='auto')
        c.setFillColor(NAVY);c.setFont(bold_font,19)
        c.drawString(44*mm,h-21*mm,"Questionnaire de fin d'UV")
        c.setFont(normal_font,12);c.setFillColor(BLUE)
        c.drawString(44*mm,h-28*mm,'Evaluation formative')
        c.setFont(normal_font,8);c.setFillColor(MUTED)
        c.drawRightString(w-17*mm,h-28*mm,mode)
        c.setStrokeColor(GOLD);c.setLineWidth(1.4);c.line(17*mm,h-35*mm,w-17*mm,h-35*mm)
        c.setStrokeColor(LINE);c.setLineWidth(.6);c.line(17*mm,16*mm,w-17*mm,16*mm)
        c.setFillColor(MUTED);c.setFont(normal_font,7)
        c.drawString(17*mm,11*mm,f'{course.upper()} · UV {row["number"]:02} · Evaluation formative')
        c.drawRightString(w-17*mm,11*mm,f'Page {d.page}')
    doc.build(story,onFirstPage=page,onLaterPages=page)
    output.seek(0)
    return output
