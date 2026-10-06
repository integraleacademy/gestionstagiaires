"""Editorial content for the manuals showcase, separate from order pricing.

Based on the supplied 2026 collection brochure. Edition-dependent lesson counts
and obsolete combined SSIAP/SST descriptions are deliberately not advertised.
Prices always come from manuals_shop.CATALOGUE.
"""

PRESENTATIONS = {
    "ssiap1": {
        "audience": "Pour vos stagiaires en sécurité incendie",
        "lead": "Rendre la sécurité incendie concrète, page après page.",
        "intro": "Un support illustré pour accompagner les cours de sécurité incendie et d’assistance à personnes. Les scènes métier, les schémas et les repères opérationnels aident vos stagiaires à faire le lien entre les notions abordées en salle et les situations professionnelles.",
        "tags": ["Scènes métier", "Schémas pédagogiques", "Repères opérationnels"],
        "features": [
            ("Se projeter dans le métier", "Des scènes professionnelles illustrées pour donner du contexte aux explications du formateur et ouvrir les échanges avec le groupe."),
            ("Comprendre par l’image", "Des schémas pédagogiques pour rendre les notions plus accessibles et accompagner les explications étape par étape."),
            ("Retrouver les points essentiels", "Des repères opérationnels à consulter pendant la formation, puis à reprendre lors des révisions."),
        ],
        "preview_labels": ["Scènes métier illustrées", "Schémas pédagogiques", "Repères opérationnels"],
    },
    "aps": {
        "audience": "Pour vos futurs agents de prévention et de sécurité",
        "lead": "Relier les cours aux missions quotidiennes de l’agent.",
        "intro": "Un manuel qui s’appuie sur des situations professionnelles pour donner du sens aux apprentissages. Les illustrations et les ateliers visuels permettent au formateur d’expliquer, de faire observer et de relier les notions aux missions de prévention et de sécurité.",
        "tags": ["Situations professionnelles", "Ateliers visuels", "Cas concrets"],
        "features": [
            ("Partir de situations concrètes", "Des scènes du quotidien professionnel pour mettre les notions en perspective et nourrir les échanges en formation."),
            ("Observer pour mieux comprendre", "Des supports visuels pour repérer les informations utiles, comparer les situations et expliquer les choix professionnels."),
            ("Accompagner les révisions", "Un support que chaque stagiaire peut annoter et reprendre entre les journées de formation pour consolider ses acquis."),
        ],
        "preview_labels": ["Situations professionnelles", "Ateliers visuels", "Mises en pratique"],
    },
    "a3p": {
        "audience": "Pour vos stagiaires en protection physique des personnes",
        "lead": "Visualiser les missions et comprendre les méthodes de protection.",
        "intro": "Les missions illustrées et les schémas de protection donnent des repères visuels aux stagiaires. Ce support accompagne le travail du formateur en reliant les explications aux méthodes de mission et aux exemples professionnels.",
        "tags": ["Missions illustrées", "Schémas de protection", "Méthodes de mission"],
        "features": [
            ("Donner du contexte aux missions", "Des illustrations pour présenter les situations professionnelles et aider le groupe à en identifier les enjeux."),
            ("Expliquer avec des schémas", "Des représentations visuelles pour accompagner l’explication des méthodes de protection des personnes."),
            ("Structurer les apprentissages", "Des dossiers et des exemples professionnels à retrouver pendant les cours et lors du travail de révision."),
        ],
        "preview_labels": ["Missions illustrées", "Schémas de protection", "Exemples professionnels"],
    },
    "vtc": {
        "audience": "Pour vos futurs chauffeurs VTC",
        "lead": "Un fil conducteur pour apprendre, comprendre et réviser.",
        "intro": "Un support structuré qui associe illustrations pleine page, notions expliquées en images et cas pratiques commentés. Il aide à organiser les révisions et à travailler les situations professionnelles liées à l’activité de chauffeur VTC.",
        "tags": ["Illustrations pleine page", "Notions en images", "Cas pratiques commentés"],
        "features": [
            ("Donner envie d’ouvrir le manuel", "Des illustrations pleine page pour introduire les sujets et créer des points de repère au fil de la formation."),
            ("Rendre les notions accessibles", "Des explications visuelles que le formateur peut reprendre pour guider le groupe dans les apprentissages."),
            ("Relier théorie et situations métier", "Des cas pratiques commentés pour prolonger les cours et préparer les séances de révision."),
        ],
        "preview_labels": ["Illustrations pleine page", "Notions en images", "Cas pratiques commentés"],
    },
    "dssp": {
        "audience": "Pour vos stagiaires dirigeants de sociétés de sécurité privée",
        "lead": "Des méthodes et des repères pour aborder la gestion d’une société.",
        "intro": "Un manuel consacré à la gestion d’une société de sécurité privée, avec des méthodes, des calculs expliqués et des fiches professionnelles. Il donne des supports concrets au formateur pour aborder le management et l’organisation.",
        "tags": ["Management et organisation", "Calculs expliqués", "Fiches professionnelles"],
        "features": [
            ("Aborder le management", "Des supports consacrés à l’organisation pour mettre en perspective les responsabilités du dirigeant."),
            ("Comprendre les calculs", "Des calculs expliqués pour accompagner le raisonnement et reprendre les méthodes abordées pendant les cours."),
            ("S’appuyer sur des fiches", "Des fiches professionnelles pour retrouver les repères utiles et prolonger le travail du formateur."),
        ],
        "preview_labels": ["Management et organisation", "Calculs expliqués", "Fiches professionnelles"],
    },
    "sst": {
        "audience": "Pour vos stagiaires sauveteurs secouristes du travail",
        "lead": "Des repères visuels pour la prévention et les premiers secours.",
        "intro": "Un support dédié à la prévention et aux premiers secours, avec des situations et des repères illustrés. Il accompagne les explications du formateur et permet aux stagiaires de retrouver les notions travaillées pendant la formation.",
        "tags": ["Prévention en images", "Premiers secours", "Repères illustrés"],
        "features": [
            ("Comprendre la prévention", "Des situations illustrées pour observer, échanger et rendre les notions de prévention plus concrètes."),
            ("Accompagner l’apprentissage", "Des repères visuels à reprendre avec le formateur en complément des démonstrations et des mises en situation."),
            ("Conserver un support de référence", "Un manuel à consulter pour revoir les points abordés et garder une trace de la formation."),
        ],
        "preview_labels": ["Prévention en images", "Schémas de prévention", "Alerte et organisation"],
        "preview_note": "Exemples de contenus SST issus de la collection, présentés dans la brochure.",
    },
}


def presentation_books(catalogue):
    """Join editorial material onto the existing, authoritative price catalogue."""
    return [dict(book, **PRESENTATIONS[book["code"]]) for book in catalogue]
