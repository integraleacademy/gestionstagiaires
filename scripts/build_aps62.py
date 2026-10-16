"""Reproducible build from the supplied Academy manual and editorial source.

Usage: python scripts/build_aps62.py /path/to/APS.pdf
Runtime does not require the source PDF, PyMuPDF or this build script.
"""
from pathlib import Path
import hashlib
import io
import json
import re
import sys
import fitz
from PIL import Image
from aps62_editorial import MODULES, VERSION, records

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'elearning_native/aps62'
ASSETS = OUT / 'assets/media/aps62'
SOURCES = [
 ('Programme et modalités de formation', 'https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000052197461'),
 ('TFP APS : répartition du distanciel par l’ADEF', 'https://adef-securite.fr/tfp-aps-quelles-sequences-peuvent-etre-dispensees-a-distance-et-lesquelles-doivent-rester-en-presentiel/'),
 ('Code de la sécurité intérieure, livre VI', 'https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000025503132/LEGISCTA000025506179/'),
 ('CNAPS : tenue des agents', 'https://cnaps.interieur.gouv.fr/Publications/Fiches-thematiques/Tenue-des-agents-prives-de-securite'),
 ('CNIL : vidéoprotection au travail', 'https://www.cnil.fr/fr/la-videosurveillance-videoprotection-au-travail'),
 ('INRS : prévention du risque électrique', 'https://www.inrs.fr/risques/electriques/prevention-risque-electrique'),
 ('SGDSN : plan Vigipirate actualisé', 'https://www.sgdsn.gouv.fr/vigipirate'),
]

def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')

def paragraphs(page):
    result=[]
    for block in page.get_text('dict')['blocks']:
        if block['type'] != 0 or block['bbox'][1] < 61 or block['bbox'][3] > page.rect.height-50:
            continue
        spans=[s for line in block['lines'] for s in line['spans']]
        text=' '.join(s['text'].strip() for s in spans)
        size=max(s['size'] for s in spans)
        if not text or text.isdigit(): continue
        if size >= 17: continue  # activity supplies its own title
        kind='heading' if size >= 10.7 or text=='EXEMPLE EXPLIQUÉ' else 'paragraph'
        if text.startswith('À RETENIR'): kind='takeaway'
        result.append({'kind':kind,'text':text})
    return result

def build_bank(pdf, refs):
    doc=fitz.open(pdf); bank={}
    for i,page in enumerate(doc):
        t=page.get_text(); m=re.search(r'LEÇON (\d+\.\d+)\s*[·•]\s*(.*)',t)
        if not m or m[1] not in refs: continue
        code=m[1]
        if 'JE COMPRENDS' in m[2]:
            lines=t.splitlines(); start=next(j for j,l in enumerate(lines) if 'LEÇON ' in l)+1
            bank.setdefault(code,{})['title']=' '.join(lines[start:start+2])
            name=f'repere-{code}.webp'; pix=page.get_pixmap(matrix=fitz.Matrix(2,2))
            Image.frombytes('RGB',[pix.width,pix.height],pix.samples).save(ASSETS/name,quality=86)
            bank[code].update({'page':i+1,'diagram':f'media/aps62/{name}'})
        if 'COURS DÉVELOPPÉ' in m[2]:
            bank.setdefault(code,{})['paragraphs']=paragraphs(page)
            bank[code]['course_page']=i+1
            title_spans=[s['text'].strip() for b in page.get_text('dict')['blocks'] if b['type']==0
                         for line in b['lines'] for s in line['spans'] if s['size'] >= 17]
            bank[code]['title']=' '.join(title_spans)
        if 'JE M’ENTRAÎNE' in m[2]:
            before, _, after=t.partition('1  ÉTUDIER LA SITUATION')
            background=next((p['text'] for p in paragraphs(page) if len(p['text']) > 150
                             and p['text'] in ' '.join(before.split())), '')
            scenario, _, transfer=after.partition('2  RÉUTILISER DANS UN AUTRE CAS')
            scenario=re.split(r'\n1\n',scenario)[0]
            transfer=transfer.split('Point de vigilance')[0]
            bank.setdefault(code,{})['practice']={
                'background':background,'case':' '.join(scenario.split()),
                'transfer':' '.join(transfer.split()),'page':i+1,
            }
    for code in refs:
        assert bank.get(code,{}).get('paragraphs'), code
    dump(OUT/'manual_bank.json',bank)
    return bank

def prepare_assets(pdf):
    ASSETS.mkdir(parents=True,exist_ok=True)
    scene_pages={1:51,2:118,3:169,4:205,5:244,6:283,7:325,8:409,9:466,10:500,11:539,12:576,13:606,14:637}
    doc=fitz.open(pdf)
    for scene in {int(m[3]) for m in MODULES}:
        destination=ASSETS/f'scene-{scene:02d}.webp'
        if not destination.exists():
            page=doc[scene_pages[scene]-1]
            source=max(page.get_images(),key=lambda im:im[2]*im[3])
            raw=doc.extract_image(source[0])['image']
            Image.open(io.BytesIO(raw)).convert('RGB').save(destination,quality=86)
    cover=ROOT/'static/images/aps62-cover.webp'
    cover.parent.mkdir(parents=True,exist_ok=True)
    if not cover.exists():cover.write_bytes((ASSETS/'scene-02.webp').read_bytes())

def sentence(text):
    return re.split(r'(?<=[.!?])\s+',text)[0]

def cards_for(refs,bank):
    cards=[]
    for ref in refs:
        heading=bank[ref]['title']
        for item in bank[ref]['paragraphs']:
            if item['kind']=='heading': heading=item['text']
            elif item['kind']=='paragraph':
                cards.append({'front':heading,'back':item['text']})
    return cards[:4]

def build(pdf):
    prepare_assets(pdf)
    data=records(); refs={r for rows in data.values() for row in rows for r in row['refs']}
    bank=build_bank(pdf,refs)
    media=json.loads((OUT/'video_manifest.json').read_text()) if (OUT/'video_manifest.json').exists() else {}
    manifest=[]; total_words=0
    for code,title,hours,scene,regulation in MODULES:
        cid=f'academy-aps62-{code}'; sections=[]
        for n,row in enumerate(data[code],1):
            sid=f'aps62-{code}-{n:02d}'; aids=[]; cards=cards_for(row['refs'],bank)
            common={'dossier':f'{code}.{n:02d}','title':row['title']}
            def content(suffix,label,minutes,academy,**extra):
                a={'id':sid+'-'+suffix,'title':label,'type':'content','scored':False,
                   'planned_minutes':minutes,'blocks':[],'academy':{**common,**academy},**extra}
                aids.append(a); return a
            lessons=[{'ref':r,**bank[r]} for r in row['refs']]
            lecture=content('comprendre','Comprendre · '+row['title'],18,{
                'kind':'lesson','image':f'media/aps62/scene-{scene}.webp',
                'case':row['case'],'reason':row['reason'],'lessons':lessons,
                'decision':row['good'],'pitfall':row['bad'],
                'objectives':['Expliquer : '+row['title'].lower(),
                              'Justifier une décision à partir de faits et de limites.',
                              'Produire une réponse professionnelle et analyser une variante.'],
                'table':[['Faits disponibles',row['case']],['Décision à justifier',row['good']],
                         ['Piège à éviter',row['bad']],['Pourquoi ?',row['reason']]],
                'flow':[{'label':'Observer','text':sentence(row['case'])},
                        {'label':'Vérifier','text':sentence(row['reason'])},
                        {'label':'Décider','text':row['good']},
                        {'label':'Réévaluer','text':row['transfer']}],
            })
            memo=content('memoriser','Voir et mémoriser',8,{'kind':'memory','cards':cards,
                'instruction':'Regardez la capsule. Fermez ensuite la correction et expliquez chaque carte à voix haute avant de la retourner. Revenez au cours pour les points hésitants.'})
            if sid in media:
                video=media[sid]
                memo['blocks']=[{'id':sid+'-video','type':'video','html':'','children':[],
                    'video':{'id':sid+'-video','title':row['title'],'required':True,**video}}]
                memo['academy']['transcript']=video.get('transcript','')
            else:
                raise ValueError('Missing exported video: '+sid)
            choices=[{'text':row['good'],'feedback':row['reason'],'correct':True},
                     {'text':row['bad'],'feedback':'Cette proposition dépasse le cadre ou augmente le risque. '+row['reason'],'correct':False},
                     {'text':row['misleading'],'feedback':'Cette proposition ne répond pas aux faits disponibles. '+row['model'],'correct':False}]
            shift=n%3; choices=choices[shift:]+choices[:shift]
            content('atelier','Atelier · prendre position et rédiger',16,{
                'kind':'workshop','case':row['case'],'choices':choices,'task':row['task'],
                'model':row['model'],'criteria':['Faits et sources clairement distingués',
                'Décision et limite expliquées','Message compréhensible par le destinataire',
                'Relais, incertitudes et suites explicités']},workbook={'min_chars':180,'max_chars':12000})
            options=[{'id':f'{sid}-a{i}','text':c['text'],'is_correct':c['correct']} for i,c in enumerate(choices)]
            aids.append({'id':sid+'-q1','title':'Défi décision · quelle réponse retenir ?',
                         'type':'question','question_type':'single_choice','scored':True,
                         'planned_minutes':4,'prompt':row['case'],'options':options,'explanation':row['reason']})
            pairs=[{'id':sid+f'-pair{i}','left':c['front'],'right':sentence(c['back'])} for i,c in enumerate(cards[:3])]
            assert len(pairs)==3
            aids.append({'id':sid+'-q2','title':'Défi notions · relier et expliquer',
                         'type':'question','question_type':'matching','scored':True,'planned_minutes':4,
                         'prompt':'Reliez les notions à leur explication. Avant de valider, expliquez pourquoi les autres associations ne conviennent pas.',
                         'pairs':pairs,'explanation':' '.join(p['left']+' : '+p['right'] for p in pairs)})
            content('transfert','Changer de situation · réutiliser la méthode',8,{
                'kind':'transfer','case':row['transfer'],'task':
                'Rédigez une réponse argumentée. Distinguez ce que cette nouvelle information change, ce qu’elle ne permet pas de conclure, les vérifications encore nécessaires et le relais adapté.',
                'model':row['reason']+' '+row['model'],
                'criteria':['La nouvelle information est prise en compte','Les limites restent identifiées',
                            'La décision est justifiée','Les vérifications et le relais sont précisés']},
                workbook={'min_chars':120,'max_chars':12000})
            content('synthese','Synthèse · mes repères de terrain',2,{
                'kind':'recap','decision':row['good'],'reason':row['reason'],
                'pitfall':row['bad'],'cards':cards[:3],'sources':SOURCES,
                'manual_refs':[{'ref':r,'page':bank[r]['course_page']} for r in row['refs']],
                'instruction':'Sans regarder le cours, résumez le raisonnement en trois phrases. Notez la question que vous souhaitez reprendre avec votre formateur. Les exercices écrits sont des productions pédagogiques, pas une validation automatique de compétence pratique.'})
            sections.append({'id':sid,'title':f'{n:02d} · {row["title"]}','planned_minutes':60,'activities':aids})
        activities=[a for s in sections for a in s['activities']]
        assets=sorted(set(re.findall(r'media/aps62/[\w.\-]+',json.dumps(sections))))
        course={'format_version':1,'id':cid,'version':VERSION,'title':f'APS {code} · {title}',
            'locale':'fr','author_name':'Intégrale Academy','source':{'type':'academy-aps62','reviewed_on':'2026-10-03'},
            'settings':{'mastery_score':80,'force_navigation':True,'attempts_limited':False},
            'theme':{'main_color':'#2860e8','button_color':'#245bdb','text_color':'#172b4d'},
            'planned_minutes':hours*60,'required_minutes':hours*60,'regulation':regulation,
            'introduction':[],'sections':sections,'activity_order':[a['id'] for a in activities],
            'counts':{'sections':len(sections),'activities':len(activities),'scored_activities':2*hours,
                'required_videos':hours,'workbooks':2*hours,'assets':len(assets)},
            'assets':assets,'import_warnings':[]}
        dump(OUT/'courses'/cid/(VERSION+'.json'),course)
        manifest.append({'id':cid,'version':VERSION,'title':title,'number':code,'hours':hours,
                         'scene':scene,'sections':hours,'activities':len(activities),'regulation':regulation})
        total_words+=len(' '.join(v for s in sections for a in s['activities'] for v in [json.dumps(a,ensure_ascii=False)]).split())
    dump(OUT/'manifest.json',{'version':VERSION,'hours':62,'modules':manifest,'sources':SOURCES,
         'sequence_count':62,'activity_count':434,'workbook_count':124,'question_count':124,'video_count':62,
         'manual_lesson_count':len(bank),'editorial_words':sum(len(v.split()) for rows in data.values() for row in rows for v in row.values() if isinstance(v,str)),
         'manual_words':sum(len(p['text'].split()) for b in bank.values() for p in b['paragraphs'])
             + sum(len(v.split()) for b in bank.values() for v in b.get('practice',{}).values() if isinstance(v,str)),
         'source_sha256':hashlib.sha256(Path(pdf).read_bytes()).hexdigest()})
    print('Built 15 modules / 62 dossiers / 434 activities / 124 written assignments / 124 questions; manual lessons:',len(bank))

if __name__=='__main__':
    if '--assets-only' in sys.argv:
        prepare_assets(sys.argv[1])
    else:
        build(sys.argv[1])
