"""Normal-speed VTC playback preserves media, timing and required watching."""
import copy
import json
import re
import time
from unittest.mock import patch

import pytest
from elearning_native import vtc, vtc_video_quality
from elearning_native.videos import activity_playback_policy
from tests import test_native_elearning_web as fixture


def all_videos(course):
    return [(a,b['video']) for s in course['sections'] for a in s['activities']
            for b in a.get('blocks',[]) if b.get('video')]


def test_all_104_current_videos_are_normal_speed_without_changing_media_or_time():
    n=0
    source=vtc_video_quality.quality_manifest()
    for mod in vtc.curriculum_manifest()['modules']:
        course=vtc.load_bundled_course(mod['id'])
        assert course['vtc_media_revision']==13
        for activity,video in all_videos(course):
            n+=1
            row=source['modules'][mod['id'][-1].upper()] if video['id'].endswith('-capsule') else source['lessons'][activity['vtc']['ref']]
            assert video['default_playback_rate']==1
            assert video['allowed_playback_rates']==[1]
            for key in ('src','duration_seconds','chapters','transcript','learning_pauses','presentation'):
                assert video[key]==row[key]
            if video.get('required'):
                assert activity_playback_policy(course,activity['id'])[video['id']]['rates']==(1,)
    assert n==104


@pytest.mark.parametrize('preview',[True,False])
def test_preview_and_learner_have_one_subtitle_view_and_no_speed_choice(preview):
    case=fixture.NativeElearningWebTests(methodName='runTest');case.setUp()
    try:
        case.data['sessions'][0].update(training_type='VTC',aps_native_course_id='academy-vtc-a',aps_native_course_version=vtc.curriculum_manifest()['version'])
        if preview:
            case._admin_login();url='/admin/elearning/courses/academy-vtc-a/preview?activity=vtc-a-02-cours'
        else:
            case._public_login();url='/espace/public-token/elearning/academy-vtc-a'
        response=case.client.get(url);assert response.status_code==200
        text=response.text
        assert 'Texte de la voix' not in text
        assert 'data-video-caption-toggle' not in text
        assert 'data-playback-rate' not in text
        assert 'Vitesse de lecture' not in text
        assert 'noplaybackrate' in text
        config=json.loads(re.search(r'data-video-pacing-config>(.*?)</script>',text,re.S)[1])
        assert config['default_playback_rate']==1 and config['allowed_playback_rates']==[1]
        assert config['learning_pauses']
        assert 'data-video-companion' in text and 'Agrandir la lecture' in text
        if not preview:
            player=case._player_config(response)
            assert case._api_post(player['completeUrl'],player).status_code==409
    finally:case.tearDown()


def test_one_x_receipts_credit_real_seconds_and_refuse_slower_or_faster_playback():
    case=fixture.NativeElearningWebTests(methodName='runTest');case.setUp()
    try:
        case.data['sessions'][0].update(training_type='VTC',aps_native_course_id='academy-vtc-a',aps_native_course_version=vtc.curriculum_manifest()['version'])
        case._public_login()
        now=[time.time()]
        with patch('elearning_native.store.time.time',side_effect=lambda:now[0]):
            config=case._player_config(case.client.get('/espace/public-token/elearning/academy-vtc-a'))
            vid=next(iter(config['requiredVideos']));aid=config['activityId']
            tr=case._api_post(config['startUrl'],config,activity_id=aid,tab_id='x1-check').json['tracking_session_id']
            def ping(position,rate=1,initial=False):
                return case._api_post(config['heartbeatUrl'],config,tracking_session_id=tr,activity_id=aid,visible=True,focused=True,recent_activity=initial,interaction_age_seconds=299 if initial else 600,media_playing=True,videos=[dict(id=vid,position=position,rate=rate,playing=True,ended=False)])
            assert ping(0,initial=True).status_code==200
            now[0]+=4;r=ping(4);assert r.status_code==200 and r.json['credited_seconds']==4
            assert r.json['progress']['video_progress'][aid][vid]['watched_seconds']==4
            for rate in (.85,2):
                now[0]+=4;r=ping(4+4*rate,rate)
                assert r.status_code==200 and r.json['credited_seconds']==0
                assert not r.json['media_active']
    finally:case.tearDown()
