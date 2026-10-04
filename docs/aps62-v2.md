# APS illustré — édition du 4 octobre 2026

La version `20261004-aps62-v2` complète le parcours guidé de 62 h :

- 15 modules, 62 dossiers et 434 activités, dont 124 productions écrites et 124 questions de cours.
- 15 illustrations de scènes professionnelles, 15 synthèses visuelles, 15 études de cas complémentaires et 62 jeux de classement.
- 62 capsules avec la voix de référence `fr-FR-HenriNeural`, débit `-2%`, hauteur `+0Hz`, volume `+0%`. Sous-titres français incrustés, piste WebVTT synchronisée et transcription.
- 30 questions d’examen blanc par module (450 questions distinctes), plus une synthèse finale de 100 questions sélectionnées dans les 15 banques, à raison de 6 ou 7 par module.
- Score calculé côté serveur, correction expliquée, sources de référence, pistes de révision, impression de la correction et nouvelles tentatives.

L’objectif de 75 % est un repère d’entraînement, pas le barème d’un examen officiel. Les examens blancs sont un entraînement complémentaire ; ils ne créditent pas artificiellement du temps dans les 62 h. Les limites réglementaires du distanciel restent explicitées dans le catalogue.

## Accès et conservation

L’administrateur peut prévisualiser les cours et les 16 examens depuis le catalogue sans créer de résultat stagiaire. Les stagiaires accèdent aux examens de leurs modules affectés et déverrouillés. L’examen final demande les 15 modules complets de la même édition, leurs activités et leurs durées affectées terminées. Une sélection partielle de séquences ne suffit pas.

Les tentatives sont conservées dans une nouvelle table additive `aps_exam_attempts` du fichier existant `native_elearning/tracking.sqlite3`. Elles sont isolées par session, stagiaire, examen, édition et identifiant de tentative. Un nouvel envoi après une erreur réseau est idempotent ; une nouvelle tentative a son propre identifiant. Les réponses du cours, les vidéos déjà suivies et les temps actifs restent indépendants.

La v1, ses JSON et ses médias restent présents. Les parcours affectés sont liés à leur version ; ouvrir le catalogue ne réaffecte aucun stagiaire. La nouvelle édition est proposée dans le compositeur de parcours.

## Reproduction

Les textes sont dans `scripts/aps62_editorial.py`, `scripts/aps62_visuals.py` et `scripts/aps62_exam_questions*.txt`. Les illustrations fournies servent aux capsules et aux pages.

```sh
APS62_IMAGES=/chemin/illustrations APS62_WORK=/chemin/cache python scripts/render_aps62_henri.py
python scripts/build_aps62_v2.py
python -m pytest tests/test_native_elearning*.py -q
NODE_PATH=/chemin/node_modules node --test tests/test_native_elearning_*ui.cjs
```

La génération nécessite Pillow, edge-tts et ffmpeg ; ces dépendances ne sont pas ajoutées à l’application en production. Le cache vocal contient seulement les textes pédagogiques fictifs. Les fichiers publiés sont versionnés dans le dépôt. Le rendu vérifie la durée des scènes et de l’assemblage avant remplacement du fichier final.

Les tests couvrent les corrections, les réponses incomplètes, le CSRF, les accès non autorisés, les nouvelles tentatives, les reprises réseau, l’isolation des résultats, l’absence d’effet sur la progression, le verrouillage du final et la conservation de la v1. Le rendu de toutes les activités et les règles de suivi vidéo restent également vérifiés.
