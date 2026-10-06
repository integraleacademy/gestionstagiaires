"""Publish the beginner-friendly edition without rewriting historical courses."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts.aps62_v5.content import courses
from scripts.build_aps62_v3 import write

ROOT = REPO / 'elearning_native/aps62'
OLD = '20261006-aps62-v4'
VERSION = '20261006-aps62-v5'


def paragraphs(text):
    """Small reading units, retaining every sentence and its legal qualifications."""
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZÀÂÉÈÊÎÔÙÇ«])', text)
    result, current = [], ''
    for sentence in sentences:
        if current and len((current + ' ' + sentence).split()) > 50:
            result.append(current)
            current = ''
        current = (current + ' ' + sentence).strip()
    if current:
        result.append(current)
    return result


def build():
    authored = courses()
    videos = json.loads((ROOT/'video_manifest_v5.json').read_text())
    assert set(videos) == set(authored), 'Render all 62 videos first'
    manifest = json.loads((ROOT/'manifest.json').read_text())
    allocation = json.loads((ROOT/'allocation_v4.json').read_text())
    allocation['version'] = VERSION
    for module in manifest['modules']:
        course = json.loads((ROOT/'courses'/module['id']/(OLD+'.json')).read_text())
        course['version'] = course['interaction_revision'] = VERSION
        course['reading_revision'] = 'plain-language-v1'
        for section in course['sections']:
            sid = section['id']
            row = authored[sid]
            section['title'] = sid[-2:] + ' · ' + row['title']
            cards = [dict(front=t['term'], back=t['definition']) for t in row['glossary']]
            for activity in section['activities']:
                academy = activity.get('academy', {})
                academy['edition'] = '2026-10-06'
                academy['plain_language'] = True
                if not activity['id'].endswith('-q2'):
                    activity['easy_glossary'] = copy.deepcopy(row['glossary'])
                kind = academy.get('kind')
                titles = {'lesson': 'Le cours · ' + row['title'], 'memory': 'Le cours en vidéo',
                    'workshop': 'La situation évolue', 'transfer': 'Une autre situation',
                    'recap': 'À retenir'}
                if kind in titles:
                    activity['title'] = titles[kind]
                if kind == 'lesson':
                    academy['plain_course'] = [dict(title=title, paragraphs=paragraphs(row[key]))
                        for title, key in [('Comprendre la règle', 'rule'),
                                           ('Un exemple expliqué', 'example'), ('L’essentiel à retenir', 'takeaway')]]
                    # The reference material stays complete; only paragraph boundaries change.
                    for reference in academy['lessons']:
                        reference['paragraphs'] = [dict(p, text=text)
                            for p in reference['paragraphs']
                            for text in (paragraphs(p['text']) if p['kind'] == 'paragraph' else [p['text']])]
                    for part in academy.get('deepening', []):
                        part['paragraphs'] = [p for text in part['paragraphs'] for p in paragraphs(text)]
                elif kind == 'memory':
                    academy.update(cards=copy.deepcopy(cards), voice=videos[sid]['voice'],
                        transcript=videos[sid]['transcript'],
                        instruction='Cliquez sur un mot pour lire sa définition. Vous pouvez le revoir autant de fois que nécessaire.')
                elif kind == 'recap':
                    academy.update(decision=row['takeaway'], reason='', cards=copy.deepcopy(cards),
                        instruction='Si un point reste difficile, relisez le cours ou refaites l’exercice concerné.')
                if activity['id'].endswith('-q1'):
                    activity['title'] = 'Choisir une réponse'
                    activity['explanation'] = row['takeaway'] + '\n\n' + activity['explanation']
                if activity['id'].endswith('-q2'):
                    activity.update(title='Relier les mots à leur définition',
                        prompt='Pour chaque mot, choisissez la bonne définition.',
                        pairs=[dict(id=f'{sid}-pair{i}', left=t['term'], right=t['definition'])
                            for i, t in enumerate(row['glossary'])],
                        explanation=' '.join(t['term'] + ' : ' + t['definition'] for t in row['glossary']))
                for block in activity.get('blocks', []):
                    if block.get('video'):
                        block['video'].update(videos[sid], title=row['title'])
                if activity.get('practice'):
                    activity['practice']['revision'] = VERSION
                    for ex in activity['practice']['exercises']:
                        if ex['id'] == 'constat':
                            ex['prompt'] = 'Quel fait est établi dans cette situation ?'
                        elif ex['id'] == 'decision':
                            ex['prompt'] = 'Quelle action choisir ?'
                        if ex.get('branches'):
                            ex['branches'] = {key: value.replace('Examinez la nouvelle information à l’étape suivante.',
                                'Lisez maintenant la suite de la situation.').replace('Réexaminez votre choix à partir de ces repères.',
                                'Lisez cette explication, puis essayez à nouveau.') for key, value in ex['branches'].items()}
            lesson = section['activities'][0]['academy']
            lesson['pacing'] = [dict(label=a['title'], minutes=a['planned_minutes']) for a in section['activities']]
        used = set()
        def collect(value):
            if isinstance(value, str) and value.startswith('media/aps62/'):
                used.add(value)
            elif isinstance(value, dict):
                for key, v in value.items():
                    if key != 'assets':
                        collect(v)
            elif isinstance(value, list):
                for v in value:
                    collect(v)
        collect(course)
        course['assets'] = sorted(used)
        assert all((ROOT/'assets'/p).is_file() for p in used)
        assert sum(a['planned_minutes'] for s in course['sections'] for a in s['activities']) == course['planned_minutes']
        write(ROOT/'courses'/module['id']/(VERSION+'.json'), course)
        module['previous_versions'] = list(dict.fromkeys([*module.get('previous_versions', []), OLD]))
        module['version'] = VERSION
        allocation_module = next(m for m in allocation['modules'] if m['module'] == module['number'])
        for entry, section in zip(allocation_module['sections'], course['sections']):
            entry['activities'] = [a['title'] for a in section['activities']]
    for path in (ROOT/'exams'/OLD).glob('*.json'):
        exam = json.loads(path.read_text())
        exam['version'] = VERSION
        write(ROOT/'exams'/VERSION/path.name, exam)
    manifest.update(version=VERSION, interaction_revision=VERSION)
    manifest['exam_versions'] = list(dict.fromkeys([*manifest.get('exam_versions', []), VERSION]))
    manifest['readability'] = dict(course_only_videos=62, explained_terms=186,
        caption_lines_max=2, subtitle_punctuation=True, authored_on='2026-10-06',
        source_sha256=hashlib.sha256((REPO/'scripts/aps62_v5/courses.txt').read_bytes()).hexdigest(),
        validation='Relecture éditoriale et contrôles techniques. Compréhension à éprouver avec les apprenants concernés ; aucune certification FALC revendiquée.')
    write(ROOT/'manifest.json', manifest)
    write(ROOT/'allocation_v5.json', allocation)
    review = json.loads((ROOT/'regulatory_review.json').read_text())
    review['edition'] = VERSION
    write(ROOT/'regulatory_review.json', review)
    print(VERSION + ': 62 cours simplifiés, 186 définitions, 62 vidéos de cours ; éditions précédentes conservées.')


if __name__ == '__main__':
    build()
