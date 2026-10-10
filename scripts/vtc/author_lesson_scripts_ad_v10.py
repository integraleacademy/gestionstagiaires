#!/usr/bin/env python3
"""Build reviewed A–D lesson narrations from the existing VTC pedagogy edition.

Only the source selection/transitions and the short display extracts are authored
here. No legal, financial or medical rules are inferred by this builder.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from elearning_native.vtc import load_bundled_course

VERSION = '20261010-vtc-v6-pedagogie'
OUT = ROOT / 'elearning_native/vtc/lesson_video_scripts_v10'

# Specific examples from the manual are preferred to its generic repeated case.
# The review overrides below only paraphrase or explain information in the course.
OVERRIDES = {}
POINTS = {}

OVERRIDES.update({
 'A.03': {'example': 'Samir reçoit son résultat favorable en théorie. Il prévoit sa pratique et les démarches de carte. Il ne commence pas entre-temps à transporter des clients sur la seule base de son relevé de notes.'},
})
POINTS.update({
 'A.01': {0:{0:'Un transport rémunéré, à la demande, en véhicule de petite capacité.'},2:{1:'Identifier l’activité, puis vérifier les conditions pour la réaliser.'}},
 'A.02': {0:{1:'La plateforme met en relation ; son contrôle ne remplace pas vos obligations.'},1:{0:'L’indépendant peut cumuler deux fonctions, avec des preuves distinctes.'}},
 'A.03': {0:{0:'Permis, aptitude, honorabilité et examen : des conditions distinctes.',1:'Nouvelles demandes : fin de l’ancienne voie nationale par expérience depuis le 12 août 2026.'},2:{0:'Réussir la théorie ne permet pas encore de transporter des clients.'}},
 'A.04': {0:{1:'Un événement peut interrompre le droit d’exercer avant le renouvellement.'},1:{0:'Alerte, dépôt et expiration : trois dates différentes.',1:'Suivre le titulaire, les pièces manquantes et la décision réelle.'}},
 'A.05': {0:{1:'RC professionnelle d’exploitation : dommages liés à l’activité, selon le contrat.'},1:{1:'Assurance de circulation et RC professionnelle ont des objets différents.'}},
 'A.06': {0:{0:'Un traitement défavorable fondé sur un critère protégé est interdit.',1:'Distinguer discrimination et impossibilité objective et proportionnée.'},1:{0:'Justifier la décision par la capacité, les équipements ou un danger réel.',1:'Une supposition sur la personne ne constitue pas un critère de service.'}},
 'A.07': {0:{0:'Des propos ou comportements sexistes ou sexuels peuvent porter atteinte à la dignité.',1:'Consentement : libre, éclairé, spécifique, préalable et révocable.'},1:{0:'Les sollicitations insistantes et contacts imposés ne sont pas un désaccord commercial.'}},
 'A.08': {1:{1:'Décrire le lieu, les faits, les personnes et les dangers présents.'},2:{0:'Une passagère menacée demande un lieu de dépose sûr.'}},
 'A.09': {0:{1:'Chiens guides et d’assistance : droit d’accès sous conditions légales, sans supplément.'},2:{1:'Adapter les explications et la communication avec le passager.'}},
 'A.10': {0:{1:'Verrouiller les appareils et limiter l’accès aux réservations.'},1:{0:'Les données nécessaires au service ne peuvent pas servir à tous les usages.',1:'Identifier la finalité, le besoin réel et le destinataire.'}},
 'A.12': {2:{1:'Construire la chronologie des engagements, des faits et des mesures prises.'}},
})



OVERRIDES.update({
 'B.01': {'pitfall':'Aucun statut n’est le meilleur pour tous. Comparez le même projet, les mêmes recettes et les mêmes dépenses.'},
 'B.02': {'example':'Une entreprise a quatre mille euros disponibles et trois mille deux cents euros de paiements de démarrage certains. Quatre mille moins trois mille deux cents donnent huit cents euros. Ce solde reste disponible avant les recettes suivantes ; il ne permet pas d’ignorer les charges du mois à venir.', 'pitfall':'L’immatriculation de l’entreprise ne remplace pas les autorisations propres au transport.'},
 'B.03': {'example':'Dans un bilan simplifié, le véhicule vaut dix-huit mille euros, les clients doivent deux mille euros et la banque contient quatre mille euros. Dix-huit mille plus deux mille plus quatre mille donnent vingt-quatre mille euros à l’actif. Au passif, huit mille euros de capitaux propres, quatorze mille euros d’emprunt et deux mille euros de dettes fournisseurs totalisent aussi vingt-quatre mille euros.', 'explanation':'Lorsqu’un client règle une facture déjà comptabilisée, la créance diminue et la banque augmente. Le total de l’actif peut rester identique. L’encaissement ne crée pas une deuxième vente. À l’inverse, un emprunt fait entrer de l’argent et crée une dette : ce n’est pas du chiffre d’affaires. Ces distinctions évitent de confondre le solde bancaire avec la richesse produite par les courses.', 'pitfall':'L’égalité entre actif et passif ne prouve pas, à elle seule, la bonne santé de l’entreprise.'},
 'B.04': {'example':'Sur un mois fictif, les produits sont de six mille euros, les charges d’exploitation de quatre mille cinq cents euros et les intérêts de cent euros. Six mille moins quatre mille cinq cents, puis moins cent, donnent mille quatre cents euros de résultat avant impôt. Un remboursement de capital de cinq cents euros réduit la banque, mais n’ajoute pas cinq cents euros de charge.', 'pitfall':'Résultat et trésorerie ne varient pas toujours ensemble. Gardez la même période et la même base dans le calcul.'},
 'B.05': {'example':'Une mission comprend huit kilomètres d’approche, vingt-quatre kilomètres avec le passager et huit kilomètres de retour. Le véhicule parcourt donc quarante kilomètres. Avec une hypothèse de vingt-quatre centimes de coût variable par kilomètre, quarante multiplié par zéro virgule vingt-quatre donnent neuf euros soixante. Multiplier seulement les vingt-quatre kilomètres du passager aurait oublié l’approche et le retour.', 'pitfall':'Un kilomètre sans client coûte aussi de l’argent. Une contribution positive n’est pas automatiquement un bénéfice net.'},
 'B.06': {'intro':[
  'La TVA collectée sur les ventes n’est pas un revenu appartenant à l’entreprise. La TVA déductible sur certains achats peut réduire le montant à reverser, sous réserve des conditions de déduction. Dans les exemples du cours, le transport intérieur de voyageurs est étudié au taux de dix pour cent lorsque l’entreprise est redevable ; des prestations accessoires ou particulières peuvent appeler une autre analyse.',
  'Pour obtenir le prix toutes taxes comprises, multipliez le prix hors taxes par un plus le taux, exprimé en nombre décimal. Pour retrouver le prix hors taxes, divisez par ce même coefficient. En franchise en base, vous ne facturez pas la TVA et ne la déduisez pas. Le régime micro et la franchise sont indépendants.'
 ], 'depth':'Le taux s’applique au prix hors taxes. Au taux de dix pour cent, le coefficient est un virgule dix. Pour passer au prix toutes taxes comprises, on multiplie par un virgule dix ; pour revenir au prix hors taxes, on divise par un virgule dix. Retirer dix pour cent du prix toutes taxes comprises conduit à une erreur, car on utilise une base différente. Calculez ensuite la taxe par différence et vérifiez que le prix hors taxes, augmenté de la TVA, donne bien le prix payé.',
 'example':'Une course est vendue quatre-vingt-huit euros toutes taxes comprises, avec une TVA de dix pour cent. Quatre-vingt-huit divisé par un virgule dix donnent quatre-vingts euros hors taxes. La différence est de huit euros de TVA. Sur une période fictive, six cents euros de TVA collectée moins cent quatre-vingts euros de TVA déductible donnent quatre cent vingt euros à reverser, hors autres corrections.',
 'explanation':'Toutes les dépenses ne donnent pas automatiquement droit à déduction : le justificatif, l’affectation et la nature de l’achat comptent. Le montant à reverser doit être anticipé dans la trésorerie.',
 'pitfall':'Pour retrouver le hors taxes, divisez le toutes taxes comprises par le coefficient ; ne soustrayez pas directement le pourcentage.'},
 'B.07': {'example':'Dans cet exercice, quatre mille euros sont encaissés et le taux social pédagogique est de vingt et un virgule deux pour cent, hors autres contributions et dispositifs. Quatre mille multiplié par zéro virgule deux cent douze donnent huit cent quarante-huit euros de cotisations. Après mille cinq cents euros de frais, il reste mille six cent cinquante-deux euros avant impôt et autres charges. Ce taux sert au calcul de l’exercice ; il ne remplace pas la vérification du taux applicable à votre situation.', 'pitfall':'Le plafond du régime micro et les seuils de franchise de TVA répondent à des règles distinctes.'},
 'B.08': {'example':'Le solde est de mille deux cents euros. Un paiement de mille cinq cents euros arrive avant un encaissement de neuf cents euros. Après le paiement, mille deux cents moins mille cinq cents donnent un solde temporaire de moins trois cents euros. L’encaissement suivant le remonte à six cents euros. Le solde final positif ne fait pas disparaître le manque d’argent à la première échéance.', 'pitfall':'Une facture payable le trente ne finance pas automatiquement un prélèvement prévu le dix.'},
 'B.09': {'depth':'Le seuil de rentabilité se calcule à partir des charges fixes et de la marge sur coûts variables. Avec un prix unitaire et un coût variable unitaire constants, la marge unitaire vaut le prix moins le coût variable. Le nombre minimal de prestations doit couvrir les charges fixes ; lorsqu’il n’est pas entier, on arrondit au nombre supérieur. Un résultat arrondi vers le bas laisserait une partie des charges non couverte.', 'example':'Avec neuf cents euros de charges fixes, un prix de soixante euros et un coût variable de vingt-quatre euros par course, la marge unitaire est de trente-six euros. Soixante moins vingt-quatre donnent trente-six. Neuf cents divisé par trente-six donnent vingt-cinq courses pour couvrir les charges fixes dans ce modèle simplifié.', 'pitfall':'Le seuil dépend des charges retenues. Oublier la rémunération, les cotisations ou des kilomètres à vide fausse la conclusion.'},
 'B.10': {'example':'Une location fictive coûte sept cents euros par mois sur trente-six mois, avec deux mille euros initiaux et neuf cents euros de frais prévus. Trente-six fois sept cents donnent vingt-cinq mille deux cents euros. Avec les versements et frais supplémentaires, le scénario totalise vingt-huit mille cent euros. Une offre à six cent cinquante euros par mois peut rester plus chère si les kilomètres supplémentaires et les services exclus dépassent l’écart.', 'pitfall':'Une mensualité faible ne garantit pas un coût total faible.'},
 'B.11': {'example':'Un transfert a été facturé quatre-vingt-cinq euros. Le client paie cinquante euros, puis trente-cinq euros. Le total réglé est de quatre-vingt-cinq euros et le reste dû est zéro, à condition que les deux règlements soient rapprochés de cette facture. Une facture décrit ce qui est dû ; les règlements établissent ce qui a été encaissé.', 'pitfall':'Une facture ne prouve pas, à elle seule, que le paiement a été reçu.'},
 'B.12': {'example':'Six heures de transport, une heure d’approche, trente minutes de nettoyage et trente minutes de gestion représentent huit heures mobilisées. Avec cent soixante euros de revenu de référence dans cet exercice, cent soixante divisé par huit donnent vingt euros par heure. Diviser seulement par les six heures de transport ferait paraître le revenu horaire plus élevé en oubliant du temps réellement travaillé.', 'pitfall':'Le chiffre d’affaires d’un indépendant ne se compare pas directement à un salaire net.'},
})

POINTS.update({
 'B.01': {0:{1:'Comparer responsabilités, administration, fiscalité et protection sociale.'},1:{0:'Forme juridique, fiscalité, régime social et TVA : quatre questions distinctes.',1:'Adapter le choix au projet, aux frais, au financement et à la protection recherchée.'}},
 'B.02': {2:{0:'Trésorerie de départ : 4 000 € disponibles, 3 200 € de paiements certains.',1:'Financer les dépenses avant les premières recettes.'}},
 'B.04': {0:{1:'Un véhicule durable n’est pas automatiquement une charge intégrale du mois.'},1:{1:'Facturation, encaissement et emprunt n’agissent pas de la même façon.'}},
 'B.05': {0:{0:'Coût fixe : relativement stable dans la plage d’activité étudiée.',1:'Compter l’approche, le trajet passager et le retour sans client.'},1:{0:'Des coûts restent dus même si le véhicule roule moins.',1:'Les coûts variables évoluent avec l’activité.'}},
 'B.06': {0:{1:'TTC = HT × (1 + taux exprimé en décimal)'}},
 'B.07': {0:{0:'Cotisations : chiffre d’affaires encaissé × taux applicable.',1:'Seuil micro services : 83 600 € pour 2026–2028, sous conditions.'},1:{0:'Identifier les recettes à déclarer et la période concernée.',1:'Un taux pédagogique ne remplace pas la vérification du taux réel.'}},
 'B.08': {1:{0:'Solde initial + encaissements − paiements, à leurs dates respectives.'}},
 'B.09': {0:{1:'Point mort : moment où le seuil est atteint, selon l’hypothèse de ventes.'},1:{1:'Nombre minimal de prestations : arrondir au nombre entier supérieur.'}},
 'B.10': {2:{1:'Comparer la même durée, les mêmes services et la propriété finale.'}},
 'B.11': {0:{0:'Identifier les parties, la date, la prestation, les montants et les taxes.',1:'Corriger par un document traçable, sans masquer l’erreur.'},1:{1:'Devis → réservation → prestation → facture → règlement.'},2:{1:'Vérifier les identités, les dates, le service, les montants et la TVA.'}},
 'B.12': {0:{1:'Formalités, rémunération, temps de travail et prévention des risques.'},1:{0:'Compter aussi préparation, nettoyage, approche, retours et administration.'},2:{1:'Prévoir les marges, les pauses et les contraintes du statut.'}},
})
CUSTOM_POINTS = {
 'B.02': {2:[('Le départ','4 000 € disponibles ; 3 200 € à payer.','Une entreprise a quatre mille euros'),('Le calcul','4 000 − 3 200 = 800 € restants.','Quatre mille moins trois mille deux cents'),('La réserve','Les premières dépenses arrivent avant les premières recettes.','La trésorerie de départ finance')]},
 'B.03': {2:[('Les emplois','Véhicule 18 000 € + clients 2 000 € + banque 4 000 €.','Dans un bilan simplifié'),('Actif total','18 000 + 2 000 + 4 000 = 24 000 €.','Dix-huit mille plus deux mille'),('Passif total','8 000 + 14 000 + 2 000 = 24 000 €.','Au passif, huit mille euros')]},
 'B.04': {2:[('Les données','Produits 6 000 € ; charges 4 500 € ; intérêts 100 €.','Sur un mois fictif'),('Le résultat','6 000 − 4 500 − 100 = 1 400 € avant impôt.','Six mille moins quatre mille cinq cents'),('La trésorerie','Rembourser 500 € de capital réduit la banque, sans ajouter 500 € de charge.','Un remboursement de capital de cinq cents')]},
 'B.05': {2:[('La distance','8 km d’approche + 24 km passager + 8 km de retour = 40 km.','Une mission comprend huit kilomètres'),('Le coût variable','40 × 0,24 € = 9,60 €.','Avec une hypothèse de vingt-quatre centimes'),('La rentabilité','Une contribution positive doit encore payer les coûts fixes.','Distinguez également le coût complet et la contribution')]},
 'B.06': {1:[('Le coefficient','10 % → coefficient 1,10.','Au taux de dix pour cent'),('Le sens du calcul','TTC = HT × 1,10 ; HT = TTC ÷ 1,10.','Pour passer au prix toutes taxes comprises, on multiplie'),('La taxe','TVA = TTC − HT ; vérifier HT + TVA = TTC.','Calculez ensuite la taxe par différence')],2:[('Le hors taxes','88 € TTC ÷ 1,10 = 80 € HT.','Quatre-vingt-huit divisé par un virgule dix'),('La différence','88 − 80 = 8 € de TVA.','La différence est de huit euros'),('Le reversement','600 € collectés − 180 € déductibles = 420 € à reverser.','Sur une période fictive')]},
 'B.07': {2:[('Hypothèse pédagogique','Base 4 000 € ; taux d’exercice 21,2 %.','Dans cet exercice, quatre mille euros'),('Les cotisations','4 000 × 0,212 = 848 €.','Quatre mille multiplié par zéro virgule'),('Le disponible','4 000 − 848 − 1 500 = 1 652 €, avant impôt et autres charges.','Après mille cinq cents euros de frais')]},
 'B.08': {2:[('Avant la recette','1 200 − 1 500 = −300 € : un manque temporaire.','Après le paiement, mille deux cents'),('Après la recette','−300 + 900 = 600 €, sans effacer le creux précédent.','L’encaissement suivant le remonte'),('La réserve','Une réserve absorbe les écarts ; un crédit a ses propres conditions.','Une réserve sert à absorber un écart')]},
 'B.09': {2:[('La marge unitaire','60 − 24 = 36 € par course.','Soixante moins vingt-quatre donnent'),('Le seuil simplifié','900 ÷ 36 = 25 courses pour couvrir les charges fixes.','Neuf cents divisé par trente-six'),('La faisabilité','Prix, coûts, capacité, approches, attente et demande doivent être cohérents.','Ce modèle suppose un niveau de prix')]},
 'B.10': {2:[('Les loyers','36 × 700 € = 25 200 €.','Trente-six fois sept cents donnent'),('Le coût du scénario','25 200 + 2 000 + 900 = 28 100 €.','Avec les versements et frais supplémentaires'),('La comparaison','Une offre à 650 €/mois peut coûter plus si des frais restent exclus.','Une offre à six cent cinquante euros')]},
 'B.11': {2:[('La facture','Montant facturé : 85 €.','Un transfert a été facturé'),('Les règlements','50 + 35 = 85 € ; reste dû = 0 €.','Le total réglé est de quatre-vingt-cinq'),('La cohérence','Rapprocher parties, date, service, montants et TVA.','La cohérence porte sur l’identité des parties')]},
 'B.12': {2:[('Le temps mobilisé','6 h + 1 h + 30 min + 30 min = 8 h.','Six heures de transport'),('Le revenu de référence','160 € ÷ 8 h = 20 €/h dans cet exercice.','Avec cent soixante euros de revenu'),('Le planning','Prévoir marges, pauses et contraintes applicables au statut.','Le planning doit aussi prévoir des marges')]},
}

OVERRIDES.update({
 'C.01':{'pitfall':'Un contrôle technique à jour ne remplace pas la vérification quotidienne et ne rend pas une anomalie acceptable.'},
 'C.02':{'pitfall':'Une limitation est un maximum, pas une vitesse à atteindre. Une limite locale plus basse reste prioritaire.'},
 'C.03':{'example':'À quatre-vingt-dix kilomètres par heure, divisez quatre-vingt-dix par trois virgule six pour obtenir la vitesse en mètres par seconde. Le résultat est vingt-cinq mètres par seconde. En deux secondes, vingt-cinq multiplié par deux donnent cinquante mètres parcourus.', 'explanation':'Cette valeur illustre un intervalle de deux secondes. Elle n’annonce pas une distance d’arrêt universelle de cinquante mètres. La distance d’arrêt comprend la réaction puis le freinage, qui dépend de l’adhérence, du véhicule et de la vitesse. Les repères de calcul aident à comprendre ; les conditions réelles imposent toujours une marge adaptée.', 'pitfall':'Ne confondez pas la distance parcourue pendant un intervalle et la distance totale nécessaire pour s’arrêter.'},
 'C.04':{'pitfall':'Une zone masquée peut cacher un usager. Le clignotant annonce une intention, mais ne donne pas priorité.'},
 'C.05':{'pitfall':'Une instruction du GPS ne constitue pas une autorisation d’emprunter une voie interdite.'},
 'C.06':{'pitfall':'Un trajet court ne justifie pas de partager une ceinture ou de renoncer au dispositif de retenue adapté.'},
 'C.07':{'example':'Les paupières deviennent lourdes et le conducteur lutte pour rester attentif. Il doit rechercher un arrêt sûr et traiter cet état de vigilance. Augmenter la musique ou ouvrir la fenêtre ne remplace pas le repos. Il prévient le client si le service doit être réorganisé.', 'pitfall':'La bande d’arrêt d’urgence n’est pas une aire de repos, et le café ne remplace pas le sommeil.'},
 'C.08':{'pitfall':'Une impression de bien-être, deux cafés ou une douche ne garantissent ni l’aptitude ni le respect d’un seuil.'},
 'C.09':{'pitfall':'Un feu rouge n’est pas un stationnement autorisant à manipuler librement le téléphone.'},
 'C.10':{'pitfall':'Conduire souplement ne signifie pas rouler au point mort ou renoncer à réagir à un danger.'},
 'C.11':{'pitfall':'Une transmission intégrale ou une aide électronique ne supprime pas la distance de freinage.'},
 'C.12':{'pitfall':'La récupération des bagages et les formalités passent après la protection des personnes et l’alerte.'},
})

POINTS.update({
 'C.01':{0:{0:'Vérifier pneus, feux, vitrages, niveaux, voyants et anomalies.'},2:{1:'Toujours le même ordre : extérieur, habitacle, poste de conduite, documents et mission.'}},
 'C.02':{1:{1:'Visibilité, adhérence, circulation et usagers peuvent imposer de ralentir davantage.'}},
 'C.03':{1:{1:'Le freinage dépend de l’adhérence, du véhicule et de l’action de freinage.'}},
 'C.04':{1:{0:'Répartir l’attention entre trajectoire, intersections, rétroviseurs et zones masquées.'}},
 'C.05':{0:{1:'Giratoire avec cédez-le-passage : priorité aux véhicules sur l’anneau.'},1:{1:'Un agent ou une signalisation temporaire peut modifier l’organisation habituelle.'}},
 'C.06':{1:{1:'Préparer le dispositif enfant avec les informations de réservation et les règles applicables.'},2:{1:'Ranger les bagages sans gêner la visibilité ni créer de projectiles.'}},
 'C.07':{0:{0:'Bâillements, paupières lourdes, écarts de trajectoire : prendre les signes au sérieux.',1:'Planifier le sommeil et les pauses, notamment la nuit et tôt le matin.'},1:{1:'Fenêtre ouverte ou musique forte ne rétablissent pas durablement la vigilance.'}},
 'C.08':{2:{1:'Le ressenti personnel ne prouve pas l’aptitude ni le respect d’un seuil légal.'}},
 'C.10':{0:{0:'Observer tôt, garder une allure régulière et éviter les freinages tardifs.',1:'Adapter accélération, freinage et virages au véhicule, à l’adhérence et aux passagers.'},1:{0:'Anticiper les ralentissements et préparer les changements de direction.'},2:{1:'Réduire la consommation sans compromettre la sécurité.'}},
 'C.11':{2:{0:'Visibilité sous 50 m : plafond de 50 km/h, avec une allure plus faible si nécessaire.'}},
 'C.12':{0:{1:'Alerter : lieu, sens, repère, dangers et nombre de victimes.'},2:{1:'Après l’urgence : assistance, remplacement éventuel et information du client.'}},
})
CUSTOM_POINTS.update({
 'C.02':{0:[('Temps sec — repères','Sec : 130 / 110 / 80 km/h, selon le réseau et la signalisation.','En règle générale, par temps sec'),('Sous la pluie','Pluie : 110 / 100 / 80 km/h ; toute limite plus basse reste prioritaire.','Sous la pluie, les plafonds usuels'),('Visibilité sous 50 m','Visibilité sous 50 m : 50 km/h maximum, voire moins si nécessaire.','Si la visibilité est inférieure')]},
 'C.03':{2:[('Conversion','90 km/h ÷ 3,6 = 25 m/s.','À quatre-vingt-dix kilomètres par heure'),('Deux secondes','25 × 2 = 50 m parcourus.','En deux secondes, vingt-cinq multiplié'),('À distinguer','Cet intervalle ne constitue pas une distance d’arrêt universelle.','Cette valeur illustre un intervalle')]},
 'C.04':{0:[('Observer','Regarder loin, autour et dans les rétroviseurs ; contrôler l’angle mort.','Balayez le regard loin devant'),('Les piétons','Laisser passer le piéton engagé ou voulant clairement traverser.','Laissez passer le piéton régulièrement engagé'),('Dépasser un cycle','Minimum : 1 m en agglomération ; 1,50 m hors agglomération.','Pour dépasser un cycle')]},
 'C.06':{0:[('Chaque occupant','Une place autorisée et un dispositif de retenue adapté.','Chaque occupant utilise une place autorisée'),('L’enfant','Moins de 10 ans : dispositif homologué adapté, selon le Code.','Pour un enfant de moins de dix ans'),('Préparer la course','Préparer dès la réservation. L’exemption taxi ne vaut pas pour un VTC.','Préparez le dispositif dès la réservation')]},
 'C.08':{0:[('Les seuils','Seuil : 0,5 g/L ; 0,2 g/L pour les catégories concernées.','Le seuil général d’interdiction'),('Les stupéfiants','Conduire après usage est interdit.','La conduite après usage de stupéfiants'),('Les médicaments','Lire la notice et demander conseil ; ne pas arrêter seul un traitement.','Certains médicaments provoquent')]},
 'C.12':{0:[('Protéger','Éviter le suraccident et rejoindre un refuge sûr si accessible.','En cas d’incident, évitez le suraccident.'),('Alerter','112 ou moyens d’urgence : lieu, sens, repère, dangers et victimes.','Alertez par le 112'),('Le blessé','Ne pas déplacer, sauf danger immédiat évitable sans vous exposer.','Ne déplacez pas un blessé')]},
})

OVERRIDES.update({
 'D.01':{'pitfall':'Une information vraie en général peut rester hors sujet si elle ne répond pas au document et à la consigne.'},
 'D.02':{'example':'La réservation est effectuée le douze juin à dix-huit heures, pour une prise en charge le treize juin à sept heures trente. À la question portant sur la date de la course, il faut répondre le treize juin. Le douze juin est la date de commande. À la question portant sur l’heure de prise en charge, il faut répondre sept heures trente, et non dix-huit heures. Chaque réponse relie donc un chiffre à son rôle dans le message.', 'pitfall':'Une heure de réservation, une heure de prise en charge et une heure d’arrivée sont trois informations différentes.'},
 'D.03':{'example':'Le texte indique : « La circulation est dense. Le chauffeur estime qu’un retard de dix minutes est possible et prévient le passager. » La circulation dense est le fait décrit. Le retard est une possibilité annoncée par le chauffeur, pas un retard déjà certain. Écrire « le chauffeur aura dix minutes de retard » supprimerait la nuance. De même, « le client juge l’accueil excellent » rapporte l’opinion de ce client ; cela ne signifie pas que tous les passagers ont donné cet avis.', 'pitfall':'Ne transformez pas une hypothèse en certitude, ni l’avis d’un client en avis de tous les clients.'},
 'D.04':{'depth':'Pour trouver ce qu’un pronom remplace, partez du verbe et de l’action. Dans « La cliente appelle le chauffeur. Il lui confirme l’heure », le pronom « il » désigne le chauffeur, qui confirme. Le pronom « lui » désigne la cliente, qui reçoit l’information. Dans « Elle le remercie », les rôles changent : « elle » est la cliente et « le » est le chauffeur. Le genre et le nombre donnent des indices ; le sens de l’action permet de les vérifier.', 'example':'Lisons : « Les passagers attendent leurs bagages. Le chauffeur les aide à les charger. » Dans « les aide », le premier « les » renvoie aux passagers : le chauffeur aide des personnes. Dans « les charger », le second « les » renvoie aux bagages : ce sont les bagages qui sont chargés. Un même pronom peut donc désigner deux éléments différents dans la même phrase. Remplacer mentalement chaque pronom par son nom permet de contrôler la compréhension.', 'pitfall':'Le nom le plus proche n’est pas toujours le bon référent. Vérifiez le verbe, le contexte et le sens.'},
 'D.05':{'depth':'Une cause répond à la question « pourquoi ? ». Dans « Le chauffeur change de trajet parce que la rue est fermée », la fermeture explique le changement. Une conséquence décrit ce qui résulte d’une situation. Un but indique ce que l’on cherche à obtenir. Dans « Il part tôt afin d’éviter le retard », partir tôt vise un objectif ; la phrase ne prouve pas qu’il arrivera à l’heure. Relisez donc les deux idées ensemble et demandez-vous si la seconde explique, résulte, s’oppose ou exprime un objectif.', 'pitfall':'Changer un connecteur peut renverser le raisonnement. Un but recherché n’est pas la preuve d’un résultat obtenu.'},
 'D.06':{'depth':'Les verbes et les adverbes modifient l’engagement. « Peut » indique une possibilité ; « doit » une obligation dans le contexte ; « devrait » peut exprimer une prévision ou un conseil. « Environ », « probablement » et « sous réserve » signalent une marge ou une condition. Ne les remplacez pas par une certitude. Une phrase introduite par « si », « sauf si » ou « à condition que » peut limiter la règle annoncée. Identifiez le cas général, puis l’exception, sans étendre cette exception à toutes les situations.', 'pitfall':'Ne remplacez pas « certains » par « tous », ni « au moins » par « au plus ».'},
 'D.07':{'depth':'Une réservation, un devis, une facture, un reçu, un acompte et un remboursement décrivent des étapes différentes. Un mot voisin n’est pas toujours interchangeable. Recherchez ce que le document ou l’action accomplit réellement. Pour mémoriser un terme, notez une définition simple et une phrase d’usage. Ajoutez un mot à ne pas confondre. L’objectif n’est pas de compliquer les messages, mais de choisir le terme précis. Si un mot technique risque de ne pas être compris par le client, expliquez-le avec un exemple concret.', 'pitfall':'Un synonyme possible dans une phrase peut devenir faux dans une autre. Le contexte décide du sens utile.'},
 'D.08':{'depth':'Hier, aujourd’hui, demain, avant, après et depuis aident à organiser la chronologie. Attention aux messages transférés plusieurs jours plus tard : « demain » renvoie au lendemain du message initial, pas toujours au lendemain de sa lecture. Pour une réservation, une date complète et une heure précise sont plus fiables qu’une indication relative. Reliez ensuite chaque verbe au moment de l’action : une confirmation déjà faite, une vérification en cours et une réponse promise pour plus tard ne décrivent pas le même état du dossier.', 'example':'« Je serai devant l’hôtel à sept heures trente » annonce une présence future : « serai » s’écrit ici sans s final. « Je serais disponible si le vol arrivait plus tôt » exprime une disponibilité conditionnelle : « serais » prend un s final. L’écriture et le contexte permettent de distinguer la présence future annoncée et la condition posée. La présence de « si » invite à vérifier ce qui doit se produire pour que la disponibilité existe.', 'pitfall':'Une action annoncée au futur n’est pas encore une action accomplie, et une hypothèse n’est pas une confirmation.'},
 'D.09':{'intro':[
  'Le verbe s’accorde avec son sujet : « Les clients arrivent. » L’adjectif s’accorde avec le nom : « Les valises sont lourdes. » Au passé composé avec être, le participe s’accorde généralement avec le sujet : « Les passagères sont arrivées. » Avec avoir, l’accord dépend notamment de la place du complément d’objet direct.',
  'Pour les homophones, utilisez un test simple. Le verbe « a », sans accent, se remplace par « avait » ; la préposition « à », avec accent grave, ne se remplace pas ainsi. « Sont », avec un t final, se remplace par « étaient » ; « son », sans t final, exprime la possession. Pour une terminaison en é accent aigu ou en e r, remplacez le verbe par « vendu » ou « vendre ». Une relecture ciblée est plus efficace qu’une lecture rapide sans objectif.'
 ], 'depth':'Posez la question « qui fait l’action ? ». Dans « Les clients du chauffeur attendent », le sujet est « les clients », même si « chauffeur » est plus proche du verbe. Le verbe s’accorde donc au pluriel. Dans un groupe nominal, le déterminant, le nom et l’adjectif doivent rester cohérents : « une réservation confirmée », puis « des réservations confirmées ». Commencez par le nom principal et vérifiez les mots qui s’y rapportent.', 'example':'La phrase erronée « Les clients on réservé », avec « on » sans t final, devient « Les clients ont réservé », avec un t final à « ont ». Le test « avaient réservé » fonctionne : il s’agit du verbe avoir. Autre correction : « Merci de confirmé », avec é accent aigu, devient « Merci de confirmer », terminé par e r. On peut dire « Merci de vendre » : il faut donc l’infinitif.', 'pitfall':'La ressemblance à l’oral ne suffit pas. Utilisez le sujet et les tests de remplacement pour choisir l’écriture.'},
 'D.10':{'example':'La question est : « Pourquoi le chauffeur appelle-t-il le client ? » Le texte indique que deux hôtels portent le même nom. Une réponse précise est : « Il appelle le client pour confirmer l’adresse, car deux hôtels portent le même nom. » Cette phrase relie l’action à sa cause. Répondre seulement « pour le trajet » resterait trop vague. Ajouter que le prix a changé introduirait une information absente du texte.', 'pitfall':'Une réponse courte doit rester complète : conserver la cause, l’unité ou la condition demandée.'},
 'D.11':{'example':'Voici la consigne : « Le départ est maintenu à huit heures. La réception demande seulement de remplacer la sortie principale par la sortie côté jardin. Merci de confirmer ce point au passager. » Le message au client peut donc préciser : « Votre départ reste prévu à huit heures. Le rendez-vous aura lieu à la sortie côté jardin. Merci de confirmer que vous avez bien reçu ce changement de lieu. » Le message garde l’heure initiale, précise le repère modifié et indique l’action attendue.', 'pitfall':'La politesse ne remplace pas une heure, un lieu identifiable ou une demande précise.'},
 'D.12':{'example':'Il reste quatre minutes. Les QCM et deux réponses courtes sont traités, mais la dernière question demande deux causes et le brouillon n’en donne qu’une. La priorité est de revenir au passage utile pour retrouver la seconde cause, puis de vérifier que les deux raisons sont distinctes. Une longue introduction ne comblerait pas l’élément manquant. Une question difficile ne doit pas absorber tout le temps au point de laisser une autre réponse accessible vide.', 'pitfall':'Relire seulement l’orthographe ne suffit pas : vérifiez aussi que chaque consigne et chaque nombre d’éléments sont respectés.'},
})

POINTS.update({
 'D.01':{1:{0:'Lire avec un but : heure, consigne, cause ou condition à retrouver.'},2:{0:'Rendez-vous déplacé à la porte B ; horaire inchangé.'}},
 'D.06':{0:{0:'Tous, certains, aucun, seulement, sauf : conserver la portée exacte.'},2:{0:'Deux bagages au maximum : une limite, sans obligation d’en avoir deux.',1:'« Sauf » introduit une exception : relire toute la phrase.'}},
 'D.07':{0:{1:'Réservation, devis, facture et reçu remplissent des fonctions différentes.'},1:{0:'Identifier l’étape décrite par le mot, sans confondre les termes proches.'}},
 'D.08':{0:{1:'Le conditionnel exprime notamment une hypothèse ou une demande polie.'},1:{1:'Une date complète et une heure précise évitent les ambiguïtés de « demain ».'}},
 'D.09':{0:{0:'Le verbe s’accorde avec son sujet ; l’adjectif avec le nom.'},2:{1:'Relire le sens puis la forme, en surveillant heures, nombres et négations.'}},
 'D.10':{1:{1:'Pourquoi → cause ; combien → quantité ; quand → moment.'}},
 'D.11':{1:{1:'La politesse accompagne une information concrète et exploitable.'}},
 'D.12':{0:{0:'Texte de 15 à 20 lignes ; 7 QCM et 3 réponses courtes.',1:'Lire → répondre → rédiger les réponses courtes → relire, selon votre rythme.'},1:{1:'Éliminer les réponses qui ajoutent, inversent ou exagèrent une information.'},2:{1:'Relire dates, négations, conditions et personnes.'}},
})
CUSTOM_POINTS.update({
 'D.02':{2:[('La commande','Réservation : le 12 juin à 18 h.','La réservation est effectuée le douze juin'),('La course','Prise en charge : le 13 juin à 7 h 30.','À la question portant sur la date de la course'),('L’unité','Vérifier ce que compte le nombre : passagers, bagages, véhicules ou euros.','Pour un nombre, vérifiez ce qu’il compte')]},
 'D.03':{2:[('Le fait décrit','La circulation est dense.','La circulation dense est le fait décrit.'),('L’hypothèse','Un retard de 10 minutes est possible, pas déjà certain.','Le retard est une possibilité annoncée'),('L’opinion attribuée','L’avis d’un client ne représente pas celui de tous les passagers.','De même, « le client juge l’accueil excellent »')]},
 'D.04':{1:[('Qui confirme ?','« il » = le chauffeur, qui confirme.','le pronom « il » désigne le chauffeur'),('À qui ?','« lui » = la cliente, qui reçoit l’information.','Le pronom « lui » désigne la cliente'),('Qui remercie qui ?','« Elle le remercie » : la cliente remercie le chauffeur.','Dans « Elle le remercie »')],2:[('La phrase','« Le chauffeur les aide à les charger. »','Le chauffeur les aide à les charger.'),('Le premier « les »','« les aide » → les passagers.','Dans « les aide »'),('Le second « les »','« les charger » → les bagages.','Dans « les charger »')]},
 'D.05':{1:[('La cause','« Parce que la rue est fermée » explique le changement.','Dans « Le chauffeur change de trajet'),('Le but','« Afin d’éviter le retard » décrit l’objectif recherché.','Dans « Il part tôt afin d’éviter le retard »'),('La vérification','Expliquer, résulter, s’opposer ou viser un objectif ?','Relisez donc les deux idées ensemble')],2:[('L’opposition','« Malgré la pluie, le véhicule arrive à l’heure. »','« Malgré la pluie, le véhicule arrive à l’heure.'),('La condition','« Si le client confirme » ne dit pas qu’il a déjà confirmé.','« Si le client confirme »'),('La chronologie','« Après confirmation » impose une étape préalable.','« Après confirmation »')]},
 'D.06':{0:[('Les bornes','Au moins 2 : 2 ou plus. Au plus 2 : 2 ou moins.','« Au moins deux » signifie'),('La condition','Attendre si le client confirme ne signifie pas attendre toujours.','« Le chauffeur attend si le client confirme son retard »'),('La restriction','« Ne… que » signifie « seulement ».','« Ne… que » marque une restriction')],2:[('La limite','Deux bagages au maximum ne signifie ni deux obligatoires ni trois gratuits.','« Le tarif inclut deux bagages au maximum.'),('L’exception','« Aucun supplément sauf attente prévue » : conserver l’exception.','Une phrase négative mérite une lecture complète')]},
 'D.07':{2:[('Occasionnel','« Cette prestation ponctuelle aura lieu mardi » : occasionnelle.','« Cette prestation ponctuelle aura lieu mardi »'),('À l’heure','« Ce chauffeur est ponctuel » : il respecte l’horaire.','« Ce chauffeur est ponctuel »'),('Le contexte','« Correspondance » : liaison de transport ou échange écrit, selon la phrase.','Une « correspondance » peut être')]},
 'D.08':{2:[('Le futur','« Je serai devant l’hôtel à 7 h 30 » : sans s final, présence future annoncée.','« Je serai devant l’hôtel à sept heures trente »'),('Le conditionnel','« Je serais disponible si… » : avec s final, disponibilité sous condition.','« Je serais disponible si le vol arrivait plus tôt »'),('La vérification','Une phrase au futur ne prouve pas que l’action est déjà accomplie.','Une phrase au futur ne prouve')]},
 'D.09':{0:[('Les accords','Le verbe avec le sujet ; l’adjectif avec le nom.','Le verbe s’accorde avec son sujet'),('A ou à ?','« a » → « avait » ; « à » ne permet pas ce remplacement.','Le verbe « a », sans accent'),('Sont ou son ?','« sont » → « étaient » ; « son » exprime la possession.','« Sont », avec un t final')],1:[('Le sujet','Dans « Les clients du chauffeur attendent », le sujet est « les clients ».','Dans « Les clients du chauffeur attendent »'),('Le groupe nominal','Une réservation confirmée → des réservations confirmées.','Dans un groupe nominal')],2:[('Correction du verbe','« Les clients ont réservé » : ont avec un t final.','devient « Les clients ont réservé »'),('Le test','« Avaient réservé » fonctionne : c’est le verbe avoir.','Le test « avaient réservé » fonctionne'),('Correction de l’infinitif','« Merci de confirmer » : e r, comme « Merci de vendre ».','devient « Merci de confirmer »')]},
 'D.10':{2:[('La question','Pourquoi le chauffeur appelle-t-il le client ?','La question est : « Pourquoi le chauffeur'),('La réponse justifiée','Pour confirmer l’adresse, car deux hôtels portent le même nom.','Une réponse précise est'),('La limite','Choisir une formulation entraîne la précision, sans reproduire le geste d’écriture.','La plateforme vous fait choisir entre plusieurs formulations')]},
 'D.11':{2:[('Ce qui change','Heure maintenue à 8 h ; rendez-vous déplacé côté jardin.','Voici la consigne : « Le départ est maintenu à huit heures.'),('Le message','Préciser l’heure, le nouveau lieu et demander confirmation de réception.','Le message au client peut donc préciser'),('La fiabilité','Séparer ce qui est confirmé de ce qui reste à vérifier.','En cas de retard ou de modification')]},
 'D.12':{2:[('Le temps restant','Il reste 4 minutes pour terminer et vérifier les réponses.','Il reste quatre minutes.'),('La priorité','Retrouver la seconde cause et vérifier que les deux raisons sont distinctes.','La priorité est de revenir au passage utile'),('La relecture','Contrôler dates, négations, conditions et personnes.','Conservez du temps pour une relecture')]},
})

def sentences(text):
    return re.split(r'(?<=[.!?])\s+(?=[«A-ZÀÂÇÉÈÊËÎÏÔÙÛÜŸ0-9])', text)


def excerpt(sentence, limit=100):
    """Keep a complete sentence/clause when possible, otherwise a readable extract."""
    sentence = sentence.strip()
    if len(sentence) <= limit:
        return sentence
    for delimiter in (' ; ', ' : ', ', ', ' ;', ': ', '; '):
        chunks = sentence.split(delimiter)
        if len(chunks) > 1 and 25 <= len(chunks[0]) <= limit:
            return chunks[0].rstrip('.') + '…'
    head = sentence[:limit - 1].rsplit(' ', 1)[0]
    return head.rstrip(' ,;:') + '…'


def anchor(text, occurrence, count=8):
    words = occurrence.split()
    for n in range(min(count, len(words)), len(words)+1):
        result = ' '.join(words[:n])
        if text.count(result) == 1:
            return result
    assert text.count(occurrence) == 1, (text, occurrence)
    return occurrence


def point(text, phrase, label, display=None):
    return {'label': label, 'text': display or excerpt(phrase), 'anchor_text': anchor(text, phrase)}


def plain(text):
    # Speaking whole numbers rather than symbolic arithmetic is curated in B.
    return re.sub(r'\s+', ' ', text).strip()


def build(v):
    ref = v['ref']
    d = v['deepening']
    p = [p['text'] for p in v['paragraphs'] if p['kind']=='paragraph']
    overrides = OVERRIDES.get(ref, {})
    first, second = overrides.get('intro', p[:2])
    depth = overrides.get('depth', d['paragraphs'][0])
    explanation = overrides.get('explanation', d['paragraphs'][1])
    case = v.get('manual_case') or {}
    example = overrides.get('example', case.get('example') or d['example'])
    method = overrides.get('method', d['method'])
    pitfall = overrides.get('pitfall', d['pitfall'])
    texts = [
        plain(first + ' ' + second),
        plain('Pour bien comprendre, allons un peu plus loin. ' + depth),
        plain('Prenons un exemple concret. ' + example + ' ' + explanation),
        plain('Pour retenir la méthode, procédez en trois étapes. ' + ' '.join(method) + ' Le piège à éviter : ' + pitfall),
    ]
    titles = ['Les repères essentiels', d['title'], overrides.get('example_title', 'Un exemple expliqué'), 'La méthode à retenir']
    labels = ['COMPRENDRE', 'EXPLIQUER', 'METTRE EN PRATIQUE', 'RETENIR']
    sourcephrases = [
        [(sentences(first)[0], 'Le repère'), (sentences(second)[0], 'Dans la pratique')],
        [(sentences(depth)[0], 'Le principe'), (sentences(depth)[max(1,len(sentences(depth))//2)], 'Le point clé')],
        [(sentences(example)[0], 'La situation'), (sentences(explanation)[0], 'Le raisonnement')],
        [(item, item.split(' : ')[0]) for item in method],
    ]
    scenes = []
    for i, text in enumerate(texts):
        pts=[]
        for n,(phrase,label) in enumerate(sourcephrases[i]):
            display=POINTS.get(ref,{}).get(i,{}).get(n)
            pts.append(point(text,phrase,label,display))
        if i in CUSTOM_POINTS.get(ref, {}):
            pts=[point(text, phrase, label, display) for label,display,phrase in CUSTOM_POINTS[ref][i]]
        if i==3:
            for pnt in pts:
                pnt['text']=pnt['text'].split(' : ',1)[-1]
        scene={'title':titles[i][:65], 'label':labels[i], 'kind':'concept' if i<2 else 'method', 'segments':[{'lang':'fr','text':text}], 'points':pts}
        if i<3:
            prompt = [
                'À vous : '+v['objective'],
                'Avant l’exemple, retenez cette question : '+method[0].split(' : ',1)[-1],
                'Dans cette situation, expliquez le piège à éviter avec vos mots.'
            ][i]
            scene['pause']={'seconds':4,'message':prompt}
        scenes.append(scene)
    result={'ref':ref,'title':v['title'],'objective':v['objective'],'image':v['image'],'source_sha256':hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'scenes':scenes}
    validate(result)
    return result


def validate(lesson):
    for scene in lesson['scenes']:
        text=' '.join(s['text'] for s in scene['segments'])
        indices=[]
        assert len(scene['points']) in (2,3)
        for point_ in scene['points']:
            a=point_['anchor_text']
            assert text.count(a)==1, (lesson['ref'],a)
            indices.append(text.index(a))
            assert len(point_['label'])<=32
            assert len(point_['text'])<=112, (lesson['ref'],point_['text'])
        assert indices==sorted(indices), (lesson['ref'],indices)
    assert 'pause' not in lesson['scenes'][-1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('modules',nargs='*',default=list('ABCD'));args=parser.parse_args()
    for mod in args.modules:
        course=load_bundled_course('academy-vtc-'+mod.lower(),VERSION)
        lessons=[build(a['vtc']) for s in course['sections'] for a in s['activities'] if a.get('vtc',{}).get('kind')=='lesson']
        assert len(lessons)==12
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/f'{mod}.json').write_text(json.dumps({'revision':10,'module':mod,'lessons':lessons},ensure_ascii=False,indent=2)+'\n')
        counts=[len(re.findall(r'\S+', ' '.join(seg['text'] for sc in l['scenes'] for seg in sc['segments']))) for l in lessons]
        print(mod,len(lessons),'lessons;',min(counts),'-',max(counts),'words;',sum(counts),'total')

if __name__=='__main__':main()
