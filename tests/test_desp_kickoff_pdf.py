import ast
import copy
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

from flask import Flask, redirect, render_template, session
import pymupdf
import pytest

import afc_schedule
import desp_kickoff as kickoff

ROOT = Path(__file__).resolve().parents[1]
# Exercise the app's actual course/site routing without booting unrelated services.
tree = ast.parse((ROOT/'app.py').read_text())
config_nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name in {'_automation_training_text', '_automation_document_config'}]
config_globals = dict(Dict=Dict, Any=Any, afc_schedule=afc_schedule,
                      _session_get=lambda obj, key, default='': obj.get(key, default))
exec(compile(ast.Module(body=config_nodes, type_ignores=[]), str(ROOT/'app.py'), 'exec'), config_globals)


@pytest.fixture(params=['paris', 'puget'])
def case(request, monkeypatch):
    city = request.param
    trainee = dict(public_token='trainee-one')
    training = dict(id='desp-test', training_type='DIRIGEANT', name='DESP '+city.upper(),
                    date_start='2027-01-04', date_end='2027-02-18', exam_date='2027-02-19',
                    dirigeant_remote_start='2027-01-04', dirigeant_remote_end='2027-02-05',
                    dirigeant_in_person_start='2027-02-08', dirigeant_in_person_end='2027-02-18',
                    trainees=[trainee])
    data = dict(sessions=[training])
    services = SimpleNamespace(
        INTEGRALE_PARTNER_ID='integrale',
        _session_get=config_globals['_session_get'],
        _automation_document_config=config_globals['_automation_document_config'],
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
    app = Flask(__name__, template_folder=str(ROOT/'templates'))
    app.config.update(TESTING=True, SECRET_KEY='test-only')
    app.add_url_rule('/espace/<token>/login', 'public_trainee_login', lambda token: 'Login')
    kickoff.register(app, services)
    monkeypatch.setattr(kickoff, 'today', lambda: date(2027, 1, 4))
    client = app.test_client()
    with client.session_transaction() as cookie:
        cookie['public_auth_trainee-one'] = True
    return app, client, services, training, trainee, city


PUBLIC = '/espace/trainee-one/diaporama-desp.pdf'
ADMIN = '/admin/sessions/desp-test/diaporama-desp.pdf'


def test_release_and_card_use_remote_start(case, monkeypatch):
    app, client, services, training, trainee, city = case
    # The recorded hybrid-course start has priority over a stale generic date.
    training['date_start'] = '2026-12-01'
    for day, expected in [(date(2027, 1, 3), 403), (date(2027, 1, 4), 200), (date(2028, 1, 1), 200)]:
        monkeypatch.setattr(kickoff, 'today', lambda day=day: day)
        assert client.get(PUBLIC).status_code == expected
        state = kickoff.view(services, training, trainee)
        with app.test_request_context('/'):
            html = render_template('desp_kickoff_card.html', desp_kickoff=state, token_safe='trainee-one')
        assert ('Consulter le diaporama' in html) == (expected == 200)
        assert ('Télécharger le PDF' in html) == (expected == 200)
        if expected == 200:
            assert kickoff.CITIES[city] in html


def test_authentication_token_ownership_and_cancellation(case):
    app, client, services, training, trainee, city = case
    assert app.test_client().get(PUBLIC).status_code == 302
    assert client.get('/espace/trainee-two/diaporama-desp.pdf').status_code == 302
    with client.session_transaction() as cookie:
        cookie['public_auth_unknown'] = True
    assert client.get('/espace/unknown/diaporama-desp.pdf').status_code == 404
    trainee['registration_cancelled'] = True
    assert client.get(PUBLIC).status_code == 403
    assert not kickoff.view(services, training, trainee)['available']


def test_admin_preview_and_download_before_start(case, monkeypatch):
    _, client, _, _, _, city = case
    monkeypatch.setattr(kickoff, 'today', lambda: date(2026, 10, 1))
    assert client.get(ADMIN).status_code == 302
    with client.session_transaction() as cookie:
        cookie['admin_logged_in'] = True
    result = client.get(ADMIN)
    assert result.status_code == 200 and result.mimetype == 'application/pdf'
    assert result.headers['Content-Disposition'].startswith('inline;')
    assert f'Diaporama_DESP_{city}_2027-01-04.pdf' in result.headers['Content-Disposition']
    assert client.get(ADMIN+'?download=1').headers['Content-Disposition'].startswith('attachment;')
    assert result.headers['Cache-Control'] == 'private, no-store'
    assert client.get(PUBLIC).status_code == 403
    assert client.get('/admin/sessions/unknown/diaporama-desp.pdf').status_code == 404


@pytest.mark.parametrize('change', [dict(training_type='DESP VAE'), dict(training_type='MAC DESP'),
    dict(name='RECYCLAGE DESP'), dict(training_type='APS', name='APS novembre'),
    dict(training_type='A3P'), dict(training_type='VTC'), dict(afc_enabled=True),
    dict(partner_id='another-centre')])
def test_other_courses_and_partners_are_excluded(case, change):
    _, client, services, training, trainee, _ = case
    training.update(change)
    assert kickoff.view(services, training, trainee) is None
    assert client.get(PUBLIC).status_code == 404
    with client.session_transaction() as cookie:
        cookie['admin_logged_in'] = True
    assert client.get(ADMIN).status_code == 404


@pytest.mark.parametrize('change', [dict(exam_date=''), dict(dirigeant_remote_end='bad-date'),
    dict(dirigeant_in_person_start='2027-01-15'), dict(exam_date='2027-02-01'),
    dict(dirigeant_remote_start='')])
def test_incomplete_or_inconsistent_dates_never_create_a_wrong_pdf(case, change):
    _, client, services, training, trainee, _ = case
    training.update(change)
    assert not kickoff.view(services, training, trainee)['ready']
    assert client.get(PUBLIC).status_code == 403
    with client.session_transaction() as cookie:
        cookie['admin_logged_in'] = True
    assert client.get(ADMIN).status_code == 409


def test_all_dynamic_dates_and_correct_site_update_without_mutations(case):
    _, _, services, training, _, city = case
    before = copy.deepcopy(training)
    content = kickoff.pdf(services, training)
    assert training == before and kickoff.pdf(services, training) == content
    document = pymupdf.open(stream=content, filetype='pdf')
    text = '\n'.join(page.get_text() for page in document)
    assert len(document) == 24 and '2026' not in text
    assert 'en centre' not in text.lower()
    assert 'SESSION INITIALE À '+('PARIS' if city == 'paris' else 'PUGET-SUR-ARGENS') in document[0].get_text()
    assert '19 février 2027' in document[16].get_text()
    assert 'Dates 2027' in document[4].get_text()
    assert '4 janvier au 5 février' in document[4].get_text()
    assert '8 au 18 février' in document[4].get_text()
    assert '174 h de e-learning' in text and '70 h' in text
    assert '28 mars 2025' in document[2].get_text() and '28 mars 2027' in document[2].get_text()
    assert 'Votre accès au e-learning est ouvert.' in document[23].get_text()
    if city == 'paris':
        assert '53 rue des' in document[13].get_text() and '75010 Paris' in document[13].get_text()
    else:
        assert 'PUGET-SUR-ARGENS' in document[13].get_text()
    training['exam_date'] = '2027-02-20'
    revised = kickoff.pdf(services, training)
    assert revised != content
    assert '20 février 2027' in pymupdf.open(stream=revised, filetype='pdf')[16].get_text()


def test_cross_year_calendar_retains_years_and_leap_day(case):
    _, _, services, training, _, _ = case
    training.update(date_start='2027-12-13', date_end='2028-02-28', exam_date='2028-02-29',
                    dirigeant_remote_start='2027-12-13', dirigeant_remote_end='2028-01-28',
                    dirigeant_in_person_start='2028-02-01', dirigeant_in_person_end='2028-02-28')
    document = pymupdf.open(stream=kickoff.pdf(services, training), filetype='pdf')
    assert 'Dates 2027 – 2028' in document[4].get_text()
    calendar = document[4].get_text().replace('\n', ' ')
    assert '13 décembre 2027 au 28 janvier 2028' in calendar
    assert '1 au 28 février 2028' in calendar and '29 février 2028' in calendar
    assert '29 février 2028' in document[16].get_text()


def test_release_uses_paris_midnight_in_winter_and_summer(monkeypatch):
    for utc, expected in [('2026-10-25T22:59:59+00:00', date(2026, 10, 25)),
                          ('2026-10-25T23:00:00+00:00', date(2026, 10, 26)),
                          ('2027-06-06T22:00:00+00:00', date(2027, 6, 7))]:
        instant = datetime.fromisoformat(utc)
        class Clock:
            @staticmethod
            def now(tz):
                return instant.astimezone(tz)
        monkeypatch.setattr(kickoff, 'datetime', Clock)
        assert kickoff.today() == expected
