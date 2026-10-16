"""Document control, multi-stage missions and applied comparison dossiers."""
from .common import question as q, numbers, sorting, order, money

AUDITS={
'A.01':('Reconnaître le cadre d’un transport',['Transport professionnel créé pour le client','Partage de frais d’un trajet personnel','Autre organisation à examiner'],[
 ('Un conducteur allait déjà au travail et partage ses frais avec un voisin.',1),('Un hôtel commande un trajet facturé que le chauffeur n’avait pas prévu pour lui-même.',0),('Des places sont vendues sur une ligne à arrêts et horaires réguliers.',2),('Une entreprise affrète un autocar pour un groupe.',2),('Un professionnel attend une commande payante pour choisir sa destination.',0),('Un parent accompagne gratuitement son enfant pour un besoin familial.',2),('Une voiture transporte un client sur réservation dédiée et contre rémunération.',0),('Une commune organise un service collectif à la demande selon son dispositif.',2)]),
'A.02':('Relier la preuve au bon dossier',['Conducteur','Exploitant','Véhicule','Mission'],[
 ('Carte professionnelle personnelle',0),('Inscription de l’entreprise au REVTC',1),('Caractéristiques du véhicule réellement utilisé',2),('Date et heure de réservation',3),('Permis et aptitude du conducteur',0),('Formalités de l’entreprise',1),('Justificatif d’entretien de cette voiture',2),('Lieu de prise en charge du client',3)]),
'A.03':('Situer les étapes du candidat',['Apprentissage','Étape d’examen','Titre ou condition d’exercice','Vérification particulière'],[
 ('Inscription à une formation préparatoire',0),('Résultat d’admissibilité théorique',1),('Évaluation de conduite en circulation',1),('Carte professionnelle délivrée',2),('Avis médical conforme au cadre applicable',2),('Ancienne demande déposée avant la réforme de 2026',3),('Révision personnelle du code',0),('Reconnaissance de qualifications européennes',3)]),
'A.04':('Distinguer l’état réel d’une démarche',['À préparer','Déposé, décision à suivre','Décision reçue à vérifier','Événement nécessitant une réaction immédiate'],[
 ('Le renouvellement est prévu mais aucune pièce n’a été rassemblée.',0),('Un accusé de réception de dossier est disponible.',1),('Le nouveau titre vient d’être reçu.',2),('Le permis a été suspendu hier.',3),('Un rendez-vous médical reste à prendre.',0),('La préfecture demande une pièce complémentaire après dépôt.',1),('Une assurance vient d’être résiliée.',3),('Une décision indique une restriction à prendre en compte.',2)]),
'A.05':('Lire la portée des éléments d’assurance',['Information utile à la garantie','Élément insuffisant pour prouver la garantie'],[
 ('Identité du titulaire du contrat',0),('Logo de l’assureur sur une publicité',1),('Usage professionnel déclaré dans les pièces du contrat',0),('Phrase orale « tout est assuré » sans précision',1),('Période de validité indiquée',0),('Numéro du véhicule effectivement couvert',0),('Bonne note commerciale sur une application',1),('Exclusions, franchises et plafonds applicables',0)]),
'A.06':('Repérer un critère pertinent',['Contrainte objective à examiner','Critère de traitement défavorable à écarter'],[
 ('Le groupe dépasse les places autorisées.',0),('Le nom du client laisse supposer une origine.',1),('Un bagage ne peut pas être installé en sécurité.',0),('La religion supposée du passager déplaît au partenaire.',1),('Un comportement violent crée un danger concret.',0),('Le client est écarté uniquement en raison de son handicap.',1),('Le véhicule n’offre pas le dispositif matériel nécessaire à la demande précise.',0),('Une personne est refusée à cause de sa couleur de peau.',1)]),
'A.07':('Choisir un circuit de réaction',['Danger immédiat : protection et alerte','Faits à conserver et signaler sans diffusion publique','Comportement professionnel adapté'],[
 ('Une agression est en cours.',0),('Des messages sexuels insistants sont reçus après le trajet.',1),('Le conducteur écoute sans culpabiliser la personne.',2),('Une menace immédiate se produit dans le véhicule.',0),('Une capture utile doit être transmise au canal de signalement approprié.',1),('La conductrice pose une limite et cherche une situation sûre.',2),('Un passager utilise la notation pour exercer une pression sexuelle.',1),('L’équipe oriente la personne vers l’aide adaptée.',2)]),
'A.08':('Construire une alerte utile',['Information prioritaire utile','Information secondaire ou hypothèse à ne pas présenter comme fait'],[
 ('Lieu précis et sens de circulation',0),('Nombre de personnes concernées observé',0),('Danger encore présent',0),('Avis personnel sur la faute sans éléments',1),('Blessures apparentes décrites sans diagnostic inventé',0),('Couleur préférée du client',1),('Possibilité d’accès et repère visible',0),('Supposition sur l’état médical non constaté',1)]),
'A.09':('Respecter l’autonomie',['Adaptation utile avec accord','Action à corriger'],[
 ('Demander quelle aide la personne souhaite.',0),('Toucher le fauteuil sans prévenir.',1),('Décrire un obstacle à une personne malvoyante.',0),('S’adresser uniquement à l’accompagnant sans raison.',1),('Vérifier avec le passager comment ranger une aide à la mobilité.',0),('Exiger un diagnostic complet sans utilité pour le service.',1),('Chercher un véhicule adapté lorsque la limite matérielle est réelle.',0),('Imposer une aide refusée sans nécessité de sécurité immédiate.',1)]),
'A.10':('Limiter les données au besoin',['Donnée ou partage justifié par le besoin décrit','Donnée ou partage excessif dans ce contexte'],[
 ('Transmettre au remplaçant le point de rendez-vous de sa mission.',0),('Envoyer à tous les collègues l’historique privé du passager.',1),('Noter le besoin pratique de temps pour l’installation.',0),('Demander tout le dossier médical pour un simple transfert.',1),('Conserver une facture selon la durée applicable à cette pièce.',0),('Publier une réservation identifiable pour se moquer d’un client.',1),('Utiliser un canal adapté pour les informations de la course.',0),('Garder indéfiniment toutes les coordonnées sans finalité définie.',1)]),
'A.11':('Préparer un contrôle cohérent',['Pièce utile et cohérente selon les faits','Anomalie à traiter'],[
 ('Bon de réservation correspondant à la mission du jour.',0),('Carte personnelle appartenant à un collègue absent.',1),('Pièce du véhicule avec la bonne immatriculation.',0),('Bon d’une ancienne course présenté comme celui du client actuel.',1),('Document lisible et accessible.',0),('Date modifiée après coup pour masquer l’absence de réservation.',1),('Dossier classé par conducteur, exploitant, véhicule et mission.',0),('Justificatif d’assurance d’une voiture différente sans couverture confirmée.',1)]),
'A.12':('Distinguer les volets d’un incident',['Volet contractuel ou commercial','Volet assurance et dommage','Volet pénal éventuel','Fait à établir avant toute conclusion'],[
 ('Le service convenu comprenait-il cette attente ?',0),('Quelle garantie peut couvrir le bagage endommagé ?',1),('Les faits pourraient-ils constituer une infraction ?',2),('Quelle heure de départ est effectivement prouvée ?',3),('Quel geste commercial l’entreprise peut-elle décider ?',0),('Quel délai de déclaration le contrat prévoit-il ?',1),('Quelle autorité traite l’infraction éventuelle ?',2),('Qui a observé le début de l’événement ?',3)]),
}

def enrich(topics, practices):
    for ref,(title,categories,rows) in AUDITS.items():
        practices[ref].append(sorting(ref,title,'Huit cartes décrivent des situations différentes. Lisez chaque phrase jusqu’au bout avant de choisir sa catégorie.',categories,rows,
            'La catégorie doit correspondre à la fonction réelle de l’élément et aux faits décrits. '+topics[ref]['pitfall']))
        # Second task reverses the observation/action relationship, not only option order.
        practices[ref].append(order(ref,'Vous découvrez une difficulté avant une mission. Retrouvez l’enchaînement de cette méthode de vérification.',[
           'Décrire précisément les faits et les pièces disponibles.','Identifier la règle, la limite ou l’interlocuteur compétent.','Traiter la difficulté ou choisir une solution conforme.','Vérifier le résultat avant de considérer la mission prête.']))
    for v in range(6):
        name=['Société Atlas','Société Azur','Société Riviera','Société Horizon','Société Delta','Société Central'][v]
        expiry=10+v;missionday=15;valid=expiry>=missionday;contact=v%2==0
        rows=[['Exploitant du dossier',name+' (fictif)'],['Titulaire de la pièce',name if v%3 else 'Une autre entreprise fictive'],['Mission','15 novembre 2026, 14 h'],['Échéance de la pièce',f'{expiry} novembre 2026, fin de journée'],['Réservation enregistrée','15 novembre 2026, 13 h 20'],['Prise en charge souhaitée','15 novembre 2026, 14 h'],['Moyen de contacter le client','Disponible sans délai' if contact else 'Absent du dossier et non accessible'],['Usage couvert','Transport rémunéré confirmé' if v%2 else 'Usage privé seulement']]
        docs=[{'title':f'Fiche de contrôle {v+1} · extrait simplifié','rows':rows}]
        context='Ce dossier fictif est un extrait de travail, pas un justificatif réglementaire complet. Chaque question porte uniquement sur le point indiqué. Ne concluez pas à une conformité générale à partir d’un seul contrôle.'
        for ref in ['A.04','A.05','A.11','G.01','G.02','G.04','G.05','G.10','G.11','G.12']:
            practices[ref].append(q(ref,context,'La pièce présentée est-elle cohérente avec le titulaire du dossier sur ce point ?',
              'Oui, les titulaires correspondent' if v%3 else 'Non, la pièce désigne une autre entreprise',
              'Non, les titulaires diffèrent' if v%3 else 'Oui, les titulaires correspondent',
              'Le titulaire n’a jamais d’importance',
              'Il faut comparer le titulaire de la preuve et l’entité concernée, sans supposer qu’un document est transférable.',documents=docs,stage='Audit · titulaire'))
            practices[ref].append(q(ref,context,'Sur les seules dates données, la pièce couvre-t-elle la date de mission ?',
              'Oui, sur ce seul critère de date' if valid else 'Non, elle arrive à échéance avant la mission',
              'Non, elle expire avant la mission' if valid else 'Oui, sur ce seul critère de date',
              'La date de réservation prolonge la pièce',
              f'La mission est le 15 novembre ; la pièce arrive à échéance le {expiry}. Les autres conditions restent à vérifier.',documents=docs,stage='Audit · échéance'))
        for ref in ['G.05','G.06','G.07','G.08','G.09']:
            practices[ref].append(q(ref,context,'La chronologie indiquée établit-elle une commande antérieure à l’heure de prise en charge ?',
               'Oui, 13 h 20 précède 14 h','Non, 14 h précède 13 h 20','L’ordre des horaires n’a aucune importance',
               'La chronologie est cohérente sur ce critère, sans constituer à elle seule toute la vérification du dossier.',documents=docs,stage='Audit · réservation'))
            practices[ref].append(q(ref,context,'Le contact du client peut-il être fourni sans délai selon cette fiche ?',
              'Oui, la fiche l’indique disponible' if contact else 'Non, l’accès au contact reste à résoudre',
              'Non, il est indiqué absent' if contact else 'Oui, il est indiqué disponible',
              'Un numéro inventé peut être ajouté',
              'Le support ou les moyens de contact doivent permettre de répondre aux exigences applicables. Un numéro fictif ne résout pas le manque réel.',documents=docs,stage='Audit · accès aux informations'))
    for v in range(5):
        model='Thermique' if v%2==0 else 'Motorisation à vérifier';capacity=5+v%3;passengers=capacity-(0 if v%2 else 1)
        docs=[{'title':f'Comparatif véhicule {v+1} · données fictives','rows':[['Motorisation',model],['Places autorisées conducteur compris',str(capacity)],['Passagers prévus',str(passengers)],['Usage d’assurance confirmé','Transport rémunéré de personnes'],['Fiche technique et catégorie','À rapprocher des règles et exceptions applicables']]}]
        practices['G.03'].append(q('G.03','Vous ne devez conclure que sur le critère de capacité fourni.','La capacité passagers suffit-elle ?',
          'Oui, conducteur compris le total reste dans la capacité' if passengers+1<=capacity else 'Non, il manque au moins une place autorisée',
          'Non, il manque une place' if passengers+1<=capacity else 'Oui, tous les passagers peuvent être ajoutés au conducteur',
          'Les bagages peuvent servir de place supplémentaire',
          f'{passengers} passagers + 1 conducteur = {passengers+1} personnes pour {capacity} places. Les autres critères doivent être vérifiés séparément.',documents=docs))
    for ref in ['B.01','B.02','F.01','F.02','F.07','F.11']:
        for v in range(6):
            budget=3000+v*400;vehicle=1400+v*150;insurance=500;setup=350;remaining=budget-vehicle-insurance-setup
            docs=[{'title':f'Projet hôtelier {v+1} · données de préparation','rows':[['Budget disponible',money(budget)],['Paiement véhicule avant démarrage',money(vehicle)],['Assurance à payer',money(insurance)],['Autres dépenses initiales',money(setup)],['Commande potentielle','8 transferts sur des créneaux à confirmer'],['Règlement client','Après réalisation selon l’accord à vérifier']]}]
            context='Le partenaire est intéressé, mais la commande et les créneaux ne sont pas encore confirmés. Le budget ci-dessous est disponible ; les recettes espérées ne le sont pas encore. Le cas est fictif.'
            practices[ref].append(numbers(ref,context,'Quel solde reste après les trois paiements initiaux indiqués ?',remaining,budget-vehicle,budget+vehicle,
               f'{budget} − {vehicle} − {insurance} − {setup} = {remaining} €. Il faut encore couvrir les prochaines échéances et conserver une marge.',documents=docs,stage='Projet · moyens disponibles'))
            practices[ref].append(q(ref,context,'Quel engagement commercial est actuellement établi ?','Un intérêt à transformer en commande précise','Huit courses définitivement garanties','Une recette déjà encaissée','Une intention, une réservation et un règlement sont trois états différents.',documents=docs,stage='Projet · niveau de certitude'))
    return topics,practices

def missions(letter, topics, practices):
    """Two connected mission variants per module. Facts evolve across stages."""
    result=[]
    contexts=[('Le transfert gare–hôtel','une gare','un hôtel','un rendez-vous professionnel'),
              ('Le retour d’un événement','un centre de congrès','un aéroport','une heure limite d’arrivée')]
    for variant,(title,start,end,reason) in enumerate(contexts):
        base=70+variant*30;total_km=50+variant*20;commission=20;variable=total_km*.3
        reservation=[{'title':'Ordre de mission fictif · version confirmée','rows':[['Réservation','Veille de la prestation, 18 h'],['Prise en charge','9 h, '+start],['Destination',end],['Voyageurs','3 adultes, 3 bagages compatibles avec le coffre'],['Prix convenu',money(base)],['Attente incluse','10 minutes'],['Arrêt supplémentaire','Sur accord préalable'],['Échéance client',reason]]}]
        context=f'Vous prenez en charge une mission entre {start} et {end}. Le client doit respecter {reason}. Les données suivantes sont fictives. Chaque nouvelle étape ajoute une information : ne remplacez pas les faits confirmés par une hypothèse.'
        ref=letter+'.01';steps=[]
        def add(r,c,p,g,b1,b2,why,stage,docs=None):
            ex=q(r,c,p,g,b1,b2,why,stage=stage,documents=docs or [])
            ex['consequences']={o['id']:('La mission peut être préparée avec cette information vérifiée. '+why if o['id']==ex['answer'] else 'Cette option crée un écart dans la mission. '+why) for o in ex['options']}
            steps.append(ex)
        add(ref,context,'Que faut-il considérer comme la base de départ ?','Le bon confirmé et ses conditions','Une supposition sur le besoin du client','Les détails d’une ancienne course','La préparation part du document correspondant à la mission, pas d’une habitude.','1 · Réservation',reservation)
        add(letter+'.02',context+' Le client précise que sa réservation a été faite par son entreprise.','Quelle distinction conserver ?','Réservant, passager et payeur peuvent être différents','Le conducteur peut ignorer l’identité du passager','Le payeur doit toujours être dans la voiture','Clarifier les rôles évite une erreur d’accueil ou de facturation.','1 · Réservation',reservation)
        add(letter+'.03',context+' Le client demande si l’arrêt à une pharmacie est déjà compris.','Que répondre ?','Il faut confirmer la modification et ses conditions avant de l’ajouter','Tous les arrêts sont gratuits sans limite','Aucun arrêt ne peut jamais être envisagé','Le bon prévoit un accord préalable pour les arrêts supplémentaires.','1 · Réservation',reservation)
        add(letter+'.04',context+' La voiture prévue devient indisponible. Un remplaçant est proposé.','Quel contrôle faut-il refaire ?','Les conditions du conducteur, du véhicule et du service réellement proposés','Seulement la couleur de la voiture','Aucun contrôle si le client est pressé','Un remplacement doit conserver une prestation conforme et sûre.','2 · Préparation')
        add(letter+'.05',context+' Le remplaçant dispose d’une carte personnelle mais l’usage rémunéré du véhicule n’est pas confirmé.','Peut-on lever cette réserve ?','Seulement après la vérification de couverture adaptée','Oui, la carte garantit automatiquement toutes les assurances','Oui, si le prix est faible','Les conditions personnelles et les garanties du véhicule ne se remplacent pas.','2 · Préparation')
        duration=35+variant*10;appoint=10*60;install=10;margin=15;depart=appoint-duration-install-margin
        def time(n):return f'{n//60:02d} h {n%60:02d}'
        add(letter+'.06',f'Pour un créneau alternatif, le rendez-vous à destination est à 10 h. Comptez {duration} min de route, 10 min d’installation et 15 min de marge.','À quelle heure faut-il commencer l’installation ?',time(depart),time(appoint-duration),time(depart+10),f'10 h − {duration} min − 10 min − 15 min = {time(depart)}.','2 · Préparation')
        add(letter+'.07',context+' Au point prévu, deux personnes portent le même prénom.','Comment éviter l’erreur de prise en charge ?','Confirmer discrètement une autre information de réservation','Annoncer toutes les données personnelles à voix haute','Prendre la première personne qui s’approche','La vérification doit identifier le bon client sans divulgation excessive.','3 · Accueil')
        add(letter+'.08',context+' L’un des passagers indique un besoin d’aide pour l’installation.','Quelle question est adaptée ?','Quelle aide souhaitez-vous pour vous installer ?','Quel est votre dossier médical complet ?','Pourquoi n’avez-vous pas choisi un autre transport ?','Le besoin pratique guide l’aide ; les détails médicaux inutiles ne sont pas nécessaires.','3 · Accueil')
        add(letter+'.09',context+' Le groupe annonce finalement un quatrième grand bagage qui ne tient pas de façon sûre.','Que faire ?','Résoudre l’installation avant de partir et adapter les moyens si nécessaire','Le poser librement au milieu de l’habitacle','Partir parce que la course est réservée','La capacité et le rangement restent des conditions concrètes de sécurité.','3 · Accueil')
        add(letter+'.10',context+' Une fermeture temporaire apparaît sur le trajet habituel.','Quelle est la première décision ?','Respecter la fermeture et rechercher une alternative autorisée','Passer parce que l’itinéraire était prévu','Suivre la voiture qui franchit la barrière','La situation actuelle prévaut sur le plan initial.','4 · Trajet')
        add(letter+'.11',context+' L’alternative comporte un péage non inclus.','Comment traiter cette option ?','Expliquer le coût et confirmer l’accord dans le cadre de la prestation','Le facturer seulement à l’arrivée sans information','Le présenter comme une amende','Le changement doit être compréhensible et accepté.','4 · Trajet')
        add(letter+'.12',context+' Le client demande de saisir une nouvelle adresse pendant une manœuvre.','Quelle séquence retenir ?','Terminer en sécurité puis traiter la modification à l’arrêt adapté','Saisir immédiatement en conduisant','Confier le volant au passager','Une tâche secondaire ne doit pas compromettre le contrôle du véhicule.','4 · Trajet')
        add(letter+'.01',context+' Un retard devient probable mais sa durée n’est pas encore certaine.','Quel message est exact ?','Le trajet est perturbé ; je vous donne une estimation puis une mise à jour dès confirmation','Nous arriverons exactement à l’heure malgré tout','Le retard sera forcément d’une heure','Il faut distinguer fait établi, estimation et prochaine action.','5 · Incident et information')
        add(letter+'.02',context+' Le client se montre mécontent de la nouvelle estimation.','Quelle réponse préserve la relation ?','Écouter, expliquer les faits et rechercher les options réalisables','L’accuser de ne rien comprendre','Promettre un remboursement sans pouvoir le décider','La relation s’appuie sur l’écoute et une solution dans votre périmètre.','5 · Incident et information')
        add(letter+'.03',context+' Une solution de remplacement est évoquée par téléphone, sans confirmation.','Comment la présenter ?','Comme une option en cours de vérification','Comme un véhicule déjà sur place','Comme une obligation acceptée par le client','La disponibilité doit être confirmée avant un engagement précis.','5 · Incident et information')
        supplement=10+variant*5;final=base+supplement
        add(letter+'.04',f'Le prix initial était {base} €. Un arrêt supplémentaire de {supplement} € a été explicitement accepté. Aucun autre poste n’est dû dans ce dossier.','Quel total expliquer au client ?',money(final),money(base),money(final+20),f'{base} + {supplement} = {final} €. Les postes correspondent aux conditions convenues.','6 · Paiement')
        add(letter+'.05',context+' Le terminal indique un statut de paiement incertain.','Que faire avant une nouvelle tentative ?','Vérifier l’état du premier paiement','Relancer plusieurs fois sans contrôle','Facturer le double par précaution','La vérification évite un double règlement.','6 · Paiement')
        add(letter+'.06',context+' Le client demande un justificatif et annonce une réclamation sur le retard.','Quelle réponse est adaptée ?','Remettre les documents et indiquer le canal de traitement de la réclamation','Refuser tout document parce qu’il est mécontent','Effacer les horaires enregistrés','La transparence et la traçabilité permettent l’examen du dossier.','6 · Clôture')
        add(letter+'.07',context+' Un objet est retrouvé après la dépose.','Comment organiser sa remise ?','Vérifier le propriétaire et convenir d’une restitution sécurisée','Le remettre au premier passant','Publier son contenu et les données du client','La restitution doit préserver la personne et ses données.','7 · Suivi')
        add(letter+'.08',context+' Le retard provient d’une fermeture signalée avant le départ mais non consultée.','Quelle amélioration traite la cause ?','Ajouter une vérification des perturbations lors de la préparation','Envoyer seulement des excuses identiques à chaque course','Ne plus accepter de clients exigeants','Une action préventive ciblée réduit la répétition de l’erreur.','7 · Retour d’expérience')
        # Module-specific numerical evidence and language keep missions connected to their subject.
        if letter in 'BF':
            for r,prompt,correct,w1,w2,why in [
               (letter+'.05','Quelle commission résulte du taux hypothétique de 20 % appliqué au prix initial ?',base*.2,base*.8,base*1.2,f'{base} × 20 % = {money(base*.2)}.'),
               (letter+'.09','Quelle contribution reste après cette commission et 0,30 €/km sur la distance totale ?',base*.8-variable,base*.8,base-variable,f'{base} × 0,80 − {total_km} × 0,30 = {money(base*.8-variable)}. Les charges fixes restent à couvrir.')]:
                steps.append(numbers(r,f'Bilan fictif de la mission : prix initial {base} €, {total_km} km totaux, commission 20 %, coût variable 0,30 €/km. On ignore ici le supplément pour étudier la mission initiale.',prompt,correct,w1,w2,why,stage='8 · Bilan économique'))
        result.append({'id':f'{letter.lower()}-mission-{variant+1}','title':title,'introduction':context,'exercises':steps})
    return result
