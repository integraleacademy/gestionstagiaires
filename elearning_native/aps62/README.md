# Parcours APS illustré — édition 20261003-aps62-v1

15 modules, 62 dossiers de 60 minutes de travail guidé, 434 activités, 124 productions écrites et 124 questions évaluées. 62 capsules avec narration française, sous-titres et transcription (73,9 minutes de vidéo au total). Les 62 heures sont une durée pédagogique prévue, à éprouver avec les apprenants ; ce ne sont pas 62 heures de vidéo ou une mesure acquise de présence.

Le contenu du manuel fourni par Intégrale Academy est complété par des scénarios fictifs, ateliers de décision, tableaux, schémas, cartes de mémorisation et variantes. Les notions sont réinvesties dans plusieurs contextes. L'import existant et les parcours déjà affectés ne sont pas modifiés. Un bouton du compositeur permet d'ajouter les 15 modules, puis d'adapter et enregistrer explicitement la composition.

## Périmètre pédagogique

Le découpage se fonde sur les séquences à distance des annexes II et III de l'arrêté du 1er septembre 2025. L'ADEF identifie 50 h 30 de séquences dans un plafond de 51 h pour le TFP APS de branche. Le parcours complet ne constitue donc pas une autorisation de déclarer 62 h de distanciel pour ce TFP. Les sources sont accessibles dans le catalogue et les synthèses. Une validation pédagogique humaine et un pilote apprenant restent nécessaires avant utilisation certificative.

Les travaux écrits sont enregistrés dans le suivi existant et consultables depuis « Travaux écrits » dans le suivi du module. Ils n'obtiennent pas de note automatique. Les réponses et médias restent liés à la session et au cours autorisés ; le calcul du temps actif et le contrôle des vidéos restent côté serveur.

## Construction et maintenance

- Préparation initiale : `python scripts/build_aps62.py MANUEL_APS.pdf --assets-only`, puis rendu des vidéos, puis construction complète.
- `scripts/aps62_editorial.py` : 62 dossiers éditoriaux, durées et modules.
- `scripts/render_aps62_videos.py MODEL.onnx` : export des capsules avec Piper, Pillow et ffmpeg ; modèle et outils requis uniquement à la construction.
- `scripts/build_aps62.py MANUEL_APS.pdf` : extraction des fiches et génération des cours, avec PyMuPDF et Pillow.
- `manifest.json` conserve l'empreinte du PDF source, les volumes et la version.

Les JSON et médias sont livrés avec l'application ; aucun téléchargement tiers n'est nécessaire pendant la formation. Préserver les versions déjà affectées lors d'une future édition. Ne jamais écraser une version utilisée par des stagiaires.

## Crédits

Textes et illustrations du manuel APS fourni par Intégrale Academy, édition septembre 2026. Charte inspirée des manuels APS et SSIAP fournis pour ce projet.

Narration par voix de synthèse Piper, modèle `fr_FR-siwis-medium` : jeu de données « The SIWIS French Speech Synthesis Database », Junichi Yamagishi, Pierre-Edouard Honnet, Philip Garner, Alexandros Lazaridis (2017), licence Creative Commons Attribution 4.0. Source : https://datashare.ed.ac.uk/handle/10283/2353. Modèle : https://huggingface.co/rhasspy/piper-voices/tree/main/fr/fr_FR/siwis/medium. Audio généré pour ces scénarios, puis monté et synchronisé en capsules ; il ne s'agit pas d'un enregistrement de la personne source lisant les cours.
