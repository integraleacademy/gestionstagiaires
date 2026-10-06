"""Immutable VTC curriculum, independent of APS editions and learner records."""
from pathlib import Path
from functools import lru_cache
import copy, json
ROOT=Path(__file__).parent/'vtc'

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
    if version!=module['version']:return None
    return copy.deepcopy(_course(course_id,version))

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
