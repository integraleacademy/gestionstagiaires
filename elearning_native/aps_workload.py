"""Read-only workload calibration; historical gaps never become study time."""
from __future__ import annotations

from statistics import median

from .aps_depth import REVISION
from .exams import module_exam_activity_id


def clock(seconds):
    seconds = max(0, int(float(seconds or 0)))
    return f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'


def summarize(course, records):
    workshops = {a['id'] for s in course['sections'] for a in s['activities']
                 if a.get('academy', {}).get('kind') == 'workshop'}
    readings = {a['id'] for s in course['sections'] for a in s['activities']
                if a.get('academy', {}).get('reading_revision')}
    exam_id = module_exam_activity_id(course)
    learners, samples = [], []
    for record in records:
        if not record.get('assigned_current'):
            continue
        snapshot = record.get('aps_workload') or {}
        ledger = record.get('activity_seconds') or {}
        total = float(record.get('active_seconds') or 0)
        captured = sum(float(value) for value in ledger.values())
        old_seconds = max(0, total - captured)
        measured = None
        reason = 'Activités encore en cours'
        if snapshot.get('revision') == REVISION:
            observed = snapshot.get('activity_seconds') or {}
            at_finish = float(snapshot.get('active_seconds') or 0)
            complete_ledger = abs(sum(float(v) for v in observed.values()) - at_finish) <= 1
            current_work = all(snapshot.get('workshop_revisions', {}).get(aid) == REVISION for aid in workshops)
            current_reading = all(snapshot.get('reading_revisions', {}).get(aid) == REVISION for aid in readings)
            if complete_ledger and current_work and current_reading and record.get('required_seconds') == course['required_minutes'] * 60:
                measured = max(0, at_finish - float(observed.get(exam_id) or 0))
                samples.append({'seconds': measured, 'ledger': observed})
                reason = 'Nouvelle charge observée à la première fin des activités'
            else:
                reason = 'Historique partiel ou cours et exercices de plusieurs révisions : exclu de la médiane'
        elif snapshot.get('revision'):
            reason = 'Première fin enregistrée sous une révision antérieure : exclue de la médiane actuelle'
        elif record.get('activities_completed'):
            reason = 'Activités terminées avant la mesure : aucun temps reconstitué'
        learners.append({'trainee_name': record.get('trainee_name') or 'Stagiaire',
            'session_name': record.get('session_name') or '', 'version': record.get('course_version') or '',
            'total_seconds': total, 'total_label': clock(total),
            'exam_seconds': float(ledger.get(exam_id) or 0), 'exam_label': clock(ledger.get(exam_id)),
            'unallocated_seconds': old_seconds, 'unallocated_label': clock(old_seconds),
            'first_seconds': measured, 'first_label': clock(measured) if measured is not None else '—',
            'reason': reason, 'finished_at': snapshot.get('finished_at') or '',
            'activity_percent': record.get('progress_percent') or 0,
            'duration_percent': record.get('duration_percent') or 0,
            'module_complete': bool(record.get('module_complete'))})
    planned = course['study_plan']['activities_minutes'] * 60
    value = median(s['seconds'] for s in samples) if samples else None
    sections = []
    for section in course['sections']:
        ids = [a['id'] for a in section['activities']]
        values = [sum(float(sample['ledger'].get(aid) or 0) for aid in ids) for sample in samples]
        observed = median(values) if values else None
        sections.append({'title': section['title'], 'planned_minutes': section['planned_minutes'],
            'observed_label': clock(observed) if observed is not None else '—',
            'review': observed is not None and observed < section['planned_minutes'] * 60 * .8})
    return {'course_id': course['id'], 'title': course['title'], 'plan': course['study_plan'],
        'sample_count': len(samples), 'learners': learners, 'sections': sections,
        'median_label': clock(value) if value is not None else '—',
        'short_count': sum(sample['seconds'] < planned * .8 for sample in samples),
        'review': value is not None and value < planned * .8,
        'status': 'Échantillon à constituer' if len(samples) < 3 else 'Charge à revoir' if value < planned * .8 else 'À interpréter avec le formateur'}
