"""Extract the user-owned VTC manual into accessible, versioned learning content.

Usage: python scripts/vtc/extract_manual.py /path/to/manual.pdf
Only build-time dependencies: PyMuPDF and Pillow. No runtime PDF parsing.
"""
from pathlib import Path
import collections, hashlib, io, json, re, sys
import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'elearning_native/vtc'
MEDIA = OUT / 'assets/media/vtc'
MEDIA.mkdir(parents=True, exist_ok=True)
doc = fitz.open(sys.argv[1])

def blocks(page):
    result=[]
    for b in page.get_text('dict')['blocks']:
        if b['type'] != 0: continue
        lines=[''.join(s['text'] for s in line['spans']).strip() for line in b['lines']]
        spans=[s for l in b['lines'] for s in l['spans']]
        result.append({'box':list(b['bbox']), 'text':' '.join(lines), 'lines':lines,
                       'size':max(s['size'] for s in spans),
                       'fonts':list({s['font'] for s in spans})})
    return result

def webp(page, name, clip=None, width=1200):
    area=fitz.Rect(clip) if clip else page.rect
    pix=page.get_pixmap(matrix=fitz.Matrix(width/area.width,width/area.width),clip=area,alpha=False)
    im=Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGB')
    buffer=io.BytesIO(); im.save(buffer,'WEBP',quality=85,method=6)
    payload=buffer.getvalue(); assert len(payload)>100,name
    path=MEDIA/name; temporary=path.with_suffix('.tmp')
    temporary.write_bytes(payload); temporary.replace(path)
    return 'media/vtc/'+name

def title_of(page):
    b=next(x for x in blocks(page) if x['size']>14 and 60<x['box'][1]<120)
    return b['text']

lessons=[]; modules=[]; extras=collections.defaultdict(list)
for i,page in enumerate(doc):
    text=page.get_text()
    m=re.search(r'LEÇON ([A-H]\.\d{2}) • JE COMPRENDS(?! /)',text)
    if not m: continue
    ref=m[1]; first=blocks(page); second=blocks(doc[i+1])
    title=title_of(page)
    tops=sorted([b for b in first if 8.25<b['size']<8.55 and 150<b['box'][1]<290 and 'Bold' in ' '.join(b['fonts'])],key=lambda b:b['box'][0])
    cards=[]
    for top in tops:
        mid=(top['box'][0]+top['box'][2])/2
        nearby=[b for b in first if 9.4<b['size']<9.8 and b['box'][1]>=top['box'][3] and b['box'][1]<top['box'][3]+35 and abs((b['box'][0]+b['box'][2])/2-mid)<55]
        if nearby: cards.append({'label':top['text'],'text':' '.join(b['text'] for b in sorted(nearby,key=lambda b:b['box'][1]))})
    custom={
      'B.03':[('Actif','Les biens et les créances de l’entreprise.'),('Passif','Les capitaux propres et les dettes.'),('Bilan','Une photographie à une date donnée.')],
      'B.06':[('HT vers TTC','Multiplier le montant HT par 1 + le taux de TVA.'),('TTC vers HT','Diviser le montant TTC par 1 + le taux de TVA.'),('TVA','La différence entre TTC et HT.')],
      'C.03':[('Réaction','Le véhicule avance avant le début du freinage.'),('Freinage','Distance parcourue pendant le ralentissement jusqu’à l’arrêt.'),('Arrêt','Réaction et freinage réunis.')],
      'E.04':[('Next to','À côté de.'),('Opposite','En face de.'),('Between','Entre deux repères.')],
      'G.03':[('Capacité','De 4 à 9 places, conducteur compris.'),('Régime ordinaire','Âge, portes, dimensions et puissance à vérifier.'),('Exceptions','Vérifier la catégorie exacte et les dérogations applicables.')],
      'G.08':[('Nouvelle mission justifiée','Exécuter la prestation réservée ou le contrat justifié.'),('Sans nouvelle réservation','Rejoindre la base ou un stationnement autorisé hors chaussée.'),('Dans tous les cas','Respecter les lieux et l’interdiction de maraude.')],
      'H.11':[('Parcours','Préparer et réaliser : 3 points.'),('Conduite','Sécurité, souplesse et code : 10 points.'),('Service','Relation et tourisme : 5 points ; facturation : 2 points.')],
    }
    if len(cards)!=3:
        print('CUSTOM DIAGRAM',ref,len(cards),flush=True)
        cards=[{'label':label,'text':txt} for label,txt in custom.get(ref,[])]
        assert len(cards)==3,(ref,cards)
    paras=[]
    for page_blocks,is_first in [(first,True),(second,False)]:
        for b in page_blocks:
            y=b['box'][1]
            if y<90 or y>=570: continue
            if is_first and y<(max(x['box'][3] for x in tops)+40 if tops else 270): continue
            if b['size']<10: # Keep original short section headings, not diagram labels.
                if b['size']>=9.7 and len(b['text'])>140 and b['box'][0]<70 and b['box'][2]>300:
                    paras.append({'kind':'paragraph','text':b['text']})
                if 'Bold' in ' '.join(b['fonts']) and y>260 and b['size']>=7.8:
                    paras.append({'kind':'heading','text':b['text']})
                continue
            if not is_first and len(b['text'])<110:
                if 'Bold' in ' '.join(b['fonts']):
                    paras.append({'kind':'heading','text':b['text']})
                continue
            lines=b['lines']
            if 'SourceSans3-Roman' in b['fonts'] and len(lines)>2 and len(lines[0])<85 and b['size']>=10.4:
                paras.append({'kind':'heading','text':lines[0]})
                paras.append({'kind':'paragraph','text':' '.join(lines[1:])})
            else:
                paras.append({'kind':'paragraph','text':b['text']})
    # A crop preserves the exact original diagram, alongside reflowable text.
    diagram_rows=[b for b in second if 9.5<b['size']<9.9 and 180<b['box'][1]<570 and len(b['text'])<200]
    diagram=None; diagram_text=[]
    if diagram_rows:
        first_y=min(b['box'][1] for b in diagram_rows)
        before=[b for b in second if 10<b['size']<12 and b['box'][1]<first_y and len(b['text'])<100 and b['box'][1]>150]
        top=before[-1]['box'][1]-9 if before else first_y-15
        bottom=min(571,max(b['box'][3] for b in second if top<b['box'][1]<570)+10)
        diagram=webp(doc[i+1],f'diagram-{ref.lower()}.webp',(43,top,393,bottom))
        diagram_text=[b['text'] for b in sorted(second,key=lambda x:(x['box'][1],x['box'][0])) if top<b['box'][1]<bottom]
    objective=next((b['text'] for b in first if 90<b['box'][1]<170 and 10<=b['size']<11),'')
    lessons.append({'ref':ref,'title':title,'page':i+1,'pages':[i+1,i+2],
                    'objective':objective,'paragraphs':paras,'cards':cards,
                    'diagram':diagram,'diagram_text':diagram_text})

for letter,start,art,hours in [('A',13,14,8),('B',67,68,9),('C',128,129,8),('D',189,190,7),('E',237,238,8),('F',286,287,7),('G',337,338,7),('H',387,388,6)]:
    page=doc[start-1]
    raw_image=max(doc[art-1].get_images(full=True),key=lambda x:x[2]*x[3])
    im=Image.open(io.BytesIO(doc.extract_image(raw_image[0])['image'])).convert('RGB')
    im.thumbnail((1600,1200)); image_name=f'module-{letter.lower()}.webp'
    im.save(MEDIA/image_name,'WEBP',quality=86,method=6)
    (ROOT/'static/images/vtc').mkdir(exist_ok=True)
    im.thumbnail((960,700)); im.save(ROOT/'static/images/vtc'/image_name,'WEBP',quality=82,method=6)
    texts=page.get_text().splitlines()
    bullets=[t.removeprefix('• ').strip() for t in texts if t.startswith('• ')]
    modules.append({'letter':letter,'title':title_of(page),'planned_minutes':hours*60,'page':start,
                    'image':'media/vtc/'+image_name,'illustration':'images/vtc/'+image_name,'objectives':bullets})

for i,page in enumerate(doc):
    t=page.get_text(); m=re.search(r'MODULE ([A-H]) • COMPLÉMENT DE COURS',t)
    if not m: continue
    letter=m[1]; b=blocks(page)
    title=title_of(page)
    content=[x['text'] for x in sorted(b,key=lambda x:(x['box'][1],x['box'][0])) if 112<x['box'][1]<570]
    extras[letter].append({'title':title,'page':i+1,'image':webp(page,f'complement-{i+1}.webp',(43,72,393,569)),
                           'text':content})

# Read the manual's original QCU and the corresponding justified answer keys.
quiz=collections.defaultdict(list); corrections={}
for page in doc:
    t=page.get_text(); mod=re.search(r'VTC / ([A-H])\n',t)
    if not mod: continue
    letter=mod[1]
    if 'CORRIGÉS /' in t:
        for n,answer,explanation in re.findall(r'(\d{2}) · ([ABC]) — (.*?)(?=\n\d{2} · [ABC] —|\nINTÉGRALE|\nLEÇON|\nATELIER|\n\d{3}\n|$)',t,re.S):
            corrections[(letter,int(n))]=(answer,' '.join(explanation.split()))
    if 'QUIZ / SANS LE COURS' not in t: continue
    pattern=r'^([0-9]{2}) (.*?)\nA (.*?)\nB (.*?)\nC (.*?)(?=\n[0-9]{2} |\nINTÉGRALE|\nCORRIGÉ|\n[0-9]{3}\n|$)'
    found=re.findall(pattern,t,re.M|re.S)
    assert len(found)==5,(letter,len(found))
    for n,prompt,a,b,c in found:
        clean=lambda value:' '.join(value.split())
        quiz[letter].append({'id':f'vtc-{letter.lower()}-manual-{n}','prompt':clean(prompt),
            'options':[{'id':key,'text':clean(value)} for key,value in zip('abc',[a,b,c])],'number':int(n)})
for letter,questions in quiz.items():
    for q in questions:
        answer,explanation=corrections[(letter,q.pop('number'))]
        q.update(answer=answer.lower(),explanation=explanation,module=letter,sources=['Manuel VTC Intégrale Academy, édition octobre 2026'])

assert len(lessons)==96
assert len({l['ref'] for l in lessons})==96
assert all(len(quiz[l])==10 for l in 'ABCDEFGH')
data={'source_sha256':hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest(),
      'source_name':Path(sys.argv[1]).name,'modules':modules,'lessons':lessons,'supplements':extras,'manual_questions':quiz}
(OUT/'manual_bank.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
print(json.dumps({'lessons':len(lessons),'words':sum(len(p['text'].split()) for l in lessons for p in l['paragraphs']),
                  'diagrams':sum(bool(l['diagram']) for l in lessons),'supplements':sum(map(len,extras.values())),
                  'manual_questions':sum(map(len,quiz.values()))}))
