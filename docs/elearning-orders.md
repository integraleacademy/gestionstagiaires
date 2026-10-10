# Commandes e-learning des organismes

## Utilisation

- Organisme : `/admin/organisme/e-learning`, tableau de bord des groupes et accès individuels. Créer un groupe nommé (même vide) ou un accès individuel, puis compléter et enregistrer la liste au fil des connexions.
- Chaque participant non commandé peut être modifié ou supprimé. « Créer les espaces e-learning » enregistre la liste puis affiche un récapitulatif et l’adresse de facturation. La confirmation crée une commande à régler, sans activation avant vérification du paiement.
- Les participants déjà commandés restent liés à leur commande et ne sont plus modifiables. Le centre peut ajouter de nouvelles personnes à un groupe : la commande suivante ne facture que ces nouveaux participants. Un groupe accepte jusqu’à 100 personnes ; un accès individuel n’en accepte qu’une.
- Les brouillons n’ont aucun délai de paiement. Les récapitulatifs sont signés et valables 24 heures ; un changement de tarif ou de liste demande une nouvelle confirmation. Une révision protège les modifications simultanées dans plusieurs onglets.
- Administration : `/admin/commandes-elearning`, sélection d'un partenaire, prix TTC par personne et case Gratuit indépendante pour APS et VTC. Un prix vide désactive la commande de ce parcours, sauf gratuité.
- Le tarif APS initial reprend les 59 € déjà affichés dans l'espace organisme. Le tarif VTC doit être défini par l'administrateur.
- Renseigner la TVA e-learning dans les réglages de facturation existants avant la première commande payante. La connexion Qonto, l'IBAN et l'autorisation de paiement restent ceux de la plateforme marchande.

## Paiement et livraison

Une commande payante émet sa facture Qonto avant le paiement. Le traitement vérifie la référence, le client, la devise et le montant de la facture. Un retour navigateur ou un montant envoyé par le formulaire ne débloque jamais un accès. Le statut payé, le paiement intégral et un solde nul sont nécessaires. Une commande gratuite utilise le tarif accordé par l'administrateur à la confirmation, sans Qonto.

La file durable existante des commandes traite aussi les commandes e-learning. Une facture impayée est normalement vérifiée toutes les 60 secondes, ou toutes les cinq minutes si elle nécessite une intervention. Le centre peut actualiser le suivi ; l'administrateur peut relancer le traitement. Les commandes sans configuration de facturation reprennent après enregistrement des réglages.

Le centre reçoit sa confirmation et ses factures PDF. Chaque stagiaire reçoit un e-mail HTML avec son lien personnel seulement après activation. Les envois réussis sont mémorisés ; les échecs sont relancés sans recréer de facture ni d'accès. Comme tout envoi sans transaction commune avec le fournisseur d'e-mail, une interruption entre la livraison Brevo et l'enregistrement local peut exceptionnellement provoquer un doublon.

## Données et accès

Les commandes utilisent la collection existante `manual_orders` avec `order_type: elearning`, conservant l'isolation par partenaire en JSON et PostgreSQL. Les groupes persistants utilisent `order_type: elearning_group` et restent en statut `draft`, sans file marchande ni droit d’accès. Chaque commande confirmée est un instantané indépendant lié par `group_id`, avec les identifiants stables des participants. Aucun champ de stockage ni migration supplémentaire n’est nécessaire. Les écrans et routes des commandes de supports ignorent ces commandes. Les factures sont mises en cache dans le stockage `factures` du partenaire par le traitement marchand.

Les programmes natifs APS 62 h et VTC 105 h sont figés à la version présente lors de la commande. Les personnes utilisent des sessions virtuelles dédiées, sans inscription dans les sessions administratives habituelles. L'accès et la progression passent par le moteur e-learning natif existant. Les partenaires suspendus et les commandes dont le droit d'accès a été retiré localement ne sont plus autorisés.

Le lien personnel utilise une signature HMAC du secret applicatif et des identifiants de commande/personne. Seul le condensat est stocké. Conserver le secret Flask existant lors des redéploiements ; une rotation nécessite une procédure de réémission des accès. Les pages contenant ces liens interdisent le cache et l'envoi du référent.

## Vérification

`python -m pytest tests/test_elearning_groups.py tests/test_elearning_orders.py tests/test_manuals_shop.py tests/test_manuals_commerce.py -q`

La suite couvre les paiements incomplets, la gratuité, les doubles confirmations, les relances d'e-mails, les prix falsifiés, les changements de tarif, l'isolation des organismes et l'ouverture effective des deux parcours natifs. Qonto et Brevo sont simulés : elle n'émet aucune facture réelle et n'envoie aucun e-mail réel.

