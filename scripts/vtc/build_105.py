"""Compile the new 105-hour programme without mutating assigned older editions."""
from pathlib import Path
import copy, hashlib, json, random, re
from edition105 import legal, business, driving, french, english, applied, missions

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'elearning_native/vtc'
VERSION='20261006-vtc-v3-105h'
PREVIOUS=['20261006-vtc-v1','20261006-vtc-v2']
HOURS=dict(zip('ABCDEFGH',[14,16,14,11,15,14,11,10]))
LESSON_MIN=dict(zip('ABCDEFGH',[20,22,20,15,18,20,15,12]))

def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def journey(aid,title,ref,exercises,minutes,purpose,introduction='',adaptive=False):
    exercises=copy.deepcopy(exercises)
    for i,ex in enumerate(exercises):ex['id']=f'e{i+1:03}'
    return {'id':aid,'title':title,'type':'content','scored':False,'planned_minutes':minutes,'blocks':[],
      'vtc':{'kind':'journey','ref':ref,'module':ref[0],'introduction':introduction},
      'practice':{'revision':VERSION,'mode':'journey','purpose':purpose,'adaptive':adaptive,'exercises':exercises}}

def find_assets(value):
    if isinstance(value,str):
        if value.startswith('media/vtc/'):yield value
    elif isinstance(value,dict):
        for v in value.values():yield from find_assets(v)
    elif isinstance(value,list):
        for v in value:yield from find_assets(v)

def main():
    topics={};practices={}
    for author in [legal,business,driving,french,english]:
        t,p,*_=author.build();topics.update(t);practices.update(p)
    applied.enrich(topics,practices)
    assert len(topics)==96 and len(practices)==96
    listening=json.loads((OUT/'listening_manifest_v3.json').read_text());assert len(listening)==48
    cases=json.loads((OUT/'manual_cases_v3.json').read_text())
    old=json.loads((OUT/'manifest.json').read_text())
    manifest={k:copy.deepcopy(old[k]) for k in ['id','title','sources','notice','final_exam_id']}
    manifest.update(version=VERSION,reviewed_on='2026-10-06',planned_minutes=6300,lesson_count=96,workshop_count=96,
      modules=[],exam_versions=PREVIOUS+[VERSION],video_count=8,narrated_video_count=8,
      professional_workshops=96,mission_count=16,listening_count=48,listening_minutes=round(sum(v['duration_seconds'] for v in listening.values())/60,1),
      diagnostic_count=8,adaptive_review_count=8,duration_status='programme_previsionnel',
      duration_note='105 h de programme pédagogique prévisionnel. La durée réellement nécessaire dépend des acquis et des reprises. Le suivi distingue le temps actif et l’achèvement ; un groupe pilote permet de calibrer les estimations.',
      module_exam_questions=240,final_exam_questions=100)
    extra_sources=[
      {'title':'Justificatif de réservation préalable · arrêté du 6 août 2025','url':'https://www.legifrance.gouv.fr/loda/id/JORFTEXT000052153206/'},
      {'title':'Minimisation des données · CNIL','url':'https://www.cnil.fr/fr/minimiser-les-donnees-collectees'},
      {'title':'Durées de conservation · CNIL','url':'https://www.cnil.fr/fr/passer-laction/les-durees-de-conservation-des-donnees'},
      {'title':'Fatigue au volant · Sécurité routière','url':'https://modules.securite-routiere.gouv.fr/jsrt/Fatigue/Fatigue.html'},
    ]
    seen={s['url'] for s in manifest['sources']};manifest['sources'] += [s for s in extra_sources if s['url'] not in seen]
    counts={'activities':0,'exercises':0,'decisions':0};exams=[]
    for letter in 'ABCDEFGH':
        cid='academy-vtc-'+letter.lower();c=json.loads((OUT/'courses'/cid/(PREVIOUS[-1]+'.json')).read_text())
        c['version']=VERSION;c['planned_minutes']=HOURS[letter]*60;c['required_minutes']=0
        c['source'].update(edition='105h',reviewed_on='2026-10-06');c['duration_note']=manifest['duration_note']
        sections=copy.deepcopy(c['sections'][:12]);core_minutes=c['planned_minutes']-150
        per,remainder=divmod(core_minutes,12)
        for n,section in enumerate(sections):
            ref=letter+f'.{n+1:02}';lesson,workshop=section['activities']
            lesson['planned_minutes']=LESSON_MIN[letter];workshop['planned_minutes']=6
            lesson['vtc']['deepening']=topics[ref]
            if ref in cases:lesson['vtc']['manual_case']=cases[ref]
            dossier_minutes=per+int(n<remainder)-lesson['planned_minutes']-6
            assert dossier_minutes>=15,(ref,dossier_minutes)
            stage=journey('vtc-'+ref.lower().replace('.','-')+'-dossier','Décider et appliquer · '+lesson['title'],ref,
               practices[ref],dossier_minutes,topics[ref]['title'],
               'Cette séance combine l’analyse des données, les décisions, la lecture des corrections et la reprise des erreurs. Les exemples chiffrés et les documents sont fictifs. Prenez le temps d’expliquer mentalement chaque décision avant de la vérifier.')
            section['activities'].append(stage)
        for m in missions.build(letter,topics,practices):
            aid='vtc-'+m['id']
            sections.append({'id':aid,'title':'Mission filée · '+m['title'],'activities':[
              journey(aid,m['title'],letter+'.MISSION',m['exercises'],40,'Une mission, des décisions successives',m['introduction'])]})
        diagnostic=[];review=[]
        for n in range(1,13):
            ref=letter+f'.{n:02}';choices=[e for e in practices[ref] if e['kind']=='single']
            assert len(choices)>=3,ref
            diagnostic.extend(copy.deepcopy(choices[i%len(choices)]) for i in [0,2])
            review.extend(copy.deepcopy(choices[i%len(choices)]) for i in [1,3])
        sections.append({'id':'vtc-'+letter.lower()+'-evaluation','title':'Bilan · évaluer puis réviser','activities':[
          journey('vtc-'+letter.lower()+'-diagnostic','Faire le point · 24 décisions',letter+'.BILAN',diagnostic,20,'Évaluer votre raisonnement',
             'Répondez sans relire immédiatement le cours. Les premières erreurs servent à repérer les notions à consolider. La correction reste disponible ; ce bilan n’est pas l’examen officiel.'),
          journey('vtc-'+letter.lower()+'-revision','Réviser selon mes erreurs · 24 décisions',letter+'.REVISION',review,30,'Reprendre les notions qui vous ont posé problème',
             'Les thèmes de vos premières erreurs sont présentés en priorité. Lisez les explications, reprenez les décisions à revoir, puis vérifiez votre compréhension sur les autres notions.',adaptive=True)]})
        synthesis=copy.deepcopy(c['sections'][-1]);synthesis['activities'][0]['planned_minutes']=2;synthesis['activities'][1]['planned_minutes']=18
        sections.append(synthesis);c['sections']=sections
        c['activity_order']=[a['id'] for s in sections for a in s['activities']]
        c['assets']=sorted(set(c['assets'])|set(find_assets(sections)))
        assert len(c['activity_order'])==len(set(c['activity_order']))==42
        assert sum(a['planned_minutes'] for s in sections for a in s['activities'])==c['planned_minutes']
        for name in c['assets']:assert (OUT/'assets'/name).is_file(),name
        exercise_count=sum(len(a.get('practice',{}).get('exercises',[])) for s in sections for a in s['activities'])
        decision_count=sum(len(ex.get('rows',[])) or 1 for s in sections for a in s['activities'] for ex in a.get('practice',{}).get('exercises',[]))
        c['counts'].update(sections=len(sections),activities=42,interactive_workshops=12,professional_workshops=12,
          interactive_missions=2,diagnostics=1,adaptive_reviews=1,exercises=exercise_count,decisions=decision_count,
          listening_dialogues=48 if letter=='E' else 0,assets=len(c['assets']),workbooks=0)
        c['duration_breakdown']=[{'label':'Cours, exemples et schémas','minutes':12*LESSON_MIN[letter]},
          {'label':'Ateliers de repères','minutes':72},
          {'label':'Dossiers professionnels et corrections','minutes':core_minutes-12*LESSON_MIN[letter]-72},
          {'label':'Deux missions filées','minutes':80},
          {'label':'Bilan et révisions adaptées aux erreurs','minutes':50},
          {'label':'Synthèse, vidéo et approfondissement','minutes':20}]
        c['programme_minutes']=6300
        save(OUT/'courses'/cid/(VERSION+'.json'),c)
        base_module=next(m for m in old['modules'] if m['letter']==letter)
        base_module=copy.deepcopy(base_module);base_module.update(version=VERSION,previous_versions=PREVIOUS,
          planned_minutes=c['planned_minutes'],counts=c['counts'],duration_breakdown=c['duration_breakdown'])
        manifest['modules'].append(base_module)
        # Versioned mock exams remain standalone; listening and document cases use their own journeys.
        exam=json.loads((OUT/'exams'/PREVIOUS[-1]/('vtc-'+letter.lower()+'.json')).read_text());exam['version']=VERSION
        random.Random(VERSION+letter).shuffle(exam['questions']);save(OUT/'exams'/VERSION/(exam['id']+'.json'),exam);exams.append(exam)
        counts['activities']+=42;counts['exercises']+=exercise_count;counts['decisions']+=decision_count
    final=[]
    for i,exam in enumerate(exams[:7]):
        qs=copy.deepcopy(exam['questions']);random.Random(VERSION+str(i)).shuffle(qs);final+=qs[:15 if i<2 else 14]
    random.Random(VERSION).shuffle(final)
    assert len(final)==100 and len({q['id'] for q in final})==100
    save(OUT/'exams'/VERSION/'vtc-final.json',{'id':'vtc-final','version':VERSION,'training_label':'VTC',
       'title':'VTC · Examen blanc final · Les sept matières','pass_percent':80,'questions':final,'notice':manifest['notice']})
    manifest.update(activity_count=counts['activities'],exercise_count=counts['exercises'],decision_count=counts['decisions'])
    save(OUT/'manifest.json',manifest)
    save(OUT/'programme_105.json',{'version':VERSION,'planned_minutes':6300,'status':manifest['duration_status'],'duration_note':manifest['duration_note'],
      'modules':[{'letter':m['letter'],'title':m['title'],'planned_minutes':m['planned_minutes'],'breakdown':m['duration_breakdown']} for m in manifest['modules']],
      'validation':{'real_learners_tested':0,'measured_median_minutes':None,
       'method':'Groupe pilote de profils variés : mesurer les temps actifs par activité et les premières erreurs ; recueillir les difficultés ; comparer la médiane et les écarts au programme ; ajouter, scinder ou redistribuer les séquences avant de déclarer la durée validée.'},
      'rules':['Aucun temps fictif ajouté par une réponse ou une correction.','Aucune rédaction libre demandée.','Les anciennes affectations conservent leur version.','La pratique en circulation nécessite un entraînement encadré distinct.']})
    print(json.dumps({'version':VERSION,'minutes':6300,'lessons':96,'new_dossiers':96,'missions':16,'dialogues':48,**counts},ensure_ascii=False))

if __name__=='__main__':main()
