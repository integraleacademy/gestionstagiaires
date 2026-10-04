"""Versioned practice exams, server-side marking and independent attempt history.

Training attempts never modify course completion, video progress or active time.
"""
from __future__ import annotations
import copy
from contextlib import contextmanager
import datetime as dt
import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from .academy import ROOT, curriculum_manifest


@lru_cache(maxsize=64)
def _load(exam_id, version):
    if not re.fullmatch(r'(?:module-\d{2}|final)', exam_id):
        return None
    if version not in curriculum_manifest().get('exam_versions', []):
        return None
    path = ROOT / 'exams' / version / (exam_id + '.json')
    return json.loads(path.read_text()) if path.is_file() else None


def load_exam(exam_id, version):
    return copy.deepcopy(_load(exam_id, version))


def public_exam(exam):
    """Explicit allowlist: never serialize keys, rationales or source hints."""
    return {key: exam[key] for key in ('id', 'version', 'title', 'pass_percent')} | {
        'questions': [{key: q[key] for key in ('id', 'prompt', 'options')} for q in exam['questions']]
    }


def grade_exam(exam, answers):
    questions = exam['questions']
    if not isinstance(answers, dict) or set(answers) != {q['id'] for q in questions}:
        raise ValueError('Répondez à toutes les questions avant de corriger votre examen.')
    corrections = []
    for q in questions:
        selected = answers[q['id']]
        if not isinstance(selected, str) or selected not in {o['id'] for o in q['options']}:
            raise ValueError('Une réponse n’est pas valide. Rechargez l’examen.')
        corrections.append({'id': q['id'], 'prompt': q['prompt'], 'options': q['options'],
                            'selected': selected, 'answer': q['answer'], 'correct': selected == q['answer'],
                            'explanation': q['explanation'], 'module': q['module'], 'sources': q['sources']})
    score = sum(q['correct'] for q in corrections)
    percent = round(score / len(questions) * 100, 1)
    return {'score': score, 'total': len(questions), 'percent': percent,
            'passed': percent >= exam['pass_percent'], 'pass_percent': exam['pass_percent'],
            'corrections': corrections}


class ExamStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS aps_exam_attempts (
                session_id TEXT NOT NULL, trainee_id TEXT NOT NULL,
                exam_id TEXT NOT NULL, version TEXT NOT NULL, attempt_id TEXT NOT NULL,
                submitted_at TEXT NOT NULL, result_json TEXT NOT NULL,
                PRIMARY KEY(session_id, trainee_id, exam_id, version, attempt_id))''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, session_id, trainee_id, exam, attempt_id, result):
        if not isinstance(attempt_id, str) or not re.fullmatch(r'[a-f0-9]{32}', attempt_id):
            raise ValueError('Identifiant de tentative invalide. Rechargez l’examen.')
        key = (str(session_id), str(trainee_id), exam['id'], exam['version'], attempt_id)
        date = dt.datetime.now(dt.timezone.utc).isoformat()
        with self.connect() as db:
            # INSERT OR IGNORE makes network retries idempotent across processes.
            db.execute('INSERT OR IGNORE INTO aps_exam_attempts VALUES (?,?,?,?,?,?,?)',
                       (*key, date, json.dumps(result, ensure_ascii=False)))
            row = db.execute('''SELECT submitted_at, result_json FROM aps_exam_attempts
                WHERE session_id=? AND trainee_id=? AND exam_id=? AND version=? AND attempt_id=?''', key).fetchone()
        return json.loads(row['result_json']) | {'submitted_at': row['submitted_at'], 'attempt_id': attempt_id}

    def history(self, session_id, trainee_id, exam):
        with self.connect() as db:
            rows = db.execute('''SELECT attempt_id, submitted_at, result_json FROM aps_exam_attempts
                WHERE session_id=? AND trainee_id=? AND exam_id=? AND version=? ORDER BY submitted_at DESC LIMIT 50''',
                (str(session_id), str(trainee_id), exam['id'], exam['version'])).fetchall()
        return [{'attempt_id': r['attempt_id'], 'submitted_at': r['submitted_at'],
                 **{k: json.loads(r['result_json'])[k] for k in ('score','total','percent','passed')}} for r in rows]
