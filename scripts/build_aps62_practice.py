"""Publish click-only replacements while retaining course/activity identities."""
import copy
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'elearning_native/aps62'
REVISION = '20261006-sans-redaction'


def shuffled(items, seed):
    items = copy.deepcopy(items)
    random.Random(seed).shuffle(items)
    return items


def single(identifier, prompt, texts, explanation, seed):
    arranged = shuffled(texts, seed)
    options = [{'id': str(i + 1), 'text': text} for i, text in enumerate(arranged)]
    return dict(id=identifier, kind='single', prompt=prompt, options=options,
                answer=str(arranged.index(texts[0]) + 1), explanation=explanation)


def build():
    variants = {}
    for line in (ROOT / 'scripts/aps62_transfer_choices.txt').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        key, *texts = line.split('|')
        assert key not in variants and len(texts) == 3
        variants[key] = texts
    bank = {}
    manifest = json.loads((DATA / 'manifest.json').read_text())
    for module in manifest['modules']:
        course = json.loads((DATA / 'courses' / module['id'] / (module['version'] + '.json')).read_text())
        exam = json.loads((DATA / 'exams' / module['version'] / ('module-' + module['number'] + '.json')).read_text())
        for index, section in enumerate(course['sections']):
            lesson, _, workshop, _, matching, transfer, recap = section['activities']
            base = lesson['academy']
            choices = workshop['academy']['choices']
            good = next(c['text'] for c in choices if c['correct'])
            bad = [c['text'] for c in choices if not c['correct']]
            decision = single('decision', 'Quelle décision est adaptée aux faits de ce dossier ?',
                              [good, *bad], base['reason'], workshop['id'])
            categories = [{'id': 'fait', 'text': 'Fait de la situation'},
                          {'id': 'adapte', 'text': 'Action adaptée'},
                          {'id': 'ecarter', 'text': 'Décision à écarter'}]
            sorting = dict(id='classement', kind='sort', prompt='Classez les trois cartes.', options=categories,
                rows=shuffled([{'id': 'c1', 'text': base['case'], 'answer': 'fait'},
                               {'id': 'c2', 'text': good, 'answer': 'adapte'},
                               {'id': 'c3', 'text': bad[0], 'answer': 'ecarter'}], workshop['id'] + 'sort'),
                explanation='Les faits décrivent la situation ; la décision respecte le cadre ; le piège doit être écarté. ' + base['reason'])
            pairs = matching['pairs']
            association = dict(id='association', kind='matching', prompt='Reliez chaque explication au repère du cours.',
                options=shuffled([{'id': p['id'], 'text': p['left']} for p in pairs], workshop['id'] + 'pairs'),
                rows=shuffled([{'id': 'r' + str(i), 'text': p['right'], 'answer': p['id']} for i, p in enumerate(pairs)], workshop['id'] + 'rows'),
                explanation='Ces associations reprennent les repères du manuel étudiés dans ce dossier.')
            order = dict(id='ordre', kind='order', prompt='Reconstituez les quatre étapes du raisonnement présenté dans le cours.',
                options=[{'id': str(i + 1), 'text': f'Étape {i + 1}'} for i in range(4)],
                rows=shuffled([{'id': 's' + str(i), 'text': s['label'] + ' — ' + s['text'], 'answer': str(i + 1)}
                               for i, s in enumerate(base['flow'])], workshop['id'] + 'order'),
                explanation='La méthode du dossier : observer les faits, vérifier le cadre, décider, puis réévaluer lorsque la situation évolue. Ce classement pédagogique ne remplace pas les priorités de mise en sécurité en cas d’urgence.')
            bank[workshop['id']] = dict(revision=REVISION, exercises=[decision, sorting, association, order])
            variant = variants[workshop['academy']['dossier']]
            exercises = [single('variante', 'Quelle réponse retenir dans cette nouvelle situation ?',
                                variant, variant[0] + ' ' + base['reason'], transfer['id'])]
            for n, q in enumerate(exam['questions'][index * 2:index * 2 + 2], 1):
                exercises.append(dict(id=f'repere-{n}', kind='single', prompt=q['prompt'],
                    options=copy.deepcopy(q['options']), answer=q['answer'], explanation=q['explanation']))
            bank[transfer['id']] = dict(revision=REVISION, exercises=exercises)
    assert len(variants) == 62 and len(bank) == 124
    target = DATA / 'practice_bank.json'
    target.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + '\n')
    print(f'{len(bank)} ateliers sans rédaction, {sum(len(v["exercises"]) for v in bank.values())} exercices')


if __name__ == '__main__':
    build()
