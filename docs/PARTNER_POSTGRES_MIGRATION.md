# PostgreSQL dédié aux partenaires

Cette migration laisse les données historiques d’Intégrale dans `data.json`.
Seuls les partenaires externes, leurs utilisateurs, leurs invitations et leur
charge métier sont stockés dans le schéma PostgreSQL `partner_store`.

## Modes

| `PARTNER_POSTGRES_MODE` | Source utilisée | Comportement |
|---|---|---|
| `off` | JSON | Comportement historique, aucune connexion PostgreSQL |
| `shadow` | JSON | Sauvegarde puis copie/validation PostgreSQL sans servir ses données |
| `active` | PostgreSQL pour les partenaires | Intégrale reste en JSON ; les partenaires échouent en 503 si leur base est indisponible |

Le passage direct de `off` à `active` est interdit en exploitation. La phase
`shadow` doit se terminer avec des checksums identiques pour chaque partenaire.

## Variables Render

- `PARTNER_DATABASE_URL` : URL **interne** de la base Render située dans la
  même région et le même workspace que le service web.
- `PARTNER_POSTGRES_MODE` : `off`, `shadow` ou `active`.
- `PARTNER_POSTGRES_AUTO_MIGRATE` : `true` uniquement pendant le premier
  déploiement `shadow`, puis `false` après vérification.
- `PARTNER_POSTGRES_POOL_MAX_SIZE` : `4` avec le service Gunicorn actuel.
- `PARTNER_POSTGRES_TIMEOUT_SECONDS` : `5`.

Ne jamais enregistrer l’URL de connexion dans Git.

## Séquence de mise en production

1. Déployer le code avec `PARTNER_POSTGRES_MODE=off` et vérifier `/healthz`.
2. Créer PostgreSQL dans la même région Render et conserver le disque actuel.
3. Définir l’URL interne, `PARTNER_POSTGRES_MODE=shadow` et
   `PARTNER_POSTGRES_AUTO_MIGRATE=true`.
4. Le démarrage crée une sauvegarde durable `pre-partner-postgres`, importe
   chaque partenaire dans une transaction séparée puis relit et compare son
   checksum.
5. Vérifier les journaux, les lignes `partner_store.tenants`, `users` et
   `invitations`, puis remettre `PARTNER_POSTGRES_AUTO_MIGRATE=false`.
6. Passer à `active`, tester un compte partenaire, un compte administrateur et
   deux locataires différents, puis surveiller CPU, mémoire, erreurs et
   connexions PostgreSQL.

La commande manuelle équivalente est :

```bash
python scripts/migrate_partners_to_postgres.py --apply --verify
```

## Isolation et concurrence

- Chaque table porte obligatoirement un `partner_id`.
- PostgreSQL applique `FORCE ROW LEVEL SECURITY` sur les trois tables.
- Chaque transaction fixe localement le partenaire autorisé.
- Les connexions d’authentification utilisent uniquement les petites tables
  indexées, jamais le document métier complet.
- Une écriture issue d’une page obsolète est refusée avec un conflit 409 au
  lieu d’écraser silencieusement une modification plus récente.
- Une suppression crée d’abord une sauvegarde autonome du partenaire.

## Retour arrière

Tant que le mode `active` n’a reçu aucune nouvelle écriture, remettre `off`
réutilise directement le JSON sauvegardé. Après de nouvelles écritures, il faut
d’abord reconstruire le miroir JSON depuis PostgreSQL :

```bash
python scripts/export_partners_from_postgres.py
python scripts/export_partners_from_postgres.py --apply
```

La première commande est une simulation. La seconde sauvegarde `data.json`,
remplace uniquement les données des partenaires externes et contrôle que les
données d’Intégrale sont restées identiques. PostgreSQL et ses sauvegardes ne
doivent être supprimés qu’après validation définitive.
