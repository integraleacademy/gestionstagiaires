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
- `ADMIN_PUSH_NOTIFICATIONS_ENABLED` (`1/true/on` pour activer l'envoi push des notifications admin)
- `ADMIN_PUSH_WEBHOOK_URL` (URL webhook du service push vers ton téléphone)
- `ADMIN_PUSH_TOKEN` (optionnel, envoyé en `Authorization: Bearer ...`)
- `ADMIN_PUSH_TITLE` (optionnel, titre affiché pour la notification, défaut `Gestion stagiaires`)
- `PERSIST_DIR` (par défaut `/data`)
- `BACKUP_RETENTION` (optionnel, nombre de snapshots conservés, défaut `120`)
- `BACKUP_MIN_INTERVAL_SECONDS` (optionnel, fréquence mini entre snapshots automatiques, défaut `300`)

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
