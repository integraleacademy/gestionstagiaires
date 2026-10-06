# APS : édition enrichie du 6 octobre 2026

L'édition `20261006-aps62-v3` approfondit les 15 modules existants. Les anciennes
éditions, les médias, les affectations et les progressions déjà enregistrées
restent distincts. Aucune migration automatique des sessions n'est effectuée.
L'administrateur choisit la nouvelle édition lors de la composition d'un parcours.

## Contenu

- 62 dossiers, 558 activités, 248 ateliers corrigés côté serveur.
- 62 nouveaux cas métier, chacun avec cinq décisions successives et une évolution.
- 62 analyses documentaires : fiche d'événement, consigne validée, brouillon
  comportant des écarts de fond, de chronologie et de clôture.
- 62 simulations de main courante composées par six choix ; aucune rédaction libre.
- 62 situations distinctes réservées aux révisions ciblées. Seules les difficultés
  repérées déclenchent un exercice de révision ; une même révision n'est pas répétée
  lorsqu'elle répond à plusieurs erreurs d'une activité.
- Approfondissements juridiques et professionnels, exemples expliqués et comparaison
  des décisions avant et après une nouvelle information.
- Les deux questions de banque d'examen auparavant répétées dans chaque transfert
  sont remplacées par une comparaison de contextes. Les banques d'examens blancs
  sont conservées, et ne sont pas présentées comme de nouvelles questions.

Le modèle de 60 minutes par dossier répartit 16 minutes de compréhension, 4 de
mémorisation, 12 de mission, 6 de questionnaire, 6 de transfert, 8 d'analyse de
documents, 6 de main courante et 2 de synthèse. Il s'agit d'une hypothèse de charge
guidée. Aucun essai apprenant n'établit encore que le contenu occupe réellement
62 heures. Les vidéos existantes ne sont ni rallongées ni comptées comme nouvelles.

## Progression et limites

Les exercices et les questionnaires de la nouvelle édition doivent être corrigés
avant de poursuivre. Une réponse incorrecte au questionnaire renvoie l'explication
et permet un nouvel essai, sans marquer l'activité comme terminée. Les versions
antérieures conservent leur comportement et leur historique. Le score du cours est
donc un résultat après correction ; les examens blancs restent des entraînements
séparés. Les révisions sont proposées pendant l'activité et ne constituent pas un
diagnostic durable des difficultés de l'apprenant.

Les réponses attendues et les corrigés des révisions restent côté serveur. Les
conséquences des choix des missions sont visibles immédiatement, dans un objectif
formatif. La vérification d'une révision ne valide pas à elle seule l'exercice
initial. Les contrôles d'accès, CSRF, vidéos et temps actif restent appliqués.

## Correspondance réglementaire

Le catalogue affiche les objectifs, les liens vers les dossiers et les limites de
chacun des 15 modules, à partir de `elearning_native/aps62/regulatory_review.json`.

- Arrêté du 1er septembre 2025, annexes II et III : 62 h de séquences théoriques
  rapprochées du parcours, dans le cadre réglementaire de la formation initiale.
- ADEF, TFP APS : 50 h 30 de séquences identifiées à distance, plafond 51 h. Les
  blocs 07, 08, 10, 12, 13 et 14 ne sont pas imputables intégralement à distance.
- Arrêté du 23 octobre 2024, article 8 : modalités déclarées, questionnaires,
  tableaux signés, réunion initiale, assistance, communication, suivi et
  conservation des données doivent aussi être vérifiés dans l'organisation réelle.

La présence d'une correspondance ne vaut pas attestation de conformité complète.
Le module 12 nécessite une validation et des compléments de supports spécialisés
de reconnaissance. Les modules 08 et 13 préparent la qualité documentaire ; la
production autonome et l'usage de l'outil doivent être observés. Les gestes et les
entraînements pratiques restent dans les séquences présentielles requises.

Sources vérifiées le 06/10/2026 :

- https://www.legifrance.gouv.fr/loda/id/JORFTEXT000052197461/
- https://adef-securite.fr/tfp-aps-quelles-sequences-peuvent-etre-dispensees-a-distance-et-lesquelles-doivent-rester-en-presentiel/
- https://www.legifrance.gouv.fr/loda/id/JORFTEXT000050398597/

## Maintenance

Les cas et approfondissements sont rédigés dans `scripts/aps62_v3/`. Le script
`python scripts/build_aps62_v3.py` régénère exclusivement la version 3 et son
manifeste. Après affectation à des apprenants, publier les futures évolutions dans
une nouvelle version plutôt que réécrire cette édition.

Tests : intégrité des 62 cas, correction de tous les ateliers, affichage des
558 activités, absence de rédaction, correction des révisions, validation avant
progression, accès/CSRF, conservation des anciennes éditions et examens, DOM des
missions successives et de la main courante.
