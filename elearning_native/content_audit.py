"""Read-only inventory of current teaching material, not a duration certificate."""
from __future__ import annotations

from functools import lru_cache
import math

from . import academy, a3p, mac_aps, vtc
from .lesson_timing import lesson_pages
from .paths import project_course
from .reading_layout import _ENV, _Fragment
from .videos import course_videos


def _reading_words(course, activity, pages):
    if activity.get('academy', {}).get('kind') == 'lesson':
        markup = _ENV.get_template('_aps62_activity.html').render(course=course, activity=activity)
        tree = _Fragment(markup).root
        return sum(len(node.text().split()) for node in tree.walk() if 'data-aps-lesson-page' in node.attrs)
    return sum(page.get('word_count', 0) for page in pages)


def audit_course(course):
    activities = [a for s in course['sections'] for a in s['activities']]
    mandatory = [a for a in activities if not a.get('optional')]
    pages_by_id = {a['id']: lesson_pages(course, a) for a in mandatory}
    readings = [a for a in mandatory if pages_by_id[a['id']]]
    words = sum(_reading_words(course, a, pages_by_id[a['id']]) for a in readings)
    pages = [p for rows in pages_by_id.values() for p in rows if not p.get('media')]
    video_seconds = sum(sum(videos.values()) for videos in course_videos(course).values())
    required = int(course.get('required_minutes') or 0)
    missing = sum(not a.get('planned_minutes') for a in mandatory)
    planned = sum(a.get('planned_minutes', 0) for a in activities)
    optional = sum(a.get('planned_minutes', 0) for a in activities if a.get('optional'))
    calibration = course.get('calibration') or {}
    gap = max(0, required - planned) if calibration else None
    questions = sum(len(a.get('answer_groups') or [None]) for a in mandatory if a.get('scored'))
    interactive_items = sum(len(a.get('practice', {}).get('exercises', [])) for a in mandatory)
    issues = []
    if missing:
        issues.append(f'{missing} activités sans durée pédagogique détaillée : établir le budget de chaque séquence et enrichir les cours avant de valider la durée du module.')
    countdown = sum(p['required_seconds'] for p in pages) / 60
    if required and countdown + video_seconds / 60 > required:
        issues.append('Les lectures minimales et vidéos dépassent déjà la durée du module : revoir la répartition avant validation pédagogique.')
    if optional:
        issues.append(f'{optional} minutes du budget concernent des ateliers facultatifs : mesurer aussi le parcours sans ces ateliers.')
    if calibration:
        issues.append('Estimation éditoriale, sans essai apprenant : les durées détaillées ne sont pas des temps mesurés ni des heures acquises.')
        if gap:
            issues.append(f'Écart de contenu estimé : {gap} minutes entre les activités disponibles ({planned} min) et le volume du module ({required} min). Prévoir du contenu supplémentaire et des essais ; ne pas combler cet écart par des attentes artificielles.')
    sections = []
    for section in course['sections']:
        selected = [a for a in section['activities'] if not a.get('optional')]
        section_pages = [p for a in selected for p in pages_by_id.get(a['id'], []) if not p.get('media')]
        sections.append({'title': section['title'], 'planned_minutes': section.get('planned_minutes'),
                         'reading_minutes': sum(p['required_seconds'] for p in section_pages) / 60,
                         'pages': len(section_pages),
                         'activities': [{'title': a['title'], 'minutes': a.get('planned_minutes'),
                                         'decisions': len(a.get('practice', {}).get('exercises', []))}
                                        for a in selected]})
    return {'id': course['id'], 'version': course['version'], 'title': course['title'],
            'training': course.get('training_label', 'APS'), 'required_minutes': required,
            'lessons': len(readings), 'pages': len(pages), 'words': words,
            'reading_low': math.ceil(words / 180), 'reading_high': math.ceil(words / 120),
            'countdown_minutes': round(countdown), 'video_minutes': round(video_seconds / 60, 1),
            'questions': questions, 'interactive_items': interactive_items,
            'activities': len(mandatory), 'planned_minutes': planned,
            'optional_minutes': optional, 'missing_plans': missing, 'issues': issues,
            'calibration': calibration, 'gap_minutes': gap,
            'priority': 'Enrichissement et calibrage nécessaires' if missing or gap else 'Essais apprenants à réaliser',
            'sections': sections}


@lru_cache(maxsize=1)
def audit_catalog():
    reports = []
    for provider in (academy, mac_aps, a3p, vtc):
        for course_id in provider.curriculum_ids():
            course = provider.load_bundled_course(course_id)
            if course.get('training_label') == 'A3P':
                course = project_course(course, {'required_minutes': course['required_minutes']})
            reports.append(audit_course(course))
    return reports
