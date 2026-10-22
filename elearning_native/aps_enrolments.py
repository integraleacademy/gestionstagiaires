"""Automatic APS curriculum for training sessions starting from November 2026.

The release snapshot is immutable: opening a portal or a report never rewrites
the roster or transfers progress from an earlier course/version. Purchased
access keeps its own curriculum and is outside this session policy.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
from functools import lru_cache
from pathlib import Path

CUTOFF = dt.date(2026, 11, 3)


def is_native_aps_session(training):
    if str(training.get('id') or '').startswith('el-'):
        return False
    label = str(training.get('training_type') or training.get('type_formation') or '').strip().upper()
    if not label.startswith('APS') or not training.get('aps_elearning_enabled'):
        return False
    raw = str(training.get('date_start') or training.get('date_debut') or '').strip()
    try:
        return dt.date.fromisoformat(raw[:10]) >= CUTOFF
    except ValueError:
        return False


@lru_cache(maxsize=1)
def _release():
    return json.loads((Path(__file__).parent / 'aps62' / 'session-rollout-20261103.json').read_text(encoding='utf-8'))


def modules():
    return copy.deepcopy(_release()['modules'])


def learner_session(training):
    if not is_native_aps_session(training):
        return training
    return {**training, 'aps_native_modules': modules(),
            'aps_native_path_title': 'Mon parcours APS', 'aps_native_automatic': True}
