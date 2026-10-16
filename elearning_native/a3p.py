"""Current A3P edition and immutable dispatch for assigned historical editions."""
from . import a3p_v1 as legacy
from . import a3p_v2 as previous
from . import a3p_v3 as enriched
from . import a3p_v4 as current

ROOT = current.ROOT
VERSION = current.VERSION
SUPPORTED_VERSIONS = (*enriched.SUPPORTED_VERSIONS, VERSION)
MODULES, NOTICE = current.MODULES, current.NOTICE
DISTANCE = previous.DISTANCE
_manual, _questions, _video = previous._manual, previous._questions, previous._video
_review, _rows, _minutes, _mode = previous._review, previous._rows, previous._minutes, previous._mode
curriculum_ids = current.curriculum_ids
load_bundled_course = current.load_bundled_course
bundled_asset = current.bundled_asset
curriculum_manifest = current.curriculum_manifest
load_exam = current.load_exam
