"""A3P enriched edition. Historical editions and earned progress remain immutable."""
from __future__ import annotations
import copy
import hashlib
import json
import math
from functools import lru_cache
from . import a3p_v1 as legacy
from . import a3p_v2 as previous

ROOT = previous.ROOT
VERSION = '20261015-a3p-v3-contenus'
SUPPORTED_VERSIONS = (legacy.VERSION, previous.VERSION, VERSION)
MODULES = previous.MODULES
NOTICE = previous.NOTICE
_manual = previous._manual
_questions = previous._questions
_video = previous._video
_review = previous._review
_rows = previous._rows
_minutes = previous._minutes
_mode = previous._mode
DISTANCE = previous.DISTANCE
curriculum_ids = previous.curriculum_ids


@lru_cache(maxsize=1)
def _bank():
    return json.loads((ROOT / 'enrichment_v3.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _extensions():
    return json.loads((ROOT / 'extensions_v3.json').read_text(encoding='utf-8'))


def _pages(ref, dossiers):
    result = []
    for n, dossier in enumerate(dossiers, 1):
        for i, part in enumerate(dossier['teaching'], 1):
            result.append({'page': f'v3-{ref.replace(".", "-")}-{n}-{i}',
                'kind': 'APPROFONDISSEMENT', 'source_label': 'Cours enrichi · Intégrale Academy',
                'components': [{'kind': 'heading', 'text': part['title']},
                               {'kind': 'paragraph', 'text': part['text']}]})
    return result


def _practice(ref, dossiers):
    exercises = []
    for di, dossier in enumerate(dossiers):
        context = '\n\n'.join(doc['title'] + ' — ' + doc['text'] for doc in dossier['documents'])
        for qi, question in enumerate(dossier['decisions']):
            texts = [question['correct'], *question['alternatives']]
            shift = (int(ref.replace('.', '')) + di + qi) % len(texts)
            texts = texts[shift:] + texts[:shift]
            opts = [{'id': chr(97 + index), 'text': text} for index, text in enumerate(texts)]
            exercises.append({'id': f'a3p-{ref.replace(".", "-")}-d{di+1}-q{qi+1}',
                'kind': 'single', 'stage': f'Dossier {di+1} · {dossier["title"]}',
                'context': context, 'prompt': question['prompt'], 'options': opts,
                'answer': next(opt['id'] for opt in opts if opt['text'] == question['correct']),
                'explanation': question['explanation']})
    return {'revision': VERSION, 'mode': 'guided', 'sequential': True,
            'dossier': False, 'title': 'Décider à partir des pièces du dossier',
            'documents': [], 'exercises': exercises}


def _word_count(value):
    if isinstance(value, list):
        return sum(_word_count(v) for v in value)
    if isinstance(value, dict):
        return sum(_word_count(v) for k, v in value.items() if k in ('text', 'rows', 'components'))
    return len(str(value).split()) if value is not None else 0


def _estimate(lesson, dossiers, quiz):
    """Transparent editorial study estimates; never scale them to legal minima.

    Study pace 60 wpm for course text; documents 90 wpm, 2 minutes per
    decision and 1 minute per correction; quiz 2 minutes/item, recap 5 minutes.
    These are hypotheses for learner trials, not observed learning durations.
    """
    text_words = _word_count(lesson['a3p']['pages'])
    doc_words = sum(len(doc['text'].split()) for d in dossiers for doc in d['documents'])
    decisions = sum(len(d['decisions']) for d in dossiers)
    reading = max(5, math.ceil(text_words / 60))
    analysis = max(5, math.ceil(doc_words / 90) + 3 * decisions)
    assessment = max(4, 2 * len(quiz['answer_groups']))
    return [reading, analysis, assessment, 5]


@lru_cache(maxsize=8)
def _course(uv):
    course = previous.load_bundled_course('academy-a3p-' + uv)
    course['version'] = VERSION
    course['pedagogy_revision'] = VERSION
    course['calibration'] = {'status': 'provisional_content_estimate',
        'method': 'Hypothèses de travail : étude du cours à 60 mots/min, lecture des pièces à 90 mots/min, 2 min par décision puis 1 min de correction, 2 min par question de QCM et 5 min de synthèse. À mesurer auprès des apprenants.',
        'measured': False, 'target_minutes': course['required_minutes']}
    actual = []
    for section in course['sections']:
        if section.get('delivery') != 'distance':
            continue
        activities = section['activities']
        ref = activities[0]['a3p']['ref']
        dossiers = [_bank()[ref], *_extensions().get(ref, [])]
        activities[0]['a3p']['pages'].extend(_pages(ref, dossiers))
        activities[0]['a3p']['editorial_revision'] = VERSION
        activities[0]['a3p']['dossier_count'] = len(dossiers)
        activities[1]['practice'] = _practice(ref, dossiers)
        activities[1]['title'] = 'Dossiers interactifs · ' + section['title'].split(' · ', 1)[1]
        activities[1]['a3p']['editorial_revision'] = VERSION
        activities[3]['a3p']['points'] = [q['explanation'] for q in dossiers[0]['decisions']]
        minutes = _estimate(activities[0], dossiers, activities[2])
        section['planned_minutes'] = sum(minutes)
        section['calibration_status'] = 'estimate_to_test'
        section['dossier_count'] = len(dossiers)
        for activity, budget in zip(activities, minutes):
            activity['planned_minutes'] = budget
            activity['duration_estimated'] = True
        actual.extend(activities)
    planned = sum(a['planned_minutes'] for a in actual)
    course['planned_minutes'] = planned
    course['calibration']['estimated_minutes'] = planned
    course['calibration']['gap_minutes'] = max(0, course['required_minutes'] - planned)
    course['counts']['interactive_workshops'] = sum(bool(a.get('practice')) for a in actual)
    course['counts']['interactive_decisions'] = sum(len(a.get('practice', {}).get('exercises', [])) for a in actual)
    raw = json.dumps({'source': previous._manual()['source'], 'content': _bank(), 'extensions': _extensions()}, ensure_ascii=False, sort_keys=True)
    course['source']['sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    return course


def load_bundled_course(course_id, version=None):
    if version in (legacy.VERSION, previous.VERSION):
        return previous.load_bundled_course(course_id, version)
    if course_id not in curriculum_ids() or version not in (None, VERSION):
        return None
    return copy.deepcopy(_course(course_id.rsplit('-', 1)[1]))


def bundled_asset(course_id, version, name):
    if version in (legacy.VERSION, previous.VERSION):
        return previous.bundled_asset(course_id, version, name)
    course = load_bundled_course(course_id, version)
    if course is None or name not in course['assets']:
        return None
    root = (ROOT / 'assets').resolve()
    path = (root / name).resolve()
    return path if root in path.parents and path.is_file() else None


def curriculum_manifest():
    manifest = previous.curriculum_manifest()
    manifest['version'] = VERSION
    manifest['enriched_lesson_count'] = len(_bank())
    manifest['dossier_count'] = len(_bank()) + sum(map(len, _extensions().values()))
    manifest['interactive_decisions'] = sum(_course(uv)['counts']['interactive_decisions'] for uv in MODULES)
    manifest['calibration_estimated_minutes'] = sum(_course(uv)['planned_minutes'] for uv in MODULES)
    manifest['calibration_target_minutes'] = sum(_course(uv)['required_minutes'] for uv in MODULES)
    manifest['calibration_gap_minutes'] = sum(_course(uv)['calibration']['gap_minutes'] for uv in MODULES)
    manifest['calibration_status'] = 'provisional_content_estimate'
    for module in manifest['modules']:
        course = _course(module['uv'])
        module['version'] = VERSION
        module['estimated_minutes'] = course['planned_minutes']
        module['calibration_gap_minutes'] = course['calibration']['gap_minutes']
        module['interactive_decisions'] = course['counts']['interactive_decisions']
    return manifest


def load_exam(exam_id, version):
    if version in (legacy.VERSION, previous.VERSION):
        return previous.load_exam(exam_id, version)
    if version != VERSION:
        return None
    exam = previous.load_exam(exam_id, previous.VERSION)
    if exam:
        exam['version'] = VERSION
    return exam
