"""Connected business and document cases, plus listening transfer sessions."""
import copy
from .common import question as q, numbers, money
from .applied import missions as road_missions

def business_mission(letter, variant):
    multiplier=variant+1;rides=40+20*variant;price=70+10*variant;gross=rides*price;commission=gross*.2
    km=1600+500*variant;variable=km*.3;fixed=700+100*variant;paid=gross-400;initial=1500
    title='Une semaine d’exploitation à analyser' if variant==0 else 'Développer un contrat hôtelier sans perdre sa marge'
    docs=[{'title':'Tableau de la semaine · données entièrement fictives','rows':[
       ['Courses réalisées',str(rides)],['Prix uniforme par course',money(price)],['Commission','20 % du chiffre d’affaires'],
       ['Kilomètres totaux',str(km)+' km'],['Coût variable','0,30 €/km'],['Charges fixes attribuées à la semaine',money(fixed)],
       ['Factures non encaissées','400 €'],['Solde de trésorerie initial','1 500 €'],['Autres hypothèses','Tous les coûts indiqués sont payés ; TVA et autres postes exclus de cet exercice']]}]
    context='Vous analysez une semaine terminée, puis décidez comment organiser la suivante. Les chiffres sont sur une même base pédagogique. Le modèle est volontairement simplifié : aucun poste non mentionné ne doit être inventé.'
    steps=[]
    def number(ref,p,c,w1,w2,why,stage):steps.append(numbers(ref,context,p,c,w1,w2,why,documents=docs,stage=stage))
    def choice(ref,p,g,b1,b2,why,stage):steps.append(q(ref,context,p,g,b1,b2,why,documents=docs,stage=stage))
    number('B.04','Quel chiffre d’affaires a été réalisé ?',gross,paid,gross-fixed,f'{rides} × {price} = {money(gross)}. Les factures non encaissées restent distinctes de la trésorerie.','1 · Reconstituer les recettes')
    number('F.05','Quel montant de commission est prévu ?',commission,gross*.8,gross*.02,f'{gross} × 20 % = {money(commission)}.','1 · Reconstituer les recettes')
    number('F.05','Quelle recette après commission reste sur la base du chiffre d’affaires réalisé ?',gross-commission,gross+commission,commission,f'{gross} − {commission} = {money(gross-commission)}.','1 · Reconstituer les recettes')
    number('B.05','Quel coût variable correspond aux kilomètres totaux ?',variable,km*.03,km,f'{km} × 0,30 = {money(variable)}. Les approches et retours sont compris dans le total.','2 · Identifier les coûts')
    number('B.04','Quel résultat simplifié obtient-on après commission, coûts variables et charges fixes ?',gross-commission-variable-fixed,gross-commission-variable,gross-variable-fixed,
       f'{gross} − {commission} − {variable} − {fixed} = {money(gross-commission-variable-fixed)}.','2 · Identifier les coûts')
    number('B.08','Quels encaissements clients sont effectivement reçus ?',paid,gross,gross+400,f'{gross} − 400 = {money(paid)}. Les 400 € restants ne sont pas encore disponibles.','3 · Vérifier la trésorerie')
    cash=initial+paid-commission-variable-fixed
    number('B.08','Quel est le solde final de trésorerie du modèle ?',cash,cash+400,cash-initial,
       f'1 500 + {paid} − {commission} − {variable} − {fixed} = {money(cash)}.','3 · Vérifier la trésorerie')
    choice('B.03','Pourquoi le résultat ne suffit-il pas à connaître le solde bancaire ?','Des décalages de paiement et le solde initial interviennent','Le chiffre d’affaires est toujours le solde bancaire','Les charges fixes n’existent qu’en comptabilité','Les produits, les encaissements et le solde disponible sont trois lectures différentes.','3 · Vérifier la trésorerie')
    newprice=price-10;newgross=rides*newprice;newresult=newgross*.8-variable-fixed
    extra={'title':'Proposition commerciale pour la semaine suivante','rows':[['Nombre de courses','Même volume'],['Prix proposé',money(newprice)],['Autres hypothèses','Commission, kilomètres et charges inchangés dans ce scénario']]}
    newcontext=f'Le partenaire propose maintenant un prix de {newprice} € par course, à volume et coûts inchangés. Cette offre n’est pas encore acceptée.'
    steps.append(numbers('F.03',newcontext,'Quel résultat simplifié donnerait cette offre ?',newresult,newgross*.8-variable,newgross-variable-fixed,
        f'{rides} × {newprice} × 0,80 − {variable} − {fixed} = {money(newresult)}.',documents=docs+[extra],stage='4 · Comparer une nouvelle offre'))
    steps.append(q('F.07',newcontext,'Que faut-il clarifier avant un engagement ?','Volume confirmé, horaires, attente, annulation et paiement','Uniquement le nombre d’étoiles de l’hôtel','Une promesse orale suffit pour tous les cas','Le prix doit être relié au périmètre et à la faisabilité du service.',documents=[extra],stage='4 · Comparer une nouvelle offre'))
    choice('F.01','Quel risque le chiffre d’affaires seul masque-t-il ?','Une hausse d’activité peut mobiliser davantage de coûts et de temps','Tout chiffre d’affaires plus élevé garantit un bénéfice supérieur','Les kilomètres à vide n’ont jamais de coût','Il faut regarder la contribution et le temps réellement mobilisé.','4 · Comparer une nouvelle offre')
    campaign=180+variant*60;contacts=60+variant*20;clients=6+variant*2
    campaigncontext=f'Une campagne test distincte coûte {campaign} €. Elle contacte {contacts} prospects et apporte {clients} nouveaux clients attribués à cette campagne.'
    steps.append(numbers('F.08',campaigncontext,'Quel coût d’acquisition par client attribué calcule-t-on ?',campaign/clients,campaign/contacts,campaign,
        f'{campaign} ÷ {clients} = {money(campaign/clients)} par nouveau client.',stage='5 · Piloter la prospection'))
    steps.append(numbers('F.06',campaigncontext,'Quel taux contacts → clients obtient-on ?',clients/contacts*100,100-clients/contacts*100,clients,
        f'{clients} ÷ {contacts} × 100 = {clients/contacts*100:.1f} %.',unit=' %',stage='5 · Piloter la prospection'))
    steps.append(q('F.09',campaigncontext,'Quelle donnée faut-il encore suivre pour juger l’intérêt commercial ?','La contribution et le retour éventuel de ces clients','Seulement le nombre de vues d’une image','La couleur choisie pour le tableau','Le coût d’acquisition doit être rapproché de la valeur effectivement générée, sans la présumer.',stage='5 · Piloter la prospection'))
    complaint='Un client de la semaine conteste un supplément d’attente. Le devis prévoit dix minutes incluses ; l’horaire de présentation du véhicule et celui du départ ne sont pas encore rapprochés.'
    steps.append(q('F.11',complaint,'Quelle étape vient avant la décision financière ?','Vérifier les conditions et les horaires établis','Reconnaître n’importe quel montant demandé','Rejeter toute demande sans lecture','L’examen factuel évite une décision automatique.',stage='6 · Traiter et améliorer'))
    steps.append(q('B.11',complaint,'Si une erreur de facturation est confirmée, comment la traiter ?','Par une correction traçable selon la procédure','En supprimant discrètement la facture','En changeant seulement l’adresse du client','La correction doit permettre de comprendre l’opération initiale et sa régularisation.',stage='6 · Traiter et améliorer'))
    steps.append(q('F.10',complaint,'Quelle amélioration prévient une nouvelle contestation ?','Clarifier les conditions d’attente et conserver des horaires cohérents','Ne plus remettre de devis','Facturer tous les clients de la même façon sans données','L’amélioration doit viser la cause de l’écart.',stage='6 · Traiter et améliorer'))
    steps.append(q('B.12','Le calcul du revenu horaire a divisé le résultat par les seules heures passager.','Quel complément est nécessaire ?','Inclure les autres temps professionnels du périmètre choisi','Supprimer les approches du planning','Assimiler les heures facturées à toutes les heures mobilisées','La base temporelle doit correspondre à l’activité réellement analysée.',stage='7 · Bilan et décision'))
    return {'id':f'{letter.lower()}-mission-{variant+1}','title':title,'introduction':context,'exercises':steps}

def written_mission(variant):
    hour=8+variant;newplace='sortie jardin' if variant==0 else 'hall B';price=80+variant*20
    docs=[{'title':'Message 1 · réception · 16 h','text':f'Bonjour, nous confirmons demain {hour} h, trois passagers, entrée principale, prix {price} € pour le trajet direct.'},
          {'title':'Message 2 · réception · 17 h 10','text':f'L’heure est maintenue. Merci de rejoindre la {newplace}. Un arrêt pourrait être demandé, mais il n’est pas confirmé. Prévenez-nous avant de modifier le prix.'},
          {'title':'Message 3 · chauffeur · 17 h 20','text':f'J’ai bien reçu votre message. Je confirmerai la faisabilité de l’arrêt après vérification. La prise en charge reste prévue à {hour} h, {newplace}.'},
          {'title':'Compte rendu · lendemain','text':f'Le véhicule est présenté à {hour} h. Le client indique qu’il pensait être attendu à l’entrée principale. Il rejoint le nouveau lieu dix minutes plus tard. Le conducteur suppose que le message n’a pas été relayé. Aucun arrêt supplémentaire n’a finalement été réalisé.'}]
    ref='D.';steps=[]
    data=[
      ('01','Quel est l’objet principal de la deuxième communication ?','Changer le lieu en maintenant l’heure','Annuler la réservation','Confirmer un arrêt supplémentaire','L’heure est maintenue et seul le lieu est confirmé comme modifié.'),
      ('02','À quelle heure le départ reste-t-il prévu ?',f'{hour} h',f'{hour+1} h','17 h 10','Les heures 16 h et 17 h 10 sont celles des messages, pas de la prise en charge.'),
      ('02','Quel est le dernier lieu confirmé ?',newplace,'entrée principale','le bureau du transporteur','Le message de 17 h 10 est repris par le chauffeur à 17 h 20.'),
      ('03','Quel élément du compte rendu est une supposition ?','Le message n’aurait pas été relayé','Le client rejoint le lieu dix minutes plus tard','Aucun arrêt n’a été réalisé','Le texte attribue explicitement cette idée à une supposition du conducteur.'),
      ('03','Que sait-on du point de vue du client ?','Il dit qu’il pensait être attendu à l’entrée principale','Il a forcément menti','Il avait certainement reçu tous les messages','Le compte rendu rapporte son propos sans en faire une conclusion sur sa bonne foi.'),
      ('06','Que signifie « un arrêt pourrait être demandé » ?','Une possibilité encore non confirmée','Un arrêt déjà commandé et accepté','Une annulation définitive du transfert','Pourrait exprime une éventualité.'),
      ('08','Que prouve « je confirmerai après vérification » ?','L’action est annoncée pour plus tard et sous cette étape préalable','La vérification est déjà terminée','Le chauffeur refuse définitivement','Le futur et après ne décrivent pas un accomplissement déjà réalisé.'),
      ('05','Dans « après vérification », quelle relation est indiquée ?','Une chronologie','Une opposition','Une comparaison de prix','La vérification doit précéder la confirmation.'),
      ('10','Quelle réponse courte explique le décalage de dix minutes observé ?','Le client a rejoint le nouveau point dix minutes après la présentation du véhicule','Le véhicule était nécessairement en panne','L’heure de prise en charge avait été changée','La réponse reprend l’événement décrit sans ajouter une cause non établie.'),
      ('11','Quel message au client est le plus professionnel ?','Nous allons vérifier les messages transmis et les horaires pour vous répondre précisément.','Vous n’avez sûrement pas lu, ce n’est pas notre problème.','Nous garantissons un remboursement avant de lire le dossier.','La réponse annonce une action utile sans accusation ni promesse non maîtrisée.'),
      ('12','L’arrêt supplémentaire peut-il être facturé comme réalisé selon ce compte rendu ?','Non, le compte rendu indique qu’il n’a pas été réalisé','Oui, puisqu’il avait été évoqué','Oui, le conditionnel suffit à prouver la prestation','Évoquer une possibilité ne prouve pas son exécution.'),
      ('09','Quelle phrase est correctement accordée ?','Les informations sont confirmées.','Les informations est confirmé.','Les information sont confirmée.','Informations est féminin pluriel ; le verbe et le participe doivent être cohérents.'),
      ('04','Dans « la réception informe le chauffeur ; celui-ci répond », qui répond ?','Le chauffeur','La réception','Le véhicule','Celui-ci reprend ici le chauffeur.'),
      ('07','Dans ce dossier, « faisabilité » signifie…','possibilité de réaliser la demande dans les conditions requises','paiement déjà reçu','réduction automatique du prix','Le mot concerne la possibilité concrète de réalisation.'),
      ('12','Quelle conclusion est entièrement appuyée par le dossier ?','Le lieu a changé, l’heure a été maintenue et l’arrêt envisagé n’a pas été réalisé','Le chauffeur était absent à l’heure prévue','Le client avait accepté tous les suppléments','La bonne synthèse respecte les faits disponibles et leurs limites.')]
    for n,p,g,b1,b2,why in data:steps.append(q(ref+n,'Reconstituez ce dossier de messages dans l’ordre. Chaque réponse doit être justifiée par une phrase ou un fait du dossier.',p,g,b1,b2,why,documents=docs,stage='Lecture croisée · dossier évolutif'))
    return {'id':f'd-mission-{variant+1}','title':'Une réservation modifiée : lire les versions' if not variant else 'Une réclamation : faits, propos et réponse','introduction':'Comparez les messages, distinguez les faits et choisissez une réponse professionnelle. Aucune rédaction n’est demandée.','exercises':steps}

def build(letter, topics, practices):
    if letter in 'BF':return [business_mission(letter,v) for v in range(2)]
    if letter=='D':return [written_mission(v) for v in range(2)]
    if letter in 'AG':return [legal_mission(letter,v) for v in range(2)]
    if letter=='C':
        result=[]
        for v in range(2):
            steps=[]
            for n in range(1,13):
                ex=copy.deepcopy(practices[f'C.{n:02}'][v]);ex['stage']=f'Événement {n} · préparer puis conduire'
                ex['context']='Séance de conduite préparatoire. Après résolution de l’événement précédent dans des conditions sûres, vous analysez le nouvel événement suivant. '+ex['context'];steps.append(ex)
            steps+=copy.deepcopy(practices['C.11'][6+v*4:10+v*4])
            result.append({'id':f'c-mission-{v+1}','title':'Préparer un départ puis gérer les aléas' if v==0 else 'Conserver ses marges dans une journée difficile','introduction':'Douze événements successifs et une comparaison d’itinéraires. Pour chaque événement, identifiez le risque et la décision qui permet de reprendre dans des conditions sûres. La séance ne remplace pas la conduite avec un formateur.','exercises':steps})
        return result
    if letter=='E':
        result=[]
        for v in range(2):
            steps=[]
            for ref in ['E.02','E.04','E.05','E.07','E.09','E.10','E.11']:
                for ex in practices[ref][v*3:(v+1)*3]:
                    ex=copy.deepcopy(ex);ex['context']='Journée de service : vous rencontrez plusieurs clients. Chaque conversation possède ses propres informations ; ne reportez pas un prix ou un horaire d’une scène à la suivante. '+ex['context'];steps.append(ex)
            result.append({'id':f'e-mission-{v+1}','title':'Une journée de service en anglais · '+str(v+1),'introduction':'Traversez sept situations : réservation, rendez-vous, bagages, trajet, changement, paiement et objet oublié. Écoutez les informations avant de prendre votre décision.','exercises':steps})
        return result
    result=road_missions(letter,topics,practices)
    actual=['H.01','A.02','G.09','G.10','A.05','H.02','H.04','A.09','C.06','C.05','G.09','C.09','H.08','F.11','H.08','B.11','H.09','F.11','H.10','H.12']
    for mission in result:
        for ex,ref in zip(mission['exercises'],actual):ex['competency']=ref
        if letter=='C':
            # Safety evidence is assessed explicitly, in addition to the connected transport story.
            for ref in ['C.01','C.03','C.04','C.07','C.08','C.11','C.12']:
                ex=copy.deepcopy(practices[ref][len(mission['id'])%4]);ex['stage']='Conduite · analyser un nouvel événement';mission['exercises'].append(ex)
    return result

def legal_mission(letter,variant):
    registered=variant==1;medical=variant==0
    docs=[{'title':'Dossier de départ · entreprise et personne fictives','rows':[
      ['Conductrice','Nadia, carte personnelle valide'],['Entreprise','Nouvelle entreprise de Nadia'],
      ['REVTC','Inscription confirmée' if registered else 'Dossier incomplet, inscription non finalisée'],
      ['Aptitude médicale','Valide à la date de mission' if medical else 'Échéance dépassée avant la mission'],
      ['Assurance véhicule','Usage transport rémunéré confirmé'],['Mission','Réservation réelle la veille ; prise en charge à 10 h'],
      ['Client','Deux adultes ; besoin d’assistance à préciser'],['Contact client','Accessible sans délai'],
      ['Fin de mission','Aucune réservation suivante confirmée']]}]
    context='Vous accompagnez la préparation d’une nouvelle activité. Les documents sont des extraits pédagogiques fictifs. Le traitement d’un point ne permet pas de déclarer tout le dossier conforme. Les étapes suivantes supposent que les anomalies antérieures ont été résolues avant tout transport.'
    rows=[
      ('A.02','La carte personnelle suffit-elle à prouver l’inscription de la nouvelle entreprise ?','Non, les deux démarches sont distinctes','Oui, la carte remplace le registre','Oui, si Nadia travaille seule','Une personne peut cumuler deux rôles sans fusionner leurs obligations.'),
      ('G.01','Quel est l’état de l’inscription selon le dossier ?','Confirmée' if registered else 'Non finalisée','Non finalisée' if registered else 'Confirmée','Automatiquement sans objet','Il faut lire l’état réel indiqué et ne pas confondre dépôt et décision.'),
      ('A.04','Quel contrôle de validité personnelle appelle ici une action ?','L’aptitude médicale dépassée' if not medical else 'Aucune anomalie médicale n’est indiquée sur ce seul point','Aucune anomalie médicale' if not medical else 'La carte appartient nécessairement à une autre personne','Toutes les pièces sont automatiquement périmées','La validité médicale se suit séparément de la carte.'),
      ('A.05','Quelle garantie a été explicitement confirmée ?','L’usage de transport rémunéré du véhicule','Une couverture illimitée de tous les dommages','L’assurance personnelle de tous les clients','La portée de la confirmation doit rester limitée à ce qui est écrit.'),
      ('G.05','Quel élément distingue le moment de commande et celui du transport ?','Réservation la veille et prise en charge à 10 h','La couleur du véhicule','La marque du téléphone','La chronologie doit permettre une réservation réellement préalable.'),
      ('G.05','Que vérifier au-delà de la chronologie ?','Les autres mentions et moyens de preuve requis pour la mission','Rien, une heure suffit à tout prouver','Uniquement la note du client','Un seul critère cohérent ne rend pas le justificatif complet.'),
      ('A.09','Le client annonce un besoin d’assistance sans diagnostic. Quelle démarche est utile ?','Demander quelle aide pratique est souhaitée','Exiger tout le dossier médical','Refuser sans examiner le besoin','La bonne information est celle qui permet d’adapter la prestation.'),
      ('A.06','Un partenaire suggère un refus lié à l’origine supposée du client. Quelle réponse retenir ?','Écarter ce critère et examiner les faits pertinents pour le service','Appliquer la consigne pour garder le contrat','Augmenter le tarif selon l’origine','Une demande commerciale ne justifie pas un traitement discriminatoire.'),
      ('A.10','Un remplaçant conforme doit reprendre la mission. Que transmettre ?','Les seules informations nécessaires par un canal adapté','Tout l’historique privé du client','Le dossier médical de sa famille','Le partage doit rester proportionné à la mission.'),
      ('A.11','Lors d’un contrôle, un ancien bon est ouvert par erreur. Que faire ?','Présenter le bon réel de la mission sans modifier les dates','Antidater l’ancien bon','Affirmer que tous les bons sont identiques','La preuve doit correspondre aux faits.'),
      ('G.07','Le client attend dans une zone où l’arrêt est interdit. Que proposer ?','Un point autorisé et accessible avec une consigne claire','Un arrêt interdit parce que le client l’a choisi','Un passage au milieu des voies pour rejoindre la voiture','Les règles du lieu s’ajoutent à la réservation.'),
      ('G.08','Après la dépose, aucune course suivante n’est confirmée. Que prévoir ?','Le retour ou le stationnement autorisé selon les règles VTC','L’attente sur un emplacement taxi pour chercher un client','Une réservation fictive pour rester sur place','La fin de mission ne crée pas un droit à la maraude.'),
      ('A.07','Un message sexuel insistant est reçu après la course. Quel traitement choisir ?','Conserver les éléments utiles et utiliser le signalement adapté sans diffusion publique','Publier le numéro et le contenu sur les réseaux','Négocier l’arrêt des messages contre une bonne note','La protection, les preuves utiles et le signalement doivent rester adaptés à la situation.'),
      ('A.08','Si une agression immédiate est ensuite signalée, quelle priorité change ?','Protéger et alerter les services d’urgence adaptés','Attendre le bilan commercial mensuel','Commencer par publier une vidéo','Un danger immédiat nécessite une réponse urgente.'),
      ('A.12','Un geste commercial a été accordé après un incident. Que peut-on en déduire ?','Il ne règle pas nécessairement toutes les responsabilités','Toute infraction éventuelle disparaît','Toute preuve doit être supprimée','Les volets commercial, assurance et pénal ne se confondent pas.'),
      ('G.12','Une règle contradictoire est trouvée dans une vieille fiche. Que faire ?','Vérifier la source actuelle, sa date et son périmètre','Appliquer systématiquement la plus ancienne','Choisir la version la plus avantageuse sans vérification','Une veille utile rapproche le texte en vigueur et la situation réelle.')]
    chosen=rows if letter=='A' else rows[4:12]+rows[:4]+rows[-2:]
    steps=[q(ref,context,p,g,b1,b2,why,documents=docs,stage=f'Dossier professionnel · étape {i+1}') for i,(ref,p,g,b1,b2,why) in enumerate(chosen)]
    # The G sequence repeats chronology under a different review stage: retain unique exercise IDs.
    for i,ex in enumerate(steps):ex['id']=f'm{variant+1}-{i+1}-'+ex['id']
    return {'id':f'{letter.lower()}-mission-{variant+1}','title':('Lancer une activité et protéger les personnes' if letter=='A' else 'Du dossier de réservation au contrôle')+f' · cas {variant+1}','introduction':context,'exercises':steps}
