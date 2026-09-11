# Espace BTS — gestion des dossiers d’apprentissage

## Connexions OPCO via WEDOF (10 septembre 2026)

La connexion principale réutilise `WEDOF_API_KEY`. Aucun identifiant OAuth AKTO
supplémentaire ni nouveau service Render n’est nécessaire. Le connecteur direct
AKTO reste disponible dans les paramètres avancés.

Les quatre financeurs suivants sont acceptés, selon les identifiants de l’API
WEDOF. Les contrats CPF et ceux des autres OPCO sont exclus de cet import.

| OPCO | Identifiant WEDOF |
| --- | --- |
| AKTO | `opcoCfaAkto` |
| OPCO EP | `opcoCfaEp` |
| L’Opcommerce | `opcoCfaOpcommerce` |
| OPCO Mobilités | `opcoCfaMobilites` |

- `GET /api/workingContracts?financer=…&state=all&limit=100&page=…`
  récupère le catalogue paginé. Le paramètre `financer` contient les quatre
  identifiants séparés par une virgule, ou le seul OPCO choisi dans le formulaire.
  Le financeur de chaque réponse est vérifié ; celui de l’aperçu doit être conservé
  lors de l’ajout et celui du dossier existant lors d’une actualisation.
- Le dossier lié `/api/registrationFolders/{externalId}` complète l’identité de
  l’apprenti et la formation. Son identifiant et sa nature OPCO sont contrôlés.
- « Mettre à jour le dossier » relit un contrat puis tente la lecture bêta
  `/api/workingContracts/{id}/raw`. Seules les données CFA Dock dont l’identité est
  vérifiée sont exploitées. Les échéances ne sont affichées que si elles existent
  dans ce retour ; les montants absents restent inconnus. Les factures et paiements
  WEDOF génériques ne sont pas assimilés aux factures et règlements OPCO.

L’ajout est individuel : saisir le numéro complet de contrat OPCO ou le numéro
DECA, vérifier l’aperçu, puis cliquer sur « Ajouter ce dossier ». Une recherche
n’ajoute aucun dossier à la liste BTS. Les numéros sont comparés exactement,
après normalisation de la casse et des espaces ; une référence partielle ne
sélectionne pas les contrats dont le numéro commence de la même façon. Le choix
« Les quatre OPCO » est proposé par défaut ; il est possible de limiter la
recherche à un seul OPCO. Le financeur est conservé dans les résultats, la liste,
la fiche, la comptabilité et l’historique. Un même DECA chez plusieurs OPCO ne
fusionne jamais leurs contrats (chaque ID WEDOF reste distinct).

L’URL d’ajout est `/admin/BTS/ajouter-opco`. L’ancienne URL `/admin/BTS/ajouter-akto`
redirige vers ce formulaire. Les anciens aperçus et diagnostics de connexion
limités à AKTO sont invalidés lors du changement de périmètre ; les dossiers déjà
ajoutés restent conservés.

L’API WEDOF ne documente pas de filtre par ces numéros. La recherche explicite lit
donc les pages du catalogue, puis les fiches liées aux seuls contrats correspondant
au numéro. Les autres contrats ne sont pas enregistrés comme dossiers. L’aperçu
est lié à la session, expire après 20 minutes d’inactivité et n’entre pas dans les
exports. Chaque POST traite une page ou une fiche liée, avec un curseur et une
révision pour éviter les lectures répétées. Une série est limitée à 20 tentatives
avant reprise explicite ; tous les appels respectent aussi le compteur partagé
WEDOF, sans dérogation ni retry HTTP.

L’ajout relit uniquement le contrat choisi et sa fiche liée, vérifie leur identité
et l’absence de changement du contrat depuis l’aperçu, puis crée ce seul dossier
dans une transaction. Un double clic ne crée pas de doublon. Si plusieurs contrats
portent le numéro DECA saisi, chacun doit être ajouté séparément.

Les GET de navigation n’effectuent aucun appel WEDOF et aucun cron n’est ajouté.
La synchronisation périodique des OPCO vers WEDOF n’ajoute rien dans Gestion Stagiaires.
Les anciens imports globaux `/admin/BTS/synchroniser`,
`/admin/BTS/wedof/synchroniser` et `/admin/BTS/akto/sync` sont désactivés côté serveur
(HTTP 410 après contrôle des droits et du CSRF).

`bts_wedof_contracts` conserve le cache par ID WEDOF (`w-…`) de manière additive.
Un nouvel ajout d’un contrat déjà présent ouvre le dossier existant sans le modifier.
L’actualisation ciblée ne modifie jamais les notes, frais, brouillons ou dossiers locaux.
Deux contrats du même apprenti restent distincts ; aucune fusion par nom n’est
faite. Une recherche ne remplace ni ne supprime aucun dossier existant. Les informations importées sont en
lecture seule et limitées aux champs utiles ; le payload brut, le NIR et les
coordonnées bancaires ne sont pas conservés.

Les événements explicitement liés à l’apprentissage ne passent plus par les
relais commerciaux CPF vers le CRM/Salesforce. Ils ne déclenchent pas de mise à
jour BTS automatique dans ce lot. Les protections de connexion, droits d’écriture,
super-administration, CSRF, verrou interprocessus et non-cache sont réutilisées.

Le bouton de test vérifie réellement l’accès au catalogue des quatre OPCO, sans
certifier que chaque connexion individuelle est active. La présence de la
clé ne suffit pas à annoncer une connexion validée. Une liste vide peut indiquer
que les contrats ne sont pas encore synchronisés chez WEDOF ou pas accessibles à
cette clé ; le logiciel l’indique sans fabriquer de dossiers.

Sources vérifiées : [API WEDOF](https://www.wedof.fr/api/doc/),
[connexion OPCO CFA](https://doc.wedof.fr/article/21-connexion-opco-cfa).
Tests : `python -m unittest tests.test_wedof_bts tests.test_bts_workspace tests.test_akto_bts tests.test_wedof_isolation`.

## Accès et périmètre

Le point d’entrée de production `crm_app:app` enregistre `register_bts_workspace(legacy_app)`. L’URL reste `/admin/BTS` et `/admin/bts` redirige vers cette URL. Le lien de navigation historique ne change pas.

L’interface reprend la structure demandée : navigation dédiée, liste de dossiers, fiche par apprenti, onglets Suivi dossier / Étudiant / Contrat / Entreprise / Gestion / Comptabilité et comptabilité en deux colonnes (références et répartition des échéances à gauche, échéancier et frais à droite). Aucun logo Filiz et aucune donnée de démonstration ne sont ajoutés en production.

### Disponible sans raccordement OPCO

- Création de dossiers locaux ; modification des données étudiant, entreprise, maître d’apprentissage, formation et contrat.
- Contrôles de format et de cohérence : champs obligatoires, e-mails, longueur du SIRET, dates, heures et montants.
- Notes, checklist de préparation déclarative et historique interne.
- Brouillons de factures entreprise, export JSON et suppression explicite de ces brouillons.
- Recherche, filtres, pagination et export des données de l’espace.

### Disponible sur les dossiers OPCO ajoutés

- Consultation des données remontées par le connecteur existant, sans modification de leur source.
- Échéancier, répartition des montants payés/en instruction/à facturer/à venir/à vérifier.
- Périodes OPCO lorsqu’elles sont fournies ; sinon périodes calculées entre l’ouverture d’une échéance et celle de la suivante. Cette convention d’affichage ne modifie pas l’ouverture à la facturation. Une ouverture suivante absente, dupliquée ou incohérente ne permet pas de calculer une fin. Aucune fin n’est inventée pour la dernière échéance.
- Frais annexes accordés regroupés par nature, avec colonnes Accordé / Réglé / Non réglé. Les plafonds ne sont plus affichés ni utilisés dans les montants. L’état explicite « réglé » permet d’afficher le montant accordé soldé ; « non réglé » est présenté comme « Non soldé », sans déduire les montants d’éventuels paiements partiels. Les règlements non détaillés restent inconnus, jamais assimilés à zéro ou aux règlements des échéances pédagogiques. Les données périmées ne confirment pas un règlement.
- Préparation d’un brouillon OPCO pour une échéance ouverte et exploitable. Le montant est calculé côté serveur et les doublons de brouillons par échéance sont bloqués.
- Présentation séparée des factures déjà connues d’AKTO, avec leur date de synchronisation.

### Lecture directe AKTO sur action explicite

- Test de connexion : authentification OAuth, puis lecture de la première page `/v2/dossiers/etats`. Paramètres renseignés et connexion vérifiée sont deux états différents. Le résultat est invalidé si la configuration change.
- Actualisation ciblée : lecture du dossier `/v2/dossiers?numeroInterne=…`, vérification de son identité et mise à jour de ses données/échéances seulement. Les factures gardent leur propre date de vérification.
- L’ancien import global direct AKTO est désactivé, comme l’import global WEDOF.

## Limites à ne pas confondre avec des fonctionnalités actives

Ce lot n’émet pas de contrat ni de facture et ne transmet aucun document à un OPCO. Les CERFA PDF, conventions, signatures électroniques, certificats de réalisation, factures définitives, envois et retours d’instruction restent des lots distincts à développer/valider. La checklist interne ne prouve pas la présence d’une signature ou la conformité réglementaire d’un dossier.

La saisie et l’affichage des frais locaux ont été retirés de l’interface à la demande de l’utilisateur. Les anciennes données sont conservées en base et dans l’export ; elles ne sont pas des montants acceptés par l’OPCO. Les brouillons ne font pas évoluer artificiellement les montants facturés, les règlements ou les états du financeur. Le reste à charge entreprise n’est pas calculé automatiquement.

La récupération via WEDOF nécessite la clé WEDOF existante, une connexion active chez WEDOF pour chacun des OPCO concernés et des contrats accessibles à cette clé. Aucun nouveau secret OPCO n’est saisi dans Gestion Stagiaires. Le test n’infère pas la validité de chaque connexion à partir de la seule présence des variables. Les identifiants OAuth AKTO concernent uniquement le connecteur direct avancé.

## Stockage et sécurité

Les tables `bts_local_dossiers`, `bts_annotations`, `bts_fees`, `bts_invoice_drafts`, `bts_events`, `bts_diagnostics`, `bts_wedof_contracts` et `bts_wedof_lookups` sont créées de manière additive dans la base BTS dédiée. Aucun accès à `data.json` n’est nécessaire pour rendre les pages BTS. Le remplacement du cache AKTO ne supprime pas ces tables locales. Les recherches expirées sont exclues des lectures et purgées lors de l’enregistrement d’une nouvelle étape de recherche.

Les routes reprennent les contrôles de connexion, de super-administration et de droit d’écriture du projet. Les partenaires sont exclus. Les nouveaux formulaires POST ont un jeton CSRF propre à la session. Les modifications simultanées sont protégées par un numéro de révision. Les exports sont confidentiels et non mis en cache. Les clés et secrets restent dans Render, ne figurent ni dans les pages ni dans les diagnostics enregistrés.

Les montants d’échéances incomplets, négatifs ou incohérents et les identifiants d’échéance ambigus ne donnent pas lieu à un brouillon automatiquement préparé. Une mise à jour de l’échéancier peut rendre un ancien brouillon à revalider.

## Validation reproductible

Le workflow `Espace BTS` exécute les tests unitaires de l’espace, les tests du connecteur existant, un contrôle de l’entrée réelle `crm_app` et des parcours Chromium sur une application temporaire avec données fictives.

Commandes :

```sh
python -m unittest tests.test_bts_workspace -v
python -m unittest tests.test_akto_bts -v
python -m unittest tests.test_wedof_bts tests.test_wedof_isolation -v
python scripts/check_bts_workspace_ui.py --browser
```

Le script de navigateur vérifie le sélecteur des quatre OPCO, la recherche par DECA, l’aperçu sans import, l’ajout du seul contrat OPCO EP choisi parmi quatre contrats disponibles, les dialogues, la création d’un dossier local, les frais accordés et leurs états de règlement, le retrait de la saisie locale, les périodes entre ouvertures, les brouillons, l’absence d’erreurs JavaScript et le débordement horizontal aux largeurs 1440, 1024, 768 et 390 pixels. Les tests unitaires couvrent aussi les quatre financeurs, les références identiques, le filtre conservé lors d’une reprise et le rejet d’un OPCO inattendu. Le contrôle de l’entrée réelle vérifie la désactivation des trois anciens imports globaux. Le faux accès de test n’est enregistré que dans l’application Flask temporaire du script et n’existe pas en production.

## Déploiement et retour arrière

La fusion sur `main` déclenche le déploiement automatique Render déjà configuré. Aucun nouveau service ni nouvelle variable obligatoire n’est ajouté. Contrôler le statut du déploiement, `/healthz` et les journaux avant d’annoncer la mise en ligne.

Toute restauration doit conserver l’enregistrement de l’espace BTS et la désactivation des imports globaux. Ne pas supprimer les tables `bts_*` : elles contiennent le travail local et doivent être conservées/exportées. Une sauvegarde/restauration doit utiliser les mécanismes SQLite appropriés et tenir compte du journal WAL.
