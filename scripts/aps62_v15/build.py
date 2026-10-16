"""Build reviewed APS editorial overlays from immutable v12 learning material.

The existing remediation bank supplies scenarios not narrated in the lessons.
They become the workshop itself, instead of repeating a worked video example.
Run with: python -m scripts.aps62_v15.build
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .challenges import CHALLENGES

ROOT = Path(__file__).resolve().parents[2] / 'elearning_native' / 'aps62'
REVISION = '20261013-aps-varied-practice-v15'
SOURCE_VERSION = '20261012-aps62-v12'

# Make the few contextual pronouns independent of the original worked example.
CONTEXT_REPAIRS = {
    ('01-01', 'evolution'): "Au musée, une porte du périmètre protégé signale une ouverture pendant que le poste examine une demande extérieure à sa mission. Que prioriser ?",
    ('01-02', 'evolution'): "Un agent présente un titre consultable et valide, mais pour une autre activité que la mission prévue. Quel contrôle reste nécessaire ?",
    ('01-03', 'evolution'): "Une ronde reste dans le périmètre de l'usine, mais elle tombe pendant la pause de l'agent d'accueil. Que vérifier ?",
    ('02-02', 'evolution'): "Après un échange apaisé, une personne saisit un objet et avance de manière menaçante vers un tiers. Que faire ?",
    ('03-01', 'evolution'): "Un premier signalement repose sur une silhouette. Un autre témoin apporte ensuite des détails précis sur des gestes immédiatement observés. Que réexaminer ?",
    ('03-02', 'evolution'): "Pendant une attente organisée en vue de la remise à l'OPJ, la personne signale une douleur et devient pâle. Que faire évoluer ?",
    ('04-01', 'evolution'): "Un service habilité demande des données, mais l'incident indiqué dans sa demande ne correspond pas au dossier préparé. Que contrôler ?",
    ('05-02', 'evolution'): "Une personne distribue des tracts dans une zone où toutes les distributions sont encadrées, quelles que soient les convictions exprimées. Que traiter ?",
    ('06-01', 'evolution'): "Un fournisseur avait proposé un cadeau avec une demande d'exception au contrôle. Il retire la demande d'exception mais maintient le cadeau. Quelle suite ?",
    ('06-04', 'evolution'): "Un agent refuse de signer ou de se connecter sous l'identité d'un collègue. Il subit ensuite des pressions. Que transmettre ?",
    ('07-01', 'evolution'): "Lors d'une réclamation liée à l'attente, un usager se rapproche vivement après votre explication. Que réévaluer ?",
    ('07-05', 'transfert'): "Un conflit entre deux équipes revient une semaine après une proposition de correction. Que vérifier ?",
    ('09-01', 'evolution'): "Dans un hall, une altercation vient de cesser. À proximité, un autre usager est soudain attaqué. Quel raisonnement appliquer à cette nouvelle situation ?",
    ('08-05', 'evolution'): "Une mesure provisoire prévoit l'utilisation d'une clé à la relève. L'équipe entrante ne dispose pas de cette clé. Quelle suite ?",
    ('09-02', 'evolution'): "Un accès alternatif a été désigné pour les secours après la fermeture du portail habituel. Ce passage devient à son tour encombré. Que faire immédiatement ?",
    ('09-03', 'evolution'): "Après le refus d'un contrôle imposé hors du cadre du poste, le client propose un contrôle avec l'accord de la personne. Que faut-il encore vérifier ?",
    ('10-01', 'evolution'): "Un passage glissant est fermé aux salariés, mais des livreurs continuent de l'utiliser. Que réévaluer ?",
    ('11-01', 'evolution'): "Un coffret électrique détérioré a été balisé, mais des visiteurs contournent ce premier balisage. Quelle suite ?",
    ('11-02', 'evolution'): "Le relais compétent a confirmé la sécurisation électrique après un accident. La victime reste inconsciente. Quelle suite ?",
    ('11-02', 'application'): "Après un accident électrique, un collègue s'approche de la victime alors que la suppression du danger n'est pas confirmée. Quelle priorité retenir ?",
    ('12-02', 'evolution'): "Un objet inhabituel a entraîné l'application de la procédure de protection. Une personne affirme en être propriétaire, sans vérification encore faite. Quelle suite ?",
    ('12-03', 'evolution'): "Une proposition de renforcement du filtrage obstruerait l'accès réservé aux secours. Quelle suite ?",
    ('13-02', 'evolution'): "Un service autorisé attend une procédure professionnelle. Son interlocuteur demande finalement un envoi à une adresse personnelle. Que réexaminer ?",
    ('14-01', 'evolution'): "Une personne présente dans une zone réservée affirme être autorisée. Le service concerné dément ensuite cette autorisation. Que faire évoluer ?",
    ('14-02', 'evolution'): "Après un signal de portique, le justificatif et l'article correspondent. Une étiquette oubliée est identifiée. Quelle mise à jour ?",
    ('14-04', 'evolution'): "Une personne appréhendée dans le cadre de l'article 73 se plaint de difficultés respiratoires pendant l'organisation du relais. Quelle suite ?",
    ('14-07', 'evolution'): "Une présence inhabituelle a été signalée sur le site. Une explication plausible est apportée et peut être vérifiée auprès d'un contact identifié. Quelle suite ?",
    ('15-05', 'evolution'): "Une voie adaptée à la mise en sécurité a été confirmée par le responsable, mais certains usagers hésitent sur la direction. Comment guider ?",
    ('15-07', 'evolution'): "Après un refus du lecteur de billets, le service habilité confirme une admission exceptionnelle après vérification. Quelle trace ?",
}


def unique_options(exercise, key):
    """Stable, balanced ordering without reusing legacy answer identifiers."""
    options = copy.deepcopy(exercise['options'])
    offset = int(hashlib.sha256(key.encode()).hexdigest()[:4], 16) % len(options)
    options = options[offset:] + options[:offset]
    mapping = {opt['id']: f'v15-{index + 1}' for index, opt in enumerate(options)}
    answer = mapping[exercise['answer']]
    for opt in options:
        opt['id'] = mapping[opt['id']]
    return options, answer


def from_drill(drill, key, stage, prompt=None):
    options, answer = unique_options(drill, key)
    return {'id': 'v15-' + key.rsplit('-', 1)[-1], 'kind': 'single',
            'stage': stage, 'context': '', 'prompt': prompt or drill['prompt'],
            'options': options, 'answer': answer, 'explanation': drill['explanation']}


def build():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    output = {'revision': REVISION, 'source_version': SOURCE_VERSION, 'sections': {}}
    all_prompts = set()
    first_reference = {}
    for module in manifest['modules']:
        course = json.loads((ROOT / 'courses' / module['id'] / (SOURCE_VERSION + '.json')).read_text())
        for section in course['sections']:
            sid = section['id']; key = sid.removeprefix('aps62-')
            row = {'practices': {}}
            prompt, correct, wrong_a, wrong_b, explanation = CHALLENGES[key]
            exercise = {'options': [{'id': 'correct', 'text': correct}, {'id': 'a', 'text': wrong_a},
                                    {'id': 'b', 'text': wrong_b}], 'answer': 'correct'}
            options, answer = unique_options(exercise, sid)
            row['question'] = {'prompt': prompt, 'options': [dict(opt, is_correct=opt['id'] == answer) for opt in options],
                               'explanation': explanation}
            for activity in section['activities']:
                kind = activity.get('academy', {}).get('kind')
                if kind == 'lesson':
                    for reference in activity['academy']['lessons']:
                        first_reference.setdefault(reference['ref'], sid)
                if kind not in ('workshop', 'transfer') or activity.get('production'):
                    continue
                original = activity['practice']; exercises = []
                if kind == 'workshop':
                    for n, ex in enumerate(original['exercises']):
                        drill = ex['remediation']
                        exercises.append(from_drill(drill, sid + '-' + ex['id'],
                            ('Situation 1 · Analyser les faits', 'Situation 2 · Choisir une action',
                             'Situation 3 · Adapter la décision')[n], CONTEXT_REPAIRS.get((key, ex['id']))))
                else:
                    for ex in original['exercises']:
                        if ex['id'] == 'variante':
                            exercises.append(from_drill(ex['remediation'], sid + '-transfert', 'Situation 1 · Appliquer la règle',
                                CONTEXT_REPAIRS.get((key, 'transfert'))))
                        else:
                            item = copy.deepcopy(ex)
                            item['id'] = 'v15-' + ex['id']
                            item['stage'] = 'Situation 2 · Justifier son choix'
                            item['prompt'] = CONTEXT_REPAIRS.get((key, ex['id']), item['prompt'])
                            if item.get('context', '').startswith('Nouvelle situation indépendante'):
                                item['context'] = ''
                            # Do not introduce another repetition after a failed answer.
                            item.pop('remediation', None)
                            item['options'], item['answer'] = unique_options(ex, activity['id'] + '-' + ex['id'])
                            exercises.append(item)
                for ex in exercises:
                    if ex['prompt'] in all_prompts:
                        raise ValueError('Repeated exercise: ' + ex['prompt'])
                    all_prompts.add(ex['prompt'])
                row['practices'][activity['id']] = {
                    'revision': REVISION, 'title': 'Trois situations pour décider' if kind == 'workshop' else 'Appliquer dans un autre contexte',
                    'mode': 'guided', 'sequential': True, 'exercises': exercises,
                }
            output['sections'][sid] = row
    assert set(CHALLENGES) == {sid.removeprefix('aps62-') for sid in output['sections']}
    output['first_reference'] = first_reference
    path = ROOT / 'editorial_v15.json'
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(f'{len(output["sections"])} sequences, {len(all_prompts)} workshop/transfer questions, {len(CHALLENGES)} new application questions')


if __name__ == '__main__':
    build()
