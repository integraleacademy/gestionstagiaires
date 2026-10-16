"""Pure in-memory improvements for the next immutable VTC course edition.

No bundled course is loaded or written here. Call improve_course on a copy destined
for a new version; existing learner assignments must keep their original edition.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

# Replacement keeps the option ID and answer key. Each distractor is a genuine
# professional misconception, with feedback explaining its concrete consequence.
DISTRACTORS: dict[str, tuple[str, str]] = {
    'La couleur de leur logo': ('Le régime de TVA, sans comparer leurs frais ni leur protection sociale', 'La TVA ne décrit ni les frais réels ni la protection sociale. Deux projets au même chiffre d’affaires peuvent laisser des revenus disponibles différents.'),
    'Ce sont deux véhicules commerciaux': ('La micro-entreprise et la SASU sont deux régimes de calcul des cotisations', 'La SASU est une forme de société ; la réduire à un régime de cotisations empêche de comparer correctement personnalité juridique, fiscalité et protection sociale.'),
    'Le carburant devient gratuit': ('Les frais réels diminuent automatiquement le chiffre d’affaires à déclarer', 'Confondre dépense réelle et déduction de la base déclarée conduit à sous-déclarer le chiffre d’affaires du régime micro. La dépense continue à sortir de la banque.'),
    'Le loyer du véhicule est annulé': ('Les frais sont couverts par l’abattement fiscal et n’ont plus à être retirés du revenu disponible', 'Un abattement sert au calcul fiscal ; il ne paie pas le bailleur. Omettre le loyer surestime le revenu réellement disponible.'),
    'L’appliquer définitivement': ('Le reprendre parce qu’il figurait dans le dossier de création de l’entreprise', 'Une règle correcte à la création peut avoir changé. Sans date et champ d’application, le montant repris peut fausser la décision actuelle.'),
    'Utiliser la moyenne de seuils trouvés sur les réseaux': ('Retenir le seuil le plus élevé trouvé dans les documents, sans vérifier le régime concerné', 'Des seuils de chiffre d’affaires, de TVA et d’imposition n’ont pas le même objet ; choisir le plus élevé peut faire manquer une obligation.'),
    'Oui, pour les trajets inférieurs à 10 km': ('Oui, dès que le premier contrat commercial est signé', 'Le contrat client ne remplace ni carte professionnelle, ni assurance adaptée, ni inscription de l’exploitant. La distance ou la commande ne rend pas l’exploitation conforme.'),
    'Oui, l’immatriculation remplace tous les documents': ('Oui, la création juridique suffit pour commencer ; l’assurance peut être finalisée ensuite', 'Commencer sans assurance adaptée expose l’activité avant que le dossier métier soit conforme. Les formalités d’entreprise et les conditions de transport sont cumulatives.'),
    'Oui, si un client a versé un acompte': ('Oui, dès lors qu’un acompte finance les premières dépenses', 'Un acompte améliore la trésorerie mais ne valide pas les assurances, le conducteur ou le véhicule.'),
    'La marquer comme traitée sans preuve': ('Clôturer la tâche dès que la demande de pièce a été envoyée', 'Envoyer une demande ne prouve pas sa réception ni la conformité du document. La clôture prématurée masque une pièce encore manquante.'),
    'Attendre sans échéance': ('La reprendre seulement lors de la prochaine revue mensuelle, sans responsable désigné', 'Sans responsable et échéance liée au démarrage, la pièce peut rester absente au moment où elle est nécessaire.'),
    'Dans les stocks de carburant': ('À l’actif, avec le véhicule financé par l’emprunt', 'Le véhicule est un emploi à l’actif ; la dette qui le finance est une ressource au passif. Les regrouper ferait perdre la distinction entre bien et financement.'),
    'Dans les recettes de courses': ('Dans les produits, car le prêt a augmenté le compte bancaire', 'Recevoir un prêt augmente la banque et une dette, pas le chiffre d’affaires. Le comptabiliser en produit gonflerait artificiellement le résultat.'),
    'Seulement si elle n’a pas de clients': ('Seulement lorsque le compte de résultat est déficitaire', 'Des clients peuvent payer après les échéances de charges : un bénéfice positif ne garantit donc pas la disponibilité bancaire le jour du paiement.'),
    'Seulement avec trois salariés': ('Seulement après transformation obligatoire en société', 'La TVA et la forme juridique sont deux sujets distincts. Une entreprise individuelle au régime micro peut devenir redevable de TVA sans se transformer automatiquement en société.'),
    'À la date d’achat du véhicule': ('À la date de la prestation, même si le règlement est prévu trente jours après', 'Le plan de trésorerie suit les flux bancaires. Inscrire la recette dès la prestation masquerait les besoins de financement pendant les trente jours d’attente.'),
    'Ne plus payer de cotisations': ('Avoir encaissé assez pour rembourser intégralement les emprunts', 'Le seuil de rentabilité concerne les charges du modèle ; il ne prouve pas que toutes les échéances de financement ont été réglées.'),
    'Uniquement la couleur proposée': ('Le seul total des loyers, sans apport ni option de rachat', 'Omettre l’apport et le rachat final sous-estime le coût du financement et empêche une comparaison à périmètre égal.'),
    'L’option finale doit toujours être oubliée': ('Comparer les loyers seuls, même si l’achat final est prévu', 'Si l’option est exercée, elle fait partie des paiements. L’exclure favorise artificiellement l’offre dont le coût est reporté en fin de contrat.'),
    'Un avis client': ('Le devis du fournisseur, même si la dépense a ensuite changé', 'Un devis décrit une proposition ; il ne suffit pas à justifier le montant finalement engagé et réglé. La pièce définitive doit être rapprochée de la dépense.'),
    'Une estimation orale sans date': ('Le montant saisi dans le tableur sans conserver la pièce d’origine', 'Une saisie seule ne permet pas de vérifier la nature, le fournisseur et la date de la dépense lors d’un contrôle ou d’un rapprochement.'),
    'Le nom du conducteur dans le planning': ('La facture émise, même sans preuve de règlement', 'Émettre une facture crée une créance ; cela ne démontre pas que le client a payé. Il faut rapprocher un paiement réel du document.'),
    'Le REVTC encaisse toutes les cotisations': ('La même échéance et le même organisme s’appliquent à toutes les obligations', 'Regrouper les échéances sans vérifier leur destinataire risque de laisser un impôt, une cotisation ou un renouvellement métier impayé ou expiré.'),
    'Uniquement le nombre d’étoiles de l’hôtel': ('Le seul volume annoncé, sans horaires ni conditions d’annulation', 'Le volume ne prouve ni la faisabilité du planning ni le revenu conservé après attente ou annulation ; il faut formaliser ces conditions avant de s’engager.'),
    'La couleur choisie pour le tableau': ('Le seul chiffre d’affaires, sans coût d’acquisition ni retour des clients', 'Un chiffre d’affaires élevé peut coûter plus cher à obtenir que la contribution qu’il laisse. La fidélisation et les dépenses d’acquisition changent l’intérêt commercial.'),
    'Rejeter toute demande sans lecture': ('Appliquer immédiatement le geste commercial habituel sans relire les conditions', 'Un geste automatique peut résoudre le mauvais problème. Vérifier les horaires et conditions permet de distinguer erreur, service réalisé et simple désaccord.'),
    'Reconnaître n’importe quel montant demandé': ('Retenir le montant réclamé sans le rapprocher de la réservation et de la facture', 'Sans rapprochement des pièces, le remboursement peut être incorrect et la cause de l’écart rester inconnue.'),
    'En changeant seulement l’adresse du client': ('En renvoyant un document modifié sous le même numéro sans trace de correction', 'Une correction sans historique rompt la traçabilité. Relier facture initiale, correction ou avoir permet de comprendre ce qui a été modifié.'),
    'Ne plus remettre de devis': ('Remettre les mêmes conditions standard sans préciser l’attente pour cette mission', 'Une formule standard ne tranche pas un désaccord sur l’attente si les horaires et modalités propres à la mission restent flous.'),
}

B_FEEDBACK = {
    'B.01': 'Le choix du cadre doit comparer les mêmes recettes, les dépenses réellement supportées et la protection recherchée.',
    'B.02': 'Le démarrage demande de distinguer formalités accomplies, pièces encore attendues et argent effectivement mobilisable.',
    'B.03': 'L’actif décrit les biens et créances ; le passif explique leur financement. Les capitaux propres ne sont pas le seul solde bancaire.',
    'B.04': 'Le résultat utilise produits et charges de la période ; la banque suit solde initial, encaissements et décaissements.',
    'B.05': 'La contribution se calcule après commission et coûts variables de tous les kilomètres retenus, y compris l’approche et le retour.',
    'B.06': 'La TVA se calcule sur le HT ; pour retrouver le HT à partir du TTC, divisez par 1 plus le taux au lieu de soustraire ce pourcentage du TTC.',
    'B.07': 'La réserve calculée sur les recettes ne remplace pas les dépenses réelles : il faut déduire les deux pour estimer ce qui reste.',
    'B.08': 'Placez chaque paiement à sa date : une recette future ne finance pas automatiquement une échéance antérieure.',
    'B.09': 'Calculez la marge par course, puis divisez les charges fixes par cette marge ; arrondissez au nombre entier supérieur de courses.',
    'B.10': 'Comparez apport, totalité des échéances, éventuel rachat et postes exclus sur la même durée d’utilisation.',
    'B.11': 'Distinguez le montant facturé, la somme effectivement payée et le solde restant dû ; conservez les pièces de rapprochement.',
    'B.12': 'Le temps mobilisé comprend les tâches du périmètre indiqué ; convertir toutes les minutes en heures évite de surestimer le ratio horaire.',
    'B.MISSION': 'Rapprochez la commande, les conditions acceptées, les prestations réalisées et les flux financiers avant de conclure.',
}


def _normal(text: Any) -> str:
    return ' '.join(str(text or '').split()).casefold()


def exercise_signature(exercise: dict[str, Any]) -> tuple:
    """Same prompt, choices and semantic answer even after option ID randomisation."""
    options = {str(o['id']): _normal(o.get('text')) for o in exercise.get('options', [])}
    answer = options.get(str(exercise.get('answer')), _normal(exercise.get('answer')))
    rows = tuple(sorted((_normal(row.get('text')), options.get(str(row.get('answer')), _normal(row.get('answer')))) for row in exercise.get('rows', [])))
    return (exercise.get('kind'), _normal(exercise.get('prompt')), tuple(sorted(options.values())), answer, rows)


def _number(text: str) -> tuple[Decimal, str] | None:
    match = re.fullmatch(r'\s*(-?\d[\d\s]*(?:[,.]\d+)?)\s*(€(?:/h)?|min|courses?)\s*', text)
    if not match:
        return None
    try:
        return Decimal(match[1].replace(' ', '').replace(',', '.')), match[2]
    except InvalidOperation:
        return None


def _feedback(ex: dict[str, Any], ref: str) -> int:
    replacements = 0
    custom = {}
    revised_feedback = {text: feedback for text, feedback in DISTRACTORS.values()}
    for option in ex.get('options', []):
        if option['id'] != ex.get('answer') and option['text'] in DISTRACTORS:
            option['text'], custom[option['id']] = DISTRACTORS[option['text']]
            replacements += 1
        elif option['id'] != ex.get('answer') and option['text'] in revised_feedback:
            custom[option['id']] = revised_feedback[option['text']]
    explanation = ex.get('explanation', '')
    correct = next((o['text'] for o in ex.get('options', []) if o['id'] == ex.get('answer')), '')
    if not correct:
        return replacements
    expected = _number(correct)
    consequences = {}
    for option in ex['options']:
        oid, value = option['id'], option['text']
        if oid == ex['answer']:
            consequences[oid] = f'Vous retenez « {value} ». {explanation}'
        elif oid in custom:
            consequences[oid] = custom[oid] + ' ' + explanation
        else:
            chosen = _number(value)
            if chosen and expected and chosen[1] == expected[1]:
                delta = chosen[0] - expected[0]
                direction = 'au-dessus' if delta > 0 else 'au-dessous'
                amount = format(abs(delta), '.2f').replace('.', ',')
                consequences[oid] = f'Votre valeur est {amount} {expected[1]} {direction} du résultat attendu. {explanation}'
            else:
                consequences[oid] = f'« {value} » ne permet pas de conclure dans ce dossier. {B_FEEDBACK.get(ref, B_FEEDBACK["B.MISSION"])} {explanation}'
    ex['consequences'] = consequences
    ex['coaching'] = B_FEEDBACK.get(ref, B_FEEDBACK['B.MISSION']) + ' ' + explanation
    return replacements


def _specific_order(ex: dict[str, Any], lesson: dict[str, Any]) -> bool:
    if ex.get('kind') != 'order' or ex.get('prompt') != 'Retrouvez l’ordre des opérations dans cette procédure pédagogique.':
        return False
    steps = lesson.get('visual_steps', [])
    if len(steps) < 2:
        return False
    ex['prompt'] = f'Pour « {lesson["title"]} », retrouvez l’ordre de la méthode présentée dans le cours.'
    ex['context'] = lesson.get('manual_case', {}).get('situation') or lesson.get('deepening', {}).get('example') or lesson.get('objective', '')
    ex['options'] = [{'id': f'p{i}', 'text': f'Étape {i+1}'} for i in range(len(steps))]
    rows = [{'id': f'r{i}', 'text': f'{step["title"]} : {step["text"]}', 'answer': f'p{i}'} for i, step in enumerate(steps)]
    # Fixed non-answer order makes builds repeatable without teaching the answer by layout.
    ex['rows'] = rows[1:] + rows[:1]
    ex['explanation'] = 'La méthode suit ces étapes : ' + ' → '.join(row['text'] for row in rows) + ' ' + lesson.get('objective', '')
    ex['coaching'] = f'Reprenez le schéma « La méthode : {lesson["title"]} » : chaque étape prépare la suivante dans cette démarche pédagogique.'
    return True


def improve_course(course: dict[str, Any]) -> dict[str, Any]:
    """Mutate only *course*; return an audit of changes, preserving retained IDs.

    Duplicate removal is per journey activity, not across separate lessons,
    diagnostics or adaptive reviews. Different numerical answers/options survive.
    Planned durations are not increased or presented as measured learner time.
    """
    audit: dict[str, Any] = {'removed_duplicates': 0, 'specific_methods': 0, 'replaced_distractors': 0, 'removed_ids': {}}
    lessons = {}
    for section in course.get('sections', []):
        for activity in section.get('activities', []):
            lesson = activity.get('vtc', {})
            if lesson.get('kind') == 'lesson':
                lessons[lesson.get('ref')] = lesson
    is_b = course.get('id') == 'academy-vtc-b'
    for section in course.get('sections', []):
        for activity in section.get('activities', []):
            practice = activity.get('practice', {})
            exercises = practice.get('exercises', [])
            ref = activity.get('vtc', {}).get('ref', '')
            for ex in exercises:
                lesson = lessons.get(ex.get('competency') or ref)
                if lesson and _specific_order(ex, lesson):
                    audit['specific_methods'] += 1
                if is_b and ex.get('kind') == 'single':
                    audit['replaced_distractors'] += _feedback(ex, ex.get('competency') or ref)
            if practice.get('mode') == 'journey':
                seen, retained, removed = set(), [], []
                for ex in exercises:
                    signature = exercise_signature(ex)
                    if signature in seen:
                        removed.append(ex['id'])
                    else:
                        seen.add(signature)
                        retained.append(ex)
                if removed:
                    practice['exercises'] = retained
                    audit['removed_ids'][activity['id']] = removed
                    audit['removed_duplicates'] += len(removed)
    all_exercises = [e for s in course.get('sections', []) for a in s.get('activities', []) for e in a.get('practice', {}).get('exercises', [])]
    course.setdefault('counts', {}).update(exercises=len(all_exercises), decisions=sum(len(ex.get('rows', [])) or 1 for ex in all_exercises))
    return audit
