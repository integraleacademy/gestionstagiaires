"""Unseen application questions, one distinct decision for each APS sequence.

Each tuple contains the situation/question, correct choice, two plausible errors,
and the explanation shown only after submission. No text is generated at runtime.
"""

CHALLENGES = {
    '01-01': (
        "Vous surveillez un entrepôt. Le client vous demande de tenir la caisse du magasin voisin pendant la pause d'un vendeur. Aucun incident n'est signalé. Quel point doit être clarifié avant toute nouvelle tâche ?",
        "La compatibilité de cette tâche avec la mission de sécurité et son cadre d'exercice.",
        "Le montant de la caisse, l'accord du client suffisant pour changer de fonction.",
        "Le temps nécessaire, toute tâche brève étant comprise dans la surveillance.",
        "La limite d'une mission concerne aussi la nature du travail. Une proximité géographique ou une courte durée ne transforme pas une activité commerciale en mission de sécurité. La demande doit être examinée avec l'encadrement."
    ),
    '01-02': (
        "Avant une affectation, le numéro d'une carte professionnelle donne un résultat valide dans le téléservice officiel. Le nom retourné ne correspond pas à l'identité de la personne présente. Quelle conclusion retenir ?",
        "La vérification n'est pas concluante pour cette personne : faire clarifier l'identité avant l'affectation.",
        "Le résultat valide suffit, puisque le numéro a été accepté par le téléservice.",
        "Corriger le nom sur la copie afin de le faire correspondre au planning.",
        "Un numéro valide ne prouve pas que la personne devant vous est son titulaire. L'identité, l'activité autorisée et la validité doivent correspondre. Une correction de document par le poste ne résout pas l'écart."
    ),
    '01-03': (
        "Un hôtel possède un service interne et reçoit aussi une équipe d'une entreprise de sécurité. Les deux équipes portent des badges du site. Une consigne ne précise pas qui leur donne les instructions ni leur périmètre. Que demander au briefing ?",
        "Identifier les employeurs, les responsables et les missions de chaque équipe.",
        "Désigner comme chef l'agent qui connaît le mieux l'hôtel, sans autre vérification.",
        "Répartir librement les tâches entre tous les porteurs du même badge.",
        "Le badge facilite l'accès mais ne définit ni l'employeur ni la chaîne de responsabilité. Clarifier l'organisation permet d'éviter de confondre service interne et prestation extérieure."
    ),
    '01-04': (
        "La tenue prévue pour une vacation extérieure est conforme. Au début d'une averse, l'agent ajoute un poncho opaque qui masque tous les marquages. Quel contrôle effectuer ?",
        "Vérifier que la tenue effectivement portée permet toujours l'identification réglementaire.",
        "Vérifier seulement la tenue sous le poncho, puisqu'elle a déjà été contrôlée.",
        "Remplacer les marquages masqués par une présentation orale à chaque visiteur.",
        "C'est l'ensemble porté pendant la mission qui doit permettre l'identification. L'équipement de pluie doit être prévu avec l'employeur pour conserver les mentions applicables et éviter toute confusion."
    ),
    '02-01': (
        "Un agent a diffusé sans autorisation un compte rendu nominatif. Après avoir supprimé le message, il affirme que sa responsabilité ne peut plus être examinée. Quelle analyse est correcte ?",
        "La suppression limite la diffusion mais n'efface pas automatiquement les conséquences du premier envoi.",
        "La suppression rend l'envoi juridiquement inexistant.",
        "Seul le destinataire est responsable dès qu'il a ouvert le message.",
        "Une mesure corrective peut réduire les effets d'un incident. Elle ne dispense pas de signaler les faits et ne préjuge pas de l'examen des responsabilités selon les circonstances."
    ),
    '02-02': (
        "Une personne pousse violemment un visiteur. L'agent intervient pour le protéger. L'auteur est ensuite séparé du groupe, à distance, sans nouveau geste d'attaque. Comment adapter la réaction ?",
        "Réévaluer immédiatement la nécessité des mesures à partir du danger encore présent.",
        "Maintenir automatiquement la même force jusqu'à ce que l'auteur présente des excuses.",
        "Faire dépendre la force de la gravité de l'insulte prononcée après la séparation.",
        "Une réaction de défense s'apprécie au moment où elle est exercée. La protection contre une attaque et une punition après les faits n'ont pas le même objet. Le relais et la protection restent à organiser."
    ),
    '02-03': (
        "Dans un parking, un témoin appelle à l'aide depuis un local où de la fumée est visible. Vous n'êtes pas équipé pour y pénétrer. Quelle action constitue une aide adaptée ?",
        "Alerter les secours, empêcher une nouvelle exposition et donner le lieu précis depuis une zone sûre.",
        "Entrer avec le témoin pour vérifier la situation avant de téléphoner.",
        "Attendre dehors sans alerter, puisque vous ne pouvez pas entrer.",
        "Ne pas entrer dans un danger non maîtrisé n'empêche pas d'agir. La protection des tiers et une alerte précise apportent une aide sans ajouter une victime."
    ),
    '03-01': (
        "Un commerçant reconnaît sur une ancienne photographie une personne qu'il soupçonne d'un vol survenu la semaine précédente. Elle revient aujourd'hui sans commettre de fait nouveau observé. Que permet d'affirmer cette seule information ?",
        "Elle justifie de transmettre des éléments, mais ne démontre pas à elle seule les conditions de l'article 73 aujourd'hui.",
        "Elle autorise une appréhension parce que le commerçant est certain de son souvenir.",
        "Elle permet de retenir la personne le temps qu'elle prouve son innocence.",
        "Une accusation relative à des faits anciens n'établit pas, à elle seule, un crime flagrant ou un délit flagrant puni d'emprisonnement. L'agent transmet les faits et leur source sans transformer un soupçon en pouvoir d'enquête."
    ),
    '03-02': (
        "Après une appréhension dont les conditions ont été vérifiées, le magasin propose de laisser partir la personne si elle signe une reconnaissance de dette. Le relais vers l'OPJ n'a pas été organisé. Quelle priorité retenir ?",
        "Organiser sans délai la remise à l'OPJ et préserver les droits et la sécurité de la personne.",
        "Négocier le montant avant de décider s'il faut appeler la police.",
        "Attendre une signature pour que le magasin dispose d'un dossier complet.",
        "L'article 73 n'institue pas une procédure privée de négociation ou d'aveu. L'agent organise le relais prévu, sans conditionner la situation de la personne à une signature ou à un paiement."
    ),
    '04-01': (
        "Un technicien de maintenance doit vérifier un logiciel d'accueil. Il demande une exportation complète des visiteurs de l'année sur sa clé USB personnelle. L'intervention prévue ne mentionne aucun transfert. Quelle décision retenir ?",
        "Faire valider le besoin, l'habilitation et le moyen sécurisé avant toute communication de données.",
        "Fournir le fichier puisque le technicien intervient déjà sur l'ordinateur.",
        "Retirer les noms puis transmettre tous les téléphones et horaires sans autre contrôle.",
        "L'accès technique à un outil ne vaut pas autorisation générale d'emporter ses données. Les téléphones et horaires peuvent aussi identifier des personnes. La demande doit suivre le circuit prévu et rester limitée au besoin autorisé."
    ),
    '05-01': (
        "Lors d'un contrôle d'accès, une visiteuse malentendante vous demande de montrer la consigne par écrit. Elle possède les justificatifs requis. Quelle conduite respecte l'égalité de traitement ?",
        "Adapter la manière d'expliquer la même règle sans ajouter de condition d'accès injustifiée.",
        "Refuser l'accès parce que toutes les personnes doivent comprendre l'annonce orale.",
        "Supprimer tous les contrôles pour éviter de prolonger l'échange.",
        "L'égalité ne consiste pas à imposer un moyen de communication inadapté. L'agent peut rendre la règle accessible tout en maintenant les conditions objectives prévues."
    ),
    '05-02': (
        "Une zone technique impose à tous les visiteurs une protection de tête prévue au briefing. Un visiteur portant un couvre-chef religieux demande comment respecter cette exigence. Que faire ?",
        "Expliquer le risque et faire rechercher une solution compatible avec la protection, sans jugement sur sa conviction.",
        "Refuser toute discussion en invoquant une interdiction générale des signes religieux sur les sites privés.",
        "Autoriser l'entrée sans protection pour éviter d'aborder la difficulté.",
        "L'analyse porte sur la règle de sécurité réellement applicable et sur la compatibilité de l'équipement. Elle ne repose ni sur une interdiction générale inventée ni sur l'abandon de la protection."
    ),
    '05-03': (
        "Un règlement intérieur exige que les visiteurs montrent le contenu de leurs messages privés à l'agent d'accueil. Le responsable affirme qu'une règle affichée doit toujours être exécutée. Quel raisonnement retenir ?",
        "Vérifier la compatibilité de la demande avec les droits et le cadre légal avant de l'appliquer.",
        "Appliquer la règle dès lors que le visiteur a franchi l'entrée.",
        "Considérer l'accord du responsable comme un pouvoir d'enquête confié à l'agent.",
        "Une consigne locale ne se place pas au-dessus des droits et des textes applicables. La demande doit être signalée et clarifiée par la hiérarchie ; son affichage ne crée pas de nouveaux pouvoirs."
    ),
    '06-01': (
        "Votre cousin arrive pour une livraison sans le document exigé par la procédure. Il ne propose aucun cadeau, mais vous demande de faire une exception familiale. Quelle décision prendre ?",
        "Appliquer la procédure et faire traiter l'écart par le circuit prévu.",
        "Laisser passer puisque vous pouvez personnellement garantir son identité.",
        "Inscrire un faux numéro de livraison pour éviter un blocage informatique.",
        "Un passe-droit peut découler d'un lien personnel sans avantage financier. La probité impose de ne pas remplacer les vérifications prévues par une faveur et de tracer honnêtement la demande."
    ),
    '06-02': (
        "En transport en commun après votre service, un collègue vous demande au téléphone les détails nominaux d'un incident. Des passagers entendent l'échange. Que faire ?",
        "Reporter les informations confidentielles vers un canal professionnel et un lieu adaptés.",
        "Continuer puisque le correspondant travaille dans la même entreprise.",
        "Énoncer seulement les noms, sans préciser le nom du site.",
        "La qualité du destinataire ne suffit pas : le contexte de transmission compte aussi. Les informations doivent rester accessibles aux seules personnes autorisées, y compris après la vacation."
    ),
    '06-03': (
        "Pendant un contrôle, un document demandé n'est pas immédiatement disponible au poste. Votre collègue propose d'en rédiger une version antidatée pour combler le manque. Quelle conduite retenir ?",
        "Expliquer l'indisponibilité, prévenir le responsable et rechercher la pièce authentique par le circuit prévu.",
        "Reconstituer le document en le présentant comme celui utilisé lors de la vacation.",
        "Refuser toute autre vérification jusqu'à ce que le document soit retrouvé.",
        "Coopérer implique une information sincère. Un document manquant se signale et se recherche ; sa fabrication ou son altération fausse le contrôle. La surveillance du poste reste organisée."
    ),
    '06-04': (
        "Un client demande d'effacer une anomalie de la main courante avant l'envoi du compte rendu. Les faits ont été constatés et le responsable de sécurité n'a pas validé de correction. Que faire ?",
        "Conserver une trace fidèle et faire examiner la demande par l'encadrement.",
        "Effacer l'anomalie puisque le client est propriétaire du bâtiment.",
        "Remplacer l'anomalie par une mention rassurante sans indiquer le changement.",
        "Une correction sert à rétablir l'exactitude, pas à dissimuler un fait. La demande commerciale ne justifie pas la falsification d'une trace professionnelle."
    ),
    '07-01': (
        "Une borne d'accueil affiche un mauvais numéro de guichet. Plusieurs personnes reviennent mécontentes, mais restent à distance et ne menacent personne. Quel élément traiter en priorité pour limiter la tension ?",
        "L'information erronée et l'absence d'explication sur l'orientation.",
        "Le caractère supposé agressif de toutes les personnes qui reviennent.",
        "La sanction des premières personnes ayant exprimé leur mécontentement.",
        "Le déclencheur observable est ici un dysfonctionnement d'accueil. Corriger l'information et expliquer la suite permet d'agir sur la cause sans attribuer une intention dangereuse sans faits."
    ),
    '07-02': (
        "Un livreur répète qu'il va perdre sa tournée si le quai reste fermé. Vous ne pouvez pas autoriser l'ouverture. Quelle réponse écoute le besoin sans promettre ce que vous ne maîtrisez pas ?",
        "« Vous devez repartir rapidement. Je contacte le responsable du quai pour connaître la solution autorisée. »",
        "« Vous passerez dans deux minutes, je vous le garantis. »",
        "« Votre planning ne concerne pas le poste de sécurité. »",
        "La reformulation reconnaît la contrainte du livreur et annonce une action réalisable. Elle ne transforme pas l'écoute en promesse d'accès ou de délai non confirmé."
    ),
    '07-03': (
        "Dans une petite loge, une personne mécontente se trouve entre vous et la seule sortie. L'échange reste verbal. Quel aménagement peut réduire votre exposition ?",
        "Proposer calmement de poursuivre vers un espace permettant de garder une distance et un dégagement.",
        "S'approcher pour la pousser contre le bureau et libérer le passage.",
        "Fermer la porte pour empêcher l'arrivée de témoins.",
        "L'espace disponible et les possibilités de dégagement participent à la protection. Une réorganisation calme et un appui adapté peuvent éviter l'encerclement sans transformer l'échange en confrontation physique."
    ),
    '07-04': (
        "Une personne filme le contrôle et vous insulte. Elle reste à distance. Un collègue vous propose de prendre son téléphone pour obtenir le calme. Quelle réponse choisir ?",
        "Rester centré sur le comportement, poser une limite verbale et demander un appui si la tension monte.",
        "Saisir le téléphone jusqu'à ce que les insultes cessent.",
        "Répondre par une insulte pour rétablir une relation équilibrée.",
        "L'objectif est d'empêcher l'escalade et de protéger les personnes. Une insulte ne crée pas un pouvoir général de confiscation. L'agent utilise les moyens adaptés au danger effectivement observé."
    ),
    '07-05': (
        "Après un désaccord résolu au contrôle d'accès, vous constatez que le courriel d'invitation et l'affiche du hall donnent encore deux horaires différents. Quelle suite est utile ?",
        "Signaler la contradiction à corriger et transmettre la solution appliquée à la relève.",
        "Clore toute action puisque le dernier visiteur est désormais calme.",
        "Supprimer l'affiche sans prévenir afin que la contradiction disparaisse.",
        "La résolution immédiate et la prévention d'une nouvelle tension sont complémentaires. Une trace factuelle et la correction validée de l'information permettent à l'équipe de ne pas reproduire le conflit."
    ),
    '08-01': (
        "Une consigne signée prévoit l'accès des prestataires au bâtiment C. Une demande orale ajoute le local technique du bâtiment D, absent de la consigne. Quel élément doit être clarifié ?",
        "La portée de l'autorisation et la validation de cette extension de zone.",
        "Uniquement la capacité du badge à ouvrir le bâtiment D.",
        "Uniquement l'heure de départ du prestataire.",
        "Lire une consigne signifie aussi vérifier son champ d'application. Un badge qui fonctionne ou une demande orale ne suffit pas à établir un droit d'accès à une autre zone."
    ),
    '08-02': (
        "Vous observez de l'eau qui s'écoule près d'un tableau électrique dans le couloir est, niveau 1. Personne n'est blessé ; vous maintenez les usagers à distance. Quel message aide le PC à décider ?",
        "« Couloir est, niveau 1 : écoulement près du tableau électrique. Pas de blessé observé. Passage protégé. Je demande le relais technique prévu. »",
        "« Ça recommence, il faut venir vite avec ce qu'il faut. »",
        "« Le bâtiment entier est certainement hors service, envoyez tout le monde. »",
        "Le lieu, les faits observés, la protection engagée et le besoin permettent de coordonner la réponse. Une hypothèse globale ou un message vague oblige le PC à deviner."
    ),
    '08-03': (
        "Le PC reçoit à 10 h 20 le récit d'un événement qu'un témoin situe vers 10 h 05. L'agent n'y a pas assisté. Comment consigner les horaires ?",
        "Distinguer l'heure de réception et l'heure approximative de l'événement, attribuée au témoin.",
        "Écrire que l'agent a constaté les faits à 10 h 05.",
        "Remplacer tous les horaires par 10 h 20 pour simplifier la chronologie.",
        "L'heure d'un fait, celle de son signalement et la précision de la source ne se confondent pas. Leur distinction permet de reconstituer ce qui était connu à chaque moment."
    ),
    '08-04': (
        "Un témoin affirme avoir vu une personne forcer une porte. Vous constatez seulement une rayure sur la poignée. Quelle formulation est fidèle ?",
        "« Une rayure est observée sur la poignée ; selon le témoin, une personne aurait forcé la porte. »",
        "« L'effraction est confirmée par l'agent. »",
        "« Le témoin ment puisque seule une rayure est visible. »",
        "Le rapport distingue votre constat de la déclaration reçue. Il ne transforme ni le récit en certitude personnelle ni l'absence d'observation en preuve que le témoin se trompe."
    ),
    '08-05': (
        "À la relève, une intervention technique est annoncée pour 22 h, mais le nom de l'intervenant et son accès restent à confirmer. Quelle transmission est exploitable ?",
        "Préciser l'intervention attendue, les vérifications encore ouvertes et le contact chargé de les confirmer.",
        "Indiquer seulement qu'une intervention est prévue et que tout est réglé.",
        "Transmettre le nom d'un technicien habituel même s'il n'est pas confirmé.",
        "Une relève utile comprend les suites en attente et leur responsable. Elle ne complète pas les informations manquantes par des suppositions et ne présente pas une action prévue comme achevée."
    ),
    '09-01': (
        "Vous rédigez le compte rendu d'une intervention. Votre seule observation directe commence lorsque les protagonistes sont déjà séparés. Un collègue vous raconte le début. Comment présenter les éléments utiles à l'analyse de la défense ?",
        "Séparer ce que vous avez vu du récit du collègue et indiquer les moments encore incertains.",
        "Présenter tout le récit à la première personne pour rendre le rapport plus cohérent.",
        "Conclure à la légitime défense parce qu'un membre de l'équipe l'affirme.",
        "La justification doit pouvoir être confrontée aux faits, à leur chronologie et à leur source. Un récit rapporté peut être utile s'il reste clairement attribué ; il ne devient pas votre observation."
    ),
    '09-02': (
        "Un ascenseur est bloqué avec une personne qui dit se sentir mal. Vous ne savez pas où se trouve exactement la cabine et vous n'êtes pas habilité à intervenir sur l'appareil. Que faire ?",
        "Alerter les secours et le relais technique prévu, maintenir le contact et transmettre les informations disponibles.",
        "Forcer immédiatement une porte palière pour chercher la cabine.",
        "Attendre uniquement le prochain passage du mainteneur sans signaler le malaise.",
        "L'urgence appelle une aide immédiate dans le champ de compétence de l'agent. L'alerte, le contact et la protection sont utiles ; une manœuvre technique improvisée peut créer un danger supplémentaire."
    ),
    '09-03': (
        "Après une dispute commerciale, le client vous demande de bloquer le véhicule d'un prestataire pour l'obliger à rendre un outil. Vous n'avez pas observé de faits établissant le cadre d'une appréhension. Que répondre ?",
        "Faire traiter le différend par les interlocuteurs compétents sans créer une contrainte sur cette seule demande.",
        "Bloquer la sortie jusqu'à ce que les deux parties trouvent un accord.",
        "Prendre les clés du véhicule, ce qui évite de toucher directement la personne.",
        "Le litige signalé ne crée pas à lui seul un pouvoir de contrainte privée. L'agent protège le site et rend compte des faits sans devenir l'instrument d'un recouvrement ou d'une restitution forcée."
    ),
    '10-01': (
        "Sur un quai, des piétons traversent la trajectoire d'un engin de manutention. Aucun accident n'a encore eu lieu. Quel élément caractérise le risque ?",
        "L'exposition des piétons à un engin en mouvement et la possibilité d'une collision.",
        "Uniquement le nombre d'accidents déjà enregistrés sur ce quai.",
        "Uniquement la présence d'un panneau de danger à l'entrée.",
        "Le danger existe avant l'accident. Le risque s'analyse avec l'exposition et les dommages possibles ; l'absence d'accident passé ne dispense pas de traiter une circulation dangereuse."
    ),
    '10-02': (
        "Un nouvel itinéraire de ronde traverse désormais une zone de circulation d'engins. La durée de la ronde reste identique. Que doit faire remonter l'agent ?",
        "Le changement d'exposition pour faire réexaminer les risques et les mesures de prévention.",
        "Aucun changement, puisque le temps de travail n'augmente pas.",
        "Seulement le nombre de pas supplémentaires si l'itinéraire est plus long.",
        "L'évaluation porte sur les situations de travail réelles. Un changement de trajet peut créer un nouveau risque sans modifier la durée, l'effectif ou le matériel porté par l'agent."
    ),
    '10-03': (
        "Une entreprise nettoie un sol pendant qu'une autre déplace des charges dans le même passage. Chaque équipe dit respecter ses propres consignes, mais aucune coordination du passage n'est connue du poste. Que signaler ?",
        "L'interférence entre les activités et la nécessité d'une coordination par les responsables compétents.",
        "Seulement l'entreprise arrivée en dernier, car la première garde la priorité.",
        "Aucune anomalie puisque chaque entreprise possède ses propres consignes.",
        "La coactivité crée des risques liés aux interactions. Des procédures séparées ne garantissent pas à elles seules que le passage commun, les horaires et les protections sont compatibles."
    ),
    '10-04': (
        "Au briefing industriel, deux plans présentent des points de regroupement différents selon le type d'alerte. L'agent connaît uniquement celui utilisé lors du dernier exercice incendie. Quel préalable est nécessaire ?",
        "Identifier le signal reçu et la consigne applicable au scénario avant d'orienter les personnes.",
        "Choisir systématiquement le point utilisé lors du dernier exercice.",
        "Choisir le point le plus proche sans vérifier le danger concerné.",
        "Les mesures de protection dépendent de l'événement et de l'organisation prévue. Un itinéraire ou un regroupement adapté à un exercice ne se transpose pas automatiquement à toute alerte industrielle."
    ),
    '10-05': (
        "Un accès à une plateforme a perdu sa protection collective. Un salarié propose de laisser passer les visiteurs en leur donnant un casque. Quelle analyse retenir ?",
        "Le casque ne compense pas le risque de chute lié à la protection collective absente.",
        "Le casque permet le passage si chaque visiteur signe une décharge.",
        "Un passage très rapide supprime le besoin d'une protection collective.",
        "Une protection se choisit en fonction du risque. Un équipement destiné à un type de dommage ne remplace pas une protection collective manquante ; l'accès doit être traité selon la procédure de mise en sécurité."
    ),
    '10-06': (
        "Un flacon non étiqueté est découvert dans un placard technique. Un salarié affirme que son odeur permet de l'identifier comme un produit courant. Quelle conduite retenir ?",
        "Éviter les manipulations et faire identifier le produit par le circuit compétent avec les documents disponibles.",
        "Le sentir de près pour confirmer l'avis du salarié.",
        "Le transvaser dans un récipient étiqueté avec le nom supposé.",
        "L'odeur et l'habitude ne constituent pas une identification fiable. Une manipulation ou un étiquetage supposé peut exposer les personnes et créer une information fausse pour l'équipe suivante."
    ),
    '10-07': (
        "Une radio est remplacée par un modèle identique d'apparence avant une ronde en zone ATEX. La compatibilité du nouvel appareil n'a pas été vérifiée. Que faire ?",
        "Faire vérifier l'adéquation du nouvel équipement à la zone avant de l'y utiliser.",
        "L'utiliser puisqu'il possède les mêmes boutons que l'ancien.",
        "Le couvrir d'une housse ordinaire pour le rendre compatible.",
        "La ressemblance et le fonctionnement apparent ne prouvent pas l'adéquation à une atmosphère explosive. L'agent suit les prescriptions du site et fait vérifier l'équipement avant son introduction."
    ),
    '11-01': (
        "Une armoire électrique présente une porte détériorée. L'éclairage du couloir fonctionne normalement. Un collègue en déduit qu'il n'y a aucun danger. Quelle décision retenir ?",
        "Protéger l'accès et signaler l'anomalie sans ouvrir ni réparer l'armoire.",
        "Ouvrir l'armoire pour vérifier visuellement si les fils sont bien fixés.",
        "Ignorer l'anomalie tant que l'éclairage fonctionne.",
        "Le fonctionnement d'une installation ne démontre pas son innocuité. Une enveloppe détériorée peut exposer à des éléments dangereux ; l'agent protège et alerte le personnel compétent sans intervention improvisée."
    ),
    '11-02': (
        "Après un accident près d'un appareil électrique, un témoin annonce avoir actionné un interrupteur. La suppression du danger n'est pas confirmée. Il vous demande de toucher la victime pour vérifier son état. Que faire d'abord ?",
        "Faire établir la sécurité électrique, alerter et empêcher les autres personnes de s'exposer.",
        "Toucher la victime brièvement puisque l'interrupteur a été actionné.",
        "Déplacer l'appareil à mains nues pour l'éloigner avant toute alerte.",
        "L'action annoncée sur un interrupteur ne garantit pas à elle seule la suppression de toutes les sources de danger. La protection et l'alerte précèdent le contact avec une victime encore potentiellement exposée."
    ),
    '12-01': (
        "Un réseau social diffuse une photographie présentée comme une menace contre votre site. La même image semble provenir d'un événement ancien dans une autre ville. Que transmettre au PC ?",
        "Le signalement avec sa source et l'incertitude sur la date et le lieu, sans le présenter comme une alerte officielle.",
        "Une alerte confirmée, car la photographie paraît réaliste.",
        "Aucune information : une incohérence de date exclut tout intérêt pour le poste.",
        "L'agent distingue une information reçue d'un fait confirmé. Il transmet ce qui peut être utile au circuit de vérification, avec ses limites, sans amplifier une rumeur ni écarter seul une alerte."
    ),
    '12-02': (
        "Un colis présente des éléments inhabituels près d'un accueil. Une personne dit reconnaître un emballage de livraison ordinaire mais personne n'en confirme l'origine. Que faire ?",
        "Garder les distances, protéger les personnes et appliquer le circuit d'alerte sans manipuler le colis.",
        "Ouvrir l'emballage pour vérifier si son contenu correspond à une livraison.",
        "Le déplacer vers une poubelle afin de dégager l'accueil.",
        "Une ressemblance visuelle ne permet pas d'écarter un danger. L'agent n'a pas à déterminer la composition de l'objet ; il met en œuvre la protection et l'alerte prévues sans s'exposer."
    ),
    '12-03': (
        "Le PC reçoit une mesure renforcée validée pour un événement particulier. Un agent veut l'appliquer sans limite de durée à tous les autres sites de l'entreprise. Quelle vérification effectuer ?",
        "Vérifier le périmètre, la durée et les modalités de la mesure auprès du circuit de consignes compétent.",
        "Généraliser toute mesure renforcée, quel que soit son champ annoncé.",
        "Ignorer la mesure parce qu'elle diffère de l'affiche habituelle.",
        "Une mesure opérationnelle se lit avec son champ d'application. L'agent suit les instructions validées et actualisées pour son site, sans les étendre arbitrairement ni s'en tenir à un ancien affichage."
    ),
    '12-04': (
        "Deux visiteurs consultent le plan public du bâtiment. L'un tente ensuite d'emprunter trois fois une porte signalée comme réservée malgré les indications données. Quel fait mérite un signalement précis ?",
        "Les tentatives répétées d'utiliser l'accès réservé, avec le lieu et les horaires observés.",
        "Le fait que les visiteurs parlent une langue que l'agent ne comprend pas.",
        "L'intention certaine de préparer une attaque.",
        "Le signalement décrit un comportement observable et son contexte. Il ne déduit pas une intention certaine ni un niveau de danger de la langue ou de l'apparence d'une personne."
    ),
    '12-05': (
        "Un appelant évoque une menace puis la communication coupe. Vous avez entendu un lieu, mais un mot reste incertain. Quelle transmission est la plus utile ?",
        "Rapporter les mots entendus, l'heure et le lieu évoqué en signalant explicitement le mot incertain.",
        "Compléter le mot par celui qui paraît le plus probable et le présenter comme certain.",
        "Attendre un second appel avant de prévenir le PC.",
        "La transmission rapide conserve les paroles utiles et leur degré de certitude. Une lacune clairement signalée vaut mieux qu'un détail inventé qui orienterait la réponse au mauvais endroit."
    ),
    '12-06': (
        "Un message présenté comme venant du service informatique demande de communiquer le code d'accès du poste de sécurité pour une intervention urgente. Le numéro de rappel indiqué est inconnu. Que faire ?",
        "Vérifier la demande par un contact officiel déjà connu et ne pas communiquer le code sur cette seule sollicitation.",
        "Rappeler le numéro contenu dans le message et lui dicter le code.",
        "Envoyer le code puis le changer après l'intervention annoncée.",
        "L'urgence affichée ne démontre pas l'identité du demandeur. Une vérification indépendante et la protection des accès limitent le risque de détourner les outils de sécurité."
    ),
    '12-07': (
        "Après une explosion signalée, un témoin vous indique depuis une zone sûre qu'une personne respire difficilement. L'accès à la victime n'est pas sécurisé. Quelle information transmettre en priorité aux secours ?",
        "Le lieu, le danger encore possible et la difficulté respiratoire rapportée, en précisant la source du renseignement.",
        "Un diagnostic certain de lésion interne, même sans examen.",
        "Seulement le nombre de débris visibles, avant de parler de la victime.",
        "L'alerte utile décrit les signes disponibles et les conditions d'accès. L'agent ne transforme pas le récit en diagnostic et ne pénètre pas dans une zone non sécurisée pour compléter son message."
    ),
    '13-01': (
        "Vous avez laissé la main courante électronique ouverte sous votre compte. À votre retour, une ligne ajoutée par un collègue porte votre identité. Quel problème traiter ?",
        "La traçabilité de l'auteur : signaler l'écart, le corriger selon la procédure et sécuriser la session.",
        "Aucun problème, puisque le collègue appartient à la même équipe.",
        "Effacer toute la vacation pour supprimer le nom erroné.",
        "Un compte nominatif relie les opérations à leur auteur. Une session partagée fausse cette trace. La correction doit rester traçable et ne pas supprimer les autres faits de la vacation."
    ),
    '13-02': (
        "Après une panne, le logiciel est rétabli. Vous avez consigné deux événements sur le support de secours autorisé, avec leurs heures. Comment reprendre le suivi ?",
        "Reporter les événements selon la procédure en distinguant l'heure des faits et celle de la saisie différée.",
        "Enregistrer les deux faits à l'heure de reconnexion comme s'ils venaient de se produire.",
        "Détruire le support de secours avant de vérifier la reprise complète des informations.",
        "La continuité nécessite de réintégrer les informations sans réécrire leur chronologie. Le support de secours et sa conservation suivent les règles du site jusqu'à la vérification de la reprise."
    ),
    '14-01': (
        "Pendant une ronde d'entrepôt, vous découvrez un véhicule arrêté près d'un portail de livraison. Le conducteur dit attendre un créneau ; vous n'avez pas encore vérifié le planning. Quelle première décision est adaptée ?",
        "Vérifier les éléments par le circuit du site et préserver la sécurité des accès sans conclure immédiatement à une infraction.",
        "Immobiliser le conducteur parce qu'il attend près d'un accès réservé.",
        "Laisser entrer le véhicule pour faciliter ensuite la vérification.",
        "La présence observée et l'explication fournie constituent des éléments à vérifier. L'agent contrôle l'accès et protège le site dans son cadre de mission ; il ne déduit pas automatiquement un délit d'une situation inhabituelle."
    ),
    '14-02': (
        "Une personne transporte un carton vers la sortie d'un magasin. Le vendeur reconnaît l'emballage mais ignore s'il a été payé ou retiré au service après-vente. Quel élément manque à la décision ?",
        "Des faits permettant de distinguer une sortie autorisée d'une soustraction.",
        "La preuve apportée par le client qu'il n'a jamais commis de vol.",
        "L'accord du vendeur pour fouiller immédiatement ses poches.",
        "Le transport d'un article ne démontre pas à lui seul un vol. L'agent distingue constat, information à vérifier et conditions juridiques de l'action envisagée, sans inverser la charge de justification par une contrainte improvisée."
    ),
    '14-03': (
        "L'agent qui tient une fonction essentielle de sécurité incendie reçoit une demande d'accompagnement d'un visiteur vers son véhicule. Aucun remplaçant n'est désigné. Quel point doit être résolu ?",
        "La continuité de la fonction de sécurité et la répartition des missions avant tout départ du poste.",
        "Uniquement la durée estimée de l'accompagnement.",
        "Uniquement la priorité commerciale du visiteur.",
        "Le fait de porter une tenue de sécurité ne rend pas les fonctions interchangeables. Une demande doit être organisée sans laisser une mission essentielle sans continuité."
    ),
    '14-04': (
        "Pendant une intervention, la personne cesse de résister et s'assoit calmement. Un collègue veut conserver exactement les mêmes mesures physiques parce qu'elles étaient justifiées au début. Que rappeler ?",
        "La nécessité et la proportion des mesures doivent être réexaminées avec le comportement et l'état de santé actuels.",
        "Une mesure initialement justifiée reste justifiée jusqu'à la clôture administrative de l'incident.",
        "L'absence de résistance permet de prolonger la contrainte pour faciliter le compte rendu.",
        "La décision n'est pas figée. Un changement de comportement, de danger ou d'état de santé oblige à réévaluer les moyens employés et à organiser le relais adapté."
    ),
    '14-05': (
        "Une caméra peut contenir des images utiles à un incident. Un agent propose de les copier sur son téléphone avant leur écrasement automatique. Quelle action privilégier ?",
        "Signaler rapidement le besoin de conservation au service habilité par le circuit sécurisé prévu.",
        "Copier d'abord sur un téléphone personnel et demander une autorisation ensuite.",
        "Diffuser les images dans le groupe de l'équipe pour multiplier les sauvegardes.",
        "Préserver un élément utile ne signifie pas en multiplier les copies personnelles. Le délai de conservation doit être signalé pour permettre au service habilité d'agir dans un cadre traçable et sécurisé."
    ),
    '14-06': (
        "La police arrive. Votre collègue a observé le début de l'incident ; vous avez seulement assuré la protection et recueilli les coordonnées d'un témoin volontaire. Comment organiser la remise ?",
        "Présenter la chronologie, les actions de chacun et la source de chaque information, puis indiquer les éléments disponibles.",
        "Désigner un seul agent comme témoin direct de toute la scène pour simplifier l'entretien.",
        "Commencer par les suppositions sur le passé de la personne concernée.",
        "Une transmission exploitable sépare les rôles, les observations et les déclarations. L'interlocuteur compétent doit pouvoir identifier ce qui est établi et ce qui reste à vérifier."
    ),
    '14-07': (
        "Vous recevez deux signalements concernant une porte : un témoin parle d'une entrée forcée, le technicien évoque une intervention programmée. Vous n'avez pas encore vérifié le chantier. Quelle démarche retenir ?",
        "Croiser les informations avec les interlocuteurs identifiés tout en maintenant les mesures de protection nécessaires.",
        "Retenir uniquement le premier appel, puisqu'il est arrivé avant l'autre.",
        "Classer immédiatement l'alerte parce qu'une explication technique est possible.",
        "Des versions différentes imposent de conserver les sources et de vérifier les faits. Une explication plausible ne devient pas une confirmation ; l'incertitude n'autorise pas non plus une contrainte sans fondement."
    ),
    '15-01': (
        "Avant l'ouverture d'une exposition, la billetterie vous demande de décider seul d'une modification du dispositif de sécurité. Le briefing attribue cette décision au responsable du dispositif. Que faire ?",
        "Transmettre le besoin au responsable identifié et obtenir une instruction coordonnée avant la modification.",
        "Accepter la demande de la billetterie, qui connaît le nombre de visiteurs attendus.",
        "Laisser chaque agent choisir l'organisation de son accès.",
        "Les fonctions commerciales, de contrôle et de coordination ont des responsabilités distinctes. Une modification du dispositif doit suivre la chaîne définie pour que les postes appliquent des décisions compatibles."
    ),
    '15-02': (
        "Une accréditation autorise un prestataire à entrer dans une zone technique jusqu'à 16 h avec accompagnement. Il revient seul à 17 h en montrant le même badge. Quelle vérification effectuer ?",
        "Faire confirmer une autorisation correspondant à l'heure et aux conditions réelles de sa nouvelle demande.",
        "Le laisser entrer parce que le badge a déjà été accepté dans la journée.",
        "Considérer que seule la zone compte, sans tenir compte de l'accompagnement.",
        "Le droit d'accès peut dépendre de la personne, du lieu, de la période et de conditions particulières. Une admission précédente ne vaut pas autorisation permanente."
    ),
    '15-03': (
        "Un second contrôle est installé après la billetterie. Sa capacité est plus faible et le public s'accumule entre les deux postes. Quel élément transmettre pour organiser la réponse ?",
        "L'emplacement de l'accumulation, son évolution et la différence de débit entre les deux postes.",
        "Uniquement le nombre total de billets vendus depuis le début de la journée.",
        "L'ordre de supprimer le second contrôle sans coordination avec le responsable.",
        "Une file dépend aussi de la capacité du poste situé en aval. Les observations sur l'accumulation permettent au responsable d'ajuster les flux sans supprimer arbitrairement une mesure de contrôle."
    ),
    '15-04': (
        "À une sortie de spectacle, plusieurs personnes disent ne plus pouvoir avancer ni reculer dans un passage. Vous ne voyez pas toute la zone. Quelle transmission est adaptée ?",
        "Signaler immédiatement la perte de mobilité rapportée, la zone concernée et les limites de votre observation.",
        "Attendre de voir personnellement une chute avant de signaler la situation.",
        "Annoncer que toute la foule panique, même sans observation correspondante.",
        "La perte de liberté de mouvement et la pression sont des signes à transmettre rapidement. L'agent précise ce qu'il observe ou recueille sans attendre l'accident ni généraliser au-delà des faits."
    ),
    '15-05': (
        "Une mise en sécurité est engagée. La voie prévue reste praticable, mais un groupe repart en sens inverse parce qu'il ne comprend pas la consigne. Que faire dans le dispositif coordonné ?",
        "Donner une indication courte et cohérente avec le circuit validé, puis signaler la difficulté au responsable.",
        "Inventer un nouvel itinéraire pour ce groupe sans informer les autres postes.",
        "Multiplier les annonces contradictoires pour attirer davantage l'attention.",
        "La cohérence des messages et la compréhension du public sont nécessaires à une mise en sécurité. Une difficulté se traite avec l'équipe, sans créer des flux opposés par des décisions isolées."
    ),
    '15-06': (
        "Une journaliste accréditée demande d'entrer dans la zone d'intervention des secours pour photographier un incident. Son badge autorise seulement l'espace presse. Quelle réponse retenir ?",
        "L'orienter vers l'interlocuteur et la zone autorisés en préservant l'accès et le travail des secours.",
        "Laisser entrer toute personne accréditée dans toutes les zones de l'événement.",
        "Retenir son matériel pour l'empêcher de présenter une nouvelle demande.",
        "Le rôle d'une personne et son accréditation ne lui donnent pas un accès universel. L'agent respecte les zones, les consignes et la priorité opérationnelle des intervenants."
    ),
    '15-07': (
        "Deux portails signalent en même temps des billets refusés après une panne de réseau. Les visiteurs présentent des confirmations d'achat. Quel élément doit guider la réponse ?",
        "La possibilité d'un incident technique à faire vérifier par la billetterie, tout en organisant l'attente et les flux.",
        "La certitude que tous les porteurs de billets refusés utilisent de faux billets.",
        "L'autorisation pour chaque agent d'ignorer définitivement tous les contrôles.",
        "Un message de refus doit être interprété avec le contexte de fonctionnement de l'outil. Le relais habilité vérifie les droits d'entrée ; l'agent préserve un accueil calme et une circulation sûre."
    ),
}
