# Essai EDOF direct sur Test V2

Page : `/admin/edof-test`, administrateur interne uniquement, hors assistance partenaire.
Activation exclusivement sur le service Render `srv-d928tc19rddc7388qie0` via
`RENDER_SERVICE_ID` (jamais via le Host de la requête). Aucun changement de `main`,
des variables de production ou du Blueprint. Intégration par `crm_app.py`.

## Premier test réel

1. Ouvrir la page avec une session administrateur de Test V2.
2. Télécharger et décompresser le module Chrome. Le charger dans
   `chrome://extensions` avec « Charger l’extension non empaquetée ».
3. Préparer le numéro du dossier CPF à lire. Copier le code d’essai.
4. Se connecter normalement à EDOF, ouvrir le dossier et l’onglet DevTools
   « Intégrale EDOF ». Coller le code, préparer la lecture, recharger la fiche.
5. Contrôler le dossier détecté, puis déclencher le transfert volontaire.
6. Actualiser le résultat dans Test V2. La page cherche d’abord un lien CPF
   existant, puis propose les inscriptions dont l’identité complète ou l’e-mail
   concorde. Les critères et les écarts restent visibles ; aucun lien n’est créé.
7. Refaire avec un nouveau code après déconnexion/reconnexion EFP Connect.
   Cela vérifie la nouvelle session du navigateur, pas une reconnexion serveur.

## Périmètre et isolation

- Observation de la réponse GET exacte du dossier choisi via l’API DevTools
  `onRequestFinished` / `getContent`. Aucun appel à EDOF, pas de replay, de
  `getHAR`, d’accès aux cookies ou aux en-têtes d’authentification.
- Un clic de transmission vers la seule origine Test V2 ; pas de domaine configurable.
- Liste blanche côté extension ET serveur. Pas de dossier brut, adresse,
  téléphone, naissance, historique, sollicitation de financement ou TVA ambiguë.
- Le code comporte 256 bits aléatoires, expire en 15 min, est associé au dossier,
  à la session d’administration et à un seul transfert. Seul son hash est stocké.
- Stockage propre à Test V2 : `/var/data/edof_readonly_test.sqlite3`, permissions
  0600. Un résultat par session. Résultat inaccessible après 24 h ; suppression
  des lignes expirées au prochain accès au stockage. Effacement explicite disponible.
- Lecture directe de `DATA_FILE` pour comparer les liens CPF existants et les inscriptions,
  sans appeler `load_data`, `save_data`, un webhook ni les context processors
  historiques. Aucun ajout à `wedof_folder_cache` ou aux tables d’automatisation.
- Les valeurs nulles financières restent inconnues. Le montant TTC ne signifie
  pas paiement. Les données reçues restent une observation du navigateur,
  sans garantie cryptographique de provenance ; aucune décision métier automatique.

## Recherche locale (version 1.1)

`edof_matching.py` est une fonction pure : aucune dépendance client WEDOF,
aucune requête externe, aucune écriture ni ouverture de fiche métier.

- Priorité au numéro CPF déjà lié. Les liens multiples ou périmés sont signalés
  et ne sont jamais remplacés par une suggestion basée sur l’identité.
- Sans lien existant, recherche par nom ET prénom normalisés, ou par e-mail exact
  après suppression des espaces périphériques et mise en minuscules.
- Une proposition concordante nécessite une inscription unique, nom et prénom,
  e-mail et deux dates identiques, session non archivée et absence d’autre lien CPF.
  La formation reste à vérifier : l’intitulé n’est pas une clé fiable entre systèmes.
- Un nom seul, un e-mail partagé, une différence de dates ou un doublon appelle
  une vérification explicite ; aucune association automatique n’est effectuée.
- Dates de session prioritaires ; repli sur les deux dates du dossier uniquement
  lorsque les dates de session sont incomplètes, sans mélanger leurs bornes.
- Affichage limité à six fiches et six sessions, avec comptes complets. Données
  de test absentes ou indisponibles distinguées d’un transfert EDOF en échec.
- La mise à jour conserve le résultat reçu pendant sa durée de validité et ne
  nécessite aucune nouvelle version du module Chrome.

## Validation

`python -m pytest -q tests/test_edof_readonly_test.py tests/test_edof_matching.py`

`node --test tests/test_edof_extension.cjs`

Après déploiement, `/healthz` doit répondre et `/api/edof-test/ping` doit annoncer
`version: 1.1`, `matching_preview: true`, `mode: browser_observation`, `autonomous_sync: false`.
La page et le ZIP exigent une session administrateur. Aucun secret dans les URL.

Cette version ne réalise ni synchronisation autonome, ni parcours paginé de tous
les dossiers, ni écriture EDOF. L’authentification serveur et son renouvellement
restent à établir séparément avant de remplacer une intégration WEDOF existante.
