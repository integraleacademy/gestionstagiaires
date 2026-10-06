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

La confirmation enregistre la commande et sa file de traitement dans une même mutation atomique. Le worker embarqué démarre à la première requête et reprend les travaux enregistrés après redémarrage. Il utilise des réservations persistantes de dix minutes ; les appels réseau ont lieu hors des transactions et hors du contexte HTTP d’un client. Il ne démarre pas dans les tests. La validation conduit directement à une page d’ouverture du paiement : elle lit uniquement le statut local toutes les deux secondes et ouvre l’URL Qonto vérifiée dans le même onglet dès sa disponibilité. Aucun appel marchand ne se fait dans la session HTTP du client. Le bouton Retour du navigateur revient au suivi de commande sans relancer le paiement. Après deux minutes ou en cas de blocage du prestataire, le suivi affiche la situation et permet de reprendre le paiement.

1. Avant tout encaissement, le compte destinataire du paiement OAuth est comparé aux comptes de l’organisme de facturation identifié par clé API. La TVA et les prix TTC de la commande sont figés.
2. Un lien Qonto **Basket à usage unique**, sans facture, reprend les articles et le montant exact TTC. Il s’ouvre automatiquement après la validation, reste accessible depuis la commande et l’espace organisme dans le même onglet, puis est envoyé par e-mail. La disponibilité du paiement est publiée avant l’envoi des e-mails ; une panne de messagerie ne masque pas un lien valide. Pour une TVA non nulle, un lot peut être regroupé afin de respecter la limite de deux décimales de Qonto sans modifier le TTC.
3. Brevo adresse une confirmation au centre et une notification à **clement@integraleacademy.com**, même si Qonto est indisponible.
4. La plateforme interroge les paiements du lien toutes les minutes (worker réveillé toutes les 45 secondes). Seul un paiement `paid`, de montant exact en EUR, rattaché au lien et à la commande, autorise la facturation. Un lien indiqué payé sans paiement confirmé, une autorisation bancaire, un paiement en cours, refusé ou abandonné ne suffisent pas. Le bouton d’actualisation est limité à une demande par minute. Les paramètres de retour du navigateur ne font jamais foi.
5. **Après paiement seulement**, le client Qonto est retrouvé par SIRET. La facture reprend les quantités, la TVA et les prix TTC figés. Le total, la devise, l’organisme marchand, le client et la référence de commande sont vérifiés avant finalisation. La facture porte sa date d’émission réelle et la référence du paiement ; Qonto gère sa numérotation.
6. La facture est marquée acquittée avec la date du paiement confirmé, puis son statut est relu. Le PDF officiel est envoyé par Brevo et devient accessible dans l’espace organisme. Un PDF en génération ou un échec d’envoi est retenté sans recréer la facture.
7. Si le prestataire est encore `pending`, une vérification est programmée toutes les quinze minutes. **Aucune facture n’est créée pendant cette attente.** Les autres défauts de configuration ou discordances demandent une intervention administrative.

Les e-mails acceptés par Brevo ne sont pas renvoyés lors d’une relance. Un échec d’envoi est retenté avec temporisation, au maximum huit tentatives consécutives. Le journal indique l’acceptation par le prestataire, pas une preuve de lecture ou de remise en boîte de réception. Une interruption entre acceptation réseau et sauvegarde locale peut provoquer un second e-mail ; la sécurité des factures est traitée séparément.

Les créations Qonto ont une clé d’idempotence stable, mais leur sûreté ne dépend pas de sa durée de vie de 30 minutes : une création incertaine est recherchée par l’UUID immuable `purchase_order` (ou par l’UUID de commande présent dans la description des articles pour un panier, et par `invoice_id` pour un ancien lien lié à une facture) ; aucune nouvelle création automatique n’est tentée si l’incertitude persiste. Un total non conforme laisse la facture en brouillon. Les règlements partiels et liens expirés demandent un contrôle administratif. Annuler le statut logistique ne crée ni avoir ni remboursement dans Qonto.

Les anciennes factures déjà créées ou en cours de création sont conservées et réutilisées. Une facture annulée n’est ni réémise ni envoyée. Les commandes sans facture utilisent le paiement préalable lors de leur traitement ; aucune ancienne commande non mise en file n’est relancée automatiquement.

## Activation dans chaque environnement

- **Brevo** : la connexion existante de la plateforme est réutilisée.
- **Factures Qonto** : identifiants API existants et `QONTO_IBAN` sur le service concerné.
- **TVA** : renseigner les taux applicables aux manuels et clés USB dans les réglages. Aucun taux fiscal n’est déduit de prix TTC ; une exonération exige un motif. Les taux sont figés avant la création du lien de paiement.
- **Paiement** : `QONTO_OAUTH_CLIENT_ID` et `QONTO_OAUTH_CLIENT_SECRET`, consentement comportant `payment_link.read` et `payment_link.write`, et prestataire de paiement actif dans Qonto. Le compte bancaire destinataire retourné par `/v2/payment_links/connections` doit appartenir à l’organisme de facturation retourné par `/v2/organization` avec la clé API ; aucun droit OAuth supplémentaire n’est nécessaire.
- Enregistrer dans l’application OAuth Qonto l’URL de retour propre à l’environnement, affichée dans les réglages : **`https://gestionstagiaires-test-v2.onrender.com/api/commerce/connexion-paiement/retour`** pour test-v2. Ce parcours ne modifie pas le retour OAuth historique du CRM vers la production.
- Les liens des e-mails utilisent `MANUALS_BASE_URL`, puis `RENDER_EXTERNAL_URL`, puis l’URL publique configurée.

La page d’administration distingue la présence de configuration d’un test de connexion réussi. Aucun test ne doit émettre de facture réelle fictive ou envoyer des messages de démonstration aux utilisateurs.

### Diagnostic et reprise des commandes (6 octobre 2026)

La liste et le détail administrateur affichent ensemble les prérequis manquants : TVA, identifiants/IBAN de facturation et autorisation des liens de paiement. Le lien client d’une commande ouvre désormais son détail administratif lorsqu’il est consulté par le super administrateur, au lieu de perdre la référence en revenant à la liste. Les clients voient un état d’attente d’activation explicite, sans accès aux réglages internes.

Le contrôle des factures accepte la devise dans `total_amount.currency`, conformément à la réponse documentée par Qonto ; le champ `currency` du payload de création n’est pas nécessairement renvoyé à la racine. Une devise absente, divergente ou autre qu’EUR bloque toujours la finalisation. Les tests de commerce utilisent ce format de réponse. Une autorisation de paiement manquante bloque la création du lien et de la facture ; la reprise ne crée pas de doublon.

Le parcours dédié aux manuels nécessite que son adresse de retour soit enregistrée dans l’application du portail développeur Qonto. Une erreur Qonto `invalid_request` mentionnant `redirect_uri` signifie que cette inscription manque ; un déploiement Render ne peut pas l’ajouter chez Qonto. Ne pas remplacer ce retour par celui de production, qui enregistrerait l’autorisation dans un autre environnement. Les droits nécessaires sont `client_invoices.read`, `payment_link.read` et `payment_link.write`.

## Vérification

- Tests du parcours, tarifs, isolation JSON/PG, reprise des factures, paiements et e-mails : `tests/test_manuals*.py`. Vérification finale ciblée (incluant OAuth, sécurité et partenaires) : **200 tests réussis, 14 sous-tests réussis**.
- Vérification navigateur locale en 1440 px et 390 px, inscription → accueil → e-learning → sélection → facture et lien simulés ; aucun débordement ni erreur JavaScript.
- Suite élargie effectuée sans réseau : 358 réussites, 10 tests ignorés, 14 sous-tests réussis avant les derniers tests OAuth ciblés. Quatre échecs historiques ont été reproduits sur le commit antérieur `a86c9c2` : facturation CPF externalisée, normalisation de paiement Qonto et deux tests de sessions anciennes. Ils ne sont pas modifiés dans cette évolution.

Références API officielles consultées : [factures](https://docs.qonto.com/api-reference/business-api/expense-management/client-quotes-notes/client-invoices/create-a-client-invoice), [liens de paiement Basket](https://docs.qonto.com/api-reference/business-api/payments-transfers/payment-links/create), [paiements confirmés](https://docs.qonto.com/api-reference/business-api/payments-transfers/payment-links/index-payments), [acquittement après règlement](https://docs.qonto.com/api-reference/business-api/expense-management/client-quotes-notes/client-invoices/mark-a-client-invoice-as-paid), [idempotence](https://docs.qonto.com/get-started/general/idempotent-requests).


## Présentation des manuels (octobre 2026)

Le bouton de l’accueil organisme et l’entrée « Manuels » ouvrent désormais `/admin/manuels/presentation`. Les six fiches `/admin/manuels/presentation/<code>` présentent les avantages, trois aperçus agrandissables, la personnalisation et les prix. Les actions de commande mènent au titre concerné dans le formulaire existant ; les liens de détails depuis ce formulaire s’ouvrent dans un autre onglet pour conserver la sélection.

Les textes et les 19 illustrations de `static/manuals/previews/` proviennent de la brochure « Brochure_Manuels_Tarifs_2026_corrigee.pdf » fournie le 4 octobre. Les images ont été extraites et converties en WebP ; les pages sont chargées à la demande. Les anciens nombres de leçons et la partie SST autrefois incluse dans le SSIAP 1 ne sont pas repris dans les descriptifs. Les prix des manuels restent exclusivement ceux de `CATALOGUE`, identiques au panier (notamment SSIAP 1 à 17 € dans les deux paliers).

Les nouvelles routes sont authentifiées et figurent dans l’allowlist des organismes. Le super administrateur peut consulter la présentation depuis « Commandes reçues » sans prendre l’identité d’un organisme. Cette consultation ne charge aucune commande et ne propose pas de validation d’achat.

Validation : 26 tests existants du parcours de commande réussis ; parcours présentation et six fiches contrôlé avec un organisme isolé, authentification, code inconnu (404), absence de droit d’administration, prix et images, puis consultation administrateur.

### Spécimens et formations sur mesure

Chaque carte de la collection donne accès au spécimen PDF, et chaque fiche propose la consultation dans un nouvel onglet ainsi que le téléchargement. Les liens du catalogue de commande ouvrent toujours la fiche dans un autre onglet pour conserver les quantités saisies.

Les fichiers `static/specimenaps.pdf`, `specimenssiap.pdf`, `specimensst.pdf`, `specimendssp.pdf` et `specimenvtc.pdf` reprennent sans modification les cinq spécimens fournis sur `main` le 6 octobre. `static/specimena3p.pdf` est une copie de démonstration du manuel A3P du 3 octobre (290 pages), avec filigrane sur chaque page, emplacements de logo et page d’accueil générique reprise du spécimen APS. Le manuel source reste inchangé. Les illustrations de cette copie sont allégées et le texte reste lisible et sélectionnable. L’association titre/fichier est centralisée dans `manuals_presentation.py`.

L’accueil organisme, la présentation et les fiches indiquent la possibilité de proposer des manuels pour tout type de formation. L’encart `/admin/manuels/presentation#sur-mesure` cite MAC APS, SSIAP 2, SSIAP 3 et habilitation électrique, avec un contact pour présenter un projet. Ces exemples ne créent pas de nouveaux articles ni de nouveaux tarifs dans le formulaire de commande.

Validation de cette évolution : six PDF lisibles et servis en `application/pdf`, requêtes partielles HTTP 206, six cartes et six fiches avec leurs liens corrects, téléchargement et rendu organisme/super administrateur. Les 26 tests existants du parcours de commande restent réussis.
