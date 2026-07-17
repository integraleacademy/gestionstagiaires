# Webhook Qonto — factures clients

Endpoint à déclarer côté Qonto :

- `https://<votre-domaine-public>/api/qonto/webhooks`

Événement utilisé par la plateforme :

- Type : `v1/client-invoices`
- Événements : `created`, `updated`

Scopes Qonto requis :

- `client_invoices.read` pour relire la facture via `GET /v2/client_invoices/{id}` après réception du webhook.
- `webhook` uniquement si la souscription webhook est créée ou gérée via l’API Qonto.

Configuration serveur :

- Définir `QONTO_WEBHOOK_SECRET` dans les variables d’environnement.
- Ne pas stocker ce secret dans `data.json`.
- La plateforme ne crée pas automatiquement de nouvelle souscription webhook au démarrage ; la synchronisation manuelle reste disponible si la souscription webhook n’est pas configurée.

Sécurité :

- La signature `X-Qonto-Signature` attendue est au format `t={timestamp},v1={signature}`.
- Le timestamp est refusé au-delà de 5 minutes.
- Le montant encaissé n’est jamais pris comme source définitive depuis le webhook : la facture est toujours relue côté serveur auprès de Qonto avant mise à jour locale.
