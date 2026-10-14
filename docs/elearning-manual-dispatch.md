# Envoi des accès à l’initiative du centre

Le règlement intégral vérifié rend les accès disponibles à l’envoi. Il ne crée plus de nouveaux accès actifs et ne déclenche plus d’e-mail aux stagiaires. Le centre utilise le bouton « Envoyer les accès e-learning aux stagiaires », dans sa commande ou dans le groupe correspondant. La règle concerne APS, MAC APS et VTC. Une commande gratuite confirmée utilise le même bouton, sans paiement à effectuer.

La demande passe par un POST protégé par CSRF et réservé au centre propriétaire, avec un rôle autorisant les modifications. L’éligibilité est revérifiée côté serveur : un paiement partiel, une commande annulée ou une annulation en cours ne permettent pas l’envoi. Les nouvelles commandes ajoutées à un groupe ont leur propre règlement et leur propre demande d’envoi.

Le clic conserve `access_dispatch_requested_at` et `access_dispatch_requested_by` dans la commande, puis réveille le traitement existant. Le traitement active les accès et envoie les messages au nom du centre. Les clés d’envoi existantes évitent de renvoyer les messages déjà réussis. Les échecs sont réessayés. Un clic pendant la finalisation du paiement reste en attente durable sans interrompre le traitement en cours ; la réservation de traitement est libérée à sa fin.

Les accès précédemment activés, leurs liens et les historiques pédagogiques sont conservés. Les anciens messages non envoyés demandent désormais une action du centre. Les confirmations de commande et factures adressées au centre conservent leur fonctionnement, avec des explications mises à jour. La suspension des nouvelles ventes ne bloque pas l’envoi d’une commande déjà confirmée et réglée.

## Vérification du 14 octobre 2026

208 tests Python réussis sur les commandes, groupes, paiements simulés, permissions, envois, suivi, documents et identité du centre ; 14 tests JavaScript réussis. Deux tests du lecteur VTC sont exclus car les médias binaires de cette copie de travail partielle ne sont pas présents. Les nouveaux tests de paiement et d’envoi couvrent bien APS, MAC APS et VTC, dans les deux modes de stockage des fixtures.

Les vérifications utilisent des données fictives et des substituts Qonto/Brevo : aucune facture ni aucun e-mail réel n’est créé par les tests. Après publication, contrôler les écrans existants en lecture seule, sans déclencher d’envoi réel.
