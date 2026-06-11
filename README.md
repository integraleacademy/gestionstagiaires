# Gestion stagiaires

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
- `BACKUP_RETENTION` (optionnel, nombre de snapshots conservés, défaut `120`)
- `BACKUP_MIN_INTERVAL_SECONDS` (optionnel, fréquence mini entre snapshots automatiques, défaut `300`)
- `AUTO_RESTORE_FROM_BACKUP` (optionnel, défaut `1`) : en cas de `data.json` manquant/corrompu, tente une restauration automatique depuis `PERSIST_DIR/backups`.
- `CNAPSV3_BASE_URL` (optionnel, défaut `https://cnapsv3.onrender.com`)
- `GESTIONSTAGIAIRE_SYNC_TOKEN` (obligatoire pour synchroniser le statut CNAPS vers cnapsv3)
- `WEDOF_WEBHOOK_SECRET` (recommandé : si défini, une signature invalide/manquante est refusée)
- `WEDOF_API_TOKEN` (token API WeDoF pour récupérer le détail complet d'un dossier)
- `DOCS_TO_CONTROL_PUBLIC_TOKEN` (optionnel : token requis pour exposer `/docs_to_control.json` à un dashboard externe sans session admin)
- `MAX_JSON_BACKUP_BYTES` (optionnel, défaut `52428800` : limite de taille d'un JSON sauvegardé automatiquement)
- `YPAREO_API_URL` (défaut `https://api.ypareo-neo.com`)
- `YPAREO_AUTH_TOKEN` (obligatoire ; token initial fourni par YPAREO, utilisé uniquement par `/authenticate`)
- `YPAREO_AUTH_ENDPOINT` (défaut `/authenticate`)
- `YPAREO_APPRENANTS_ENDPOINT` (défaut `/personne`)
- `YPAREO_CURSUS_ENDPOINT` (optionnel, défaut `/personne/{id_personne}/cursus`)
- `YPAREO_ID_ORGANISME` (UUID de l’organisme envoyé lors de la création du cursus)
- `YPAREO_ID_STATUT_CURSUS` (UUID du statut initial du cursus)
- `YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE` (optionnel, défaut `1`)
- `YPAREO_RESULTAT_CERTIFICATION` (optionnel, défaut `1`)
- UUID de formation selon les sessions utilisées : `YPAREO_ID_FORMATION_APS`, `YPAREO_ID_FORMATION_SSIAP1`, `YPAREO_ID_FORMATION_A3P`, `YPAREO_ID_FORMATION_VTC`, `YPAREO_ID_FORMATION_BTS_MOS`, `YPAREO_ID_FORMATION_BTS_MCO`, `YPAREO_ID_FORMATION_BTS_NDRC`, `YPAREO_ID_FORMATION_BTS_PI`, `YPAREO_ID_FORMATION_BTS_CI` et `YPAREO_ID_FORMATION_DSSP`. Cette dernière couvre toutes les variantes Dirigeant, DSSP, DO-ESP et DOESP.

## Intégration WeDoF CPF/EDOF

- Endpoint webhook: `POST /api/webhooks/wedof`
- URL Render à configurer côté WeDoF: `https://gestionstagiaires-r5no.onrender.com/api/webhooks/wedof`
- Historique webhook persisté dans `PERSIST_DIR/wedof_webhooks.json`

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
- Un snapshot JSON est créé automatiquement dans `PERSIST_DIR/backups` avant les écritures et au plus toutes les 5 minutes par défaut pour les snapshots périodiques.
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
