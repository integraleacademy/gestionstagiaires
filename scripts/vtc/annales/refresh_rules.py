"""Narrow, idempotent rule reconciliation for the annales edition of VTC courses.

Only mutate a new in-memory course, never the immutable source edition or annales.
``refresh_course(course)`` returns an audit list of actual edits and stores the
bounded review scope in ``course['rule_review']``. Historical source quotations
and distractors are not globally search/replaced.

Review of the 96 v4 lessons on 2026-10-07 found their substantive statements
already current for these topics. The corrections below are conservative guards
against reintroducing specific mistakes found in the supplied 2020–2022 annales.
"""
from __future__ import annotations

import copy
import re

REVIEW_DATE = '2026-10-07'

RULES = {
    'penalty-l3124-12': {
        'refs': ['A.12', 'G.06'],
        'source': 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000047053344',
        'text': 'Depuis le 27 juin 2026, les faits visés par l’article L3124-12 du code des transports, notamment certaines prises en charge sans réservation préalable, exposent une personne physique à trois ans d’emprisonnement et 45 000 € d’amende au maximum, ainsi qu’aux peines complémentaires prévues. Une autre infraction, notamment d’assurance, exige son propre texte.',
    },
    'rne': {
        'refs': ['B.02'],
        'source': 'https://entreprendre.service-public.gouv.fr/actualites/A15855',
        'text': 'Depuis le 1er janvier 2023, l’immatriculation artisanale relève du Registre national des entreprises (RNE), par le guichet unique. L’ancien Répertoire des métiers et son extrait D1 ne sont pas les démarches et justificatifs actuels. L’immatriculation ne remplace ni le REVTC ni la carte professionnelle du conducteur.',
    },
    'electric-scope': {
        'refs': ['G.03'],
        'source': 'https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000030437123',
        'text': 'L’exception concernant les catégories de véhicules hybrides et électriques porte sur les caractéristiques visées par l’arrêté du 26 mars 2015. Elle ne supprime pas l’ensemble des contraintes : nombre de places, assurance, contrôle technique et autres obligations applicables doivent toujours être vérifiés.',
    },
    'fuel-vat': {
        'refs': ['B.06'],
        'source': 'https://bofip.impots.gouv.fr/bofip/1194-PGP.html/identifiant=BOI-TVA-DED-30-30-40-20210224',
        'text': 'La TVA sur un carburant n’est pas récupérable automatiquement dans tous les cas. Le droit à déduction dépend du régime de TVA, de la nature de la dépense et de l’affectation du véhicule. Une entreprise en franchise en base ne récupère pas la TVA sur ses achats.',
    },
    'signage-private': {
        'refs': ['G.04'],
        'source': 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000034389549/2026-05-03',
        'text': 'La carte professionnelle du conducteur et la signalétique du véhicule sont distinctes. L’ancienne phrase de R3122-8 imposant de retirer ou d’occulter la signalétique hors activité ne figure plus dans sa rédaction depuis juillet 2017. Les prescriptions actuelles de délivrance, fixation et emploi doivent être vérifiées avant de reprendre une ancienne consigne.',
    },
}

# Explicit assertions only. A question asking whether a rule is true and a wrong
# answer option containing an obsolete number must remain untouched.
ASSERTIONS = {
    'rne': re.compile(r"^(?:l['’]entreprise|le futur chef d['’]entreprise|l['’]artisan) (?:doit |est tenu de )?(?:s['’]inscri(?:re|t)|s['’]immatriculer|être immatriculé) au [Rr]épertoire des [Mm]étiers[.! ]"),
    'electric-scope': re.compile(r"^(?:un|le|les) véhicules? électriques? (?:n['’]a|n['’]ont) (?:aucune contrainte|pas de (?:contrainte|caractéristique technique))", re.I),
    'fuel-vat': re.compile(r"^la TVA sur les carburants est (?:toujours |entièrement |totalement )?récupérable (?:totalement )?dans tous les cas", re.I),
    'signage-private': re.compile(r"^(?:la signalétique VTC|la signalétique) (?:doit être |est )retirée ou occultée (?:si|lorsque|quand) le véhicule (?:est utilisé|n['’]est pas utilisé)", re.I),
}


def _rule_for_assertion(text: str, ref: str | None) -> str | None:
    # A dated observation/quotation is deliberately not treated as a current rule.
    if re.search(r'\b(?:ancien|ancienne|historique|corrigé|annale)\b', text, re.I):
        return None
    if (ref in RULES['penalty-l3124-12']['refs']
            and re.search(r'L\.?\s*3124\s*[-–]\s*12|prise en charge.*sans réservation|maraude', text, re.I)
            and re.search(r'15[\s.\u00a0]*000\s*(?:€|euros)|(?:un|1) an d[’\']emprisonnement', text, re.I)):
        return 'penalty-l3124-12'
    for key, pattern in ASSERTIONS.items():
        if ref in RULES[key]['refs'] and pattern.search(text):
            return key
    return None


def _replace_text_tree(value, ref, audit, path):
    if isinstance(value, str):
        rule = _rule_for_assertion(value, ref)
        if rule:
            replacement = RULES[rule]['text']
            audit.append({'rule': rule, 'path': path, 'before': value, 'after': replacement,
                          'source': RULES[rule]['source']})
            return replacement
        return value
    if isinstance(value, list):
        return [_replace_text_tree(v, ref, audit, f'{path}[{i}]') for i, v in enumerate(value)]
    if isinstance(value, dict):
        return {k: _replace_text_tree(v, ref, audit, f'{path}.{k}') for k, v in value.items()}
    return value


def _current_penalty_exercise(original):
    """Replace the whole exercise, preserving its stable ID and provenance tags."""
    replacement = {
        'id': original['id'], 'kind': 'single', 'competency': 'G.06',
        'context': 'Le 7 octobre 2026, un conducteur prend en charge dans la rue une personne qui n’avait pas réservé. L’exercice vise les faits entrant dans l’article L3124-12 du code des transports.',
        'prompt': 'Quels maxima de peine principale ce texte prévoit-il pour une personne physique ?',
        'options': [
            {'id': 'current', 'text': 'Trois ans d’emprisonnement et 45 000 € d’amende.'},
            {'id': 'former', 'text': 'Un an d’emprisonnement et 15 000 € d’amende.'},
            {'id': 'insurance', 'text': 'L’amende du seul défaut d’assurance, quelle que soit la prise en charge.'},
        ],
        'answer': 'current',
        'explanation': RULES['penalty-l3124-12']['text'],
        'coaching': 'L’erreur à éviter est d’utiliser le plafond d’une ancienne annale ou de confondre maraude et infraction d’assurance. Identifier l’article, la date et la personne visée avant d’appliquer une sanction.',
        'consequences': {
            'current': 'La date et le texte applicable sont correctement identifiés.',
            'former': 'Ces maxima correspondent à l’ancienne rédaction ; la réforme s’applique depuis le 27 juin 2026.',
            'insurance': 'Les obligations d’assurance et de réservation relèvent d’infractions distinctes.',
        },
        'sources': [{'title': 'Code des transports · Article L3124-12', 'url': RULES['penalty-l3124-12']['source']}],
        'regulatory_refresh': {'date': REVIEW_DATE, 'reason': 'Ancien plafond devenu inexact : exercice entier remplacé, y compris clé et explication.'},
    }
    if 'stage' in original:
        replacement['stage'] = original['stage']
    return replacement


def refresh_course(course: dict) -> list[dict]:
    """Reconcile proven legacy assertions in a *new* course object; return edits.

    The review excludes imported historical annales activities. It never changes
    a question's distractor in isolation and never applies a global 15000→45000
    replacement (financial exercises and different offences retain their values).
    """
    audit = []
    for si, section in enumerate(course.get('sections', [])):
        for ai, activity in enumerate(section.get('activities', [])):
            if 'annales' in activity.get('id', '') or activity.get('annales'):
                continue
            vtc = activity.get('vtc', {})
            ref = vtc.get('ref')
            base = f'sections[{si}].activities[{ai}]'
            for key in ('paragraphs', 'deepening', 'cards', 'visual_steps', 'visual_table'):
                if key in vtc:
                    vtc[key] = _replace_text_tree(vtc[key], ref, audit, f'{base}.vtc.{key}')
            practice = activity.get('practice', {})
            for qi, exercise in enumerate(practice.get('exercises', [])):
                if exercise.get('status') == 'historical' or exercise.get('source_question_id'):
                    continue
                selected_ids = exercise.get('answers') or [exercise.get('answer')]
                selected = ' '.join(o.get('text', '') for o in exercise.get('options', []) if o.get('id') in selected_ids)
                subject = ' '.join([exercise.get('prompt', ''), exercise.get('context', ''), exercise.get('explanation', '')])
                if (re.search(r'L\.?\s*3124\s*[-–]\s*12|maraude|prise en charge.*sans réservation', subject, re.I)
                        and re.search(r'15[\s.\u00a0]*000\s*(?:€|euros)|(?:un|1) an d[’\']emprisonnement', selected, re.I)):
                    replacement = _current_penalty_exercise(exercise)
                    practice['exercises'][qi] = replacement
                    audit.append({'rule': 'penalty-l3124-12', 'path': f'{base}.practice.exercises[{qi}]',
                                  'before': copy.deepcopy(exercise), 'after': copy.deepcopy(replacement),
                                  'source': RULES['penalty-l3124-12']['source']})
    previous = course.get('rule_review', {})
    recorded = list(previous.get('changes', [])) if previous.get('reviewed_on') == REVIEW_DATE else []
    seen = {(item['rule'], item['path']) for item in recorded}
    for item in audit:
        if (item['rule'], item['path']) not in seen:
            recorded.append({key: item[key] for key in ('rule', 'path', 'source')})
            seen.add((item['rule'], item['path']))
    course['rule_review'] = {
        'reviewed_on': REVIEW_DATE,
        'scope': 'Contradictions ciblées relevées dans les annales 2020–2022 ; ce contrôle ne vaut pas audit universel de toute réglementation.',
        'source_edition': '20261007-vtc-v4-visuals',
        'topics_checked': ['honorabilité et accès 2026', 'sanctions T3P 2026', 'réservation 2025',
                           'RNE et ancien RM', 'TVA, micro et résultat', 'patrimoines EI',
                           'capacité financière', 'caractéristiques et signalétique du véhicule',
                           'fin de course et nouvelle réservation'],
        'changes': recorded,
    }
    return audit
