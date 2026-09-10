# Espace BTS — gestion des dossiers d’apprentissage

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
