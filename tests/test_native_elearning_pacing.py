"""Playback speed is a course policy; wall time and watched media stay distinct."""
import json
from pathlib import Path
from tests import test_native_elearning as tracking_tests
from elearning_native.videos import activity_playback_policy


class TestVTCPacing:
    def setup_method(self):
        self.case = tracking_tests.NativeTrackingTests(methodName='runTest')
        self.case.setUp()
        self.store = self.case.store
        self.access = {**self.case.access, 'course_id': 'academy-vtc-e',
                       'course_version': '20261010-vtc-v6-pedagogie'}
        self.policy = {'capsule': {'rates': (.85, 1), 'pauses': [
            {'at_seconds': 272, 'duration_seconds': 4},
        ]}}
        self.duration = 510

    def teardown_method(self):
        self.case.tearDown()

    def start(self, access=None, when=0):
        return self.store.start_tracking(access or self.access, tab_id='pacing',
            activity_id='lesson', now_epoch=1000 + when)['tracking_session_id']

    def ping(self, tracking, elapsed, position, *, rate=.85, playing=True, ended=False,
             access=None, visible=True, focused=True, age=None):
        age = elapsed if age is None else age
        return self.store.heartbeat(access or self.access, tracking, activity_id='lesson',
            now_epoch=1000 + elapsed, visible=visible, focused=focused,
            recent_activity=age < 300, media_playing=playing, interaction_age_seconds=age,
            video_requirements={'capsule': self.duration}, video_playback_policy=self.policy,
            video_samples=[dict(id='capsule', position=position, rate=rate, playing=playing, ended=ended)])

    def record(self, result):
        return result['progress']['video_progress']['lesson']['capsule']

    def test_slow_video_credits_wall_time_and_finishes_after_ten_minutes(self):
        tracking = self.start()
        self.ping(tracking, 0, 0)
        for elapsed in range(4, 600, 4):
            result = self.ping(tracking, elapsed, round(elapsed * .85, 3))
            assert result['media_active']
            assert not result['video_resync']
            assert abs(result['progress']['active_seconds'] - elapsed) < .01
            assert self.record(result)['watched_seconds'] == round(elapsed * .85, 3)
        result = self.ping(tracking, 600, 510, playing=False, ended=True)
        assert self.record(result)['completed']
        assert result['progress']['active_seconds'] == 600
        assert self.ping(tracking, 620, 510, playing=False, ended=True)['credited_seconds'] == 0

    def test_rate_changes_close_previous_rate_interval_without_resetting_progress(self):
        tracking = self.start()
        self.ping(tracking, 0, 0)
        changed = self.ping(tracking, 4, 3.4, rate=1)
        assert self.record(changed)['watched_seconds'] == 3.4
        faster = self.ping(tracking, 8, 7.4, rate=1)
        assert not faster['video_resync']
        assert faster['progress']['active_seconds'] == 8
        self.ping(tracking, 8, 7.4, rate=.85)
        slower = self.ping(tracking, 12, 10.8)
        assert self.record(slower)['watched_seconds'] == 10.8
        assert slower['progress']['active_seconds'] == 12

    def test_configured_pause_after_idle_resumes_without_counting_silence(self):
        tracking = self.start()
        self.ping(tracking, 0, 0)
        for elapsed in range(4, 320, 4):
            self.ping(tracking, elapsed, round(elapsed * .85, 3))
        paused = self.ping(tracking, 320, 272, playing=False)
        assert paused['active'] and not paused['media_active']
        assert paused['progress']['active_seconds'] == 320
        still = self.ping(tracking, 323, 272, playing=False)
        assert still['active'] and still['credited_seconds'] == 0
        resumed = self.ping(tracking, 324, 272)
        assert resumed['active'] and resumed['credited_seconds'] == 0
        playing = self.ping(tracking, 328, 275.4)
        assert playing['media_active'] and not playing['video_resync']
        assert playing['progress']['active_seconds'] == 324
        assert self.record(playing)['watched_seconds'] == 275.4

    def test_pause_grace_expires_and_hidden_page_revokes_it(self):
        for hidden in (False, True):
            access = {**self.access, 'trainee_id': str(hidden)}
            tracking = self.start(access)
            self.policy['capsule']['pauses'][0]['at_seconds'] = 3.4
            self.ping(tracking, 0, 0, access=access, age=296)
            self.ping(tracking, 4, 3.4, access=access, age=300, playing=False)
            if hidden:
                self.ping(tracking, 5, 3.4, access=access, age=301, playing=False, visible=False)
            result = self.ping(tracking, 6 if hidden else 12, 3.4, access=access, age=310)
            assert not result['active']
            assert result['credited_seconds'] == 0

    def test_speed_spoof_buffering_jumps_and_duplicate_tabs_stay_blocked(self):
        for condition in ('fast', 'stalled', 'jump', 'second-tab', 'old-course'):
            access = {**self.access, 'trainee_id': condition}
            if condition == 'old-course': access['course_id'] = 'aps-module'
            tracking = self.start(access)
            rate = 1 if condition == 'old-course' else .85
            self.ping(tracking, 0, 0, access=access, age=296, rate=rate)
            position = 4 if rate == 1 else 3.4
            self.ping(tracking, 4, position, access=access, age=300, rate=rate)
            args = dict(access=access, age=304)
            if condition == 'fast': args['rate'] = 2; position += 8
            if condition == 'jump': position += 100
            if condition == 'old-course': position += 3.4
            if condition == 'second-tab':
                tracking = self.start(access, when=4)
                args['age'] = 0
                result = self.ping(tracking, 4, position, **args)
                assert result['duplicate']
                position += 3.4
            result = self.ping(tracking, 8, position, **args)
            assert not result['media_active']
            assert result['credited_seconds'] == 0
            assert not self.record(result)['completed']

    def test_reloaded_progress_and_completed_video_survive_rate_changes(self):
        tracking = self.start()
        self.ping(tracking, 0, 0)
        self.ping(tracking, 4, 3.4)
        self.ping(tracking, 4, 3.4, playing=False, visible=False)
        reloaded = self.start(when=8)
        self.ping(reloaded, 8, 3.4, rate=1, age=0)
        result = self.ping(reloaded, 12, 7.4, rate=1, age=4)
        assert self.record(result)['watched_seconds'] == 7.4
        assert not result['video_resync']

    def test_all_eight_real_timelines_finish_with_all_105_pauses_and_rate_switches(self):
        root = Path(__file__).resolve().parents[1] / 'elearning_native' / 'vtc'
        pauses = json.loads((root / 'video_learning_pauses_v9.json').read_text())['modules']
        media = json.loads((root / 'video_pacing_v9.json').read_text())['modules']
        count = 0
        for letter, module in pauses.items():
            self.access = {**self.access, 'course_id': f'academy-vtc-{letter.lower()}'}
            self.duration = media[letter]['duration_seconds']
            self.policy = {'capsule': {'rates': (.85, 1), 'pauses': module['pauses']}}
            tracking = self.start()
            elapsed, position, rate, total_paused = 0., 0., .85, 0.
            self.ping(tracking, elapsed, position, rate=rate)
            targets = [*module['pauses'], {'at_seconds': self.duration, 'duration_seconds': 0}]
            for index, pause in enumerate(targets):
                target = pause['at_seconds']
                while position < target - .000001:
                    next_position = min(target, position + 4 * rate)
                    elapsed += (next_position - position) / rate
                    position = next_position
                    at_target = abs(position - target) < .000001
                    result = self.ping(tracking, elapsed, position, rate=rate,
                        playing=not at_target, ended=at_target and not pause['duration_seconds'])
                    assert not result['video_resync'], (letter, target, result)
                    assert self.record(result)['watched_seconds'] >= position - .01
                if pause['duration_seconds']:
                    count += 1
                    total_paused += pause['duration_seconds']
                    elapsed += pause['duration_seconds']
                    rate = 1 if index % 2 else .85
                    self.ping(tracking, elapsed, position, rate=rate)
            assert self.record(result)['completed'], letter
            assert elapsed - total_paused - .01 <= result['progress']['active_seconds'] <= elapsed + .01
        assert count == 105


def test_policy_is_read_only_and_limited_to_reviewed_vtc_editions():
    video = {'id': 'capsule', 'required': True, 'duration_seconds': 20,
             'default_playback_rate': .85, 'allowed_playback_rates': [.85, 1],
             'learning_pauses': [{'at_seconds': 10, 'duration_seconds': 4, 'message': 'Retenez cette notion.'}]}
    course = {'id': 'academy-vtc-a', 'version': '20261010-vtc-v6-pedagogie',
              'sections': [{'activities': [{'id': 'lesson', 'blocks': [{'video': video}]}]}]}
    assert activity_playback_policy(course, 'lesson')['capsule']['rates'] == (.85, 1)
    assert not activity_playback_policy(course, 'other')
    assert not activity_playback_policy({**course, 'id': 'aps'}, 'lesson')
    assert not activity_playback_policy({**course, 'version': '20261006-vtc-v3-105h'}, 'lesson')
