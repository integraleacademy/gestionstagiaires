# Diaporamas de lancement DESP

Les modèles `paris.pdf` et `puget.pdf` proviennent des deux PowerPoints de 24 diapositives révisés le 24 octobre 2026 avec un calendrier visuel. Les fichiers JSON repèrent les 13 zones de texte dynamiques de chaque modèle. Le calendrier de la diapositive 5 est entièrement recalculé par `desp_calendar.py`, avec des cases bleues pour le distanciel, vertes pour le présentiel et dorées pour l’examen. Les couleurs indiquent des périodes, pas un planning quotidien de présence. Le programme, les illustrations, les coordonnées et les dates d’enregistrement RNCP restent ceux des documents fournis.

`desp_kickoff.py` choisit le modèle avec la même règle que les conventions et convocations DESP. Les formations VAE, MAC, les autres formations et les sessions partenaires sont exclues. Les polices Rubik et leur licence sont partagées avec `aps_kickoff_assets`.

## Utilisation

- Renseigner les dates de début et fin du distanciel, du présentiel, et de l’examen dans « Modifier la session ».
- « Prévisualiser le diaporama DESP » permet de vérifier le PDF depuis la liste des sessions ou des stagiaires, avant le démarrage.
- Le PDF apparaît automatiquement dans l’espace stagiaire à partir du début du distanciel, à minuit en heure de Paris. Il reste accessible après la formation. Une inscription annulée ne donne pas accès au PDF.
- Toute modification des dates de la session se retrouve dans le PDF à la prochaine consultation. Aucun dépôt manuel ni tâche planifiée n’est nécessaire.
- Le contenu pédagogique n’est pas modifiable depuis l’administration : fournir un PowerPoint révisé pour mettre à jour le modèle concerné.

## Mise à jour du contenu

Exporter les PowerPoints vers PDF avec LibreOffice, puis exécuter `prepare_templates.py SOURCE_PPTX_DIRECTORY EXPORTED_PDF_DIRECTORY`. Adapter les noms de fichiers et le repérage des zones si la structure des diapositives a changé. `desp_calendar.layout` fournit les objets éditables des PowerPoints et `draw_pdf` reprend exactement cette géométrie pour les PDF en ligne. Ne pas effacer les dates fixes du RNCP. Augmenter `VERSION` dans `desp_kickoff.py`, vérifier visuellement les deux modèles et une session d’une autre année, puis exécuter `python -m pytest -q tests/test_aps_kickoff_pdf.py tests/test_desp_kickoff_pdf.py` avant déploiement.

Le PDF ne contient aucune donnée personnelle de stagiaire. Les routes réutilisent l’authentification existante et interdisent les téléchargements directs avant la date d’ouverture.
