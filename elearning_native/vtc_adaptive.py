"""Server-selected VTC reviews; completed historical editions are never changed."""
from __future__ import annotations

import copy
import json

STRATEGY = 'competency_review_v1'


def _identity(exercise):
    options = {o['id']: ' '.join(o['text'].split()).casefold() for o in exercise['options']}
    return json.dumps([exercise['kind'], exercise['prompt'], sorted(options.values()),
                       options.get(exercise.get('answer')),
                       [(row['text'], options[row['answer']]) for row in exercise.get('rows', [])],
                       *[exercise.get(k) for k in ('context', 'documents', 'audio', 'transcript', 'translation', 'map', 'calculator', 'image')]],
                      sort_keys=True, ensure_ascii=False)


def select_activity(course, activity, progress):
    """Use only authoritative prior results, excluding the review being selected.

    Earlier activities are completed and immutable before this review can start.
    The same plan is therefore stable across reloads, tabs and corrected retries.
    Two different situations answered correctly on first attempt provide evidence
    for a lighter review. Correcting the same question never creates that evidence.
    """
    practice = activity.get('practice', {})
    if (not course.get('id', '').startswith('academy-vtc-')
            or practice.get('selection_strategy') != STRATEGY):
        return activity
    observations = {}
    completed = set(progress.get('completed_activity_ids', []))
    for section in course['sections']:
        stop = False
        for previous in section['activities']:
            if previous['id'] == activity['id']:
                stop = True
                break
            if previous['id'] not in completed:
                continue
            saved = progress.get('answers', {}).get(previous['id'], {})
            for ex in previous.get('practice', {}).get('exercises', []):
                diagnostic = saved.get('practice_diagnostics', {}).get(ex['id'])
                if not diagnostic or not ex.get('competency'):
                    continue
                choices = observations.setdefault(ex['competency'], {})
                key = _identity(ex)
                choices.pop(key, None)
                choices[key] = bool(diagnostic.get('first_correct') and diagnostic.get('correct'))
        if stop:
            break
    refs = list(dict.fromkeys(ex.get('competency') for ex in practice['exercises']))
    mastered = {ref for ref, choices in observations.items()
                if len(choices) >= 2 and all(list(choices.values())[-2:])}
    weak = [ref for ref in refs if ref not in mastered]
    selected = [ex for ex in practice['exercises'] if ex.get('competency') in weak]
    # Keep four spaced checks when everything appears acquired, and at least four
    # items otherwise. A small control remains useful even after successful work.
    strong = [ex for ex in practice['exercises'] if ex.get('competency') in mastered]
    needed = max(0, min(4, len(practice['exercises'])) - len(selected))
    if needed and strong:
        indexes = {min(len(strong) - 1, i * len(strong) // needed) for i in range(needed)}
        selected += [strong[i] for i in sorted(indexes)]
    selected_ids = {ex['id'] for ex in selected}
    result = copy.deepcopy(activity)
    result['practice']['exercises'] = sorted(
        [ex for ex in result['practice']['exercises'] if ex['id'] in selected_ids],
        key=lambda ex: ex.get('competency') not in weak)
    result['practice']['selection_summary'] = {
        'selected_count': len(selected), 'available_count': len(practice['exercises']),
        'weak_refs': weak, 'mastered_count': len(set(refs) & mastered),
        'control_count': len(selected) - sum(ex.get('competency') in weak for ex in selected),
    }
    return result
