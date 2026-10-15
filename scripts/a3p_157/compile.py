"""Compile the authored programme; media durations are supplied only after rendering."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from .editorial import CARDS
from . import relations  # register authored focuses

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / 'elearning_native/a3p_resources'


def all_cards():
    # The other authoring files are optional while preparing a sample, required
    # by validate_complete before the complete programme may be published.
    import importlib
    for module in ('prevention', 'mission', 'risks'):
        if (Path(__file__).parent / (module + '.py')).is_file():
            importlib.import_module('scripts.a3p_157.' + module)
    counts = {}
    result = []
    review = json.loads((RES / 'regulatory_review.json').read_text())
    objectives = {r['id']: r for r in review['eligible_objectives']}
    for source in CARDS:
        row = dict(source)
        oid = row['objective_id']
        counts[oid] = counts.get(oid, 0) + 1
        objective = objectives[oid]
        row.update(id='a3p-v4-' + oid.lower() + '-' + str(counts[oid]).zfill(2),
                   ordinal=counts[oid], uv=objective['delivery_module'],
                   objective=objective['objective'],
                   minutes=min(60, objective['minimum_minutes'] - (counts[oid] - 1) * 60))
        assert row['ref'] in objective['lesson_refs'], (oid, row['ref'])
        result.append(row)
    return result


def validate_complete(rows):
    objectives = json.loads((RES / 'regulatory_review.json').read_text())['eligible_objectives']
    assert len(rows) == 160, len(rows)
    assert sum(r['minutes'] for r in rows) == 9450
    assert len({r['id'] for r in rows}) == len(rows)
    assert len({r['title'] for r in rows}) == len(rows)
    for objective in objectives:
        selected = [r for r in rows if r['objective_id'] == objective['id']]
        assert len(selected) == math.ceil(objective['minimum_minutes'] / 60), objective['id']
        assert sum(r['minutes'] for r in selected) == objective['minimum_minutes'], objective['id']


def base_lesson(ref):
    from elearning_native import a3p_v2
    if ref == '09.15':
        return a3p_v2._injuries_lesson()
    return next(r for r in a3p_v2._manual()['lessons'] if r['ref'] == ref)


def narration(row):
    """A worked case distinct from the changed situation used in the workshop.

    No numeric duration is assigned here. Word count is an editorial lower
    bound; the renderer measures decoded speech and refuses short exports.
    """
    base = base_lesson(row['ref'])
    bank = json.loads((RES / 'enrichment_v3.json').read_text())
    texts = [c['text'] for p in base['pages'] for c in p['components']
             if c['kind'] == 'paragraph' and len(c['text'].split()) > 15]
    focus = bank[row['ref']]
    scenes = [dict(title=row['title'], label='Comprendre le sujet',
        text=row['title'] + '. ' + row['teaching'],
        cards=[row['objective'], 'Analyser les faits', 'Expliquer une décision']),
        dict(title='Les repères du cours', label='Le cadre et ses limites',
             text=' '.join(texts[:4]), cards=[base['objective'], row['title']]),
        dict(title='Lire la situation professionnelle', label='Cas expliqué',
             text=row['situation'] + ' Le point établi est le suivant. ' + row['fact'] +
             ' Il faut cependant conserver une distinction avec ce qui reste inconnu. ' + row['unknown'] +
             ' Ces deux informations ne jouent pas le même rôle. La première peut fonder une décision ; la seconde doit être traitée comme une vérification à organiser. '
             'Le fait de ne pas connaître une information ne permet ni de la considérer favorable, ni de conclure au pire. Il faut préciser comment cette incertitude affecte la mission.',
             cards=[row['fact'], row['unknown']]),
        dict(title='Expliquer la décision', label='Raisonnement commenté',
             text='Dans cette situation, la décision adaptée est la suivante. ' + row['decision'] +
             ' Pour comprendre cette réponse, revenons à la règle étudiée. ' + row['teaching'] +
             ' La qualité du choix se vérifie sur ses conséquences : maintien de la protection, respect du cadre, information de la personne compétente et possibilité de réévaluer. '
             'Une décision ne doit pas être présentée comme définitivement valable si ses conditions changent. Il faut donc conserver les éléments sur lesquels elle repose et prévoir le retour d’information utile.',
             cards=[row['decision'], 'Faits → règle → conséquence']),
    ]
    # Substantive material already authored for this particular manual lesson,
    # rather than repeated generic introductions or silence to reach five minutes.
    for part in focus['teaching']:
        scenes.append(dict(title=part['title'], label='Approfondissement', text=part['text'],
                           cards=[part['title'], base['objective']]))
    scenes.append(dict(title='Vérifier son raisonnement', label='Synthèse et transfert',
        text='Pour faire le point, distinguez quatre éléments dans le cas expliqué. D’abord, la situation. ' + row['situation'] +
        ' Ensuite, le fait confirmé. ' + row['fact'] + ' Puis, la limite de l’information disponible. ' + row['unknown'] +
        ' Enfin, l’action retenue et son relais. ' + row['decision'] +
        ' Dans l’atelier qui suit, une information nouvelle modifiera le dossier. Vous devrez relire les pièces et choisir une réponse adaptée à cette évolution. '
        'La correction expliquera le choix après votre réponse. Le but est de transférer le raisonnement, et pas de mémoriser la phrase donnée dans cet exemple.',
        cards=['Faits confirmés', 'Limites de l’information', 'Décision et relais', 'Réévaluation']))
    words = sum(len(s['text'].split()) for s in scenes)
    used = 4
    while words < 920 and used < len(texts):
        paragraph = texts[used]
        scenes.insert(-1, dict(title='Préciser le cadre de la décision', label='Repère complémentaire',
                             text=paragraph, cards=[base['objective'], row['title']]))
        words += len(paragraph.split())
        used += 1
    if words < 920:
        documents = ' '.join(d['title'] + '. ' + d['text'] for d in focus['documents'])
        comments = ' '.join(q['prompt'] + ' ' + q['correct'] + ' ' + q['explanation'] for q in focus['decisions'])
        scenes.insert(-1, dict(title=focus['title'], label='Deuxième exemple commenté',
                             text=documents + ' ' + comments, cards=[focus['title'], 'Comparer les critères de décision']))
    assert sum(len(s['text'].split()) for s in scenes) >= 760, row['id']
    return scenes


def signature(row, scenes):
    return hashlib.sha256(json.dumps(dict(row=row, scenes=scenes), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


if __name__ == '__main__':
    rows = all_cards()
    validate_complete(rows)
    RES.joinpath('v4').mkdir(parents=True, exist_ok=True)
    RES.joinpath('v4/programme.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    scripts = [{**r, 'scenes': narration(r)} for r in rows]
    RES.joinpath('v4/video_scripts.json').write_text(json.dumps(scripts, ensure_ascii=False, indent=2) + '\n')
    print('Programme:', len(rows), 'séquences,', sum(r['minutes'] for r in rows), 'minutes')
