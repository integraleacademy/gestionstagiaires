"""Reviewed pedagogical changes for VTC v6. Pure transformation; no file writes.

enrich_course(course) returns a deep copy. Existing activity/exercise/option IDs
and answer keys remain stable, except the explicitly replaced B.01 dossier.
The immutable annales and their historical answers are never rewritten.
"""
from __future__ import annotations
import copy
import hashlib
import re
from decimal import Decimal

REVIEWED_ON = '2026-10-10'
REVISION = '20261010-vtc-v6-pedagogie'

SOURCES = {
 'discrimination': ('Code pénal · article 225-2', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000033975382/2026-06-13'),
 'criteria': ('Code pénal · article 225-1', 'https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000045391831/2025-02-19'),
 'defender': ('Défenseur des droits · Lutter contre les discriminations', 'https://www.defenseurdesdroits.fr/lutter-contre-les-discriminations-et-promouvoir-legalite-185'),
 'consent': ('Code pénal · article 222-22', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000052535583'),
 'rape': ('Code pénal · article 222-23', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000052535571/2026-03-26'),
 'harassment': ('Code pénal · article 222-33', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000054724663'),
 'outrage': ('Code pénal · article 222-33-1-1', 'https://www.legifrance.gouv.fr/codes/id/LEGISCTA000006089684'),
 'structure': ('Service Public Entreprendre · Choisir la forme juridique', 'https://entreprendre.service-public.gouv.fr/vosdroits/F23844'),
 'eurl': ('Service Public Entreprendre · EURL', 'https://entreprendre.service-public.gouv.fr/vosdroits/F37777'),
}

G_DEEPENING = {
 'G.01': 'Le registre identifie l’exploitant, tandis que la carte identifie le conducteur. Pour une même mission, rapprochez la raison sociale figurant sur la réservation, le numéro REVTC et l’entreprise qui exécute réellement le transport. Le numéro d’un partenaire ne prouve pas votre propre inscription ; un dossier déposé doit être distingué d’une inscription effectivement obtenue.',
 'G.02': 'Raisonnez véhicule par véhicule. La propriété et la location suffisamment longue se prouvent par leurs pièces ; une location courte demande d’examiner la garantie applicable. Un avenant peut changer la durée à retenir. Reconstituez donc le contrat complet au lieu de comparer seulement le loyer mensuel ou la première page.',
 'G.03': 'Construisez deux colonnes : conformité et adéquation à la mission. Dans la première, relevez catégorie, âge, places, dimensions, puissance et éventuelle exception avec leur preuve. Dans la seconde, estimez bagages, autonomie et accessibilité. Un coffre trop petit peut rendre la course inadaptée même si les critères réglementaires du modèle sont satisfaits.',
 'G.04': 'La signalétique du véhicule, la carte du conducteur et le logo commercial ont trois fonctions différentes. Lors d’un remplacement, vérifiez la correspondance des éléments avec le véhicule réellement utilisé et suivez la procédure prévue. Une photographie lisible d’un ancien macaron ne règle pas la conformité d’un nouveau véhicule.',
 'G.05': 'Lisez séparément l’heure de réservation et l’heure de prise en charge : la première doit correspondre à une commande réelle antérieure. Contrôlez ensuite exploitant, identifiants, client et lieu. Entraînez-vous à retrouver le justificatif sans réseau. Une preuve complète mais inaccessible au contrôle ne remplit pas la même fonction qu’une preuve effectivement présentable.',
 'G.06': 'Distinguez le canal de commande et l’antériorité. Une commande téléphonique peut être réelle et préalable ; une application ouverte après une prise en charge spontanée ne rend pas cette dernière conforme. Le nom, l’horaire et le lieu doivent décrire la mission effectivement réalisée, et non servir à réutiliser un bon préparé pour quelqu’un d’autre.',
 'G.07': 'La réservation ne donne pas un droit général d’accès aux emplacements de la gare ou de l’aéroport. Préparez un point autorisé, un moyen de joindre le client et une solution d’attente si son arrivée est retardée. Si le terminal change, faites confirmer le rendez-vous : changer seulement le GPS peut laisser le passager à l’ancienne sortie.',
 'G.08': 'À la dépose, identifiez la situation suivante : réservation confirmée, mise à disposition convenue ou absence de mission. Chacune conduit à vérifier un lieu d’attente ou un repositionnement autorisé. Une promesse vague de rappel ne constitue pas la preuve d’une prochaine réservation ; le chauffeur ne doit pas transformer cette incertitude en attente commerciale sur la chaussée.',
 'G.09': 'Pour une modification demandée en route, comparez le service accepté et le nouveau besoin : détour, attente, péage ou arrêt supplémentaire. Expliquez les conséquences avant d’exécuter le changement et conservez l’accord utile. Une ligne ajoutée à la facture à l’arrivée ne démontre pas, à elle seule, que le client avait accepté le supplément.',
 'G.10': 'Un remplacement oblige à contrôler les deux ressources : le conducteur et le véhicule. Vérifiez le titre personnel du collègue, les garanties et documents du véhicule, puis informez le client de la plaque et du point de rencontre par un canal sûr. Ne communiquez au remplaçant que les informations nécessaires à la mission, y compris les besoins pratiques d’assistance.',
 'G.11': 'Associez chaque pièce à une immatriculation et à une échéance propre. Le contrôle technique, l’assurance et l’entretien ne se prolongent pas mutuellement. Suivez le kilométrage total, approches et retours compris ; le kilométrage facturé sous-estime l’usage. Un défaut de freinage constaté aujourd’hui doit être traité même si le prochain contrôle n’est pas encore dû.',
 'G.12': 'Consignez quatre éléments lors d’une veille : source officielle, version ou date d’effet, situation concernée et action à entreprendre. Comparez ensuite la règle avec vos documents ou pratiques. Un texte publié peut entrer en vigueur plus tard ; un critère commercial de plateforme peut être plus restrictif sans devenir une règle légale applicable à tous les VTC.',
}

# Correct-answer text -> two contextual distractors with their own rationale.
DECISIONS = {}
DECISIONS.update({
 'Traiter l’anomalie avant de partir': [('Partir si le témoin de pression reste éteint.', 'Un témoin éteint ne suffit pas à écarter une anomalie visible du pneu.'), ('Regonfler puis reporter tout contrôle à la fin de la journée.', 'Le regonflage ne permet pas, à lui seul, d’écarter une fuite ou une détérioration avant le service.')],
 'Nettoyer pour rétablir une visibilité correcte': [('Augmenter la ventilation sans contrôler les reflets restants.', 'La ventilation peut traiter la buée, mais ne retire pas les salissures à l’origine des reflets.'), ('Nettoyer uniquement l’extérieur, déjà accessible à la station.', 'Le défaut décrit est à l’intérieur ; agir seulement dehors ne rétablit pas le champ de vision.')],
 'Le déplacer vers un emplacement sûr': [('Caler le bagage contre la porte pour limiter son mouvement.', 'Le calage ne résout pas l’obstruction d’une sortie.'), ('Demander au passager de le déplacer si une évacuation devient nécessaire.', 'Une sortie doit être dégagée avant de rouler ; une évacuation peut imposer une réaction immédiate.')],
 'Identifier le défaut et décider selon sa gravité': [('Prévoir une vérification après la première course si le moteur fonctionne normalement.', 'Le fonctionnement apparent du moteur ne permet pas de connaître la gravité du témoin.'), ('Redémarrer et considérer l’absence de bruit comme un diagnostic suffisant.', 'Un redémarrage et l’absence de bruit ne caractérisent pas le défaut signalé.')],
 'Réduire l’allure et augmenter les marges': [('Garder l’allure tant que le véhicule précédent reste visible.', 'Voir le véhicule précédent ne garantit pas une distance d’arrêt adaptée à la visibilité.'), ('Augmenter seulement l’écart avec le véhicule précédent, sans réexaminer l’allure.', 'L’intervalle ne remplace pas l’adaptation de la vitesse à l’espace effectivement visible.')],
 'Expliquer la limite et chercher une solution sûre': [('Recalculer l’arrivée en supposant que toutes les portions seront parcourues à leur vitesse maximale.', 'Une limite est un plafond ; ce calcul ne tient pas compte des conditions ni des marges nécessaires.'), ('Promettre l’heure demandée, puis informer le client seulement si le retard persiste.', 'Une promesse sans base retarde la recherche d’une autre organisation sans réduire le risque.')],
 'Anticiper et se préparer à ralentir ou s’arrêter': [('Maintenir l’allure jusqu’à ce qu’un piéton pose un pied sur la chaussée.', 'Attendre l’entrée effective réduit le temps disponible pour gérer une intention de traversée.'), ('Vérifier uniquement le piéton situé de votre côté de la chaussée.', 'Un piéton peut arriver de l’autre côté ou être masqué ; l’observation doit couvrir la traversée.')],
 'Adapter l’allure à l’espace visible': [('Conserver l’allure habituelle du virage tant que la chaussée paraît sèche.', 'L’adhérence n’est qu’un facteur : le masquage limite aussi la distance disponible pour s’arrêter.'), ('Utiliser la vitesse conseillée par le GPS comme référence suffisante.', 'Une estimation numérique ne prouve pas que l’espace au-delà du virage est libre.')],
 'En deux secondes, le véhicule parcourt 50 mètres': [('En deux secondes, le véhicule parcourt 25 mètres.', '25 mètres correspondent ici à une seule seconde ; la durée demandée est deux fois plus longue.'), ('En deux secondes, le véhicule parcourt 12,5 mètres.', 'Diviser par deux inverse l’opération : à vitesse constante, la distance augmente avec la durée.')],
 'Augmenter les marges et adapter la conduite': [('Conserver l’intervalle habituel si les pneus ont été changés récemment.', 'Des pneus récents ne suppriment pas la baisse d’adhérence liée à la chaussée.'), ('Réduire l’allure mais garder le même intervalle minimal.', 'L’allure et l’intervalle participent ensemble à la marge ; la première adaptation ne dispense pas de la seconde.')],
 'Le véhicule avance davantage avant sa réaction': [('Le freinage commence au même endroit si la vitesse ne change pas.', 'À vitesse identique, la seconde d’inattention ajoute de la distance avant le début du freinage.'), ('Le délai supplémentaire modifie seulement la distance de freinage après action sur la pédale.', 'La distraction ajoute d’abord une distance avant la réaction, distincte du freinage proprement dit.')],
 'Garder une marge et tenir compte des conditions réelles': [('Utiliser la valeur affichée comme distance d’arrêt totale.', 'Une distance de freinage n’inclut pas nécessairement la distance parcourue avant la réaction.'), ('Utiliser la même valeur sur sol sec et mouillé si la vitesse reste identique.', 'Le calcul théorique dépend d’hypothèses d’adhérence qui peuvent différer des conditions réelles.')],
 'Effectuer les contrôles adaptés avant la manœuvre': [('Se fier au seul rétroviseur principal si aucun cycliste n’y apparaît.', 'Un angle mort peut subsister en dehors du champ de ce rétroviseur.'), ('Engager lentement la manœuvre après avoir actionné le clignotant.', 'Le signal annonce une intention ; il ne prouve pas que la trajectoire est libre.')],
 'Anticiper la présence possible d’un piéton': [('Maintenir l’allure tant que personne n’est visible devant le fourgon.', 'Le fourgon masque précisément la zone où un piéton pourrait apparaître.'), ('Surveiller seulement le côté dégagé de la traversée.', 'Le danger peut provenir du côté masqué ; limiter l’observation à la zone visible ne traite pas ce risque.')],
 'Conserver le regard et l’attention nécessaires à la conduite': [('Alterner fréquemment le regard entre le client et la route pour montrer votre écoute.', 'Ces regards répétés réduisent la disponibilité pour la circulation ; la relation client doit s’adapter à la conduite.'), ('Régler le rétroviseur intérieur vers le visage du client pendant l’échange.', 'Un réglage destiné à la conversation peut réduire la surveillance arrière et ajoute une manipulation.')],
 'Vérifier vous-même les autres risques': [('S’appuyer sur le geste pour conclure que toutes les voies sont libres.', 'Le conducteur qui fait signe ne maîtrise pas nécessairement les autres voies ni les usagers masqués.'), ('Vérifier uniquement que la voiture qui fait signe est arrêtée.', 'Ce seul contrôle ne couvre ni les piétons ni les véhicules qui peuvent la dépasser.')],
 'Suivre la signalisation et rechercher un autre itinéraire': [('Vérifier si le GPS affiche encore la rue comme ouverte avant de décider.', 'La signalisation rencontrée s’impose ; une carte non actualisée ne la neutralise pas.'), ('Emprunter la rue si la destination se trouve à quelques mètres de l’entrée.', 'La proximité de la destination ne constitue pas une exception à un sens interdit.')],
 'Respecter ses indications dans le cadre applicable': [('Attendre uniquement le prochain feu vert avant de suivre le geste.', 'Lorsque l’agent règle la circulation, ses indications doivent être prises en compte au lieu de suivre seulement le feu.'), ('Suivre le véhicule précédent pour éviter d’interpréter le geste.', 'Le véhicule précédent peut avoir reçu une indication différente ; il faut lire celle qui vous concerne.')],
 'Adapter le parcours': [('Conserver le trajet enregistré jusqu’à ce que l’application annonce aussi la restriction.', 'La restriction visible ne dépend pas de son intégration dans l’application.'), ('Suivre les riverains qui franchissent la restriction sans vérifier les exceptions.', 'Une autorisation réservée à certains usagers ne s’étend pas automatiquement au VTC.')],
 'Continuer jusqu’à une possibilité autorisée de réorientation': [('S’arrêter juste après la sortie pour recalculer avant de poursuivre.', 'L’arrêt improvisé sur une voie peut créer un danger ; la correction du trajet doit se préparer dans un lieu adapté.'), ('Revenir par le passage de service visible à proximité.', 'Un passage de service n’est pas nécessairement ouvert à la circulation générale ; sa présence ne prouve pas une autorisation.')],
 'Prévoir une solution conforme à la capacité': [('Accepter si l’un des cinq passagers est un enfant.', 'Un enfant occupe aussi une place autorisée ; les cinq places comprennent déjà le conducteur.'), ('Se fier au nombre de sièges arrière sans compter le conducteur.', 'La capacité indiquée comprend le conducteur ; ici il reste quatre places passagers.')],
 'La ranger de manière sûre avant le départ': [('La poser au sol devant un passager sans vérifier l’accès à la sortie.', 'Déplacer la valise ne suffit pas si elle gêne les jambes, une commande ou une issue.'), ('La laisser sur le siège avec la poignée tenue par le client.', 'La prise à la main n’offre pas une retenue sûre lors d’un freinage important.')],
 'Résoudre le besoin avant le départ': [('Utiliser la ceinture adulte sans vérifier son adaptation à l’enfant.', 'La ceinture seule ne remplace pas automatiquement le dispositif adapté requis.'), ('Appliquer au VTC l’exception connue pour un taxi.', 'Le régime des taxis ne doit pas être transposé au VTC ; le besoin doit être résolu avant le départ.')],
 'S’arrêter dans un lieu sûr si nécessaire': [('Autoriser le détachement pendant une portion rectiligne à faible allure.', 'Une faible allure et une ligne droite n’écartent pas un freinage ou un choc.'), ('Demander de rester assis mais de passer la ceinture derrière le dos.', 'Une ceinture mal positionnée ne conserve pas sa fonction de retenue.')],
 'S’arrêter en sécurité et traiter l’état de vigilance': [('Ouvrir la fenêtre et poursuivre jusqu’au prochain rendez-vous prévu.', 'L’air frais ne traite pas durablement la somnolence ; le prochain rendez-vous peut être trop éloigné.'), ('Boire un café puis repartir immédiatement sans temps de récupération.', 'La consommation d’une boisson ne prouve pas une vigilance rétablie au moment du départ.')],
 'Réorganiser avant de confirmer': [('Confirmer les deux missions en utilisant leur durée moyenne sans marge.', 'Une moyenne ne réserve pas le temps de pause déjà identifié comme nécessaire.'), ('Compter l’attente à un feu ou dans les embouteillages comme récupération suffisante.', 'Un arrêt dans la circulation demande encore de l’attention et n’équivaut pas à une pause organisée.')],
 'Maintenir l’attention et surveiller la vigilance': [('Conserver la même durée de service parce que l’itinéraire est mémorisé.', 'La connaissance du trajet ne compense pas une baisse de vigilance.'), ('Réduire les contrôles aux seuls endroits où un incident s’est déjà produit.', 'Des risques nouveaux peuvent apparaître sur un parcours familier.')],
 'Prévenir et organiser une solution conforme': [('Effectuer la course en limitant seulement la vitesse.', 'Ralentir ne rend pas apte un conducteur qui ne peut plus rester suffisamment vigilant.'), ('Demander au passager de maintenir une conversation pendant le trajet.', 'Le passager ne peut pas garantir la vigilance du conducteur ; la conversation n’est pas une solution de remplacement.')],
 'Demander conseil au professionnel de santé et respecter les précautions': [('Tester le médicament pendant une courte course pour juger de son effet.', 'Un service avec passager n’est pas un moyen sûr d’évaluer un effet médicamenteux sur la vigilance.'), ('Appliquer les habitudes d’un collègue prenant un autre dosage.', 'Le dosage, le traitement et la situation personnelle peuvent différer ; le conseil doit être adapté.')],
 'Ne pas utiliser ce ressenti comme preuve d’aptitude ou de conformité': [('Se fier à un repas et à l’absence de sensation d’ivresse.', 'Le repas et le ressenti ne mesurent ni l’alcoolémie ni les capacités nécessaires à la conduite.'), ('Se tester sur quelques mètres avant de prendre le client.', 'Une conduite d’essai ne constitue pas une preuve fiable d’aptitude ou de respect des limites.')],
 'Préserver une conduite conforme et sûre': [('Accepter un verre puis décaler le départ d’un délai fixé au hasard.', 'Un délai improvisé ne permet pas de conclure que les effets de l’alcool ont disparu.'), ('Choisir une boisson moins forte et conserver le service prévu sans autre vérification.', 'Une teneur plus faible ne suffit pas à garantir une conduite conforme et sûre.')],
 'Consulter le prescripteur ou le pharmacien': [('Supprimer seulement la dose du matin pour cette journée de travail.', 'Modifier seul un traitement peut affecter la santé et ne permet pas de décider de l’aptitude à conduire.'), ('Décaler la dose après la dernière course sans avis professionnel.', 'Un changement d’horaire de prise constitue aussi une modification du traitement à faire vérifier.')],
 'Rejoindre un arrêt sûr avant de manipuler la navigation': [('Dicter puis vérifier le résultat sur l’écran pendant l’intersection.', 'La dictée ne supprime pas la distraction liée à la vérification de l’écran dans une situation complexe.'), ('Saisir seulement le nom de rue et compléter le numéro plus tard.', 'Une saisie partielle détourne encore l’attention au moment où elle doit rester disponible.')],
 'Proposer de vérifier une fois stationné': [('Consulter seulement la première réponse affichée en gardant une main sur le volant.', 'Une lecture brève reste une distraction ; la main sur le volant ne rend pas la recherche sûre.'), ('Lancer la recherche maintenant et lire les avis au prochain ralentissement.', 'Un ralentissement dans la circulation demande encore une surveillance ; ce n’est pas un stationnement sûr.')],
 'Ne pas se pencher pour le récupérer en roulant': [('Le récupérer sur la prochaine ligne droite si aucun véhicule n’est proche.', 'Se pencher réduit le champ de vision et le contrôle, même sur une ligne droite.'), ('Demander au passager de passer sous le siège pendant que le véhicule roule.', 'La recherche peut compromettre l’installation et la retenue du passager ; elle doit attendre un arrêt sûr.')],
 'La traiter selon une procédure compatible avec la conduite': [('La lire au prochain feu rouge sans examiner la situation de circulation.', 'Un arrêt au feu demande de surveiller la circulation et ne vaut pas une autorisation générale de manipuler le téléphone.'), ('Répondre immédiatement parce que la notification expire rapidement.', 'La durée de validité commerciale ne change pas le besoin de garder l’attention sur la conduite.')],
 'Anticiper et ralentir progressivement selon la situation': [('Maintenir l’allure jusqu’à ce que le freinage du véhicule précédent commence.', 'Attendre ce signal réduit la marge d’anticipation pourtant offerte par le ralentissement visible.'), ('Ralentir en observant uniquement l’avant, sans tenir compte de ceux qui suivent.', 'L’anticipation doit aussi intégrer la circulation derrière le véhicule pour une décélération adaptée.')],
 'Prioriser la sécurité même si le confort est affecté': [('Limiter le freinage à ce que les passagers trouvent confortable.', 'Le confort ne doit pas empêcher la réaction nécessaire à un danger immédiat.'), ('Chercher d’abord une trajectoire de contournement sans vérifier si elle est libre.', 'Une manœuvre vers une zone non contrôlée peut ajouter un danger au lieu d’éviter celui qui est identifié.')],
 'Surveiller la route et connaître ses limites': [('Concentrer l’attention sur le service client tant que l’aide reste activée.', 'L’activation d’une aide ne transfère pas toute la surveillance ni la responsabilité de conduite.'), ('Attendre l’alerte du système pour rechercher un danger.', 'Une aide peut détecter tardivement ou ne pas détecter certaines situations ; l’observation reste nécessaire.')],
 'Adapter la préparation et la conduite': [('Conserver tous les réglages habituels parce que le nombre de passagers ne change pas.', 'Le poids et sa répartition peuvent changer sans modification du nombre de passagers.'), ('Compenser la charge uniquement en prévoyant plus de carburant.', 'Le carburant concerne l’autonomie ; il ne traite ni l’arrimage ni le comportement du véhicule chargé.')],
 'Adapter l’allure et les marges': [('Conserver l’allure si les essuie-glaces dégagent correctement le pare-brise.', 'Le pare-brise dégagé ne rétablit pas l’adhérence et toute la visibilité perdue sous la pluie.'), ('Réduire la vitesse mais se rapprocher du véhicule précédent pour suivre ses feux.', 'Se rapprocher réduit la distance disponible alors que la visibilité et l’adhérence peuvent être dégradées.')],
 'Respecter la fermeture et rechercher une alternative autorisée': [('Franchir la fermeture si le GPS calcule encore ce trajet.', 'La carte peut être en retard sur l’événement ; elle ne vaut pas autorisation de passage.'), ('Attendre derrière la barrière sans chercher de lieu d’attente autorisé.', 'L’attente doit aussi être sûre et autorisée ; une fermeture n’y crée pas automatiquement un emplacement adapté.')],
 'Utiliser l’éclairage adapté sans éblouir': [('Garder l’éclairage le plus puissant tant que personne ne fait d’appel de phares.', 'L’absence de réaction d’autrui ne prouve pas l’absence d’éblouissement.'), ('Corriger uniquement l’orientation en conservant des feux inadaptés à la situation.', 'Un réglage ne remplace pas le choix du type de feux approprié.')],
 'Informer le client et préserver les marges': [('Confirmer l’heure initiale en retirant la marge prévue à l’arrivée.', 'Supprimer une marge sur le papier ne rend pas le trajet plus rapide et peut produire une promesse irréaliste.'), ('Attendre la fin du trajet pour expliquer le retard réellement constaté.', 'Une information tardive prive le client de la possibilité d’adapter son rendez-vous.')],
 'Prioriser la protection et l’alerte appropriée': [('Appeler d’abord un véhicule de remplacement tout en restant exposé près de la circulation.', 'La continuité commerciale vient après la mise en sécurité face au risque immédiat.'), ('Photographier les dégâts avant de déplacer les occupants vers un endroit sûr.', 'Les preuves ne passent pas avant la protection des personnes exposées.')],
 'L’en dissuader et utiliser un moyen d’alerte sûr': [('Le laisser traverser s’il porte un gilet visible.', 'Un gilet améliore la visibilité, mais ne rend pas la traversée des voies sûre.'), ('Traverser avec lui pour lui apporter une aide.', 'Accompagner le passager expose une personne supplémentaire sans supprimer le danger.')],
 'Vérifier qu’il permet un transport sûr et conforme': [('Retenir le véhicule le plus proche en vérifiant uniquement le nombre de places.', 'La capacité ne prouve pas l’éligibilité, les garanties ni l’état du véhicule de remplacement.'), ('Utiliser le véhicule après accord du client sans vérifier l’assurance.', 'L’accord commercial du passager ne remplace pas les garanties nécessaires au transport.')],
 'Donner une information factuelle et la solution prévue': [('Annoncer le délai le plus court évoqué, même si le prestataire ne l’a pas confirmé.', 'Une estimation non confirmée doit rester présentée comme telle, sans devenir une promesse.'), ('Expliquer seulement la cause probable de la panne sans préciser la suite du service.', 'Le client a aussi besoin d’une solution et d’un prochain point d’information, même si la cause reste à confirmer.')],
})
# Exact obsolete distractor -> (plausible alternative, explanation of its error).
CHOICES = {}
CHOICES.update({
 'La couleur de la voiture uniquement': ('Le seul nombre de passagers, sans examiner l’organisation du service.', 'Des départs et arrêts fixes demandent d’examiner le régime du service, pas seulement la capacité.'),
 'La couleur du téléphone utilisé': ('Le seul nom de la commune sans préciser la voie ni le sens.', 'Sur une voie à deux sens, une localisation imprécise peut diriger les secours du mauvais côté.'),
 'Seulement la couleur du véhicule': ('Le montant de la franchise, sans vérifier l’usage professionnel couvert.', 'Une franchise ne précise pas si le transport rémunéré de personnes entre dans les garanties.'),
 'Rien : tous les usages sont automatiquement couverts': ('La présence de la mention « tous risques », sans lire les exclusions d’usage.', 'Une formule commerciale ne prouve pas la couverture du transport rémunéré ni l’absence d’exclusions.'),
 'Supprimer l’échéance médicale du suivi': ('Attendre la date de la carte pour renouveler les deux pièces ensemble.', 'Les échéances sont distinctes ; la carte peut rester datée comme valide alors que la condition médicale doit être renouvelée.'),
 'Aucun suivi nécessaire': ('En attente de fabrication, sans vérifier si la demande a été acceptée.', 'Le dépôt ne prouve pas une décision favorable ; il faut suivre l’instruction avant de conclure à une fabrication.'),
 'Toute mention quelconque interdit toujours la profession': ('Se limiter au bulletin personnel présenté par le candidat pour conclure.', 'L’honorabilité fait l’objet du contrôle prévu ; un document personnel ne remplace pas ce contrôle.'),
 'L’honorabilité n’a jamais à être vérifiée': ('Considérer la réussite à l’examen comme une validation de l’honorabilité.', 'L’examen et les conditions d’honorabilité répondent à des exigences distinctes.'),
 'Refuser toute discussion sans examen': ('Maintenir le refus en se fondant uniquement sur l’absence de facture d’achat de l’objet.', 'Une pièce manquante appelle un examen des faits et justificatifs disponibles, pas une conclusion automatique.'),
 'Reconnaître immédiatement toutes les responsabilités': ('Promettre le remboursement intégral avant de vérifier le dommage et les garanties.', 'L’accueil de la réclamation n’impose pas de reconnaître un montant ou une responsabilité non établis.'),
 'Son dossier médical complet': ('Le diagnostic détaillé, même s’il ne change pas l’aide à organiser.', 'Le service demande de connaître les besoins utiles ; le diagnostic peut être inutile et excessif.'),
 'Le nom de tous ses médecins': ('L’historique des déplacements médicaux précédents.', 'Cet historique ne décrit pas l’aide nécessaire pour la prise en charge actuelle et collecte des informations supplémentaires.'),
 'Exiger tout le dossier médical': ('Demander le diagnostic avant de discuter des besoins pratiques.', 'La préparation du service peut se faire à partir des besoins sans demander une justification médicale détaillée.'),
 'Le dossier médical de sa famille': ('L’historique complet des demandes d’assistance, même sans lien avec cette mission.', 'Le remplaçant doit recevoir les informations utiles au service actuel, pas tout l’historique du client.'),
 'Effacer tous les documents sans analyse': ('Effacer aussi les factures soumises à une obligation de conservation.', 'Une demande d’effacement doit être examinée selon la finalité et les obligations de conservation de chaque document.'),
 'Refuser toute demande de manière définitive': ('Conserver les coordonnées de prospection aussi longtemps que les factures.', 'La durée de conservation d’une facture ne justifie pas automatiquement celle d’un fichier commercial.'),
 'Supprimer le trajet de l’application': ('Modifier l’heure de réservation pour la faire correspondre à la prise en charge.', 'Corriger l’affichage ne prouve pas une réservation antérieure réelle ; la chronologie doit correspondre aux faits.'),
 'Montrer les réservations de tous les clients': ('Conserver une capture avec seulement le prénom et le prix.', 'La solution de secours doit permettre de présenter les informations requises, pas un résumé incomplet.'),
 'Affirmer que tous les bons sont interchangeables': ('Présenter le bon d’une mission voisine réalisée par le même exploitant.', 'Le justificatif doit concerner le client et la mission contrôlés, même si l’entreprise est la même.'),
 'Affirmer que tous les bons sont identiques': ('Utiliser le bon le plus récent sans vérifier la mission qu’il concerne.', 'La date seule ne permet pas de choisir le justificatif correspondant au contrôle.'),
 'Inventer une panne survenue la veille': ('Présenter seulement le bon initial sans documenter le remplacement.', 'Le changement de véhicule doit être expliqué avec des pièces correspondant à la situation réelle.'),
 'Effacer la réservation': ('Corriger la plaque sur une copie sans conserver la trace du changement.', 'Une modification non traçable ne permet pas de comprendre l’incohérence relevée.'),
 'Le chauffeur peut effacer toutes les preuves': ('Clore aussi le suivi auprès de l’assureur sans vérifier les démarches restantes.', 'Un accord commercial ne règle pas nécessairement les autres responsabilités et obligations de déclaration.'),
 'Supprimer les échanges pour éviter un conflit': ('Conserver uniquement le message où le client accepte le geste commercial.', 'Une chronologie partielle peut masquer les faits nécessaires à l’analyse du dommage.'),
 'Accuser automatiquement le passager': ('Se fonder uniquement sur l’horaire reçu par le chauffeur pour conclure.', 'Il faut aussi vérifier l’engagement communiqué au client et l’origine de la divergence.'),
 'La couleur du véhicule': ('L’heure de fin de la course précédente.', 'Cet horaire n’établit pas le moment où cette commande a été passée ni celui de sa prise en charge.'),
 'Rien, une heure suffit à tout prouver': ('Seulement la date du document, sans vérifier les identités ni les autres mentions.', 'La chronologie n’est qu’un contrôle parmi ceux nécessaires sur le justificatif.'),
 'Automatiquement sans objet': ('Déposé, assimilé à une inscription déjà obtenue.', 'Une démarche déposée et une inscription confirmée sont deux états différents ; il faut lire le dossier.'),
 'Toutes les pièces sont automatiquement périmées': ('Renouveler toutes les pièces à la date de celle qui expire la dernière.', 'Chaque condition a son échéance ; attendre la dernière peut laisser une pièce obligatoire expirer.'),
 'L’assurance personnelle de tous les clients': ('La protection juridique, considérée comme preuve de toutes les garanties métier.', 'La protection juridique ne prouve pas les garanties de circulation et de responsabilité professionnelle demandées.'),
 'Une couverture illimitée de tous les dommages': ('La formule commerciale du contrat sans ses usages et exclusions.', 'La portée de la garantie dépend du contrat et de l’activité couverte, pas de sa seule appellation.'),
 'Le titulaire n’a jamais d’importance': ('Une concordance suffisante dès que les entreprises ont le même dirigeant.', 'Deux entreprises ne sont pas nécessairement le même titulaire ; il faut rapprocher la pièce de l’exploitant concerné.'),
 'Les obligations sont toujours identiques': ('Les formalités de société découlent uniquement du montant de chiffre d’affaires.', 'Les formalités tiennent aussi à la structure juridique ; comparer seulement le chiffre d’affaires confond forme et régime.'),
 'Effacer la facture sans trace': ('Modifier directement la facture envoyée sans conserver la version initiale.', 'Une correction doit préserver la traçabilité de la pièce et du changement.'),
 'Obtenir automatiquement un salaire net garanti': ('Avoir encaissé toutes les créances nécessaires au paiement des prochaines échéances.', 'Le seuil de rentabilité porte sur charges et marge ; il ne garantit pas l’encaissement à une date donnée.'),
 'Une déclaration Urssaf remplace tous les impôts': ('Déclarer les recettes à un seul organisme sans vérifier les déclarations fiscales.', 'Les obligations sociales, fiscales et métier ont des objets et destinataires distincts.'),
 'Le chiffre d’affaires est toujours le solde bancaire': ('Le résultat inclut les encaissements à venir comme de l’argent déjà disponible.', 'Une recette comptabilisée peut rester à encaisser ; le solde bancaire demande les flux et le solde initial.'),
 'Les kilomètres à vide n’ont jamais de coût': ('Le kilométrage facturé suffit pour estimer les frais variables de toute la mission.', 'L’approche et le retour consomment aussi des ressources même sans passager payant.'),
 'Supprimer les approches du planning': ('Limiter le calcul aux périodes où un client se trouve dans le véhicule.', 'Le temps d’approche mobilise aussi le chauffeur et doit être inclus dans le périmètre demandé.'),
 'Facturer tous les clients de la même façon sans données': ('Ajouter le supplément habituel sans préciser le début du décompte d’attente.', 'Un supplément uniforme ne résout pas l’absence de conditions et de relevé vérifiables.'),
 'La marge doit être nulle': ('La marge doit être exactement de quinze minutes.', '« Au moins » fixe un minimum et autorise davantage ; il ne fixe pas une durée exacte.'),
 'Il est toujours fermé': ('Une réservation garantit l’accès quelle que soit la disponibilité.', '« Uniquement sur réservation » énonce une condition nécessaire, pas la garantie que tout créneau demandé est disponible.'),
 'Le trajet est annulé': ('Un arrêt supplémentaire est compris si sa durée est courte.', '« Aucun arrêt supplémentaire n’est inclus » ne prévoit pas cette exception de durée.'),
 'Aucun dossier ne sera vérifié': ('La vérification aura commencé avant l’arrivée.', 'La phrase place la vérification après l’arrivée ; elle ne décrit pas une action déjà commencée.'),
 'La couleur des valises': ('Le nom de l’enseigne hôtelière sans son adresse.', 'Plusieurs établissements peuvent porter le même nom ; l’adresse complète permet de les distinguer.'),
 'La nationalité des voyageurs': ('Le quartier de l’hôtel sans le nom de rue.', 'Le quartier seul peut encore contenir plusieurs établissements ; il ne remplace pas l’adresse demandée.'),
 'Tous les grands bagages sur ses genoux': ('Le bagage enregistré destiné au coffre.', 'Il faut distinguer le bagage rangé au coffre des objets que le dialogue demande de garder avec soi.'),
 'Aucune climatisation obligatoire': ('La même température qu’actuellement.', 'Cette proposition ne reprend pas la demande de modification exprimée dans le dialogue.'),
 'Une musique très forte': ('Un fond musical maintenu au volume actuel.', 'Le souhait exprimé porte sur l’ambiance ; conserver le réglage actuel ne reprend pas nécessairement la demande de calme.'),
 'Toujours moins de cinq minutes': ('Environ cinq minutes.', 'Le nombre annoncé dans l’audio donne une durée plus longue ; il faut distinguer les minutes entendues sans les réduire.'),
 'Jamais, le conducteur décide seul': ('Après l’exécution de la modification, au moment d’établir la facture.', 'La confirmation doit précéder le changement ; la facture constate une prestation déjà réalisée.'),
 'Une annulation décidée sans prévenir': ('Un changement déjà confirmé sans attendre la vérification annoncée.', 'Le dialogue distingue une option à vérifier d’une solution déjà confirmée.'),
 'À n’importe quel inconnu': ('À la personne présente au point de rendez-vous sans vérifier son identité.', 'Une remise sécurisée exige de confirmer que l’interlocuteur est autorisé à récupérer l’objet.'),
 'Que toutes les chambres commanderont forcément une course': ('Le nombre de chambres occupées, sans identifier les transferts effectivement demandés.', 'L’occupation d’un hôtel n’est pas un volume de courses accessible à l’entreprise.'),
 'Qu’aucun concurrent ne travaille': ('Le seul prix du concurrent le moins cher.', 'Un prix concurrent ne renseigne ni le besoin, ni les créneaux, ni les conditions d’accès à la clientèle.'),
 'La couleur du véhicule uniquement': ('Le seul niveau de prix annoncé, sans analyser la prestation.', 'La présentation commerciale ne remplace pas l’analyse du service et de son coût.'),
 'Seulement la musique': ('Le seul supplément de prix pour deux voyageurs supplémentaires.', 'Un supplément ne crée pas de places autorisées ; la capacité doit être réexaminée.'),
 'Pour pouvoir refuser tous les passagers à l’arrivée': ('Pour fixer le prix avant de vérifier si les bagages peuvent être transportés.', 'L’information sert à confirmer la faisabilité, pas seulement à établir un prix avant de connaître le besoin.'),
 'Aucun retard possible quelles que soient les conditions': ('Une durée fondée uniquement sur le trajet le plus rapide déjà observé.', 'Un meilleur temps passé n’est pas une garantie dans les conditions de la mission future.'),
 'La couleur choisie pour le tableau': ('Le seul chiffre d’affaires apporté par la campagne.', 'Le chiffre d’affaires ne suffit pas à apprécier le coût d’acquisition, la contribution et le retour des clients.'),
 'Le nombre de couleurs du logo': ('Le nombre de messages envoyés sans mesurer les réponses ni les conversions.', 'Le volume d’envoi mesure l’effort, pas son efficacité commerciale.'),
 'Seulement la couleur des cartes de visite': ('Le seul volume de courses espéré sans horaires ni conditions d’annulation.', 'Un partenariat doit préciser les engagements réalisables, pas seulement un volume potentiel.'),
 'Faire monter tous les clients dans trois véhicules au-delà de la capacité': ('Répartir les départs sur plusieurs heures sans faire accepter ce changement.', 'Cela modifie la demande de départs simultanés ; il faut convenir d’une organisation réalisable avec le partenaire.'),
 'Accepter tous les départs sans solution': ('Confirmer les dix départs avant de vérifier les disponibilités de sous-traitants.', 'La disponibilité de moyens supplémentaires ne doit pas être supposée au moment de l’engagement.'),
 'Rien tant que la relation est cordiale': ('Attendre la première annulation pour fixer les frais et délais applicables.', 'Les conditions doivent être clarifiées avant le service, afin de ne pas les définir après un incident.'),
 'Uniquement la couleur du document': ('Le seul prix des courses réalisées, sans conditions d’annulation.', 'Le prix de la course n’explique pas ce qui se passe si elle est annulée ou décalée.'),
 'Créer une nouvelle erreur pour compenser': ('Accorder une remise sur une course future sans corriger la facture erronée.', 'Un geste commercial ne répare pas la pièce incorrecte ni la traçabilité de l’opération initiale.'),
 'Nier malgré les éléments': ('Demander un nouveau justificatif déjà présent sans traiter l’erreur confirmée.', 'Lorsque l’erreur est établie, il faut la corriger et informer le client plutôt que retarder son traitement.'),
 'Supprimer la facture sans examen': ('Émettre immédiatement un avoir total sans vérifier le supplément contesté.', 'La réclamation appelle d’abord le rapprochement des conditions, de la prestation et du calcul.'),
 'Promettre de supprimer tous les avis négatifs': ('Proposer un geste commercial uniquement si le client retire son avis.', 'Le traitement d’une réclamation justifiée ne doit pas être conditionné au retrait d’un avis honnête.'),
 'Un remboursement certain sans habilitation': ('Annoncer le montant habituellement remboursé avant validation du décideur.', 'Une pratique passée ne donne pas au chauffeur l’habilitation nécessaire pour engager l’entreprise.'),
 'Une absence totale de réponse': ('Transmettre le dossier sans annoncer qui répondra ni dans quel délai.', 'Une transmission sans suivi ne donne pas au client une perspective de traitement.'),
 'Reconnaître n’importe quel montant demandé': ('Retenir le montant réclamé sans le rapprocher des conditions et des faits.', 'Le montant doit être justifié par le dossier avant de décider de la correction financière.'),
})
CHOICES.update({
 'La seule couleur de la carrosserie': ('Le montant du loyer, sans examiner la durée ni le titulaire du contrat.', 'La situation de détention du véhicule ne se déduit pas du seul loyer ; durée et justificatifs comptent.'),
 'Le fait que le conducteur préfère ce modèle': ('La durée habituelle des locations précédentes plutôt que celle du contrat signé.', 'Il faut vérifier le véhicule et le contrat concernés, pas une habitude antérieure.'),
 'Attendre sans vérifier jusqu’à la fermeture de l’entreprise': ('Attendre le prochain renouvellement du registre sans examiner la procédure de mise à jour.', 'Une modification importante doit être traitée selon la procédure applicable ; elle ne peut être différée sans vérification.'),
 'Oui, tous les numéros sont équivalents': ('Oui, si l’autre société appartient au même réseau commercial.', 'L’appartenance à un réseau ne confond pas les exploitants ni leurs inscriptions.'),
 'Oui, automatiquement': ('Oui, si l’acceptation commerciale mentionne le même véhicule.', 'Une vérification commerciale n’est pas une décision administrative du registre.'),
 'Le prix du trajet change automatiquement': ('La pièce reste utilisable si les deux sociétés ont le même responsable.', 'Un dirigeant commun ne rend pas les deux sociétés interchangeables comme titulaires.'),
 'Aucun, toutes les sociétés sont équivalentes': ('Le justificatif suffit dès lors qu’il concerne un véhicule de même modèle.', 'Le modèle du véhicule ne corrige pas une différence de titulaire du dossier.'),
 'Supposer que toutes les règles disparaissent': ('Appliquer l’exception de motorisation aux assurances et au contrôle technique.', 'Une exception sur des caractéristiques techniques ne supprime pas les autres obligations.'),
 'Accepter toute voiture portant un autocollant vert': ('Retenir la qualification commerciale « écologique » sans vérifier la catégorie technique.', 'Une appellation publicitaire ne prouve pas l’appartenance à une catégorie bénéficiant d’une exception.'),
 'Ignorer la fiche technique': ('Utiliser la fiche d’une version proche du même modèle.', 'La motorisation et les caractéristiques peuvent changer d’une version à l’autre.'),
 'Oui, si les sièges se ressemblent': ('Oui, si le nom du modèle et l’année de commercialisation sont identiques.', 'Une même gamme et une même année peuvent comporter des versions techniques différentes.'),
 'Six si un trajet est court': ('Trois, en retirant deux places pour le conducteur.', 'La capacité comprend un seul conducteur ; cinq places au total laissent quatre places passagers.'),
 'Oui, tous les passagers peuvent être ajoutés au conducteur': ('Oui, en lisant les places totales comme des places passagers.', 'Le nombre de places du véhicule comprend le conducteur ; il faut le retrancher pour obtenir la capacité passagers.'),
 'Oui, si les voitures ont la même couleur': ('Oui, si les véhicules appartiennent au même exploitant.', 'Un exploitant commun ne prouve pas que la signalétique et les documents correspondent au véhicule remplacé.'),
 'Oui, les immatriculations n’ont aucune importance': ('Oui, si le modèle et la motorisation sont identiques.', 'L’identité du véhicule ne se réduit pas à son modèle ; le remplacement demande de vérifier les pièces applicables.'),
 'Une voiture de luxe est dispensée de tout repère': ('L’acceptation du véhicule par la plateforme tient lieu de signalétique réglementaire.', 'La validation commerciale ne remplace pas les éléments réglementaires d’identification.'),
 'Ajouter seulement un logo publicitaire': ('Conserver une photographie du macaron lisible sans traiter celui du véhicule.', 'La copie conservée ne remet pas en état l’élément réglementaire devenu illisible.'),
 'Le masquer davantage': ('Reporter la remise en conformité au prochain changement de véhicule.', 'Le défaut concerne le véhicule utilisé maintenant ; il doit être traité selon la procédure applicable.'),
 'Aucun, les documents suivent toujours le conducteur': ('Reprendre les pièces du véhicule habituel lorsque le conducteur reste le même.', 'Le titre personnel du conducteur et les documents du véhicule ont des objets distincts.'),
 'Seulement le niveau de musique': ('L’accord commercial du client, sans rapprocher les pièces du nouveau véhicule.', 'L’accord du client ne prouve pas la conformité du véhicule de remplacement.'),
 'La couleur des bagages': ('L’heure de paiement de la course.', 'Le paiement ne remplace pas la date et l’heure auxquelles la réservation a été passée.'),
 'Le menu choisi à destination': ('L’heure estimée d’arrivée à destination.', 'L’arrivée estimée ne prouve pas l’antériorité de la commande par rapport à la prise en charge.'),
 'Inventer un numéro pour compléter': ('Donner seulement le standard de l’entreprise, sans possibilité de joindre le client sans délai.', 'Le moyen fourni doit permettre à l’agent de contacter le client sans délai dans le cadre prévu.'),
 'Affirmer qu’aucun contact n’est jamais nécessaire': ('Promettre de transmettre les coordonnées après la fin du contrôle.', 'Un envoi ultérieur ne répond pas à l’exigence de mise en contact sans délai.'),
 'L’ordre des horaires n’a aucune importance': ('La date d’édition du document suffit, même si l’heure de commande est absente.', 'L’édition du document et la réservation réelle sont deux événements distincts.'),
 'Un numéro inventé peut être ajouté': ('Le prénom du client suffit pour reconstituer son contact après le contrôle.', 'Une possibilité future de recherche ne constitue pas un moyen de contacter le client sans délai.'),
 'Utiliser un faux bon déjà préparé': ('Réutiliser le bon d’une course annulée en ne changeant que le prénom.', 'Un document d’une autre mission ne prouve pas la réservation préalable du passant.'),
 'Rien, un bon vaut pour tous les clients': ('Seulement le prix, puisque le point de départ reste identique.', 'Un lieu identique ne transforme pas la réservation d’un client en celle d’un autre.'),
 'Seulement le nombre de valises': ('Seulement la destination, si elle est identique à celle du premier client.', 'La réservation doit correspondre à la prestation effectivement réalisée et au client pris en charge.'),
 'Supprimer toute communication avec le client': ('Conserver le rendez-vous initial sans vérifier l’heure actualisée du vol.', 'Le suivi de l’arrivée permet d’adapter l’attente et d’informer le client avant une difficulté.'),
 'Masquer la signalétique du véhicule': ('Utiliser la voie réservée le temps d’un embarquement très rapide.', 'Une durée courte ne constitue pas à elle seule une autorisation d’accès à une voie réservée.'),
 'Deviner la sortie au hasard': ('Choisir la sortie utilisée lors du précédent vol du client.', 'Le changement de terminal demande une confirmation actuelle, pas l’application d’une habitude.'),
 'Un faux bon pour une mission hypothétique': ('Un simple agenda personnel sans conserver le justificatif de la réservation confirmée.', 'L’organisation du planning ne remplace pas la preuve de la réservation.'),
 'Une attente sur n’importe quelle voie': ('L’attente au point le plus proche sans vérifier son autorisation.', 'La proximité du client ne donne pas un droit général de stationnement.'),
 'Aucun contrôle une fois le client descendu': ('Le seul montant prévu, sans examiner la durée et le lieu d’attente.', 'Une mise à disposition doit être rapprochée de ses conditions réelles et des règles de stationnement.'),
 'Seulement le nom de l’hôtel': ('La seule présence du client dans cet hôtel.', 'Le lieu de séjour ne prouve pas les conditions du contrat ni l’autorisation d’attendre au lieu choisi.'),
 'Uniquement la couleur des sièges': ('La seule adresse de destination, sans traiter l’attente prévisible.', 'L’adresse est utile, mais ne définit pas le temps inclus et le coût de l’attente supplémentaire.'),
 'Le signe astrologique du client': ('Le mode de paiement, sans préciser les conditions du supplément.', 'Le paiement ne définit pas le contenu du prix ni la méthode de calcul de l’attente.'),
 'Rien, le chiffre règle tout': ('La seule concordance entre le prix affiché et le montant saisi au terminal.', 'Il faut aussi connaître la prestation couverte et les conditions d’éventuelles modifications.'),
 'Le présenter comme une amende': ('Le présenter comme inclus puis le rajouter au total après le trajet.', 'L’information tarifaire doit être cohérente avec les conditions acceptées ; une annonce contradictoire crée un litige.'),
 'Oui, s’il a déjà conduit une berline': ('Oui, si l’exploitant confirme son expérience professionnelle.', 'L’expérience déclarée ne remplace pas une carte professionnelle personnelle valide.'),
 'Oui, si la course dure moins de dix minutes': ('Oui, si le client accepte le remplacement par écrit.', 'L’accord du client ne remplace pas les conditions requises pour le conducteur.'),
 'Aucune, toute location autorise le VTC': ('Le contrat de location seul, sans vérifier l’usage assuré et l’éligibilité.', 'La disponibilité d’une location ne prouve pas qu’elle peut être utilisée pour le transport VTC.'),
 'Seulement la climatisation': ('Le niveau de confort annoncé par le loueur.', 'Le confort ne remplace pas les vérifications réglementaires et d’assurance du véhicule réel.'),
 'Modifier son nom pour correspondre au bon': ('Laisser la plaque précédente sur la confirmation pour ne pas modifier le dossier.', 'Le client doit pouvoir reconnaître le véhicule réel ; conserver une information obsolète entretient la confusion.'),
 'La liste de ses consultations': ('Le diagnostic supposé à partir de ses anciennes demandes.', 'Le remplaçant a besoin d’informations pratiques pertinentes, pas d’une interprétation de la santé du passager.'),
 'Augmenter la musique pour ne plus entendre le bruit': ('Se fier au contrôle technique encore valide sans analyser le défaut nouveau.', 'Un contrôle antérieur ne garantit pas l’absence de défaut apparu depuis ; le freinage doit être traité avant une mission dangereuse.'),
 'Le nombre d’applications installées': ('Le nombre de courses, sans tenir compte de leur distance.', 'Deux courses peuvent avoir des distances très différentes ; l’entretien suit l’usage réel du véhicule.'),
 'Les seules évaluations des clients': ('La distance totale facturée, en excluant les approches et les retours.', 'Les kilomètres à vide usent aussi le véhicule et doivent être comptés dans son suivi.'),
 'Le cacher aux passagers': ('Reporter l’intervention jusqu’à ce qu’un client constate le défaut.', 'Le suivi du véhicule relève du professionnel ; il ne dépend pas d’une réclamation du client.'),
 'Choisir celui dont le titre est le plus court': ('Retenir la publication la plus récente sans examiner la date d’effet du texte cité.', 'La date d’un article n’est pas nécessairement celle de la règle qu’il décrit.'),
 'Suivre toujours le premier résultat': ('Retenir la règle reprise par le plus grand nombre de sites sans remonter au texte.', 'La répétition d’une information ne prouve pas son actualité ni son champ d’application.'),
 'Toujours le jour où vous découvrez le texte': ('La date de publication, sans vérifier la disposition d’entrée en vigueur.', 'Une entrée en vigueur différée doit être distinguée de la publication.'),
 'La date du commentaire d’un internaute': ('La date de mise à jour du guide commercial consulté.', 'Une mise à jour de guide n’établit pas la date d’application juridique à la situation.'),
 'Uniquement une rumeur résumée': ('La conclusion copiée sans le lien ni la version du texte.', 'Sans source et version, l’équipe ne peut pas vérifier le fondement ni l’évolution de la décision.'),
 'Le nom du premier collègue qui l’a entendue': ('La date de transmission interne sans le périmètre d’application.', 'La traçabilité demande aussi de savoir quelle situation est couverte par la règle.'),
})
DECISIONS.update({
 'Clarifier les rôles et l’identité à accueillir': [('Remplacer le nom du passager par celui du payeur sans confirmation.', 'Le réservant, le voyageur et le payeur peuvent être différents ; il faut identifier la personne attendue.'), ('Annuler la mission parce que les deux noms ne correspondent pas.', 'La différence peut être normale, notamment pour une réservation d’entreprise ; elle demande une clarification.')],
 'Faire préciser l’adresse avant de partir': [('Retenir la commune la plus proche du point de départ.', 'La proximité ne permet pas de savoir quelle adresse le client a réellement demandée.'), ('Choisir le premier résultat de navigation puis confirmer à l’arrivée.', 'Une confirmation tardive risque d’imposer un détour ; l’ambiguïté doit être levée avant le départ.')],
 'Vérifier une solution adaptée': [('Accepter en prévoyant de répartir les bagages libres entre les passagers.', 'La répartition ne garantit ni retenue des objets ni accès libre aux issues.'), ('Conserver le véhicule prévu en comptant sur une valise laissée sur une place occupée.', 'Une place occupée ne constitue pas une capacité supplémentaire de rangement sûr.')],
 'Clarifier et proposer une organisation réaliste': [('Confirmer l’heure en prenant le meilleur temps observé sur ce trajet.', 'Un record de trajet ne constitue pas une estimation fiable pour cette mission.'), ('Réduire le temps annoncé en retirant toutes les minutes prévues pour l’installation.', 'L’installation reste nécessaire ; sa suppression dans le calcul ne résout pas l’incompatibilité.')],
 'L’exclure des options possibles': [('Le conserver dans la comparaison, mais ajouter une petite marge de temps.', 'Une marge ne rend pas un véhicule compatible avec une restriction d’accès.'), ('Le retenir si son avantage de coût compense le détour des autres trajets.', 'La conformité est une condition préalable, pas un coût à arbitrer contre une économie.')],
 'Expliquer l’option et les conditions au client': [('Choisir le péage puis laisser la facture expliquer le supplément.', 'La facture arrive après le choix ; elle ne remplace pas l’information et l’accord utiles en amont.'), ('Éviter systématiquement le péage sans examiner le besoin d’horaire du client.', 'Les deux options sont autorisées : il faut présenter leurs conséquences plutôt que supposer la préférence du client.')],
 'Le comparer sur le temps et la fiabilité, pas seulement les kilomètres': [('Choisir automatiquement celui qui a le moins de kilomètres.', 'La distance seule ne permet pas d’évaluer l’heure d’arrivée et la fiabilité dans les conditions données.'), ('Choisir automatiquement le plus long puisque sa marge est supérieure.', 'Une marge utile doit être mise en balance avec le temps, le coût et les conditions convenues.')],
 'Réévaluer le parcours et informer le client en sécurité': [('Changer de trajet sans réexaminer le délai annoncé.', 'La fermeture peut affecter l’heure d’arrivée ; le nouveau parcours doit être évalué et expliqué.'), ('Attendre que le client remarque le détour avant de l’informer.', 'Une information proactive permet au client d’anticiper les conséquences du changement.')],
 'Les repérer à l’arrêt avant le départ': [('Se limiter aux commandes identiques à celles du véhicule habituel.', 'Les fonctions différentes sont précisément celles qui demandent une familiarisation.'), ('Prévoir d’identifier le désembuage seulement s’il devient nécessaire.', 'Une commande urgente à retrouver en circulation peut détourner l’attention ; elle doit être repérée avant le départ.')],
 'Revoir son installation': [('Réduire la luminosité de l’écran sans déplacer le support.', 'La luminosité ne supprime pas le masquage physique d’une partie de la route.'), ('Déplacer le support plus haut sans vérifier le nouveau champ de vision.', 'Un déplacement doit être contrôlé ; il peut déplacer le masquage plutôt que le supprimer.')],
 'Régler le poste avant de partir': [('Corriger seulement les rétroviseurs depuis la position inconfortable.', 'Les rétroviseurs doivent être réglés après une position permettant de maîtriser les commandes.'), ('Repousser le siège au maximum pour libérer les mouvements.', 'Plus d’espace ne garantit pas l’accès aux pédales et au volant sans étirement.')],
 'Le ranger de manière sûre': [('Coincer le câble sous le tapis sans vérifier sa fixation.', 'Un câble mal fixé peut revenir vers les commandes ; le rangement doit rester stable.'), ('Le déplacer sur le siège conducteur pour le garder accessible.', 'Cela crée encore un objet libre susceptible de gêner les gestes ou de retomber.')],
 'Vérifier discrètement une information de réservation': [('Demander uniquement à chacun de confirmer le prénom annoncé.', 'Les deux personnes ont le même prénom : ce contrôle ne permet pas de les distinguer.'), ('Annoncer publiquement toutes les coordonnées figurant sur le bon.', 'La vérification doit éviter une divulgation excessive de données personnelles.')],
 'Respecter ce choix tout en donnant les informations utiles': [('Ne plus transmettre aucune information, même en cas de changement de trajet.', 'Respecter le calme n’interdit pas les informations nécessaires à la mission.'), ('Limiter la conversation à des questions personnelles courtes.', 'Le souhait de calme porte sur l’échange, pas seulement sur la longueur des questions.')],
 'Proposer de l’aide et agir avec accord et prudence': [('Prendre la valise sans attendre la réponse pour accélérer l’embarquement.', 'Une aide utile suppose l’accord du client et une manipulation adaptée.'), ('Laisser la valise au client dès lors qu’elle paraît lourde, sans proposer d’autre solution.', 'La prudence ne dispense pas d’identifier une aide réalisable ou une méthode adaptée avec le client.')],
 'Clarifier avant le départ': [('Suivre le bon sans demander si le besoin du client a changé.', 'Le document et la demande diffèrent : un changement réel doit pouvoir être identifié.'), ('Suivre l’adresse orale sans vérifier ses conséquences sur la réservation.', 'Une nouvelle destination peut modifier la prestation, le prix ou l’organisation ; elle doit être clarifiée.')],
 'Terminer en sécurité puis confirmer et traiter la demande': [('Répéter l’adresse et lancer immédiatement sa saisie pendant la manœuvre.', 'Confirmer et saisir à ce moment ajoute une tâche alors que la manœuvre nécessite l’attention.'), ('Mémoriser approximativement l’adresse sans la faire confirmer ensuite.', 'Une mémorisation partielle peut produire une destination erronée ; la confirmation reste nécessaire une fois disponible.')],
 'Reporter poliment l’explication': [('Donner l’explication complète en observant régulièrement le client dans le rétroviseur.', 'Le passage difficile impose de garder l’attention sur la route ; une explication longue peut attendre.'), ('Répondre très vite en utilisant des informations non vérifiées.', 'La rapidité ne justifie ni une distraction ni une information inventée.')],
 'Poursuivre jusqu’à une correction autorisée': [('Tourner à la prochaine ouverture sans vérifier son sens de circulation.', 'La correction doit rester autorisée ; la proximité d’une ouverture ne suffit pas.'), ('S’immobiliser à l’endroit de l’erreur pour relire le plan.', 'Un arrêt improvisé peut gêner ou exposer le véhicule ; il faut chercher un lieu adapté.')],
 'Vérifier sa cohérence avec la signalisation': [('Accepter le changement parce que l’estimation d’arrivée est meilleure.', 'Un gain de temps ne prouve pas que l’accès proposé est autorisé.'), ('Suivre l’écran si aucun autre véhicule ne contredit la manœuvre.', 'La faible circulation ne permet pas de déduire les règles d’accès ; la signalisation reste à vérifier.')],
 'Proposer la dépose autorisée la plus adaptée': [('S’arrêter devant la porte en gardant le moteur allumé.', 'Le moteur en marche ne crée pas une autorisation d’arrêt.'), ('Laisser le passager choisir la responsabilité de cet arrêt.', 'La demande du client ne transfère pas au passager les obligations du conducteur.')],
 'Attendre et prévenir le passager avant l’ouverture': [('Demander au passager de regarder lui-même sans lui signaler le cycliste observé.', 'Le conducteur dispose d’une information utile qu’il doit transmettre ; déléguer ne supprime pas le risque.'), ('Entrouvrir la porte pour montrer l’intention de descendre.', 'Une ouverture même partielle peut surprendre le cycliste ou empiéter sur sa trajectoire.')],
 'Attendre l’immobilisation sûre': [('Déverrouiller le coffre pendant la fin de la manœuvre pour gagner du temps.', 'Le chargement et la dépose se préparent une fois l’immobilisation sûre acquise.'), ('Laisser le passager se détacher pendant les derniers mètres.', 'Le véhicule est encore en mouvement ; la retenue doit être conservée jusqu’à l’arrêt sûr.')],
 'Rechercher un autre lieu autorisé et expliquer': [('Choisir le lieu le plus proche sans contrôler les restrictions d’arrêt.', 'La proximité ne suffit pas à rendre la dépose autorisée et sûre.'), ('Conserver le point initial et demander au client de traverser l’obstacle.', 'Un point devenu inaccessible appelle une réorganisation, pas une exposition du client à un obstacle.')],
 'Proposer de vérifier une source officielle à l’arrêt': [('Donner l’horaire mémorisé lors de la dernière visite comme celui d’aujourd’hui.', 'Un horaire passé peut avoir changé ; le présenter comme actuel transforme un souvenir en information non vérifiée.'), ('Utiliser le premier extrait trouvé sans regarder sa date.', 'Une réponse de recherche peut reproduire un horaire ancien ; la date et la source sont nécessaires.')],
 'Présenter cela comme un avis et vérifier la disponibilité si nécessaire': [('Présenter son appréciation personnelle comme une recommandation officielle.', 'Une préférence personnelle peut être utile, mais ne doit pas être présentée comme un classement objectif ou officiel.'), ('Déduire la disponibilité d’une table du nombre de places dans la salle.', 'La capacité totale ne tient pas compte des réservations ni de l’occupation au moment souhaité.')],
 'Reporter la recherche à une phase sûre': [('Ouvrir le site au feu suivant sans vérifier si la circulation demande encore votre attention.', 'Un arrêt dans la circulation n’est pas une phase de stationnement permettant toute recherche.'), ('Demander au client de lire à voix haute les résultats pendant la manœuvre.', 'L’écoute et la sélection de résultats peuvent encore mobiliser l’attention dans une phase complexe.')],
 'Confirmer le lieu exact avec le client': [('Retenir celui qui correspond à la prononciation la plus proche.', 'Une ressemblance de noms n’identifie pas la destination ; une confirmation reste nécessaire.'), ('Suivre le résultat le plus fréquent de la navigation.', 'La fréquence d’un résultat ne prouve pas qu’il correspond au lieu demandé par ce client.')],
 'Informer avec une estimation actualisée et rechercher les options': [('Annoncer le temps habituel du détour sans intégrer les conditions présentes.', 'Une estimation utile doit tenir compte de la fermeture et des conditions actualisées.'), ('Proposer une alternative comme acquise avant de vérifier sa disponibilité.', 'Une option envisagée doit rester distincte d’une solution confirmée.')],
 'Le présenter comme une option à confirmer': [('Donner au client un horaire ferme sur la base de la disponibilité habituelle du collègue.', 'Une habitude ne confirme ni le véhicule ni son heure d’arrivée pour cette mission.'), ('Annuler immédiatement la solution actuelle avant d’avoir confirmé l’alternative.', 'L’alternative n’est pas encore acquise ; supprimer la solution existante peut laisser le client sans transport.')],
 'Confirmer le nouveau service et ses conditions': [('Conserver uniquement le prix initial sans noter le nouveau périmètre.', 'L’accord doit préciser la modification réellement acceptée ; le prix seul ne décrit pas le service.'), ('Considérer un accord sur le trajet comme un accord automatique sur tout supplément.', 'Le périmètre et ses conséquences tarifaires doivent être compris ; un accord partiel n’autorise pas toute facturation.')],
 'Mobiliser le bon interlocuteur': [('Appliquer de mémoire le geste commercial accordé à un autre client.', 'Une décision antérieure ne donne pas une habilitation générale ni la même solution pour ce dossier.'), ('Attendre la prochaine réunion sans donner au client de délai de réponse.', 'Une transmission utile doit aussi organiser un suivi et un délai réaliste.')],
 'Vérifier avant toute nouvelle tentative': [('Relancer le même montant dès qu’aucun ticket n’est imprimé.', 'L’absence de ticket ne prouve pas l’absence de débit ; une nouvelle tentative peut créer un doublon.'), ('Conclure que le paiement est reçu parce que la carte a été présentée.', 'La présentation de la carte ne confirme pas l’acceptation et l’aboutissement du paiement.')],
 'Vérifier les conditions convenues et traiter l’écart': [('Maintenir le supplément parce que le terminal affiche ce total.', 'Le montant saisi ne prouve pas que le supplément a été accepté.'), ('Rembourser toute la course sans examiner la prestation réellement réalisée.', 'Il faut identifier l’écart et la solution proportionnée ; un remboursement intégral n’est pas automatiquement justifié.')],
 'Reporter le paiement à l’arrêt en sécurité': [('Préparer seulement le montant en roulant puis tendre le terminal à l’arrêt.', 'La saisie du montant mobilise déjà l’attention ; la préparation fait partie de l’opération à réaliser à l’arrêt sûr.'), ('Poser le terminal près du volant pour limiter le temps de regard.', 'Rapprocher l’écran ne supprime pas les manipulations ni la distraction.')],
 'Utiliser la procédure traçable de l’entreprise': [('Renvoyer une facture modifiée sous le même numéro sans conserver l’historique.', 'Une correction sans trace ne permet plus de reconstituer ce qui a été émis et modifié.'), ('Ajouter une note privée dans le planning sans corriger la pièce remise au client.', 'La traçabilité doit concerner aussi le document comptable et le client, pas seulement le planning interne.')],
 'Vérifier la mission concernée et organiser une remise sécurisée': [('Remettre le téléphone à la première personne qui en décrit la couleur.', 'Une caractéristique courante ne suffit pas à identifier le propriétaire.'), ('Appeler tous les clients récents en leur communiquant le contenu visible de l’appareil.', 'La recherche du propriétaire doit limiter les informations divulguées et cibler les vérifications utiles.')],
 'Évaluer et traiter la situation avant de promettre le départ': [('Confirmer l’heure puis expliquer le défaut seulement lorsque le client monte.', 'La confirmation doit tenir compte du temps nécessaire pour remettre le véhicule en état.'), ('Traiter uniquement ce qui apparaît sur une photo envoyée au client.', 'Une présentation visuelle ne remplace pas la vérification réelle du confort, de l’hygiène et de la sécurité.')],
 'Respecter les règles de retour ou de stationnement': [('Rester sur la chaussée en attente d’un appel annoncé mais non confirmé.', 'Une intention de rappel ne prouve pas une réservation et ne crée pas un droit d’attente commerciale.'), ('Utiliser la zone de dépose comme stationnement jusqu’à la prochaine course.', 'Une zone de dépose ne constitue pas nécessairement un lieu d’attente autorisé.')],
 'Vérifier avec lui la restitution complète': [('Compter seulement le nombre de bagages sans vérifier à qui ils appartiennent.', 'Le bon nombre n’exclut pas une confusion entre objets similaires.'), ('Remettre les bagages les plus proches de l’ouverture sans confirmation.', 'L’ordre de chargement ne permet pas d’identifier le propriétaire ; la restitution doit être vérifiée avec le client.')],
 'Il doit corriger la conduite ; les qualités commerciales ne compensent pas tout': [('Viser davantage de points commerciaux en conservant le même risque de conduite.', 'Un risque éliminatoire ne se compense pas par une meilleure relation client.'), ('Travailler uniquement le parcours pour réduire le temps passé en circulation.', 'Réduire la durée ne corrige pas le comportement dangereux ; il faut traiter la compétence de conduite concernée.')],
 'Il doit encore s’entraîner en circulation avec un formateur': [('Passer directement à une évaluation finale sans observer les gestes en circulation.', 'Un résultat sur écran ne mesure pas l’exécution réelle des contrôles et manœuvres.'), ('Remplacer les séances pratiques par davantage de séries identiques.', 'Des réponses mémorisées ne prouvent pas le transfert à la conduite réelle.')],
 'Prévoir un entraînement ciblé et un nouveau retour': [('Refaire un parcours complet sans critère précis d’observation.', 'Sans objectif ciblé, il sera difficile de vérifier si le contrôle visuel signalé s’améliore.'), ('Apprendre une phrase annonçant le contrôle sans vérifier le geste.', 'Dire que le contrôle est fait ne prouve pas que le regard et la prise d’information ont été réalisés.')],
 'Revenir au dossier et aux critères demandés': [('Préparer le trajet habituel du quartier avant de lire les contraintes de la commande.', 'La connaissance locale ne donne pas les besoins et contraintes de cette mission.'), ('Privilégier les lieux touristiques connus même s’ils modifient l’arrivée demandée.', 'L’information touristique reste au service de la mission acceptée ; elle ne remplace pas les contraintes du client.')],
 'Relire le raisonnement puis résoudre une variante': [('Relancer aussitôt la même question en mémorisant la position de la réponse.', 'Retenir une position ne prouve pas la compréhension du raisonnement.'), ('Passer à un autre thème parce que le dernier essai était correct.', 'Une réussite après tâtonnement ne montre pas que la compétence est acquise sans les indices précédents.')],
 'Identifier la base et reprendre des exercices ciblés': [('Répéter le calcul avec de plus grands nombres sans identifier la confusion.', 'Changer les nombres ne corrige pas une erreur sur la base ou le périmètre.'), ('Retenir le résultat de l’exemple pour le réutiliser dans le cas suivant.', 'Le résultat dépend des données ; c’est la méthode qu’il faut transférer.')],
 'Commencer la révision par ces contrôles': [('Répartir le temps également entre tous les thèmes, y compris ceux déjà maîtrisés.', 'Le bilan révèle une priorité ; une répartition uniforme peut laisser trop peu de travail sur la difficulté observée.'), ('Refaire uniquement les calculs de tarif pour améliorer rapidement le score global.', 'Un meilleur score ailleurs ne corrige pas les erreurs documentaires identifiées.')],
 'Vérifier le transfert en préparation et en conduite encadrée': [('Conclure à la maîtrise des manœuvres parce que le trajet sur écran est correct.', 'La préparation d’itinéraire et l’exécution en circulation sont deux compétences distinctes.'), ('Réutiliser le même trajet sans modifier les contraintes ni demander d’observation.', 'La répétition du même cas ne permet pas de vérifier l’adaptation à une mission différente.')],
})


CHOICES.update({
 'Publier ses coordonnées pour le dénoncer': ('Transmettre les captures dans un groupe professionnel ouvert pour demander un avis.', 'Une diffusion large expose les données et peut aggraver la situation ; conserver les éléments pour les canaux appropriés est préférable.'),
 'Publier son récit avec son identité': ('Partager son récit avec des partenaires avant de lui expliquer les démarches.', 'L’accompagnement demande de préserver la confidentialité et d’associer la personne aux démarches utiles.'),
 'Lui demander pourquoi elle était seule': ('Commencer par vérifier si son comportement a favorisé la situation.', 'Cette approche culpabilise la personne et retarde l’écoute et la protection demandées.'),
 'Les publier avec le numéro de téléphone': ('Les transférer à tous les collègues sans limiter les destinataires.', 'Les éléments doivent être conservés et transmis aux interlocuteurs utiles, pas diffusés à tout un réseau.'),
 'Commencer par publier une vidéo': ('Attendre une confirmation commerciale de la plateforme avant d’alerter les secours.', 'Une agression immédiate demande une alerte adaptée sans attendre une procédure commerciale.'),
 'Publier le numéro et le contenu sur les réseaux': ('Répondre longuement pour convaincre l’auteur, sans conserver les messages.', 'Il faut préserver les éléments utiles et sa sécurité ; prolonger l’échange ne remplace pas le signalement.'),
 'Continuer sans rien faire pour conserver la note': ('Attendre la fin de la course avant de poser une limite pour éviter une réclamation.', 'Un contact imposé doit être traité en préservant immédiatement la sécurité ; la notation ne justifie pas de différer la protection.'),
 'S’arrêter immédiatement sur la trajectoire des véhicules': ('S’arrêter à l’endroit le plus proche sans examiner son exposition à la circulation.', 'Un arrêt mal choisi peut ajouter un risque ; la recherche d’un lieu sûr fait partie de la première décision.'),
 'Placer obligatoirement le chien dans le coffre': ('Demander un transport en cage comme condition systématique.', 'Une condition automatique ne tient pas compte du droit d’accès et du rôle du chien d’assistance auprès du passager.'),
 'Le mettre obligatoirement dans le coffre': ('Exiger qu’un accompagnateur s’occupe du chien à la place de la passagère.', 'La présence d’un chien d’assistance ne justifie pas d’imposer un accompagnateur ; il faut organiser l’installation avec la personne.'),
 'La soulever immédiatement': ('Commencer le transfert dès que la portière est ouverte sans demander la méthode souhaitée.', 'La personne connaît ses besoins ; un transfert non convenu peut la déséquilibrer ou ne pas correspondre à ses capacités.'),
 'Crier sans reformuler': ('Augmenter le volume de voix sans se placer face à la personne.', 'La difficulté de communication peut demander des repères visuels ou un message écrit plutôt qu’un volume plus élevé.'),
 'Refuser toutes les personnes handicapées à l’avenir': ('Classer toute future demande avec fauteuil comme techniquement impossible.', 'Un fauteuil plié et un passager restant dans son fauteuil présentent des contraintes différentes ; il faut examiner chaque besoin.'),
 'Publier son hôtel sur un réseau social': ('Utiliser ses coordonnées pour une offre commerciale avant d’organiser la restitution.', 'La coordonnée peut servir au traitement de l’objet oublié ; une réutilisation commerciale relève d’une autre finalité.'),
 'Menacer de publier les informations de l’agent': ('Débattre de la contestation au lieu de présenter les pièces demandées.', 'La contestation suit une voie adaptée ; elle ne dispense pas de coopérer au contrôle dans son cadre.'),
 'Regarder seulement le GPS': ('Conserver l’allure habituelle parce que le passage figure sur la carte.', 'La carte ne renseigne pas sur le piéton éventuellement masqué par le véhicule au moment de l’approche.'),
 'Supprimer les repas pour gagner du temps': ('Enchaîner les courses en comptant les attentes dans la circulation comme des pauses.', 'Ces attentes demandent encore de la vigilance et ne remplacent pas des temps de récupération organisés.'),
 'Réparer immédiatement au milieu de la circulation': ('Commencer le diagnostic mécanique avant de protéger les occupants exposés.', 'Le diagnostic et la continuité du service viennent après la protection contre le suraccident.'),
 'Changer seulement le nom du dossier': ('Accorder le même geste commercial à chaque occurrence sans analyser la cause.', 'Répéter une compensation ne corrige pas l’origine du problème et laisse de futurs clients exposés.'),
 'Ignorer les réclamations suivantes': ('Classer séparément chaque réclamation sans rapprocher les incidents similaires.', 'Le rapprochement permet d’identifier un défaut récurrent du processus.'),
 'Le nombre de photos publiées': ('Le nombre total de courses, sans relever leurs horaires de prise en charge.', 'La ponctualité nécessite un critère de retard et des horaires ; un volume d’activité ne la mesure pas.'),
 'En changeant seulement l’adresse du client': ('Reporter la correction sur la prochaine facture sans la relier à celle qui est erronée.', 'Le lien avec la pièce initiale permet d’expliquer et de vérifier la rectification.'),
 'Seulement le prix du carburant': ('Le seul prix du véhicule, sans examiner sa propriété ou son contrat de location.', 'La capacité financière dépend notamment de la situation de détention ; le prix ne suffit pas à décider.'),
 'L’heure du nettoyage et celle du plein seulement': ('L’heure d’édition du justificatif et l’heure de paiement.', 'Ces événements ne se confondent pas avec la commande réelle et la prise en charge demandée.'),
 'Seulement sa propreté': ('Sa catégorie commerciale et le niveau de confort indiqué par le loueur.', 'La conformité et les garanties du véhicule ne se déduisent pas de sa catégorie commerciale.'),
 'Seulement le titre du texte': ('La date de publication sans lire le calendrier d’application.', 'La publication et l’entrée en vigueur peuvent différer ; les dispositions transitoires peuvent aussi compter.'),
 'Choisir au hasard': ('Retenir l’entrée utilisée lors de la course précédente.', 'Une habitude ne confirme pas l’entrée convenue pour cette réservation.'),
 'Demander au client d’ignorer le panneau': ('Considérer l’adresse demandée par le client comme une autorisation d’accès.', 'Une destination ne donne pas le droit d’emprunter une voie interdite au véhicule.'),
 'Seulement la température extérieure': ('La destination saisie au GPS sans contrôler la liberté des commandes.', 'La navigation ne remplace pas la préparation physique du poste de conduite.'),
 'Seulement la playlist': ('Le réglage du siège conservé par le conducteur précédent.', 'Une position adaptée à quelqu’un d’autre peut gêner l’accès aux commandes et la visibilité du conducteur actuel.'),
 'Se pencher immédiatement sous le volant': ('Pousser le téléphone avec le pied tout en poursuivant le trajet.', 'Manipuler un objet près des pédales en roulant peut gêner les commandes ; il faut rejoindre un arrêt sûr.'),
 'En annonçant publiquement toutes ses coordonnées': ('En demandant seulement de confirmer un prénom pouvant être partagé par plusieurs voyageurs.', 'Une information croisée doit permettre de distinguer le bon client avec discrétion.'),
 'Seulement le montant payé': ('Uniquement que le véhicule est immobile, sans observer la circulation latérale.', 'L’immobilisation ne supprime pas le risque d’un cycliste ou véhicule approchant de la portière.'),
 'Inventer un horaire plausible': ('Présenter l’horaire d’une visite passée comme celui d’aujourd’hui.', 'Le souvenir peut être périmé ; il faut vérifier la source et la date avant d’affirmer un horaire actuel.'),
 'Publier immédiatement son contenu en ligne': ('Confier l’objet à un proche du client sans confirmer son autorisation.', 'La restitution doit vérifier l’identité ou l’autorisation de la personne qui reçoit l’objet.'),
 'Au seul numéro du permis': ('Au prix standard d’un trajet similaire, sans reprendre les conditions de la mission.', 'La facture doit correspondre à la prestation et aux conditions effectivement retenues.'),
 'À un ancien trajet choisi au hasard': ('Au devis initial sans intégrer une modification réellement convenue.', 'Une modification acceptée et réalisée doit être prise en compte de manière cohérente dans la facture.'),
 'Supprimer toutes les preuves de prestation': ('Clore le dossier sans rapprocher le règlement et la facture.', 'La clôture doit conserver des pièces cohérentes et distinguer facturation et paiement reçu.'),
 'Considérer qu’un sourire vaut paiement': ('Considérer la facture émise comme la preuve que le paiement a abouti.', 'L’émission d’une facture ne confirme pas l’encaissement ; le statut du règlement doit être vérifié.'),
 'Changer toutes les habitudes au hasard': ('Multiplier les parcours sans fixer de critère précis à observer.', 'Un objectif ciblé et un nouveau retour permettent de vérifier la progression sur la difficulté identifiée.'),
 'Seulement la couleur de la voiture': ('Seulement le confort du véhicule, sans vérifier la capacité et les équipements nécessaires.', 'Un niveau de confort ne prouve pas que les personnes et leurs effets peuvent être transportés correctement.'),
 'Effacer les horaires enregistrés': ('Retenir uniquement l’horaire annoncé, sans le rapprocher des événements réels.', 'Le traitement de la réclamation exige une chronologie fondée sur les éléments disponibles.'),
 'Publier son contenu et les données du client': ('Remettre l’objet à la personne qui se présente sans vérifier le lien avec la mission.', 'La proximité du lieu de dépose ne suffit pas à identifier le propriétaire.'),
 'Envoyer seulement des excuses identiques à chaque course': ('Maintenir l’organisation actuelle tout en accordant un geste commercial répétitif.', 'Une compensation peut traiter un cas, mais ne corrige pas la cause d’un incident récurrent.'),
})


def _add_section(lesson, title, paragraphs, source_keys):
    if not any(p.get('kind') == 'heading' and p.get('text') == title for p in lesson['paragraphs']):
        lesson['paragraphs'].append({'kind': 'heading', 'text': title})
        lesson['paragraphs'].extend({'kind': 'paragraph', 'text': p} for p in paragraphs)
    links = lesson.setdefault('reviewed_sources', [])
    for key in source_keys:
        title_, url = SOURCES[key]
        item = {'title': title_, 'url': url, 'checked_on': REVIEWED_ON}
        if item not in links:
            links.append(item)


def _lesson_changes(v):
    ref = v['ref']
    if ref == 'A.06':
        _add_section(v, 'Les sanctions et les interlocuteurs', [
            'L’article 225-2 du Code pénal prévoit jusqu’à trois ans d’emprisonnement et 45 000 € d’amende pour les discriminations qu’il vise, notamment un refus discriminatoire de fournir un bien ou un service. Le refus visé au 1° commis dans un lieu accueillant du public ou pour en interdire l’accès porte les peines à cinq ans et 75 000 €. Il faut identifier les faits et la qualification applicable : ces plafonds ne sont ni une amende automatique pour toute difficulté de service ni les sanctions de la maraude VTC.',
            'Une personne victime ou témoin peut contacter les juristes du Défenseur des droits au 3928 ou sur antidiscriminations.fr pour être écoutée et accompagnée. La saisine ne remplace pas une plainte auprès de la police ou de la gendarmerie et ne constitue pas un appel d’urgence. Conservez les éléments utiles : message de refus, date, prestation demandée, motif donné et témoins, sans les publier.',
            'Exemple : un hôtel demande d’écarter une cliente à cause de son origine supposée. Le chauffeur refuse cette consigne, conserve le message utile et maintient des critères de service identiques. À l’inverse, un nombre de voyageurs supérieur aux places disponibles demande une autre organisation ; cette contrainte n’autorise pas un refus général envers un groupe de personnes.'
        ], ['discrimination', 'criteria', 'defender'])
    if ref == 'A.07':
        v['deepening']['example'] = 'Un passager menace de publier un mauvais avis si la conductrice refuse de le revoir dans un cadre intime. Elle pose une limite, préserve sa sécurité, garde les messages utiles et utilise les canaux de signalement ; elle ne négocie pas son consentement contre une note.'
        _add_section(v, 'Distinguer les comportements pour réagir', [
            'L’outrage sexiste ou sexuel concerne des propos ou comportements imposés, humiliants ou créant une situation intimidante, hostile ou offensante. Il peut être constitué sans répétition. Le harcèlement sexuel vise notamment des propos ou comportements répétés ; une pression grave pour obtenir un acte sexuel peut aussi suffire même si elle est unique. La répétition peut, dans les conditions de l’article 222-33, résulter de plusieurs auteurs.',
            'L’agression sexuelle suppose un acte sexuel non consenti, et ne se limite donc pas à des paroles. Les agressions autres que le viol peuvent notamment prendre la forme d’attouchements imposés. Le viol vise les actes de pénétration sexuelle, bucco-génitaux ou bucco-anaux dans les conditions prévues par la loi ; les articles 222-22 et 222-23 doivent être lus ensemble. Des règles particulières protègent aussi les mineurs. Le chauffeur décrit les faits sans imposer sa propre qualification juridique à la victime.',
            'Le consentement doit être libre, éclairé, spécifique, préalable et révocable. Accepter une aide pour attacher un bagage ou une ceinture n’autorise pas un contact sexuel. Le silence, l’absence de réaction, un trajet payé ou une conversation aimable ne suffisent pas à établir un consentement. La première action reste de protéger, d’interrompre le comportement dans des conditions sûres et d’alerter selon l’urgence, comme en A.08.'
        ], ['outrage', 'harassment', 'consent', 'rape'])
    if ref == 'B.01':
        v['deepening']['paragraphs'] = [p.replace('La micro-entreprise est un régime simplifié de l’entreprise individuelle, pas une société comparable à une SASU.', 'Le régime micro est un régime simplifié, notamment utilisé en entreprise individuelle et accessible à certaines EURL sous conditions ; ce n’est pas une forme de société comparable à une SASU.') for p in v['deepening']['paragraphs']]
        v['visual_table'] = {
            'title': 'Trois cadres pour entreprendre seul',
            'headers': ['Critère', 'Entreprise individuelle', 'EURL', 'SASU'],
            'rows': [
                ['Qui exerce ?', 'L’entrepreneur en nom propre', 'Une société distincte', 'Une société distincte'],
                ['Associés au départ', 'Pas de capital partagé avec des associés', 'Un associé unique', 'Un associé unique'],
                ['Dirigeant du cas étudié', 'Entrepreneur indépendant', 'Gérant associé unique : indépendant', 'Président rémunéré : assimilé salarié'],
                ['Choix à étudier séparément', 'Régime fiscal, TVA, frais et protection', 'Fiscalité, rémunération, frais et protection', 'Fiscalité, rémunération, frais et protection'],
            ],
            'note': 'Le tableau distingue des cadres, sans désigner le meilleur pour tous. Le régime micro n’est pas une forme juridique. Un mandat assimilé salarié n’est pas à lui seul un contrat de travail ni une assurance chômage.',
        }
        _add_section(v, 'Comparer les structures avec le même projet', [
            'Pour travailler seul, comparez l’entreprise individuelle et les sociétés unipersonnelles EURL ou SASU. Une EI ne crée pas une personne morale distincte ; EURL et SASU sont des sociétés avec statuts et formalités propres. Le régime micro est une modalité fiscale et sociale soumise à conditions, pas une troisième forme de société ; certaines EURL peuvent également y être éligibles. Dépasser un seuil ne transforme donc pas automatiquement l’entreprise en SASU.',
            'Le dirigeant associé unique d’une EURL relève normalement du régime des indépendants. Le président de SASU rémunéré pour son mandat relève du régime général comme assimilé salarié ; ce mandat n’ouvre pas à lui seul les droits d’un contrat de travail ni l’assurance chômage. Pour comparer, précisez la rémunération, les frais, les cotisations et la protection recherchée avant de conclure sur le revenu disponible.',
            'Méthode : partez du même chiffre d’affaires et des mêmes dépenses ; séparez les frais réellement payés, les bases fiscales et sociales et la trésorerie. Comparez ensuite formalités, rémunération, protection sociale et projet d’association. Une activité à frais élevés demande d’étudier la déduction des charges au régime réel ; cela ne suffit pas, isolément, à désigner la meilleure structure. Faites chiffrer les options avec les règles applicables à votre situation.'
        ], ['structure', 'eurl'])
    if ref in G_DEEPENING:
        ps = v.get('deepening', {}).get('paragraphs', [])
        v['deepening']['paragraphs'] = [G_DEEPENING[ref] if p.startswith('Le bon réflexe consiste à vérifier les informations qui peuvent changer') else p for p in ps]


def _question(ref, id_, context, prompt, correct, errors, explanation, documents=None):
    opts = [('a', correct), ('b', errors[0][0]), ('c', errors[1][0])]
    shift = int(hashlib.sha256(id_.encode()).hexdigest()[:4], 16) % 3
    opts = opts[shift:] + opts[:shift]
    new_ids = {old: chr(97+i) for i, (old, _) in enumerate(opts)}
    outcomes = {'a': explanation, 'b': errors[0][1], 'c': errors[1][1]}
    q = {'id': id_, 'kind': 'single', 'competency': ref, 'context': context, 'stage': 'Comparer et justifier',
         'prompt': prompt, 'options': [{'id': new_ids[k], 'text': t} for k, t in opts], 'answer': new_ids['a'],
         'explanation': explanation, 'coaching': explanation,
         'consequences': {new_ids[k]: rationale for k, rationale in outcomes.items()},
         'revision': REVISION}
    if documents:
        q['documents'] = copy.deepcopy(documents)
    return q


def _b01_cases():
    ref = 'B.01'
    def q(n, context, prompt, correct, e1, why1, e2, why2, explanation, documents=None):
        return _question(ref, f'v6-b01-{n:02}', context, prompt, correct, [(e1, why1), (e2, why2)], explanation, documents)
    docs = [{'title': 'Deux projets sur une année · données fictives', 'rows': [
        ['Chiffre d’affaires encaissé de chaque projet', '48 000 €'],
        ['Projet direct : véhicule, énergie, entretien et autres frais', '15 000 €'],
        ['Projet avec location et plateforme : mêmes postes + commissions', '29 000 €'],
        ['Périmètre du calcul demandé', 'Avant cotisations personnelles, impôts et frais de structure non indiqués'],
    ]}]
    return [
      q(1, 'Lina entreprend seule. Elle souhaite créer une personne morale distincte de sa personne et ne prévoit pas encore d’associé.', 'Quel ensemble de formes répond à ces deux critères ?', 'EURL ou SASU.', 'EI au réel ou EI au régime micro.', 'Le choix fiscal ne transforme pas l’EI en une personne morale distincte.', 'SASU ou régime micro, considérés comme deux sociétés.', 'Le régime micro n’est pas une forme de société ; il faut d’abord identifier la structure juridique.', 'EURL et SASU sont des sociétés à associé unique. L’EI exerce en nom propre. Ces seuls critères permettent de retenir un ensemble de formes, pas de choisir définitivement entre EURL et SASU.'),
      q(2, 'Lina compare une EURL dont elle serait gérante associée unique et une SASU dont elle serait présidente rémunérée pour son mandat.', 'Quelle comparaison du régime social est correcte dans ces situations ?', 'Gérante associée d’EURL : indépendante ; présidente rémunérée de SASU : assimilée salariée.', 'Les deux mandats entraînent automatiquement un contrat de travail.', 'Un mandat de direction n’est pas, à lui seul, un contrat de travail.', 'La SASU ne donne un régime social au président que lorsqu’un second associé entre.', 'Le statut social décrit dépend du mandat rémunéré ; il ne nécessite pas un second associé.', 'La gérante associée unique relève normalement du régime des indépendants. Le président de SASU rémunéré au titre de son mandat est assimilé salarié ; cela ne lui confère pas automatiquement l’assurance chômage.'),
      q(3, 'Une fiche compare deux projets ayant les mêmes recettes, mais des dépenses différentes. Ne calculez ici que ce qui reste après les frais indiqués.', 'Quelle comparaison respecte le périmètre du document ?', '33 000 € pour le projet direct et 19 000 € pour le projet avec location et plateforme.', '48 000 € dans chaque cas, puisque le chiffre d’affaires est identique.', 'Le chiffre d’affaires ne retranche pas les frais réellement payés ; il masque ici un écart de 14 000 €.', '33 000 € et 19 000 € de salaires nets garantis.', 'Les soustractions sont exactes, mais les cotisations, impôts et frais non indiqués restent à traiter : ce ne sont pas des salaires nets.', '48 000 − 15 000 = 33 000 € ; 48 000 − 29 000 = 19 000 €. L’écart de frais est de 14 000 €. Ces montants intermédiaires ne permettent pas de désigner le statut le plus avantageux sans les autres éléments.', docs),
      q(4, 'Le projet avec location supporte 29 000 € de frais. Son porteur pense que l’abattement fiscal du régime micro remboursera ces dépenses.', 'Quelle correction de raisonnement faut-il retenir ?', 'L’abattement intervient dans un calcul fiscal ; les dépenses restent payées par l’entreprise.', 'Les frais du véhicule peuvent être soustraits librement du chiffre d’affaires micro déclaré.', 'Au régime micro, les dépenses réelles ne se déduisent pas librement de la base de chiffre d’affaires déclarée.', 'Le montant de l’abattement est versé sur le compte bancaire après la déclaration.', 'Un abattement n’est pas une somme remboursée ; il ne finance pas les paiements du véhicule.', 'Il faut séparer base fiscale et trésorerie. Des dépenses élevées justifient une comparaison chiffrée avec le régime réel, mais ne suffisent pas à annoncer automatiquement un gain ni une structure idéale.'),
      q(5, 'Un partenaire souhaite entrer au capital de l’entreprise dès sa création. Les deux personnes veulent partager les décisions et les résultats.', 'Quelle évolution du projet faut-il étudier ?', 'Une forme de société à plusieurs associés, par exemple SAS ou SARL, et ses règles de gouvernance.', 'Une EI avec deux entrepreneurs inscrits comme associés au même capital.', 'Une EI n’a pas le capital social ni les associés d’une société ; cette proposition ne répond pas au projet.', 'Une SASU en conservant deux associés sans changer sa configuration juridique.', 'La SASU est une société par actions simplifiée à associé unique ; l’arrivée d’un deuxième associé modifie cette configuration.', 'La présence d’associés est un critère structurant. Il faut définir apports, décisions, rémunération et sortie éventuelle au lieu de choisir uniquement à partir d’un taux de cotisations.'),
      q(6, 'Un entrepreneur quitte le régime micro mais souhaite continuer seul avec la même activité. Aucun associé ni changement de personne morale n’est décidé.', 'Quelle affirmation évite de confondre régime et forme ?', 'Le changement de régime ne crée pas automatiquement une SASU.', 'Le dépassement transforme l’EI en SASU dès le premier euro supplémentaire.', 'Un seuil de régime et la constitution d’une société sont deux mécanismes différents ; une société demande ses propres formalités.', 'Le passage à un régime réel implique toujours de prendre un associé.', 'Un régime réel peut concerner une activité exercée seul ; il ne suppose pas l’entrée d’un associé.', 'Il faut vérifier les conditions et dates du changement de régime, puis décider séparément si une transformation du cadre juridique est utile. Il n’existe pas de conversion automatique en SASU sur cette seule base.'),
      q(7, 'Deux simulations comparent une EI et une SASU. L’une utilise 48 000 € de recettes hors taxe ; l’autre 48 000 € TTC avec une TVA donnée de 10 %. Les autres postes sont annoncés identiques.', 'Quel défaut doit être corrigé avant de comparer le revenu ?', 'Ramener les recettes sur une base identique avant de comparer les autres postes.', 'Choisir la simulation ayant le plus grand montant affiché.', 'Les montants n’ont pas la même base ; leur valeur affichée ne permet pas une comparaison directe.', 'Ajouter les charges de l’EI au TTC de la SASU pour neutraliser la différence.', 'Additionner des dépenses ne remet pas les recettes sur la même base et fausse encore la comparaison.', 'Dans l’hypothèse donnée, 48 000 € TTC ÷ 1,10 ≈ 43 636,36 € HT. Il faut comparer le même niveau de recettes, puis les frais, cotisations, impôts et protections. Le taux indiqué sert seulement à ce calcul.'),
    ]


def _sensitive_cases(ref):
    questions = []
    if ref == 'A.06':
        questions = [
          _question(ref, 'v6-a06-sanctions', 'On examine les peines de base prévues par l’article 225-2 pour un refus discriminatoire de service. La question ne retient pas le cas aggravé du refus dans un lieu accueillant du public ou pour en interdire l’accès.', 'Quels plafonds de peine correspondent à ce cadre de base ?', 'Trois ans d’emprisonnement et 45 000 € d’amende.', [('Cinq ans d’emprisonnement et 75 000 € d’amende dans tous les cas.', 'Ce second couple concerne le refus aggravé précisé par le texte ; il ne faut pas confondre cadre de base et aggravation.'), ('Une indemnisation civile seulement si le client a été remboursé.', 'Un remboursement commercial ne supprime pas à lui seul la dimension pénale du refus discriminatoire.')], 'L’article 225-2 prévoit trois ans et 45 000 € dans le cadre de base. Il prévoit cinq ans et 75 000 € pour le refus aggravé qu’il décrit. La qualification dépend des faits ; une peine maximale n’est pas une condamnation automatique.'),
          _question(ref, 'v6-a06-orientation', 'Un client rapporte un refus de service fondé sur son origine supposée. Il n’y a pas de danger immédiat. Il souhaite connaître ses droits et être accompagné par un acteur spécialisé dans les discriminations.', 'Quelle orientation correspond à cette demande ?', 'Le Défenseur des droits, notamment au 3928 ou sur antidiscriminations.fr.', [('Le 3919 comme service spécialisé dans tous les litiges de transport.', 'Le 3919 concerne les violences faites aux femmes ; il n’est pas un service général des discriminations ou des litiges de transport.'), ('L’assureur automobile comme autorité chargée de qualifier et sanctionner la discrimination.', 'L’assureur examine les garanties ; il ne remplace ni l’accompagnement du Défenseur des droits ni les autorités pénales.')], 'Le Défenseur des droits écoute et accompagne les personnes victimes ou témoins de discrimination. Cette démarche ne remplace pas un appel d’urgence ou, selon la situation, une plainte. Conserver les messages et les faits aide au traitement.'),
        ]
    if ref == 'A.07':
        questions = [
          _question(ref, 'v6-a07-distinctions', 'Dans une formation, quatre notions sont rapprochées : outrage sexiste ou sexuel, harcèlement sexuel, autres agressions sexuelles et viol.', 'Quelle distinction est correcte ?', 'Des paroles imposées peuvent relever de l’outrage ou du harcèlement ; un acte sexuel non consenti relève des agressions sexuelles, avec la qualification de viol pour les actes visés par la loi.', [('Sans répétition, aucun propos sexuel imposé ne peut constituer une infraction.', 'L’outrage n’exige pas une répétition ; une pression grave pour obtenir un acte sexuel peut également relever du harcèlement même unique.'), ('Toute remarque sexiste relève du viol dès que la personne reste silencieuse.', 'Le silence ne vaut pas consentement, mais il ne transforme pas une parole en l’acte visé par la définition du viol.')], 'Il faut distinguer nature des faits, répétition ou pression grave et présence d’un acte sexuel non consenti. Le viol concerne notamment pénétration et actes bucco-génitaux ou bucco-anaux dans le cadre légal. Face à un récit, le chauffeur protège et décrit les faits sans imposer une qualification à la victime.'),
        ]
    for q in questions:
        q['required_core'] = True
        keys = ['discrimination'] if q['id'].endswith('sanctions') else ['defender'] if q['id'].endswith('orientation') else ['outrage', 'harassment', 'consent', 'rape']
        q['sources'] = [list(SOURCES[k]) for k in keys]
    return questions


def _exercises(value):
    if isinstance(value, dict):
        if value.get('kind') in ('single', 'multiple', 'sort', 'matching', 'order') and value.get('prompt') and value.get('options'):
            yield value
            return
        for key, child in value.items():
            if key not in ('annales_notes', 'content_revision'):
                yield from _exercises(child)
    elif isinstance(value, list):
        for child in value:
            yield from _exercises(child)


def _revise_question(q, fallback_ref, text_updates):
    if q.get('kind') != 'single' or 'answer' not in q:
        return False
    ref = q.get('competency') or fallback_ref or ''
    correct = next((o['text'] for o in q['options'] if o['id'] == q['answer']), None)
    if correct is None:
        raise ValueError(f"Missing answer in {q.get('id')}")
    wrong = [o for o in q['options'] if o['id'] != q['answer']]
    changes = []
    if ref[:1] in ('C', 'H') and correct in DECISIONS and len(wrong) == 2:
        for option, (replacement, reason) in zip(wrong, DECISIONS[correct]):
            changes.append((option, replacement, reason))
    else:
        for option in wrong:
            if option['text'] in CHOICES:
                replacement, reason = CHOICES[option['text']]
                if option['text'] == 'La couleur du véhicule' and ref.startswith('F.'):
                    replacement = 'Le nombre de courses, sans leur durée ni leurs coûts.'
                    reason = 'Un nombre de courses ne mesure pas le temps mobilisé ni la contribution laissée par chacune.'
                changes.append((option, replacement, reason))
            # Make duration misunderstandings plausible without touching recordings.
            elif ref.startswith('E.') and re.fullmatch(r'Exactement \d+ minutes garanties', option['text']):
                changes.append((option, option['text'].replace('Exactement ', 'Environ ').replace(' garanties', ''), 'Le nombre de minutes ne correspond pas à l’estimation annoncée dans le dialogue ; réécoutez le groupe de mots indiquant la durée.'))
    if not changes:
        return False
    consequences = q.setdefault('consequences', {})
    for option, replacement, reason in changes:
        old = option['text']
        if replacement != old:
            text_updates[(q.get('context', ''), old)] = replacement
        option['text'] = replacement
        consequences[option['id']] = reason
    consequences[q['answer']] = q['explanation']
    q['coaching'] = q['explanation']
    q['content_revision'] = REVISION
    if len({o['text'].casefold() for o in q['options']}) != len(q['options']):
        raise ValueError(f"Duplicate choice after revision: {q['id']} {q['prompt']}")
    return True


def _update_derived_rows(q, text_updates):
    count = 0
    for row in q.get('rows', []):
        text = row.get('text', '')
        if ' → ' not in text:
            continue
        context, choice = text.rsplit(' → ', 1)
        replacement = text_updates.get((context, choice))
        if replacement:
            row['text'] = context + ' → ' + replacement
            count += 1
    return count


def _number_with_unit(text):
    m = re.fullmatch(r'\s*(-?\d[\d \u00a0]*(?:[,.]\d+)?)\s*(€(?:/h)?|%|minutes?|min|courses?|km|h)?\s*', text)
    if not m:
        return None
    return Decimal(m[1].replace(' ', '').replace('\u00a0', '').replace(',', '.')), (m[2] or '')


def _replace_empty_feedback(q):
    """Use the worked correction, never invent a cause for an unknown calculation."""
    if q.get('kind') != 'single' or not q.get('explanation'):
        return False
    outcomes = q.get('consequences', {})
    expected = next(o['text'] for o in q['options'] if o['id'] == q['answer'])
    changed = False
    for option in q['options']:
        old = outcomes.get(option['id'], '')
        if not old.startswith(('Ce choix ne résout pas correctement', 'Votre choix permet de poursuivre')):
            continue
        if option['id'] == q['answer']:
            feedback = q['explanation']
        else:
            proposed = _number_with_unit(option['text'])
            wanted = _number_with_unit(expected)
            if proposed and wanted and proposed[1] == wanted[1] and proposed[0] != wanted[0]:
                delta = abs(proposed[0] - wanted[0])
                unit = 'point(s) de pourcentage' if wanted[1] == '%' else wanted[1]
                direction = 'au-dessus' if proposed[0] > wanted[0] else 'en dessous'
                feedback = f"{q['explanation']} La valeur choisie est {direction} du résultat de {str(delta).replace('.', ',')} {unit}."
            else:
                feedback = f"Vous avez choisi « {option['text']} ». {q['explanation']}"
        outcomes[option['id']] = feedback
        changed = True
    if changed:
        q['content_revision'] = REVISION
    return changed


def enrich_course(course):
    result = copy.deepcopy(course)
    if result.get('content_revision', {}).get('version') == REVISION:
        return result
    audit = {'version': REVISION, 'checked_on': REVIEWED_ON, 'lessons': [], 'exercises_revised': 0, 'feedback_refocused': 0, 'derived_rows_updated': 0, 'replacement_activities': [], 'added_exercise_ids': []}
    text_updates = {}
    for section in result['sections']:
        for activity in section['activities']:
            v = activity.get('vtc', {})
            if v.get('kind') == 'lesson':
                before = copy.deepcopy(v)
                _lesson_changes(v)
                if before != v:
                    audit['lessons'].append(v['ref'])
            if activity['id'] == 'vtc-b-01-dossier' and _b01_cases():
                activity['practice']['exercises'] = _b01_cases()
                activity['practice']['purpose'] = 'Comparer un projet en EI, EURL ou SASU et distinguer formes, régimes et trésorerie.'
                audit['replacement_activities'].append(activity['id'])
            if activity['id'] in ('vtc-a-06-dossier', 'vtc-a-07-dossier'):
                additions = _sensitive_cases(v['ref'])
                ids = {q['id'] for q in activity['practice']['exercises']}
                for q in additions:
                    if q['id'] not in ids:
                        activity['practice']['exercises'].append(q)
                        audit['added_exercise_ids'].append(q['id'])
            for q in _exercises(activity):
                if _revise_question(q, v.get('ref'), text_updates):
                    audit['exercises_revised'] += 1
                if _replace_empty_feedback(q):
                    audit['feedback_refocused'] += 1
    # Sorting exercises reproduce some scenario options; update these copies too.
    for q in _exercises(result):
        audit['derived_rows_updated'] += _update_derived_rows(q, text_updates)
    result['content_revision'] = audit
    return result
