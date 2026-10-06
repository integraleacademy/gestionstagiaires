# Espace des organismes de formation

## Accès

- Inscription : `/creer-mon-espace`, depuis « Je n’ai pas de compte ».
- Accueil après connexion : `/admin/organisme`. Les liens directs autorisés vers une commande sont conservés ; les routes CRM restent interdites aux comptes organismes.
- Manuels : `/admin/manuels` ; e-learning en présentation uniquement : `/admin/organisme/e-learning` (APS 59 € TTC / stagiaire, A3P 89 € TTC / stagiaire).
- Gestion des comptes : `/admin/partners`, menu **Organismes de formation**.
- Commandes : `/admin/commandes-manuels`, menu **Commandes de manuels**.
- TVA, état de la configuration et connexion de paiement : `/admin/commandes-manuels/reglages`.

Les anciens comptes `account_type=manuals_only` deviennent des espaces organismes sans migration ni ouverture des modules CRM. Les commandes restent isolées par `partner_id` en JSON et PostgreSQL.

## Tarifs de la brochure 2026

Prix unitaires TTC, personnalisation des manuels et livraison incluses. Le palier est calculé **par titre**, pas sur le panier cumulé.

| Manuel | 50–99 exemplaires | 100 exemplaires et plus |
|---|---:|---:|
| SSIAP 1 | 17 € | 17 € |
| APS | 20 € | 18 € |
| A3P | 22 € | 20 € |
| DSSP | 22 € | 20 € |
| VTC | 22 € | 20 € |
| SST | 12 € | 10 € |

PowerPoint sur clé USB : 199 € par formation, sauf SST à 99 €. Aucun changement des valeurs n’était nécessaire après lecture de la nouvelle brochure ; l’affichage explicite « TTC / exemplaire » a été ajouté et les paliers sont vérifiés contre des valeurs de référence indépendantes.

## Commande, e-mails et facturation

La confirmation enregistre la commande et sa file de traitement dans une même mutation atomique. Le worker embarqué démarre à la première requête et reprend les travaux enregistrés après redémarrage. Il utilise des réservations persistantes de dix minutes ; les appels réseau ont lieu hors des transactions et hors du contexte HTTP d’un client. Il ne démarre pas dans les tests.

1. Brevo adresse une confirmation au centre et une notification à **clement@integraleacademy.com**, même si Qonto est indisponible.
2. La facturation réutilise le client Qonto identifié exactement par SIRET, avec les coordonnées de facturation vérifiées lors de la commande.
3. Le brouillon Qonto reprend les quantités, la TVA configurée et les prix TTC. Son total, sa devise, son client et sa référence de commande doivent correspondre avant finalisation. La numérotation reste gérée par Qonto.
4. La facture validée est envoyée au centre par e-mail avec son PDF en pièce jointe, son lien Qonto et le suivi de commande, même si le paiement en ligne n’est pas encore activé. Elle figure directement sur l’accueil organisme, dans l’historique du catalogue et dans le détail de commande. Un PDF encore en génération ou un échec Brevo est retenté sans réémettre de facture.
5. Une connexion OAuth autorisée à lire cette même facture crée un lien de paiement lié à la facture avec les moyens de paiement activés dans Qonto. Si la facture a déjà été envoyée sans lien de paiement, un e-mail distinct annonce une seule fois la disponibilité du règlement. Si le lien était disponible dès l’envoi de la facture, il est inclus dans le même e-mail.
6. Quand l’API Qonto confirme que la connexion au prestataire est `pending`, le traitement conserve la facture et revérifie automatiquement le paiement toutes les quinze minutes. Les autres défauts de configuration restent sous contrôle administrateur.
7. Le statut du paiement est vérifié auprès de Qonto toutes les quinze minutes pour les commandes actives. Le bouton d’actualisation est limité à une demande par minute. Une URL de retour du navigateur ne marque jamais une commande comme payée.

Les e-mails acceptés par Brevo ne sont pas renvoyés lors d’une relance. Un échec d’envoi est retenté avec temporisation, au maximum huit tentatives consécutives. Le journal indique l’acceptation par le prestataire, pas une preuve de lecture ou de remise en boîte de réception. Une interruption entre acceptation réseau et sauvegarde locale peut provoquer un second e-mail ; la sécurité des factures est traitée séparément.

Les créations Qonto ont une clé d’idempotence stable, mais leur sûreté ne dépend pas de sa durée de vie de 30 minutes : une création incertaine est recherchée par l’UUID immuable `purchase_order` (ou par `invoice_id` pour un lien) ; aucune nouvelle création automatique n’est tentée si l’incertitude persiste. Un total non conforme laisse la facture en brouillon. Les règlements partiels et liens expirés demandent un contrôle administratif. Annuler le statut logistique ne crée ni avoir ni remboursement dans Qonto.

Les commandes antérieures à cette version ne déclenchent aucun envoi ni aucune facture rétroactive. L’administrateur peut explicitement lancer leur traitement depuis le détail.

## Activation dans chaque environnement

- **Brevo** : la connexion existante de la plateforme est réutilisée.
- **Factures Qonto** : identifiants API existants et `QONTO_IBAN` sur le service concerné.
- **TVA** : renseigner les taux applicables aux manuels et clés USB dans les réglages. Aucun taux fiscal n’est déduit de prix TTC ; une exonération exige un motif. Les taux sont figés lorsque la préparation de la facture commence.
- **Paiement** : `QONTO_OAUTH_CLIENT_ID` et `QONTO_OAUTH_CLIENT_SECRET`, consentement comportant `payment_link.read` et `payment_link.write`, et prestataire de paiement actif dans Qonto. Le compte OAuth doit pouvoir lire la facture du compte marchand.
- Enregistrer dans l’application OAuth Qonto l’URL de retour propre à l’environnement, affichée dans les réglages : **`https://gestionstagiaires-test-v2.onrender.com/api/commerce/connexion-paiement/retour`** pour test-v2. Ce parcours ne modifie pas le retour OAuth historique du CRM vers la production.
- Les liens des e-mails utilisent `MANUALS_BASE_URL`, puis `RENDER_EXTERNAL_URL`, puis l’URL publique configurée.

La page d’administration distingue la présence de configuration d’un test de connexion réussi. Aucun test ne doit émettre de facture réelle fictive ou envoyer des messages de démonstration aux utilisateurs.

### Diagnostic et reprise des commandes (6 octobre 2026)

La liste et le détail administrateur affichent ensemble les prérequis manquants : TVA, identifiants/IBAN de facturation et autorisation des liens de paiement. Le lien client d’une commande ouvre désormais son détail administratif lorsqu’il est consulté par le super administrateur, au lieu de perdre la référence en revenant à la liste. Les clients voient un état d’attente d’activation explicite, sans accès aux réglages internes.

Le contrôle des factures accepte la devise dans `total_amount.currency`, conformément à la réponse documentée par Qonto ; le champ `currency` du payload de création n’est pas nécessairement renvoyé à la racine. Une devise absente, divergente ou autre qu’EUR bloque toujours la finalisation. Les tests de commerce utilisent ce format de réponse et vérifient qu’une autorisation de paiement manquante conserve la facture et la reprend sans doublon.

Le parcours dédié aux manuels nécessite que son adresse de retour soit enregistrée dans l’application du portail développeur Qonto. Une erreur Qonto `invalid_request` mentionnant `redirect_uri` signifie que cette inscription manque ; un déploiement Render ne peut pas l’ajouter chez Qonto. Ne pas remplacer ce retour par celui de production, qui enregistrerait l’autorisation dans un autre environnement. Les droits nécessaires sont `client_invoices.read`, `payment_link.read` et `payment_link.write`.

## Vérification

- Tests du parcours, tarifs, isolation JSON/PG, reprise des factures, paiements et e-mails : `tests/test_manuals*.py`. Vérification finale ciblée (incluant OAuth, sécurité et partenaires) : **200 tests réussis, 14 sous-tests réussis**.
- Vérification navigateur locale en 1440 px et 390 px, inscription → accueil → e-learning → sélection → facture et lien simulés ; aucun débordement ni erreur JavaScript.
- Suite élargie effectuée sans réseau : 358 réussites, 10 tests ignorés, 14 sous-tests réussis avant les derniers tests OAuth ciblés. Quatre échecs historiques ont été reproduits sur le commit antérieur `a86c9c2` : facturation CPF externalisée, normalisation de paiement Qonto et deux tests de sessions anciennes. Ils ne sont pas modifiés dans cette évolution.

Références API officielles consultées : [factures](https://docs.qonto.com/api-reference/business-api/expense-management/client-quotes-notes/client-invoices/create-a-client-invoice), [liens de paiement](https://docs.qonto.com/api-reference/business-api/payments-transfers/payment-links/create), [idempotence](https://docs.qonto.com/get-started/general/idempotent-requests).


## Présentation des manuels (octobre 2026)

Le bouton de l’accueil organisme et l’entrée « Manuels » ouvrent désormais `/admin/manuels/presentation`. Les six fiches `/admin/manuels/presentation/<code>` présentent les avantages, trois aperçus agrandissables, la personnalisation et les prix. Les actions de commande mènent au titre concerné dans le formulaire existant ; les liens de détails depuis ce formulaire s’ouvrent dans un autre onglet pour conserver la sélection.

Les textes et les 19 illustrations de `static/manuals/previews/` proviennent de la brochure « Brochure_Manuels_Tarifs_2026_corrigee.pdf » fournie le 4 octobre. Les images ont été extraites et converties en WebP ; les pages sont chargées à la demande. Les anciens nombres de leçons et la partie SST autrefois incluse dans le SSIAP 1 ne sont pas repris dans les descriptifs. Les prix des manuels restent exclusivement ceux de `CATALOGUE`, identiques au panier (notamment SSIAP 1 à 17 € dans les deux paliers).

Les nouvelles routes sont authentifiées et figurent dans l’allowlist des organismes. Le super administrateur peut consulter la présentation depuis « Commandes reçues » sans prendre l’identité d’un organisme. Cette consultation ne charge aucune commande et ne propose pas de validation d’achat.

Validation : 26 tests existants du parcours de commande réussis ; parcours présentation et six fiches contrôlé avec un organisme isolé, authentification, code inconnu (404), absence de droit d’administration, prix et images, puis consultation administrateur.
