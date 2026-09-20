# E-learning APS natif

Ce module remplace progressivement Easygenerator pour la diffusion des cours et Digiforma pour le suivi de l’activité e-learning. Les anciens liens restent disponibles tant qu’aucun cours natif n’est affecté à une session.

## Parcours administrateur

1. Ouvrir **Administration → E-learning APS**.
2. Importer un export **SCORM manuel** Easygenerator au format ZIP.
3. Contrôler le nombre de séquences, d’activités et de questions détectées.
   Le bouton **Visualiser le contenu** ouvre le lecteur en **Mode aperçu** :
   toutes les séquences sont accessibles, les médias et interactions sont
   consultables, et les administrateurs peuvent tester plusieurs réponses.
   Aucun temps, score ni résultat stagiaire n’est enregistré. Cet aperçu ne
   nécessite aucune affectation à une session et conserve la version du module
   lors de la navigation. Les comptes en lecture seule peuvent consulter le contenu.
4. Dans **Parcours des sessions APS**, cliquer sur **Composer le parcours**.
   Ajouter les modules importés (jusqu’à 100), les ordonner avec les flèches,
   déplier chaque module pour choisir et ordonner ses séquences, puis enregistrer.
5. Vérifier que l’option e-learning de la session est activée.
6. Ouvrir **Suivi en direct** pour consulter les connexions, la progression, le score et le temps actif, ou exporter ces données en CSV.

Les gros ZIP sont envoyés par fragments de 5 Mo. L’export fourni de 112 Mo peut donc être importé sans augmenter la limite globale des pièces jointes de l’application.

## Import en ligne de commande

```bash
PERSIST_DIR=/var/data python scripts/import_easygenerator_course.py /chemin/vers/cours.zip
```

Une version de cours est immuable. Réimporter un ZIP identique est sans effet; réimporter une nouvelle version conserve les versions précédentes. Les sessions restent attachées à la version qui leur a été affectée.

## Parcours multi-modules

La hiérarchie est **session → parcours → modules importés → séquences → activités**.
Le nom du parcours et les noms de ses modules sont personnalisables. Les activités
d’une séquence restent dans leur ordre d’origine et les règles de navigation du
module sont conservées. Le passage au module suivant nécessite la validation des
activités précédentes et de leur durée obligatoire.

Le champ `aps_native_modules` de la session contient la liste ordonnée des
références (`course_id`, `course_version`, `title`, `section_ids`).
`aps_native_path_title` est le titre du parcours. Les anciennes affectations
`aps_native_course_id` / `aps_native_course_version` se lisent automatiquement
comme un parcours d’un module, sans migration ni changement de version.

Le stagiaire accède à `/espace/<token>/elearning` : tous ses modules, leurs
séquences, la progression pondérée par le nombre d’activités et le temps actif
cumulé y sont présentés. Consulter cette vue ne démarre aucun module.
Le lecteur passe au module suivant en fin de module et permet de revenir au
parcours complet. Les liens vers Digiforma restent utilisés en l’absence de
parcours natif.

Retirer un module ou une séquence ne supprime jamais les réponses, événements ou
temps enregistrés. Réaffecter la même version rétablit la progression. Les totaux
du parcours comprennent ses modules affectés ; le temps d’un module conserve
tout son historique même si certaines séquences sont retirées. Une nouvelle
version dispose d’une progression distincte. Les scores et pourcentages sont
recalculés sur les séquences actuellement choisies, y compris dans le suivi admin.

Les sauvegardes vérifient les versions, les séquences, les doublons, le rôle
administrateur, le CSRF et la révision du parcours pour détecter un formulaire
périmé. Les actions pédagogiques revérifient l’affectation. Le contrôle d’accès
des heartbeats utilise un cache borné de 60 secondes, invalidé lors d’une
sauvegarde du parcours dans le même processus ; il ne conserve pas le gros
document administratif ni les cours en mémoire. Une page déjà ouverte doit
être rechargée après modification.

## Mesure du temps

Le navigateur envoie un battement toutes les 15 secondes (4 secondes pour une
activité avec vidéo obligatoire), mais le serveur reste l’autorité de calcul.
Le temps est crédité uniquement lorsque :

- la page est visible;
- le navigateur est actif ou une vidéo est en lecture, et l’apprenant a interagi au cours des cinq dernières minutes;
- aucun autre onglet n’est déjà en train de comptabiliser du temps pour le même stagiaire dans la même session, même sur un autre module.

Chaque battement crédite au maximum 20 secondes. Une coupure réseau, un ordinateur en veille ou un onglet laissé ouvert ne peut donc pas ajouter une longue période artificielle. Les démarrages, pauses, reprises, doublons et fins de session sont journalisés.

## Vidéo Intégrale Academy obligatoire

La capsule graphique validée **Missions et limites de l’agent de sécurité**
(1 min 39 s, 4K) est placée au début de l’activité **Missions et limites de l’agent**
du module P1M1. `elearning_native/videos.py` associe explicitement le média à
l’activité `91d2d66063374f0f9ea3cb268859b3a6` du cours
`eg-3c985ae8a9fe4dd6a5842605f952cb39`, version `20260907-141439-975`.
L’enrichissement à la lecture ne modifie ni le fichier importé ni ses identifiants.
Une nouvelle version importée nécessite une association vérifiée séparément.

Le stagiaire doit regarder chaque vidéo obligatoire jusqu’à la fin avant de
terminer l’activité ou d’accéder aux suivantes, même par le sommaire ou une URL
directe. Le serveur enregistre la portion regardée sans saut et vérifie la durée
à partir des métadonnées connues, du temps réellement écoulé et d’une seule
session active. Les variations de latence disposent d’un solde de temps déjà
crédité, borné à 500 ms, qui ne se renouvelle pas à chaque requête.
Un événement `ended` isolé ou une ancienne activité terminée ne suffit pas.

La pause, la reprise après rechargement et le retour sur un passage déjà regardé
restent possibles. La vitesse reste normale jusqu’à validation. Quitter l’onglet
ou perdre la connexion met la vidéo en pause ; la reprise utilise la dernière
position confirmée. L’aperçu administrateur conserve une lecture libre sans
enregistrer de progression stagiaire.

Le MP4 et son affiche sont livrés dans `elearning_native/media/` et passent par
la route de médias authentifiée, compatible avec les requêtes HTTP Range.
Ils ne sont pas exposés dans le dossier public `static`. Le suivi persiste dans
`learner_course_progress.video_progress_json`, avec les positions temporaires
dans `tracking_sessions.video_samples_json` et un événement `video_completed`
à la validation. Les colonnes sont ajoutées automatiquement et sans effacement.

## Données persistantes

Les cours et les médias sont stockés dans :

```text
PERSIST_DIR/native_elearning/courses/<course_id>/<version>/
```

La progression et les traces de temps sont stockées dans :

```text
PERSIST_DIR/native_elearning/tracking.sqlite3
```

Ces éléments doivent être inclus dans la politique de sauvegarde du disque persistant. Le ZIP source est conservé avec chaque version importée depuis l’interface d’administration.

## Formats pris en charge

- pages de texte, tableaux et images;
- vidéo locale;
- listes, étapes, cartes à retourner et cartes classées;
- choix unique, choix multiple, affirmations, associations et texte à trous.

L’importeur n’exécute aucun JavaScript contenu dans le ZIP. Il retire scripts, gestionnaires d’événements, styles injectés et médias externes. Seuls les exports Easygenerator manuels contenant `content/data.js` sont convertibles; les petits ZIP dynamiques qui chargent le cours depuis Easygenerator sont volontairement refusés.
