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


def test_edit_source_is_atomic_scoped_and_immediately_visible(monkeypatch):
    candidate = {'id': 'one', 'identifiant_ft': '0000011A', 'archived': True}
    enrolled = {'id': 'a', 'last_name': 'Alpha', 'first_name': 'Zoé', 'afc_candidate_id': 'one',
                'identifiant_ft': 'old copy', 'afc_ran_hours': 54}
    other = {'id': 'b', 'last_name': 'Bêta', 'first_name': 'Noé', 'identifiant_ft': '1234567T - 032'}
    training = {'id': 's', 'name': 'AFC APS novembre', **DATES, 'trainees': [enrolled, other]}
    data = {'sessions': [training], 'afc': {'candidates': [candidate]}}
    monkeypatch.setenv('AFC_ATTENDANCE_SYNC_TOKEN', 'test-attendance')
    monkeypatch.setattr(app, 'load_data', lambda **kw: data)
    monkeypatch.setattr(app, '_atomic_update_data', lambda mutator: mutator(data))
    client = app.app.test_client()
    def edit(changes, previous, student='a', source='s', auth=AUTH):
        payload = {'studentId': student, 'sourceSessionId': source, 'changes': changes, 'previous': previous}
        return client.patch(URL, query_string=DATES, headers=auth, json=payload)
    def read():
        return client.get(URL, query_string=DATES, headers=AUTH).json['students'][0]
    before = deepcopy(data)
    for changes, previous, code in [
        ({'france_travail_id': '1234567T'}, {'france_travail_id': '0000011A'}, 400),
        ({'entryDate': '2029-02-01', 'ranHours': 40}, {'entryDate': DATES['date_start'], 'ranHours': 54}, 400),
        ({'exitDate': '2027-02-10'}, {'exitDate': DATES['date_end']}, 400),
        ({'entryDate': '2026-11-18'}, {'entryDate': '2026-11-10'}, 409),
        ({'ranHours': False}, {'ranHours': 54}, 400),
        ({'france_travail_id': '0000001B'}, {}, 400),
    ]:
        assert edit(changes, previous).status_code == code
        assert data == before
    assert edit({'ranHours': 40}, {'ranHours': 54}, auth={}).status_code == 403
    assert edit({'ranHours': 40}, {'ranHours': 54}, student='absent').status_code == 409
    assert edit({'ranHours': 40}, {'ranHours': 54}, source='wrong-session').status_code == 409
    assert data == before
    changes = {'france_travail_id': '0000234b-012', 'entryDate': '2026-11-18', 'ranHours': 40}
    previous = {'france_travail_id': '0000011A', 'entryDate': DATES['date_start'], 'ranHours': 54}
    saved = edit(changes, previous)
    assert saved.status_code == 200 and saved.json['student'] == read()
    assert enrolled['identifiant_ft'] == candidate['identifiant_ft'] == '0000234B - 012'
    assert enrolled['training_date_start'] == '2026-11-18' and enrolled['afc_ran_hours'] == 40
    assert edit(changes, previous).status_code == 200  # retry after a lost response
    assert edit({'ranHours': 0}, {'ranHours': 54}).status_code == 409
    assert edit({'france_travail_id': ''}, {'france_travail_id': '0000234B - 012'}).status_code == 200
    assert read()['france_travail_id'] == candidate['identifiant_ft'] == ''
    assert other == before['sessions'][0]['trainees'][1]


def test_edit_legacy_registration_without_changing_an_inferred_candidate(monkeypatch):
    legacy = {'nom': 'Martin', 'prenom': 'Zoé', 'email': 'zoe@example.test', 'unknown_field': 'preserve'}
    training = {'id': 's', 'name': 'AFC APS', **DATES, 'stagiaires': [legacy]}
    candidate = {'id': 'c', 'nom': 'Martin', 'prenom': 'Zoé', 'email': 'zoe@example.test', 'identifiant_ft': '7654321X'}
    data = {'sessions': [training], 'afc': {'candidates': [candidate]}}
    monkeypatch.setenv('AFC_ATTENDANCE_SYNC_TOKEN', 'test-attendance')
    monkeypatch.setattr(app, 'load_data', lambda **kw: data)
    monkeypatch.setattr(app, '_atomic_update_data', lambda f: f(data))
    client = app.app.test_client()
    def read():
        return client.get(URL, query_string={'session_id': 's'}, headers=AUTH).json['students'][0]
    row = read()
    assert row['id'] == read()['id'] and row['france_travail_id'] == '7654321X'
    def edit(value, previous):
        return client.patch(URL, query_string={'session_id': 's'}, headers=AUTH, json={
            'sourceSessionId': 's', 'studentId': row['id'], 'changes': {'france_travail_id': value},
            'previous': {'france_travail_id': previous}})
    assert edit('', '7654321X').status_code == 200
    assert read()['france_travail_id'] == ''
    assert edit('00000001234', '').status_code == 200
    assert read()['france_travail_id'] == '00000001234'
    assert candidate['identifiant_ft'] == '7654321X' and legacy['unknown_field'] == 'preserve'
    legacy['inscription_annulee'] = True
    assert edit('00000004567','00000001234').status_code == 409
