# Révision pédagogique APS — 13 octobre 2026

Le signalement portait sur les reprises du cas Horizon dans le premier module.
L'audit des 15 modules et 62 séquences de l'édition v12 a retrouvé 58 cours
contenant déjà le corrigé du dossier repris dans l'atelier. Les exemples étaient
aussi déclinés en guide, tableau, chaîne de décision et tri de phrases. Les
157 utilisations du manuel correspondaient à 73 références distinctes.

## Changements

- Un cours écrit centré sur la règle, les références illustrées et les nuances.
  Les paragraphes du manuel, les explications complémentaires et le schéma
  réglementaire de la tenue sont conservés. Les 84 reprises de références
  deviennent des rappels avec l'explication complète disponible à la demande.
- Le cas expliqué appartient désormais à la vidéo. Voix, sous-titres,
  transcription, identifiants et chronologie de lecture restent identiques.
- Les ateliers utilisent les 186 situations complémentaires de l'ancienne
  banque de remédiation, rendues indépendantes de leur ancien contexte.
  Les 52 activités de transfert conservées apportent deux situations chacune.
  Les 290 énoncés sont distincts ; la correction intervient après le choix.
- 62 questions d'application sont rédigées dans `challenges.py` pour vérifier
  le raisonnement dans un contexte différent. Les associations de vocabulaire,
  études de documents, main courante, exemples corrigés et examens blancs
  restent disponibles. Les positions des bonnes réponses sont réparties.

`python -m scripts.aps62_v15.build` régénère `editorial_v15.json` à partir des
archives v12 et des questions relues. `aps_editorial.refine_course` applique
cette présentation aux 180 éditions affectables (15 modules × 12 éditions).
Il ne réécrit pas les archives ni les affectations.

## Continuité des parcours

Les identifiants d'activités, l'ordre, les durées prévues et les vidéos requises
sont conservés. Aucune migration du suivi et aucun crédit artificiel de temps.
Une question déjà validée affiche l'énoncé original correspondant à la réponse
enregistrée ; une nouvelle réponse reçoit la révision de contenu. Les anciens
onglets peuvent terminer leur suivi de présence mais doivent être rechargés
avant de répondre ou de valider une activité. Les nouvelles clés d'exercices
et de cache empêchent la réutilisation de choix provenant des anciens ateliers.

## Vérifications

Commande ciblée :

```sh
python -m pytest -q tests/test_aps62_editorial_v15.py tests/test_aps62_without_productions.py
```

Résultat : 10 tests réussis et 180 sous-tests réussis. Couverture : rendu des
62 cours, banque complète et corrections, confidentialité des réponses,
rejet des anciennes clés et des anciens onglets, conservation des réponses,
scores, temps et règles vidéo, présentation historique des 180 éditions.

La suite générale `test_native_elearning_web.py` a également été tentée :
9 tests réussissent ; les vérifications du catalogue global sont bloquées
dans le checkout allégé par l'absence des médias VTC requis. Les fichiers VTC
et la logique correspondante ne sont pas modifiés dans cette révision.

Le contrôle visuel s'effectue dans l'aperçu administrateur du site de test,
sans ouvrir ni valider les activités d'un véritable stagiaire.

Repères officiels consultés pour les nouveaux cas :

- [Article 73 du CPP](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000029000766)
- [CNAPS — Exercer le métier d'agent de sécurité privée](https://www.cnaps.interieur.gouv.fr/Demarches-en-ligne/Vous-etes-un-particulier/Exercer-le-metier-d-agent-de-securite-privee/Exercer-le-metier-d-agent-de-securite-privee)
- [INRS — Accidents d'origine électrique](https://www.inrs.fr/risques/electriques/accidents-origine-electrique)
- [INRS — Zonage et matériel ATEX](https://www.inrs.fr/risques/explosion/zonage-marquage-materiel-atex)
