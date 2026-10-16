"""Curriculum, version and learner gating regressions for the complete A3P edition."""
import copy
import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch
import pytest
from elearning_native import a3p, a3p_v4, a3p_v3, a3p_v2
from elearning_native.practice import public_practice, grade_practice
from elearning_native.paths import project_course
from elearning_native.videos import course_videos, video_blocker
from elearning_native.lesson_timing import lesson_pages
from scripts.a3p_157.compile import all_cards, validate_complete


@pytest.fixture
def curriculum():
    # Only structural unit tests use synthetic durations. Publication separately
    # requires the full measured manifest, decoded media and content hashes.
    rows=all_cards()
    path=a3p.ROOT/'v4/media_manifest.json'
    if path.is_file():metadata=json.loads(path.read_text())
    else:metadata={r['id']:{'id':r['id']+'-video','title':r['title'],'duration_seconds':400.,'narration_seconds':398.,
        'required':True,'burned_captions':True,'src':'media/a3p/v4/'+r['id']+'.mp4',
        'poster':'media/a3p/v4/'+r['id']+'.jpg','captions':'media/a3p/v4/'+r['id']+'.vtt'} for r in rows}
    a3p_v4._course.cache_clear()
    with patch.object(a3p_v4,'media',return_value=metadata):
        yield [a3p.load_bundled_course(cid) for cid in a3p.curriculum_ids()]
    a3p_v4._course.cache_clear()


def test_40_objectives_exact_157h30(curriculum):
    rows=all_cards();validate_complete(rows)
    actual=Counter()
    assert sum(c['planned_minutes'] for c in curriculum)==9450
    for c in curriculum:
        projected=project_course(c,{'required_minutes':c['required_minutes']})
        assert sum(a['planned_minutes'] for s in projected['sections'] for a in s['activities'])==c['required_minutes']
        assert all(s['delivery']=='distance' for s in projected['sections'])
        for s in projected['sections']:
            actual[s['objective_id']]+=sum(a['planned_minutes'] for a in s['activities'])
            assert len(s['activities'])==5
    assert actual==Counter({r['id']:r['minimum_minutes'] for r in a3p._review()['eligible_objectives']})


def test_160_required_videos_and_no_skip(curriculum):
    count=0
    for course in curriculum:
        projected=project_course(course,{'required_minutes':course['required_minutes']})
        requirements=course_videos(projected);count+=len(requirements)
        first=projected['sections'][0]
        assert not video_blocker(projected,{},first['activities'][0]['id'])
        assert video_blocker(projected,{},first['activities'][2]['id'])==first['activities'][1]['id']
        assert all(len(v)==1 for v in requirements.values())
    assert count==160


def test_cases_are_distinct_click_only_and_answers_remain_private(curriculum):
    contexts=set();decisions=0
    for c in curriculum:
        for s in c['sections']:
            if s['delivery']!='distance':continue
            a=s['activities'][2];p=a['practice'];assert 'workbook' not in a
            assert {e['kind'] for e in p['exercises']}=={'classification','matching','single','order'}
            contexts.add(p['documents'][0]['text']+' '+p['documents'][-1]['text'])
            public=public_practice(p)
            assert 'answer' not in json.dumps(public) and 'explanation' not in json.dumps(public)
            answers={e['id']:e['answer'] if e['kind']=='single' else {r['id']:r['answer'] for r in e['rows']} for e in p['exercises']}
            assert grade_practice(p,answers)['correct']
            changed=next(e for e in p['exercises'] if e['kind']=='single')
            bad=copy.deepcopy(answers);bad[changed['id']]=next(o['id'] for o in changed['options'] if o['id']!=changed['answer'])
            assert not grade_practice(p,bad)['correct']
            decisions+=sum(len(e.get('rows',[])) or 1 for e in p['exercises'])
    assert len(contexts)==160 and decisions==2720


def test_historical_editions_remain_unchanged(curriculum):
    for provider in (a3p_v2,a3p_v3):
        for cid in provider.curriculum_ids():
            assert a3p.load_bundled_course(cid,provider.VERSION)==provider.load_bundled_course(cid,provider.VERSION)
    assert a3p.legacy.VERSION in a3p.SUPPORTED_VERSIONS
    assert a3p.load_bundled_course('academy-a3p-02','invalid') is None


def test_course_pages_and_corrected_quizzes(curriculum):
    for c in curriculum:
        for s in c['sections']:
            if s['delivery']!='distance':continue
            lesson,film,workshop,quiz,recap=s['activities']
            assert lesson_pages(c,lesson)
            assert all(any(a['is_correct'] for a in g['answers']) for g in quiz['answer_groups'])
            assert quiz['explanation'] and quiz['a3p']['delivery']=='distance'
            assert all(a['planned_minutes']>0 for a in s['activities'])
            assert sum(a['planned_minutes'] for a in s['activities'])==s['planned_minutes']

from tests.test_shared_lesson_timing import case
from elearning_native.store import NativeElearningStore
import re


def test_every_new_workshop_renders_and_server_grades_without_tracking(curriculum,case):
    case._admin_login()
    count=0
    for course in curriculum:
        for section in course['sections']:
            if section['delivery']!='distance':continue
            activity=section['activities'][2]
            response=case.client.get('/admin/elearning/courses/'+course['id']+'/preview',
                query_string={'version':a3p.VERSION,'activity':activity['id']})
            assert response.status_code==200
            assert '<textarea' not in response.text and 'contenteditable=' not in response.text
            assert 'Revoir les pièces du dossier' in response.text
            cfg=json.loads(re.search(r'<script id="nativePreviewConfig" type="application/json">(.*?)</script>',response.text,re.S).group(1))
            public=json.loads(re.search(r'<script id="apsPracticeConfig" type="application/json">(.*?)</script>',response.text,re.S).group(1))
            assert 'answer' not in json.dumps(public['practice'])
            ex=activity['practice']['exercises'][0]
            answer={r['id']:r['answer'] for r in ex['rows']}
            with case.client.session_transaction() as session:csrf=session['native_elearning_csrf']
            payload={'practice_step':ex['id'],'practice_answers':{ex['id']:answer}}
            assert case.client.post(cfg['answerUrl'],json=payload).status_code==403
            result=case.client.post(cfg['answerUrl'],json=payload,headers={'X-Elearning-CSRF':csrf})
            assert result.status_code==200 and result.json['correct']
            count+=1
    assert count==160
    assert not (case.persist_dir/'native_elearning/tracking.sqlite3').exists()


def test_course_first_learner_cannot_skip_or_receive_planned_time(curriculum,case):
    c=curriculum[0];lesson,film,workshop,quiz,recap=c['sections'][0]['activities']
    case.data['sessions'][0].update(training_type='A3P',aps_native_modules=[{
        'course_id':c['id'],'course_version':c['version'],'required_minutes':c['required_minutes']}])
    case._public_login();url='/espace/public-token/elearning/'+c['id']
    response=case.client.get(url);assert response.status_code==200
    cfg=case._player_config(response);assert cfg['activityId']==lesson['id']
    assert case._api_post(cfg['completeUrl'],cfg).status_code==409
    requested=case.client.get(url,query_string={'activity':film['id']})
    assert requested.status_code == 200
    assert case._player_config(requested)['activityId'] == lesson['id']
    assert case._api_post('/api/elearning/v1/activities/'+workshop['id']+'/complete',cfg).status_code==409
    store=NativeElearningStore(case.persist_dir/'native_elearning/tracking.sqlite3')
    access={'session_id':'session-aps','trainee_id':'trainee-1','course_id':c['id'],'course_version':c['version']}
    progress=store.get_progress(access)
    assert progress['active_seconds']==0 and not progress['completed_activity_ids']


def test_latest_catalog_and_exam_links_target_existing_sequences(curriculum,case):
    case._admin_login()
    response=case.client.get('/admin/elearning/a3p');assert response.status_code==200
    for label in ('160','168','157 h 30','2 720'):
        assert label.replace(' ','') in response.text.replace(' ','')
    assert 'durée globale à compléter' not in response.text
    from elearning_native.exams import load_exam
    exam=load_exam('a3p-module-02',a3p.VERSION)
    with case.client.session_transaction() as session:csrf=session['native_elearning_csrf']
    response=case.client.post('/api/admin/elearning/exams/a3p-module-02',
        json={'version':a3p.VERSION,'answers':{q['id']:q['answer'] for q in exam['questions']}},headers={'X-Elearning-CSRF':csrf})
    assert response.status_code==200
    links={link['url'] for correction in response.json['result']['corrections'] for link in correction['lesson_links']}
    assert links and all('a3p-v4-' in link for link in links)
    for link in links:assert case.client.get(link).status_code==200


def test_presentation_preserves_all_preexisting_reading_ledgers():
    # Captured from test-v2 before the APS presentation refresh: all three
    # assignable A3P editions, 388 lessons, including in-person preparation.
    import hashlib
    ledgers={}
    for version in a3p.SUPPORTED_VERSIONS[1:]:
        for cid in a3p.curriculum_ids():
            course=a3p.load_bundled_course(cid,version)
            for section in course['sections']:
                for activity in section['activities']:
                    pages=lesson_pages(course,activity)
                    if pages:ledgers[version+':'+cid+':'+activity['id']]=pages
    assert len(ledgers)==388
    assert hashlib.sha256(json.dumps(ledgers,ensure_ascii=False,sort_keys=True).encode()).hexdigest()==\
        '02dc7baae6b4590f5335c57f45b3a2d2f41dd1961077549e734160ed4f94df4e'
