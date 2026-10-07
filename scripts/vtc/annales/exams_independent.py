"""Build deterministic exams from reviewed annales and independent cases.

Historical, multiple-answer and visually dependent items are never selected.
Original cases are authored below; they are not copies of lesson workshops.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path


def normal(text):
    return re.sub(r'[^a-z0-9]+', '', unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower())


# ref, prompt, correct answer, distractor 1, distractor 2, worked correction.
CASES = {letter: [] for letter in 'ABCDEFG'}
CASES['A'] = [
('A.01', 'Une réservation nominative est déjà confirmée. En arrivant, un autre passant propose de payer le trajet à la place du client. Quelle décision respecte le fonctionnement du VTC ?', 'Conserver la mission réservée ; une autre prise en charge suppose sa propre réservation préalable.', 'Accepter le passant si le prix proposé est supérieur.', 'Remplacer le nom du client une fois le passant installé.', 'La présence d’une réservation pour une personne ne permet pas de prendre un autre client à la volée. Une nouvelle mission exige une réservation préalable réelle.'),
('A.05', 'Un nouveau contrat automobile porte la mention « usage privé ». Quel point bloque son utilisation pour une activité VTC rémunérée ?', 'La garantie doit couvrir explicitement le transport rémunéré de personnes.', 'Le contrat doit seulement mentionner une utilisation quotidienne.', 'La preuve de paiement de la prime suffit quel que soit l’usage déclaré.', 'Le risque assuré doit correspondre à l’activité réelle. Un paiement à jour n’étend pas automatiquement une assurance privée au transport rémunéré.'),
('A.09', 'Une passagère signale une difficulté à marcher et voyage sans accompagnant. Quelle première réponse prépare une aide adaptée ?', 'Lui demander l’aide souhaitée et convenir d’un point de prise en charge accessible.', 'Décider de la porter jusqu’au véhicule sans lui demander son accord.', 'Demander systématiquement qu’un proche réalise le trajet avec elle.', 'Les besoins ne se déduisent pas d’un handicap présumé. Demander l’aide souhaitée respecte l’autonomie et permet de préparer l’accès au véhicule.'),
('A.10', 'Après une course, un chauffeur veut publier une photo de son planning pour montrer son activité. Les noms et numéros de clients sont visibles. Que faire ?', 'Retirer ces données avant toute publication.', 'Publier si aucun montant payé ne figure sur la photo.', 'Conserver les noms et masquer uniquement les numéros.', 'Les noms et coordonnées sont des données personnelles. La promotion de l’activité ne justifie pas leur exposition ; il faut supprimer les éléments identifiants.'),
('A.11', 'Lors d’un contrôle, la carte du conducteur est valide mais le justificatif de réservation est introuvable. Quelle conclusion est exacte ?', 'La carte et la preuve de réservation répondent à deux obligations distinctes.', 'La carte dispense de produire une preuve pour chaque réservation.', 'Une facture établie après la course prouve à elle seule l’antériorité de la réservation.', 'La carte autorise le conducteur à exercer ; la réservation justifie les conditions de la mission. Un document ne remplace pas l’autre.'),
('A.12', 'Deux courriers arrivent : une décision préfectorale sur la carte et un jugement pénal. Comment préparer les recours ?', 'Identifier séparément la nature de chaque décision, la juridiction compétente et le délai indiqué.', 'Adresser une lettre unique au client à l’origine du contrôle.', 'Faire appel de tous les documents devant la même juridiction sans distinguer leur nature.', 'Une décision administrative et un jugement pénal ne relèvent pas de la même voie de contestation. Il faut lire les notifications et leurs délais au lieu de confondre les procédures.'),
]
CASES['C'] = [
('C.03', 'À 72 km/h, un véhicule parcourt 20 mètres par seconde. Quelle distance parcourt-il pendant deux secondes avant tout freinage ?', '40 mètres.', '20 mètres.', '72 mètres.', 'Distance = vitesse en mètres par seconde × durée. Ici 20 × 2 = 40 m. Ce calcul porte seulement sur le temps avant freinage, pas sur la distance totale d’arrêt.'),
('C.07', 'Pendant une mission longue, le conducteur bâille et peine à garder une trajectoire régulière. Quelle action traite le risque immédiat ?', 'Rejoindre un endroit sûr pour interrompre la conduite et se reposer.', 'Augmenter le volume sonore tout en poursuivant jusqu’à destination.', 'Réduire légèrement la vitesse et compter sur la conversation avec le client.', 'Les signes de somnolence imposent une interruption dans un lieu sûr. La musique ou la conversation peuvent masquer la fatigue sans restaurer la vigilance.'),
('C.09', 'Le téléphone demande de confirmer une nouvelle destination pendant que le véhicule roule. Quelle organisation évite la manipulation dangereuse ?', 'S’arrêter dans un endroit autorisé et sûr avant de modifier la destination.', 'Saisir seulement le numéro de rue en gardant le téléphone sous le volant.', 'Confirmer rapidement au prochain ralentissement sans s’arrêter.', 'La saisie détourne l’attention visuelle et mentale. Une modification de destination se prépare à l’arrêt dans des conditions sûres, même si elle paraît brève.'),
('C.11', 'La pluie commence après une longue période sèche. Le trajet reste dans les délais. Quelle adaptation est pertinente ?', 'Réduire l’allure selon l’adhérence et augmenter les distances.', 'Conserver les mêmes marges tant qu’aucune limitation supplémentaire n’est affichée.', 'Suivre de plus près le véhicule précédent pour utiliser sa trajectoire.', 'Une limitation est un plafond, pas une garantie d’adhérence. La pluie et les dépôts sur la chaussée justifient davantage de marge, même sans retard ni nouveau panneau.'),
]
CASES['F'] = [
('F.01', 'Un quartier compte cinq nouveaux hôtels. Quelle donnée transforme cette observation en estimation commerciale exploitable ?', 'Leurs besoins réels de transferts, horaires et conditions de partenariat.', 'Le seul nombre de chambres construites.', 'Le tarif le plus élevé affiché par un hôtel.', 'La présence d’hôtels signale un marché possible ; les besoins, créneaux et modalités d’achat permettent d’évaluer les courses accessibles.'),
('F.02', 'Une offre « transfert familles » promet deux sièges enfants sur réservation. Quel contrôle doit précéder la confirmation ?', 'Vérifier les équipements adaptés disponibles et la capacité de transport avec les bagages.', 'Confirmer la formule puis vérifier les équipements le jour même.', 'Remplacer les sièges promis par une remise sur la course.', 'L’offre doit correspondre à une capacité réelle. Le matériel, le nombre de passagers et les bagages conditionnent l’exécution de la promesse commerciale.'),
('F.03', 'Une course rapporte 84 € avant une commission de 25 % et entraîne 18 € de coûts variables. Quelle contribution reste pour couvrir les charges fixes ?', '45 €.', '63 €.', '66 €.', 'Commission : 84 × 25 % = 21 €. Contribution : 84 − 21 − 18 = 45 €. Le montant après commission n’est pas encore la contribution après coûts variables.'),
('F.04', 'Un devis prévoit le trajet et le prix mais ne traite pas l’attente à l’arrivée du train. Quelle précision réduit un désaccord ultérieur ?', 'Le délai inclus, le point de départ du décompte et le prix de l’attente supplémentaire.', 'Une mention « attente possible » sans durée ni montant.', 'La seule durée habituelle du trajet routier.', 'Une attente facturable doit pouvoir être comprise et calculée à partir des conditions proposées. Une formule générale ne précise ni le seuil ni le coût.'),
('F.05', 'Deux canaux génèrent chacun 1 000 € de ventes. Le premier prélève 200 € et le second coûte 80 € de prospection pour ces mêmes ventes. À coûts de mission identiques, quel canal laisse la meilleure contribution ?', 'Le second, avec 120 € de plus.', 'Le premier, car une commission remplace les coûts de véhicule.', 'Ils sont équivalents puisque leur chiffre d’affaires est identique.', 'Les coûts commerciaux diffèrent : 1 000 − 200 = 800 €, contre 1 000 − 80 = 920 €. L’écart est de 120 €, avant les mêmes coûts de mission.'),
('F.06', 'Une campagne de prospection obtient 12 rendez-vous pour 60 contacts ciblés. Quel est son taux de prise de rendez-vous ?', '20 %.', '12 %.', '5 %.', 'Le taux se calcule avec le résultat sur le nombre de contacts : 12 ÷ 60 × 100 = 20 %. Le nombre brut de rendez-vous ne constitue pas un taux.'),
('F.07', 'Un hôtel propose des transferts à horaires fixes avec règlement à 45 jours. Quel point doit être étudié en plus du prix par course ?', 'Le financement des dépenses engagées avant le règlement.', 'Le montant du règlement comme s’il était encaissé le jour de la course.', 'Le nombre d’étoiles de l’hôtel comme seule garantie du paiement.', 'Le carburant, les commissions et d’autres dépenses peuvent être payés avant l’encaissement. Le délai client crée donc un besoin de trésorerie.'),
('F.08', 'Une page de réservation affiche « prix tout compris » mais ajoute des frais obligatoires au dernier écran. Quelle amélioration corrige le problème ?', 'Présenter clairement le prix complet et les conditions avant la validation.', 'Conserver les frais cachés et les expliquer uniquement après paiement.', 'Retirer la description du trajet pour simplifier le premier écran.', 'La clarté porte sur l’offre entière et ses conditions. Un client doit comprendre le montant à accepter avant de confirmer sa commande.'),
('F.09', 'Un client effectue une première course. Le chauffeur souhaite réutiliser son numéro pour des offres promotionnelles. Quelle démarche respecte la finalité initiale des données ?', 'Vérifier les conditions applicables à la prospection et informer le client avant une réutilisation commerciale.', 'Considérer la réservation comme un accord permanent à toute publicité.', 'Transmettre le numéro à un partenaire qui se chargera de demander ensuite.', 'Une coordonnée collectée pour exécuter une course ne devient pas librement réutilisable. La prospection demande de vérifier sa base et l’information du client.'),
('F.10', 'Sur 80 courses, 6 ont commencé avec plus de dix minutes de retard. Quel indicateur mesure exactement ce problème ?', '7,5 % des courses ont dépassé dix minutes de retard au départ.', '6 % des courses ont dépassé dix minutes de retard au départ.', 'Tous les clients ont subi en moyenne dix minutes de retard.', '6 ÷ 80 × 100 = 7,5 %. Cet indicateur ne donne ni le retard moyen de tous les trajets ni la durée de chaque retard.'),
('F.11', 'Un client conteste 15 € d’attente facturés. Quelle information doit être rapprochée en premier ?', 'Les conditions acceptées, les horaires réellement constatés et le calcul facturé.', 'Le seul montant que le client souhaite payer.', 'La note moyenne laissée par les autres clients.', 'Le rapprochement de la commande, des faits et du calcul permet de distinguer erreur de facturation et désaccord sur des conditions connues.'),
('F.12', 'Une activité réalise 2 400 € sur 40 courses. Quel est son panier moyen par course ?', '60 €.', '40 €.', '96 €.', 'Le panier moyen par course est le chiffre d’affaires divisé par le nombre de courses : 2 400 ÷ 40 = 60 €. Il ne représente pas le bénéfice par course.'),
]


def _originals(module):
    result = []
    for n, (ref, prompt, correct, wrong1, wrong2, explanation) in enumerate(CASES[module], 1):
        options = [{'id': 'a', 'text': correct}, {'id': 'b', 'text': wrong1}, {'id': 'c', 'text': wrong2}]
        # Rotate positions without making the correct position predictable.
        shift = int(hashlib.sha256(prompt.encode()).hexdigest()[:4], 16) % 3
        options = options[shift:] + options[:shift]
        answer = next(chr(97+i) for i, option in enumerate(options) if option['id'] == 'a')
        options = [{'id': chr(97+i), 'text': option['text']} for i, option in enumerate(options)]
        result.append({'id': f'independent-{module.lower()}-{n:02}', 'prompt': prompt, 'options': options,
                       'answer': answer, 'explanation': explanation, 'module': module, 'sources': [],
                       'lesson_refs': [ref], 'origin': 'pedagogical-independent'})
    return result


def _pool(module, documents):
    result, seen = [], set()
    for doc in sorted(documents, key=lambda d: (d.get('year', 0), d['id']), reverse=True):
        for section in doc['sections']:
            if section['module'] != module:
                continue
            for q in section['questions']:
                if q['status'] != 'active' or len(q['answers']) != 1 or q.get('context') or q.get('image'):
                    continue
                # Underspecified distance estimates are unsuitable for an autonomous test.
                if 'distance d’arrêt' in q['prompt'] or "distance d'arrêt" in q['prompt']:
                    continue
                key = normal(q['prompt'])
                if key in seen:
                    continue
                seen.add(key)
                result.append({'id': 'exam-' + q['id'], 'prompt': q['prompt'].strip(),
                               'options': copy.deepcopy(q['options']), 'answer': q['answers'][0],
                               'explanation': q['explanation'], 'module': module,
                               'sources': [[s['title'], s['url']] for s in q.get('sources', []) if s.get('url')],
                               'lesson_refs': copy.deepcopy(q['lesson_refs']), 'origin': 'reviewed-annales',
                               'source_question_id': q['id'], 'source_title': doc['title'],
                               'source_page': q['page'], 'correction_origin': q['correction_origin']})
    return result


def _module_questions(module, documents):
    if module == 'D':
        data = json.loads(Path(__file__).with_name('exam-d-independent.json').read_text())
        return copy.deepcopy(data['questions'] if isinstance(data, dict) else data)
    if module == 'G':
        data = json.loads(Path(__file__).with_name('exam-g-supplement.json').read_text())
        originals = copy.deepcopy(data['questions'] if isinstance(data, dict) else data)
    else:
        originals = _originals(module)
    pool = _pool(module, documents)
    # French texts and VTC-specific cases are self-contained original scenarios.
    candidates = originals + pool if module in 'DG' else pool + originals
    selected, seen = [], set()
    for q in candidates:
        key = normal(q['prompt'])
        if key not in seen:
            selected.append(q)
            seen.add(key)
        if len(selected) == 30:
            break
    if len(selected) != 30:
        raise ValueError(f'Module {module}: {len(selected)} autonomous questions; 30 required')
    return selected


def build_exams(previous_exam, annales_sources, version):
    """Return one new exam, preserving the existing server-side marking schema."""
    module = previous_exam['id'].removeprefix('vtc-').upper()
    documents = list(annales_sources.values()) if isinstance(annales_sources, dict) else list(annales_sources)
    if module == 'H':
        h = json.loads(Path(__file__).with_name('exam-h-independent.json').read_text())
        questions = copy.deepcopy(h['questions'] if isinstance(h, dict) else h)
    elif module == 'FINAL':
        # 100 questions across all seven theoretical subjects: 15+15+14*5.
        questions = []
        for letter in 'ABCDEFG':
            bank = _module_questions(letter, documents)
            # Spread coverage throughout each module instead of taking its first topics.
            n = 15 if letter in 'AB' else 14
            questions.extend(bank[(i * len(bank)) // n] for i in range(n))
        questions = sorted(questions, key=lambda q: hashlib.sha256(q['id'].encode()).hexdigest())
    else:
        questions = _module_questions(module, documents)
    assert len({normal(q['prompt']) for q in questions}) == len(questions), 'Duplicate exam prompts'
    for q in questions:
        assert q['answer'] in {o['id'] for o in q['options']}
        assert len({o['id'] for o in q['options']}) == len(q['options'])
        assert q['explanation'] and q.get('lesson_refs'), q['id']
    exam = copy.deepcopy(previous_exam)
    exam.update(version=version, questions=questions,
                notice='Entraînement pédagogique à choix unique. Les questions historiques et celles nécessitant un visuel absent sont exclues. La correction renvoie aux leçons à revoir ; ce bilan ne remplace pas le barème de l’examen officiel.',
                construction={'reviewed_on': '2026-10-07', 'independent_of_workshops': True,
                              'annales_questions': sum(q.get('origin') == 'reviewed-annales' for q in questions),
                              'original_questions': sum(q.get('origin') != 'reviewed-annales' for q in questions)})
    return exam
