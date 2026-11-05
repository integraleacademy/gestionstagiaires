INTÉGRALE EDOF — LECTURE DE DOSSIER

1. Décompresser le ZIP. Ouvrir chrome://extensions, activer Mode développeur,
   puis Charger l’extension non empaquetée. Choisir ce dossier (manifest.json).
2. Sur https://gestionstagiaires-r5no.onrender.com/admin/edof-test,
   créer un code pour le numéro du dossier CPF choisi. Le code expire en 15 min.
3. Dans EDOF, ouvrir ce dossier. Ouvrir les outils de développement (Option +
   Commande + I), puis l’onglet Intégrale EDOF (éventuellement dans »).
   Si l’onglet manque, fermer puis rouvrir les outils de développement.
4. Coller le code, cliquer Préparer la lecture, puis recharger la fiche EDOF.
5. Vérifier le dossier détecté et cliquer Transmettre à Gestion Stagiaires.
6. Dans Gestion Stagiaires, cliquer Afficher le résultat. Effacer l’essai après contrôle.

Ce module observe uniquement la réponse GET du dossier préparé, après une
connexion normale. Il ne demande, ne lit et ne transmet aucun cookie ou
en-tête d’authentification. Aucun appel n’est émis vers EDOF.
Le transfert vers Gestion Stagiaires est déclenché par votre clic et limité aux champs
autorisés (identité, e-mail, formation/session, dates, statut et montants).
Les données brutes, adresses, téléphones, dates de naissance et historique
ne sont ni transmis ni conservés. Aucune fiche métier n’est modifiée.

La connexion automatique depuis un serveur et son renouvellement ne sont
pas réalisés par cette première version. Aucune donnée nominative de
démonstration ni aucun identifiant de connexion n’est inclus dans les fichiers.
