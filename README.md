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
- `WEDOF_WEBHOOK_SECRET` (optionnel au démarrage, secret de signature webhook WeDoF)

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

- Chaque écriture de `data.json` et `data_vae.json` est atomique (`.tmp` puis `os.replace`).
- Un snapshot JSON est créé automatiquement dans `PERSIST_DIR/backups` (au plus toutes les 5 minutes par défaut).
- Les actions de suppression sensibles forcent un snapshot immédiat juste avant la suppression.
- L'endpoint `GET /api/health` expose le nombre de sauvegardes présentes pour vérification rapide.


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
