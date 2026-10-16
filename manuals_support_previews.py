"""Small public selections, never the complete trainer files.

APS / SSIAP 1 are captures of supplied PowerPoints. Other references use newly
authored presentation slides based on the selected manual pages, explicitly
labelled as pedagogical previews rather than captures of a delivered deck.
Illustrations are extracted from those same public manual selections.
Electrical/first-aid wording was also checked against INRS on 2026-10-13:
https://www.inrs.fr/risques/electriques/habilitation-electrique-foire-aux-questions
https://www.inrs.fr/risques/electriques/operations-installations.html
https://www.inrs.fr/demarche/organisation-secours/alerte-signalisation-moyens-secours
"""


def lesson(title, lead, points, takeaway):
    return dict(kind="lesson", label="Repères du cours", title=title, lead=lead,
                points=points, takeaway=takeaway)


def method(title, lead, rows, takeaway):
    return dict(kind="method", label="Méthode en pratique", title=title, lead=lead,
                rows=rows, takeaway=takeaway)


def case(title, scenario, questions, takeaway):
    return dict(kind="case", label="Situation à discuter", title=title,
                scenario=scenario, questions=questions, takeaway=takeaway)


SUPPORT_PREVIEWS = {
    "aps": {
        "capture": True,
        "description": "Gestion des conflits, sécurité incendie et vidéosurveillance : trois extraits du PowerPoint APS pour découvrir le cours en situation.",
        "slides": [
            {"title": "Un atelier de gestion des conflits", "image": "aps-1.webp"},
            {"title": "Comprendre la mise en sécurité incendie", "image": "aps-2.webp"},
            {"title": "Lire une image de vidéosurveillance", "image": "aps-3.webp"},
        ],
    },
    "ssiap1": {
        "capture": True,
        "description": "Trois extraits du premier jour de formation : propagation de la chaleur, dangers des fumées et critères de résistance au feu.",
        "slides": [
            {"title": "Les chemins de la chaleur", "image": "ssiap1-1.webp"},
            {"title": "Comprendre les fumées", "image": "ssiap1-2.webp"},
            {"title": "Distinguer les critères R, E et I", "image": "ssiap1-3.webp"},
        ],
    },
    "mac_aps": {
        "source_pages": [7, 24, 60],
        "description": "Accueil du public, communication et préparation de la vacation : trois situations pour remettre les pratiques professionnelles en perspective.",
        "slides": [
            lesson("Un accueil équitable", "La même qualité d’accueil, pour chaque personne.", [
                ("Respecter", "Accueillir sans jugement ni traitement discriminatoire."),
                ("Expliquer", "Présenter la consigne avec des mots clairs et un ton calme."),
                ("Adapter", "Tenir compte du besoin exprimé, dans le cadre de la mission."),
            ], "Une posture professionnelle se voit dès le premier échange."),
            method("Face à une agression verbale", "Garder le contrôle de sa communication.", [
                ("Écouter", "Repérer la demande derrière la tension, sans répondre aux insultes."),
                ("Recentrer", "Rappeler calmement la consigne et ce qui est possible."),
                ("Relayer", "Solliciter le relais prévu si la situation dépasse le cadre de la mission."),
            ], "Une réponse courte, stable et compréhensible aide à clarifier la situation."),
            case("Avant de prendre son poste", "Vous commencez une vacation sur un site inhabituel. Une consigne a changé et la radio n’a pas encore été vérifiée.", [
                "Quelles consignes faut-il confirmer avant la prise de poste ?",
                "Quels moyens et contacts devez-vous vérifier ?",
                "Comment signalez-vous une information manquante ?",
            ], "Une vacation se prépare : mission, consignes, moyens et interlocuteurs."),
        ],
    },
    "a3p": {
        "source_pages": [11, 177, 289],
        "description": "Cadrer la mission, préparer un déplacement et transmettre les informations utiles : des exemples pour animer les échanges avec le groupe.",
        "slides": [
            lesson("Définir le cadre de la mission", "Une préparation précise donne un cadre commun à l’équipe.", [
                ("Comprendre", "Recueillir la demande, les contraintes et les attentes."),
                ("Délimiter", "Clarifier le périmètre et les limites de la mission."),
                ("Partager", "Confirmer les rôles, les horaires et les interlocuteurs."),
            ], "Distinguer ce qui est demandé, ce qui est confirmé et ce qui reste à vérifier."),
            method("Préparer un déplacement", "Mettre les informations utiles au même niveau.", [
                ("Programme", "Horaires, étapes, contraintes et changements possibles."),
                ("Lieux", "Accès, points de rendez-vous et contacts sur place."),
                ("Équipe", "Répartition des rôles et modalités de communication."),
                ("Vérification", "Informations confirmées et points encore en attente."),
            ], "Une information non confirmée doit rester identifiée comme telle."),
            case("Le programme change", "Un rendez-vous est déplacé à la dernière minute. Le nouveau lieu est connu, mais l’accès et le contact sur place restent à confirmer.", [
                "Quelles informations faut-il obtenir en priorité ?",
                "Qui doit recevoir la mise à jour du programme ?",
                "Comment distinguer les faits confirmés des hypothèses ?",
            ], "Préparer, vérifier, transmettre : trois repères pour une mission cohérente."),
        ],
    },
    "dssp": {
        "source_pages": [277, 157, 385],
        "description": "Organisation d’équipe, construction d’un coût et suivi de la prévention : trois entrées pour travailler le pilotage d’une activité de sécurité privée.",
        "slides": [
            lesson("Préparer une équipe opérationnelle", "Les compétences, les consignes et les moyens se préparent ensemble.", [
                ("Mission", "Traduire la demande du client en besoins opérationnels."),
                ("Équipe", "Vérifier les compétences et répartir les responsabilités."),
                ("Moyens", "Prévoir le matériel, les consignes et les relais utiles."),
            ], "Une organisation claire permet à chacun de connaître son rôle."),
            method("Décomposer un coût horaire", "Un prix de prestation doit couvrir plusieurs composantes.", [
                ("Personnel", "Le coût des agents mobilisés pour la prestation."),
                ("Moyens", "Les équipements et les moyens nécessaires à la mission."),
                ("Encadrement", "La préparation, le suivi et la coordination."),
                ("Structure", "Les charges de fonctionnement à intégrer au calcul."),
            ], "Identifier les coûts avant de discuter le prix de vente."),
            case("Passer du constat à l’action", "Sur un site client, la circulation des agents croise une zone de livraison. Le risque est identifié, mais aucune action n’a encore de responsable.", [
                "Quelle mesure de prévention faut-il formaliser ?",
                "Qui porte l’action et pour quelle échéance ?",
                "Quelle vérification permettra d’en confirmer l’efficacité ?",
            ], "Un plan d’actions relie chaque mesure à un responsable, un délai et un contrôle."),
        ],
    },
    "ssiap2": {
        "source_pages": [11, 151, 221],
        "description": "Encadrer, transmettre et vérifier : trois aperçus consacrés au rôle du chef d’équipe et à la qualité des informations échangées.",
        "slides": [
            lesson("Expliquer, faire pratiquer, accompagner", "Une consigne comprise peut être reformulée et mise en œuvre.", [
                ("Expliquer", "Donner l’objectif et les repères utiles à l’équipe."),
                ("Faire pratiquer", "Proposer une situation adaptée à la séance."),
                ("Accompagner", "Observer, faire reformuler et reprendre les points fragiles."),
            ], "Le chef d’équipe vérifie la compréhension, pas seulement la transmission."),
            method("Transmettre une mission claire", "Quatre informations pour éviter les interprétations.", [
                ("Destinataire", "À qui s’adresse précisément la consigne ?"),
                ("Localisation", "Quel bâtiment, niveau ou secteur est concerné ?"),
                ("Action", "Quelle action est attendue dans le cadre des consignes ?"),
                ("Retour", "Quelle information faut-il transmettre, et à qui ?"),
            ], "Un message exploitable permet au destinataire de savoir ce qui est attendu."),
            case("Le retour d’information manque", "Depuis le poste de sécurité, vous avez confié une mission à un agent. Un second événement survient alors que son retour n’a pas encore été reçu.", [
                "Quelles informations sont déjà confirmées ?",
                "Comment clarifier l’état de la mission en cours ?",
                "Quels éléments transmettre à l’équipe pour la coordination ?",
            ], "Coordonner suppose de suivre les actions et de conserver une vision partagée."),
        ],
    },
    "ssiap3": {
        "source_pages": [1, 2, 3],
        "description": "Conseil à l’exploitant, analyse des risques et priorisation : des exemples pour illustrer le travail du chef de service.",
        "slides": [
            lesson("Conseiller à partir de faits", "Transformer un constat de terrain en décision argumentée.", [
                ("Constater", "Décrire les faits et préciser leur localisation."),
                ("Analyser", "Relier la situation aux risques et aux protections existantes."),
                ("Proposer", "Présenter les actions possibles et leur suivi."),
            ], "Un conseil utile relie le constat, l’enjeu et la décision à prendre."),
            method("Structurer l’analyse des risques", "Quatre questions pour organiser le raisonnement.", [
                ("Danger", "Quelle situation peut provoquer un dommage ?"),
                ("Personnes", "Qui peut être exposé, et dans quelles circonstances ?"),
                ("Protection", "Quelles mesures sont déjà en place ?"),
                ("Amélioration", "Quelles actions complémentaires faut-il proposer ?"),
            ], "Une analyse sert à orienter l’action et à expliquer les priorités."),
            case("Argumenter une priorité budgétaire", "Vous préparez le budget du service. Plusieurs besoins sont recensés : maintenance, formation de l’équipe et renouvellement d’équipements.", [
                "Quels constats justifient chaque besoin ?",
                "Quels critères permettent de hiérarchiser les demandes ?",
                "Comment présenter une décision et son calendrier de suivi ?",
            ], "Présenter un budget, c’est rendre lisibles les besoins et leurs conséquences."),
        ],
    },
    "ssiap1_recyclage": {
        "source_pages": [17, 30, 54],
        "description": "Prévention, lecture de la chaîne SSI et échanges au poste de sécurité : des situations pour réactiver les repères du métier.",
        "slides": [
            lesson("Observer avec méthode", "La prévention commence par des constats précis.", [
                ("Repérer", "Observer les circulations, les accès et les anomalies visibles."),
                ("Situer", "Identifier exactement le lieu et les éléments concernés."),
                ("Transmettre", "Rendre compte selon les consignes du site."),
            ], "Un constat localisé aide à décider et à suivre la réponse apportée."),
            method("Comprendre la chaîne SSI", "Relier l’information reçue aux fonctions du système.", [
                ("Information", "Un événement ou un état est signalé par le système."),
                ("Traitement", "L’information est prise en compte selon l’organisation du SSI."),
                ("Action", "Les fonctions de mise en sécurité concernées sont sollicitées."),
            ], "L’exploitation du SSI s’appuie sur les consignes et les équipements du site."),
            case("Une information arrive au PC", "Un appel signale une odeur inhabituelle au premier étage. Le bâtiment est occupé et la localisation reste imprécise.", [
                "Quelles précisions faut-il recueillir ?",
                "Quels faits sont confirmés à ce stade ?",
                "Comment transmettre une information claire selon les consignes ?",
            ], "En exercice, distinguer l’observation, le message reçu et l’hypothèse."),
        ],
    },
    "ssiap2_recyclage": {
        "source_pages": [4, 5, 6],
        "description": "Coordination au PC, qualité des messages et animation d’une séquence : trois situations centrées sur les pratiques du chef d’équipe.",
        "slides": [
            lesson("Coordonner depuis le poste de sécurité", "Conserver une vision claire des missions et des informations.", [
                ("Répartir", "Attribuer les missions et préciser les attentes."),
                ("Recueillir", "Centraliser les retours utiles de l’équipe."),
                ("Actualiser", "Partager les changements de situation confirmés."),
            ], "La coordination dépend autant du suivi que de la consigne initiale."),
            method("Construire un message exploitable", "Privilégier les faits, la précision et la demande attendue.", [
                ("Qui ?", "Identifier l’émetteur et le destinataire."),
                ("Où ?", "Donner une localisation sans ambiguïté."),
                ("Quoi ?", "Décrire les faits utiles et l’état de la situation."),
                ("Attente", "Préciser l’action ou le retour demandé."),
            ], "Une reformulation permet de vérifier que le message a été compris."),
            case("Animer une courte instruction", "Vous préparez une séquence de rappel pour l’équipe. Les agents connaissent la consigne, mais les pratiques observées ne sont pas homogènes.", [
                "Quel objectif concret donnez-vous à la séquence ?",
                "Quelle situation permet de faire pratiquer les agents ?",
                "Comment vérifiez-vous leur compréhension à la fin ?",
            ], "Donner un objectif, faire pratiquer, puis vérifier les acquis."),
        ],
    },
    "ssiap3_recyclage": {
        "source_pages": [7, 8, 9],
        "description": "Suivi des installations, traitement des anomalies et projet d’aménagement : des exemples pour travailler la décision et la traçabilité.",
        "slides": [
            lesson("Piloter le suivi des installations", "Faire le lien entre les échéances, les constats et les actions.", [
                ("Planifier", "Tenir à jour les échéances et les interventions prévues."),
                ("Exploiter", "Lire les comptes rendus et identifier les points à traiter."),
                ("Vérifier", "Suivre les corrections et conserver leur traçabilité."),
            ], "Un compte rendu reçu n’est pas, à lui seul, une anomalie résolue."),
            method("Suivre une anomalie jusqu’à sa clôture", "Une chaîne de suivi lisible pour chaque point relevé.", [
                ("Identifier", "Décrire et localiser l’anomalie."),
                ("Analyser", "Évaluer ses conséquences et la priorité de traitement."),
                ("Agir", "Désigner l’action, son responsable et son échéance."),
                ("Vérifier", "Contrôler le résultat avant de clôturer le suivi."),
            ], "La preuve de correction donne du sens à la clôture d’une action."),
            case("Accompagner un aménagement", "Un projet modifie l’usage de plusieurs locaux et les circulations. Vous êtes consulté avant la validation du nouvel aménagement.", [
                "Quels changements d’usage faut-il clarifier ?",
                "Quelles incidences sur les circulations et protections examiner ?",
                "Comment formaliser les points à valider et leur suivi ?",
            ], "Intégrer la sécurité dès la préparation du projet facilite les décisions."),
        ],
    },
    "h0b0": {
        "source_pages": [6, 12, 30],
        "description": "Identifier sa mission, comprendre ses limites et signaler une anomalie : des repères pour les opérations d’ordre non électrique.",
        "slides": [
            lesson("Identifier avant d’entrer", "Le lieu ne suffit pas à définir ce que l’on est autorisé à faire.", [
                ("Mission", "Comprendre la tâche non électrique confiée."),
                ("Périmètre", "Identifier les accès, limites et consignes applicables."),
                ("Interlocuteur", "Savoir à qui demander une précision ou signaler un écart."),
            ], "Le titre d’habilitation et les consignes déterminent le cadre de la mission."),
            method("Rester dans le cadre H0 / B0", "Des habilitations pour des opérations d’ordre non électrique.", [
                ("Tâche", "Respecter la nature de l’opération confiée."),
                ("Limites", "Ne pas réaliser de dépannage ou d’intervention électrique."),
                ("Zone", "Respecter le balisage, les accès et les consignes."),
                ("Doute", "Interrompre la tâche et solliciter le responsable désigné."),
            ], "Une habilitation H0 / B0 ne donne pas une autorisation générale d’agir."),
            case("Un écart sur le lieu de travail", "Vous arrivez pour une tâche non électrique. Le balisage diffère de celui présenté au briefing et un câble paraît endommagé.", [
                "Quelles différences constatez-vous par rapport aux consignes ?",
                "À qui signalez-vous la situation sans intervenir sur le câble ?",
                "Quelles précisions sont nécessaires avant de reprendre la tâche ?",
            ], "En cas d’écart, ne pas improviser : interrompre, signaler, faire clarifier."),
        ],
    },
    "bs_be": {
        "source_pages": [12, 8, 51],
        "description": "Repérage, distinction des missions BS et BE Manœuvre, compte rendu : trois angles pour aborder le cadre d’intervention.",
        "slides": [
            lesson("Comprendre avant d’agir", "Identifier l’équipement et le cadre exact de l’opération confiée.", [
                ("Repérer", "Identifier l’installation et l’équipement concernés."),
                ("Vérifier", "Relier la tâche au titre d’habilitation et aux consignes."),
                ("Clarifier", "Faire préciser toute information manquante avant l’opération."),
            ], "L’habilitation correspond à des opérations définies, dans des limites précises."),
            method("BS et BE Manœuvre : deux cadres", "La nature de l’opération détermine le rôle attendu.", [
                ("BS", "Interventions élémentaires en basse tension, dans les limites prévues."),
                ("BE Manœuvre", "Manœuvres d’exploitation ou de consignation, dans le cadre confié."),
                ("Point commun", "Respect du titre, des instructions et des limites de l’opération."),
            ], "Un intitulé d’habilitation ne remplace ni la formation ni les instructions."),
            case("Rendre compte d’une situation inhabituelle", "L’état constaté sur un équipement ne correspond pas à celui annoncé dans les instructions. L’opération ne peut pas être engagée comme prévu.", [
                "Comment identifier précisément l’équipement concerné ?",
                "Quels faits et écarts faut-il transmettre au responsable ?",
                "Comment tracer la situation et les consignes reçues ?",
            ], "Décrire l’équipement, le constat, l’heure et les points restant à clarifier."),
        ],
    },
    "vtc": {
        "source_pages": [14, 117, 138],
        "description": "Préparation de l’activité, repères de gestion et relation client : trois exemples pour relier le cours à des situations professionnelles.",
        "slides": [
            lesson("Préparer une prestation VTC", "Relier l’organisation de l’activité à la qualité du service.", [
                ("Conducteur", "Vérifier sa situation et les documents utiles à l’activité."),
                ("Véhicule", "Préparer le véhicule et les éléments nécessaires à la prestation."),
                ("Mission", "Confirmer la réservation, les horaires et les besoins du client."),
            ], "Une prestation réussie commence avant la prise en charge du client."),
            method("Distinguer activité et trésorerie", "Trois notions à ne pas confondre dans le suivi de l’activité.", [
                ("Chiffre d’affaires", "Le montant des prestations réalisées sur la période."),
                ("Encaissements", "Les sommes effectivement reçues sur la période."),
                ("Décaissements", "Les sommes effectivement payées sur la période."),
            ], "Une prestation réalisée et son règlement peuvent intervenir à des dates différentes."),
            case("Un horaire de prise en charge évolue", "Le client vous annonce un changement d’horaire. Une autre réservation suit et les conditions de circulation ont évolué.", [
                "Quelles informations faut-il confirmer avec le client ?",
                "Comment réévaluer l’organisation des deux prestations ?",
                "Quel message permet de présenter clairement la solution proposée ?",
            ], "Anticiper et communiquer sans laisser la contrainte horaire dicter une conduite risquée."),
        ],
    },
    "sst": {
        "source_pages": [6, 10, 30],
        "description": "Prévention, informations d’alerte et repérage d’une situation : des exemples pour faire participer le groupe sans remplacer la pratique encadrée.",
        "slides": [
            lesson("Prévenir avant l’accident", "Observer une situation de travail et faire remonter les risques.", [
                ("Observer", "Repérer les dangers, les passages et les situations inhabituelles."),
                ("Décrire", "Expliquer les faits et les personnes potentiellement exposées."),
                ("Signaler", "Transmettre aux personnes chargées de la prévention dans l’entreprise."),
            ], "Le SST contribue aussi à la prévention des risques professionnels."),
            method("Transmettre une alerte précise", "Des informations utiles pour orienter les secours.", [
                ("Où ?", "Le lieu exact et les indications pour accéder à la zone."),
                ("Quoi ?", "La nature de l’événement et les dangers constatés."),
                ("Combien ?", "Le nombre de personnes concernées et leur état apparent."),
                ("Échange", "Répondre aux questions et suivre les consignes de l’interlocuteur."),
            ], "L’alerte s’inscrit dans l’organisation des secours de l’entreprise."),
            case("Observer une zone encombrée", "Dans un atelier, des colis encombrent un passage. Un câble traverse la circulation et l’accès prévu pour les secours est partiellement occupé.", [
                "Quels dangers et quelles personnes exposées repérez-vous ?",
                "Quelles informations faut-il transmettre au responsable ?",
                "Quels points de prévention faut-il suivre après le signalement ?",
            ], "Les gestes de secours s’apprennent et se pratiquent avec le formateur SST."),
        ],
    },
}
