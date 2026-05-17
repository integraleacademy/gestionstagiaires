# Audit sécurité et persistance des données

Date de réalisation : 2026-05-17.

## Sauvegarde préalable

Avant modification, une archive complète du code existant a été créée hors dépôt :

- `/workspace/backups/gestionstagiaires-pre-security-audit-20260517T043714Z.tar.gz`

## Cartographie des données

Toutes les données mutables doivent être stockées dans `PERSIST_DIR` :

| Donnée | Emplacement | Persistant attendu |
| --- | --- | --- |
| Données principales sessions/stagiaires/admin | `PERSIST_DIR/data.json` | Oui |
| Dossiers VAE | `PERSIST_DIR/data_vae.json` | Oui |
| Historique webhook WeDoF | `PERSIST_DIR/wedof_webhooks.json` | Oui |
| Uploads stagiaires, documents, factures, livrables, imports CNAPS | `PERSIST_DIR/uploads/` | Oui |
| Sauvegardes automatiques JSON | `PERSIST_DIR/backups/` | Oui |
| Corbeille fichiers supprimés | `PERSIST_DIR/trash/` | Oui |

Aucune base de données SQL/NoSQL dédiée n'est utilisée dans le code actuel : la persistance applicative repose sur des fichiers JSON et des fichiers uploadés.

## Risques trouvés

### Critiques

1. **Risque d'exposition de routes admin/API sans authentification explicite**
   - Plusieurs routes `/admin/afc`, `/api/admin/afc/*`, `/api/secretariat/*` et `/api/cnaps_lookup` n'avaient pas toutes un décorateur d'authentification local.
   - Correction : ajout d'un garde global `before_request` sur les espaces sensibles.

2. **Route JSON publique des dossiers à contrôler**
   - `/docs_to_control.json` est volontairement publique pour alimenter la plateforme principale.
   - Correction actuelle : la route reste exclue des gardes admin/API et renvoie uniquement un JSON structuré attendu par le dashboard.

3. **Signature webhook WeDoF non bloquante**
   - Si `WEDOF_WEBHOOK_SECRET` était configuré mais la signature absente/invalide, le webhook continuait son traitement.
   - Correction : rejet HTTP 401 quand un secret est configuré et que la signature est invalide.

### Élevés

4. **Écritures JSON atomiques mais verrouillage inter-processus insuffisant**
   - Le verrou Python protège un seul processus. En production, plusieurs workers peuvent écrire en même temps.
   - Correction : ajout d'un verrou fichier `fcntl.flock` et de fichiers temporaires uniques avant `os.replace`.

5. **Sauvegardes pouvant s'écraser dans la même seconde**
   - Les noms de sauvegarde utilisaient un timestamp à la seconde.
   - Correction : timestamp microseconde + suffixe UUID.

6. **Suppression physique d'un import CNAPS**
   - Une route supprimait directement le fichier lié à un import CNAPS en attente.
   - Correction : déplacement vers `PERSIST_DIR/trash/` via `_safe_remove_file`.

### Moyens

7. **Chemin de persistance trop rigide**
   - Le code forçait `/data`, ce qui peut être éphémère selon la configuration Render.
   - Correction : `PERSIST_DIR` devient prioritaire, puis fallback `/var/data`, puis `/data`, avec test d'écriture au démarrage.

8. **Dé-tokenisation de chemins perfectible**
   - La suppression de `..` était insuffisante comme garde de chemin.
   - Correction : résolution `realpath` et vérification stricte que le fichier reste sous `PERSIST_DIR`.

## Corrections appliquées

- Garde global des namespaces sensibles `/admin/*`, `/api/admin/*`, `/api/secretariat/*`, `/api/cnaps*`.
- Refus d'écriture API pour les sessions admin en rôle `viewer`.
- Verrouillage inter-processus des fichiers JSON via `.lock` + `fcntl.flock`.
- Écriture durable : `json.dump` dans un temporaire unique, `fsync`, `os.replace`, puis `fsync` du dossier parent.
- Sauvegarde avant écriture avec noms non collisionnels.
- Sauvegarde des webhooks WeDoF avec le même mécanisme de backup que les autres JSON.
- Exclusion explicite de `/docs_to_control.json` du garde global afin de conserver le flux public attendu.
- Rejet des webhooks WeDoF invalides quand `WEDOF_WEBHOOK_SECRET` est défini.
- Sécurisation des chemins tokenisés sous `PERSIST_DIR`.
- Mise en corbeille des fichiers CNAPS supprimés au lieu d'une suppression immédiate.

## Recommandations Render

Variables Render à vérifier/configurer :

- `SECRET_KEY` : obligatoire, aléatoire, long.
- `ADMIN_USER`, `ADMIN_PASSWORD`, `SECRETARY_USER`, `SECRETARY_PASSWORD` : uniquement en variables Render.
- `SCOTIA_USER`, `SCOTIA_PASSWORD` : uniquement en variables Render si portail Scotia utilisé.
- `PERSIST_DIR` : chemin exact du disque persistant Render, recommandé `/var/data` si le disque est monté ici.
- `BACKUP_RETENTION` : garder plusieurs versions, recommandé `120` ou plus selon volume.
- `BACKUP_SNAPSHOT_BEFORE_SAVE=1` : recommandé.
- `WEDOF_WEBHOOK_SECRET` : recommandé pour bloquer les faux webhooks.
- `/docs_to_control.json` : endpoint public consommé par la plateforme principale.
- Clés Brevo/VAPID/OCR/API : uniquement en variables Render, jamais dans le code.

## Restauration simple

1. Arrêter temporairement l'application ou bloquer les écritures.
2. Identifier la sauvegarde valide dans `PERSIST_DIR/backups/`.
3. Copier la sauvegarde vers le fichier cible (`data.json`, `data_vae.json` ou `wedof_webhooks.json`).
4. Redémarrer le service.
5. Contrôler `/api/health/storage-integrity`.

Le code tente déjà une restauration automatique de `data.json`/`data_vae.json` si un fichier est manquant ou corrompu.
