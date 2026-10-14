# APS : dossiers approfondis et calibrage des durées

Révision de diffusion : `20261014-aps-dossiers-v16`.

Le constat de départ est un parcours dont les activités peuvent être terminées bien avant le temps obligatoire. Cette révision ajoute du travail d’analyse et mesure la première fin des activités, sans attribuer des heures à partir d’une estimation.

## Contenu et budgets

Les 62 séquences reçoivent chacune un apport de cours et un dossier de trois pièces fictives. Les 310 nouveaux exercices représentent 868 choix ou associations élémentaires : qualification des informations, comparaison de documents, ordre des actions, décision et réévaluation. Les trois situations de transfert v15 restent à la suite de chaque dossier. Les réponses libres longues ne sont pas réintroduites.

Les vidéos, les questions notées, les identifiants d’activités, les versions d’affectation et leurs durées obligatoires restent conservés. Les ateliers non terminés utilisent la nouvelle banque. Un atelier déjà réussi reste acquis et peut être retravaillé librement ; son historique n’est ni effacé ni requalifié comme ayant réalisé les nouvelles questions.

| Module | Activités prévues | Examen et correction | Total du module |
|---|---:|---:|---:|
| APS 01 | 205 min | 35 min | 240 min |
| APS 02 | 150 min | 30 min | 180 min |
| APS 03 | 95 min | 25 min | 120 min |
| APS 04 | 40 min | 20 min | 60 min |
| APS 05 | 150 min | 30 min | 180 min |
| APS 06 | 205 min | 35 min | 240 min |
| APS 07 | 265 min | 35 min | 300 min |
| APS 08 | 265 min | 35 min | 300 min |
| APS 09 | 150 min | 30 min | 180 min |
| APS 10 | 380 min | 40 min | 420 min |
| APS 11 | 95 min | 25 min | 120 min |
| APS 12 | 380 min | 40 min | 420 min |
| APS 13 | 95 min | 25 min | 120 min |
| APS 14 | 380 min | 40 min | 420 min |
| APS 15 | 380 min | 40 min | 420 min |

Total : 3 720 minutes. Le temps réel de l’examen final reste additionnel au total des modules. Les budgets sont des repères pédagogiques à valider avec des apprenants, pas la preuve que chaque personne passera exactement cette durée dans chaque activité.

Les vidéos disposent au minimum de leur durée réelle arrondie à la minute. Le reste du budget est réparti entre lecture, dossier, vérification, transfert et synthèse. Aucun ralentissement vidéo ni attente obligatoire par page n’est ajouté. Le bouton en fin de module conduit à l’examen avant la condition de durée nécessaire au module suivant.

## Mesure et conservation

La ventilation `activity_seconds_json` reçoit désormais les secondes réellement créditées des modules APS et des examens. La navigation crédite le reliquat à l’activité quittée, dans la même transaction que le compteur global. Le délai de dix minutes et les protections contre le double comptage restent appliqués.

Une colonne additive `aps_workload_json` conserve un instantané à la première fin des activités sous cette révision. Les anciennes lignes reçoivent seulement une valeur vide par défaut ; aucun temps, résultat ou instant de fin n’est reconstruit. Les révisions ultérieures ne modifient pas l’instantané.

Le rapport `/admin/elearning/calibrage` et son CSV réutilisent le périmètre d’identités et d’affectations du suivi administratif. Une médiane n’intègre une observation que si tous les dossiers sont de cette révision, si la ventilation couvre le temps enregistré et si la durée affectée correspond au module. Les parcours historiques ou mixtes restent visibles avec leur motif d’exclusion et leur temps non ventilé.

Le point de mesure des activités exclut les secondes d’examen déjà ventilées. Le temps cumulé et le temps d’examen continuent d’être affichés séparément. Trois observations constituent seulement un seuil de début d’interprétation ; un temps inférieur à 80 % du repère attire l’attention du formateur. Ces seuils ne constituent pas une règle réglementaire ni une validation automatique de la charge.

## Sources examinées

Les situations et pièces sont originales et fictives. Elles complètent les références déjà présentes dans les cours. Les points sensibles ont été rapprochés de sources officielles consultées le 14 octobre 2026 :

- [Arrêté du 1er septembre 2025, annexes II et III](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000052197461/).
- [Livre VI du code de la sécurité intérieure](https://www.legifrance.gouv.fr/codes/id/LEGISCTA000029191767), notamment conditions d’exercice, exclusivité, contrôle des bagages et distinction avec la puissance publique.
- [Article L613-2, version consultée](https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000053710911/2026-04-16).
- [Article 73 du code de procédure pénale](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000029000766/2026-01-03).
- [Article 122-5 du code pénal](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006417218/2022-01-26).
- [CNIL : habilitations](https://www.cnil.fr/fr/securite-gerer-les-habilitations), [accès aux locaux](https://cnil.fr/fr/acces-locaux-controle-des-horaires-au-travail) et [vidéoprotection](https://www.cnil.fr/fr/la-videoprotection).
- [INRS : prévention électrique](https://www.inrs.fr/risques/electriques/prevention-risque-electrique), [accidents électriques](https://www.inrs.fr/risques/electriques/accidents-origine-electrique), [risque chimique](https://www.inrs.fr/risques/chimiques/evaluation-risques) et [explosion](https://www.inrs.fr/risques/explosion/demarche-prevention-risques.html).
- [SGDSN : Vigipirate](https://www.sgdsn.gouv.fr/vigipirate/le-plan-vigipirate-faire-face-ensemble) et [affiches de réaction](https://www.sgdsn.gouv.fr/vigipirate/les-affiches-de-sensibilisation). Les nouveaux dossiers demandent les consignes actualisées du site et ne figent pas les niveaux du dispositif.

## Validation pédagogique restante

Faire un essai réel d’APS 01 avec des profils représentatifs, puis comparer les autres modules. Examiner la première fin des activités, le temps d’examen et les difficultés déclarées. Enrichir les séquences sous-chargées par des travaux adaptés ; ne pas demander une présence inactive pour compléter le compteur. Les tests logiciels ne remplacent pas ce calibrage humain ni l’observation des compétences pratiques.

## Vérifications techniques

Le 14 octobre 2026 : 110 tests Python et 49 sous-tests réussis, plus 10 tests d’interface JavaScript. La vérification couvre les 62 dossiers, la correction serveur, les budgets des 15 modules, la conservation des anciens résultats, le passage vers l’examen avant la durée minimale, les examens blancs et final, le délai d’inactivité, la navigation et le cloisonnement du rapport administratif.

Trois tests existants sont exclus de cette exécution locale : deux nécessitent les vidéos binaires non téléchargées dans la copie de travail partielle ; le troisième concerne des sous-titres VTC et échoue aussi avec le modèle d’origine, indépendamment de cette révision APS. Aucun fichier vidéo ni comportement VTC n’est modifié.
