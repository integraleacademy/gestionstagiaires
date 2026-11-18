"""Small, revision-checked public contexts for the UV request path.

The administrative JSON is atomically replaced by its writers. Keep only the
fields needed to authorize/render a questionnaire, indexed by its existing
public tokens. Every lookup checks the file revision; no access decision or
SQLite questionnaire state is cached here.
"""
from copy import deepcopy
from functools import lru_cache
import json
import os
from pathlib import Path
import threading

from trainee_recovery import collapse_registration_copies
from uv_questionnaire_store import UV_FIELDS


TRAINING_FIELDS = (
    'id', 'partner_id', 'name', 'nom', 'training_type', 'type',
    'date_start', 'date_end', 'date_debut', 'date_fin',
    'aps_remote_start', 'aps_remote_end', 'aps_in_person_start',
    'aps_in_person_end', 'aps_elearning_enabled', 'afc_enabled',
)
TRAINEE_FIELDS = (
    'id', 'public_token', 'token', 'first_name', 'last_name',
    'registration_cancelled', 'registration_canceled', 'inscription_annulee',
    'training_date_start', 'training_date_end', *UV_FIELDS,
)


class UnversionedSource(ValueError):
    """This source cannot provide a reliable filesystem revision."""


def _revision(stat):
    values = tuple(getattr(stat, name, None) for name in (
        'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
    if any(value is None for value in values):
        raise UnversionedSource('Questionnaire context source has no file revision.')
    return values


def _project(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('sessions', []), list):
        raise ValueError('Invalid questionnaire context source.')
    # Use the same canonical row as the administrative reader. Deduplication
    # needs creation/partner metadata, so it must precede the slim projection.
    collapse_registration_copies(payload, lambda *_args: None)
    tokens = {}
    for training in payload.get('sessions', []):
        if not isinstance(training, dict):
            continue
        current = isinstance(training.get('trainees'), list)
        people = training.get('trainees') if current else training.get('stagiaires', [])
        if not isinstance(people, list):
            continue
        slim_training = {key: training[key] for key in TRAINING_FIELDS if key in training}
        for person in people:
            if not isinstance(person, dict):
                continue
            aliases = [value.strip() for key in ('public_token', 'token')
                       if isinstance(value := person.get(key), str) and value.strip()]
            if not aliases:
                continue
            slim_person = {key: person[key] for key in TRAINEE_FIELDS if key in person}
            if not current:
                # Legacy rosters use French identity fields. Never generate a
                # new token or identifier during this read-only projection.
                slim_person['first_name'] = person.get('prenom') or ''
                slim_person['last_name'] = person.get('nom') or ''
            context = (slim_training, slim_person)
            for token in aliases:
                # Public lookup has always used the first canonical match.
                tokens.setdefault(token, context)
    return tokens


class UVContextIndex:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._snapshot = None
        self.build_count = 0

    def _current(self):
        return _revision(self.path.stat())

    def lookup(self, token):
        token = (token or '').strip()
        if not token:
            return None, None
        revision = self._current()
        snapshot = self._snapshot
        if snapshot is None or snapshot[0] != revision:
            with self._lock:
                # Only one thread parses a new revision. Waiting threads reuse
                # its finished index, never a partly constructed dictionary.
                for _ in range(3):
                    revision = self._current()
                    snapshot = self._snapshot
                    if snapshot is not None and snapshot[0] == revision:
                        break
                    with self.path.open('r', encoding='utf-8') as handle:
                        opened = _revision(os.fstat(handle.fileno()))
                        payload = json.load(handle)
                        read_revision = _revision(os.fstat(handle.fileno()))
                    if opened != read_revision or self._current() != opened:
                        continue
                    projected = _project(payload)
                    if self._current() != opened:
                        continue
                    snapshot = (opened, projected)
                    self._snapshot = snapshot
                    self.build_count += 1
                    break
                else:
                    raise OSError('Questionnaire context changed while being read.')
        # A missing, corrupt or changing source fails closed above. Never
        # return an old context just because rebuilding the new revision failed.
        context = snapshot[1].get(token)
        if context is not None and any(
                not isinstance(item.get('id'), str) or not item['id'].strip()
                for item in context):
            # Legacy normalization may supply missing identifiers. Never form
            # an empty/shared SQLite key from a lightweight projection.
            raise UnversionedSource('Questionnaire context has no stable identifiers.')
        return deepcopy(context) if context is not None else (None, None)


_INDEX_LOCK = threading.Lock()


@lru_cache(maxsize=8)
def _index(path):
    return UVContextIndex(path)


def index_for(path):
    with _INDEX_LOCK:
        return _index(os.path.abspath(os.fspath(path)))
