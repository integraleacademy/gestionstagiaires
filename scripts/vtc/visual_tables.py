"""Concrete comparison tables; all amounts and cases are teaching examples."""

def table(title, headers, rows, note=''):
    return dict(title=title, headers=headers, rows=rows, note=note)


TABLES = {
'A.01':table('Deux trajets qui ne répondent pas au même besoin', ['Situation','Ce qui crée le trajet','À distinguer'], [
    ['Un client commande un transfert','Le besoin du client','Une prestation professionnelle payante.'],
    ['Une personne partage son trajet personnel','Le déplacement du conducteur','Un partage de frais, sans déguiser une activité lucrative.']]),
'A.02':table('Chaque justificatif répond à une question', ['Élément','Question à vérifier'], [
    ['Conducteur','Cette personne peut-elle exercer ?'],['Entreprise','Cet exploitant remplit-il ses obligations ?'],
    ['Véhicule','Cette voiture peut-elle être utilisée pour la prestation ?'],['Réservation','Cette prise en charge a-t-elle été convenue à l’avance ?']]),
'A.05':table('Deux protections à examiner séparément', ['Contrat','Risque à vérifier','Point de vigilance'], [
    ['Assurance du véhicule','Usage du véhicule pour le transport rémunéré','Un contrat privé ne suffit pas par son seul intitulé.'],
    ['Responsabilité de l’activité','Dommages liés à la prestation','Lire les garanties, exclusions et bénéficiaires.']]),
'A.10':table('Partager uniquement ce qui sert à la mission', ['Information','Usage utile','Partage à éviter'], [
    ['Nom et point de rencontre','Identifier le bon passager','Afficher tout le dossier devant les autres voyageurs.'],
    ['Coordonnée de contact','Prévenir d’un changement de rendez-vous','Réutiliser librement le numéro pour une autre finalité.'],
    ['Besoin d’assistance','Préparer l’accueil demandé','Collecter des détails intimes inutiles.']]),
'B.03':table('Lire un bilan sans le confondre avec la banque', ['Actif : emplois','Passif : ressources'], [
    ['Véhicule de l’entreprise','Capitaux apportés et résultats accumulés'],['Créances clients','Emprunts et dettes'],['Disponibilités en banque','Autres financements de l’entreprise']],
    'Présentation simplifiée : les deux colonnes décrivent un ensemble, pas des paires à relier ligne par ligne.'),
'B.04':table('Résultat et trésorerie : deux calculs différents', ['Mesure','Exemple fictif','Ce que l’on obtient'], [
    ['Résultat de la période','8 000 € de produits − 6 500 € de charges','1 500 € de résultat'],
    ['Variation de banque','7 000 € encaissés − 6 800 € décaissés','200 € de trésorerie supplémentaire']],
    'Les dates de règlement expliquent notamment pourquoi les montants ne coïncident pas.'),
'B.08':table('Suivre l’argent au moment où il entre ou sort', ['Étape','Montant','Solde'], [
    ['Solde au début du mois','1 000 €','1 000 €'],['Encaissements du mois','+ 3 200 €','4 200 €'],['Décaissements du mois','− 3 700 €','500 €']],
    'Exemple fictif : une facture non réglée ne constitue pas encore une entrée en banque.'),
'B.09':table('Calculer un seuil course par course', ['Donnée ou opération','Exemple fictif','Sens'], [
    ['Recette unitaire','50 €','Montant retenu pour l’exercice.'],['Coût variable unitaire','20 €','Coût lié à chaque course.'],
    ['Contribution unitaire','50 − 20 = 30 €','Somme disponible pour couvrir les coûts fixes.'],
    ['Charges fixes / contribution','1 500 / 30 = 50 courses','Seuil d’équilibre de ce modèle simplifié.']],
    'Au-delà du seuil, vérifier que tous les coûts et la rémunération visée ont bien été pris en compte.'),
'C.01':table('Contrôle avant départ : observer puis décider', ['Observation','Décision adaptée'], [
    ['Un objet peut glisser sous les pédales','Le ranger avant de rouler.'],['Un pneu semble anormal','Vérifier la situation avant le départ.'],
    ['La navigation n’est pas prête','La régler à l’arrêt.'],['Le client est pressé','Conserver les vérifications de sécurité.']]),
'C.03':table('La distance d’arrêt comporte deux parties', ['Phase','Ce qui se passe','Ce qui peut l’allonger'], [
    ['Réaction','Le véhicule avance avant le début du freinage.','Distraction, fatigue, vitesse.'],
    ['Freinage','Le véhicule ralentit jusqu’à l’arrêt.','Vitesse, adhérence, état des pneus et de la chaussée.']],
    'Distance d’arrêt = distance de réaction + distance de freinage. Une marge se prépare avant le danger.'),
'C.07':table('Fatigue : reconnaître le signal utile', ['Signal','Ce qu’il indique','Réponse'], [
    ['Bâillements répétés','La vigilance peut diminuer.','Préparer un arrêt sûr.'],
    ['Paupières lourdes','Continuer devient dangereux.','S’arrêter pour se reposer.'],
    ['Difficulté à rester concentré','Le service doit être réorganisé.','Informer et chercher une solution sûre.']],
    'La musique et la fenêtre ouverte ne remplacent pas le repos.'),
'C.09':table('Une même action change de risque selon le moment', ['Action','Avant de rouler','Pendant le trajet'], [
    ['Préparer le GPS','Régler l’itinéraire à l’arrêt.','Ne pas manipuler en conduisant.'],
    ['Lire un message','Clarifier les informations utiles.','Attendre un arrêt sûr.'],
    ['Chercher un objet','Le placer à portée avant le départ.','Garder l’attention sur la conduite.']]),
'D.03':table('Lire sans ajouter une histoire', ['Phrase','Nature','Pourquoi'], [
    ['« Le passager est arrivé à 9 h 12. »','Fait indiqué','Une heure précise est donnée.'],
    ['« Il est arrivé tard parce qu’il est négligent. »','Interprétation','Une cause et un jugement sont ajoutés.']],
    'Un retard peut être constaté si l’heure convenue est connue ; sa cause ne doit pas être inventée.'),
'D.05':table('Les petits mots changent le lien entre les idées', ['Mot','Lien','Exemple'], [
    ['Car','Cause','La prise en charge change, car la sortie est fermée.'],['Donc','Conséquence','La sortie est fermée, donc le rendez-vous change.'],
    ['Mais','Opposition','Le trajet est court, mais la circulation est dense.'],['Si','Condition','Si le terminal change, le client prévient le chauffeur.']]),
'D.08':table('Placer une action dans le temps', ['Moment','Phrase','Repère'], [
    ['Avant','Le client a confirmé.','L’action est présentée comme accomplie.'],['Maintenant','Le client confirme.','L’action est au présent.'],
    ['Après','Le client confirmera.','L’action est annoncée au futur.']]),
'D.11':table('Rendre un message plus facile à comprendre', ['Formulation confuse','Formulation précise'], [
    ['« J’arrive là-bas tout à l’heure. »','« Je vous attends à la sortie B à 14 h. »'],
    ['« Ça a changé. »','« La sortie A est fermée ; le rendez-vous est déplacé à la sortie B. »']],
    'L’exercice consiste à comparer et sélectionner une formulation ; aucune rédaction n’est demandée.'),
'E.01':table('Choisir la bonne salutation', ['Moment','Expression','Sens'], [
    ['Matin','Good morning.','Bonjour.'],['Après-midi','Good afternoon.','Bonjour.'],['Soir, à l’accueil','Good evening.','Bonsoir.'],
    ['Au moment de prendre congé pour la nuit','Good night.','Bonne nuit.']]),
'E.03':table('Des nombres proches à faire confirmer', ['Expression','Valeur','Réflexe'], [
    ['Thirteen','13','Faire répéter en cas de doute.'],['Thirty','30','Ne pas deviner à partir du contexte.'],
    ['Fifteen','15','Répéter le nombre compris.'],['Fifty','50','Attendre la confirmation.']]),
'E.05':table('Proposer une aide sans l’imposer', ['Expression','Traduction','Usage'], [
    ['How many bags do you have?','Combien de bagages avez-vous ?','Vérifier la capacité.'],
    ['May I help you with your luggage?','Puis-je vous aider avec vos bagages ?','Proposer une aide.'],
    ['Is this your bag?','Est-ce votre sac ?','Vérifier avant de déplacer.']]),
'E.10':table('Conclure le service en anglais', ['Expression','Traduction'], [
    ['How would you like to pay?','Comment souhaitez-vous payer ?'],['Would you like a receipt?','Souhaitez-vous un reçu ?'],
    ['Please check the amount.','Veuillez vérifier le montant.'],['Thank you. Have a nice day.','Merci. Bonne journée.']]),
'F.03':table('Une commission se calcule sur le prix', ['Hypothèse fictive','Calcul','Résultat'], [
    ['Prix facturé','100 €','Base du calcul'],['Commission de 20 %','100 × 20 %','20 €'],['Recette après commission','100 − 20','80 €']],
    'Pour conserver 80 € avec cette retenue, le calcul est 80 / 0,80 = 100 €. Les autres coûts restent à retirer.'),
'F.05':table('Rapprocher ventes et virement', ['Élément fictif','Montant','Lecture'], [
    ['Courses de la période','200 €','Ventes de l’exercice.'],['Commission hypothétique','− 40 €','Retenue de 20 %.'],
    ['Net avant autres ajustements','160 €','Montant à rapprocher du relevé et du règlement.']]),
'F.06':table('Préciser le dénominateur d’un taux', ['Indicateur fictif','Calcul','Résultat'], [
    ['Rendez-vous / contacts','10 / 40','25 %'],['Contrats / contacts','4 / 40','10 %'],['Contrats / rendez-vous','4 / 10','40 %']],
    'Ces trois taux décrivent le même exemple, mais ne répondent pas à la même question.'),
'F.11':table('Traiter une réclamation dans un ordre utile', ['Moment','Action','Objectif'], [
    ['Écouter','Reformuler ce qui est contesté.','Comprendre la demande.'],['Vérifier','Rapprocher réservation, service et prix.','Établir les faits.'],
    ['Répondre','Expliquer la solution et les suites.','Donner une réponse compréhensible.']]),
'G.01':table('Ne pas confondre personne et entreprise', ['Élément','Concerne','À retenir'], [
    ['Titre du conducteur','La personne qui conduit','Il ne remplace pas l’inscription de l’exploitant.'],
    ['Inscription de l’exploitant','L’entreprise de transport','Elle ne remplace pas le titre du conducteur.'],
    ['Dossier du véhicule','La voiture utilisée','Il doit correspondre au service réellement effectué.']]),
'G.05':table('Une preuve doit correspondre à la course', ['Contrôle','Question concrète'], [
    ['Antériorité','La réservation existe-t-elle avant la prise en charge ?'],['Correspondance','Les données concernent-elles ce client et ce trajet ?'],
    ['Disponibilité','Le justificatif peut-il être présenté ?'],['Complétude','Les mentions réglementaires applicables sont-elles présentes ?']]),
'G.06':table('Deux situations à distinguer', ['Situation','Point décisif'], [
    ['Le chauffeur rejoint un client ayant réservé.','La réservation précède la prise en charge.'],
    ['Le chauffeur cherche un client disponible dans la rue.','Ce fonctionnement relève de la maraude, hors du cadre VTC.']],
    'L’utilisation d’une application ne suffit pas à elle seule à prouver la conformité du service.'),
'G.10':table('Un remplacement exige plusieurs vérifications', ['Ce qui change','Ce qu’il faut rapprocher'], [
    ['Le conducteur','Identité, titre et conditions d’exercice.'],['Le véhicule','Éligibilité, assurance et documents.'],
    ['L’organisation de la mission','Information du client, point de rencontre et justificatifs.']]),
'H.01':table('Trois personnes peuvent jouer trois rôles', ['Rôle','Exemple fictif','À clarifier'], [
    ['Réservant','Un hôtel','Qui commande le service ?'],['Passager','Un voyageur','Qui faut-il accueillir ?'],
    ['Payeur','L’entreprise du voyageur','Qui règle et reçoit la facture ?']]),
'H.02':table('Remonter le temps depuis le rendez-vous', ['Hypothèse fictive','Heure','Calcul'], [
    ['Rendez-vous à destination','10 h 00','Heure d’arrivée demandée.'],['Dépose et accès','9 h 50','Retirer 10 minutes.'],
    ['Trajet estimé','9 h 20','Retirer 30 minutes.'],['Marge prévue','9 h 10','Retirer 10 minutes supplémentaires.']],
    'Exemple de raisonnement : les marges réelles dépendent du trajet, de la circulation et des accès.'),
'H.08':table('Expliquer un imprévu en trois informations', ['Information','Exemple de formulation'], [
    ['Le fait','« La route prévue est fermée. »'],['La conséquence','« Le trajet doit être modifié. »'],
    ['La proposition','« Je vous explique l’alternative et son incidence avant de poursuivre. »']]),
'H.10':table('La prestation se termine après la dépose', ['Point','Vérification'], [
    ['Passager','La sortie du véhicule est sûre.'],['Bagages','Les effets remis correspondent au passager.'],
    ['Règlement','Le paiement et le document remis sont cohérents.'],['Habitacle','Aucun objet oublié avant la mission suivante.']]),
}
