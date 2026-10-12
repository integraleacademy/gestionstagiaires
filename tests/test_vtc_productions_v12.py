"""The authored 105-hour edition is additive, private, and internally teachable."""
import copy
import json

import pytest

from elearning_native import vtc, vtc_productions as productions
from elearning_native.videos import course_videos
from elearning_native.vtc_ai import _private_assignment, normalize_answers


def activities(course):
    return [activity for section in course['sections'] for activity in section['activities']]


@pytest.mark.parametrize('letter', 'ABCDEFGH')
def test_composed_course_keeps_all_existing_activities_and_videos(letter):
    course_id = 'academy-vtc-' + letter.lower()
    base = vtc.load_bundled_course(course_id, productions.BASE_VERSION)
    before = copy.deepcopy(base)
    current = vtc.load_bundled_course(course_id)
    assert base == before
    assert current['version'] == productions.VERSION
    assert current['planned_minutes'] == current['required_minutes'] == productions.MODULE_MINUTES[letter]
    assert sum(a['planned_minutes'] for a in activities(current)) == current['planned_minutes']
    assert sum(row['minutes'] for row in current['duration_breakdown']) == current['planned_minutes']
    assert len(current['activity_order']) == 46
    added = {a['id']: a for a in activities(current) if a.get('production')}
    assert len(added) == 4
    assert [aid for aid in current['activity_order'] if aid not in added] == base['activity_order']
    old_activities = {a['id']: a for a in activities(base)}
    for activity in activities(current):
        if activity['id'] in added:
            assert activity['vtc']['kind'] == 'production'
            assert activity['planned_minutes'] == activity['production']['estimated_minutes']
            continue
        expected = copy.deepcopy(old_activities[activity['id']])
        if expected.get('vtc', {}).get('kind') == 'supplements':
            expected['vtc']['notice'] = productions.NOTICE
        assert activity == expected
    assert current['assets'] == base['assets']
    assert course_videos(current) == course_videos(base)
    assert len(course_videos(current)) == 13
    for number in range(1, 5):
        section = next(s for s in current['sections'] if s['id'] == f'vtc-{letter.lower()}-{number * 3:02}')
        assert section['activities'][-1]['id'] == f'vtc-{letter.lower()}-production-{number:02}'
    # No caller mutates the historical source or a subsequent fresh load.
    current['sections'][0]['activities'][0]['title'] = 'caller mutation'
    assert vtc.load_bundled_course(course_id, productions.BASE_VERSION) == before
    assert vtc.load_bundled_course(course_id)['sections'][0]['activities'][0]['title'] != 'caller mutation'


def test_all_32_subjects_and_models_can_be_graded_without_an_api_call():
    bank = productions.production_bank()
    assert len(bank['productions']) == 32
    assert sum(row['estimated_minutes'] for row in bank['productions']) == 878
    assert sum(len(row['response_fields']) for row in bank['productions']) == 99
    for row in bank['productions']:
        with_id = f"{row['id']}"
        private = _private_assignment(row)
        assert len(private['rubric']) == 4, with_id
        assert sum(c['max_points'] for c in private['rubric']) == 20, with_id
        assert normalize_answers(row, row['model_response']) == row['model_response'], with_id
        assert sum(p['minutes'] for p in row['work_phases']) == row['estimated_minutes'], with_id
        assert all(p['deliverable'] for p in row['work_phases']), with_id
        course = vtc.load_bundled_course(row['course_id'])
        section_ids = {s['id'] for s in course['sections']}
        assert all(t['course_id'] == row['course_id'] and t['section_id'] in section_ids
                   for t in row['revision_targets']), with_id


def test_public_subject_does_not_disclose_any_marking_answers():
    assignment = productions.get_production('vtc-b-production-02')
    before = copy.deepcopy(assignment)
    public = productions.public_production(assignment)
    assert 'model_response' not in public and 'rubric' not in public and 'feedback' not in public
    assert all(set(c) == {'id', 'label', 'max_points'} for c in public['rubric_preview'])
    assert public['work_phases'] == assignment['work_phases']
    assert public['documents'] == assignment['documents']
    public['documents'][0]['text'] = 'changed by caller'
    assert assignment == before
    assert productions.get_production(assignment['id']) == before
    revealed = productions.public_production(assignment, reveal=True)
    assert revealed['feedback']['model_response'] == assignment['model_response']


def test_catalogue_and_programme_total_105_hours_with_cma_additional():
    manifest = vtc.curriculum_manifest()
    programme = json.loads((vtc.ROOT / manifest['programme_file']).read_text())
    assert manifest['version'] == programme['version'] == productions.VERSION
    assert manifest['planned_minutes'] == programme['planned_minutes'] == 6300
    assert sum(m['planned_minutes'] for m in manifest['modules']) == 6300
    assert sum(m['planned_minutes'] for m in programme['modules']) == 6300
    assert sum(m['base_minutes'] for m in programme['modules']) == 5422
    assert sum(m['production_minutes'] for m in programme['modules']) == 878
    assert manifest['activity_count'] == 368
    assert manifest['production_count'] == 32
    assert programme['additional_simulation']['minutes'] == 230
    assert programme['additional_simulation']['included_in_105_hours'] is False
    assert programme['validation']['real_learners_tested'] == 0
    assert programme['validation']['measured_median_minutes'] is None


@pytest.mark.parametrize('exam_id', [f'vtc-{letter}' for letter in 'abcdefgh'] + ['vtc-final'])
def test_existing_pedagogical_exams_are_available_for_v12_without_changing_old_bank(exam_id):
    base = vtc.load_exam(exam_id, productions.BASE_VERSION)
    expected = {**copy.deepcopy(base), 'version': productions.VERSION}
    current = vtc.load_exam(exam_id, productions.VERSION)
    assert current == expected
    current['questions'].clear()
    assert vtc.load_exam(exam_id, productions.BASE_VERSION) == base
    assert vtc.load_exam(exam_id, productions.VERSION) == expected


def test_historical_versions_and_unknown_ids_do_not_receive_new_requirements():
    for version in ('20261010-vtc-v6-pedagogie', productions.BASE_VERSION):
        old = vtc.load_bundled_course('academy-vtc-a', version)
        assert old['version'] == version
        assert len(old['activity_order']) == 42
        assert not any(a.get('production') for a in activities(old))
        assert old['planned_minutes'] == 755
    assert productions.get_production('vtc-a-production-01', productions.BASE_VERSION) is None
    assert productions.get_production('vtc-a-production-99') is None
    assert productions.productions_for_module('academy-aps') == []
    assert vtc.load_bundled_course('academy-vtc-a', 'unknown-edition') is None
    assert vtc.load_exam('unknown-exam', productions.VERSION) is None


@pytest.mark.parametrize('change', ['missing', 'position', 'duration', 'model', 'rubric'])
def test_incomplete_authored_bank_is_rejected_before_it_can_block_a_learner(change):
    bank = productions.production_bank()
    if change == 'missing':
        bank['productions'].pop()
    elif change == 'position':
        bank['productions'][0]['after_section_id'] = 'vtc-a-06'
    elif change == 'duration':
        bank['productions'][0]['work_phases'][0]['minutes'] += 1
    elif change == 'model':
        bank['productions'][0]['model_response'].pop('decisions')
    else:
        bank['productions'][0]['rubric'][0]['field_ids'] = ['unknown_field']
    with pytest.raises(ValueError):
        productions._validate_bank(bank)
