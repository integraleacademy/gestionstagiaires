# Espace commandes des organismes de formation

- Inscription : `/creer-mon-espace`, accessible depuis « Je n’ai pas de compte » sur la connexion commune.
- Connexion existante : `/admin/login`. Les nouveaux organismes arrivent sur `/admin/manuels`, quel que soit le paramètre `next` fourni.
- Administration : **Commandes de manuels**, dans la barre latérale, ou `/admin/commandes-manuels`. Seuls les administrateurs plateforme peuvent consulter toutes les commandes et modifier leur statut.
- Tarifs : brochure Intégrale Academy 2026, 50–99 puis 100 exemplaires et plus **par titre**. Les montants sont en centimes TTC, calculés côté serveur. Clés USB : 199 € par formation, 99 € pour SST. Livraison et personnalisation des manuels incluses.
- Il s’agit d’une commande enregistrée, sans prélèvement ni facture automatique. L’équipe organise le règlement, la personnalisation et le délai de livraison avec le centre.

## Stockage et sécurité

Les comptes réutilisent le stockage partenaires existant, en mode JSON ou PostgreSQL. Aucun changement de schéma SQL n’est nécessaire. Le partenaire porte `account_type=manuals_only` et une liste `enabled_modules` vide. Son rôle technique reste `partner_admin`, mais le garde global applique une liste positive de routes autorisées, avant les routes métiers. La restriction est relue depuis le stockage et ne dépend pas uniquement du cookie. Les comptes partenaires existants conservent leur comportement.

`manual_orders` est une collection explicitement cloisonnée par `partner_id`. Les quantités, prix et destinataires sont validés côté serveur. Les brouillons sont modifiables et accessibles depuis le catalogue ; la confirmation atomique d’un même brouillon ne crée pas deux commandes. Les écritures comportent un jeton CSRF. Les logos sont validés puis réencodés en PNG dans le dossier persistant du partenaire et téléchargés par une route protégée.

## E-mail de bienvenue

L’envoi réutilise Brevo et les variables existantes `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME` et l’adresse publique configurée. Le lien de connexion privilégie `MANUALS_BASE_URL` (optionnel), puis `RENDER_EXTERNAL_URL`, puis l’adresse publique existante. Cela maintient le lien sur le bon service, notamment `test-v2`.

Le compte est enregistré avant l’appel à Brevo. Le mot de passe n’est jamais envoyé par e-mail. Le résultat d’envoi est conservé dans `partner.welcome_email`. En cas d’échec, la page de succès précise que la connexion reste disponible et propose de réessayer après une minute. Aucun message de commande ni de prospection n’est envoyé automatiquement.

## Validation

`tests/test_manuals_shop.py` couvre les deux modes de stockage, l’inscription et ses validations, l’échec de livraison du mail, les droits, les seuils tarifaires, la manipulation des montants, les brouillons, la confirmation idempotente, les logos, les comptes suspendus et l’isolation entre centres.

Pour exécuter les tests d’interface existants qui dépendent des routes e-learning, importer `crm_app` avant de lancer pytest (c’est le point d’entrée Gunicorn).
