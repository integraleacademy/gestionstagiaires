"""Minimum reading times for all native readers, independent of module credit.

The order mirrors the reading templates. IDs identify content, not a browser
index. Existing completed activities remain exempt; old time is never invented.
"""
from __future__ import annotations

import re

from .reading_layout import reading_pages


def _words(value):
    if isinstance(value, dict):
        return sum(_words(item) for key, item in value.items()
                   if key not in {'image', 'diagram', 'src', 'id', 'kind', 'ref'})
    if isinstance(value, (list, tuple)):
        return sum(_words(item) for item in value)
    return len(re.findall(r"\S+", value)) if isinstance(value, str) else 0


def lesson_pages(course, activity):
    if course.get('id', '').startswith(('academy-macaps-', 'academy-a3p-', 'academy-vtc-')):
        return reading_pages(activity)
    lesson = activity.get('academy', {})
    if (not course.get('id', '').startswith('academy-aps62-')
            or lesson.get('kind') != 'lesson' or not lesson.get('editorial_revision')):
        return []
    pages = []

    def add(key, title, seconds):
        pages.append({'id': key, 'title': title, 'required_seconds': seconds})

    add('introduction', lesson.get('title', 'Introduction'), 60)
    for index, page in enumerate(lesson.get('reading_pages', [])):
        seconds = 300 if page.get('kind') == 'example' or _words(page) >= 500 else 120
        add(f'reading-{index}', page['title'], seconds)
    if lesson.get('visual_board'):
        add('overview', lesson['visual_board']['title'], 60)
    for index, reference in enumerate(lesson.get('lessons', [])):
        seconds = 60 if reference.get('review_reference') else 300 if _words(reference) >= 550 else 120
        add(f'reference-{index}-{reference["ref"]}', reference['title'], seconds)
    if lesson.get('depth_teaching'):
        part = lesson['depth_teaching']
        add('depth', part['title'], 300 if _words(part) >= 500 else 120)
    for index, part in enumerate(lesson.get('deepening', [])):
        add(f'deepening-{index}', part['title'], 300 if _words(part) >= 500 else 120)
    if lesson.get('uniform_diagram'):
        add('uniform', lesson['uniform_diagram']['title'], 300)
    for example in lesson.get('worked_examples', []):
        for index, document in enumerate(example.get('documents', [])):
            words = _words(document)
            seconds = 300 if words >= 350 or len(document.get('rows', [])) >= 8 else 120 if words > 80 or document.get('image') else 60
            add(f'{example["id"]}-document-{index}', document['title'], seconds)
        for index, answer in enumerate(example.get('answers', [])):
            add(f'{example["id"]}-answer-{index}', answer['label'], 120 if _words(answer) > 140 else 60)
        if example.get('points'):
            add(f'{example["id"]}-points', 'Repères à retenir', 60)
    return pages


def first_pending(pages, seconds, videos=None):
    return next((index for index, page in enumerate(pages)
                 if float(seconds.get(page['id']) or 0) < page['required_seconds']
                 or (videos is not None and page.get('video_id')
                     and not videos.get(page['video_id'], {}).get('completed'))), len(pages))


def remaining_seconds(pages, seconds):
    return sum(max(0, page['required_seconds'] - float(seconds.get(page['id']) or 0)) for page in pages)
