import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import app as services
import identity_photos as photos

BASE = '/api/admin/sessions/S1/trainees/T1/identity-photo'


@pytest.fixture
def case(monkeypatch, tmp_path):
    original = tmp_path / 'uploads/S1/T1/original.jpg'
    original.parent.mkdir(parents=True)
    image = Image.new('RGB', (1400, 1800), 'blue')
    ImageDraw.Draw(image).rectangle((0, 0, 699, 899), fill='red')
    image.save(original, quality=95)
    payload = {'sessions':[{'id':'S1','training_type':'SSIAP 1','exam_date':'2026-10-28','trainees':[
        {'id':'T1','first_name':'Camille','last_name':'EXEMPLE','identity_photo':'uploads/S1/T1/original.jpg'},
        {'id':'T2','first_name':'Alex','last_name':'AUTRE'}]}]}
    data = tmp_path / 'data.json'
    data.write_text(json.dumps(payload))
    for name, value in [('DATA_FILE',str(data)),('PERSIST_DIR',str(tmp_path)),('UPLOADS_DIR',str(tmp_path/'uploads')),
                        ('BACKUP_SNAPSHOT_BEFORE_SAVE',False),('BACKUP_MIN_INTERVAL_SECONDS',10**9)]:
        monkeypatch.setattr(services, name, value)
    client = services.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role='admin')
    client.get(BASE)
    return client, data, original


def state(case):
    return case[0].get(BASE).json


def stored(case):
    return json.loads(case[1].read_text())['sessions'][0]['trainees'][0]


def crop_data(case, **updates):
    metadata = state(case)
    original = case[0].get(BASE+'/image?original=1')
    return dict(version=2,rotation=0,straighten=0,cx=.5,cy=.5,width=.5,height=.5,
                revision=metadata['revision'],source_hash=original.headers['X-Photo-Source'],**updates)


def post(case, data):
    return case[0].post(BASE+'/crop',json=data,headers={'X-CSRF-Token':state(case)['csrf']})


def test_crop_is_shared_with_diplomas_and_original_is_preserved(case):
    original = case[2].read_bytes()
    before = state(case)
    result = post(case,crop_data(case))
    assert result.status_code == 200
    current = stored(case)
    assert current['identity_photo_original'] == 'uploads/S1/T1/original.jpg'
    assert case[2].read_bytes() == original
    assert result.json['photo_url'] != before['photo_url']
    assert services._ssiap_diploma_photo_path(current).endswith(current['identity_photo'])
    with Image.open(services._ssiap_diploma_photo_path(current)) as image:
        assert image.size == (700,900)
    reloaded = case[0].get(BASE+'/image?original=1')
    assert reloaded.headers['X-Photo-Source'] == hashlib.sha256(original).hexdigest()
    assert json.loads(reloaded.headers['X-Photo-Crop'])['width'] == .5
    assert 'no-store' in reloaded.headers['Cache-Control']
    workspace = case[0].get('/api/admin/sessions/S1/ssiap-exam/diplomas').json
    row = next(row for row in workspace['candidates'] if row['id']=='T1')
    assert row['photo_url'] == result.json['photo_url']
    assert row['photo_api'] == BASE
    assert case[0].get(result.json['photo_url']).status_code == 200


def test_recrop_uses_original_and_reset_restores_original(case):
    assert post(case,crop_data(case)).status_code == 200
    data = crop_data(case)
    data.update(cx=.25,cy=.25,width=.25,height=.25)
    assert post(case,data).status_code == 200
    with Image.open(services._ssiap_diploma_photo_path(stored(case))) as image:
        assert image.size == (350,450)
        r,g,b = image.getpixel((175,225))
        assert r > 240 and g < 10 and b < 10
    data = crop_data(case)
    assert post(case,{'reset':True,'revision':data['revision'],'source_hash':data['source_hash']}).status_code == 200
    assert stored(case)['identity_photo'] == 'uploads/S1/T1/original.jpg'
    assert 'identity_photo_crop' not in stored(case)
    assert 'X-Photo-Crop' not in case[0].get(BASE+'/image?original=1').headers


def test_rotation_and_straightening_match_the_preview_transform():
    image = Image.new('RGB',(1400,1800),'blue')
    ImageDraw.Draw(image).rectangle((0,0,699,899),fill='red')
    crop = photos.validate_crop(dict(version=2,rotation=90,straighten=0,cx=.25,cy=.25,width=.2,height=.2),image)
    result = photos.render_crop(image,crop)
    assert result.width/result.height == 7/9
    assert result.getpixel((result.width//2,result.height//2)) == (255,0,0)
    for angle in (-45,13,45):
        crop = photos.validate_crop(dict(version=2,rotation=270,straighten=angle,cx=.5,cy=.5,width=.2,height=.2),image)
        result = photos.render_crop(image,crop)
        assert result.getpixel((0,0)) != (255,255,255)


@pytest.mark.parametrize('change', [{'cx':-1},{'width':1,'height':1,'straighten':40},{'width':.1},
    {'rotation':1},{'rotation':True},{'straighten':46},{'cx':float('nan')},{'cy':float('inf')},
    {'height':False},{'width':.001,'height':.001},{'version':1}])
def test_invalid_crop_does_not_change_photo(case,change):
    before = stored(case)
    data = crop_data(case); data.update(change)
    assert post(case,data).status_code == 400
    assert stored(case) == before


def test_stale_editor_cannot_overwrite_photo_and_unrelated_edits_are_preserved(case):
    data = crop_data(case)
    payload = json.loads(case[1].read_text())
    payload['sessions'][0]['trainees'][0]['first_name'] = 'Prénom corrigé'
    case[1].write_text(json.dumps(payload))
    assert post(case,data).status_code == 200
    assert stored(case)['first_name'] == 'Prénom corrigé'
    before = stored(case)
    files = set(case[2].parent.rglob('*'))
    assert post(case,data).status_code == 409
    assert stored(case) == before
    assert set(case[2].parent.rglob('*')) == files


def test_changed_original_is_detected_even_if_its_path_did_not_change(case):
    data = crop_data(case)
    Image.new('RGB',(1400,1800),'green').save(case[2])
    assert post(case,data).status_code == 409


def test_upload_replaces_photo_and_clears_previous_crop(case):
    assert post(case,crop_data(case)).status_code == 200
    output = io.BytesIO(); Image.new('RGB',(350,450),'green').save(output,'PNG'); output.seek(0)
    metadata = state(case)
    result = case[0].post(BASE+'/upload',data={'photo':(output,'test.png'),'revision':metadata['revision']},
                          headers={'X-CSRF-Token':metadata['csrf']})
    assert result.status_code == 200
    assert 'identity_photo_crop' not in stored(case)
    assert 'identity_photo_original' not in stored(case)
    assert case[2].is_file()
    with Image.open(services._ssiap_diploma_photo_path(stored(case))) as image:
        assert image.size == (350,450)
    result = case[0].post(BASE+'/upload',data={'photo':(io.BytesIO(b'not an image'),'fake.jpg'),'revision':state(case)['revision']},
                          headers={'X-CSRF-Token':state(case)['csrf']})
    assert result.status_code == 400


def test_authentication_csrf_readonly_and_trainee_scope(case):
    data = crop_data(case)
    assert case[0].post(BASE+'/crop',json=data).status_code == 403
    assert case[0].get(BASE.replace('/S1/','/OTHER/')).status_code == 404
    assert case[0].get(BASE.replace('/T1/','/UNKNOWN/')).status_code == 404
    assert not case[0].get(BASE.replace('/T1/','/T2/')).json['photo_available']
    with case[0].session_transaction() as session:
        session['admin_role'] = 'viewer'
    assert state(case)['read_only']
    assert case[0].get(BASE+'/image').status_code == 200
    assert post(case,data).status_code == 403
    assert case[0].post(BASE+'/upload',headers={'X-CSRF-Token':state(case)['csrf']}).status_code == 403
    with case[0].session_transaction() as session:
        session.clear()
    assert case[0].get(BASE).status_code == 401


def test_exif_orientation_is_applied_before_crop():
    image = Image.new('RGB',(450,350),'red')
    exif = image.getexif(); exif[274] = 6
    output=io.BytesIO();image.save(output,'JPEG',exif=exif)
    assert photos.decode_photo(output.getvalue()).size == (350,450)


def test_partner_cannot_access_another_centres_photo(case):
    data = json.loads(case[1].read_text())
    data['sessions'][0]['partner_id'] = 'partner-other-uuid'
    case[1].write_text(json.dumps(data))
    with case[0].session_transaction() as session:
        session.update(admin_role='partner_admin',partner_id='partner-own-uuid')
    assert case[0].get(BASE).status_code == 404
    assert case[0].get(BASE+'/image?original=1').status_code == 404


@pytest.mark.parametrize('training_type', services.FORMATION_TYPES)
def test_profile_and_crop_are_available_for_every_training(case, training_type):
    data = json.loads(case[1].read_text())
    data['sessions'][0]['training_type'] = training_type
    case[1].write_text(json.dumps(data))
    response = case[0].get('/admin/sessions/S1/stagiaires/T1')
    assert response.status_code == 200
    assert 'data-identity-photo-edit' in response.text
    assert 'id="identityPhotoDialog"' in response.text
    assert 'photoForm' not in response.text
    assert post(case, crop_data(case)).status_code == 200
    assert stored(case)['identity_photo_original'].endswith('original.jpg')


def test_hdr_jpeg_mpo_displays_and_crops_primary_portrait_without_modifying_source(case):
    output = io.BytesIO()
    Image.new('RGB', (1400,1800), 'red').save(output, 'MPO', save_all=True,
        append_images=[Image.new('RGB', (140,180), 'blue')])
    original = output.getvalue()
    case[2].write_bytes(original)
    with Image.open(case[2]) as check:
        assert check.format == 'MPO' and check.n_frames == 2
    for url in (BASE+'/image', BASE+'/image?original=1'):
        response = case[0].get(url)
        assert response.status_code == 200
        with Image.open(io.BytesIO(response.data)) as portrait:
            assert portrait.format == 'JPEG'
            r,g,b = portrait.getpixel((portrait.width//2, portrait.height//2))
            assert r > 240 and g < 10 and b < 10
    assert post(case, crop_data(case)).status_code == 200
    assert case[2].read_bytes() == original
    with Image.open(services._ssiap_diploma_photo_path(stored(case))) as portrait:
        assert portrait.size == (700,900)
        assert portrait.getpixel((350,450))[0] > 240
