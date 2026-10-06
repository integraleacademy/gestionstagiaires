"""Build immutable VTC courses and answer banks from the reviewed editorial data."""
from pathlib import Path
import copy, hashlib, json, random
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'elearning_native/vtc'
VERSION='20261006-vtc-v2'
PREVIOUS_VERSION='20261006-vtc-v1'
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
bank=json.loads((OUT/'manual_bank.json').read_text())
videos=json.loads((OUT/'video_manifest_v2.json').read_text())
assert len(videos)==8 and all(v.get('audio') and v.get('voice')=='fr-FR-HenriNeural' for v in videos.values())
questions={}
for row in (ROOT/'scripts/vtc/questions.txt').read_text().splitlines():
    if not row or row.startswith('#'):continue
    ref,prompt,good,bad1,bad2,explanation=row.split('|')
    number=len(questions.get(ref,[]))+1
    qid='vtc-'+ref.lower().replace('.','-')+f'-q{number}'
    opts=[{'id':hashlib.sha256((qid+':'+str(i)).encode()).hexdigest()[:12],'text':txt} for i,txt in enumerate((good,bad1,bad2))]
    answer_id=opts[0]['id']
    random.Random(qid).shuffle(opts)
    questions.setdefault(ref,[]).append({'id':qid,'prompt':prompt,'options':opts,'answer':answer_id,
       'explanation':explanation,'module':ref[0],'sources':[f'Manuel VTC Intégrale Academy · Leçon {ref}']})

SOURCES=[
 {'title':'Programme et modalités de l’examen · arrêté du 6 avril 2017 modifié','url':'https://www.legifrance.gouv.fr/loda/id/JORFTEXT000034379046/'},
 {'title':'Devenir chauffeur de VTC · Service Public','url':'https://entreprendre.service-public.gouv.fr/vosdroits/F31027'},
 {'title':'Réforme de l’accès par expérience · décret du 5 août 2026','url':'https://www.legifrance.gouv.fr/loda/id/JORFTEXT000054658967/'},
]
EXAM=[(45,3,'10 QCM + 5 QRC'),(45,2,'16 QCM + 2 QRC'),(30,3,'20 QCM'),(30,2,'7 QCM + 3 QRC'),(30,1,'20 QCM'),(30,3,'12 QCM + 4 QRC'),(20,3,'6 QCM + 2 QRC'),(20,0,'Mise en situation en circulation')]
manifest={'id':'vtc','version':VERSION,'title':'VTC · Le parcours illustré','reviewed_on':'2026-10-06',
 'planned_minutes':3600,'lesson_count':96,'workshop_count':96,'sources':SOURCES,'modules':[],
 'exam_versions':[PREVIOUS_VERSION,VERSION],'final_exam_id':'vtc-final',
 'notice':'Parcours pédagogique de préparation : les durées sont indicatives et réglables par le centre. L’examen officiel comprend des QRC écrites et une épreuve de conduite en circulation. Les entraînements en ligne se font sans rédaction.'}
module_exams=[]
for m,official in zip(bank['modules'],EXAM):
    letter=m['letter']; cid='academy-vtc-'+letter.lower(); sections=[]
    assets={m['image']}; lessons=[l for l in bank['lessons'] if l['ref'].startswith(letter)]
    allq=[]
    lesson_minutes=(m['planned_minutes']-36)//12
    remainder=m['planned_minutes']-36-12*lesson_minutes
    for index,l in enumerate(lessons):
        ref=l['ref']; aid='vtc-'+ref.lower().replace('.','-')
        content=copy.deepcopy(l)
        content.update(kind='lesson',image=m['image'],module=letter)
        if l.get('diagram'):assets.add(l['diagram'])
        qset=copy.deepcopy(questions[ref]); allq.extend(qset)
        exercises=[dict(q,id=f'q{i+1}',kind='single') for i,q in enumerate(qset)]
        opts=[{'id':f'c{i}','text':c['label']} for i,c in enumerate(l['cards'])]
        rows=[{'id':f'r{i}','text':c['text'],'answer':f'c{i}'} for i,c in enumerate(l['cards'])]
        random.Random(aid).shuffle(opts);random.Random(aid+'rows').shuffle(rows)
        exercises.append({'id':'reperes','kind':'matching','prompt':'Associez chaque explication au bon repère.',
           'options':opts,'rows':rows,'explanation':'Ces trois repères reprennent le schéma de la leçon '+ref+'. Reprenez le cours si une association reste incertaine.'})
        minutes=lesson_minutes+int(index<remainder)
        sections.append({'id':aid,'title':ref+' · '+l['title'],'activities':[
           {'id':aid+'-cours','title':l['title'],'type':'content','scored':False,'planned_minutes':minutes-12,'blocks':[],'vtc':content},
           {'id':aid+'-atelier','title':'À vous de jouer · '+l['title'],'type':'content','scored':False,'planned_minutes':12,'blocks':[],
            'vtc':{'kind':'workshop','ref':ref,'title':l['title'],'objective':l['objective'],'module':letter},
            'practice':{'revision':VERSION,'exercises':exercises}}]})
    supplements=bank['supplements'].get(letter,[])
    assets.update(x['image'] for x in supplements)
    video=videos.get(letter)
    video_blocks=[]
    if video:
        assets.update(video[k] for k in ('src','poster','captions'))
        video_blocks=[{'type':'Video','video':{**video,'id':'vtc-'+letter.lower()+'-capsule','title':'Les essentiels · '+m['title'],'required':True}}]
    sections.append({'id':'vtc-'+letter.lower()+'-synthese','title':'Synthèse · relier les notions','activities':[
       {'id':'vtc-'+letter.lower()+'-capsule','title':'Voir et retenir · les essentiels','type':'content','scored':False,'planned_minutes':12,'blocks':video_blocks,
        'vtc':{'kind':'recap','module':letter,'title':m['title'],'image':m['image'],'transcript':video.get('transcript','') if video else '',
               'audio':bool(video and video.get('audio')),
               'cards':[{'label':l['ref'],'text':l['title']} for l in lessons]}},
       {'id':'vtc-'+letter.lower()+'-approfondir','title':'Approfondir · repères et méthode','type':'content','scored':False,'planned_minutes':24,'blocks':[],
        'vtc':{'kind':'supplements','module':letter,'title':'Relier le cours à la mission','supplements':supplements,'sources':SOURCES,
               'exam':{'minutes':official[0],'coefficient':official[1],'format':official[2]},'notice':manifest['notice']}}
    ]})
    course={'format_version':1,'id':cid,'version':VERSION,'title':'VTC '+letter+' · '+m['title'],
     'locale':'fr','author_name':'Intégrale Academy','training_label':'VTC',
     'source':{'type':'academy-vtc','reviewed_on':'2026-10-06','manual_sha256':bank['source_sha256']},
     'settings':{'mastery_score':80,'force_navigation':True,'attempts_limited':False},
     'theme':{'main_color':'#7045bd','button_color':'#6534b4','text_color':'#241a38'},
     'planned_minutes':m['planned_minutes'],'required_minutes':0,'introduction':[],
     'illustration':m['illustration'],'mock_exam_id':'vtc-'+letter.lower(),'mock_exam_questions':30,
     'regulation':'Épreuve '+letter if letter!='H' else 'Préparation à la pratique en circulation',
     'sections':sections,'activity_order':[a['id'] for s in sections for a in s['activities']],
     'assets':sorted(assets),'import_warnings':[],
     'counts':{'sections':13,'lessons':12,'activities':26,'scored_activities':0,'workbooks':0,'interactive_workshops':12,'required_videos':int(bool(video)),'assets':len(assets)}}
    save(OUT/'courses'/cid/(VERSION+'.json'),course)
    manifest['modules'].append({'id':cid,'version':VERSION,'previous_versions':[PREVIOUS_VERSION],'letter':letter,'title':course['title'],
       'planned_minutes':m['planned_minutes'],'illustration':m['illustration'],'mock_exam_id':course['mock_exam_id'],
       'exam':{'minutes':official[0],'coefficient':official[1],'format':official[2]},'lessons':[{'ref':l['ref'],'title':l['title'],'page':l['page']} for l in lessons]})
    exam_questions=allq+copy.deepcopy(bank['manual_questions'][letter][:6])
    assert len(exam_questions)==30
    random.Random(cid).shuffle(exam_questions)
    exam={'id':'vtc-'+letter.lower(),'version':VERSION,'training_label':'VTC','title':'VTC · '+m['title']+' · Examen blanc',
          'pass_percent':80,'questions':exam_questions,'notice':manifest['notice']}
    save(OUT/'exams'/VERSION/(exam['id']+'.json'),exam);module_exams.append(exam)
final=[]
for i,exam in enumerate(module_exams[:7]):
    # 100 questions, all seven official theory subjects, no practical substitution.
    selected=copy.deepcopy(exam['questions']);random.Random('final'+str(i)).shuffle(selected)
    final.extend(selected[:15 if i<2 else 14])
random.Random(VERSION).shuffle(final)
assert len(final)==100 and len({q['id'] for q in final})==100
save(OUT/'exams'/VERSION/'vtc-final.json',{'id':'vtc-final','version':VERSION,'training_label':'VTC',
 'title':'VTC · Examen blanc final · Les sept matières','pass_percent':80,'questions':final,'notice':manifest['notice']})
manifest.update(activity_count=208,video_count=len(videos),narrated_video_count=sum(bool(v.get('audio')) for v in videos.values()),exercise_count=288,question_bank_count=272,
                module_exam_questions=240,final_exam_questions=100)
save(OUT/'manifest.json',manifest)
print('Built 8 courses, 96 lessons, 96 workshops / 288 exercises, 8×30 and final 100 questions; videos:',len(videos))
