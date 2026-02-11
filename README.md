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
- `PERSIST_DIR` (par défaut `/data`)

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
