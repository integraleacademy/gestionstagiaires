"""Profiles and shared calendar for initial private-security exam juries."""
import re
import afc_schedule


def level(training):
    descriptor = f"{training.get('training_type') or training.get('type') or ''} {training.get('name') or training.get('nom') or ''}".upper()
    if afc_schedule.enabled(training) or re.search(r'\b(?:VAE|MAC|RECYCLAGE|RAN|SSIAP|AFC)\b', descriptor):
        return ''
    if re.search(r'\b(?:DESP|DIRIGEANT)\b', descriptor):
        return 'DESP initial'
    for label in ('A3P', 'APS'):
        if re.search(r'\b' + label + r'\b', descriptor):
            return label
    return ''


def exam_date(training):
    saved = training.get('security_exam') or {}
    if saved.get('config'):
        # Session edits must also update the date used by reminders and dossiers.
        return training.get('exam_date', saved['config'].get('date', '')) or ''
    dossier = training.get(level(training).lower() + '_exam_dossier') or {}
    return dossier.get('exam_date') or training.get('exam_date') or ''


def sync_date(training, date):
    """Called inside an atomic update; invalidate stale editors of both forms."""
    training['exam_date'] = date
    saved = training.get('security_exam') or {}
    if saved.get('config') and saved['config'].get('date') != date:
        saved['config']['date'] = date
        saved['revision'] = saved.get('revision', 0) + 1
    label = level(training)
    if label in ('APS', 'A3P'):
        dossier = training.setdefault(label.lower() + '_exam_dossier', {})
        if dossier.get('exam_date') != date:
            dossier['exam_date'] = date
            dossier['revision'] = dossier.get('revision', 0) + 1
