import copy
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

import app
import afc_schedule


@pytest.fixture
def bundle(monkeypatch, tmp_path):
    paths = {}
    for name in ('end', 'driver', 'stu'):
        pdf, docx = tmp_path / f'{name}.pdf', tmp_path / f'{name}.docx'
        pdf.write_bytes((name+' PDF').encode()); docx.write_bytes(b'docx')
        paths[name] = str(docx), str(pdf)
    monkeypatch.setattr(app, '_generate_aps_end_attestation_files', lambda *args: paths['end'])
    driver = Mock(return_value=paths['driver']); stu = Mock(return_value=paths['stu'])
    monkeypatch.setattr(app, '_generate_a3p_driver_attestation_files', driver)
    monkeypatch.setattr(app, '_generate_a3p_stu_attestation_files', stu)
    return paths, driver, stu


@pytest.mark.parametrize('kind,count', [('A3P',3),('APS',1),('SSIAP',1),('MAC A3P',1),('A3P VAE',1)])
def test_attachment_scope_and_complete_bundle(bundle, kind, count):
    paths, driver, stu = bundle
    attachments, record = app._end_attestation_attachments({'training_type':kind}, {}, 'S', 'T', paths['end'][1])
    assert len(attachments) == count
    assert bool(record) == (count == 3)
    assert driver.call_count == stu.call_count == (count == 3)
    if record:
        assert record['stu']['pdf_path'] == paths['stu'][1]


@pytest.mark.parametrize('fail_stu', [False, True])
def test_manual_end_send_attaches_three_or_sends_nothing(bundle, monkeypatch, fail_stu):
    paths, _, stu = bundle
    if fail_stu:stu.side_effect = RuntimeError('STU generation failed')
    trainee = {'id':'T','first_name':'Camille','last_name':'MARTIN','email':'camille@example.test'}
    training = {'id':'S','training_type':'A3P','date_start':'2026-09-01','date_end':'2026-10-24','trainees':[trainee]}
    monkeypatch.setattr(app, 'load_data', lambda **kwargs:{'sessions':[training]})
    monkeypatch.setattr(app, 'save_data', lambda data:None)
    monkeypatch.setattr(app, '_store_public_file_token', lambda path:'test-token')
    send = Mock(return_value=True); monkeypatch.setattr(app,'brevo_send_email',send)
    client=app.app.test_client()
    with client.session_transaction() as cookie:
        cookie.update(admin_logged_in=True,admin_role='admin')
    response=client.post('/admin/sessions/S/stagiaires/T/attestation-fin-aps/send')
    assert response.status_code == (400 if fail_stu else 200)
    if fail_stu:
        send.assert_not_called()
        assert not trainee.get('attestation_fin_aps_sent_at')
    else:
        assert len(send.call_args.kwargs['attachments']) == 3
        assert 'STU' in send.call_args.args[2]
        assert trainee['a3p_driver_attestation']['stu']['pdf_path'] == paths['stu'][1]


def test_afc_specific_context_zero_contribution_and_full_course():
    training={'training_type':'APS','name':'AFC APS + SSIAP','date_start':'2026-11-16','date_end':'2027-02-15','exam_date':'2026-12-21','ssiap_exam_date':'2027-02-16'}
    trainee={'first_name':'Camille','last_name':'MARTIN','email':'camille@example.test','training_date_start':'2026-11-18','afc_ran_hours':40,'personal_amount':'1234','cpf_amount':'5000'}
    before=copy.deepcopy(trainee)
    config=app._automation_document_config(training)
    assert config['entry_template']=='attestationentreeafc.docx'
    assert config['end_template']=='attestationfinafc.docx'
    for build in (app._aps_convention_replacements,app._build_aps_entry_attestation_context,app._build_aps_end_attestation_context,app._build_aps_convocation_context):
        ctx=build(training,trainee)
        assert ctx['date_debut_formation']=='18/11/2026'
        assert ctx['date_fin_formation']=='15/02/2027'
        assert ctx['afc_total_duration']=='379 h'
        assert ctx['montant_financement_personnel_eur']=='0 €'
        assert 'SST' in ctx['formation_nom'] and 'Habilitation électrique' in ctx['formation_nom']
    app._apply_convention_financing_payload(trainee, {'personal_amount':'9999'}, training)
    assert trainee == before


def test_a3p_templates_keep_learner_name_and_distinguish_module_duration():
    for name in ('attestationconducteura3p.docx','attestationstua3p.docx'):
        with ZipFile(Path(app.app.root_path)/'templates_word'/name) as archive:
            text=archive.read('word/document.xml').decode()
            assert '{{ nom_complet }}' in text
            assert 'Période du parcours A3P' in text
            assert ('14 heures' if name=='attestationstua3p.docx' else 'Durée du parcours A3P') in text
