"""Append-only assessment evidence, distinct from eventual course completion."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any, Mapping


def _key(access):
    values = tuple(str(access.get(name) or '').strip() for name in
                   ('session_id', 'trainee_id', 'course_id', 'course_version'))
    if not all(values):
        raise ValueError('Contexte apprenant incomplet.')
    return values


def ensure_schema(connection):
    columns = {row['name'] for row in connection.execute('PRAGMA table_info(learner_course_progress)')}
    if 'assessment_diagnostics_json' not in columns:
        connection.execute("ALTER TABLE learner_course_progress ADD COLUMN assessment_diagnostics_json TEXT NOT NULL DEFAULT '{}'")
    connection.execute('''CREATE TABLE IF NOT EXISTS learner_assessment_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL, trainee_id TEXT NOT NULL,
        course_id TEXT NOT NULL, course_version TEXT NOT NULL,
        activity_id TEXT NOT NULL, item_id TEXT NOT NULL, kind TEXT NOT NULL,
        attempt_number INTEGER NOT NULL, request_id TEXT NOT NULL,
        answer_json TEXT NOT NULL, correct INTEGER NOT NULL,
        submitted_at TEXT NOT NULL, competency TEXT NOT NULL DEFAULT '',
        revision TEXT NOT NULL DEFAULT '',
        UNIQUE(session_id, trainee_id, course_id, course_version, activity_id, item_id, kind, request_id),
        UNIQUE(session_id, trainee_id, course_id, course_version, activity_id, item_id, kind, attempt_number)
    )''')
    connection.execute('''CREATE INDEX IF NOT EXISTS learner_assessment_history_idx
        ON learner_assessment_attempts(session_id, trainee_id, course_id, course_version, id)''')


def _decode(raw, fallback):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def _serialize(row):
    return {name: row[name] for name in ('id', 'activity_id', 'item_id', 'kind',
            'attempt_number', 'submitted_at', 'competency', 'revision')} | {
            'answer': _decode(row['answer_json'], {}), 'correct': bool(row['correct'])}


def record_attempt(connection, access, *, activity_id, item_id, kind, answer,
                   correct, submitted_at, request_id='', competency='', revision=''):
    """Called inside the store's write transaction, before disclosing correction.

    Explicit request IDs make a lost HTTP response safe to retry. Legacy clients
    without IDs deduplicate consecutive identical submissions. A new explicit
    check is an attempt even if the learner chose the same answer again.
    """
    if kind not in ('question', 'practice') or type(correct) is not bool:
        raise ValueError('Résultat pédagogique invalide.')
    if request_id and (not isinstance(request_id, str) or
                       not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', request_id)):
        raise ValueError('Identifiant de réponse invalide.')
    key = _key(access)
    progress = connection.execute('''SELECT completed_json, assessment_diagnostics_json
        FROM learner_course_progress WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?''', key).fetchone()
    if progress is None:
        raise ValueError('Progression apprenant introuvable.')
    if activity_id in _decode(progress['completed_json'], []):
        return None  # Never rewrite completed work through a late/replayed request.
    encoded = json.dumps(answer, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded) > 48000:
        raise ValueError('Réponse trop longue.')
    scope = (*key, str(activity_id), str(item_id), kind)
    where = 'session_id=? AND trainee_id=? AND course_id=? AND course_version=? AND activity_id=? AND item_id=? AND kind=?'
    previous = connection.execute('SELECT * FROM learner_assessment_attempts WHERE '+where+
                                  ' ORDER BY attempt_number DESC LIMIT 1', scope).fetchone()
    if request_id:
        receipt = connection.execute('SELECT * FROM learner_assessment_attempts WHERE '+where+' AND request_id=?',
                                     (*scope, request_id)).fetchone()
        if receipt is not None:
            if receipt['answer_json'] != encoded or bool(receipt['correct']) != correct or receipt['revision'] != str(revision):
                raise ValueError('Cette réponse a déjà été reçue avec un autre contenu. Réessayez avec une nouvelle réponse.')
            return _serialize(receipt)
    elif previous is not None and previous['answer_json'] == encoded and bool(previous['correct']) == correct and previous['revision'] == str(revision):
        return _serialize(previous)
    number = previous['attempt_number'] + 1 if previous is not None else 1
    cursor = connection.execute('''INSERT INTO learner_assessment_attempts (
        session_id, trainee_id, course_id, course_version, activity_id, item_id, kind,
        attempt_number, request_id, answer_json, correct, submitted_at, competency, revision
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (*scope, number, request_id or uuid.uuid4().hex, encoded, int(correct), submitted_at, str(competency)[:500], str(revision)[:128]))
    diagnostics = _decode(progress['assessment_diagnostics_json'], {})
    bucket = diagnostics.setdefault(kind, {})
    if kind == 'practice':
        bucket = bucket.setdefault(str(activity_id), {})
    diagnostic_key = str(item_id) if kind == 'practice' else str(activity_id)
    detail = bucket.setdefault(diagnostic_key, {
        'attempts': 0, 'incorrect_attempts': 0, 'first_correct': correct,
        'first_answer': answer, 'first_submitted_at': submitted_at,
    })
    detail.update(attempts=number, incorrect_attempts=detail['incorrect_attempts'] + int(not correct),
                  last_correct=correct, last_answer=answer, last_submitted_at=submitted_at,
                  competency=str(competency)[:500], revision=str(revision)[:128])
    connection.execute('''UPDATE learner_course_progress SET assessment_diagnostics_json=?, updated_at=?
        WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?''',
        (json.dumps(diagnostics, ensure_ascii=False, separators=(',', ':')), submitted_at, *key))
    return {'id': cursor.lastrowid, 'activity_id': str(activity_id), 'item_id': str(item_id), 'kind': kind,
            'attempt_number': number, 'answer': answer, 'correct': correct, 'submitted_at': submitted_at,
            'competency': str(competency)[:500], 'revision': str(revision)[:128]}


def _summary(items):
    count = len(items)
    correct = sum(item.get('first_correct') is True for item in items)
    return {'assessed_items': count, 'first_attempt_correct': correct,
            'first_attempt_score_percent': round(correct * 100 / count, 2) if count else None,
            'attempt_count': sum(int(item.get('attempts') or 0) for item in items),
            'incorrect_attempt_count': sum(int(item.get('incorrect_attempts') or 0) for item in items),
            'items_to_review': sum(item.get('first_correct') is False for item in items)}


def summary_for(diagnostics):
    """Keep scored questions comparable with score_percent; workshops separate."""
    questions = list((diagnostics.get('question') or {}).values())
    practice = [item for group in (diagnostics.get('practice') or {}).values() for item in group.values()]
    result = _summary(questions)
    result['practice'] = _summary(practice)
    result['total_attempt_count'] = result['attempt_count'] + result['practice']['attempt_count']
    return result


def history_for(connection: sqlite3.Connection, access: Mapping[str, Any], *, activity_id=None):
    where = 'session_id=? AND trainee_id=? AND course_id=? AND course_version=?'
    params = _key(access)
    if activity_id is not None:
        where += ' AND activity_id=?'
        params += (str(activity_id),)
    return [_serialize(row) for row in connection.execute(
        'SELECT * FROM learner_assessment_attempts WHERE '+where+' ORDER BY id ASC', params).fetchall()]


def describe_history(course, records):
    """Resolve recorded choice IDs against the pinned, authored course version."""
    import html
    def plain(value):
        return html.unescape(re.sub(r'<[^>]+>', '', str(value or ''))).strip()
    activities = {item['id']: (section, item) for section in course.get('sections', [])
                  for item in section.get('activities', [])}
    result = []
    for record in records:
        section, activity = activities.get(record['activity_id'], ({}, {}))
        source = activity
        supplied = record['answer']
        if record['kind'] == 'practice':
            source = next((item for item in activity.get('practice', {}).get('exercises', [])
                           if item['id'] == record['item_id']), {})
        options = {str(item['id']): plain(item.get('text') or item.get('html')) for item in source.get('options', [])}
        if record['kind'] == 'question' and source.get('question_type') == 'matching':
            pairs = source.get('pairs', [])
            rights = {str(item['id']): plain(item.get('right')) for item in pairs}
            answer_text = '\n'.join(plain(pair.get('left'))+' → '+rights.get(str(choice), str(choice))
                                    for pair, choice in zip(pairs, supplied.get('selected', [])))
        elif record['kind'] == 'question' and isinstance(supplied, dict) and 'selected' in supplied:
            answer_text = '\n'.join(options.get(str(item), str(item)) for item in supplied['selected'])
        elif record['kind'] == 'question' and isinstance(supplied, dict) and 'groups' in supplied:
            groups = {str(item['id']): item for item in source.get('answer_groups', [])}
            lines = []
            for key, value in supplied['groups'].items():
                choices = {str(item['id']): plain(item.get('text')) for item in groups.get(key, {}).get('answers', [])}
                lines.append(choices.get(str(value), str(value)))
            answer_text = '\n'.join(lines)
        elif isinstance(supplied, dict):
            rows = {str(item['id']): plain(item.get('text')) for item in source.get('rows', [])}
            answer_text = '\n'.join(rows.get(str(key), str(key))+' → '+options.get(str(value), str(value))
                                    for key, value in supplied.items())
        else:
            answer_text = options.get(str(supplied), str(supplied))
        result.append({**record, 'dossier': plain(section.get('title')),
                       'title': plain(source.get('prompt') or source.get('title') or record['item_id']),
                       'answer_text': answer_text, 'explanation': plain(source.get('explanation'))})
    return result
