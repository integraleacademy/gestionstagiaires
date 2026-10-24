# Diaporama de lancement APS

Le modèle conserve les 41 diapositives du PowerPoint validé en octobre 2026,
avec les 14 UV et la formulation « au centre de formation ».

`template.pdf` contient les pages fixes. Les dates de la session initiale ont
été supprimées du texte du PDF. `layout.json` décrit les zones dans lesquelles
`aps_kickoff.py` insère les dates courantes. Le calendrier est recalculé, y
compris pour les changements de mois et d’année. Les polices Rubik sont
distribuées sous la licence SIL Open Font License jointe.

Les routes publiques vérifient l’authentification du stagiaire, sa session,
son inscription et la date de début du e-learning en Europe/Paris. Le fichier
reste accessible après la fin de la formation. Il n’est pas placé dans le
dossier `static` et aucun jeton public de téléchargement n’est créé.

La prévisualisation est disponible dans l’administration sur chaque session
APS initiale Intégrale Academy. Les parcours AFC et MAC APS, et les sessions
des centres partenaires, ont des modalités différentes et ne reçoivent pas
ce document. Si les périodes ou la date d’examen manquent ou se chevauchent,
la prévisualisation demande de corriger la session au lieu d’inventer des dates.

Une modification des dates produit automatiquement un nouveau PDF. Le cache
mémoire est limité à huit documents par processus et ne contient aucune donnée
nominative. Aucune écriture de dossier stagiaire, tâche planifiée ou modification
de la base de données n’est nécessaire.

Validation : `python -m pytest tests/test_aps_kickoff_pdf.py`.
