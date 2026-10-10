"""A3P: structured lessons and a distance path scoped to the ministerial order."""
from __future__ import annotations
import copy
import html
import json
import re
from functools import lru_cache
from . import a3p_v1 as legacy

ROOT = legacy.ROOT
VERSION = '20261010-a3p-v2'
MODULES = legacy.MODULES
NOTICE = ('Parcours fondé sur les annexes II et XI de l’arrêté du 1er septembre 2025. '
          'Les objectifs marqués OUI constituent le parcours à distance ; les autres ressources '
          'préparent les séances présentielles et ne les remplacent pas.')
_manual = legacy._manual
_questions = legacy._questions
_video = legacy._video
curriculum_ids = legacy.curriculum_ids

# Explicit lesson scope: never count the theoretical part of a NON row as OUI.
DISTANCE = {
    '02': list(range(1, 11)), '03': list(range(1, 7)), '04': list(range(1, 7)),
    '05': [1, 2, 3, 4, 7],
    '06': [*range(1, 12), 16, 21, 22, 23, 24, 25, 26],
    '07': [5, 6, 7, 8], '08': list(range(4, 11)), '09': [],
}


def _mode(ref):
    if ref == '09.15':
        return 'distance'
    if ref[:2] == '06' and int(ref[3:]) >= 27:
        return 'complement'
    return 'distance' if int(ref[3:]) in DISTANCE[ref[:2]] else 'presentiel'


@lru_cache(maxsize=1)
def _review():
    return json.loads((ROOT / 'regulatory_review.json').read_text(encoding='utf-8'))


def _rows(ref):
    return [r for r in _review()['eligible_objectives'] if ref in r['lesson_refs']]


def _minutes(uv):
    return sum(r['minimum_minutes'] for r in _review()['eligible_objectives'] if r['delivery_module'] == uv)


def _recap(lesson):
    paragraphs = [c['text'] for p in lesson['pages'] for c in p['components'] if c['kind'] == 'paragraph']
    points = []
    for page in lesson['pages']:
        candidates = [c['text'] for c in page['components'] if c['kind'] == 'paragraph']
        if candidates:
            value = candidates[-1]
            if value not in points and value != lesson['objective']:
                points.append(value)
    return points[-3:] or paragraphs[-1:]


def _application(lesson):
    """Use the manual's actual worked example, preserving source and full meaning."""
    for page in lesson['pages']:
        for index, item in enumerate(page['components']):
            if item['kind'] == 'heading' and item['text'] == 'UN EXEMPLE':
                paragraphs = []
                for component in page['components'][index + 1:]:
                    if component['kind'] == 'heading':
                        break
                    if component['kind'] == 'paragraph':
                        paragraphs.append(component['text'])
                if paragraphs:
                    # The complete scenario stays visible, including qualifications.
                    return {'paragraphs': paragraphs, 'page': page['page']}
    page = lesson['pages'][-1]
    return {'paragraphs': [c['text'] for c in page['components'] if c['kind'] == 'paragraph'][-2:], 'page': page['page']}


def _quiz(lesson, questions):
    prefix = 'a3p-' + lesson['ref'].replace('.', '-')
    fields, groups = [], []
    for number, q in enumerate(questions, 1):
        opts = ''.join('<option value="%s">%s</option>' % (o['id'], html.escape(o['text'])) for o in q['options'])
        fields.append('<p><strong>%s. %s</strong></p><p><select class="native-elearning-blank" data-group-id="%s" aria-label="%s"><option value="">Choisissez une réponse…</option>%s</select></p>' % (number, html.escape(q['prompt']), q['id'], html.escape(q['prompt'], quote=True), opts))
        groups.append({'id': q['id'], 'mode': 'choice', 'answers': [{**o, 'is_correct': o['id'] == q['answer']} for o in q['options']]})
    return {'id': prefix + '-quiz', 'title': 'QCM · ' + lesson['title'], 'type': 'question',
            'question_type': 'fill_blank', 'scored': True, 'prompt': 'Choisissez une réponse à chaque question, puis validez le questionnaire.',
            'prompt_html': ''.join(fields), 'answer_groups': groups,
            'a3p': {'kind': 'quiz', 'ref': lesson['ref'], 'question_count': len(questions)},
            'explanation': '\n\n'.join(str(i) + '. ' + q['explanation'] for i, q in enumerate(questions, 1))}


def _injuries_lesson():
    return {
        'ref': '09.15', 'title': 'Reconnaître les blessures spécifiques',
        'objective': 'Identifier les familles de blessures et les informations à transmettre, sans pratiquer de geste invasif.',
        'source_pages': [],
        'pages': [{'page': 'XI', 'kind': 'COURS DÉTAILLÉ', 'components': [
            {'kind': 'heading', 'text': 'OBSERVER SANS POSER DE DIAGNOSTIC'},
            {'kind': 'paragraph', 'text': 'L’objectif de cette séquence est la reconnaissance des blessures prévue à l’annexe XI (30 minutes, réalisable à distance). La mise en œuvre des gestes, le matériel et les scénarios pratiques de secours tactique se travaillent en présentiel. Une observation ne remplace ni le bilan d’un professionnel de santé ni les consignes des secours.'},
            {'kind': 'table', 'rows': [
                ['Famille de blessures', 'Informations utiles à transmettre'],
                ['Hémorragie', 'Localisation, saignement visible et évolution observée.'],
                ['Détresse respiratoire', 'Difficulté à respirer, conscience et changement constaté.'],
                ['Plaie par projectile ou arme blanche', 'Localisation visible et circonstances connues, sans explorer la plaie.'],
                ['Explosion', 'Exposition au souffle, projections, brûlures et plaintes exprimées.'],
                ['Brûlure', 'Cause présumée, localisation et étendue visible.'],
                ['Fracture suspectée', 'Zone douloureuse, mécanisme connu et impossibilité de mouvement rapportée.'],
                ['Hypothermie', 'Exposition au froid, vêtements mouillés et évolution de l’état de la personne.']]},
            {'kind': 'heading', 'text': 'NE PAS AGGRAVER LA SITUATION'},
            {'kind': 'paragraph', 'text': 'Ne pas entrer dans une zone dangereuse pour examiner une victime. Ne pas retirer un objet fiché, explorer une plaie, tenter une réduction de fracture ou effectuer un geste invasif hors de ses compétences. Protéger, alerter et suivre les instructions des services de secours. Les soins et déplacements de victimes s’apprennent avec un formateur dans le cadre adapté.'},
            {'kind': 'heading', 'text': 'TRANSMETTRE DES FAITS'},
            {'kind': 'paragraph', 'text': 'Indiquer le lieu et l’accès, le danger encore présent, le nombre de victimes et les signes observables. Distinguer ce qui est vu, ce que la victime dit et ce qui reste inconnu. Informer les secours de toute évolution. Éviter un diagnostic affirmatif fondé sur la seule apparence.'},
        ]}],
    }


def _injury_questions():
    rows = [
        ('Après une explosion, que transmettez-vous aux secours ?', 'Les circonstances connues et les signes observables.', 'Un diagnostic certain de toutes les lésions.', 'Seulement le nom de la victime.', 'Les observations et circonstances guident les secours ; des lésions peuvent ne pas être visibles.'),
        ('Un objet est fiché dans une plaie : quelle limite faut-il reconnaître ?', 'Ne pas le retirer ; alerter et suivre les consignes des secours.', 'Le retirer pour inspecter la profondeur.', 'Explorer la plaie avec le matériel disponible.', 'Cette séquence porte sur la reconnaissance. Retirer un objet fiché ou explorer la plaie peut aggraver la situation.'),
        ('Quel élément doit être distingué dans la transmission ?', 'Les faits vus, les propos de la victime et les inconnues.', 'Le diagnostic supposé et le nom du client uniquement.', 'Les avis des témoins sans vérification.', 'Un bilan utile distingue l’observation directe, les déclarations et les informations non confirmées.'),
    ]
    return [{'id': 'a3p-theorie-blessures-' + str(i), 'prompt': row[0], 'options': [{'id': chr(97+j), 'text': row[j+1]} for j in range(3)], 'answer': 'a', 'explanation': row[4]} for i, row in enumerate(rows, 1)]


def _section(lesson):
    ref = lesson['ref']; prefix = 'a3p-' + ref.replace('.', '-')
    questions = [q for q in _questions() if ref in q['lesson_refs']] if ref != '09.15' else _injury_questions()
    mode = _mode(ref)
    common = {'ref': ref, 'delivery': mode, 'objective': lesson['objective'],
              'regulatory_objectives': [r['objective'] for r in _rows(ref)]}
    def content(suffix, title, kind, **payload):
        return {'id': prefix + '-' + suffix, 'title': title + ' · ' + lesson['title'],
                'type': 'content', 'scored': False, 'blocks': [], 'a3p': {**common, 'kind': kind, **payload}}
    quiz = _quiz(lesson, questions)
    quiz['a3p'].update(common)
    return {'id': prefix, 'title': ref + ' · ' + lesson['title'], 'delivery': mode,
            'activities': [
                content('cours', 'Comprendre', 'lesson', pages=lesson['pages'], source_pages=lesson['source_pages']),
                content('application', 'Appliquer', 'application', example=_application(lesson), points=_recap(lesson)),
                quiz,
                content('retenir', 'À retenir', 'recap', points=_recap(lesson)),
            ]}


@lru_cache(maxsize=8)
def _course(uv):
    title, objective, flow = MODULES[uv]
    lessons = [l for l in _manual()['lessons'] if l['ref'].startswith(uv + '.')]
    if uv == '09':
        lessons = [_injuries_lesson(), *lessons]
    sections = [_section(l) for l in lessons]
    video = _video(uv); assets = []
    if video:
        video = {**video, 'required': False}
        assets = [video[k] for k in ('src', 'poster', 'captions')]
        # The synthesis also covers practical preparation: supplementary, never
        # included in the distance time requirement or mandatory learner path.
        sections.append({'id': 'a3p-' + uv + '-video', 'title': 'Synthèse vidéo · ' + title, 'delivery': 'complement',
                         'activities': [{'id': 'a3p-' + uv + '-video', 'title': 'Le module en vidéo · ' + title,
                            'type': 'content', 'scored': False, 'a3p': {'kind': 'video', 'delivery': 'complement'},
                            'blocks': [{'id': video['id'], 'type': 'video', 'html': '', 'children': [], 'video': video}]}]})
    case = json.loads((ROOT / 'cases.json').read_text(encoding='utf-8'))[uv]
    sections.append({'id': 'a3p-' + uv + '-atelier', 'title': 'Cas de synthèse · ' + title, 'delivery': 'complement',
                     'activities': [{'id': 'a3p-' + uv + '-cas', 'title': case['title'], 'type': 'content', 'scored': False,
                        'blocks': [], 'a3p': {'kind': 'case', 'case': case, 'flow': flow, 'delivery': 'complement'}}]})
    activities = [a for s in sections for a in s['activities']]
    return {'id': 'academy-a3p-' + uv, 'version': VERSION, 'format_version': 1,
            'title': 'A3P · UV ' + uv + ' · ' + title, 'training_label': 'A3P', 'preview_only': False,
            'required_minutes': _minutes(uv), 'planned_minutes': _minutes(uv),
            'description': objective, 'source': {'type': 'academy-a3p', 'sha256': _manual()['source']['text_sha256']},
            'mock_exam_id': 'a3p-module-' + uv, 'assets': assets, 'import_warnings': [],
            'regulation': {'scope': 'distance', 'reference': 'Arrêté du 1er septembre 2025 · annexes II et XI',
                           'objectives': [r for r in _review()['eligible_objectives'] if r['delivery_module'] == uv]},
            'theme': {'main_color': '#135846', 'button_color': '#135846', 'text_color': '#172f29'},
            'settings': {'mastery_score': 80, 'require_correct_answers': True, 'force_navigation': True}, 'introduction': [],
            'sections': sections, 'activity_order': [a['id'] for a in activities],
            'counts': {'sections': len(sections), 'activities': len(activities), 'scored_activities': sum(a['scored'] for a in activities), 'assets': len(assets), 'required_videos': 0}}


def load_bundled_course(course_id, version=None):
    if version == legacy.VERSION:
        return legacy.load_bundled_course(course_id, version)
    if course_id not in curriculum_ids() or version not in (None, VERSION):
        return None
    return copy.deepcopy(_course(course_id.rsplit('-', 1)[1]))


def bundled_asset(course_id, version, name):
    if version == legacy.VERSION:
        return legacy.bundled_asset(course_id, version, name)
    course = load_bundled_course(course_id, version)
    if course is None or name not in course['assets']:
        return None
    root = (ROOT / 'assets').resolve(); path = (root / name).resolve()
    return path if root in path.parents and path.is_file() else None


def curriculum_manifest():
    modules = []
    for uv, (title, objective, flow) in MODULES.items():
        course = _course(uv)
        lessons = [s for s in course['sections'] if s['activities'][0].get('a3p', {}).get('kind') == 'lesson']
        modules.append({'id': course['id'], 'uv': uv, 'title': title, 'objective': objective, 'flow': flow,
            'version': VERSION, 'planned_minutes': _minutes(uv), 'lesson_count': len(lessons),
            'distance_lesson_count': sum(s['delivery'] == 'distance' for s in lessons),
            'video_minutes': round((_video(uv) or {}).get('duration_seconds', 0)/60, 1),
            'lessons': [{'ref': s['activities'][0]['a3p']['ref'], 'title': s['title'].split(' · ', 1)[1], 'activity': s['activities'][0]['id'], 'delivery': s['delivery']} for s in lessons],
            'question_count': sum(q['module'] == 'UV ' + uv for q in _questions()), 'exam_id': 'a3p-module-' + uv})
    return {'version': VERSION, 'training_label': 'A3P', 'preview_only': False, 'notice': NOTICE,
            'modules': modules, 'lesson_count': 95, 'question_count': 245, 'reading_page_count': 337,
            'case_count': 8, 'application_count': 95, 'video_count': sum(bool(_video(uv)) for uv in MODULES),
            'video_minutes': round(sum((_video(uv) or {}).get('duration_seconds', 0) for uv in MODULES)/60, 1),
            'final_exam_id': 'a3p-final', 'regulatory_review': copy.deepcopy(_review())}


def load_exam(exam_id, version):
    if version == legacy.VERSION:
        return legacy.load_exam(exam_id, version)
    if version != VERSION:
        return None
    exam = legacy.load_exam(exam_id, legacy.VERSION)
    if exam:
        exam['version'] = VERSION
        exam['notice'] = 'Examen blanc : seuil pédagogique de 80 %. Il ne valide pas les gestes ni les séquences présentielles.'
    return exam
