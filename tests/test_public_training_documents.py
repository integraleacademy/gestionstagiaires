from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import app as portal


@pytest.fixture
def learner(tmp_path):
    signed = tmp_path / 'generated_documents' / 'yousign_signed_conventions'
    convocations = tmp_path / 'generated_documents' / 'convocations_aps'
    signed.mkdir(parents=True)
    convocations.mkdir(parents=True)
    trainee = {
        'id': 'T-PUBLIC', 'public_token': 'learner-token',
        'first_name': 'Alice', 'last_name': 'DUPONT', 'birth_date': '1990-01-01',
        'convention_status': 'signed', 'convention_signature': {'status': 'done'},
        'convocation_aps_pdf_token': 'generated_documents/convocations_aps/convocation.pdf',
        'convocation_aps_pdf_path': '/old-disk/convocation.pdf',
        'convocation_aps_sent_at': '2026-10-01T09:00:00Z',
    }
    session = {'id': 'S-PUBLIC', 'name': 'Formation APS', 'training_type': 'APS',
               'date_start': '2026-11-03', 'date_end': '2026-12-08', 'trainees': [trainee]}
    data = {'sessions': [session]}
    client = portal.app.test_client()
    with client.session_transaction() as auth:
        auth['public_auth_learner-token'] = True
    with patch.object(portal, 'load_data', return_value=data), \
         patch.object(portal, 'save_data') as save, \
         patch.object(portal, 'PERSIST_DIR', str(tmp_path)), \
         patch.object(portal, 'YOUSIGN_SIGNED_DIR', str(signed)), \
         patch.object(portal, 'APS_CONVOCATION_DIR', str(convocations)), \
         patch.object(portal, 'brevo_send_email') as mail:
        yield SimpleNamespace(client=client, trainee=trainee, session=session, signed=signed,
                              convocations=convocations, save=save, mail=mail)


def test_signed_convention_opens_and_downloads_without_admin_session(learner):
    path = learner.signed / 'signed.pdf'
    path.write_bytes(b'%PDF-1.4\nsigned')
    learner.trainee['convention_signature']['signed_pdf_path'] = str(path)
    for query, disposition in [('', 'inline'), ('?download=1', 'attachment')]:
        response = learner.client.get('/espace/learner-token/convention/signee.pdf' + query)
        assert response.status_code == 200
        assert response.data == path.read_bytes()
        assert disposition in response.headers['Content-Disposition']
    learner.mail.assert_not_called()


def test_public_signed_convention_recovers_verified_yousign_pdf(learner):
    learner.trainee['convention_signature']['signature_request_id'] = 'request-1'
    with patch.object(portal, '_yousign_is_configured', return_value=True), \
         patch.object(portal, '_yousign_json', return_value={'id': 'request-1', 'status': 'done'}), \
         patch.object(portal, '_yousign_request', return_value=SimpleNamespace(content=b'%PDF-1.4\nrecovered')) as download, \
         patch.object(portal, '_schedule_convocation_after_convention_signed') as schedule:
        response = learner.client.get('/espace/learner-token/convention/signee.pdf?download=1')
    assert response.status_code == 200
    assert response.data == b'%PDF-1.4\nrecovered'
    assert download.call_args.kwargs['params']['version'] == 'completed'
    assert learner.trainee['convention_signature']['signed_pdf_token']
    learner.mail.assert_not_called()
    schedule.assert_not_called()


def test_unsigned_original_is_never_served_as_signed(learner):
    original = learner.signed / 'original.pdf'
    original.write_bytes(b'%PDF-1.4\nunsigned')
    learner.trainee['convention_signature']['unsigned_pdf_path'] = str(original)
    with patch.object(portal, '_yousign_is_configured', return_value=False):
        response = learner.client.get('/espace/learner-token/convention/signee.pdf')
    assert response.status_code == 302
    assert response.location.endswith('/espace/learner-token')
    assert b'unsigned' not in response.data


@pytest.mark.parametrize('path', ['convention/signee.pdf', 'convocation.pdf'])
def test_documents_require_this_learners_login(learner, path):
    with learner.client.session_transaction() as auth:
        auth.clear()
        auth['public_auth_another-token'] = True
    response = learner.client.get('/espace/learner-token/' + path)
    assert response.status_code == 302
    assert response.location.endswith('/espace/learner-token/login')
    assert learner.client.get('/espace/unknown-token/' + path).status_code == 404
    learner.mail.assert_not_called()


def test_missing_convocation_is_regenerated_without_resending(learner):
    def generate(*args):
        path = learner.convocations / 'convocation.pdf'
        path.write_bytes(b'%PDF-1.4\nconvocation')
        return str(path.with_suffix('.docx')), str(path)
    with patch.object(portal, '_generate_aps_convocation_files', side_effect=generate) as generate_pdf:
        response = learner.client.get('/espace/learner-token/convocation.pdf')
    assert response.status_code == 200
    assert response.mimetype == 'application/pdf'
    assert 'attachment' in response.headers['Content-Disposition']
    assert learner.trainee['convocation_aps_sent_at'] == '2026-10-01T09:00:00Z'
    generate_pdf.assert_called_once()
    learner.save.assert_called_once()
    learner.mail.assert_not_called()


def test_moved_convocation_is_found_without_regeneration(learner):
    path = learner.convocations / 'convocation.pdf'
    path.write_bytes(b'%PDF-1.4\noriginal issued file')
    with patch.object(portal, '_generate_aps_convocation_files') as generate:
        response = learner.client.get('/espace/learner-token/convocation.pdf')
    assert response.status_code == 200
    assert response.data == path.read_bytes()
    generate.assert_not_called()


def test_old_missing_link_redirects_to_recovery_but_not_other_trainees_files(learner):
    root = '/espace/learner-token/download/'
    response = learner.client.get(root + learner.trainee['convocation_aps_pdf_token'])
    assert response.status_code == 302
    assert response.location.endswith('/espace/learner-token/convocation.pdf')
    assert learner.client.get(root + 'generated_documents/convocations_aps/other.pdf').status_code == 403


def test_no_convocation_is_created_before_it_has_been_issued(learner):
    for key in list(learner.trainee):
        if key.startswith('convocation_aps_'):
            del learner.trainee[key]
    with patch.object(portal, '_generate_aps_convocation_files') as generate:
        response = learner.client.get('/espace/learner-token/convocation.pdf')
    assert response.status_code == 404
    generate.assert_not_called()


def test_public_city_save_is_uppercase_and_preserves_accents(learner):
    response = learner.client.post('/espace/learner-token/infos/update', json={
        'city': '  Fréjus ', 'birth_city': ' Aix-en-Provence ', 'address': '4 rue du Port',
    })
    assert response.status_code == 200
    assert learner.trainee['city'] == 'FRÉJUS'
    assert learner.trainee['birth_city'] == 'AIX-EN-PROVENCE'
    assert learner.trainee['address'] == '4 rue du Port'


def test_signed_document_buttons_and_recovery_notice_are_visible(learner):
    learner.trainee['public_has_logged_in'] = True
    learner.trainee['city'] = 'Fréjus'
    learner.trainee['birth_city'] = 'Paris'
    with patch.object(portal, '_yousign_is_configured', return_value=False):
        response = learner.client.get('/espace/learner-token/convention/signee.pdf', follow_redirects=True)
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Votre convention signée n’est pas encore disponible' in body
    assert '/espace/learner-token/convention/signee.pdf?download=1' in body
    assert 'id="city" value="FRÉJUS"' in body
    assert 'id="birth_city" value="PARIS"' in body
