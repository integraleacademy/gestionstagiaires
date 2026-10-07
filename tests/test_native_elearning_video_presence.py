"""Long viewing receipts extend presence; flags, pauses and duplicate tabs do not."""
import unittest

from tests import test_native_elearning as tracking_tests


class LongViewingPresenceTests(unittest.TestCase):
    setUp = tracking_tests.NativeTrackingTests.setUp
    tearDown = tracking_tests.NativeTrackingTests.tearDown

    def start(self, access=None, when=1000):
        return self.store.start_tracking(access or self.access, tab_id='video-tab',
            activity_id='lesson-1', now_epoch=when)['tracking_session_id']

    def ping(self, tracking, elapsed, position, *, access=None, age=None, playing=True,
             ended=False, visible=True, focused=True, rate=1, duration=600):
        age = elapsed if age is None else age
        return self.store.heartbeat(access or self.access, tracking,
            activity_id='lesson-1', now_epoch=1000 + elapsed, visible=visible, focused=focused,
            recent_activity=age < 300, media_playing=True, interaction_age_seconds=age,
            video_requirements={'lesson-video': duration},
            video_samples=[dict(id='lesson-video', position=position, playing=playing, ended=ended, rate=rate)])

    def test_ten_minute_video_finishes_without_mouse_and_counts_time_once(self):
        tracking = self.start()
        self.ping(tracking, 0, 0)
        for elapsed in range(4, 600, 4):
            result = self.ping(tracking, elapsed, elapsed)
            self.assertTrue(result['active'], elapsed)
            self.assertTrue(result['media_active'], elapsed)
            self.assertEqual(result['progress']['active_seconds'], elapsed)
            self.assertFalse(result['video_resync'])
        ended = self.ping(tracking, 600, 600, playing=False, ended=True)
        self.assertFalse(ended['active'])
        self.assertEqual(ended['progress']['active_seconds'], 600)
        self.assertTrue(ended['progress']['video_progress']['lesson-1']['lesson-video']['completed'])
        repeat = self.ping(tracking, 620, 600, playing=False, ended=True)
        self.assertEqual(repeat['progress']['active_seconds'], 600)

    def test_stalled_paused_hidden_blurred_fast_and_forged_samples_do_not_extend_presence(self):
        for case in ('stalled', 'paused', 'hidden', 'blurred', 'fast', 'jump', 'repeat', 'disconnected'):
            with self.subTest(case=case):
                access = {**self.access, 'trainee_id': case}
                tracking = self.start(access)
                self.ping(tracking, 0, 0, access=access, age=296)
                self.ping(tracking, 4, 4, access=access, age=300)
                args = dict(access=access, age=304)
                position, elapsed = 4, 8
                if case == 'paused': args['playing'] = False
                if case == 'hidden': args['visible'] = False; position = 8
                if case == 'blurred': args['focused'] = False; position = 8
                if case == 'fast': args['rate'] = 2; position = 12
                if case == 'jump': position = 500
                if case == 'repeat': elapsed = 4
                if case == 'disconnected': elapsed = 604; position = 8; args['age'] = 900
                result = self.ping(tracking, elapsed, position, **args)
                self.assertFalse(result['active'])
                self.assertEqual(result['credited_seconds'], 0)
                self.assertEqual(result['progress']['active_seconds'], 4)

    def test_pause_reverts_to_the_existing_human_interaction_deadline(self):
        tracking = self.start()
        self.ping(tracking, 0, 0, age=290)
        paused = self.ping(tracking, 4, 4, age=294, playing=False)
        self.assertTrue(paused['active'])  # Reading the transcript remains possible.
        expired = self.ping(tracking, 12, 4, age=302, playing=False)
        self.assertFalse(expired['active'])
        self.assertEqual(expired['progress']['active_seconds'], 10)
        resumed = self.ping(tracking, 16, 4, age=0)
        self.assertEqual(resumed['credited_seconds'], 0)
        self.assertTrue(resumed['active'])

    def test_second_tab_and_second_module_cannot_share_long_video_time(self):
        tracking = self.start()
        self.ping(tracking, 0, 0, age=296)
        self.ping(tracking, 4, 4, age=300)
        other = self.start(when=1004)
        duplicate = self.ping(other, 4, 4, age=0)
        self.assertTrue(duplicate['duplicate'])
        forged = self.ping(other, 8, 8, age=4)
        self.assertEqual(forged['credited_seconds'], 0)
        access = {**self.access, 'course_id': 'second-module'}
        second = self.start(access, when=1008)
        self.assertTrue(self.ping(second, 8, 0, access=access, age=0)['duplicate'])
        current = self.ping(tracking, 8, 8, age=304)
        self.assertEqual(current['progress']['active_seconds'], 8)

    def test_jitter_balance_and_review_cannot_create_or_lose_accumulated_time(self):
        tracking = self.start()
        self.ping(tracking, 0, 0, age=299, duration=16)
        for elapsed, position in [(4, 4), (8.35, 8), (12, 12), (16.35, 16)]:
            result = self.ping(tracking, elapsed, position, age=299 + elapsed,
                               duration=16, playing=position < 16, ended=position == 16)
            self.assertFalse(result['video_resync'])
            self.assertEqual(result['progress']['active_seconds'], position)
        self.assertTrue(result['progress']['video_progress']['lesson-1']['lesson-video']['completed'])
        # A chapter selection is a real interaction; subsequent review also
        # relies on advancing receipts, without changing completed viewing.
        self.ping(tracking, 20, 4, age=296, duration=16)
        review = self.ping(tracking, 24, 8, age=300, duration=16)
        self.assertTrue(review['media_active'])
        self.assertEqual(review['progress']['active_seconds'], 20)
        self.assertTrue(review['progress']['video_progress']['lesson-1']['lesson-video']['completed'])


if __name__ == '__main__':
    unittest.main()
