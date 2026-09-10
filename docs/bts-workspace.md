# Espace BTS — gestion des dossiers d’apprentissage

## Connexion AKTO via WEDOF (10 septembre 2026)

La connexion principale réutilise `WEDOF_API_KEY`. Aucun identifiant OAuth AKTO
supplémentaire ni nouveau service Render n’est nécessaire. Le connecteur direct
AKTO reste disponible dans les paramètres avancés.

- `GET /api/workingContracts?financer=opcoCfaAkto&state=all&limit=100&page=…`
  récupère le catalogue paginé ; seuls les contrats portant ce financeur sont acceptés.
- Le dossier lié `/api/registrationFolders/{externalId}` complète l’identité de
  l’apprenti et la formation. Son identifiant et sa nature OPCO sont contrôlés.
- « Mettre à jour le dossier » relit un contrat puis tente la lecture bêta
  `/api/workingContracts/{id}/raw`. Seules les données CFA Dock dont l’identité est
  vérifiée sont exploitées. Les échéances ne sont affichées que si elles existent
  dans ce retour ; les montants absents restent inconnus. Les factures et paiements
  WEDOF génériques ne sont pas assimilés aux factures et règlements AKTO.

La synchronisation est lancée explicitement et continue tant que la page reste
ouverte. Chaque POST traite une page de catalogue ou au plus trois fiches liées.
Le curseur est enregistré dans la base BTS et chaque étape porte une révision.
Après interruption ou plafond atteint, « Poursuivre » reprend le travail conservé.
Une série est limitée à 80 tentatives avant reprise explicite ; tous les appels
respectent aussi le compteur partagé WEDOF, sans dérogation ni retry HTTP.
Les GET de navigation n’effectuent aucun appel WEDOF et aucun cron n’est ajouté.

`bts_wedof_contracts` conserve le cache par ID WEDOF (`w-…`) de manière additive.
La réimportation ne modifie jamais les notes, frais, brouillons ou dossiers locaux.
Deux contrats du même apprenti restent distincts ; aucune fusion par nom n’est
faite. Un contrat absent d’une liste complète est signalé et conservé. Une erreur
de pagination ne supprime aucun contrat. Les informations importées sont en
lecture seule et limitées aux champs utiles ; le payload brut, le NIR et les
coordonnées bancaires ne sont pas conservés.

Les événements explicitement liés à l’apprentissage ne passent plus par les
relais commerciaux CPF vers le CRM/Salesforce. Ils ne déclenchent pas de mise à
jour BTS automatique dans ce lot. Les protections de connexion, droits d’écriture,
super-administration, CSRF, verrou interprocessus et non-cache sont réutilisées.

Le bouton de test vérifie réellement l’accès à la liste AKTO. La présence de la
clé ne suffit pas à annoncer une connexion validée. Une liste vide peut indiquer
que les contrats ne sont pas encore synchronisés chez WEDOF ou pas accessibles à
cette clé ; le logiciel l’indique sans fabriquer de dossiers.

Sources vérifiées : [API WEDOF](https://www.wedof.fr/api/doc/),
[connexion OPCO CFA](https://doc.wedof.fr/article/21-connexion-opco-cfa).
Tests : `python -m unittest tests.test_wedof_bts tests.test_bts_workspace tests.test_akto_bts tests.test_wedof_isolation`.

## Accès et périmètre

Le point d’entrée de production `crm_app:app` enregistre `register_bts_workspace(legacy_app)`. L’URL reste `/admin/BTS` et `/admin/bts` redirige vers cette URL. Le lien de navigation historique ne change pas.

L’interface reprend la structure demandée : navigation dédiée, liste de dossiers, fiche par apprenti, onglets Suivi dossier / Étudiant / Contrat / Entreprise / Gestion / Comptabilité et comptabilité en deux colonnes (références et répartition des échéances à gauche, échéancier et frais à droite). Aucun logo Filiz et aucune donnée de démonstration ne sont ajoutés en production.

### Disponible sans raccordement AKTO

- Création de dossiers locaux ; modification des données étudiant, entreprise, maître d’apprentissage, formation et contrat.
- Contrôles de format et de cohérence : champs obligatoires, e-mails, longueur du SIRET, dates, heures et montants.
- Notes, checklist de préparation déclarative et historique interne.
- Frais annexes saisis localement avec montants en centimes entiers.
- Brouillons de factures entreprise, export JSON et suppression explicite de ces brouillons.
- Recherche, filtres, pagination et export des données de l’espace.

### Disponible sur le cache des dossiers AKTO

- Consultation des données remontées par le connecteur existant, sans modification de leur source.
- Échéancier, répartition des montants payés/en instruction/à facturer/à venir/à vérifier.
- Préparation d’un brouillon OPCO pour une échéance ouverte et exploitable. Le montant est calculé côté serveur et les doublons de brouillons par échéance sont bloqués.
- Présentation séparée des factures déjà connues d’AKTO, avec leur date de synchronisation.

### Lecture directe AKTO sur action explicite

- Test de connexion : authentification OAuth, puis lecture de la première page `/v2/dossiers/etats`. Paramètres renseignés et connexion vérifiée sont deux états différents. Le résultat est invalidé si la configuration change.
- Actualisation ciblée : lecture du dossier `/v2/dossiers?numeroInterne=…`, vérification de son identité et mise à jour de ses données/échéances seulement. Les factures gardent leur propre date de vérification.
- La synchronisation complète existante reste disponible et conserve son verrou interprocessus.

## Limites à ne pas confondre avec des fonctionnalités actives

Ce lot n’émet pas de contrat ni de facture et ne transmet aucun document à un OPCO. Les CERFA PDF, conventions, signatures électroniques, certificats de réalisation, factures définitives, envois et retours d’instruction restent des lots distincts à développer/valider. La checklist interne ne prouve pas la présence d’une signature ou la conformité réglementaire d’un dossier.

Les frais locaux ne sont pas des montants acceptés par AKTO. Les brouillons ne font pas évoluer artificiellement les montants facturés, les règlements ou les états du financeur. Le reste à charge entreprise n’est pas calculé automatiquement.

La récupération effective des vrais dossiers nécessite les adresses et identifiants techniques AKTO. Le test n’infère pas la validité de la connexion à partir de la seule présence des variables.

## Stockage et sécurité

Les nouvelles tables `bts_local_dossiers`, `bts_annotations`, `bts_fees`, `bts_invoice_drafts`, `bts_events` et `bts_diagnostics` sont créées de manière additive dans la base BTS dédiée. Aucun accès à `data.json` n’est nécessaire pour rendre les pages BTS. Le remplacement du cache AKTO ne supprime pas ces tables locales.

Les routes reprennent les contrôles de connexion, de super-administration et de droit d’écriture du projet. Les partenaires sont exclus. Les nouveaux formulaires POST ont un jeton CSRF propre à la session. Les modifications simultanées sont protégées par un numéro de révision. Les exports sont confidentiels et non mis en cache. Les clés et secrets restent dans Render, ne figurent ni dans les pages ni dans les diagnostics enregistrés.

Les montants d’échéances incomplets, négatifs ou incohérents et les identifiants d’échéance ambigus ne donnent pas lieu à un brouillon automatiquement préparé. Une mise à jour de l’échéancier peut rendre un ancien brouillon à revalider.

## Validation reproductible

Le workflow `Espace BTS` exécute les tests unitaires de l’espace, les tests du connecteur existant, un contrôle de l’entrée réelle `crm_app` et des parcours Chromium sur une application temporaire avec données fictives.

Commandes :

```sh
python -m unittest tests.test_bts_workspace -v
python -m unittest tests.test_akto_bts -v
python scripts/check_bts_workspace_ui.py --browser
```

Le script de navigateur vérifie les dialogues, la création d’un dossier, les frais, les brouillons, l’absence d’erreurs JavaScript et le débordement horizontal aux largeurs 1440, 1024, 768 et 390 pixels. Le faux accès de test n’est enregistré que dans l’application Flask temporaire du script et n’existe pas en production.

## Déploiement et retour arrière

La fusion sur `main` déclenche le déploiement automatique Render déjà configuré. Aucun nouveau service ni nouvelle variable obligatoire n’est ajouté. Contrôler le statut du déploiement, `/healthz` et les journaux avant d’annoncer la mise en ligne.

Pour revenir à l’écran précédent, retirer l’import et l’appel `register_bts_workspace` dans `crm_app.py`, puis redéployer le code. Ne pas supprimer les tables `bts_*` : elles contiennent le travail local et doivent être conservées/exportées. Une sauvegarde/restauration doit utiliser les mécanismes SQLite appropriés et tenir compte du journal WAL.
