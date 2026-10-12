"""Written VTC work is durable; only server corrections can release completion."""
import copy
from unittest.mock import patch

import pytest

from elearning_native.store import NativeElearningStore, TrackingError
from elearning_native.vtc_ai import VtcAIError
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
            'criteria': [], 'errors': [], 'next_steps': ['Précisez le numéro de réservation.'], 'model_response': ASSIGNMENT['model_response']}


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


def test_revised_correction_contract_does_not_reuse_an_uncertain_old_result(work):
    service, access = work
    uncertain = {**FEEDBACK, 'needs_human_review': True}
    with patch('elearning_native.vtc_ai.grade_written_work', side_effect=[uncertain, FEEDBACK]) as api:
        with patch('elearning_native.vtc_ai.CORRECTION_REVISION', 'legacy-free-quotes'), \
                patch('elearning_native.vtc_production_work.time.time', return_value=2_000_000_000):
            first = submit(service, access)
        with patch('elearning_native.vtc_production_work.time.time', return_value=2_000_000_010):
            refreshed = submit(service, access)
            repeated = submit(service, access)
    assert api.call_count == 2
    assert refreshed['cached'] is False
    assert refreshed['attempt_id'] != first['attempt_id']
    assert repeated['cached'] is True
    assert repeated['attempt_id'] == refreshed['attempt_id']
    assert refreshed['feedback']['needs_human_review'] is False
    history = service.history(access, ACTIVITY['id'])
    assert [row['status'] for row in history] == ['corrected', 'needs_human_review']
    assert all(row['answers'] == ANSWERS for row in history)
    progress = current(service, access)
    assert progress['answers'][ACTIVITY['id']]['production_first_answers'] == ANSWERS
    assert progress['active_seconds'] == 0
    assert progress['completed_activity_ids'] == []


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
    with patch('elearning_native.vtc_ai.grade_written_work', return_value={**FEEDBACK, 'score': 8}):
        submit(service, access)
    with pytest.raises(WrittenWorkError, match='Lisez'):
        service.completion_answer(access, ACTIVITY, {'production_answers': ANSWERS}, current(service, access))
    with pytest.raises(WrittenWorkError, match='12/20'):
        service.completion_answer(access, ACTIVITY, {'production_answers': ANSWERS, 'production_reviewed': True, 'score': 20}, current(service, access))


def test_uncertain_copy_can_be_released_only_by_recorded_trainer_review(work):
    service, access = work
    with patch('elearning_native.vtc_ai.grade_written_work', return_value={**FEEDBACK, 'needs_human_review': True}):
        submitted = submit(service, access)
    payload = {'production_answers': ANSWERS, 'production_reviewed': True}
    with pytest.raises(WrittenWorkError, match='formateur'):
        service.completion_answer(access, ACTIVITY, payload, current(service, access))
    service.trainer_review(submitted['attempt_id'], comment='Le raisonnement a été vérifié avec le stagiaire et correspond aux attendus.', reviewer='trainer', outcome='reviewed')
    result = service.completion_answer(access, ACTIVITY, payload, current(service, access))
    assert result['review_status'] == 'trainer_reviewed'
    assert result['production_ai_feedback']['trainer_review']['reviewer'] == 'trainer'
    assert current(service, access)['completed_activity_ids'] == []


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
