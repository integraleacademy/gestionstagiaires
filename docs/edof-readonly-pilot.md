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
6. Actualiser le résultat dans Test V2 et comparer la fiche locale si un lien
   CPF exact existe déjà. Effacer ensuite l’essai.
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
- Lecture directe de `DATA_FILE` pour comparer les seuls liens CPF existants,
  sans appeler `load_data`, `save_data`, un webhook ni les context processors
  historiques. Aucun ajout à `wedof_folder_cache` ou aux tables d’automatisation.
- Les valeurs nulles financières restent inconnues. Le montant TTC ne signifie
  pas paiement. Les données reçues restent une observation du navigateur,
  sans garantie cryptographique de provenance ; aucune décision métier automatique.

## Validation

`python -m pytest -q tests/test_edof_readonly_test.py`

`node --test tests/test_edof_extension.cjs`

Après déploiement, `/healthz` doit répondre et `/api/edof-test/ping` doit annoncer
`version: 1.0`, `mode: browser_observation`, `autonomous_sync: false`.
La page et le ZIP exigent une session administrateur. Aucun secret dans les URL.

Cette version ne réalise ni synchronisation autonome, ni parcours paginé de tous
les dossiers, ni écriture EDOF. L’authentification serveur et son renouvellement
restent à établir séparément avant de remplacer une intégration WEDOF existante.
