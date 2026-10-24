import copy
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, redirect, render_template, session, url_for
import pymupdf
import pytest

import aps_kickoff as kickoff


@pytest.fixture
def case(monkeypatch):
    trainee = dict(public_token='trainee-one')
    training = dict(id='aps-test', training_type='APS', name='APS novembre',
                    date_start='2026-11-03', date_end='2026-12-08', exam_date='2026-12-09',
                    aps_remote_start='2026-11-03', aps_remote_end='2026-11-16',
                    aps_in_person_start='2026-11-17', aps_in_person_end='2026-12-08',
                    trainees=[trainee])
    data = dict(sessions=[training])
    services = SimpleNamespace(
        INTEGRALE_PARTNER_ID='integrale',
        APS_CONVOCATION_CENTER_CITY='Puget-sur-Argens', APS_CONVOCATION_CENTER_ZIP='83480',
        APS_CONVOCATION_CENTER_ADDRESS='54 chemin du Carreou',
        _session_get=lambda obj, key, default='': obj.get(key, default),
        _trainee_registration_is_cancelled=lambda t: bool(t.get('registration_cancelled')),
        load_data=lambda **kw: data,
        find_session=lambda d, sid: next((s for s in d['sessions'] if s['id'] == sid), None),
        find_session_and_trainee_by_token=lambda d, token: (training, trainee) if token == trainee['public_token'] else (None, None),
        _public_is_authed=lambda token: bool(session.get('public_auth_'+token)),
    )
    def admin_login_required(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not session.get('admin_logged_in'):
                return redirect('/admin/login')
            return function(*args, **kwargs)
        return wrapped
    services.admin_login_required = admin_login_required
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1]/'templates'))
    app.config.update(TESTING=True, SECRET_KEY='test-only')
    app.add_url_rule('/espace/<token>/login', 'public_trainee_login', lambda token: 'Login')
    kickoff.register(app, services)
    monkeypatch.setattr(kickoff, 'today', lambda: date(2026, 11, 3))
    client = app.test_client()
    with client.session_transaction() as cookie:
        cookie['public_auth_trainee-one'] = True
    return app, client, services, training, trainee


PUBLIC = '/espace/trainee-one/diaporama-aps.pdf'
ADMIN = '/admin/sessions/aps-test/diaporama-aps.pdf'


def test_release_on_remote_start_and_remains_available(case, monkeypatch):
    app, client, services, training, trainee = case
    for day, expected in [(date(2026, 11, 2), 403), (date(2026, 11, 3), 200),
                          (date(2026, 11, 16), 200), (date(2028, 1, 1), 200)]:
        monkeypatch.setattr(kickoff, 'today', lambda day=day: day)
        assert client.get(PUBLIC).status_code == expected
        state = kickoff.view(services, training, trainee)
        with app.test_request_context('/'):
            html = render_template('aps_kickoff_card.html', aps_kickoff=state, token_safe='trainee-one')
        assert ('Consulter le diaporama' in html) == (expected == 200)
        assert ('Télécharger le PDF' in html) == (expected == 200)


def test_authentication_and_token_ownership(case):
    app, client, services, training, trainee = case
    assert app.test_client().get(PUBLIC).status_code == 302
    assert client.get('/espace/trainee-two/diaporama-aps.pdf').status_code == 302
    with client.session_transaction() as cookie:
        cookie['public_auth_unknown'] = True
    assert client.get('/espace/unknown/diaporama-aps.pdf').status_code == 404
    trainee['registration_cancelled'] = True
    assert client.get(PUBLIC).status_code == 403


def test_preview_before_start_is_admin_only(case, monkeypatch):
    _, client, _, _, _ = case
    monkeypatch.setattr(kickoff, 'today', lambda: date(2026, 10, 1))
    assert client.get(ADMIN).status_code == 302
    with client.session_transaction() as cookie:
        cookie['admin_logged_in'] = True
    result = client.get(ADMIN)
    assert result.status_code == 200
    assert result.mimetype == 'application/pdf'
    assert result.headers['Content-Disposition'].startswith('inline;')
    assert client.get(PUBLIC).status_code == 403
    assert client.get(ADMIN+'?download=1').headers['Content-Disposition'].startswith('attachment;')
    assert result.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('change', [dict(training_type='MAC APS'), dict(training_type='APS MAC'),
    dict(training_type='A3P'), dict(training_type='SSIAP 1'), dict(afc_enabled=True),
    dict(name='AFC APS + SSIAP 1'), dict(partner_id='another-centre')])
def test_other_courses_and_partner_sessions_are_excluded(case, change):
    _, client, services, training, trainee = case
    training.update(change)
    assert kickoff.view(services, training, trainee) is None
    assert client.get(PUBLIC).status_code == 404
    with client.session_transaction() as cookie:
        cookie['admin_logged_in'] = True
    assert client.get(ADMIN).status_code == 404


@pytest.mark.parametrize('change', [dict(exam_date=''), dict(aps_remote_end='bad-date'),
    dict(aps_in_person_start='2026-11-05'), dict(exam_date='2026-11-01')])
def test_missing_or_inconsistent_dates_never_create_a_wrong_pdf(case, change):
    _, client, services, training, trainee = case
    training.update(change)
    assert not kickoff.view(services, training, trainee)['ready']
    assert client.get(PUBLIC).status_code == 403
    with client.session_transaction() as cookie:
        cookie['admin_logged_in'] = True
    assert client.get(ADMIN).status_code == 409


def test_pdf_updates_all_dates_without_mutating_session(case):
    _, _, services, training, _ = case
    training.update(date_start='2027-01-04', date_end='2027-02-08', exam_date='2027-02-09',
                    aps_remote_start='2027-01-04', aps_remote_end='2027-01-15',
                    aps_in_person_start='2027-01-18', aps_in_person_end='2027-02-08')
    before = copy.deepcopy(training)
    pdf = kickoff.pdf(services, training)
    assert training == before
    assert kickoff.pdf(services, training) == pdf
    document = pymupdf.open(stream=pdf, filetype='pdf')
    text = '\n'.join(page.get_text() for page in document)
    assert len(document) == 41
    assert '9 février 2027' in text
    assert 'JANVIER 2027' in document[7].get_text()
    assert 'FÉVRIER 2027' in document[7].get_text()
    assert '2026' not in text and 'novembre' not in text.lower() and 'en centre' not in text.lower()
    assert 'Les 14 UV' in text
    assert '62 h' in text
    training['exam_date'] = '2027-02-10'
    revised = kickoff.pdf(services, training)
    assert revised != pdf
    assert '10 février 2027' in pymupdf.open(stream=revised, filetype='pdf')[34].get_text()


def test_calendar_year_transition_leap_day_and_phase_colors(case):
    _, _, services, training, _ = case
    training.update(date_start='2027-12-13', date_end='2028-02-28', exam_date='2028-02-29',
                    aps_remote_start='2027-12-13', aps_remote_end='2028-01-04',
                    aps_in_person_start='2028-01-05', aps_in_person_end='2028-02-28')
    dates = kickoff.schedule(services, training)
    assert kickoff.months_between(dates['date_start'], dates['exam_date']) == [(2027, 12), (2028, 1), (2028, 2)]
    assert kickoff.calendar_phase(date(2028, 1, 4), dates) == kickoff.BLUE
    assert kickoff.calendar_phase(date(2028, 1, 5), dates) == kickoff.GREEN
    assert kickoff.calendar_phase(date(2028, 2, 29), dates) == kickoff.GOLD
    pdf = kickoff.pdf(services, training)
    page = pymupdf.open(stream=pdf, filetype='pdf')[7]
    assert all(month in page.get_text() for month in ('DÉCEMBRE 2027', 'JANVIER 2028', 'FÉVRIER 2028', '29 février 2028'))


def test_release_uses_paris_midnight_in_winter_and_summer(monkeypatch):
    for utc, expected in [('2026-11-02T22:59:59+00:00', date(2026, 11, 2)),
                          ('2026-11-02T23:00:00+00:00', date(2026, 11, 3)),
                          ('2027-06-06T22:00:00+00:00', date(2027, 6, 7))]:
        instant = datetime.fromisoformat(utc)
        class Clock:
            @staticmethod
            def now(tz):
                return instant.astimezone(tz)
        monkeypatch.setattr(kickoff, 'datetime', Clock)
        assert kickoff.today() == expected
