"""Source-referenced VTC past papers, independent of course completion.

Answer keys and teaching notes stay on the server until an attempt is submitted.
Historical/ambiguous questions remain available to study, never in the score.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent / 'vtc' / 'annales'


@lru_cache(maxsize=1)
def _sources():
    sources = []
    for path in sorted(ROOT.glob('*.json')):
        raw = path.read_bytes()
        source = json.loads(raw)
        source['version'] = 'annales-v1-' + hashlib.sha256(raw).hexdigest()[:16]
        for section in source['sections']:
            section.update(version=source['version'], source_id=source['id'],
                           source_title=source['title'], source_filename=source['source_filename'],
                           year=source['year'], source_note=source.get('source_note', ''))
            section['pass_percent'] = 80
            for q in section['questions']:
                q['module'] = section['module']
        sources.append(source)
    return sources


def sources():
    return copy.deepcopy(_sources())


def load_section(section_id):
    return next((copy.deepcopy(s) for doc in _sources() for s in doc['sections']
                 if s['id'] == section_id), None)


def lesson_notes(ref):
    if not re.fullmatch(r'[A-H]\.\d{2}', ref):
        return []
    notes = []
    for source in _sources():
        for section in source['sections']:
            for q in section['questions']:
                if ref in q['lesson_refs']:
                    notes.append({k: copy.deepcopy(q.get(k)) for k in
                                  ('id', 'prompt', 'learning_points', 'sources', 'status', 'update_note', 'page')}
                                 | {'source_title': source['title'], 'section_id': section['id'], 'number': q['number']})
    return notes


def public_section(section):
    result = {k: section.get(k) for k in ('id', 'version', 'title', 'module', 'year', 'minutes',
                                         'source_title', 'source_filename', 'source_note', 'pass_percent')}
    result['questions'] = []
    for q in section['questions']:
        result['questions'].append({k: copy.deepcopy(q[k]) for k in
                                    ('id', 'number', 'page', 'prompt', 'options', 'original_kind', 'kind',
                                     'context', 'image', 'adaptation_note', 'status') if k in q})
    result['scored_count'] = sum(q['status'] == 'active' for q in section['questions'])
    return result


def grade(section, answers):
    if not isinstance(answers, dict):
        raise ValueError('Les réponses envoyées sont invalides.')
    questions = section['questions']
    expected_ids = {q['id'] for q in questions if q['status'] == 'active'}
    if set(answers) != expected_ids:
        raise ValueError('Répondez à chaque question évaluée avant de demander la correction.')
    corrections = []
    for q in questions:
        selected = answers.get(q['id'], [])
        if q['status'] == 'active':
            if (not isinstance(selected, list) or not selected or
                any(not isinstance(x, str) for x in selected) or len(set(selected)) != len(selected) or
                not set(selected) <= {o['id'] for o in q['options']} or
                (q['kind'] == 'single' and len(selected) != 1)):
                raise ValueError('Une réponse est invalide. Vérifiez vos choix.')
        correct = set(selected) == set(q['answers']) if q['status'] == 'active' else None
        corrections.append(copy.deepcopy(q) | {'selected': selected, 'correct': correct})
    total = len(expected_ids)
    score = sum(q['correct'] is True for q in corrections)
    percent = round(100 * score / total, 1) if total else 0
    return {'score': score, 'total': total, 'percent': percent,
            'passed': bool(total and percent >= section['pass_percent']),
            'pass_percent': section['pass_percent'], 'historical_count': len(questions) - total,
            'corrections': corrections}


def validate_bank():
    """Fail closed on incomplete imports before publication."""
    seen = set()
    for source in _sources():
        if not source.get('source_sha256') or not source.get('source_filename'):
            raise ValueError('Source PDF non référencée')
        for section in source['sections']:
            if section['module'] not in 'ABCDEFG' or not section['questions']:
                raise ValueError('Matière ou sujet invalide')
            for q in section['questions']:
                if q['id'] in seen:
                    raise ValueError('Question dupliquée : ' + q['id'])
                seen.add(q['id'])
                options = {o['id'] for o in q['options']}
                if (len(options) != len(q['options']) or not set(q['answers']) <= options or
                    len(set(q['answers'])) != len(q['answers']) or
                    q['kind'] not in ('single', 'multiple') or
                    (q['kind'] == 'single' and len(q['answers']) != 1)):
                    raise ValueError('Clé de correction invalide : ' + q['id'])
                if q.get('image'):
                    image_root = (ROOT.parent / 'assets' / 'media' / 'vtc' / 'annales').resolve()
                    image = (ROOT.parent / 'assets' / q['image']).resolve()
                    if (not q['image'].startswith('media/vtc/annales/') or
                        image_root not in image.parents or not image.is_file() or
                        image.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp')):
                        raise ValueError('Illustration du sujet invalide : ' + q['id'])
                if q['status'] == 'active' and (not q['answers'] or len(options) < 2):
                    raise ValueError('Question évaluée sans correction : ' + q['id'])
                if q['status'] not in ('active', 'historical') or q['correction_origin'] not in ('source', 'pedagogical'):
                    raise ValueError('Provenance/statut invalide : ' + q['id'])
                if (not q['explanation'] or not q['learning_points'] or not q['lesson_refs'] or
                    any(not re.fullmatch(r'[A-H]\.\d{2}', r) for r in q['lesson_refs'])):
                    raise ValueError('Couverture pédagogique incomplète : ' + q['id'])
                if q['status'] == 'historical' and not q.get('update_note'):
                    raise ValueError('Question historique non expliquée : ' + q['id'])
                if q['original_kind'] == 'qrc' and not q.get('adaptation_note'):
                    raise ValueError('Adaptation non signalée : ' + q['id'])
    return len(seen)
