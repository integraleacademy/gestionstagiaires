"""Build a smaller required path and retain contextual variants for free practice."""
from __future__ import annotations

import copy
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'elearning_native/vtc'
BASE = '20261007-vtc-v5-annales'
VISUAL = '20261007-vtc-v4-visuals'
VERSION = '20261010-vtc-v6-pedagogie'


def activities(course):
    return [a for s in course['sections'] for a in s['activities']]


def normal(value):
    return ' '.join(str(value or '').split()).casefold().replace('’', "'")


def signature(ex):
    options = {o['id']: normal(o['text']) for o in ex['options']}
    value = [ex['kind'], normal(ex['prompt']), sorted(options.values()),
             options.get(ex.get('answer')), [(normal(r['text']), options[r['answer']]) for r in ex.get('rows', [])]]
    value += [normal(json.dumps(ex.get(k), ensure_ascii=False, sort_keys=True))
              for k in ('context', 'documents', 'audio', 'transcript', 'translation', 'map', 'calculator', 'image')]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def restore_variants(course):
    """Restore supports, not exact copies; an audio change must never be ignored."""
    old = json.loads((DATA / 'courses' / course['id'] / (VISUAL + '.json')).read_text())
    before = {a['id']: a for a in activities(old)}
    count = 0
    for a in activities(course):
        if not a.get('practice'):
            continue
        current = a['practice']['exercises']
        ids = {ex['id'] for ex in current}
        seen = {signature(ex) for ex in current}
        for ex in before[a['id']].get('practice', {}).get('exercises', []):
            if ex['id'] not in ids and signature(ex) not in seen:
                restored = copy.deepcopy(ex)
                restored['restored_variant'] = True
                current.append(restored)
                seen.add(signature(ex))
                count += 1
        current.sort(key=lambda ex: ex['id'])
    return count


def select_required(activity):
    """Keep core cases, varied formats, every listening support, and short reviews."""
    candidates = activity['practice']['exercises']
    kind = activity['id'].rsplit('-', 1)[-1]
    if kind == 'atelier':
        return list(candidates)
    selected, seen = [], set()

    def add(ex):
        sig = signature(ex)
        if sig not in seen:
            selected.append(ex)
            seen.add(sig)

    if kind in ('diagnostic', 'revision'):
        by_ref = {}
        for ex in candidates:
            by_ref.setdefault(ex.get('competency'), []).append(ex)
        for ref, group in sorted(by_ref.items()):
            add(next((ex for ex in group if not ex.get('restored_variant')), group[0]))
        return selected
    if 'mission' in activity['id']:
        # Cover each reference before adding a second case for the same skill.
        refs = set()
        for ex in candidates:
            if ex.get('competency') not in refs:
                add(ex)
                refs.add(ex.get('competency'))
        for ex in candidates:
            if len(selected) >= 10:
                break
            add(ex)
        return selected
    for ex in [e for e in candidates if not e.get('restored_variant')][:4]:
        add(ex)
    for ex in candidates:
        if ex.get('required_core'):
            add(ex)
    # Audio variants remain distinct even if question and option wording match.
    heard = {ex['audio'] for ex in selected if ex.get('audio')}
    for ex in candidates:
        if ex.get('audio') and ex['audio'] not in heard:
            add(ex)
            heard.add(ex['audio'])
    if heard:
        vocabulary = next((ex for ex in candidates if ex['prompt'].startswith('Que signifie')), None)
        if vocabulary and len(selected) < 7:
            add(vocabulary)
    for format_ in ('sort', 'matching', 'order'):
        ex = next((e for e in candidates if e['kind'] == format_), None)
        if ex and len(selected) < 7:
            add(ex)
    prompts = {normal(ex['prompt']) for ex in selected}
    for ex in candidates:
        if len(selected) >= 7:
            break
        if normal(ex['prompt']) not in prompts:
            add(ex)
            prompts.add(normal(ex['prompt']))
    return selected


def estimate_minutes(activity):
    """Transparent initial workload estimate, never a measured or required time."""
    practice = activity.get('practice')
    if not practice:
        return activity['planned_minutes']
    items = practice['exercises']
    # Includes reading and explanation; one minute/row, two per individual choice.
    minutes = 2 + sum(len(ex.get('rows', [])) or 2 for ex in items)
    minutes += 2 * len({json.dumps(ex['documents'], sort_keys=True) for ex in items if ex.get('documents')})
    minutes += len({ex['audio'] for ex in items if ex.get('audio')})
    return minutes


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def build():
    from content import enrich_course
    manifest = json.loads((DATA / 'manifest.json').read_text())
    report = {'version': VERSION, 'reviewed_on': '2026-10-10', 'modules': [], 'duration_method':
              'Estimation initiale : briefing 2 min, choix 2 min, ligne à placer 1 min, document distinct 2 min, audio distinct 1 min. Cours et vidéos inchangés. Aucun temps minimum ajouté.'}
    for module in manifest['modules']:
        course = json.loads((DATA / 'courses' / module['id'] / (BASE + '.json')).read_text())
        restored = restore_variants(course)
        course = enrich_course(course)
        course.update(version=VERSION, required_minutes=0)
        course['source']['edition'] = 'pedagogie-v6'
        course['source']['pedagogy_edition_on'] = '2026-10-10'
        bank = {'version': VERSION, 'course_id': course['id'], 'title': course['title'], 'activities': []}
        for activity in activities(course):
            if not activity.get('practice'):
                continue
            practice = activity['practice']
            for ex in practice['exercises']:
                if ex['kind'] == 'single':
                    random.Random(f"{VERSION}:{course['id']}:{activity['id']}:{ex['id']}").shuffle(ex['options'])
            required = select_required(activity)
            selected_ids = {ex['id'] for ex in required}
            extras = [ex for ex in practice['exercises'] if ex['id'] not in selected_ids]
            if extras:
                bank['activities'].append({'id': activity['id'], 'title': activity['title'],
                    'vtc': copy.deepcopy(activity.get('vtc', {})), 'practice': {
                        **copy.deepcopy(practice), 'revision': VERSION, 'mode': 'journey', 'adaptive': False,
                        'purpose': 'Entraînement libre · ' + activity['title'], 'exercises': extras}})
            practice.update(revision=VERSION, exercises=required, extra_count=len(extras))
            if activity['id'].endswith('-revision'):
                practice.update(selection_strategy='competency_review_v1', adaptive=True)
            activity['planned_minutes'] = estimate_minutes(activity)
        exercises = [ex for a in activities(course) for ex in a.get('practice', {}).get('exercises', [])]
        extra_count = sum(len(a['practice']['exercises']) for a in bank['activities'])
        course['counts'].update(exercises=len(exercises), decisions=sum(len(e.get('rows', [])) or 1 for e in exercises),
            free_exercises=extra_count, listening_dialogues=len({e['audio'] for e in exercises if e.get('audio')}))
        course['planned_minutes'] = sum(a['planned_minutes'] for a in activities(course))
        groups = [('Cours, exemples et schémas', lambda a: a['id'].endswith('-cours')),
                  ('Ateliers de repères', lambda a: a['id'].endswith('-atelier')),
                  ('Dossiers professionnels', lambda a: a['id'].endswith('-dossier')),
                  ('Missions', lambda a: 'mission' in a['id']),
                  ('Bilan et révision ciblée (maximum)', lambda a: a['id'].endswith(('-diagnostic', '-revision'))),
                  ('Synthèse, vidéo et approfondissement', lambda a: a['id'].endswith(('-capsule', '-approfondir')))]
        course['duration_breakdown'] = [{'label': title, 'minutes': sum(a['planned_minutes'] for a in activities(course) if condition(a))} for title, condition in groups]
        assert sum(p['minutes'] for p in course['duration_breakdown']) == course['planned_minutes']
        course['duration_note'] = 'Estimation de charge révisée après allègement, à mesurer avec des stagiaires. La révision cible les notions à consolider ; les variantes libres sont en complément.'
        module.update(version=VERSION, planned_minutes=course['planned_minutes'], counts=copy.deepcopy(course['counts']), duration_breakdown=copy.deepcopy(course['duration_breakdown']))
        module['previous_versions'] = list(dict.fromkeys([*module.get('previous_versions', []), BASE]))
        save(DATA / 'courses' / course['id'] / (VERSION + '.json'), course)
        save(DATA / 'training' / VERSION / (course['id'] + '.json'), bank)
        report['modules'].append({'id': course['id'], 'restored_context_variants': restored, 'required_max': len(exercises),
            'free_exercises': extra_count, 'planned_minutes': course['planned_minutes'], 'listening_dialogues': course['counts']['listening_dialogues']})
    manifest.update(version=VERSION, reviewed_on='2026-10-10', planned_minutes=sum(m['planned_minutes'] for m in manifest['modules']),
        exercise_count=sum(m['required_max'] for m in report['modules']), free_exercise_count=sum(m['free_exercises'] for m in report['modules']),
        decision_count=sum(m['counts']['decisions'] for m in manifest['modules']), programme_file='programme_pedagogie.json',
        duration_note='Charge indicative recalculée après allègement. La durée dépend des acquis et des révisions ; elle reste à mesurer avec un groupe pilote. Les affectations existantes conservent leur durée configurée.')
    manifest['exam_versions'] = list(dict.fromkeys([*manifest['exam_versions'], VERSION]))
    programme = {'version': VERSION, 'planned_minutes': manifest['planned_minutes'], 'status': 'programme_previsionnel',
                 'duration_note': manifest['duration_note'], 'estimation_method': report['duration_method'],
                 'modules': [{'letter': m['letter'], 'title': m['title'], 'planned_minutes': m['planned_minutes'], 'breakdown': m['duration_breakdown']} for m in manifest['modules']],
                 'validation': {'real_learners_tested': 0, 'measured_median_minutes': None, 'status': 'a_valider_avec_un_groupe_pilote'}}
    save(DATA / 'manifest.json', manifest)
    save(DATA / 'programme_pedagogie.json', programme)
    save(DATA / 'pedagogy_revision_v6.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    build()
