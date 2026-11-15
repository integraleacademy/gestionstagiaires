from copy import deepcopy

import app


URL = '/api/integrations/plateformegestion/afc-attendance'
DATES = {'date_start': '2026-11-16', 'date_end': '2027-02-15'}
AUTH = {'Authorization': 'Bearer test-attendance'}


def test_feed_uses_active_enrolments_effective_dates_and_linked_identifiers(monkeypatch):
    people = [
        {'id': 'a', 'last_name': 'Alpha', 'first_name': 'Zoé', 'afc_candidate_id': 'c',
         'identifiant_ft': 'ancienne valeur', 'training_date_start': '2026-11-26',
         'training_date_end': '2026-12-01', 'afc_ran_hours': 0},
        {'id': 'b', 'last_name': 'Bêta', 'first_name': 'Noé', 'email': 'b@example.test'},
        {'id': 'x', 'last_name': 'Annulé', 'first_name': 'X', 'registration_cancelled': True},
        {'id': 'd', 'last_name': 'Bêta', 'first_name': 'Noé', 'email': 'homonyme@example.test'},
    ]
    training = {'id': 'source', 'name': 'AFC APS', 'trainees': people, **DATES}
    data = {'sessions': [training, {**training, 'id': 'autre', 'partner_id': 'partner'}],
            'afc': {'candidates': [
                {'id': 'c', 'identifiant_ft': '00123A', 'archived': True},
                {'id': 'old', 'nom': 'Beta', 'prenom': 'Noé', 'email': 'b@example.test', 'identifiant_ft': '00456B'},
            ]}}
    before = deepcopy(data)
    monkeypatch.setenv('AFC_ATTENDANCE_SYNC_TOKEN', 'test-attendance')
    monkeypatch.setattr(app, 'load_data', lambda **kw: data)
    client = app.app.test_client()
    assert client.get(URL, query_string=DATES).status_code == 403
    response = client.get(URL, headers=AUTH, query_string=DATES)
    assert response.status_code == 200
    assert 'no-store' in response.headers['Cache-Control']
    rows = {r['id']: r for r in response.json['students']}
    assert set(rows) == {'a', 'b', 'd'}
    assert rows['a'] == {'id': 'a', 'firstName': 'Zoé', 'lastName': 'Alpha',
                         'entryDate': '2026-11-26', 'exitDate': DATES['date_end'],
                         'france_travail_id': '00123A', 'ranHours': 0}
    assert rows['b']['entryDate'] == DATES['date_start']
    assert rows['b']['france_travail_id'] == '00456B'
    assert rows['d']['france_travail_id'] == ''
    assert data == before
    assert client.get(URL, headers=AUTH, query_string={'session_id': 'autre'}).status_code == 404
    data['sessions'].append({**training, 'id': 'other-cohort'})
    assert client.get(URL, headers=AUTH, query_string=DATES).status_code == 409
    assert client.get(URL, headers=AUTH, query_string={'session_id': 'source'}).json['session']['id'] == 'source'
    monkeypatch.delenv('AFC_ATTENDANCE_SYNC_TOKEN')
    assert client.get(URL, headers=AUTH, query_string=DATES).status_code == 403
