"""Reproducible APS edition: authored cases, click-only practice and crosswalk.

Run from the repository root. Previous editions/assets are never rewritten.
The hour allocation is a pedagogical target, not a measured learner duration.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import random
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from elearning_native.practice import adapt_course  # noqa: E402

ROOT = REPO / 'elearning_native/aps62'
SOURCE = REPO / 'scripts/aps62_v3'
OLD = '20261004-aps62-v2'
VERSION = '20261006-aps62-v3'
PACE = [('Comprendre et comparer', 16), ('Mémoriser', 4),
        ('Mission en cinq décisions', 12), ('Vérifier les repères', 6),
        ('Transférer', 6), ('Analyser les documents', 8),
        ('Composer la main courante', 6), ('Retenir', 2)]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def single(seed, ident, prompt, correct, wrong, explanation, context=''):
    texts = [correct, *wrong]
    random.Random(seed + ':' + ident).shuffle(texts)
    options = [{'id': str(i + 1), 'text': text} for i, text in enumerate(texts)]
    return dict(id=ident, kind='single', prompt=prompt, context=context,
                options=options, answer=next(o['id'] for o in options if o['text'] == correct),
                explanation=explanation)


def review(s, skill):
    ident, title, case, fact, action, bad, why, evolution, action2, bad2, why2, anomaly, instruction, newcase, newaction, newbad = s
    data = {
        'decision': ('Quelle décision retenir ?', newaction, [newbad,
            'Reporter toute décision et toute alerte jusqu’à la prochaine relève.'], why),
        'fact': ('Quel statut donner à cette information dans le compte rendu ?',
            'Décrire les faits du nouveau cas avec leur source, sans ajouter une intention supposée.',
            ['Présenter une intention malveillante comme certaine sans élément supplémentaire.',
             'Ne conserver aucune trace tant que toutes les causes ne sont pas connues.'],
            'Une observation, une déclaration et une interprétation ne sont pas interchangeables.'),
        'document': ('Quelle consigne complémentaire écarter dans ce nouveau cas ?',
            newbad, [newaction, 'Vérifier la version et le champ de la consigne auprès de l’interlocuteur habilité.'],
            'Une instruction doit être compatible avec les faits et le cadre de la mission.'),
        'journal': ('Quelle suite inscrire sans inventer un résultat ?',
            'La vérification ou le relais prévu : ' + newaction,
            ['Dossier définitivement clos sans vérification ni confirmation.',
             'Responsabilité juridique établie par l’agent, sans autre procédure.'],
            'La main courante indique les démarches et leur état réel, sans conclusion fabriquée.'),
        'time': ('Le fait est signalé à 11 h 06, puis saisi à 11 h 12. Quelle entrée est fidèle ?',
            'Événement signalé à 11 h 06 ; saisie à 11 h 12 ; origine de l’information précisée.',
            ['Événement à 11 h 12, puisque l’application l’a enregistré à cette heure.',
             'Saisie à 11 h 06, en modifiant l’historique pour faire coïncider les heures.'],
            'Distinguer heure de l’événement et heure de saisie préserve la chronologie.'),
    }
    prompt, correct, wrong, lesson = data[skill]
    ex = single(ident, 'revision-' + skill, newcase + ' ' + prompt, correct, wrong,
                lesson + ' Dans ce cas : ' + newaction)
    return {k: ex[k] for k in ('prompt', 'options', 'answer', 'explanation')} | {'lesson': lesson}


def attach_review(exercises, s, skills):
    for ex, skill in zip(exercises, skills):
        ex['remediation'] = review(s, skill)
    return exercises


def mission(s):
    ident, title, case, fact, action, bad, why, evolution, action2, bad2, why2, anomaly, instruction, *_ = s
    exercises = [
        single(ident, 'constat', '1. Sur quel fait fonder votre analyse ?', fact,
               ['Le récit prouve à lui seul une intention malveillante de toutes les personnes concernées.',
                'Aucun fait ne mérite une vérification tant qu’aucun dommage n’est visible.'],
               'Le point de départ établi est : ' + fact + ' Il ne faut pas compléter ce constat par une supposition.', case),
        single(ident, 'decision', '2. Quelle première décision prenez-vous ?', action,
               [bad, 'Attendre la fin de la vacation sans transmettre la situation à un interlocuteur.'], why,
               'Le poste doit maintenant choisir une action à partir du constat.'),
        single(ident, 'evolution', '3. Une nouvelle information arrive. Que décidez-vous ?', action2,
               [bad2, 'Garder la première décision sans examiner l’information nouvelle.'], why2, evolution),
        single(ident, 'consigne', '4. Quel document doit être écarté ou clarifié avant application ?', anomaly,
               [instruction, 'Trame validée : identifier les faits, les mesures prises et les interlocuteurs avisés.'],
               why + ' La note incompatible est : ' + anomaly,
               'Deux documents sont transmis au poste. Comparez-les avec la situation et la règle.'),
        single(ident, 'releve', '5. Quelle transmission permet une relève fiable ?',
               'Transmettre le constat, l’évolution, les mesures réellement prises et ce qui reste à vérifier.',
               ['Transmettre seulement la première décision, sans l’évolution reçue ensuite.',
                'Annoncer que toutes les vérifications sont terminées pour simplifier la relève.'],
               'Le relais doit connaître les faits nouveaux et les limites de l’information. ' + why2,
               'Le collègue de relève arrive. Il n’a assisté à aucune des étapes précédentes.'),
    ]
    for ex in exercises:
        ex['branches'] = {o['id']: ('Ce choix permet de poursuivre sur une base vérifiable. Examinez maintenant la suite.'
            if o['id'] == ex['answer'] else
            'Ce choix crée une difficulté : ' + ex['explanation'] + ' Réexaminez-le avant de poursuivre.') for o in ex['options']}
    return dict(revision=VERSION, title=title + ' · cinq décisions successives', sequential=True,
                exercises=attach_review(exercises, s, ['fact', 'decision', 'decision', 'document', 'journal']))


def documents(s):
    ident, title, case, fact, action, bad, why, evolution, action2, bad2, why2, anomaly, instruction, *_ = s
    docs = [
        dict(title='A · Fiche d’événement ' + ident, text=case,
             rows=[['09 h 02 · constat au poste', fact], ['09 h 04 · action enregistrée par l’agent', action],
                   ['09 h 07 · nouvelle information reçue', evolution],
                   ['09 h 10 · état du suivi', 'Réévaluation engagée ; issue finale non confirmée.']]),
        dict(title='B · Consigne validée pour l’exercice', text=instruction,
             rows=[['Statut', 'Version validée par le responsable pédagogique pour ce cas fictif.'],
                   ['Traçabilité', 'Distinguer les faits, les sources, les horaires, les actions et les suites.']]),
        dict(title='C · Brouillon reçu, à contrôler', text=anomaly,
             rows=[['09 h 12 · heure de saisie', 'Entrée saisie au retour au poste.'],
                   ['Heure d’événement indiquée dans le brouillon', '09 h 12'],
                   ['Conclusion proposée', 'Toutes les vérifications sont achevées ; aucune suite nécessaire.']]),
    ]
    exercises = [
        single(ident, 'anomalie', 'Quelle phrase du document C pose un problème de fond ?', anomaly,
               [instruction, 'L’entrée a été saisie à 09 h 12.'], why),
        single(ident, 'horodatage', 'Quelle anomalie chronologique faut-il corriger ?',
               'Le brouillon utilise l’heure de saisie 09 h 12 comme heure de l’événement signalé à 09 h 02.',
               ['Le délai entre constat et saisie prouve que l’événement n’a pas eu lieu.',
                'L’heure de la nouvelle information doit remplacer toutes les autres heures.'],
               'La pièce A distingue le constat à 09 h 02, l’action à 09 h 04 et l’évolution à 09 h 07. La saisie à 09 h 12 n’efface pas cette chronologie.'),
        single(ident, 'cloture', 'Quelle conclusion est réellement étayée par la pièce A ?',
               'La réévaluation est engagée et l’issue finale n’est pas confirmée.',
               ['Tout est définitivement résolu puisque le brouillon l’affirme.',
                'Aucune action n’a été engagée avant la saisie.'],
               'La dernière ligne de A décrit un suivi en cours. La conclusion de C n’est pas étayée.'),
        dict(id='statut', kind='sort', prompt='Attribuez un statut à chaque élément du dossier.',
             options=[{'id': 'fait', 'text': 'Fait ou action enregistré dans A'},
                      {'id': 'regle', 'text': 'Instruction validée dans B'},
                      {'id': 'ecart', 'text': 'Affirmation du brouillon C à corriger'}],
             rows=[{'id': 'r1', 'text': fact, 'answer': 'fait'},
                   {'id': 'r2', 'text': instruction, 'answer': 'regle'},
                   {'id': 'r3', 'text': anomaly, 'answer': 'ecart'},
                   {'id': 'r4', 'text': 'Action à 09 h 04 : ' + action, 'answer': 'fait'},
                   {'id': 'r5', 'text': 'Toutes les vérifications sont achevées.', 'answer': 'ecart'}],
             explanation='Le document d’origine et le statut de l’information comptent autant que sa formulation. A constate, B prescrit, C contient des erreurs.'),
        single(ident, 'correction', 'Comment corriger ce brouillon avant une transmission autorisée ?',
               'Rectifier les horaires, écarter la note incompatible, garder le suivi en cours et tracer la validation.',
               ['Changer seulement le titre du document, sans contrôler les trois écarts.',
                'Supprimer la fiche A pour ne conserver qu’un récit cohérent avec C.'],
               'La correction doit résoudre les écarts de fond, de chronologie et de statut, sans détruire les sources.'),
    ]
    return dict(revision=VERSION, title='Croiser trois pièces et rechercher les anomalies', documents=docs,
                exercises=attach_review(exercises, s, ['document', 'time', 'journal', 'fact', 'document']))


def journal(s, docs):
    ident, title, case, fact, action, bad, why, evolution, action2, bad2, why2, *_ = s
    entries = [
        ('heure', 'Heures de l’événement et de la saisie', 'Constat : 09 h 02 ; action : 09 h 04 ; évolution : 09 h 07 ; saisie : 09 h 12.',
         ['Événement et saisie : 09 h 12 ; aucune autre heure utile.', 'Événement à 09 h 04 ; saisie antidatée à 09 h 02.'],
         'La pièce A et le brouillon donnent des heures de nature différente. Conservez chacune avec sa fonction.', 'time'),
        ('source', 'Origine des informations', 'Constat et action consignés dans A ; nouvelle information reçue à 09 h 07 ; consigne B identifiée.',
         ['Tous les éléments ont été personnellement observés au même moment.', 'Informations certaines, sans source à conserver.'],
         'Ne transformez pas une information reçue en observation personnelle.', 'fact'),
        ('fait', 'Constat initial', fact,
         ['Intention malveillante certaine des personnes concernées.', 'Aucun fait précis à conserver dans le registre.'],
         'La formulation fidèle n’ajoute ni intention ni qualification définitive. ' + fact, 'fact'),
        ('action', 'Action réellement enregistrée à 09 h 04', action,
         [bad, 'Aucune action effectuée avant la saisie.'],
         'La pièce A enregistre cette action à 09 h 04. ' + why, 'decision'),
        ('evolution', 'Évolution à transmettre', evolution,
         ['Situation inchangée depuis le constat initial.', 'Issue définitivement confirmée à 09 h 07 sans autre démarche.'],
         'Cette nouvelle information modifie l’analyse. ' + why2, 'decision'),
        ('suite', 'État du suivi et prochaine décision', 'Réévaluation engagée, issue non confirmée. Décision à mettre en œuvre : ' + action2,
         ['Dossier clos ; aucune vérification ni transmission complémentaire.', 'Résultat juridique définitif établi par le poste.'],
         'Distinguez ce qui est fait, ce qui est décidé et ce qui reste à confirmer.', 'journal'),
    ]
    exercises = [single(ident, key, prompt, answer, wrong, why) for key, prompt, answer, wrong, why, skill in entries]
    return dict(revision=VERSION, title='Composer une main courante fiable, sans rédaction', journal=True,
                documents=copy.deepcopy(docs[:2]) + [dict(title='Moment de la saisie',
                    text='Il est 09 h 12 lorsque vous composez cette entrée. L’heure de saisie ne remplace pas les heures de la fiche A.')],
                exercises=attach_review(exercises, s, [e[-1] for e in entries]))


def transfer(s, previous, lesson):
    """Retain the authored transfer, remove the two duplicated exam-bank questions."""
    practice = copy.deepcopy(previous)
    variant = practice['exercises'][0]
    example = lesson.get('extra_case') or {'case': lesson['case'], 'model': lesson['decision'] + ' ' + lesson['reason']}
    seed = s[0]
    exercises = [variant,
        single(seed, 'contre_exemple', 'Comparez avec ce cas de référence : quelle conduite lui correspond ?', example['model'],
               [s[5], 'Appliquer la même réponse quels que soient les faits et les interlocuteurs.'],
               example['model'], example['case']),
        single(seed, 'methode', 'Que faut-il comparer avant de transposer la solution du premier cas ?',
               'Les faits, le périmètre, les autorisations, le danger et les relais effectivement disponibles.',
               ['Seulement le nom du site et l’heure de la vacation.',
                'Uniquement la première impression laissée par la personne concernée.'],
               'Un même principe peut conduire à des actions différentes lorsque les conditions changent. ' + example['model']),
    ]
    return dict(revision=VERSION, title='Transférer le raisonnement et comparer les contextes',
                exercises=attach_review(exercises, s, ['decision', 'decision', 'fact']))


def build():
    specs = {r[0]: r for line in (SOURCE / 'scenarios.txt').read_text().splitlines()
             if line and not line.startswith('#') for r in [line.split('|')]}
    assert len(specs) == 62 and all(len(r) == 16 for r in specs.values())
    deepening = {}
    for line in (SOURCE / 'repères.txt').read_text().splitlines():
        if line and not line.startswith('#'):
            module, title, paragraphs = line.split('|')
            deepening.setdefault(module, []).append(dict(title=title, paragraphs=paragraphs.split('~')))
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    for item in manifest['modules']:
        course = adapt_course(json.loads((ROOT / 'courses' / item['id'] / (OLD + '.json')).read_text()))
        course['version'] = course['interaction_revision'] = VERSION
        course['source']['reviewed_on'] = '2026-10-06'
        course['settings']['require_correct_answers'] = True
        for index, section in enumerate(course['sections']):
            s = specs[section['id'].removeprefix('aps62-')]
            section['title'] = section['title'].replace('Simulation écrite', 'Simulation interactive')
            acts = section['activities']
            lesson = acts[0]['academy']
            lesson['edition'] = '2026-10-06'
            lesson['pacing'] = [dict(label=label, minutes=minutes) for label, minutes in PACE]
            lesson['deepening'] = (copy.deepcopy(deepening[item['number']]) if index == 0 else []) + [
                dict(title='Comparer deux moments de la décision', paragraphs=[
                    'Dans le nouveau dossier « ' + s[1] + ' », le point de départ est le suivant : ' + s[2],
                    'Le fait établi est : ' + s[3] + ' La première réponse à examiner est : ' + s[4] + ' ' + s[6],
                    'La situation évolue : ' + s[7] + ' La décision doit donc être réexaminée : ' + s[8] + ' ' + s[10],
                    'Comparez les deux moments avant de lancer la mission. Le document à contrôler contient cet écart : ' + s[11] + ' La référence vérifiée est : ' + s[12]]),
            ]
            acts[0]['planned_minutes'], acts[1]['planned_minutes'] = 16, 4
            acts[2]['planned_minutes'], acts[2]['title'], acts[2]['practice'] = 12, 'Mission · ' + s[1], mission(s)
            acts[2]['academy'] = dict(kind='workshop', dossier=lesson['dossier'], title=s[1], case=s[2], edition='2026-10-06')
            acts[3]['planned_minutes'] = acts[4]['planned_minutes'] = 3
            acts[5]['planned_minutes'] = 6
            acts[5]['practice'] = transfer(s, acts[5]['practice'], lesson)
            acts[5]['title'] = 'Transférer · comparer de nouvelles situations'
            document_practice = documents(s)
            additions = []
            for suffix, title, minutes, practice in [
                ('documents', 'Documents · repérer les anomalies', 8, document_practice),
                ('journal', 'Main courante · composer une entrée', 6, journal(s, document_practice['documents']))]:
                additions.append(dict(id=section['id'] + '-' + suffix, title=title, type='content', scored=False,
                    planned_minutes=minutes, blocks=[], practice=practice,
                    academy=dict(kind=suffix, dossier=lesson['dossier'], title=s[1],
                        case='Dossier fictif « ' + s[1] + ' ». Comparez les pièces et justifiez mentalement chaque choix.', edition='2026-10-06')))
            section['activities'] = acts[:6] + additions + acts[6:]
            assert sum(a['planned_minutes'] for a in section['activities']) == 60
        all_activities = [a for sec in course['sections'] for a in sec['activities']]
        course['activity_order'] = [a['id'] for a in all_activities]
        course['counts'].update(activities=len(all_activities), workbooks=0,
            interactive_workshops=sum('practice' in a for a in all_activities))
        write(ROOT / 'courses' / course['id'] / (VERSION + '.json'), course)
        item['previous_versions'] = list(dict.fromkeys([*item.get('previous_versions', []), OLD]))
        item.update(version=VERSION, activities=len(all_activities))
    for path in (ROOT / 'exams' / OLD).glob('*.json'):
        exam = json.loads(path.read_text())
        exam['version'] = VERSION
        write(ROOT / 'exams' / VERSION / path.name, exam)
    manifest.update(version=VERSION, interaction_revision=VERSION, activity_count=558,
        workbook_count=0, interactive_workshop_count=248,
        enrichment=dict(missions=62, document_analyses=62, journals=62,
            new_review_situations=62, decision_steps=310, authored_on='2026-10-06',
            timing_status='Objectif de travail guidé à éprouver avec des apprenants ; aucun temps réel garanti.'))
    manifest['exam_versions'] = list(dict.fromkeys([*manifest.get('exam_versions', []), VERSION]))
    manifest['enrichment']['source_sha256'] = hashlib.sha256(
        (SOURCE / 'scenarios.txt').read_bytes() + (SOURCE / 'repères.txt').read_bytes()).hexdigest()
    write(ROOT / 'manifest.json', manifest)
    print(f'{VERSION}: 15 modules, 62 dossiers, 558 activités, 248 ateliers.')


if __name__ == '__main__':
    build()
