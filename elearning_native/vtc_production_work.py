"""Persistent VTC written work, with immutable submissions and server-side review.

The existing active-time store remains the sole source of credited training time.
An AI request never awards time or marks an activity complete.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
import uuid

from . import vtc_ai
from .store import _json_dict, _json_list, _utc_iso


class WrittenWorkError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def is_vtc_production(course, activity):
    return (course.get('training_label') == 'VTC'
            and activity.get('vtc', {}).get('kind') == 'production'
            and isinstance(activity.get('production'), dict))


def submission_hash(assignment, answers):
    # Include the trusted rubric so a changed assignment never reuses an old score.
    body = {'assignment': assignment, 'answers': answers}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


class VtcWrittenWork:
    def __init__(self, tracking_store):
        self.tracking = tracking_store
        with self.tracking._connect() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS vtc_written_attempts (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    trainee_id TEXT NOT NULL,
                    course_id TEXT NOT NULL,
                    course_version TEXT NOT NULL,
                    activity_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    answers_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    feedback_json TEXT NOT NULL DEFAULT '{}',
                    created_epoch REAL NOT NULL,
                    updated_epoch REAL NOT NULL,
                    error_code TEXT NOT NULL DEFAULT '',
                    human_review_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS vtc_written_attempts_owner
                ON vtc_written_attempts(session_id, trainee_id, course_id, course_version, activity_id, created_epoch);
            ''')

    def _key(self, access, activity_id):
        return (*self.tracking._key_values(access), str(activity_id))

    @staticmethod
    def _public(row):
        result = dict(row)
        return {'id': result['id'], 'status': result['status'],
                'submitted_at': _utc_iso(result['created_epoch']),
                'answers': _json_dict(result['answers_json']),
                'feedback': _json_dict(result['feedback_json']),
                'human_review': _json_dict(result['human_review_json'])}

    def history(self, access, activity_id, limit=12):
        with self.tracking._connect() as connection:
            rows = connection.execute('''SELECT * FROM vtc_written_attempts
                WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=? AND activity_id=?
                ORDER BY created_epoch DESC LIMIT ?''', (*self._key(access, activity_id), limit)).fetchall()
        return [self._public(row) for row in rows]

    def claim(self, access, activity_id, assignment, answers):
        now = time.time()
        key = self._key(access, activity_id)
        digest = submission_hash(assignment, answers)
        with self.tracking._transaction() as connection:
            latest = connection.execute('''SELECT * FROM vtc_written_attempts
                WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=? AND activity_id=?
                AND content_hash=? ORDER BY created_epoch DESC LIMIT 1''', (*key, digest)).fetchone()
            if latest and latest['status'] in ('corrected', 'needs_human_review', 'trainer_reviewed'):
                return dict(latest), True
            pending = connection.execute('''SELECT id FROM vtc_written_attempts
                WHERE session_id=? AND trainee_id=? AND status='processing' AND updated_epoch>?''',
                (*key[:2], now - 100)).fetchone()
            if pending:
                raise WrittenWorkError('Une correction est déjà en cours. Attendez quelques instants, puis réessayez.', 409)
            last = connection.execute('''SELECT MAX(created_epoch) FROM vtc_written_attempts
                WHERE session_id=? AND trainee_id=?''', key[:2]).fetchone()[0]
            if last and now - last < 8:
                raise WrittenWorkError('Patientez quelques secondes avant une nouvelle correction.', 429)
            count = connection.execute('''SELECT COUNT(*) FROM vtc_written_attempts
                WHERE session_id=? AND trainee_id=? AND created_epoch>?''', (*key[:2], now - 86400)).fetchone()[0]
            if count >= 120:
                raise WrittenWorkError('Le nombre de corrections disponibles pour aujourd’hui est atteint. Vos travaux restent enregistrés.', 429)
            connection.execute('''UPDATE vtc_written_attempts SET status='failed', error_code='interrupted', updated_epoch=?
                WHERE session_id=? AND trainee_id=? AND status='processing' AND updated_epoch<=?''',
                (now, *key[:2], now - 100))
            attempt_id = uuid.uuid4().hex
            connection.execute('''INSERT INTO vtc_written_attempts
                (id,session_id,trainee_id,course_id,course_version,activity_id,content_hash,answers_json,status,created_epoch,updated_epoch)
                VALUES (?,?,?,?,?,?,?,?,'processing',?,?)''',
                (attempt_id, *key, digest, json.dumps(answers, ensure_ascii=False), now, now))
            self.tracking._ensure_progress_row(connection, access, now_iso=_utc_iso(now))
            row = self.tracking._progress_row(connection, access)
            saved = _json_dict(row['answers_json'])
            work = saved.setdefault(activity_id, {})
            work.setdefault('production_first_answers', copy.deepcopy(answers))
            work.setdefault('production_first_submitted_at', _utc_iso(now))
            work['production_ai_attempt'] = attempt_id
            connection.execute('''UPDATE learner_course_progress SET answers_json=?, updated_at=?
                WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?''',
                (json.dumps(saved, ensure_ascii=False), _utc_iso(now), *key[:4]))
            record = connection.execute('SELECT * FROM vtc_written_attempts WHERE id=?', (attempt_id,)).fetchone()
        return dict(record), False

    def finish(self, attempt, feedback=None, error_code=''):
        now = time.time()
        status = ('needs_human_review' if feedback.get('needs_human_review') else 'corrected') if feedback else 'failed'
        with self.tracking._transaction() as connection:
            connection.execute('''UPDATE vtc_written_attempts SET status=?,feedback_json=?,error_code=?,updated_epoch=?
                WHERE id=? AND status='processing' ''',
                (status, json.dumps(feedback or {}, ensure_ascii=False), error_code, now, attempt['id']))

    def attach_feedback(self, access, activity_id, assignment, answers, attempt_id, feedback):
        """Do not overwrite text typed in another tab while the provider was running."""
        now = _utc_iso()
        with self.tracking._transaction() as connection:
            row = self.tracking._progress_row(connection, access)
            if activity_id in _json_list(row['completed_json']):
                return False
            saved = _json_dict(row['answers_json'])
            work = saved.get(activity_id, {})
            if work.get('production_answers') != answers:
                return False
            work.update(production_ai_feedback=copy.deepcopy(feedback),
                        production_ai_answers=copy.deepcopy(answers),
                        production_ai_hash=submission_hash(assignment, answers),
                        production_ai_attempt=attempt_id, production_feedback_seen=True,
                        needs_trainer_help=bool(feedback.get('needs_human_review')))
            connection.execute('''UPDATE learner_course_progress SET answers_json=?,updated_at=?
                WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?''',
                (json.dumps(saved, ensure_ascii=False), now, *self.tracking._key_values(access)))
            self.tracking._event(connection, access, 'vtc_written_corrected', activity_id=activity_id,
                at=now, details={'attempt_id': attempt_id, 'needs_human_review': bool(feedback.get('needs_human_review'))})
        return True

    def submit(self, access, course, activity, payload, current):
        assignment = activity['production']
        activity_id = activity['id']
        stage = payload.get('stage')
        if stage not in ('draft', 'compare', 'correct', 'history'):
            raise WrittenWorkError('Étape inconnue.')
        if stage == 'history':
            return {'ok': True, 'history': self.history(access, activity_id)}
        if activity_id in current.get('completed_activity_ids', []):
            if stage == 'draft':
                return {'ok': True, 'already_completed': True}
            raise WrittenWorkError('Cette production est déjà terminée. Sa correction reste consultable.', 409)
        try:
            answers = vtc_ai.normalize_answers(assignment, payload.get('production_answers'), draft=stage == 'draft')
        except ValueError as exc:
            raise WrittenWorkError(str(exc)) from exc
        self.tracking.record_production(access, activity_id, answers)
        if stage == 'draft':
            return {'ok': True, 'saved': True}
        attempt, cached = self.claim(access, activity_id, assignment, answers)
        if cached:
            feedback = _json_dict(attempt['feedback_json'])
        else:
            try:
                feedback = vtc_ai.grade_written_work(assignment, answers)
            except vtc_ai.VtcAIError as exc:
                self.finish(attempt, error_code=str(exc.code))
                raise
            except Exception:
                self.finish(attempt, error_code='correction_unavailable')
                raise WrittenWorkError('La correction est momentanément indisponible. Votre copie est enregistrée ; vous pouvez réessayer.', 503)
            self.finish(attempt, feedback)
        attached = self.attach_feedback(access, activity_id, assignment, answers, attempt['id'], feedback)
        return {'ok': True, 'feedback': feedback, 'attempt_id': attempt['id'], 'cached': cached,
                'current_copy': attached, 'history': self.history(access, activity_id)}

    def completion_answer(self, access, activity, payload, current):
        activity_id = activity['id']
        existing = current.get('answers', {}).get(activity_id, {})
        if activity_id in current.get('completed_activity_ids', []):
            return existing
        try:
            answers = vtc_ai.normalize_answers(activity['production'], payload.get('production_answers'))
        except ValueError as exc:
            raise WrittenWorkError(str(exc)) from exc
        if payload.get('production_reviewed') is not True:
            raise WrittenWorkError('Lisez la correction et confirmez que vous avez pris connaissance des conseils.')
        digest = submission_hash(activity['production'], answers)
        with self.tracking._connect() as connection:
            row = connection.execute('''SELECT * FROM vtc_written_attempts
                WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=? AND activity_id=?
                AND content_hash=? AND status IN ('corrected','trainer_reviewed')
                ORDER BY updated_epoch DESC LIMIT 1''', (*self._key(access, activity_id), digest)).fetchone()
        if not row:
            raise WrittenWorkError('Faites corriger cette version de votre travail avant de continuer. Une copie signalée doit être revue par le formateur.')
        feedback = _json_dict(row['feedback_json'])
        if row['status'] != 'trainer_reviewed' and float(feedback.get('score') or 0) < float(activity['production'].get('pass_points') or 12):
            raise WrittenWorkError('Reprenez votre réponse avec les conseils de correction pour atteindre l’objectif de 12/20 avant de continuer.')
        if answers != existing.get('production_answers'):
            raise WrittenWorkError('Votre brouillon a changé. Enregistrez et faites corriger la copie actuelle avant de continuer.', 409)
        return {**existing, 'production_answers': answers, 'production_draft': False,
                'production_ai_feedback': feedback, 'production_ai_hash': digest,
                'production_ai_attempt': row['id'], 'production_feedback_seen': True,
                'production_reviewed': True, 'review_status': 'trainer_reviewed' if row['status'] == 'trainer_reviewed' else 'ai_feedback_read',
                'needs_trainer_help': False, 'submitted_at': _utc_iso()}

    def trainer_review(self, attempt_id, *, comment, reviewer, outcome, allowed_owners=None):
        comment = str(comment or '').strip()
        if outcome not in ('reviewed', 'revise') or not 20 <= len(comment) <= 6000:
            raise WrittenWorkError('Indiquez une décision et un retour pédagogique de 20 à 6 000 caractères.')
        now = _utc_iso()
        with self.tracking._transaction() as connection:
            attempt = connection.execute('SELECT * FROM vtc_written_attempts WHERE id=?', (attempt_id,)).fetchone()
            if not attempt or (allowed_owners is not None and (attempt['session_id'], attempt['trainee_id']) not in allowed_owners):
                raise WrittenWorkError('Production introuvable.', 404)
            if attempt['status'] == 'processing':
                raise WrittenWorkError('Attendez la fin de la correction avant de relire cette copie.', 409)
            access = {key: attempt[key] for key in ('session_id','trainee_id','course_id','course_version')}
            feedback = _json_dict(attempt['feedback_json'])
            review = {'comment': comment, 'reviewer': str(reviewer), 'reviewed_at': now, 'outcome': outcome}
            feedback.update(trainer_review=review, needs_human_review=outcome != 'reviewed',
                            status='trainer_reviewed' if outcome == 'reviewed' else 'needs_human_review')
            connection.execute('''UPDATE vtc_written_attempts SET status=?,feedback_json=?,human_review_json=?,updated_epoch=? WHERE id=?''',
                (feedback['status'], json.dumps(feedback, ensure_ascii=False), json.dumps(review, ensure_ascii=False), time.time(), attempt_id))
            row = self.tracking._progress_row(connection, access)
            saved = _json_dict(row['answers_json'])
            work = saved.get(attempt['activity_id'], {})
            if (attempt['activity_id'] not in _json_list(row['completed_json'])
                    and work.get('production_answers') == _json_dict(attempt['answers_json'])):
                work.update(production_ai_feedback=feedback, production_ai_attempt=attempt_id,
                            production_ai_answers=_json_dict(attempt['answers_json']),
                            production_ai_hash=attempt['content_hash'], production_feedback_seen=True,
                            needs_trainer_help=outcome != 'reviewed')
                connection.execute('''UPDATE learner_course_progress SET answers_json=?, updated_at=?
                    WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?''',
                    (json.dumps(saved, ensure_ascii=False), now, *self.tracking._key_values(access)))
            self.tracking._event(connection, access, 'vtc_written_trainer_review', activity_id=attempt['activity_id'],
                                 at=now, details={'attempt_id': attempt_id, 'outcome': outcome, 'reviewer': str(reviewer)})
        return feedback
