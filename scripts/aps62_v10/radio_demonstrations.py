"""Spoken, fictional demonstrations tied to the course examples, never to productions.

Each scene states its extra fictional facts before the dialogue. No personal title,
medical record or access credential is broadcast on a shared radio channel.
"""


def _dialogue(context, first, response, readback, *, private=False, agent="Agent", receiver=None):
    receiver = receiver or ("Chef de poste" if private else "PC")
    return {
        "title": "Échange confidentiel au poste" if private else "Transmission et confirmation",
        "type": "post_exchange" if private else "radio",
        "context": context,
        "turns": [
            {"speaker": agent, "text": first},
            {"speaker": receiver, "text": response},
            {"speaker": agent, "text": readback},
        ],
    }


RADIO_DEMONSTRATIONS = {
    "aps62-01-01": _dialogue(
        "Exemple fictif au centre Horizon. L'agent Accueil reste dans le hall ; le gestionnaire vient de demander des photos du commerce voisin.",
        "PC de Accueil. Je suis au hall. Le gestionnaire demande des photos des voitures du commerce voisin. Je n'ai constaté aucun incident sur notre site. Je reste à mon poste et demande votre arbitrage.",
        "Accueil de PC. Reçu. Maintenez le contrôle du hall. Je prends contact avec notre responsable pour clarifier cette demande extérieure à la mission.",
        "Reçu. Je conserve le poste du hall et j'attends votre retour avant toute autre action."),
    "aps62-01-02": _dialogue(
        "Exemple fictif : entretien au poste, hors du canal radio collectif. Le remplacement n'a pas encore pris son service.",
        "La remplaçante est à l'accueil du personnel. Son diplôme est présenté, mais la capture indique une demande de carte encore en instruction. Je n'ai pas de droit d'exercer vérifié pour son affectation.",
        "Je fais contrôler le titre et l'activité par le service habilité. Elle ne prend pas seule le contrôle d'accès sur la base de cette capture. J'organise la continuité du poste.",
        "Compris. Je vous transmets les documents par le circuit RH prévu, sans les communiquer sur la radio.", private=True),
    "aps62-01-03": _dialogue(
        "Exemple fictif : le chef de poste du service interne échange avec son agent dans le bureau. La ronde du site voisin n'a pas commencé.",
        "Le directeur demande une ronde facturée à l'entreprise voisine. Notre planning concerne l'usine, et je n'ai aucun document validant cette prestation extérieure. Je n'ai pas quitté mon secteur.",
        "Je transmets la demande à la direction compétente pour vérifier son cadre. Maintenez la mission de l'usine ; nous organiserons ensuite les moyens selon la décision validée.",
        "D'accord. Je reste sur le périmètre de l'usine et je signale toute nouvelle instruction contradictoire.", private=True),
    "aps62-01-04": _dialogue(
        "Exemple fictif au vestiaire d'un salon, avant prise de poste. La veste de remplacement est encore sur son cintre.",
        "Cette veste porte un écusson ressemblant à celui d'une force publique, et mes identifiants seraient masqués. Je ne l'ai pas utilisée pour accueillir le public. Quelle dotation conforme puis-je prendre ?",
        "Gardez la veste à l'écart. Je fais apporter la dotation prévue et nous vérifierons ensemble les marquages visibles avant votre affectation.",
        "Compris. Je me présenterai comme agent de sécurité privée du salon, avec la dotation vérifiée.", private=True),
    "aps62-02-01": _dialogue(
        "Exemple fictif après un incident avec une barrière d'entrepôt. L'agent rend compte au chef de poste, à l'écart du public.",
        "À 9 h 12, à l'entrée véhicules, j'ai fermé la barrière et un visiteur a signalé une marque sur son capot. Il indique avoir déposé plainte. Je prépare la chronologie et je distingue ses déclarations de ce que j'ai vu.",
        "Conservez cette distinction. Le remboursement éventuel, la plainte et l'examen professionnel ne se confondent pas. Transmettez les faits et les pièces par notre procédure.",
        "Je note les sources et les heures ; je ne conclus pas moi-même à la responsabilité de chacun.", private=True),
    "aps62-02-02": _dialogue(
        "Exemple fictif au portillon sud. L'agent Accès 2 est derrière le dispositif d'accueil ; le visiteur s'éloigne sans nouvelle attaque observée.",
        "PC de Accès 2, portillon sud. Le visiteur qui a tenté de me frapper s'éloigne maintenant vers la sortie. Je ne vois plus de geste d'attaque. Je maintiens la distance et demande un appui au poste.",
        "Accès 2 de PC. Reçu, je vous envoie l'appui prévu. Maintenez l'observation en sécurité et annoncez immédiatement tout changement.",
        "Reçu. Je ne le poursuis pas ; je vous informe si une nouvelle menace apparaît."),
    "aps62-02-03": _dialogue(
        "Exemple fictif dans une résidence. L'agent s'est éloigné du couloir où une odeur inconnue était perçue et communique depuis une position sûre.",
        "PC de Ronde 1. Bâtiment C, deuxième étage, une personne appelle derrière la porte 24. Une odeur inconnue est présente dans le couloir. Je suis à l'écart, sans entrer, et j'empêche les occupants de s'exposer. Faites prévenir les secours.",
        "Ronde 1 de PC. Reçu : bâtiment C, étage 2, porte 24, danger non identifié. Je lance l'alerte et organise l'accueil des secours. Restez en position sûre.",
        "Reçu. Je garde les autres occupants à l'écart sans retourner vers la porte."),
    "aps62-03-01": _dialogue(
        "Exemple fictif au café d'un centre commercial. Aucun acte de soustraction n'a été vu par l'agent ; les personnes restent à distance.",
        "PC de Galerie 1, café central. Un client dit qu'on lui a pris son sac et désigne une personne avec un sac similaire. Je n'ai pas vu la prise. Je garde une distance et demande un appui pour recueillir les faits.",
        "Galerie 1 de PC. Reçu : déclaration de vol, pas de constat personnel de la prise. L'appui arrive. Transmettez les nouveaux éléments avec leur source.",
        "Compris. Je ne présente pas la ressemblance du sac comme une preuve."),
    "aps62-03-02": _dialogue(
        "Exemple fictif après des faits directement observés, dont le cadre doit être transmis sans délai aux autorités. Les identités seront communiquées par le canal autorisé.",
        "PC de Magasin 2. Nous sommes au local d'accueil, près de l'entrée est. Le responsable demande d'attendre le directeur avant l'appel à la police. Je demande le relais immédiat aux forces de l'ordre, avec les faits observés.",
        "Magasin 2 de PC. Reçu. J'engage le relais maintenant ; nous n'attendons pas le directeur. Informez-moi de l'état de la personne et de toute difficulté urgente.",
        "Reçu. Je reste attentif à son état et prépare une chronologie factuelle, sans interrogatoire."),
    "aps62-04-01": _dialogue(
        "Exemple fictif : échange confidentiel avec le responsable du poste, aucune liste de visiteurs n'est lue sur la radio.",
        "Une responsable demande les noms, téléphones et horaires des visiteurs d'un autre service pour un différend personnel. Je n'ai rien transmis. Sa qualité et cette finalité ne sont pas validées pour cet accès.",
        "Adressez la demande au responsable du traitement ou au DPO selon notre circuit. Conservez sa référence, sans copier la liste dans le message de transmission.",
        "Compris. Je transmets la demande pour examen, pas les données demandées.", private=True),
    "aps62-05-01": _dialogue(
        "Exemple fictif à l'entrée logistique. Les deux livraisons ont été reçues selon la même procédure ; le désaccord est remonté discrètement.",
        "Chef de poste, deux livreurs se sont présentés au quai 3. Un collègue a proposé de n'en contrôler qu'un en raison de son nom. J'ai maintenu les mêmes vérifications pour les deux et je vous signale cet écart.",
        "Vous avez bien fait d'appliquer les critères du poste. Je prends en charge le signalement. Si un aménagement d'accueil est nécessaire, nous l'organiserons selon le besoin, sans supprimer le contrôle.",
        "Compris. Je conserve les faits utiles dans le circuit de signalement prévu.", private=True),
    "aps62-05-02": _dialogue(
        "Exemple fictif à l'accueil d'un site privé. La discussion sur une restriction se fait discrètement au poste.",
        "Un collègue veut refuser une visiteuse à cause d'un signe religieux. Son rendez-vous et son accès sont prévus ; je n'ai constaté aucun trouble, et aucune restriction pertinente ne m'a été communiquée.",
        "Appliquez les critères habituels d'accueil. Je fais vérifier la demande de restriction par l'encadrement. N'inventez pas de condition supplémentaire au guichet.",
        "Compris. Je poursuis les mêmes vérifications d'accès et explique calmement la suite.", private=True),
    "aps62-05-03": _dialogue(
        "Exemple fictif à une cérémonie privée, devant la salle principale. Aucune menace ni violence n'est observée au moment de cet échange.",
        "PC de Salle 1. Un visiteur critique une institution à voix forte. Le client demande que nous l'arrêtions. Je ne constate ni menace ni violence et je n'ai engagé aucune contrainte. Je demande votre appui.",
        "Salle 1 de PC. Reçu. Faites préciser les faits et les règles du lieu, sans attribuer un pouvoir d'arrestation à cette seule demande. Je viens vous appuyer.",
        "Reçu. Je surveille la sécurité de la sortie et je signale immédiatement toute évolution."),
    "aps62-06-01": _dialogue(
        "Exemple fictif : le fournisseur attend au point logistique et l'agent informe discrètement son chef de poste.",
        "Un fournisseur m'a proposé deux places de spectacle, puis demandé de faire entrer son camion sans contrôle. J'ai refusé le passe-droit ; le camion reste dans l'attente prévue. Je vous transmets la proposition.",
        "Maintenez les vérifications habituelles. Je prends en charge le signalement et l'examen du cadeau selon la politique de l'entreprise.",
        "Compris. Aucun avantage proposé ne change la procédure de cette livraison.", private=True),
    "aps62-06-02": _dialogue(
        "Exemple fictif : échange confidentiel au poste vidéo. L'agent ne fait aucune nouvelle copie de l'image.",
        "Un collègue a photographié l'écran du poste pour un groupe privé. Des visiteurs sont reconnaissables. Il m'indique avoir déjà envoyé l'image à deux personnes extérieures ; je n'ai pas retransmis la photo.",
        "Je déclenche le traitement prévu pour cet incident. Notez ce que vous avez constaté et ce qui vous a été déclaré, sans multiplier les copies ni décider seul de supprimer des traces.",
        "Compris. Je conserve une chronologie factuelle et reste disponible pour le responsable désigné.", private=True),
    "aps62-06-03": _dialogue(
        "Exemple fictif à l'accueil personnel. L'échange avec le chef de poste évite de diffuser les informations des contrôleurs sur le canal collectif.",
        "Deux personnes se présentent pour un contrôle CNAPS. Je les accueille au point prévu et j'applique la vérification de qualité figurant dans notre procédure. Je vous demande de venir au poste.",
        "J'arrive. Facilitez l'accueil et préparez les documents dans le cadre du contrôle. S'il existe une erreur dans un registre, elle sera expliquée sans modification rétroactive trompeuse.",
        "Reçu. Je préserve les documents en l'état et relève les demandes des contrôleurs.", private=True),
    "aps62-06-04": _dialogue(
        "Exemple fictif : l'intervenant attend à l'accueil ; l'agent appelle son chef de poste par le canal confidentiel prévu.",
        "Le client me demande de prêter mon badge nominatif à un intervenant extérieur. Je n'ai pas remis le badge ; l'intervenant reste à l'accueil. Pouvez-vous organiser un accès régulier et clarifier la demande ?",
        "Conservez votre badge. Je prends contact avec le client et l'employeur pour une solution conforme. Maintenez le poste et tracez les faits selon la procédure.",
        "Compris. J'explique que l'accès doit être attribué à la bonne personne par le circuit prévu.", private=True),
    "aps62-07-01": _dialogue(
        "Exemple fictif à l'accueil visiteurs. La file ralentit après deux indications contradictoires ; l'agent garde un espace de dialogue.",
        "PC de Accueil 1. La file atteint le repère bleu. Un visiteur hausse la voix après deux indications différentes ; je ne constate pas de menace. Je clarifie l'information et demande un collègue pour gérer la file.",
        "Accueil 1 de PC. Reçu. J'envoie l'appui au repère bleu ; il prendra la file pendant que vous terminez l'explication.",
        "Reçu. Je garde une consigne courte et vous signale tout changement de comportement."),
    "aps62-07-02": _dialogue(
        "Exemple fictif au guichet visiteurs. L'agent échange avec le contact achats sur la liaison professionnelle prévue, sans annoncer le nom de la visiteuse sur une radio collective.",
        "Bonjour, accueil visiteurs. Une personne annonce un rendez-vous avec le service achats à 10 heures. Je ne le trouve pas sous le nom qu'elle présente. Pouvez-vous vérifier l'invitation sous le nom de son entreprise ?",
        "Oui, l'invitation est enregistrée sous l'entreprise. Je vous transmets la référence par notre circuit d'accueil pour contrôler la concordance.",
        "Merci. Je vérifie cette référence et l'identité selon la procédure avant d'autoriser le passage.", private=True, receiver="Contact achats"),
    "aps62-07-03": _dialogue(
        "Exemple fictif au comptoir. L'agent communique après s'être replacé à distance de l'usager ; des cartons gênent son cheminement.",
        "PC de Accueil 2. Au comptoir, le passage vers la porte de service est encombré de cartons. L'usager parle fort mais reste à distance maintenant. Je demande un appui pour libérer le cheminement sans le coincer.",
        "Accueil 2 de PC. Reçu. Je vous envoie un collègue par l'accès libre. Maintenez l'espace et ne déplacez pas la difficulté vers la sortie du public.",
        "Reçu. Je garde une voix calme et un passage disponible pendant l'intervention."),
    "aps62-07-04": _dialogue(
        "Exemple fictif au portillon nord. La personne reste derrière le dispositif lors du premier message.",
        "PC de Accès 1, portillon nord. Un visiteur m'insulte après le refus d'accès ; il ne tente pas de franchir pour l'instant. J'ai rappelé la procédure et maintiens le portillon. Je demande un appui.",
        "Accès 1 de PC. Reçu. L'appui arrive. Informez-moi immédiatement si une menace précise ou une tentative de passage apparaît.",
        "Reçu. Je garde la distance et ne réponds pas aux insultes."),
    "aps62-07-05": _dialogue(
        "Exemple fictif à la relève de l'accueil. Le rendez-vous a finalement été confirmé et le conflit est terminé.",
        "Relève, l'incident de 10 h 20 est terminé. Le service achats a confirmé le rendez-vous, puis l'accès a été autorisé après vérification. Deux panneaux donnent encore des horaires différents ; ce point reste à corriger.",
        "Reçu : accès régularisé et incident apaisé. Je reprends le suivi des panneaux et demande leur correction au responsable.",
        "Merci. La référence de l'incident et les deux emplacements des panneaux sont dans la main courante.", private=True, receiver="Agent de relève"),
    "aps62-08-01": _dialogue(
        "Exemple fictif au poste ouest. Il est 19 h 15 et la version validée fixe la fin d'accès à 19 heures.",
        "PC de Accès ouest. Un habitué se présente à 19 h 15. La consigne signée hier remplace celle qui indiquait 20 heures. J'applique la fermeture de 19 heures ; la personne attend à l'accueil. Confirmez-vous le contact pour une demande d'exception ?",
        "Accès ouest de PC. Reçu. Le responsable de permanence traite les exceptions. Je lui transmets la demande ; aucun accord n'est donné pour l'instant.",
        "Reçu. Je maintiens la règle en vigueur en attendant une décision authentifiée."),
    "aps62-08-02": _dialogue(
        "Exemple fictif : le PC vient de recevoir « problème au bâtiment B ». Le réseau reste disponible ; le collègue précise les faits.",
        "PC de Ronde 2. Bâtiment B, deuxième étage, porte coupe-feu près de l'escalier est : elle reste bloquée ouverte. Je ne vois pas de fumée. Je n'ai rien démonté. Je demande la prise en charge technique prévue.",
        "Ronde 2 de PC. Reçu : bâtiment B, étage 2, escalier est, porte bloquée ouverte, sans fumée observée. Je préviens le service technique et le responsable sécurité. Signalez tout changement.",
        "Reçu. Je conserve le passage sûr selon la consigne et rends compte de l'arrivée de l'intervenant."),
    "aps62-08-03": _dialogue(
        "Exemple fictif : échange au poste avant correction de la main courante. Le journal radio et l'auteur confirment l'heure de l'appel.",
        "L'entrée 214 note un appel à 14 h 12. Le journal radio indique 14 h 02, et l'auteur confirme l'erreur. Je propose une correction datée qui cite cette source et conserve l'entrée initiale.",
        "Utilisez la fonction de rectification prévue. Conservez aussi l'heure de saisie de la correction ; ne remplacez pas l'historique par une entrée silencieusement modifiée.",
        "Compris. La rectification renverra à l'entrée 214 et au journal radio.", private=True),
    "aps62-08-04": _dialogue(
        "Exemple fictif au couloir ouest après une dégradation. L'agent ne dispose d'aucune observation de l'auteur du dommage.",
        "PC de Ronde 1. À 16 h 05, couloir ouest, j'ai constaté la porte endommagée et vu un visiteur s'éloigner. Je n'ai pas vu la dégradation se produire. Je demande le relais habilité pour préserver une éventuelle séquence vidéo.",
        "Ronde 1 de PC. Reçu : porte endommagée constatée, auteur non établi. Je contacte le responsable habilité pour la conservation des images.",
        "Reçu. Je ne copie pas les images sur un appareil personnel et je sépare mes observations des hypothèses dans le rapport."),
    "aps62-08-05": _dialogue(
        "Exemple fictif : relève à 18 heures. La porte D reste sous surveillance et la réparation n'a pas été confirmée.",
        "Relève, porte D : le verrouillage est toujours défaillant. La surveillance provisoire reste en place. Le technicien annoncé vient de signaler un retard ; je n'ai pas de nouvel horaire confirmé.",
        "Reçu. Je reprends le suivi de la porte D et demande à l'encadrement les moyens pour maintenir aussi l'accueil. Je ne clos pas l'incident au changement de vacation.",
        "Merci. Le contact technique et la mesure en cours figurent dans l'entrée 318 ; la remise en état devra être confirmée.", private=True, receiver="Agent de relève"),
    "aps62-09-01": _dialogue(
        "Exemple fictif à l'entrée principale après une poussée. La personne est tombée et ne manifeste plus d'attaque au moment du message.",
        "PC de Entrée 1. Après m'avoir poussé, la personne a été repoussée puis est tombée. Je ne vois plus de geste d'attaque. Je cesse la réponse défensive, garde un espace sûr et demande un appui pour l'alerte et l'évaluation de son état.",
        "Entrée 1 de PC. Reçu. J'organise l'appui et l'alerte adaptée. Décrivez les signes observés, sans conclure qu'une personne au sol est hors de danger.",
        "Reçu. Je signale tout changement et ne prolonge pas une action pour punir le geste initial."),
    "aps62-09-02": _dialogue(
        "Exemple fictif : le portail principal est bloqué par un véhicule ; l'accès C, prévu au plan, est immédiatement praticable.",
        "PC de Portail. Les secours sont à l'entrée principale, bloquée par un véhicule. L'accès C est libre et prévu au plan. Je demande l'ouverture de C et un guide au carrefour intérieur.",
        "Portail de PC. Reçu. J'active l'ouverture de C et envoie le guide. Orientez les secours vers C avec cette information ; annoncez tout obstacle nouveau.",
        "Reçu. Je confirme l'itinéraire C aux secours et reste disponible pour le guidage."),
    "aps62-09-03": _dialogue(
        "Exemple fictif : échange confidentiel au poste avant tout contrôle imposé des effets personnels des salariés.",
        "Le directeur demande l'ouverture systématique des effets personnels sans accord après une disparition. Aucun cadre particulier ne m'a été communiqué. Je n'ai pas commencé cette fouille et je vous demande de clarifier une procédure régulière.",
        "Je prends contact avec la direction. Maintenez la sécurité du poste ; la propriété des locaux ne suffit pas à créer ce pouvoir pour l'agent.",
        "Compris. Je présenterai les limites calmement et transmettrai la consigne reçue pour vérification.", private=True),
    "aps62-10-01": _dialogue(
        "Exemple fictif au quai 2. L'agent observe depuis le cheminement piéton protégé, sans entrer dans la trajectoire des chariots.",
        "PC de Ronde 3. Au quai 2, une flaque couvre le croisement piétons-chariots. Aucun accident ne m'est signalé. Je suis hors du trafic et demande le responsable logistique pour mettre en place la protection prévue.",
        "Ronde 3 de PC. Reçu, quai 2 au croisement. J'appelle le responsable logistique. Maintenez l'avertissement depuis le point sûr, sans vous placer devant les véhicules.",
        "Reçu. Je vous indique aussi si les traversées augmentent avec la prochaine livraison."),
    "aps62-10-02": _dialogue(
        "Exemple fictif : l'agent prépare la nouvelle ronde de nuit et compare l'extrait DUERP au poste.",
        "Chef de poste, l'extrait disponible ne couvre que les rondes de jour. La nouvelle ronde de nuit passe par l'annexe où la liaison ne fonctionne pas. Je demande une clarification des mesures avant cette nouvelle organisation.",
        "Je remonte ce changement aux responsables de prévention. Il faut examiner le travail isolé, les communications et les moyens ; un simple rappel de prudence ne suffit pas.",
        "Je note le secteur, l'horaire et l'absence de liaison pour que la remontée soit précise.", private=True),
    "aps62-10-03": _dialogue(
        "Exemple fictif au portail logistique. L'entreprise extérieure attend au point prévu ; les consignes de coactivité n'ont pas été transmises.",
        "PC de Logistique. L'entreprise de maintenance est au portail pour le secteur 4. Le bon est présent, mais je n'ai pas les consignes concernant les véhicules qui y circulent. Je maintiens l'attente et demande le responsable de l'intervention.",
        "Logistique de PC. Reçu. Je contacte le responsable pour confirmer les conditions de prévention avant l'accès au secteur 4.",
        "Reçu. Je n'étends pas le bon d'intervention à d'autres zones et signale toute modification annoncée."),
    "aps62-10-04": _dialogue(
        "Exemple fictif sur un site industriel. La fiche locale associe le signal entendu à la mise à l'abri au bâtiment M ; le canal est authentifié.",
        "PC de Accueil. Le signal correspondant à la fiche 3 vient de retentir. La fiche prévoit la mise à l'abri au bâtiment M. J'oriente les visiteurs selon ce cheminement ; un intervenant propose pourtant la route extérieure. Confirmez la consigne.",
        "Accueil de PC. Consigne confirmée : bâtiment M par le trajet prévu. Ne dirigez pas le public vers la route. Signalez le nombre accueilli et toute difficulté sur le parcours.",
        "Reçu : bâtiment M. Je transmets les difficultés sans changer seul de destination."),
    "aps62-10-05": _dialogue(
        "Exemple fictif au passage piéton de l'atelier. Une séparation a été déplacée ; l'agent reste du côté protégé.",
        "PC de Atelier 1. La barrière séparant les piétons de la manutention a été déplacée au passage nord. Le port d'un gilet est proposé à la place. Je demande le responsable pour rétablir un cheminement sûr.",
        "Atelier 1 de PC. Reçu. J'appelle le responsable de zone. Ne présentez pas le gilet comme un remplacement de la séparation collective ; appliquez l'attente prévue hors de l'exposition.",
        "Reçu. Je signale l'écart aux usagers depuis la zone protégée et j'attends la remise en sécurité confirmée."),
    "aps62-10-06": _dialogue(
        "Exemple fictif près du local de nettoyage. Le contenant non identifié n'est pas manipulé ; l'agent communique depuis un emplacement sûr.",
        "PC de Ronde 2. Devant le local nettoyage, un bidon sans étiquette est présent. Une personne dit qu'il s'agit d'un produit courant, mais je n'ai pas de correspondance vérifiée. Je n'y touche pas et demande le responsable désigné.",
        "Ronde 2 de PC. Reçu : contenant non identifié, déclaration non vérifiée. J'appelle le responsable produits. Restez à l'écart et n'approchez pas pour sentir ou lire une information cachée.",
        "Reçu. Je maintiens les mesures prévues et transmets seulement les éléments déjà visibles sans m'exposer."),
    "aps62-10-07": _dialogue(
        "Exemple fictif au point de contrôle extérieur de la zone ATEX. L'appareil personnel n'a pas été introduit dans la zone.",
        "PC de Accès technique. Un prestataire souhaite entrer en zone ATEX avec un appareil personnel. Je n'ai pas de validation de compatibilité pour cet équipement. Il reste au point d'attente extérieur ; je demande le responsable habilité.",
        "Accès technique de PC. Reçu. Je sollicite la vérification avant l'entrée. Une batterie ou l'annonce d'une extinction une fois dedans ne vaut pas validation.",
        "Reçu. J'attends la confirmation des conditions d'accès et du matériel avant de laisser poursuivre."),
    "aps62-11-01": _dialogue(
        "Exemple fictif devant le couloir technique A. L'agent est hors de la zone exposée et a fait reculer les personnes sans toucher au coffret.",
        "PC de Ronde 1. Couloir technique A : un coffret est ouvert après un choc, avec une odeur inhabituelle. Je n'ai pas touché l'installation ; les personnes sont tenues à l'écart. Je demande l'intervenant électrique compétent.",
        "Ronde 1 de PC. Reçu. Je déclenche le relais prévu. Ne présentez pas l'installation comme hors tension ; maintenez la protection depuis votre position sûre.",
        "Reçu. Aucun accès ni manipulation avant confirmation de la sécurisation par l'interlocuteur compétent."),
    "aps62-11-02": _dialogue(
        "Exemple fictif dans l'atelier ouest. L'agent reste à distance ; le danger électrique n'a pas encore été supprimé.",
        "PC de Atelier ouest. Une personne est au sol près de l'appareil dégradé. Le danger électrique n'est pas exclu. J'empêche un témoin de la saisir et reste à distance. Faites alerter les secours et l'intervenant compétent pour sécuriser.",
        "Atelier ouest de PC. Reçu : une personne visible, danger électrique possible, accès non sécurisé. Je lance les deux alertes et prépare l'accueil des secours.",
        "Reçu. Je ne touche pas la personne avant un accès sûr et j'actualise les signes observables sans m'exposer."),
    "aps62-12-01": _dialogue(
        "Exemple fictif au poste nord. Une publication circule ; aucun événement d'attaque n'a été constaté par l'équipe.",
        "PC de Poste nord. Une publication annonce une attaque près du site. Je n'ai pas de confirmation officielle ; je constate seulement une circulation ralentie. Je vous transmets sa référence par le canal prévu et demande une vérification.",
        "Poste nord de PC. Reçu : information non confirmée. Je consulte le canal officiel et la consigne locale. Maintenez les mesures en vigueur et signalez les faits nouveaux.",
        "Reçu. Je ne présente pas la publication comme une confirmation au public."),
    "aps62-12-02": _dialogue(
        "Exemple fictif : depuis une position sûre, hors du secteur protégé autour de l'entrée est, l'agent utilise le canal prévu. Il ne revient pas vers l'objet pour compléter la description.",
        "PC de Entrée est. Je communique depuis le point sûr prévu. Un objet inhabituel est signalé près de l'entrée est, sans propriétaire identifié au poste. Personne ne le manipule ; le passage est écarté du secteur selon la consigne. Déclenchez le relais compétent.",
        "Entrée est de PC. Reçu. J'engage l'alerte prévue. Maintenez les protections et les cheminements prescrits ; aucune approche pour vérifier l'objet ou prendre une photo.",
        "Reçu. Je reste au point sûr et vous transmets toute nouvelle déclaration sans lever seul les protections."),
    "aps62-12-03": _dialogue(
        "Exemple fictif au poste principal. L'agent dispose d'une note reçue par le circuit authentifié du site ; il ne déduit pas la posture du jour d'une affiche.",
        "Chef de poste, l'affichage ne correspond pas à la note officielle reçue ce matin par notre circuit. La fiche locale n'est pas encore actualisée. Pouvez-vous confirmer la version à diffuser et les mesures qui changent pour l'accueil ?",
        "Je vérifie la source, la date d'effet et la déclinaison validée pour le site. Nous remplacerons les supports périmés après confirmation et informerons les équipes concernées.",
        "Compris. Je ne présente pas l'ancien affichage comme la posture actuelle.", private=True),
    "aps62-12-04": _dialogue(
        "Exemple fictif à l'entrée visiteurs. Le message décrit les actes, sans référence à l'origine ou à l'apparence de la personne.",
        "PC de Accueil. À 11 h 10, un visiteur a photographié trois accès et demandé nos horaires de présence. Je vous signale ces comportements ; je n'en connais pas la finalité. Il présente maintenant une autorisation de reportage à vérifier.",
        "Accueil de PC. Reçu. Je contacte le responsable habilité pour contrôler le périmètre de l'autorisation. Conservez les faits et leur horaire sans conclure à une intention.",
        "Reçu. J'actualise le signalement avec le résultat de cette vérification."),
    "aps62-12-05": _dialogue(
        "Exemple fictif après un appel reçu au poste. Le lieu annoncé reste ambigu ; le message ne reproduit pas le dossier de production individuelle.",
        "PC de Accueil. À 11 h 32, un appelant a annoncé une menace contre le site et cité « le bâtiment derrière ». La ligne a coupé avant précision. Je conserve ses paroles dans la fiche et demande l'activation de la procédure d'alerte.",
        "Accueil de PC. Reçu : menace annoncée, lieu non identifié avec certitude. Je déclenche le relais prévu. Transmettez la fiche et les passages incertains par le canal autorisé.",
        "Reçu. Je ne complète pas le lieu par supposition et je n'attends pas un second appel pour transmettre."),
    "aps62-12-06": _dialogue(
        "Exemple fictif à l'extérieur du poste nord. L'agent observe sans poursuivre l'aéronef ni tenter de le neutraliser.",
        "PC de Poste nord. À 15 h 18, j'observe un petit aéronef se déplacer d'est en ouest près du secteur technique. Je ne connais ni son opérateur ni son autorisation. Je reste à mon poste et demande la vérification prévue.",
        "Poste nord de PC. Reçu. Je vérifie l'éventuelle inspection autorisée et contacte le relais compétent. N'engagez aucune tentative de neutralisation.",
        "Reçu. Je note les horaires et la direction visible, sans présenter l'autorisation comme confirmée."),
    "aps62-12-07": _dialogue(
        "Exemple fictif après un événement violent. L'agent se trouve au point de rassemblement R, déclaré accessible ; la zone derrière la verrière reste non vérifiée.",
        "PC de Rassemblement R. Je vois deux personnes : près du banc, une personne répond, porte une blessure visible et dit entendre difficilement ; près de la verrière, une autre est immobile. Je n'ai pas de bilan au-delà de cette zone. Faites transmettre ces éléments aux secours.",
        "Rassemblement R de PC. Reçu : deux personnes observées, signes différents, secteur arrière non vérifié. Je transmets aux secours. Restez dans la zone accessible et respectez toute nouvelle limite.",
        "Reçu. Je signale les changements et ne présente pas ce nombre comme le total du site."),
    "aps62-13-01": _dialogue(
        "Exemple fictif au poste informatique, avant toute saisie sur la session d'un collègue. Aucun identifiant n'est prononcé sur un canal collectif.",
        "La session encore ouverte appartient à la relève précédente. Je dois saisir l'événement du portail, mais je n'ai pas utilisé son compte. Je vais ouvrir ma session ; si elle reste indisponible, quel support de continuité est prévu ?",
        "Utilisez le registre de secours identifié dans la procédure, avec votre nom, l'heure des faits et l'heure de consignation. Nous ferons ensuite la reprise traçable dans votre compte.",
        "Compris. Je ne partage ni mot de passe ni signature de l'autre agent.", private=True),
    "aps62-13-02": _dialogue(
        "Exemple fictif au poste documentaire. Le rapport doit être adressé au responsable habilité par le circuit approuvé.",
        "Je trouve deux fichiers presque identiques : un brouillon et une version validée. Avant l'envoi, je contrôle le statut, le destinataire et la pièce jointe ouverte. Une copie vers une adresse personnelle vient d'être demandée ; je ne l'ai pas envoyée.",
        "Gardez le circuit approuvé. Je fais vérifier cette nouvelle demande et l'habilitation du destinataire. La ressemblance des noms de fichiers ne permet pas de choisir au hasard.",
        "Compris. Je transmets uniquement la version et le destinataire confirmés, puis vérifie l'envoi effectif.", private=True),
    "aps62-14-01": _dialogue(
        "Exemple fictif au dépôt 2. L'agent observe depuis un point sûr sans entrer dans la zone ni engager de contrainte.",
        "PC de Ronde dépôt. Dans le secteur 2 normalement fermé, une personne déplace des colis. Je n'ai pas vu d'effraction et ne connais pas ses autorisations. Je reste en observation sûre ; pouvez-vous vérifier les interventions prévues ?",
        "Ronde dépôt de PC. Reçu. Je vérifie auprès du responsable du secteur. Transmettez tout nouveau fait avec sa source ; ne présentez pas ce déplacement comme un vol établi.",
        "Reçu. Je conserve la description factuelle et ma position sûre."),
    "aps62-14-02": _dialogue(
        "Exemple fictif au portique sortie d'un magasin. Le contrôle reste calme et la cliente a présenté son ticket.",
        "PC de Sortie 1. Le portique a sonné. La cliente présente un ticket et un article avec son dispositif de protection ; je n'ai observé aucune dissimulation. Je demande une vérification du paiement par la caisse.",
        "Sortie 1 de PC. Reçu. La caisse vérifie la référence. Conservez un échange discret et ne présentez pas l'alarme comme une preuve de vol.",
        "Reçu. J'attends la réponse de la caisse et j'actualise la suite selon les éléments vérifiés."),
    "aps62-14-03": _dialogue(
        "Exemple fictif : un poste de sécurité incendie est sollicité pour un différend commercial sans danger immédiat décrit.",
        "PC de Poste incendie. Un salarié me demande de quitter mon poste pour retenir un client à l'accueil. Aucun fait précis de flagrance ni danger immédiat ne m'est donné. Je reste sur ma fonction et demande le relais sûreté.",
        "Poste incendie de PC. Reçu. Je fais traiter le différend par le relais adapté ; votre continuité de poste reste assurée. Signalez immédiatement toute alarme relevant de votre mission.",
        "Reçu. Je ne remplace pas une autre fonction sans organisation validée."),
    "aps62-14-04": _dialogue(
        "Exemple fictif dans une situation d'appréhension en cours de relais. Le message ne décrit aucune technique de contrainte.",
        "PC de Équipe 2. La personne a cessé de résister et dit maintenant qu'elle respire difficilement. Nous réévaluons immédiatement les moyens et prenons en compte ce signe. Faites demander l'aide médicale et informez les forces de l'ordre.",
        "Équipe 2 de PC. Reçu, difficulté respiratoire déclarée. J'alerte les secours sans attendre et actualise le relais aux autorités. Continuez à surveiller les signes et suivez les instructions compétentes.",
        "Reçu. Nous transmettons toute évolution ; l'attente de la police ne justifie pas de différer l'assistance."),
    "aps62-14-05": _dialogue(
        "Exemple fictif après une dégradation. Le couloir peut être évité par un itinéraire sûr prévu ; aucun secours n'est retardé.",
        "PC de Ronde 1. Dans le couloir C, des fragments restent au sol après la dégradation. Le nettoyage est demandé, mais le passage peut être contourné sans danger. Je préserve la zone selon la consigne et demande votre relais aux autorités.",
        "Ronde 1 de PC. Reçu. Maintenez le cheminement alternatif et signalez toute modification nécessaire pour protéger une personne. Les fragments ne sont pas à déplacer pour les présenter.",
        "Reçu. Je note les accès et les actions réellement effectuées, sans reconstituer artificiellement la scène."),
    "aps62-14-06": _dialogue(
        "Exemple fictif au point de remise aux forces de l'ordre. Les heures données sont propres à cette démonstration.",
        "À 17 h 12, j'ai vu la porte forcée, pas son ouverture. À 17 h 14, un témoin m'a déclaré avoir entendu un choc. J'ai protégé le passage à 17 h 15. La copie du ticket et les coordonnées recueillies sont référencées dans ce dossier.",
        "Je reprends : votre constat porte sur la porte, le bruit est rapporté par le témoin. Y a-t-il une information de santé ou une action encore en cours à nous transmettre ?",
        "Aucun blessé ne m'a été signalé ; cela ne vaut pas un bilan de tout le site. La protection du passage est toujours en place.", private=True, receiver="Intervenant de police"),
    "aps62-14-07": _dialogue(
        "Exemple fictif au dépôt après un appel évoquant un vol. L'agent n'a pas vu l'ouverture du colis.",
        "PC de Dépôt 1. Sur place, je vois un salarié, un prestataire et un colis ouvert. Personne ne m'a encore décrit l'acte précis. Je garde une situation calme et demande la vérification de l'autorisation d'ouverture.",
        "Dépôt 1 de PC. Reçu. Je contacte le responsable. Conservez séparément les observations et les explications reçues ; le statut de salarié ne suffit pas à valider une autorisation.",
        "Reçu. Je ne désigne pas un auteur sur la seule familiarité ou absence de familiarité avec le site."),
    "aps62-15-01": _dialogue(
        "Exemple fictif avant l'ouverture du concert. L'équipe ne met pas en service l'entrée déplacée tant que le dispositif n'est pas clarifié.",
        "PC de Entrée 3. Le plan reçu par mon équipe place l'entrée à l'est ; l'équipe voisine utilise un plan la plaçant au sud. Les repères secours diffèrent aussi. Je demande une version commune validée avant l'ouverture du point.",
        "Entrée 3 de PC. Reçu. Je fais confirmer la version et les relais par l'organisation. Restez sur l'affectation prévue en attendant la diffusion coordonnée.",
        "Reçu. Je confirmerai la réception de la nouvelle version et les points critiques de notre secteur."),
    "aps62-15-02": _dialogue(
        "Exemple fictif au contrôle des coulisses. Le badge présenté autorise uniquement la zone publique.",
        "PC de Coulisses 1. Une personne présente un badge public et demande la zone technique en disant connaître l'organisateur. Aucune extension n'est enregistrée. Elle attend au point de contrôle ; je demande le contact habilité.",
        "Coulisses 1 de PC. Reçu. Je contacte le responsable des accréditations. Maintenez la limite de zone tant que les conditions ne sont pas confirmées.",
        "Reçu. Si un accès accompagné est accordé, je vérifierai sa durée, son secteur et l'accompagnement prévu."),
    "aps62-15-03": _dialogue(
        "Exemple fictif à l'entrée est du spectacle. L'agent observe depuis son poste ; il ne déplace pas seul les barrières.",
        "PC de Entrée est. La file déborde sur le cheminement de sortie, au repère E2. Le passage piéton se réduit et les arrivées continuent. Je demande le responsable de secteur pour dégager le passage et agir en amont.",
        "Entrée est de PC. Reçu, repère E2. Je mobilise le responsable pour l'adaptation coordonnée. Maintenez les dégagements selon la consigne ; ne fermez pas la sortie pour stocker la file.",
        "Reçu. Je vous rends compte de l'évolution de la file et de toute difficulté de déplacement."),
    "aps62-15-04": _dialogue(
        "Exemple fictif au passage étroit P4. L'agent reste hors de la compression et peut joindre le PC.",
        "PC de Secteur 4, urgence. Au passage P4, plusieurs personnes disent ne plus pouvoir choisir leur déplacement ; je vois une densification et une progression bloquée. Faites coordonner immédiatement les mesures du dispositif et les arrivées en amont.",
        "Secteur 4 de PC. Reçu, P4 : perte de mobilité et progression bloquée. J'engage la coordination et le relais secours prévus. Restez en sécurité et décrivez tout changement.",
        "Reçu. Je n'essaie pas de repousser seul le mouvement ni d'ouvrir une barrière vers une zone inconnue."),
    "aps62-15-05": _dialogue(
        "Exemple fictif au secteur bleu, distinct du plan à traiter en production individuelle. L'itinéraire initial est encombré ; aucune alternative n'est encore confirmée.",
        "PC de Secteur bleu. L'itinéraire de mise en sécurité par la porte B est encombré. Je n'oriente pas le public vers la porte C sans vérification. Confirmez un cheminement disponible et un point d'accueil accessible.",
        "Secteur bleu de PC. Reçu. Le responsable confirme maintenant la porte D et le point d'accueil Prairie, avec l'appui prévu. Diffusez cette seule consigne et rendez compte des difficultés.",
        "Reçu : porte D, point Prairie. Je donne une direction claire et signale les besoins d'assistance à l'appui désigné."),
    "aps62-15-06": _dialogue(
        "Exemple fictif aux accès d'un événement. La voie secours est distincte de la file logistique et du point presse.",
        "PC de Accès 2. Un véhicule de secours, une livraison et une équipe de presse arrivent ensemble. Je garde la voie secours disponible ; livraison et presse attendent à leurs points prévus. Je demande les contacts logistique et accréditations.",
        "Accès 2 de PC. Reçu. Je joins les deux contacts. Maintenez le circuit secours et ne mélangez pas ces flux sous la pression de la production.",
        "Reçu. Une demande liée à un artiste passera par la logistique, sans bloquer la voie secours."),
    "aps62-15-07": _dialogue(
        "Exemple fictif au contrôle des billets. L'échange sur le litige reste discret ; les références nominatives passent par l'outil autorisé.",
        "Billetterie de Contrôle 4. Le lecteur signale un billet déjà utilisé. La personne présente une confirmation d'achat et dit ne pas être entrée. Je l'oriente vers le point litiges ; pouvez-vous vérifier la référence dans l'outil ?",
        "Contrôle 4 de Billetterie. Reçu. Nous vérifions le statut et la synchronisation. Pour l'instant, l'alerte du lecteur ne permet pas de conclure à une fraude.",
        "Reçu. J'explique la vérification sans accusation et j'appliquerai la décision confirmée.", receiver="Billetterie"),
}


def dialogue_text(section_id):
    """Narration-ready scene; the setting precedes actions already carried out."""
    scene = RADIO_DEMONSTRATIONS[section_id]
    return scene["context"] + " " + " ".join(
        f"{turn['speaker']} : {turn['text']}" for turn in scene["turns"]
    )

# Concise visible bubbles. The full spoken turn remains in text and captions.
_DISPLAY = {
    ("01-01", 0): "Au hall, le gestionnaire demande des photos du commerce voisin. Aucun incident constaté sur notre site. Je reste au poste ; quel arbitrage ?",
    ("01-02", 0): "La remplaçante présente son diplôme et une demande de carte en instruction. Son droit d'exercer n'est pas vérifié ; elle n'a pas pris le poste.",
    ("01-03", 0): "La ronde facturée au voisin n'est couverte par aucun document disponible. Mon planning concerne l'usine ; je n'ai pas quitté mon secteur.",
    ("01-04", 0): "Cette veste évoque une force publique et masque mes identifiants. Je ne l'ai pas portée au poste. Quelle dotation conforme puis-je prendre ?",
    ("02-01", 0): "À 9 h 12, j'ai fermé la barrière. Le visiteur signale une marque sur son capot et dit avoir porté plainte. Je distingue ses propos de mes constats.",
    ("02-02", 0): "PC, portillon sud : le visiteur s'éloigne, sans nouvelle attaque observée. Je maintiens la distance et demande un appui au poste.",
    ("02-03", 0): "PC : appel à l'aide, bâtiment C, étage 2, porte 24 ; odeur inconnue. Je reste à l'écart et empêche l'approche. Faites prévenir les secours.",
    ("03-01", 0): "PC, café central : un client déclare un sac pris et désigne un sac similaire. Je n'ai pas vu la prise. Je reste à distance et demande un appui.",
    ("03-02", 0): "PC, local d'accueil près de l'entrée est : le responsable veut attendre le directeur. Je demande le relais immédiat à la police avec les faits observés.",
    ("04-01", 0): "Une liste nominative avec téléphones est demandée pour un différend personnel. Accès et finalité non validés : je n'ai transmis aucune donnée.",
    ("05-01", 0): "Au quai 3, un collègue voulait contrôler un seul livreur en raison de son nom. J'ai appliqué les mêmes vérifications aux deux ; je signale cet écart.",
    ("05-01", 1): "Je prends le signalement en charge. Nous adapterons l'accueil à un besoin identifié, en gardant les contrôles requis.",
    ("05-02", 0): "Une visiteuse a un rendez-vous et un accès prévus. Aucun trouble observé. Un collègue veut la refuser pour son signe religieux, sans restriction pertinente reçue.",
    ("05-03", 0): "PC, Salle 1 : un visiteur critique une institution. Le client veut son arrestation ; je ne vois ni menace ni violence. Aucune contrainte engagée. Besoin d'appui.",
    ("06-01", 0): "Le fournisseur propose deux places puis un passage sans contrôle. J'ai refusé le passe-droit ; le camion attend au point prévu. Je signale la proposition.",
    ("06-02", 0): "Un collègue a photographié l'écran, avec des visiteurs reconnaissables. Il dit l'avoir envoyé à deux personnes extérieures. Je n'ai rien retransmis.",
    ("06-02", 1): "Je déclenche le traitement de l'incident. Distinguez constat et déclaration ; ne multipliez pas les copies et ne supprimez pas seul des traces.",
    ("06-03", 0): "Deux personnes annoncent un contrôle CNAPS. Je les accueille et vérifie leur qualité selon la procédure. Merci de venir au poste.",
    ("06-03", 1): "J'arrive. Préparez les documents pour le contrôle. Une erreur dans un registre s'explique ; elle ne se masque pas par une modification rétroactive.",
    ("06-04", 0): "Le client demande mon badge pour un intervenant extérieur. Je le conserve ; l'intervenant attend à l'accueil. Pouvez-vous organiser un accès régulier ?",
    ("07-01", 0): "PC, Accueil 1 : file au repère bleu. Un visiteur hausse la voix après deux indications contraires, sans menace constatée. Je demande un appui pour la file.",
    ("07-02", 0): "Accueil visiteurs : un rendez-vous achats à 10 heures est introuvable sous le nom présenté. Pouvez-vous vérifier sous le nom de l'entreprise ?",
    ("07-03", 0): "PC, Accueil 2 : des cartons gênent la porte de service. L'usager parle fort mais reste à distance. Besoin d'appui pour libérer le passage sans le coincer.",
    ("07-04", 0): "PC, portillon nord : insultes après refus d'accès, sans tentative de passage. Procédure rappelée, portillon maintenu. Je demande un appui.",
    ("07-05", 0): "L'incident de 10 h 20 est résolu : rendez-vous confirmé, accès vérifié. Deux panneaux affichent encore des horaires différents ; correction à suivre.",
    ("08-01", 0): "PC, Accès ouest : arrivée à 19 h 15, après la fermeture de 19 heures fixée par la nouvelle consigne. La personne attend. Quel contact pour l'exception ?",
    ("08-02", 0): "PC, Ronde 2 : bâtiment B, étage 2, escalier est, porte coupe-feu bloquée ouverte. Pas de fumée observée ni démontage. Je demande le service technique.",
    ("08-02", 1): "Reçu : B, étage 2, escalier est, porte ouverte sans fumée observée. Je préviens technique et responsable sécurité. Signalez tout changement.",
    ("08-03", 0): "Entrée 214 : appel noté 14 h 12, journal radio à 14 h 02, erreur reconnue. Je propose une correction sourcée, datée, sans effacer l'original.",
    ("08-04", 0): "PC : à 16 h 05, porte endommagée au couloir ouest, visiteur vu s'éloigner. Dégradation non observée. Je demande le relais habilité pour conserver la vidéo.",
    ("08-05", 0): "Porte D toujours défaillante, surveillance maintenue. Le technicien annonce un retard, sans nouvel horaire confirmé. Ce suivi reste ouvert à la relève.",
    ("09-01", 0): "PC, Entrée 1 : après la poussée, la personne est tombée ; plus d'attaque visible. Je cesse la défense et garde l'espace sûr. Besoin d'appui et d'alerte.",
    ("09-02", 0): "PC, Portail : les secours sont bloqués à l'entrée principale. C est libre et prévu au plan. Demande d'ouverture de C et d'un guide au carrefour intérieur.",
    ("09-03", 0): "Le directeur demande l'ouverture des effets sans accord. Aucun cadre particulier reçu ; je n'ai pas commencé. Merci de clarifier une procédure régulière.",
    ("10-01", 0): "PC, quai 2 : flaque au croisement piétons-chariots, aucun accident signalé. Je reste hors du trafic. Demande du responsable logistique pour la protection.",
    ("10-02", 0): "L'extrait DUERP couvre le jour, pas la nouvelle ronde de nuit. La liaison ne fonctionne pas à l'annexe. Quelles mesures avant cette organisation ?",
    ("10-03", 0): "PC : maintenance au portail pour secteur 4. Bon présent, consignes de coactivité manquantes malgré le trafic. Attente maintenue ; responsable demandé.",
    ("10-04", 0): "PC : signal de la fiche 3, mise à l'abri prévue au bâtiment M. J'oriente selon la fiche ; un tiers propose la route. Confirmez la destination.",
    ("10-05", 0): "PC : barrière piétons-manutention déplacée au passage nord. On propose un gilet à sa place. Demande du responsable pour rétablir un cheminement sûr.",
    ("10-05", 1): "J'appelle le responsable. Le gilet ne remplace pas la séparation collective ; maintenez l'attente prévue hors de l'exposition.",
    ("10-06", 0): "PC : bidon sans étiquette devant le local nettoyage. Produit courant annoncé, sans correspondance vérifiée. Je n'y touche pas ; responsable demandé.",
    ("10-06", 1): "Reçu, contenant non identifié. J'appelle le responsable produits. Restez à l'écart ; aucune approche pour sentir ou lire une information cachée.",
    ("10-07", 0): "PC, Accès technique : appareil personnel sans compatibilité ATEX validée. Le prestataire reste au point extérieur. Je demande le responsable habilité.",
    ("11-01", 0): "PC : coffret ouvert après choc, couloir A, odeur inhabituelle. Je n'ai rien touché ; personnes à l'écart. Demande de l'intervenant électrique compétent.",
    ("11-02", 0): "PC, Atelier ouest : personne au sol, danger électrique non exclu. J'empêche un témoin de la saisir et reste à distance. Secours et sécurisation demandés.",
    ("12-01", 0): "PC : attaque annoncée sur une publication, sans confirmation officielle. Je constate seulement un trafic ralenti. Référence transmise ; vérification demandée.",
    ("12-02", 0): "PC, depuis le point sûr : objet inhabituel près de l'entrée est, propriétaire inconnu. Aucune manipulation, passage écarté selon consigne. Relais demandé.",
    ("12-03", 0): "L'affichage diffère de la note officielle reçue ce matin. La fiche locale attend sa mise à jour. Quelle version et quelles mesures diffuser à l'accueil ?",
    ("12-04", 0): "PC : à 11 h 10, trois accès photographiés et horaires demandés. Intention inconnue. Le visiteur présente une autorisation de reportage à vérifier.",
    ("12-05", 0): "PC : menace reçue à 11 h 32, lieu cité « le bâtiment derrière ». Ligne coupée avant précision. Paroles conservées ; activation de l'alerte demandée.",
    ("12-06", 0): "PC, Poste nord : à 15 h 18, aéronef allant d'est en ouest près du secteur technique. Opérateur et autorisation inconnus. Je demande la vérification.",
    ("12-07", 0): "PC, R : une personne répond près du banc, blessée, audition difficile déclarée ; une autre immobile près de la verrière. Bilan limité à la zone. Secours demandés.",
    ("12-07", 1): "Reçu : deux personnes observées, signes différents ; arrière non vérifié. Je transmets aux secours. Restez dans la zone accessible.",
    ("13-01", 0): "La session ouverte est celle du collègue ; je ne l'ai pas utilisée. J'ouvre mon compte pour l'événement du portail. Quel support si l'accès reste bloqué ?",
    ("13-01", 1): "Registre de secours prévu : votre auteur, heure des faits et de consignation. Reprise ensuite dans votre compte avec traçabilité.",
    ("13-02", 0): "Deux fichiers : brouillon et version validée. Je vérifie statut, destinataire et pièce jointe. Une copie personnelle est demandée ; je ne l'ai pas envoyée.",
    ("14-01", 0): "PC, dépôt 2 : une personne déplace des colis dans la zone fermée. Ni effraction vue ni droits connus. J'observe en sécurité ; intervention à vérifier.",
    ("14-02", 0): "PC, Sortie 1 : portique déclenché, ticket présenté, étiquette de protection sur l'article. Aucune dissimulation vue. Vérification du paiement demandée.",
    ("14-03", 0): "PC : on me demande de quitter le poste incendie pour retenir un client. Ni flagrance précise ni danger immédiat décrit. Je reste au poste ; relais sûreté demandé.",
    ("14-03", 1): "Je fais traiter le différend par le relais adapté ; continuité de votre poste maintenue. Signalez toute alarme de votre mission.",
    ("14-04", 0): "PC, Équipe 2 : plus de résistance, difficulté respiratoire déclarée. Nous réévaluons immédiatement les moyens. Aide médicale et information police demandées.",
    ("14-04", 1): "Difficulté respiratoire reçue. J'alerte les secours sans attendre et informe les autorités. Surveillez les signes et suivez les instructions compétentes.",
    ("14-05", 0): "PC, couloir C : fragments au sol, nettoyage demandé. Un détour sûr existe ; je préserve la zone selon consigne. Relais aux autorités demandé.",
    ("14-05", 1): "Maintenez le détour sûr. Tracez toute modification nécessaire pour protéger une personne ; ne déplacez pas les fragments pour les présenter.",
    ("14-06", 0): "17 h 12 : porte forcée constatée, ouverture non vue. 17 h 14 : choc déclaré par un témoin. 17 h 15 : passage protégé. Ticket et coordonnées référencés au dossier.",
    ("14-07", 0): "PC, Dépôt 1 : salarié, prestataire, colis ouvert ; aucun acte précis décrit. Situation calme. Je demande la vérification de l'autorisation d'ouverture.",
    ("15-01", 0): "PC, Entrée 3 : nos plans placent l'entrée à l'est et au sud, avec repères secours différents. Demande d'une version commune validée avant ouverture.",
    ("15-02", 0): "PC, Coulisses 1 : badge public, accès technique demandé, aucune extension. La personne attend. Demande du contact habilité aux accréditations.",
    ("15-03", 0): "PC, E2 : file sur le cheminement de sortie, passage réduit, arrivées continues. Demande du responsable pour dégager et agir en amont.",
    ("15-03", 1): "Reçu, E2. Responsable mobilisé pour l'adaptation coordonnée. Gardez les dégagements ; ne fermez pas la sortie pour stocker la file.",
    ("15-04", 0): "PC, urgence P4 : perte de liberté de déplacement signalée, densification et progression bloquée observées. Coordination immédiate du dispositif demandée.",
    ("15-05", 0): "PC, secteur bleu : porte B encombrée. Aucun public dirigé vers C non vérifiée. Confirmez un cheminement libre et un point d'accueil accessible.",
    ("15-05", 1): "Le responsable confirme porte D et point Prairie, avec l'appui prévu. Diffusez cette seule consigne ; rendez compte des difficultés.",
    ("15-06", 0): "PC, Accès 2 : secours, livraison et presse arrivent ensemble. Voie secours libre ; autres flux en attente prévue. Contacts logistique et presse demandés.",
    ("15-07", 0): "Billetterie : billet signalé déjà utilisé, achat présenté, entrée antérieure niée. Personne orientée au point litiges. Vérifiez la référence dans l'outil.",
}
for _section_id, _scene in RADIO_DEMONSTRATIONS.items():
    for _index, _turn in enumerate(_scene["turns"]):
        _turn["display_text"] = _DISPLAY.get((_section_id[6:], _index), _turn["text"])
