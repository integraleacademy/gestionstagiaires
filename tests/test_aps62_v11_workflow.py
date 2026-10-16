"""Check the actual publication guard without Git, network or generated media."""
import ast
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/aps-content-v11.yml'


def python_blocks():
    source = WORKFLOW.read_text()
    return [re.sub(r'^          ', '', body, flags=re.M)
            for body in re.findall(r"          python(?:3)? - <<'PY'\n(.*?)          PY\n", source, re.S)]


class Aps62V11WorkflowTests(unittest.TestCase):
    def guard(self, paths):
        body = next(block for block in python_blocks() if 'protected = (' in block)
        with patch.dict(os.environ, {'GITHUB_SHA': 'reviewed-source'}), patch(
                'subprocess.check_output', return_value=('\n'.join(paths) + '\n').encode()):
            exec(compile(body, str(WORKFLOW), 'exec'), {})

    def test_independent_runtime_and_portal_changes_can_be_integrated(self):
        self.guard([
            'app.py', 'requirements.txt', 'elearning_native/web.py',
            'elearning_native/vtc.py', 'static/js/native-elearning-player.js',
            'elearning_reporting.py', 'templates/manuals/elearning_demo.html',
            'tests/test_elearning_reporting.py',
        ])

    def test_narrations_media_and_publication_rules_cannot_change_during_rendering(self):
        for name in (
            'elearning_native/aps62/manifest.json',
            'elearning_native/aps62/assets/media/aps62/v9/aps62-01-01.mp4',
            'elearning_native/aps62/courses/academy-aps62-01/20261010-aps62-v10.json',
            'scripts/aps62_v10/video_content.py',
            'scripts/aps62_v11/pacing.py',
            'scripts/render_aps62_v5.py',
            'scripts/render_aps62_v9.py',
            'scripts/build_aps62_v11.py',
            'scripts/academy_videos/assets/Manrope-600.ttf',
            'scripts/aps62_v11_release.json',
            '.github/workflows/aps-content-v11.yml',
            'tests/test_aps62_v11_release.py',
        ):
            with self.subTest(path=name), self.assertRaises(AssertionError):
                self.guard([name])

    def test_embedded_python_is_valid(self):
        blocks = python_blocks()
        self.assertGreaterEqual(len(blocks), 6)
        for index, block in enumerate(blocks):
            with self.subTest(block=index):
                ast.parse(block)

    def test_release_uses_fresh_shards_and_new_media_decode(self):
        release = json.loads((ROOT / 'scripts/aps62_v11_release.json').read_text())
        self.assertEqual(release['version'], '20261010-aps62-v11')
        self.assertEqual(release['media_revision'], 9)
        self.assertEqual(release['shards'], 4)
        self.assertFalse(release.get('reuse_artifact_run_id'))
        workflow = WORKFLOW.read_text()
        self.assertIn("APS62_VERIFY_FULL_DECODE: '0'", workflow)
        self.assertIn("APS62_VERIFY_V11_FULL_DECODE: '1'", workflow)
        after_rebase = workflow.split('if ! git rebase origin/test-v2;', 1)[1]
        self.assertIn('APS62_VERIFY_V11_FULL_DECODE=0 python -m pytest', after_rebase)
        self.assertLess(after_rebase.index('python -m pytest'), after_rebase.index('git push'))
        self.assertLess(after_rebase.index('node --test'), after_rebase.index('git push'))
        self.assertNotIn('git push --force', workflow)


if __name__ == '__main__':
    unittest.main()
