"""Authored written complements to the APS theoretical terrorism sequence.

The v9 audio/video is deliberately not edited or relabelled as new narration.
These texts use the existing accessible lesson, glossary and diagram renderer.
"""

VERSION = "20261012-aps62-v12"
PREVIOUS = "20261010-aps62-v11"
DATE = "2026-10-12"

CURRICULUM = ["Arrêté du 1er septembre 2025, annexe III", "https://www.legifrance.gouv.fr/jorf/article_jo/JORFARTI000052197599"]
VIGIPIRATE = ["SGDSN : plan Vigipirate", "https://www.sgdsn.gouv.fr/vigipirate"]
PROTECTION = ["Consignes publiques : réagir en cas d’attaque terroriste", "https://www.info.gouv.fr/risques/reagir-en-cas-dattaque-terroriste"]
NRBC = ["SGDSN : protection et prévention des risques NRBC-E", "https://www.sgdsn.gouv.fr/nos-missions/anticiper-et-prevenir/ameliorer-les-dispositifs-de-protection-et-de-prevention"]
CYBER = ["Cybermalveillance.gouv.fr : hameçonnage", "https://www.cybermalveillance.gouv.fr/tous-nos-contenus/fiches-reflexes/16"]
PNEUMOTHORAX = ["Assurance Maladie : pneumothorax et signes d’alerte", "https://www.ameli.fr/assure/sante/urgence/pathologies/pneumothorax"]
BLAST = ["CDC : lésions pulmonaires provoquées par une explosion", "https://www.cdc.gov/mmwr/preview/mmwrhtml/mm5429a5.htm"]
SECOURS = ["Sécurité civile : références techniques nationales de secourisme", "https://www.securite-civile.interieur.gouv.fr/documentation/secourisme-et-associations/secourisme-references-techniques-nationales.html"]
ELECTRICAL = ["INRS : habilitation électrique", "https://www.inrs.fr/risques/electriques/habilitation-electrique"]


LESSONS = {
    "12.01": {
        "title": "Comprendre la menace et les modes d’action",
        "objectives": [
            "Distinguer un fait violent, une menace rapportée et une qualification terroriste établie par les autorités.",
            "Reconnaître les grandes familles de modes d’action pour transmettre des observations utiles.",
            "Relier chaque situation aux besoins de protection, sans déduire une intention d’une apparence."
        ],
        "parts": [
            ("Définition et limites du rôle de l’APS", [
                "Le terrorisme associe des actes graves à un projet visant notamment à intimider ou à terroriser une population. Le droit en précise les conditions. Une agression, une explosion ou un incendie ne devient donc pas automatiquement un acte terroriste : sa cause et son intention restent à établir. L’APS transmet les faits et les menaces reçues ; il ne conduit pas cette qualification.",
                "Une motivation idéologique, politique ou religieuse peut être revendiquée par un auteur. Une revendication peut aussi être fausse. L’origine, la religion, la tenue ou une opinion d’une personne ne prouvent ni projet violent ni appartenance à une organisation. La vigilance porte sur des actes précis, des menaces explicites et des anomalies du dispositif de sécurité."
            ]),
            ("Reconnaître les modes d’action traditionnels", [
                "Une attaque peut viser sans distinction un lieu fréquenté. Elle peut prendre la forme d’un assaut armé, d’une prise d’otages, d’un véhicule utilisé pour heurter volontairement des personnes ou d’une action dans laquelle l’auteur prévoit de mourir. Plusieurs formes peuvent se combiner. Ces catégories servent à comprendre une information ; elles ne constituent pas une méthode d’identification d’un individu.",
                "Face à des tirs rapportés, l’information utile est le lieu, l’heure, le nombre de détonations perçues si vous le connaissez et la direction observée des déplacements. Face à une prise d’otages rapportée, précisez la source, le lieu et ce que le témoin a réellement vu. Ne vous approchez pas pour confirmer une catégorie, compter les auteurs ou filmer le matériel.",
                "Un véhicule qui heurte un accès peut relever d’un accident, d’une conduite dangereuse ou d’une action volontaire. Décrivez son trajet constaté, le point d’impact et le danger pour les personnes. La protection et l’alerte ne doivent pas attendre que l’intention soit connue."
            ]),
            ("Comprendre l’évolution de la menace sans enquêter", [
                "Le programme distingue des modes d’action déjà connus et des menaces émergentes, notamment NRBC-E et cyber. Les retours d’expérience permettent d’actualiser les consignes, les accès de secours et les moyens d’alerte. Ils ne permettent pas de prédire la prochaine attaque ni de garantir qu’un site est sans risque.",
                "Dans un exercice, séparez trois colonnes : ce qui est observé, ce qui est rapporté et ce qui reste inconnu. Exemple : « trois détonations entendues à 14 h 12 » est une perception ; « un témoin évoque une arme longue » est un témoignage ; « le groupe appartient à telle organisation » reste une affirmation non établie. Chaque transmission conserve cette différence."
            ])
        ],
        "cards": [
            ("Mode d’action", "Grande forme que peut prendre une attaque, par exemple un assaut armé ou une prise d’otages."),
            ("Qualification terroriste", "Qualification juridique dont les conditions doivent être établies ; l’APS transmet les faits sans la décider seul."),
            ("Observation objective", "Description de ce qui est perçu, avec le lieu, le moment, la source et les limites de l’information.")
        ],
        "sources": [CURRICULUM, VIGIPIRATE, PROTECTION]
    },
    "12.02": {
        "title": "Reconnaître les familles de matériels sans s’exposer",
        "objectives": [
            "Nommer les familles de matériels représentées sur une fiche pédagogique, sans prétendre identifier un modèle réel à distance.",
            "Distinguer une silhouette visible, une hypothèse et une identification confirmée par un spécialiste.",
            "Décrire un objet ou un matériel depuis une position sûre et appliquer la protection et l’alerte."
        ],
        "parts": [
            ("Lire la fiche de reconnaissance visuelle", [
                "La fiche montre des silhouettes simplifiées, sans échelle et sans mécanisme. Une arme de poing est compacte : le pistolet présente généralement une partie supérieure allongée au-dessus de la poignée ; le revolver comporte un barillet visible dans sa silhouette. Une arme longue présente une crosse et un canon allongé. Ces repères pédagogiques ne donnent aucune certitude sur un objet partiellement vu.",
                "Le fusil d’assaut représenté possède une crosse, une poignée et un chargeur saillant. Le fusil de chasse illustré montre une crosse traditionnelle et deux canons ; d’autres modèles de chasse n’ont pas cette silhouette. Le fusil à pompe est ici représenté avec un garde-main sous le canon. Le lance-roquettes apparaît comme un tube porté ; un simple tube observé n’est pas pour autant identifié comme une arme. Les familles se distinguent sur la fiche, mais leurs apparences réelles peuvent se recouvrir.",
                "Le calibre, les munitions présentes, l’état de chargement, la portée et le fonctionnement ne se déduisent pas de cette fiche. Lors d’un signalement réel, « objet ressemblant à une arme longue, crosse visible » est préférable à un modèle ou à un calibre inventé. Si vous ne voyez qu’une partie du matériel, dites-le."
            ]),
            ("Matériel factice : la ressemblance ne prouve pas l’absence de danger", [
                "Un matériel d’exercice doit être identifié et contrôlé par le formateur avant la séance, dans un cadre organisé. Un objet réaliste trouvé sur un site ne devient pas factice parce qu’un témoin l’affirme, parce qu’il paraît léger ou parce qu’il possède une marque de couleur. L’APS ne le prend pas en main pour trancher.",
                "Exercice de lecture de la fiche : cachez les titres et associez chaque silhouette à sa famille, puis formulez une description de deux éléments visibles. Ajoutez une inconnue que la fiche ne permet pas de résoudre. Une séance encadrée avec des supports factices adaptés permet au formateur de vérifier cette reconnaissance ; le schéma seul ne certifie pas cette compétence pratique."
            ]),
            ("Explosifs et objets suspects : aucune apparence ne suffit", [
                "Le programme demande de connaître la diversité d’aspect des matières explosives : solides, liquides ou présentées en vrac. Aucun de ces aspects ne permet à un APS d’identifier une substance. Une poudre, un liquide, un emballage fermé ou un objet usuel ne peut être déclaré explosif ou inoffensif à la seule vue.",
                "Un engin explosif improvisé, ou EEI, peut être dissimulé dans un contenant ordinaire. Le présent support décrit les limites de reconnaissance et la conduite de sauvegarde ; il ne présente ni assemblage, ni mécanisme, ni procédé de déclenchement. Ne cherchez pas à ouvrir, déplacer, tester, neutraliser ou faire manipuler l’objet par son propriétaire supposé.",
                "Depuis la position sûre déjà occupée, transmettez l’emplacement précis, l’heure de découverte, le contexte, l’aspect déjà visible et la présence de personnes exposées. Appliquez la consigne du site et les instructions des intervenants compétents pour les accès et l’éloignement. N’inventez pas de distance universelle et ne revenez pas auprès de l’objet pour améliorer la description."
            ])
        ],
        "cards": [
            ("Arme de poing", "Famille compacte comprenant notamment le pistolet et le revolver ; une silhouette ne confirme ni modèle ni état."),
            ("Arme longue", "Famille à canon allongé et généralement à crosse ; une observation partielle ne permet pas une identification certaine."),
            ("Matériel factice", "Support imitant un matériel réel, dont le statut doit être confirmé dans le cadre contrôlé de la formation.")
        ],
        "sources": [CURRICULUM, PROTECTION, VIGIPIRATE]
    },
    "12.06": {
        "title": "Comprendre les menaces NRBC-E et cyber",
        "objectives": [
            "Développer les lettres NRBC-E et distinguer une famille de danger d’une cause malveillante établie.",
            "Reconnaître les limites de l’observation et éviter une contamination ou une exposition supplémentaire.",
            "Traiter une sollicitation numérique suspecte sans transmettre de secrets ni modifier seul la sécurité du site."
        ],
        "parts": [
            ("NRBC-E : nommer les familles de dangers", [
                "N signifie nucléaire, R radiologique, B biologique, C chimique et E explosif. Le risque nucléaire concerne notamment les effets d’un événement nucléaire ; le risque radiologique concerne l’exposition à des rayonnements ou la dispersion de matières radioactives, sans qu’une explosion nucléaire soit nécessaire. Le risque biologique concerne des agents pouvant provoquer une maladie ; le risque chimique, des substances toxiques. Plusieurs dangers peuvent être associés.",
                "Ces termes décrivent des dangers, pas une preuve d’attentat. Une fuite industrielle, un accident de transport ou un acte volontaire peuvent produire des signes comparables. L’agent décrit un événement et applique la chaîne de protection prévue, sans choisir lui-même une substance, une cause ou un auteur."
            ]),
            ("Observer sans chercher à identifier une substance", [
                "Des malaises simultanés, une irritation, une difficulté respiratoire ou une matière répandue constituent des faits à signaler avec le lieu, l’heure et la source. L’absence d’odeur ou de couleur n’établit pas l’absence de danger ; les sens ne détectent pas tous les risques. Ne goûtez pas, ne sentez pas volontairement, ne touchez pas et ne prélevez pas un produit.",
                "Évitez d’exposer d’autres personnes ou de transporter un objet potentiellement contaminé vers une zone occupée. Un masque courant ou des gants usuels ne garantissent pas une protection NRBC. Les spécialistes décident des mesures adaptées, notamment de mise à l’abri, d’évacuation ou de décontamination. Depuis une zone sûre, empêchez les nouvelles expositions dans le cadre de la consigne et transmettez les observations sans improviser un nettoyage.",
                "Cas à comparer : un témoin annonce une poudre à la réception et plusieurs personnes toussent ; ailleurs, une alarme technique signale un produit industriel. Les causes ne sont pas établies dans le premier cas et restent à vérifier dans le second. Dans les deux cas, la localisation, les signes observés, les personnes exposées et la sécurité de l’accès sont utiles à l’alerte."
            ]),
            ("Cyber : protéger les informations et le dispositif du site", [
                "Une attaque informatique peut viser la confidentialité d’informations, leur intégrité ou la disponibilité d’un service. Pour l’APS, cela peut se présenter comme une demande inhabituelle de code, un faux message du responsable, une consigne modifiée sans validation ou l’indisponibilité d’un contrôle d’accès. Une panne seule ne prouve pas une cyberattaque.",
                "L’hameçonnage consiste à imiter un interlocuteur de confiance pour obtenir une action ou une information. Un message peut paraître urgent et porter un logo connu. N’utilisez pas le lien ou le numéro fourni dans le message suspect pour vérifier son auteur : contactez l’interlocuteur par un moyen connu et indépendant. Ne communiquez pas de mot de passe ou de code à usage unique ; signalez et conservez les éléments selon le circuit de l’organisme.",
                "Si un outil du poste devient indisponible, alertez le relais technique prévu et appliquez le mode dégradé validé. Ne désactivez pas seul des protections et ne tentez pas de contre-attaque. Un drone non identifié se traite lui aussi par une observation prudente et une alerte ; l’absence d’identité connue de son pilote ne prouve pas une intention terroriste et n’autorise pas une neutralisation improvisée."
            ])
        ],
        "cards": [
            ("NRBC-E", "Nucléaire, radiologique, biologique, chimique et explosif : des familles de dangers, sans présumer leur cause."),
            ("Contamination secondaire", "Propagation d’un contaminant vers une autre personne ou une autre zone, par exemple lors du déplacement d’un objet."),
            ("Vérification indépendante", "Confirmation par un contact connu, distinct des liens et coordonnées contenus dans la demande suspecte.")
        ],
        "sources": [CURRICULUM, NRBC, CYBER, VIGIPIRATE]
    },
    "12.07": {
        "title": "Blessures par balles et explosions : comprendre et alerter",
        "objectives": [
            "Expliquer les notions de projectile, d’hémorragie, de pneumothorax et de blast sans poser un diagnostic.",
            "Comprendre qu’une blessure grave peut être peu visible et qu’une amélioration apparente ne suffit pas à écarter le danger.",
            "Transmettre les signes observés, leur source, la localisation et les conditions d’accès depuis une position sûre."
        ],
        "parts": [
            ("Blessures par balles : l’aspect extérieur ne mesure pas la gravité", [
                "Une balle est un projectile. Elle peut provoquer des lésions internes dont l’étendue ne se voit pas depuis l’extérieur. L’APS ne déduit ni le trajet du projectile, ni le calibre, ni la gravité d’une petite plaie visible. Il ne cherche pas un projectile dans la blessure et ne retire pas un objet qui y est engagé.",
                "Une hémorragie est une perte importante de sang, visible ou interne. Décrivez un saignement abondant constaté, un malaise, une pâleur ou une modification de la conscience sans en déduire une cause certaine. Les secours ont besoin des signes et de leur évolution ; l’absence de sang visible ne permet pas d’exclure une lésion grave."
            ]),
            ("Pneumothorax : un risque respiratoire après un traumatisme", [
                "Un pneumothorax est une présence d’air entre le poumon et la paroi thoracique, dans l’espace pleural. Le poumon peut alors se déployer moins bien. Un traumatisme du thorax, notamment après une blessure par balle ou une explosion, peut en être une cause. Une douleur thoracique et une difficulté à respirer après un traumatisme justifient une alerte médicale urgente.",
                "Ces signes ne suffisent pas à identifier un pneumothorax. Dites « la personne décrit une douleur dans la poitrine et respire difficilement » plutôt qu’un diagnostic certain. La fiche montre le principe anatomique pour comprendre l’urgence ; elle ne forme à aucun geste invasif, drainage ou traitement médical."
            ]),
            ("Explosion : souffle, projections et impacts", [
                "Le blast désigne les effets du souffle d’une explosion. L’onde de pression peut léser notamment les poumons ou les oreilles sans blessure extérieure évidente. Une difficulté respiratoire ou un trouble de l’audition après une explosion mérite d’être transmis, même si la personne marche ou affirme aller mieux.",
                "L’explosion peut aussi projeter des fragments devenant des projectiles et provoquer des blessures pénétrantes. Une personne projetée peut subir des lésions lors d’un impact. Chaleur, brûlures et fumées peuvent s’ajouter. Ces mécanismes peuvent coexister ; on ne limite donc pas le bilan au seul saignement visible et on ne conclut pas à l’absence de blessure à partir d’un vêtement intact."
            ]),
            ("Construire un bilan utile depuis une zone sûre", [
                "Vérifiez d’abord les conditions de votre propre sécurité. Une victime visible ne rend pas l’approche sûre. Depuis une position protégée, alertez les secours par le numéro adapté à l’urgence et aux consignes : notamment 15 ou 112 pour l’urgence médicale ; le danger de sécurité relève aussi de la chaîne d’alerte prévue, dont le 17 selon la situation. Ne retardez pas une alerte urgente pour obtenir un bilan parfait.",
                "Donnez le site et l’accès précis, votre contact, la nature de l’événement observée ou rapportée, les dangers encore connus, le nombre de victimes réellement compté ou l’estimation clairement annoncée. Décrivez les signes visibles ou attribuez-les au témoin qui les rapporte : conscience, difficulté respiratoire, saignement, douleur exprimée. Signalez ce qui reste inaccessible ou inconnu, puis répondez aux questions de l’opérateur et suivez ses instructions.",
                "Exemple : « Je suis au PC du site B, accès secours rue des Ateliers. Depuis la zone protégée, je vois une personne consciente qui saigne à la jambe. Un témoin me rapporte une deuxième personne qui respire difficilement derrière le hall ; je ne la vois pas et l’accès n’est pas confirmé sûr. » Cette formulation permet le relais sans transformer le témoignage en observation directe.",
                "Les gestes de secours nécessitent la formation pratique prévue et des conditions d’intervention sûres. Ce dossier théorique prépare la reconnaissance des besoins et l’alerte ; il ne valide pas les gestes ni l’intervention dans une zone dangereuse."
            ])
        ],
        "cards": [
            ("Hémorragie", "Perte importante de sang, externe ou interne, qui peut engager rapidement le pronostic vital."),
            ("Pneumothorax", "Présence d’air dans l’espace pleural, entre le poumon et la paroi thoracique, pouvant gêner la respiration."),
            ("Blast", "Effets du souffle d’une explosion, avec des lésions possibles même sans blessure extérieure visible.")
        ],
        "sources": [CURRICULUM, PNEUMOTHORAX, BLAST, SECOURS, PROTECTION]
    }
}


DIAGRAMS = {
    "12.02": {
        "id": "aps62-materiels-v12", "src": "media/aps62/v12/reconnaissance-materiels.svg",
        "title": "Fiche de reconnaissance : familles de matériels",
        "alt": "Six silhouettes simplifiées : pistolet, revolver, fusil d’assaut, fusil de chasse, fusil à pompe et lance-roquettes. Les repères de forme et les limites d’identification sont détaillés dans le texte adjacent.",
        "scope": "Support théorique de reconnaissance de familles. Aucun modèle, dimension, mécanisme ou maniement n’est enseigné.",
        "caption": "Schémas pédagogiques sans échelle. Une ressemblance ne confirme ni le modèle, ni l’état, ni le caractère factice d’un objet. Édition du 12 octobre 2026.",
        "source_title": CURRICULUM[0], "source_url": CURRICULUM[1],
        "points": [
            {"label": "Reconnaître", "position": "Sur la fiche", "rule": "Associer une silhouette complète à une famille et nommer les éléments visibles."},
            {"label": "Décrire", "position": "Sur le site", "rule": "Transmettre ce qui est déjà visible depuis une position sûre, en précisant les limites de l’observation."},
            {"label": "Préserver la sécurité", "position": "Devant un objet réel", "rule": "Ne pas s’approcher, manipuler ou tester pour confirmer sa nature ; suivre la protection et l’alerte prévues."}
        ]
    },
    "12.06": {
        "id": "aps62-nrbc-v12", "src": "media/aps62/v12/nrbc-cyber.svg",
        "title": "Relier un danger aux informations utiles à l’alerte",
        "alt": "Cinq familles NRBC-E : nucléaire, radiologique, biologique, chimique et explosif. Un encadré cyber rappelle la vérification indépendante ; le bas de la fiche relie observations, protection et alerte.",
        "scope": "Les familles nomment des dangers. Elles ne permettent pas de déduire une substance, un auteur ou une intention à partir de quelques signes.",
        "caption": "Lecture théorique. Les mesures spécialisées relèvent des intervenants compétents et des consignes adaptées à la situation.",
        "source_title": NRBC[0], "source_url": NRBC[1],
        "points": [
            {"label": "Observation", "position": "Lieu et moment", "rule": "Décrire les signes déjà constatés, les personnes exposées et les incertitudes ; ne pas prélever de matière."},
            {"label": "Protection", "position": "Depuis une zone sûre", "rule": "Éviter de nouvelles expositions et appliquer les instructions ; ne pas improviser une décontamination."},
            {"label": "Cyber", "position": "Message inhabituel", "rule": "Ne pas utiliser le lien suspect ; vérifier l’auteur par un contact connu et signaler au circuit prévu."}
        ]
    },
    "12.07": {
        "id": "aps62-blessures-v12", "src": "media/aps62/v12/blessures-alerte.svg",
        "title": "Comprendre une blessure et transmettre les signes",
        "alt": "Schéma simplifié du thorax comparant un poumon déployé et un poumon moins déployé avec de l’air dans l’espace pleural. Quatre encadrés : hémorragie, pneumothorax, blast et projectiles. L’alerte décrit les signes sans diagnostic.",
        "scope": "Repères théoriques de gravité. Le schéma n’est ni un diagnostic ni un enseignement de gestes médicaux.",
        "caption": "Schéma non anatomique, non à l’échelle, sans représentation de soins. Un aspect extérieur rassurant ne suffit pas à écarter une lésion.",
        "source_title": PNEUMOTHORAX[0], "source_url": PNEUMOTHORAX[1],
        "points": [
            {"label": "Poumon", "position": "Dans le thorax", "rule": "De l’air dans l’espace pleural peut réduire le déploiement du poumon ; seul le relais médical établit le diagnostic."},
            {"label": "Gravité possible", "position": "Après balle ou explosion", "rule": "Transmettre notamment une difficulté respiratoire, un saignement ou une modification de la conscience, observés ou rapportés."},
            {"label": "Alerte", "position": "Depuis la zone sûre", "rule": "Préciser le lieu, les dangers, les victimes connues, les signes et leur source, ainsi que les limites d’accès."}
        ]
    }
}
