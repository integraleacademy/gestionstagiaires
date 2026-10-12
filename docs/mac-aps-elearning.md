# MAC APS : parcours numérique, commandes et suivi

Édition courante : `20261012-macaps-v2`. Catalogue administrateur :
`/admin/elearning/mac-aps`. Démonstration publique : `/e-learning/demo/mac-aps`.

## Répartition des 14 heures

Cette édition est un support de préparation et de révision. Elle reprend les
dix objectifs cités à l’article 1 de l’arrêté du 27 janvier 2025 :

| Objectif | Durée |
| --- | ---: |
| Principes de la République française | 3 h |
| Actualisation du cadre juridique et de la déontologie | 4 h |
| Définir les risques et connaître les menaces terroristes | 1 h 30 |
| Connaître les niveaux de risque associés | 1 h |
| Connaître les différents matériels terroristes | 1 h |
| Développer ses réflexes de prévention et de sécurité | 1 h |
| Détecter et prévenir les menaces terroristes | 1 h |
| Entretenir sa culture de la sécurité | 30 min |
| Identifier le risque de blessures en rapport avec le danger | 30 min |
| Alerter les secours médicaux | 30 min |
| **Total principal** | **14 h** |

Trois modules regroupent ces objectifs : République (180 minutes), droit
(240 minutes), prévention du terrorisme (420 minutes). Leurs durées, leurs
séquences et l’ordre des séquences sont fixés côté serveur. Les durées prévues
des lectures, exercices, questionnaires et vidéos décomposent chaque budget
sans l’augmenter. Les questionnaires de fin d’objectif sont obligatoires.

Les compléments de premiers secours, conflits/filtrage, protection, intervention
des forces de l’ordre et préparation au secourisme tactique sont disponibles
séparément, hors des 840 minutes. Leur lecteur ne crée aucune session de suivi
et ne valide aucun geste pratique. Les vidéos de République et de droit sont
incluses dans les budgets principaux ; les trois autres synthèses vidéo restent
dans les compléments.

Les examens blancs comportent 30 questions par module et 100 questions finales,
distinctes des exercices de cours. La correction est réalisée côté serveur.
Le seuil de 80 % est pédagogique. Les examens blancs ne créditent ni temps ni
présence. Le bilan final nécessite les trois modules complets de la même édition,
toutes leurs activités, leurs vidéos obligatoires et leurs durées par objectif.

## Cadre réglementaire vérifié le 12 octobre 2026

L’article 4 de l’[arrêté du 27 février 2017](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000034104578/)
fixe le stage de référence à 34 heures : premiers secours 7 h, République 3 h,
cadre juridique 4 h, conflits/filtrage 7 h, prévention du terrorisme 13 h. La
dispense de secourisme demandée et documentée dans les conditions de cet article
ramène le stage à 27 heures. Elle ne dispense pas des objectifs de secours du
module terrorisme. Le positionnement préalable comporte dix questions à réponse
courte ; les QCM du support numérique ne s’y substituent pas.

L’[arrêté du 27 janvier 2025](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000051058748/)
ouvrait temporairement certains objectifs au distanciel **jusqu’au 31 décembre
2025 inclus**. Aucune prorogation officielle pour 2026 n’a été trouvée lors de
la vérification. L’[article 8 de l’arrêté du 23 octobre 2024](https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000050400272)
organise les objectifs déjà éligibles ; il ne crée pas une autorisation générale
de MAC APS à distance en 2026.

L’édition numérique ne revendique donc ni une autorisation actuelle de FOAD,
ni une imputation automatique de ses heures au stage, ni une attestation de
stage MAC APS, ni une certification SST. Cette portée est indiquée dans le
catalogue, la boutique, la démonstration, le lecteur et les relevés de suivi.
Les séquences pratiques, l’encadrement et le dossier du stage relèvent de
l’organisme de formation.

## Temps actif et conservation des parcours

Le serveur enregistre les secondes confirmées par activité dans
`learner_course_progress.activity_seconds_json`. Une migration SQLite additive
introduit ce champ avec `{}` comme valeur initiale. Aucun ancien compteur global
n’est réparti artificiellement entre des objectifs.

Le temps d’un intervalle appartient à l’activité ouverte pendant cet intervalle,
et non à celle demandée dans le nouveau message de suivi. La présence, les
délais d’inactivité, le visionnage et l’exclusion des onglets concurrents
continuent d’être contrôlés par le moteur natif. Le temps effectué sur un
objectif ne compense pas un autre objectif. Son questionnaire de clôture ne
peut être validé avant le minimum de temps actif. Les lectures et les activités
déjà ouvertes restent consultables pendant la révision.

`project_progress` expose les durées et l’état de chaque objectif. Le lecteur,
les prérequis, le bilan final, les rapports et les justificatifs s’appuient sur
cette projection. Un compteur local ou une durée envoyée par le navigateur
n’attribue aucune seconde.

L’édition `20261012-macaps-v1` est figée dans
`elearning_native/mac_aps/versions/20261012-macaps-v1/snapshot.json`. Ses cinq
modules, activités, vidéos, banques et identifiants restent chargeables. Ses
progressions conservent leurs clés d’édition. Aucun stagiaire déjà affecté
n’est migré silencieusement. Le composeur permet d’affecter explicitement la
nouvelle édition tout en conservant les anciennes traces, sans transfert
automatique de temps ou de résultats. Les nouvelles commandes utilisent v2.

## Tarif, paiement et accès

Le produit `mac-aps`, affiché « MAC APS », possède un tarif serveur unique de
**6 000 centimes TTC par stagiaire**. Les préférences de gratuité et les tarifs
spécifiques d’un organisme ne le modifient pas. Il n’existe pas de remise par
quantité ni de durée d’expiration commerciale ajoutée par cette édition.
Les parcours APS et VTC conservent leurs propres règles tarifaires.

Le parcours est commandable seul, pour un groupe et lors d’un ajout ultérieur
de stagiaires. La commande conserve quantité, montant et édition des modules.
Le circuit Qonto existant produit la facture et vérifie son règlement intégral
avant activation. Un retour du navigateur depuis le paiement ne constitue pas
une preuve de règlement. Une commande MAC APS gratuite ou avec un instantané
de prix incompatible ne donne pas accès au parcours.

Chaque accès activé est individuel et rattaché à l’organisme et à sa commande.
Les messages destinés au stagiaire et son espace reprennent l’identité de
l’organisme. La démonstration à 50 % utilise des données fictives, un extrait
de cours, un questionnaire, une courte vidéo et un spécimen de relevé. Elle
ne crée ni commande ni progression réelle et n’expose pas les médias complets.

## Rapports et signatures

Le suivi organisme distingue modules, édition, activités, temps actif,
objectifs, connexions et résultats de l’examen `macaps-final`. Les exports
PDF et CSV restent limités à l’organisme, à la commande et au stagiaire autorisés.
Les compléments restent hors des totaux du parcours principal.

Les justificatifs de module décrivent le suivi numérique constaté. Le circuit
de signature conserve l’instantané préparé et distingue préparation, envoi,
signature partielle, finalisation et archivage de la preuve. Une signature ne
transforme pas ce document en attestation réglementaire de stage MAC APS.
Un document d’une ancienne édition désaffectée ne peut pas être envoyé comme
s’il décrivait le parcours courant.

## Fichiers et contrôles de publication

- `elearning_native/mac_aps.py` : éditions, cours, compléments et examens.
- `elearning_native/mac_aps/v2/curriculum.json` : dix budgets et références.
- `elearning_native/mac_aps/v2/lessons.json` et `exams.json` : contenu principal et banques.
- `elearning_native/mac_aps_timing.py` : progression et clôture par objectif.
- `elearning_native/mac_aps/media_manifest.json` : durées et empreintes des vidéos originales.
- `mac_aps_demo.py` : démonstration publique isolée.
- `elearning_orders.py`, `elearning_groups.py` : prix, commande, paiement et activation.
- `elearning_reporting.py`, `elearning_native/module_signature*` : rapports et signatures.

Les tests emploient des organismes, commandes et stagiaires fictifs. Les
prestataires Qonto, messagerie et Yousign sont simulés : aucune facture, charge,
invitation à signer ou notification réelle n’est créée pour vérifier la livraison.
Les contrôles portent sur les budgets, la conservation de v1, le chronométrage,
les droits d’accès, les questionnaires, les médias, la commande à prix fixe,
le paiement intégral, les ajouts de groupe et les exports. Le catalogue,
le composeur, le lecteur, la boutique et la démo sont également vérifiés sur
ordinateur et téléphone avant publication sur `test-v2`.
