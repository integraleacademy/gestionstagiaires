"""Course-only narration and visual chapters, grounded in the reviewed APS edition.

The reference paragraphs remain in the course. The video introduces vocabulary,
explains the rules and walks through examples; it never asks for an interruption.
"""
import json
from pathlib import Path
import re

from scripts.aps62_v5.content import courses as plain_courses

ROOT = Path(__file__).resolve().parents[2] / 'elearning_native/aps62'
SOURCE = '20261006-aps62-v5'


def spoken(text):
    text = text.replace('À RETENIR · ', '').replace('EXEMPLE EXPLIQUÉ', 'Un exemple expliqué')
    text = text.replace('Comparez les deux moments avant de lancer la mission. ', '')
    text = text.replace('Le fait établi est :', 'Voici ce que l’on sait :')
    text = text.replace('La première réponse à examiner est :', 'L’action adaptée est la suivante :')
    text = text.replace('La situation évolue :', 'Un nouvel événement se produit :')
    text = text.replace('La décision doit donc être réexaminée :', 'L’agent adapte alors son action :')
    text = text.replace('Dans le nouveau dossier « ', 'Dans cet exemple, « ')
    text = re.sub(r'(?i)Exemple expliqué[. :]\s*', 'Par exemple, ', text)
    # These are requests to the learner in the original reference, not course facts.
    text = re.sub(r'(?i)\b(?:Choisissez|Répondez|Mettez la vidéo en pause)\b[^.!?]*[.!?]?', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def chunks(paragraphs, limit=105):
    result, current = [], []
    for paragraph in paragraphs:
        paragraph = spoken(paragraph)
        if not paragraph:
            continue
        if current and len(' '.join(current + [paragraph]).split()) > limit:
            result.append(' '.join(current))
            current = []
        current.append(paragraph)
    if current:
        result.append(' '.join(current))
    return result


def courses():
    manifest = json.loads((ROOT/'manifest.json').read_text())
    simple = plain_courses()
    result = {}
    for module in manifest['modules']:
        course = json.loads((ROOT/'courses'/module['id']/(SOURCE+'.json')).read_text())
        for section in course['sections']:
            sid = section['id']
            a = section['activities'][0]['academy']
            row = simple[sid]
            scenes = []
            def add(title, paragraphs, kind='explanation'):
                for text in chunks(paragraphs):
                    scenes.append(dict(title=title, text=text, kind=kind))
            add(row['title'], [row['rule']], 'intro')
            add('Trois mots pour comprendre', [
                'Pour comprendre ce cours, voici trois mots utiles. ' +
                ' '.join(t['term'] + ' : ' + t['definition'] for t in row['glossary'])], 'glossary')
            add('Un premier exemple', [row['example']], 'case')
            for reference in a['lessons']:
                title, paragraphs = reference['title'], []
                for p in reference['paragraphs']:
                    if p['kind'] == 'heading':
                        if paragraphs:
                            add(title, paragraphs)
                        title = reference['title'] if p['text'] == 'EXEMPLE EXPLIQUÉ' else p['text']
                        paragraphs = []
                    else:
                        paragraphs.append(p['text'])
                add(title, paragraphs)
            for part in a['deepening']:
                add(part['title'], part['paragraphs'], 'case' if 'décision' in part['title'] else 'explanation')
            add('Comprendre la bonne décision', [a['case'], a['decision'], a['reason']], 'comparison')
            if a.get('extra_case'):
                add(a['extra_case']['title'], [a['extra_case']['case'],
                    'Dans ce cas, la réponse adaptée est la suivante. ' + a['extra_case']['model']], 'case')
            # Use the existing explanations of the same topic, never silence or a loop,
            # to support the shortest dossiers with substantive material.
            if sum(len(s['text'].split()) for s in scenes) < 1050:
                for reference in a['lessons']:
                    background = reference.get('practice', {}).get('background')
                    if background:
                        add('Préciser la règle', [background])
            add('L’essentiel à retenir', [row['takeaway']], 'summary')
            text = '\n\n'.join(s['text'] for s in scenes)
            assert len(text.split()) >= 880, (sid, len(text.split()))
            assert not re.search(r'(?i)mettez.*pause|choisissez|répondez|à vous de décider', text), sid
            result[sid] = dict(row, scenes=scenes, transcript=text,
                visual=a.get('visual_board', dict(title=row['title'], steps=[dict(label=t['term'], text=t['definition']) for t in row['glossary']])),
                case=a['case'], good=a['decision'], bad=a['pitfall'])
    assert len(result) == 62
    return result


if __name__ == '__main__':
    rows = courses()
    counts = [(len(row['transcript'].split()), sid, len(row['scenes'])) for sid, row in rows.items()]
    print('Narrations:', len(rows), 'words:', sum(c[0] for c in counts), 'range:', min(counts), max(counts))
