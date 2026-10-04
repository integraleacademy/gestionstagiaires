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
4. Une connexion OAuth autorisée à lire cette même facture crée un lien de paiement lié à la facture avec les moyens de paiement activés dans Qonto. Le centre reçoit ensuite un e-mail avec le lien de règlement et le suivi de commande.
5. Le statut du paiement est vérifié auprès de Qonto toutes les quinze minutes pour les commandes actives. Le bouton d’actualisation est limité à une demande par minute. Une URL de retour du navigateur ne marque jamais une commande comme payée.

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

## Vérification

- Tests du parcours, tarifs, isolation JSON/PG, reprise des factures, paiements et e-mails : `tests/test_manuals*.py`. Vérification finale ciblée (incluant OAuth, sécurité et partenaires) : **200 tests réussis, 14 sous-tests réussis**.
- Vérification navigateur locale en 1440 px et 390 px, inscription → accueil → e-learning → sélection → facture et lien simulés ; aucun débordement ni erreur JavaScript.
- Suite élargie effectuée sans réseau : 358 réussites, 10 tests ignorés, 14 sous-tests réussis avant les derniers tests OAuth ciblés. Quatre échecs historiques ont été reproduits sur le commit antérieur `a86c9c2` : facturation CPF externalisée, normalisation de paiement Qonto et deux tests de sessions anciennes. Ils ne sont pas modifiés dans cette évolution.

Références API officielles consultées : [factures](https://docs.qonto.com/api-reference/business-api/expense-management/client-quotes-notes/client-invoices/create-a-client-invoice), [liens de paiement](https://docs.qonto.com/api-reference/business-api/payments-transfers/payment-links/create), [idempotence](https://docs.qonto.com/get-started/general/idempotent-requests).
