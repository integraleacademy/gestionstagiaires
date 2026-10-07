"""Case demonstrations for the next APS video edition.

All factual situations, decisions and legal explanations come from the authored
scenario bank already used by the guided course. The visual documents below are
explicitly fictional training documents, never purported regulatory evidence.
"""
import copy
import json
from pathlib import Path

from scripts.aps62_v6.content import courses as previous_courses

REPO = Path(__file__).resolve().parents[2]


def cases():
    result = {}
    for line in (REPO/'scripts/aps62_v3/scenarios.txt').read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        cells = line.split('|')
        assert len(cells) == 16, cells[0]
        keys = ('number', 'title', 'situation', 'fact', 'decision', 'wrong',
                'reason', 'evolution', 'next_decision', 'next_wrong',
                'next_reason', 'unverified_document', 'verified_document',
                'transfer', 'transfer_decision', 'transfer_wrong')
        result['aps62-'+cells[0]] = dict(zip(keys, cells))
    assert len(result) == 62
    return result


def courses():
    result = copy.deepcopy(previous_courses())
    for sid, case in cases().items():
        row = result[sid]
        # A transmission is demonstrated on operational topics. Legal and
        # confidentiality topics use a private briefing instead of broadcasting
        # potentially sensitive information over an open radio channel.
        radio = sid[6:8] in ('08', '09', '10', '11', '12', '14', '15')
        channel = 'Transmission radio d’exercice' if radio else 'Échange avec le chef de poste'
        dialogue = [
            {'speaker': 'Agent', 'text': case['fact']},
            {'speaker': 'Poste de contrôle' if radio else 'Chef de poste',
             'text': 'Bien reçu. Quelle action proposez-vous dans le cadre de la mission ?'},
            {'speaker': 'Agent', 'text': case['decision']},
        ]
        demonstration = [
            dict(kind='field_observation', title='Observer · '+case['title'],
                 situation=case['situation'], fact=case['fact'],
                 text='Voici une situation professionnelle d’exercice. '+case['situation']+
                      ' Le point établi, à distinguer des suppositions, est le suivant. '+case['fact']),
            dict(kind='field_documents', title='Examiner les documents du poste',
                 unverified=case['unverified_document'], verified=case['verified_document'],
                 text='Deux documents d’exercice apparaissent à l’écran. Le premier contient une anomalie : '+
                      case['unverified_document']+' Le repère à utiliser est le suivant : '+case['verified_document']+
                      ' La comparaison permet de repérer ce qui doit être clarifié avant l’action.'),
            dict(kind='field_dialogue', title=channel, dialogue=dialogue, radio=radio,
                 text=('Dans cette transmission radio simulée, le canal prévu par la consigne est utilisé. '
                       if radio else 'Voici un échange professionnel simulé avec le chef de poste. ')+
                      ' '.join(turn['speaker']+' : '+turn['text'] for turn in dialogue)+
                      ' Cette formulation sépare le constat et la proposition. Elle ne présente pas une action prévue comme déjà réalisée.'),
            dict(kind='field_consequence', title='Comprendre les conséquences du choix',
                 decision=case['decision'], wrong=case['wrong'], reason=case['reason'],
                 text='Une première option serait de '+case['wrong'][0].lower()+case['wrong'][1:]+
                      ' Le raisonnement adapté conduit à '+case['decision'][0].lower()+case['decision'][1:]+
                      ' Voici pourquoi ces choix ne sont pas équivalents. '+case['reason']),
            dict(kind='field_evolution', title='Un fait nouveau · adapter la décision',
                 evolution=case['evolution'], decision=case['next_decision'],
                 wrong=case['next_wrong'], reason=case['next_reason'],
                 text='La situation évolue maintenant. '+case['evolution']+
                      ' La décision doit être réévaluée : '+case['next_decision']+
                      ' Le point de vigilance est le suivant. '+case['next_reason']),
        ]
        # Replace the old generic comparison by the actual evidence/action/
        # consequence demonstration. Do not duplicate its spoken explanation.
        scenes = [scene for scene in row['scenes'] if scene['kind'] != 'comparison']
        assert scenes[-1]['kind'] == 'summary'
        row['scenes'] = scenes[:-1] + demonstration + scenes[-1:]
        row['transcript'] = '\n\n'.join(s['text'] for s in row['scenes'])
        row['field_case'] = case
        row['demonstration_revision'] = '20261007-aps62-v9'
    return result


if __name__ == '__main__':
    rows = courses()
    target = REPO/'elearning_native/aps62/video_scripts_v7.json'
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n')
    print(f'{len(rows)} lessons with observation, documents, dialogue and evolving decisions')
