"""Written VTC work is durable; only server corrections can release completion."""
import copy
import json
from unittest.mock import patch

import pytest

from elearning_native.store import NativeElearningStore, TrackingError
from elearning_native.vtc_ai import CORRECTION_REVISION, VtcAIError
from elearning_native.vtc_production_work import VtcWrittenWork, WrittenWorkError


ASSIGNMENT = {
    'id': 'vtc-a-production-01', 'title': 'Préparer une prise en charge',
    'brief': 'Répondez au client puis décrivez les contrôles avant la course.',
    'instructions': 'Utilisez exclusivement les données fictives du dossier.',
    'estimated_minutes': 25, 'pass_points': 12, 'max_points': 20,
    'response_fields': [
        {'id': 'message', 'label': 'Message client', 'min_chars': 20, 'max_chars': 800},
        {'id': 'checks', 'label': 'Contrôles', 'min_chars': 20, 'max_chars': 800},
    ],
    'rubric': [
        {'id': 'client', 'label': 'Informer le client', 'max_points': 10, 'expected': 'Confirmer le lieu et l’heure.', 'field_ids': ['message'], 'partial_guidance': 'Créditer les éléments exacts.'},
        {'id': 'booking', 'label': 'Vérifier la réservation', 'max_points': 10, 'expected': 'Vérifier une réservation préalable.', 'field_ids': ['checks'], 'partial_guidance': 'Créditer les éléments exacts.'},
    ],
    'model_response': {'message': 'MODÈLE PRIVÉ : rendez-vous à 9 h au point convenu.', 'checks': 'MODÈLE PRIVÉ : vérifier la réservation avant prise en charge.'},
}
ANSWERS = {'message': 'Bonjour, je vous retrouve à 9 h au point de prise en charge convenu.',
           'checks': 'Je vérifie la réservation préalable, les documents et les coordonnées de prise en charge.'}
ACTIVITY = {'id': ASSIGNMENT['id'], 'production': ASSIGNMENT, 'vtc': {'kind': 'production'}}
FEEDBACK = {'status': 'corrected', 'provider': 'openai', 'model': 'test-provider', 'score': 18, 'max_score': 20,
            'percent': 90, 'needs_human_review': False, 'summary': 'Le message est précis et les contrôles sont pertinents.',
            'human_review_reasons': [],
            'criteria': [{'id': 'client', 'label': 'Informer le client', 'points': 9, 'max_points': 10, 'status': 'partial'},
                         {'id': 'booking', 'label': 'Vérifier la réservation', 'points': 9, 'max_points': 10, 'status': 'partial'}], 'errors': [], 'next_steps': ['Précisez le numéro de réservation.'], 'model_response': ASSIGNMENT['model_response']}


@pytest.fixture
def work(tmp_path):
    store = NativeElearningStore(tmp_path / 'tracking.sqlite3')
    access = {'session_id': 'session-vtc', 'trainee_id': 'alice', 'course_id': 'academy-vtc-a', 'course_version': 'test-version'}
    return VtcWrittenWork(store), access


def current(work, access):
    return work.tracking.get_progress(access, activity_order=[ACTIVITY['id']], scored_activity_ids=[])


def submit(work, access, answers=ANSWERS):
    return work.submit(access, {}, ACTIVITY, {'stage': 'correct', 'production_answers': answers}, current(work, access))


def test_first_copy_and_identical_retry_are_durable_without_duplicate_api_or_time(work):
    service, access = work
    with patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK) as api:
        first = submit(service, access)
        repeated = submit(service, access)
    assert api.call_count == 1
    assert repeated['cached'] and repeated['attempt_id'] == first['attempt_id']
    progress = current(service, access)
    assert progress['active_seconds'] == 0
    assert progress['completed_activity_ids'] == []
    saved = progress['answers'][ACTIVITY['id']]
    assert saved['production_first_answers'] == ANSWERS
    assert saved['production_ai_feedback']['score'] == 18
    assert len(VtcWrittenWork(service.tracking).history(access, ACTIVITY['id'])) == 1


def test_failure_saves_original_copy_without_fake_grade_and_retry_can_succeed(work):
    service, access = work
    with patch('elearning_native.vtc_ai.grade_written_work', side_effect=VtcAIError('timeout')):
        with pytest.raises(VtcAIError):
            submit(service, access)
    saved = current(service, access)['answers'][ACTIVITY['id']]
    assert saved['production_first_answers'] == ANSWERS
    assert 'production_ai_feedback' not in saved
    assert service.history(access, ACTIVITY['id'])[0]['status'] == 'failed'
    with patch('elearning_native.vtc_production_work.time.time', return_value=2_000_000_000), patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK):
        assert submit(service, access)['ok']


def replace_legacy_feedback(service, access, attempt_id, feedback, *, completed=False):
    """Reconstruct an immutable legacy record; new graders may not emit it."""
    with service.tracking._transaction() as db:
        db.execute('UPDATE vtc_written_attempts SET status=?,feedback_json=?,human_review_json=? WHERE id=?',
                   (feedback['status'], json.dumps(feedback), json.dumps(feedback.get('trainer_review', {})), attempt_id))
        row = service.tracking._progress_row(db, access)
        saved = json.loads(row['answers_json'])
        activity_id = db.execute('SELECT activity_id FROM vtc_written_attempts WHERE id=?', (attempt_id,)).fetchone()[0]
        answer = saved[activity_id]
        answer.update(production_ai_feedback=copy.deepcopy(feedback), needs_trainer_help=bool(feedback.get('needs_human_review')))
        completed_ids = json.loads(row['completed_json'])
        if completed:
            completed_ids.append(activity_id)
            answer.update(production_draft=False, production_reviewed=True, review_status='trainer_reviewed')
        db.execute('UPDATE learner_course_progress SET answers_json=?,completed_json=? WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?',
                   (json.dumps(saved), json.dumps(completed_ids), *service.tracking._key_values(access)))


@pytest.mark.parametrize('old_revision', [False, True])
def test_uncertain_legacy_results_are_retried_even_when_the_digest_is_current(work, old_revision):
    service, access = work
    with patch('elearning_native.vtc_ai.CORRECTION_REVISION', 'legacy-free-quotes' if old_revision else CORRECTION_REVISION), \
            patch('elearning_native.vtc_production_work.time.time', return_value=2_000_000_000), \
            patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK):
        first = submit(service, access)
    uncertain = {**FEEDBACK, 'status': 'needs_human_review', 'needs_human_review': True,
                 'human_review_reasons': ['Ancienne correction à vérifier.']}
    replace_legacy_feedback(service, access, first['attempt_id'], uncertain)
    with patch('elearning_native.vtc_production_work.time.time', return_value=2_000_000_010), \
            patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK) as api:
        refreshed = submit(service, access)
        repeated = submit(service, access)
    assert api.call_count == 1
    assert refreshed['cached'] is False and repeated['cached'] is True
    assert refreshed['attempt_id'] != first['attempt_id']
    assert repeated['attempt_id'] == refreshed['attempt_id']
    history = service.history(access, ACTIVITY['id'])
    assert [row['status'] for row in history] == ['corrected', 'needs_human_review']
    assert history[1]['feedback'] == uncertain
    assert all(row['answers'] == ANSWERS for row in history)
    progress = current(service, access)
    assert progress['answers'][ACTIVITY['id']]['production_first_answers'] == ANSWERS
    assert progress['answers'][ACTIVITY['id']]['needs_trainer_help'] is False
    assert progress['active_seconds'] == 0 and progress['completed_activity_ids'] == []
    assert service.completion_answer(access, ACTIVITY, {'production_answers': ANSWERS, 'production_reviewed': True}, progress)['review_status'] == 'ai_feedback_read'


@pytest.mark.parametrize('target,field,value', [
    ('root', 'human_review_reasons', ['Incertitude persistante.']),
    ('root', 'human_review_reasons', None),
    ('root', 'needs_human_review', True),
    ('root', 'score', 19),
    ('root', 'criteria', []),
    ('criterion', 'status', 'uncertain'),
    ('criterion', 'uncertain', True),
    ('criterion', 'points', True),
    ('criterion', 'points', '9'),
    ('criterion', 'points', float('nan')),
    ('criterion', 'points', float('inf')),
    ('criterion', 'points', -1),
    ('criterion', 'points', 11),
    ('criterion', 'max_points', 0),
    ('criterion', 'max_points', float('inf')),
    ('criterion', 'max_points', True),
])
def test_incoherent_output_saves_copy_without_score_or_validation(work, target, field, value):
    service, access = work
    invalid = copy.deepcopy(FEEDBACK)
    (invalid if target == 'root' else invalid['criteria'][0])[field] = value
    with patch('elearning_native.vtc_ai.grade_written_work', return_value=invalid):
        with pytest.raises(VtcAIError) as error:
            submit(service, access)
    assert error.value.code == 'invalid_response'
    attempt = service.history(access, ACTIVITY['id'])[0]
    assert attempt['status'] == 'failed' and attempt['feedback'] == {}
    saved = current(service, access)
    assert saved['answers'][ACTIVITY['id']]['production_first_answers'] == ANSWERS
    assert 'production_ai_feedback' not in saved['answers'][ACTIVITY['id']]
    assert saved['active_seconds'] == 0 and saved['completed_activity_ids'] == []


def test_clearing_only_a_legacy_flag_does_not_release_or_cache_its_score(work):
    service, access = work
    with patch('elearning_native.vtc_production_work.time.time', return_value=2_000_000_000), \
            patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK):
        first = submit(service, access)
    invalid = copy.deepcopy(FEEDBACK)
    invalid['criteria'][0]['status'] = 'uncertain'
    replace_legacy_feedback(service, access, first['attempt_id'], invalid)
    with pytest.raises(WrittenWorkError, match='non confirmée'):
        service.completion_answer(access, ACTIVITY, {'production_answers': ANSWERS, 'production_reviewed': True}, current(service, access))
    with patch('elearning_native.vtc_production_work.time.time', return_value=2_000_000_010), \
            patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK) as api:
        refreshed = submit(service, access)
    assert api.call_count == 1 and refreshed['attempt_id'] != first['attempt_id']


def test_revised_draft_requires_its_own_correction_and_preserves_first_response(work):
    service, access = work
    with patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK):
        submit(service, access)
    revised = {**ANSWERS, 'message': 'Bonjour, votre réservation R-42 est confirmée pour 9 h au lieu convenu.'}
    service.submit(access, {}, ACTIVITY, {'stage': 'draft', 'production_answers': revised}, current(service, access))
    with pytest.raises(WrittenWorkError, match='corriger'):
        service.completion_answer(access, ACTIVITY, {'production_answers': revised, 'production_reviewed': True}, current(service, access))
    with patch('elearning_native.vtc_production_work.time.time', return_value=2_000_000_000), patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK):
        submit(service, access, revised)
    saved = current(service, access)['answers'][ACTIVITY['id']]
    assert saved['production_first_answers'] == ANSWERS
    assert saved['production_answers'] == revised
    assert len(service.history(access, ACTIVITY['id'])) == 2


def test_acknowledgement_and_server_threshold_are_required_not_client_score(work):
    service, access = work
    with patch('elearning_native.vtc_ai.grade_written_work', return_value={**FEEDBACK, 'score': 8, 'criteria': [{**item, 'points': 4} for item in FEEDBACK['criteria']]}):
        submit(service, access)
    with pytest.raises(WrittenWorkError, match='Lisez'):
        service.completion_answer(access, ACTIVITY, {'production_answers': ANSWERS}, current(service, access))
    with pytest.raises(WrittenWorkError, match='12/20'):
        service.completion_answer(access, ACTIVITY, {'production_answers': ANSWERS, 'production_reviewed': True, 'score': 20}, current(service, access))


@pytest.mark.parametrize('completed', [False, True])
def test_old_manual_decisions_are_immutable_and_only_completed_work_is_preserved(work, completed):
    service, access = work
    with patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK):
        submitted = submit(service, access)
    historical = {**copy.deepcopy(FEEDBACK), 'status': 'trainer_reviewed', 'score': 8,
                  'human_review_reasons': ['Ancien doute levé lors de la validation.'],
                  'trainer_review': {'outcome': 'reviewed', 'comment': 'Décision historique conservée.', 'reviewer': 'old-reviewer'}}
    replace_legacy_feedback(service, access, submitted['attempt_id'], historical, completed=completed)
    before = current(service, access)
    prior_history = service.history(access, ACTIVITY['id'])
    payload = {'production_answers': ANSWERS, 'production_reviewed': True}
    if completed:
        # A stale/missing current form is irrelevant to an already acquired completion.
        assert service.completion_answer(access, ACTIVITY, {}, before) == before['answers'][ACTIVITY['id']]
    else:
        with pytest.raises(WrittenWorkError, match='non confirmée'):
            service.completion_answer(access, ACTIVITY, payload, before)
    with pytest.raises(WrittenWorkError) as retired:
        service.trainer_review(submitted['attempt_id'], comment='Nouvelle décision interdite.', reviewer='admin', outcome='reviewed', allowed_owners={(access['session_id'], access['trainee_id'])})
    assert retired.value.status == 410
    after = current(service, access)
    assert after['answers'] == before['answers']
    assert after['completed_activity_ids'] == before['completed_activity_ids']
    assert after['active_seconds'] == before['active_seconds']
    assert service.history(access, ACTIVITY['id']) == prior_history


def test_other_learner_cannot_use_correction_or_read_history(work):
    service, access = work
    with patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK):
        submit(service, access)
    other = {**access, 'trainee_id': 'bob'}
    assert service.history(other, ACTIVITY['id']) == []
    with pytest.raises(WrittenWorkError):
        service.completion_answer(other, ACTIVITY, {'production_answers': ANSWERS, 'production_reviewed': True}, current(service, other))


def test_inflight_feedback_does_not_replace_a_newer_draft(work):
    service, access = work
    revised = {**ANSWERS, 'checks': 'Une nouvelle version de mes contrôles est en cours de rédaction dans un autre onglet.'}
    def grade(_assignment, _answers):
        service.tracking.record_production(access, ACTIVITY['id'], revised)
        return FEEDBACK
    with patch('elearning_native.vtc_ai.grade_written_work', side_effect=grade):
        result = submit(service, access)
    assert result['current_copy'] is False
    saved = current(service, access)['answers'][ACTIVITY['id']]
    assert saved['production_answers'] == revised
    assert saved['production_first_answers'] == ANSWERS
    assert 'production_ai_feedback' not in saved


def test_concurrent_draft_between_review_and_completion_is_preserved_transactionally(work):
    service, access = work
    with patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK):
        submit(service, access)
    checked = service.completion_answer(access, ACTIVITY,
        {'production_answers': ANSWERS, 'production_reviewed': True}, current(service, access))
    revised = {**ANSWERS, 'checks': 'Une nouvelle version de mes contrôles a été enregistrée dans un second onglet.'}
    service.tracking.record_production(access, ACTIVITY['id'], revised)
    before = current(service, access)
    with pytest.raises(TrackingError, match='brouillon a changé'):
        service.tracking.complete_activity(access, ACTIVITY['id'],
            activity_order=[ACTIVITY['id']], scored_activity_ids=[], mastery_score=80,
            answer=checked)
    after = current(service, access)
    assert after['answers'][ACTIVITY['id']]['production_answers'] == revised
    assert after['answers'] == before['answers']
    assert after['completed_activity_ids'] == []
    assert after['active_seconds'] == before['active_seconds']
    assert after['score_percent'] == before['score_percent']
    with service.tracking._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tracking_events WHERE event_type='answer_submitted'").fetchone()[0] == 0


def test_changed_rubric_never_reuses_a_previous_score(work):
    service, access = work
    with patch('elearning_native.vtc_ai.grade_written_work', return_value=FEEDBACK):
        submit(service, access)
    revised = copy.deepcopy(ACTIVITY)
    revised['production']['rubric'][0]['expected'] = 'Confirmer aussi un nouveau point de rendez-vous explicite.'
    with pytest.raises(WrittenWorkError):
        service.completion_answer(access, revised, {'production_answers': ANSWERS, 'production_reviewed': True}, current(service, access))
