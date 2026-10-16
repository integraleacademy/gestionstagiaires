"""APS authored productions: collect work and self-review, never infer mastery."""
from __future__ import annotations

import copy


def public_production(production, *, reveal=False):
    result = {key: copy.deepcopy(production[key]) for key in (
        'id', 'title', 'brief', 'documents', 'response_fields', 'audio', 'map',
        'estimated_minutes', 'oral_prompt', 'instructions',
    ) if key in production}
    if reveal:
        result['feedback'] = production_feedback(production)
    return result


def production_feedback(production):
    return {key: copy.deepcopy(production.get(key, {} if key == 'model_response' else []))
            for key in ('rubric', 'model_response')}


def normalize_production(production, answers, *, draft=False):
    fields = production['response_fields']
    expected = {field['id'] for field in fields}
    if not isinstance(answers, dict) or not set(answers).issubset(expected):
        raise ValueError('La production contient des champs inconnus.')
    if not draft and set(answers) != expected:
        raise ValueError('Complétez chaque partie du travail avant de comparer.')
    normalized = {}
    for field in fields:
        value = answers.get(field['id'], '')
        if not isinstance(value, str):
            raise ValueError('Chaque réponse doit être un texte.')
        value = value.strip()
        maximum = min(int(field.get('max_chars', 3000)), 6000)
        minimum = int(field.get('min_chars', 20)) if field.get('required', True) else 0
        if len(value) > maximum:
            raise ValueError(f'« {field["label"]} » : {maximum} caractères maximum.')
        if not draft and len(value) < minimum:
            raise ValueError(f'Complétez « {field["label"]} » ({minimum} caractères minimum).')
        normalized[field['id']] = value
    if sum(map(len, normalized.values())) > 24000:
        raise ValueError('Votre production est trop longue.')
    return normalized


def normalize_self_review(production, supplied, *, draft=False):
    expected = {row['id'] for row in production['rubric']}
    if (not isinstance(supplied, dict) or set(supplied) != expected
            or any(value not in (('checked', 'needs_help', '') if draft else ('checked', 'needs_help')) for value in supplied.values())):
        raise ValueError('Indiquez pour chaque critère si vous avez vérifié votre travail ou souhaitez de l’aide.')
    return copy.deepcopy(supplied)
