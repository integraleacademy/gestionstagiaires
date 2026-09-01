# Gestion stagiaires

## Import AFC depuis une capture France Travail

L'analyse structurée de la modale `/admin/afc` est réalisée exclusivement côté serveur. Variables à configurer sur Render :

- `OPENAI_API_KEY` : clé secrète du fournisseur (jamais exposée au navigateur) ;
- `AFC_IMPORT_VISION_MODEL` : modèle vision compatible JSON structuré (défaut : `gpt-4.1-mini`).

La capture est validée et réorientée en mémoire, sans conservation sur disque. La prévisualisation ne crée aucune fiche : seules les lignes confirmées sont revalidées et enregistrées.

## Intégration CRM Intégrale Connect

Le endpoint `POST /api/integrations/crm/stagiaires` est protégé par un jeton Bearer.
Configurer `CRM_INTEGRATION_API_TOKEN` avec un secret long partagé avec le CRM. Il ne
crée pas de stagiaire : il conserve le préremplissage pendant 15 minutes et renvoie
une URL d'administration contenant uniquement un identifiant temporaire opaque. Le
stagiaire n'est créé qu'après authentification et validation de la modale existante.

Après déploiement, appliquer si nécessaire la migration historique du stockage JSON avec :

```bash
python scripts/migrate_crm_integration.py
```

La migration crée une sauvegarde, initialise l'ancien registre d'idempotence et ajoute le
champ structuré `crm_center` aux sessions sans tenter de déduire un centre depuis leur
nom. Les sessions destinées au CRM doivent avoir ce champ renseigné exactement.

## Lancer en local

```bash
pip install -r requirements.txt
python app.py
```

## Variables d'environnement

- `SECRET_KEY`
- `ADMIN_USER`
- `ADMIN_PASSWORD`
- `SECRETARY_USER`
- `SECRETARY_PASSWORD`
- `ADMIN_PUSH_TITLE` (optionnel, titre affiché pour la notification, défaut `Gestion stagiaires`)
- `WEB_PUSH_VAPID_PUBLIC_KEY` (clé publique VAPID pour Web Push)
- `WEB_PUSH_VAPID_PRIVATE_KEY` (clé privée VAPID pour Web Push)
- `WEB_PUSH_VAPID_CLAIMS_SUB` (optionnel, ex: `mailto:contact@ton-domaine.com`)
- `PERSIST_DIR` (par défaut auto: `/var/data` puis `/data`)
- `MEMORY_DIAGNOSTICS_ENABLED` (optionnel, défaut `0`) : active les traces détaillées de mémoire par requête uniquement pendant un diagnostic.
- `QONTO_TRAINEE_AUTO_SYNC_TTL_SECONDS` (optionnel, défaut `300`) : délai minimal entre deux synchronisations automatiques de la même facture CPF depuis une fiche stagiaire.
- `BACKUP_RETENTION` (optionnel, nombre de snapshots conservés, défaut `120`)
- `BACKUP_MIN_INTERVAL_SECONDS` (optionnel, fréquence mini entre snapshots automatiques, défaut `300`)
- `AUTO_RESTORE_FROM_BACKUP` (optionnel, défaut `1`) : en cas de `data.json` manquant/corrompu, tente une restauration automatique depuis `PERSIST_DIR/backups`.
- `CNAPSV3_BASE_URL` (optionnel, défaut `https://cnapsv3.onrender.com`)
- `GESTIONSTAGIAIRE_SYNC_TOKEN` (obligatoire pour synchroniser le statut CNAPS vers cnapsv3)
- `CNAPS_MONITOR_TOKEN` (secret partagé entre le cron Render et le endpoint interne de suivi CNAPS)
- `CRON_SECRET` est généré et partagé automatiquement par le Blueprint Render entre le service web et les tâches cron ; il ne doit pas être créé séparément sur chaque service.
- `CNAPSV3_API_TOKEN` (obligatoire sur le service web pour que le suivi automatique lise les dossiers CNAPS)
- `WEDOF_WEBHOOK_SECRET` (recommandé : si défini, une signature invalide/manquante est refusée)
- `CRM_WEDOF_WEBHOOK_URL` (facultatif, défaut : `https://assistance-alw9.onrender.com/api/webhooks/wedof`)
- `CRM_WEDOF_WEBHOOK_SECRET` (facultatif : secret partagé avec le CRM ; à défaut, `WEDOF_WEBHOOK_SECRET` est réutilisé)
- `WEDOF_API_TOKEN` (token API WeDoF pour récupérer le détail complet d'un dossier)
- `AKTO_API_BASE_URL` (URL de l’API Convergence CFA/OPCO communiquée par AKTO)
- `AKTO_OAUTH_TOKEN_URL` (URL d’obtention du Bearer Token communiquée par AKTO)
- `AKTO_OAUTH_CLIENT_ID` et `AKTO_OAUTH_CLIENT_SECRET` (identifiants du logiciel Gestion Stagiaires fournis par AKTO)
- `AKTO_API_KEY` (clé du CFA ; la clé déjà configurée dans YPAREO peut être réutilisée)
- `AKTO_OAUTH_SCOPE` (optionnel, défaut `.default`)
- `AKTO_API_EDITOR`, `AKTO_API_SOFTWARE` et `AKTO_API_VERSION` (en-têtes d’identification du logiciel obligatoires dans l’API Convergence)
- `WEDOF_MAINTENANCE_WINDOW_ENABLED` (facultatif, `true` par défaut ; seules les valeurs `false`, `0`, `no` et `off` désactivent la suspension)
- `WEDOF_MAINTENANCE_START_TIME` (facultatif, heure de Paris au format `HH:MM`, `05:00` par défaut)
- `WEDOF_MAINTENANCE_END_TIME` (facultatif, heure de Paris au format `HH:MM`, `07:00` par défaut ; la borne de fin est exclue)
- `DOCS_TO_CONTROL_PUBLIC_TOKEN` (optionnel : token requis pour exposer `/docs_to_control.json` à un dashboard externe sans session admin)
- `DOCS_TO_CONTROL_TRUSTED_USER_AGENT` (optionnel : User-Agent exact autorisé pour le dashboard externe historique si aucun token public n’est configuré ; défaut `plateformegestion/1.0 (+https://plateformegestion.onrender.com)`)
- `MAX_JSON_BACKUP_BYTES` (optionnel, défaut `52428800` : limite de copie d'un JSON sauvegardé automatiquement si la création de snapshot par lien dur n'est pas disponible)
- `YPAREO_API_URL` (défaut `https://api.ypareo-neo.com`)
- `YPAREO_AUTH_TOKEN` (obligatoire ; token initial fourni par YPAREO, utilisé uniquement par `/authenticate`)
- `YPAREO_AUTH_ENDPOINT` (défaut `/authenticate`)
- `YPAREO_APPRENANTS_ENDPOINT` (défaut `/personne`)
- `YPAREO_CURSUS_ENDPOINT` (optionnel, défaut `/personne/{IdPersonne}/cursus`)
- `YPAREO_ID_ORGANISME` (UUID de l’organisme envoyé lors de la création du cursus)
- `YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE` (optionnel ; absent du payload cursus par défaut)
- UUID de formation selon les sessions utilisées : `YPAREO_ID_FORMATION_APS`, `YPAREO_ID_FORMATION_SSIAP1`, `YPAREO_ID_FORMATION_A3P`, `YPAREO_ID_FORMATION_VTC`, `YPAREO_ID_FORMATION_BTS_MOS`, `YPAREO_ID_FORMATION_BTS_MCO`, `YPAREO_ID_FORMATION_BTS_NDRC`, `YPAREO_ID_FORMATION_BTS_PI`, `YPAREO_ID_FORMATION_BTS_CI` et `YPAREO_ID_FORMATION_DSSP`. Cette dernière couvre toutes les variantes Dirigeant, DSSP, DO-ESP et DOESP.

## Intégration WeDoF CPF/EDOF

- Endpoint webhook: `POST /api/webhooks/wedof`
- URL Render à configurer côté WeDoF: `${PUBLIC_BASE_URL}/api/webhooks/wedof`
- Historique webhook persisté dans `PERSIST_DIR/wedof_webhooks.json`
- Chaque nouvelle demande exploitable est envoyée automatiquement à Salesforce lors de la réception du webhook. Lorsqu'elle est authentifiée, elle est aussi transmise au CRM. Le dossier complet déjà mis en cache est relayé sans nouvelle lecture WEDOF. En cas d'échec, la demande reste enregistrée et l'interface admin permet de relancer séparément chaque envoi.
- L'action **Notifier** (mail/SMS au candidat) reste volontairement manuelle dans l'interface admin.

## Espace BTS / AKTO

- Interface administrateur autonome : `GET /admin/BTS`
- Synchronisation complète et volontaire : `POST /admin/BTS/akto/sync`
- Export du cache sécurisé : `GET /admin/BTS/akto/export.json`
- Stockage séparé de `data.json` dans `PERSIST_DIR/akto_bts.sqlite3`
- La consultation et les filtres lisent exclusivement le cache local ; seuls les clics sur « Synchroniser toutes les données » contactent AKTO.
- L’API Key CFA ne suffit pas à elle seule : AKTO doit aussi attribuer à Gestion Stagiaires un Client ID et un Client Secret OAuth2, ainsi que les deux URL techniques.
- Les NIR, IBAN et secrets sont masqués avant stockage. Ils ne figurent ni dans le tableau ni dans l’export JSON.

## Module VAE DESP

- Création dossier : `GET /vae/nouveau`
- Wizard public : `GET /vae/<token>`
- Sauvegarde auto : `PATCH|POST /api/vae/<id>/save`
- Soumission : `POST /api/vae/<id>/submit`
- Confirmation : `GET /vae/<token>/succes`
- Admin liste : `GET /admin/vae`
- Admin détail : `GET|POST /admin/vae/<id>`
- Export JSON : `GET /admin/vae/<id>/export`

Les dossiers VAE sont persistés dans `data_vae.json` dans `PERSIST_DIR`.


## Sauvegardes anti-perte de données

- Chaque écriture de `data.json`, `data_vae.json` et `wedof_webhooks.json` est protégée par un verrou fichier inter-processus, écrite dans un fichier temporaire unique, synchronisée (`fsync`) puis remplacée par `os.replace`.
- Un snapshot JSON est créé automatiquement dans `PERSIST_DIR/backups` avant les écritures et au plus toutes les 5 minutes par défaut pour les snapshots périodiques. Les snapshots utilisent d’abord un lien dur pour protéger aussi les gros fichiers `data.json` sans copie coûteuse ; la limite `MAX_JSON_BACKUP_BYTES` ne s’applique qu’au repli par copie.
- Les noms de sauvegardes incluent un timestamp précis et un suffixe aléatoire pour éviter qu'une sauvegarde écrase une autre version.
- Les fichiers supprimés par les routes sensibles sont déplacés dans `PERSIST_DIR/trash` quand c'est possible.
- L'endpoint `GET /api/health` expose le nombre de sauvegardes présentes pour vérification rapide.
- Un rapport complet est disponible dans `SECURITY_AUDIT.md`.


## Notifications push iPhone (Safari)

- Ouvre le site avec Safari sur iPhone, puis **Ajouter à l'écran d'accueil**.
- Lance l'app depuis l'icône ajoutée.
- Sur une page admin (sessions/stagiaires), clique **📲 Activer push iPhone** dans le panneau notifications.
- Autorise les notifications quand iOS le demande.

> Sans les clés VAPID (`WEB_PUSH_VAPID_PUBLIC_KEY` / `WEB_PUSH_VAPID_PRIVATE_KEY`), le bouton restera désactivé côté interface.


## Surveillance automatique des statuts CNAPS

Le Blueprint Render déploie `gestionstagiaires-cnaps-monitor`, un worker permanent qui appelle toutes les 15 minutes le endpoint interne protégé `POST /internal/jobs/cnaps-public-annuaire-monitor`. La vérification et l’envoi des e-mails se font donc côté serveur, même si aucun administrateur n’ouvre le site.

Sur Render, le groupe d’environnement partagé du Blueprint fournit automatiquement la même valeur secrète `CNAPS_MONITOR_TOKEN` au service web et au worker. Le service web doit également disposer de `CNAPSV3_API_TOKEN` et de la configuration Brevo habituelle. L’intervalle est configurable avec `CNAPS_MONITOR_INTERVAL_SECONDS` (900 secondes par défaut).

### Configuration dans Render

Lors de l’application du Blueprint, Render demande les trois secrets suivants :

1. Dans le groupe partagé `gestionstagiaires-cnaps-monitor-secrets`, générer `CNAPS_MONITOR_TOKEN` avec une longue valeur aléatoire. Le Blueprint injecte automatiquement cette valeur identique dans le site et dans le worker ; il ne faut pas créer deux valeurs différentes.
2. Sur le service web `gestionstagiaires`, renseigner `CNAPSV3_API_TOKEN` avec le jeton fourni par CNAPSV3.
3. Sur ce même service web, renseigner `BREVO_API_KEY` pour permettre l’envoi des e-mails.

Le worker n’a besoin ni du jeton CNAPSV3 ni de la clé Brevo : il réveille le endpoint protégé du service web, qui effectue le contrôle et l’envoi. Après configuration, redéployer le Blueprint et vérifier dans les logs de `gestionstagiaires-cnaps-monitor` qu’une réponse contenant `"ok": true` apparaît environ toutes les 15 minutes.

### Disponibilité du service web

Le service web utilise un seul worker Gunicorn par défaut afin de limiter sa
consommation mémoire. Son recyclage périodique est désactivé : recycler l’unique
worker laisse le service sans processus disponible pendant le rechargement de
l’application et provoque des réponses 502 intermittentes sur Render.

Si le service est dimensionné avec `WEB_CONCURRENCY=2` ou plus, le recyclage
peut être réactivé avec `GUNICORN_MAX_REQUESTS` et
`GUNICORN_MAX_REQUESTS_JITTER`. L’endpoint léger `/healthz` permet de vérifier
la disponibilité sans lire les fichiers de données.

## Intégration cnapsv3 (sync ACCEPTÉ)

Lorsqu'une entrée CNAPS PRE est enregistrée et devient visible dans `/admin/cnaps/import-pre/pending`, gestionstagiaires déclenche un `POST` vers:

- `${CNAPSV3_BASE_URL}/integrations/gestionstagiaire/cnaps/accept`

Payload envoyé:

- prioritaire: `{"request_id": "..."}`
- sinon fallback: `{"dossier_id": "..."}`

Headers envoyés:

- `Content-Type: application/json`
- `Authorization: Bearer ${GESTIONSTAGIAIRE_SYNC_TOKEN}`

En cas d'erreur réseau/timeout, l'appel est retenté automatiquement (3 tentatives, backoff 1s/2s/4s).

## Webhook Qonto — factures clients

Endpoint à déclarer côté Qonto : `https://<votre-domaine>/api/qonto/webhooks`.

Configuration requise :

- variable d'environnement `QONTO_WEBHOOK_SECRET` contenant le secret de signature du webhook ;
- événement webhook `v1/client-invoices` pour les événements `created` et `updated` ;
- scopes OAuth `webhook`, `client_invoices.read`, `sepa_direct_debit.read` et `sepa_direct_debit.write` (ainsi que les scopes facturation déjà déclarés) ; `webhook` est obligatoire pour consulter, créer et mettre à jour une souscription. L'application ne crée pas automatiquement de souscription webhook au démarrage.

Le webhook ne stocke jamais le secret dans `data.json` et ne fait pas confiance au montant reçu dans le payload : il relit la facture Qonto puis met à jour les montants agrégés en centimes.

### Activation et test en production

1. Générez vous-même un secret de **32 à 128 caractères**, définissez-le dans Render sous `QONTO_WEBHOOK_SECRET`, puis redéployez. L'application envoie exactement cette valeur à Qonto lors de la création ou mise à jour de la souscription et ne l'affiche ni ne la journalise.
2. Si la connexion OAuth a été faite avant l’ajout du scope `webhook`, cliquez sur **Réinitialiser connexion Qonto OAuth**, puis reconnectez Qonto pour donner le nouveau consentement. Un ancien jeton ne suffit pas à attester ce scope.
3. Dans **Réglages > Qonto**, cliquez sur **Vérifier et activer le webhook Qonto**. L'application conserve une souscription canonique existante, complète ses événements si besoin et ne crée une souscription que si aucune n'est réutilisable.
4. Effectuez un paiement de test. Actualisez la section **État de la synchronisation Qonto** : le dernier webhook doit indiquer une date, un type et le résultat `updated`. Vérifiez ensuite la facture dans l'administration sans cliquer sur « Synchronisation Qonto ».

La synchronisation manuelle et la synchronisation à l'ouverture d'une fiche restent des mécanismes de récupération. Les événements attendus sont `v1/client-invoices`, `v1/sepa-direct-debit-mandates` et `v1/sepa-direct-debit-collections`.
