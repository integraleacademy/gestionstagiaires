"""Build the visual, guided APS edition without modifying historical versions.

Long-video production is a separate, explicit stage. Until narrated files pass
the >=300s gate, retain the available videos without claiming they were replaced.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts.aps62_v5.content import courses as simple_courses
from scripts.aps62_v6.content import courses as video_courses
from scripts.build_aps62_v3 import write

ROOT = REPO/'elearning_native/aps62'
OLD = '20261006-aps62-v5'


def build(version='20261007-aps62-v8', replace_videos=False):
    if any((ROOT/'courses').glob('*/'+version+'.json')) or (ROOT/'exams'/version).exists():
        raise ValueError('Choose a new edition: existing course versions are immutable: '+version)
    simple = simple_courses()
    authored = video_courses()
    observations = {}
    actions = {}
    for line in (REPO/'scripts/aps62_v6/actions.txt').read_text().splitlines():
        if line and not line.startswith('#'):
            sid, first, second = line.split('|')
            actions['aps62-'+sid] = (first, second)
    scenarios = {}
    for line in (REPO/'scripts/aps62_v3/scenarios.txt').read_text().splitlines():
        if line and not line.startswith('#'):
            cells = line.split('|')
            scenarios['aps62-'+cells[0]] = cells
    for line in (REPO/'scripts/aps62_v6/observations.txt').read_text().splitlines():
        if line and not line.startswith('#'):
            sid, question, correct, wrong = line.split('|')
            observations['aps62-'+sid] = (question, correct, wrong)
    assert set(observations) == set(actions) == set(authored)
    videos = json.loads((ROOT/'video_manifest_v6.json').read_text()) if replace_videos else {}
    if replace_videos:
        assert set(videos) == set(authored), 'All 62 rendered videos are required'
        assert all(v['duration_seconds'] >= 300 and v['narration_seconds'] >= 300 for v in videos.values())
    manifest = json.loads((ROOT/'manifest.json').read_text())
    allocation = json.loads((ROOT/'allocation_v5.json').read_text())
    allocation['version'] = version
    for module in manifest['modules']:
        course = json.loads((ROOT/'courses'/module['id']/(OLD+'.json')).read_text())
        course['version'] = course['interaction_revision'] = version
        course['reading_revision'] = 'visual-guided-v2'
        for section in course['sections']:
            sid = section['id']
            row, narration = simple[sid], authored[sid]
            lesson = section['activities'][0]['academy']
            # Each diagram uses the actual case, decision and explanation for this
            # dossier. The complete source paragraphs remain available below it.
            lesson['visual_guide'] = dict(title=row['title'], situation=lesson['case'],
                action=lesson['decision'], why=row['rule'], mistake=lesson['pitfall'],
                terms=copy.deepcopy(row['glossary']))
            lesson['image'] = f'media/aps62/v2/module-{sid[6:8]}.webp'
            for activity in section['activities']:
                academy = activity.get('academy', {})
                academy['edition'] = '2026-10-07'
                if activity.get('practice'):
                    practice = activity['practice']
                    practice.update(revision=version, mode='guided', sequential=True)
                    academy['image'] = lesson['image']
                    practice['title'] = academy.get('title') or row['title']
                    if academy.get('kind') == 'workshop':
                        activity['title'] = 'Que faites-vous ? · pas à pas'
                    elif academy.get('kind') == 'transfer':
                        activity['title'] = 'Un nouvel exemple · pas à pas'
                    for i, ex in enumerate(practice['exercises']):
                        ex.pop('branches', None)
                        if academy.get('kind') == 'workshop':
                            ex['stage'] = ('Comprendre la situation', 'Choisir une action', 'La suite de l’histoire')[i]
                            if ex['id'] == 'constat':
                                question, good, bad = observations[sid]
                                ex['prompt'] = question
                                # Keep a deterministic varying answer position.
                                opts = [dict(id='a', text=good), dict(id='b', text=bad)]
                                if int(sid[-2:]) % 2:
                                    opts.reverse()
                                ex.update(options=opts, answer='a', explanation=good+' '+row['rule'])
                            else:
                                # The original case has one authored alternative;
                                # remove the third, generic distractor.
                                correct = next(o for o in ex['options'] if o['id'] == ex['answer'])
                                correct['text'] = actions[sid][i-1]
                                wrong_text = scenarios[sid][5 if i == 1 else 9]
                                wrong = next(o for o in ex['options'] if o['id'] != ex['answer'])
                                wrong = dict(wrong, text=wrong_text)
                                ex['options'] = [correct, wrong] if int(sid[-2:]) % 2 == i % 2 else [wrong, correct]
                                ex['prompt'] = 'Que faites-vous maintenant ?' if i == 2 else 'Que faites-vous ?'
                                if i == 1:
                                    ex['context'] = scenarios[sid][2]
                        else:
                            ex['stage'] = 'Votre choix' if i == 0 else 'La question suivante'
                        if not ex.get('context'):
                            ex['context'] = academy.get('case', '')
                        ex['context'] = '\n\n'.join(re.split(r'(?<=[.!?])\s+(?=[A-ZÀÂÉÈÊÎÔÙÇ«])', ex['context']))
                if videos:
                    for block in activity.get('blocks', []):
                        if block.get('video'):
                            block['video'].update(videos[sid], title=row['title'])
                            # Keep the module's 62h allocation; transfer time from
                            # reading to its narrated equivalent, not extra hours.
                            added = math.ceil(videos[sid]['duration_seconds']/60)+1-activity['planned_minutes']
                            activity['planned_minutes'] += added
                            section['activities'][0]['planned_minutes'] -= added
                            assert section['activities'][0]['planned_minutes'] > 0
                    if academy.get('kind') == 'memory':
                        academy.update(transcript=videos[sid]['transcript'], voice=videos[sid]['voice'])
            lesson['pacing'] = [dict(label=a['title'], minutes=a['planned_minutes']) for a in section['activities']]
        used = set()
        def collect(value):
            if isinstance(value, str) and value.startswith('media/aps62/'):
                used.add(value)
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key != 'assets':
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(course)
        course['assets'] = sorted(used)
        assert all((ROOT/'assets'/p).is_file() for p in used)
        assert sum(a['planned_minutes'] for s in course['sections'] for a in s['activities']) == course['planned_minutes']
        write(ROOT/'courses'/module['id']/(version+'.json'), course)
        module['previous_versions'] = list(dict.fromkeys([*module.get('previous_versions', []), OLD,
            *([module['version']] if module['version'] != version else [])]))
        module['version'] = version
        entry = next(m for m in allocation['modules'] if m['module'] == module['number'])
        for target, section in zip(entry['sections'], course['sections']):
            target['activities'] = [a['title'] for a in section['activities']]
    for path in (ROOT/'exams'/OLD).glob('*.json'):
        exam = json.loads(path.read_text())
        exam['version'] = version
        write(ROOT/'exams'/version/path.name, exam)
    manifest.update(version=version, interaction_revision=version)
    manifest['exam_versions'] = list(dict.fromkeys([*manifest.get('exam_versions', []), version]))
    manifest['visual_learning'] = dict(guided_workshops=142, illustrated_summaries=62,
        vocabulary_diagrams=62, comparison_tables=62, observation_questions=62,
        authored_on='2026-10-07', long_videos_published=bool(videos))
    write(ROOT/'manifest.json', manifest)
    write(ROOT/'allocation_v6.json', allocation)
    review = json.loads((ROOT/'regulatory_review.json').read_text())
    review['edition'] = version
    write(ROOT/'regulatory_review.json', review)
    # Reviewable production sources, stored with the project, not sent anywhere.
    write(ROOT/'video_scripts_v6.json', authored)
    (ROOT/'video_narrations_v6.txt').write_text(
        'TEXTES DES 62 VIDÉOS APS — PRÉPARATION DU 7 OCTOBRE 2026\n'
        'Texte destiné à la narration Henri. Aucun envoi au service vocal sans autorisation.\n\n'
        + '\n\n'.join(sid+' — '+row['title']+'\n\n'+row['transcript'] for sid, row in authored.items())+'\n')
    print(version+': 62 visual courses, 142 guided activities; long videos '+('published' if videos else 'awaiting speech authorization'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='20261007-aps62-v8')
    parser.add_argument('--videos-v6', action='store_true')
    args = parser.parse_args()
    build(args.version, args.videos_v6)
