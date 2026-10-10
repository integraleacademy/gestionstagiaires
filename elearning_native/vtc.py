"""Immutable VTC curriculum, independent of APS editions and learner records."""
from pathlib import Path
from functools import lru_cache
import copy, json
ROOT=Path(__file__).parent/'vtc'

# This is a pronunciation repair, not a new learner assignment. The replacement
# keeps every chapter boundary and the exact mandatory-viewing duration.
_BILINGUAL_VERSIONS = frozenset({
    '20261007-vtc-v4-visuals',
    '20261007-vtc-v5-annales',
    '20261010-vtc-v6-pedagogie',
})


@lru_cache(maxsize=1)
def _bilingual_video():
    return json.loads((ROOT / 'video_english_bilingual_v7.json').read_text())


def _repair_english_narration(course):
    """Enrich only the copied, reviewed English capsule; never write courses."""
    if course.get('id') != 'academy-vtc-e' or course.get('version') not in _BILINGUAL_VERSIONS:
        return course
    try:
        replacement = _bilingual_video()
    except FileNotFoundError:
        # Generation and local authoring can run before the new media is built.
        return course
    for section in course.get('sections', []):
        for activity in section.get('activities', []):
            if activity.get('id') != 'vtc-e-capsule':
                continue
            for block in activity.get('blocks', []):
                video = block.get('video') or {}
                if (video.get('id') != 'vtc-e-capsule'
                        or video.get('src') != 'media/vtc/v4/lesson-e.mp4'
                        or video.get('duration_seconds') != 498.15
                        or len(video.get('chapters', [])) != 24
                        or replacement.get('src') != 'media/vtc/v7/lesson-e.mp4'
                        or replacement.get('captions') != 'media/vtc/v7/lesson-e.vtt'
                        or replacement.get('duration_seconds') != video['duration_seconds']
                        or replacement.get('chapters') != video['chapters']):
                    continue
                for field in ('src', 'captions', 'voice', 'rate', 'content_sha256', 'render_revision', 'transcript'):
                    video[field] = copy.deepcopy(replacement[field])
                activity['vtc']['transcript'] = replacement['transcript']
                activity['vtc']['bilingual_narration'] = True
                for asset in (video['src'], video['captions']):
                    if asset not in course['assets']:
                        course['assets'].append(asset)
                course.setdefault('counts', {})['assets'] = len(course['assets'])
    return course

@lru_cache(maxsize=1)
def _manifest():
    return json.loads((ROOT/'manifest.json').read_text())

def curriculum_manifest():
    return copy.deepcopy(_manifest())

def curriculum_ids():
    return [m['id'] for m in _manifest()['modules']]

@lru_cache(maxsize=16)
def _course(course_id,version):
    return json.loads((ROOT/'courses'/course_id/(version+'.json')).read_text())

def load_bundled_course(course_id,version=None):
    module=next((m for m in _manifest()['modules'] if m['id']==course_id),None)
    if not module:return None
    version=version or module['version']
    if version not in [module['version'],*module.get('previous_versions',[])]:return None
    return _repair_english_narration(copy.deepcopy(_course(course_id,version)))

def bundled_asset(course_id,version,name):
    course=load_bundled_course(course_id,version)
    if not course or name not in course['assets']:return None
    root=(ROOT/'assets').resolve();path=(root/name).resolve()
    return path if root in path.parents and path.is_file() else None

@lru_cache(maxsize=12)
def _exam(exam_id,version):
    if version not in _manifest()['exam_versions']:return None
    allowed={m['mock_exam_id'] for m in _manifest()['modules']}|{_manifest()['final_exam_id']}
    if exam_id not in allowed:return None
    return json.loads((ROOT/'exams'/version/(exam_id+'.json')).read_text())

def load_exam(exam_id,version):
    return copy.deepcopy(_exam(exam_id,version))
