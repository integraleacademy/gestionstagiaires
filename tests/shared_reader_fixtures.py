"""Text/UI fixtures from the real courses, including sparse source checkouts.

Media bytes are not needed to test reading. Only the file-presence check for
assets actually tracked in Git may be supplied by the checkout inventory;
source hashes, manifest validation and teaching content remain real.
"""
from contextlib import contextmanager
from pathlib import Path
import subprocess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def published_media_inventory():
    try:
        tracked = set(subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', 'HEAD'], cwd=ROOT, text=True).splitlines())
    except subprocess.CalledProcessError:
        tracked = set()
    original = Path.is_file

    def present(path):
        if original(path):
            return True
        try:
            relative = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return False
        return relative.startswith('elearning_native/vtc/assets/') and relative in tracked

    with patch.object(Path, 'is_file', present):
        yield


def reader_fixtures():
    from flask import Flask, render_template
    from elearning_native import mac_aps, a3p, vtc
    from elearning_native.lesson_timing import lesson_pages
    app = Flask(__name__, template_folder=str(ROOT / 'templates'))
    result = []
    with published_media_inventory(), app.app_context():
        for provider, family, template in ((mac_aps, 'macaps', '_macaps_lesson.html'),
                                           (a3p, 'a3p', '_a3p_lesson.html'),
                                           (vtc, 'vtc', '_vtc_activity.html')):
            for course_id in provider.curriculum_ids():
                course = provider.load_bundled_course(course_id)
                for section in course['sections']:
                    for activity in section['activities']:
                        if activity.get(family, {}).get('kind') != 'lesson':
                            continue
                        markup = render_template(template, activity=activity, course=course)
                        blocks = ''.join('<div data-aps-lesson-page><video></video></div>' for _ in activity.get('blocks', []))
                        result.append({'id': activity['id'], 'family': family, 'html': blocks + markup,
                                       'plan': lesson_pages(course, activity)})
    return result


if __name__ == '__main__':
    import json
    print(json.dumps(reader_fixtures()))
