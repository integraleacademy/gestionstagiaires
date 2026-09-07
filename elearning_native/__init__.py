"""Native e-learning engine for Gestion Stagiaires.

The package deliberately keeps Easygenerator import, learner tracking and Flask
integration outside of the historical ``app.py`` monolith.
"""

from .importer import CourseCatalog, CourseImportError, import_easygenerator_course
from .store import NativeElearningStore

__all__ = [
    "CourseCatalog",
    "CourseImportError",
    "NativeElearningStore",
    "import_easygenerator_course",
]
