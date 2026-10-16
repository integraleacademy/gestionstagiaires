"""Duration progress must not falsely certify completion or transfer surplus time."""
import pytest

from elearning_pdf_components import compact_duration, module_duration, percentage, report_duration


def module(active, required=14400, **extra):
    return dict(active_seconds=active, required_seconds=required, available=True, **extra)


def test_completed_activities_do_not_complete_the_duration():
    value = module_duration(module(10800, progress_percent=100, module_complete=False))
    assert value['fraction'] == .75
    assert value['remaining'] == 3600
    assert compact_duration(value['active']) + ' / ' + compact_duration(value['required']) == '3 h / 4 h'


def test_surplus_time_and_final_exam_do_not_complete_other_modules():
    report = dict(available=True, required_seconds=28800, active_seconds=40000,
                  modules=[module(28800), module(3600)], final_exam_time={'active_seconds': 7600})
    value = report_duration(report)
    assert value['active'] == 18000
    assert value['remaining'] == 10800
    assert value['fraction'] == .625


def test_objective_surplus_does_not_hide_missing_objective_time():
    value = module_duration(module(14400, timed_objectives=[module(12600, 7200), module(1800, 7200)]))
    assert value['fraction'] == .625
    assert value['remaining'] == 5400


def test_unavailable_module_prevents_a_complete_overall_bar():
    missing = module(14400)
    missing['available'] = False
    value = report_duration(dict(available=False, required_seconds=28800, modules=[module(14400), missing]))
    assert not value['known'] and value['fraction'] is None


def test_missing_target_is_not_replaced_by_recorded_time():
    value = module_duration({'active_seconds': 3600, 'available': True})
    assert value['active'] == 3600 and value['required'] is None
    assert value['fraction'] is None


def test_nearly_complete_is_never_rounded_up_to_100_percent():
    assert percentage(module_duration(module(14399.99))['fraction']) == '99,9 %'
    assert percentage(module_duration(module(14400))['fraction']) == '100 %'
    assert percentage(module_duration(module(18000))['fraction']) == '100 %'


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), 'invalid'])
def test_invalid_recorded_time_is_not_presented_as_completed(invalid):
    value = module_duration(module(invalid))
    assert value['fraction'] is None and not value['known']


@pytest.mark.parametrize('suffix', [' 00 s', ''])
def test_legacy_demo_labels_remain_readable_without_guessing_a_duration(suffix):
    value = module_duration({'active_time_label': '03 h 00 min' + suffix, 'required_time_label': '04 h 00 min' + suffix, 'available': True})
    assert value['fraction'] == .75
