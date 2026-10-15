"""A3P 157 h 30: 160 sequences, measured media, click-only casework.

Study budgets are editorial allocations, never credit granted to learner clocks.
The previous editions remain loadable for every previously assigned session.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from functools import lru_cache
from . import a3p_v3 as previous
from .aps_depth import _exercise

ROOT = previous.ROOT
VERSION = '20261015-a3p-v4-157h30'
MODULES, NOTICE = previous.MODULES, previous.NOTICE
curriculum_ids = previous.curriculum_ids


@lru_cache(maxsize=1)
def programme():
    rows = json.loads((ROOT/'v4/programme.json').read_text())
    assert len(rows) == 160 and sum(r['minutes'] for r in rows) == 9450
    return rows


@lru_cache(maxsize=1)
def media():
    manifest = json.loads((ROOT/'v4/media_manifest.json').read_text())
    expected = {r['id'] for r in programme()}
    assert set(manifest) == expected, 'Incomplete A3P video production'
    for row in manifest.values():
        assert row['duration_seconds'] >= 300 and row['narration_seconds'] >= 295
        assert row['required'] and row['burned_captions']
    return manifest


def _base(ref):
    return (previous.previous._injuries_lesson() if ref == '09.15' else
            next(r for r in previous._manual()['lessons'] if r['ref'] == ref))


def _page(key, title, paragraphs):
    return {'page': key, 'kind': 'COURS A3P', 'source_label': 'Intégrale Academy · parcours 157 h 30',
            'components': [{'kind':'heading','text':title}, *[{'kind':'paragraph','text':p} for p in paragraphs]]}


def _pages(row):
    base = _base(row['ref'])
    same = [r for r in programme() if r['ref'] == row['ref']]
    index = next(i for i,r in enumerate(same) if r['id'] == row['id'])
    # A common reference is studied in full at its first use. Subsequent focuses
    # revisit selected pages and add their own case, rather than duplicate all pages.
    pages = base['pages'] if index == 0 else [base['pages'][index % len(base['pages'])]]
    result = [_page(row['id']+'-focus', row['title'], [row['teaching']])]
    result.extend(copy.deepcopy(pages))
    focus = previous._bank()[row['ref']]
    for i,part in enumerate(focus['teaching']):
        result.append(_page(row['id']+f'-repere-{i}', part['title'], [part['text']]))
    result.append(_page(row['id']+'-cas', 'Étudier le cas expliqué dans la vidéo',
        [row['situation'], 'Élément établi : '+row['fact'], 'Limite de l’information : '+row['unknown'],
         'Décision expliquée : '+row['decision']]))
    result.append(_page(row['id']+'-methode', 'Préparer le travail sur dossier', [
        'Relisez la situation en distinguant les faits confirmés, les informations manquantes et les décisions. Recherchez dans le cours la règle qui explique le choix. Identifiez ce qui devrait changer si une condition de la mission disparaissait.',
        'Dans l’atelier, une nouvelle pièce modifie le dossier. Classez les informations, associez les contrôles à leurs objectifs puis choisissez la réponse adaptée. Les corrections sont accessibles après votre réponse. Aucun texte à rédiger n’est demandé.',
        'Les gestes, la conduite et les déplacements professionnels se travaillent dans les séances présentielles prévues. L’analyse de ce dossier prépare le raisonnement et ne constitue pas une validation pratique.']))
    return result


def _practice(row):
    documents = [
        {'title':'1 · Situation initiale','text':row['situation']},
        {'title':'2 · Constat confirmé','text':row['fact']},
        {'title':'3 · Réserve du dossier','text':row['unknown']},
        {'title':'4 · Nouvelle information','text':row['change']},
    ]
    rationale = row['teaching']+' Dans le dossier actualisé : '+row['revised']
    authored = [
        {'kind':'classification','prompt':'Attribuez à chaque élément son statut dans le dossier.',
         'categories':['Constat initial confirmé','Information manquante initialement','Évolution nouvellement reçue','Conclusion non démontrée'],
         'rows':[(row['fact'],0),(row['unknown'],1),(row['change'],2),('Toutes les conditions initiales restent valables sans nouvelle vérification.',3)],
         'explanation':'Le statut d’une information dépend de la pièce et de sa date. Le nouveau fait ne permet pas de supposer que tout le plan demeure valable.'},
        {'kind':'matching','prompt':'Associez chaque pièce à son utilité dans votre décision.',
         'pairs':[(row['fact'],'Identifier le point de départ confirmé'),(row['unknown'],'Délimiter ce que le dossier initial ne permet pas de conclure'),(row['change'],'Repérer ce qui impose une réévaluation')],
         'explanation':'Une décision fiable relie l’état initial, ses limites et l’évolution. Elle ne confond pas information manquante et confirmation favorable.'},
        {'kind':'single','prompt':'Quelle décision répond au dossier actualisé ?',
         'texts':[row['revised'],row['decision']+' Maintenir cette décision telle quelle sans examiner la nouvelle pièce.',
                  'Attendre la fin de la mission pour examiner cette nouvelle information.'],
         'explanation':rationale},
        {'kind':'order','prompt':'Remettez dans l’ordre les étapes de traitement du changement dans ce dossier.',
         'steps':['Prendre connaissance de la nouvelle pièce : '+row['change'],
                  'Comparer cette évolution aux conditions du choix initial : '+row['decision'],
                  'Faire appliquer la réponse adaptée : '+row['revised'],
                  'Confirmer la transmission de la décision et conserver les limites utiles à la réévaluation.'],
         'explanation':'Cet ordre décrit le raisonnement sur dossier. En présence d’un danger immédiat, la protection et l’alerte ne sont pas retardées par une formalité documentaire.'},
        {'kind':'classification','prompt':'Classez les propositions de compte rendu.',
         'categories':['À retenir dans une transmission factuelle','À écarter car non démontré ou trompeur'],
         'rows':[(row['fact'],0),(row['change'],0),('La situation est définitivement sans risque.',1),('La nouvelle information était connue dès le début de la mission.',1)],
         'explanation':'La transmission conserve les faits et la chronologie. Elle ne promet pas une absence de risque et ne réécrit pas les informations disponibles initialement.'},
        {'kind':'single','prompt':'Quelle synthèse conserve la logique de votre décision ?',
         'texts':['Le constat initial était : '+row['fact']+' La nouvelle pièce impose de réévaluer la réponse.',
                  'Le dossier initial suffit puisque la première décision avait été expliquée dans le cours.',
                  'La nouvelle pièce permet de considérer comme confirmées toutes les informations manquantes.'],
         'explanation':rationale},
    ]
    for item in authored: item['context'] = 'Comparez les quatre pièces du dossier. La quatrième modifie les conditions initiales.'
    return {'revision':VERSION,'mode':'guided','sequential':True,'dossier':True,
            'title':row['title']+' · dossier évolutif','documents':documents,
            'exercises':[_exercise(row['id'],i,e) for i,e in enumerate(authored)]}


def _quiz(row):
    ref=row['ref']; base=_base(ref)
    pool = (previous.previous._injury_questions() if ref=='09.15' else
            [q for q in previous._questions() if ref in q['lesson_refs']])
    offset=(row['ordinal']-1)%len(pool) if pool else 0
    selected=copy.deepcopy((pool[offset:]+pool[:offset])[:3])
    for i,q in enumerate(selected):q['id']=row['id']+f'-q{i}'
    texts=[row['revised'],row['decision']+' Sans réexaminer les conditions après le changement.',
           'Conserver le programme initial et analyser cette information seulement après la mission.']
    shift=row['ordinal']%3
    texts=texts[shift:]+texts[:shift]
    opts=[{'id':chr(97+i),'text':s} for i,s in enumerate(texts)]
    selected.append({'id':row['id']+'-transfert','prompt':row['situation']+' Nouvelle information : '+row['change']+' Quelle réponse retenir ?',
        'options':opts,'answer':next(o['id'] for o in opts if o['text']==row['revised']),
        'explanation':row['teaching']+' '+row['revised']})
    quiz=previous.previous._quiz({**base,'title':row['title']},selected)
    quiz['id']=row['id']+'-quiz';quiz['a3p'].update(delivery='distance',objective=row['objective'])
    return quiz


def _section(row):
    video=copy.deepcopy(media()[row['id']])
    common={'ref':row['ref'],'delivery':'distance','objective':row['objective'],
            'regulatory_objectives':[row['objective']],'objective_id':row['objective_id']}
    def activity(suffix,title,kind,**extra):
        return {'id':row['id']+'-'+suffix,'title':title+' · '+row['title'],'type':'content','scored':False,
                'blocks':[],'a3p':{**common,'kind':kind},**extra}
    film=activity('video','Voir le cas expliqué','video',blocks=[{'id':video['id'],'type':'video','html':'','children':[],'video':video}])
    lesson=activity('cours','Comprendre','lesson');lesson['a3p'].update(pages=_pages(row),source_pages=_base(row['ref'])['source_pages'])
    workshop=activity('atelier','Résoudre le dossier','application',practice=_practice(row))
    recap=activity('retenir','À retenir','recap');recap['a3p']['points']=[row['teaching'],row['revised'],
        'Distinguer le fait confirmé, les informations manquantes, la décision et ses conditions de réévaluation.']
    activities=[film,lesson,workshop,_quiz(row),recap]
    fixed=math.ceil(video['duration_seconds']/60)
    remaining=row['minutes']-fixed-2
    if remaining<12:raise ValueError('Video too long for the authored sequence: '+row['id'])
    # Like APS, reserve actual media duration and allocate the remaining study
    # budget to reading, casework and corrected assessment. No timer is changed.
    reading=max(4,round(remaining*.36));quiz=max(4,round(remaining*.18))
    budgets=[fixed,reading,remaining-reading-quiz,quiz,2]
    for item,budget in zip(activities,budgets):item.update(planned_minutes=budget,duration_estimated=True)
    lesson['a3p']['pacing']=[{'label':a['title'].split(' · ')[0],'minutes':a['planned_minutes']} for a in activities]
    lesson['a3p']['pacing_note']='Repères de travail indicatifs. Seul le temps réellement suivi est enregistré.'
    return {'id':row['id'],'title':row['title'],'delivery':'distance','objective_id':row['objective_id'],
            'planned_minutes':row['minutes'],'dossier_count':1,'activities':activities}


@lru_cache(maxsize=8)
def _course(uv):
    course=previous.previous.load_bundled_course('academy-a3p-'+uv)
    rows=[r for r in programme() if r['uv']==uv]
    sections=[_section(r) for r in rows]
    # Keep existing preparatory resources and the eight supplementary syntheses.
    supplements=[s for s in course['sections'] if s.get('delivery')!='distance']
    for s in supplements:
        for a in s['activities']:a['planned_minutes']=0
    course['sections']=sections+supplements
    activities=[a for s in course['sections'] for a in s['activities']]
    distance=[a for s in sections for a in s['activities']]
    for row in rows:
        course['assets'].extend(media()[row['id']][key] for key in ('src','poster','captions'))
    total=sum(r['minutes'] for r in rows)
    assert total==course['required_minutes']
    course.update(version=VERSION,pedagogy_revision=VERSION,planned_minutes=total,
        activity_order=[a['id'] for a in activities],
        calibration={'status':'planned_curriculum_to_measure','measured':False,'target_minutes':total,
                     'estimated_minutes':total,'gap_minutes':0,
                     'method':'Budget pédagogique par objectif : durée réelle des vidéos, étude du cours, analyse des pièces, classements, associations, décisions, QCM corrigés et synthèse. Répartition à ajuster avec les temps observés ; aucun crédit automatique.'},
        study_plan={'total_minutes':total,'activities_minutes':total,'exam_minutes':0,
                    'steps':[{'id':s['id'],'label':s['title'],'minutes':s['planned_minutes'],'kind':'section'} for s in sections],
                    'calibration_status':'Durées pédagogiques prévues ; mesure apprenant à confirmer'})
    course['source']['sha256']=hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    course['counts'].update(sections=len(course['sections']),activities=len(activities),assets=len(course['assets']),
        scored_activities=sum(a['scored'] for a in activities),required_videos=len(rows),interactive_workshops=len(rows),
        interactive_decisions=sum(len(e.get('rows',[])) or 1 for a in distance for e in a.get('practice',{}).get('exercises',[])))
    return course


def load_bundled_course(course_id,version=None):
    if version in previous.SUPPORTED_VERSIONS:return previous.load_bundled_course(course_id,version)
    if course_id not in curriculum_ids() or version not in (None,VERSION):return None
    return copy.deepcopy(_course(course_id.rsplit('-',1)[1]))


def bundled_asset(course_id,version,name):
    if version in previous.SUPPORTED_VERSIONS:return previous.bundled_asset(course_id,version,name)
    course=load_bundled_course(course_id,version)
    if not course or name not in course['assets']:return None
    root=(ROOT/'assets').resolve();path=(root/name).resolve()
    return path if root in path.parents and path.is_file() else None


def curriculum_manifest():
    result=previous.previous.curriculum_manifest()
    result.update(version=VERSION,lesson_count=160,enriched_lesson_count=160,dossier_count=160,
        application_count=160,video_count=168,required_video_count=160,
        calibration_estimated_minutes=9450,calibration_target_minutes=9450,calibration_gap_minutes=0,
        calibration_status='planned_curriculum_to_measure')
    result['video_minutes']=round(sum(v['duration_seconds'] for v in media().values())/60,1)
    result['interactive_decisions']=sum(_course(uv)['counts']['interactive_decisions'] for uv in MODULES)
    result['question_count']=sum(len(a.get('answer_groups',[])) for uv in MODULES for s in _course(uv)['sections'] if s['delivery']=='distance' for a in s['activities'])
    for module in result['modules']:
        course=_course(module['uv']);sections=[s for s in course['sections'] if s['delivery']=='distance']
        module.update(version=VERSION,lesson_count=len(sections),distance_lesson_count=len(sections),
            estimated_minutes=course['planned_minutes'],calibration_gap_minutes=0,
            video_count=len(sections),video_minutes=round(sum(media()[s['id']]['duration_seconds'] for s in sections)/60,1),
            lessons=[{'ref':s['objective_id'],'title':s['title'],'activity':s['activities'][0]['id'],'delivery':'distance'} for s in sections])
    return result


def load_exam(exam_id,version):
    if version in previous.SUPPORTED_VERSIONS:return previous.load_exam(exam_id,version)
    if version!=VERSION:return None
    exam=previous.load_exam(exam_id,previous.VERSION)
    if exam:exam['version']=VERSION
    return exam
