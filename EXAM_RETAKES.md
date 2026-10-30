# Rattrapages d’examen

Le bouton « Rattrapage » se trouve sur la fiche administrative du stagiaire, pour toutes les formations Intégrale. Le dossier conserve la fiche d’origine et une session d’accueil, sans créer d’inscription administrative supplémentaire.

## Parcours

1. Préparer la date d’examen, les éventuelles journées de préparation, les tarifs TTC et les gratuités indépendantes.
2. Enregistrer et consulter la convention PDF, puis envoyer en signature Yousign avec vérification SMS.
3. Après signature vérifiée auprès de Yousign, émettre la facture Qonto et un lien de paiement par carte, puis envoyer les documents par Brevo. Un dossier entièrement offert ne crée ni facture ni lien de paiement.
4. Après règlement intégral vérifié auprès de Qonto, afficher une ligne surlignée « Rattrapage examen » dans la session d’accueil. Cette ligne n’utilise ni la liste des inscrits ni les sélecteurs des compteurs/exportations ordinaires.
5. Afficher le suivi, les dates, les montants et les documents dans l’espace public authentifié du stagiaire d’origine.

La convention personnelle disponible est prioritaire sur le modèle actuel. Aucun tarif absent n’est inventé. En VTC pratique, le forfait du véhicule est distingué des frais CMAR ; en AFC et VAE, vérifier les conditions applicables avant une éventuelle facturation personnelle.

## Exploitation

- Persistance : `PERSIST_DIR/exam_retakes/retakes.sqlite3` et PDF privés dans le même répertoire. Inclure ce répertoire dans les sauvegardes du disque persistant.
- Le worker est démarré par `gunicorn.conf.py`, traite les dossiers en attente et reprend après redémarrage. Les webhooks authentifiés réveillent la file ; seule une lecture des API des prestataires valide la signature ou le paiement.
- Connexions existantes : Yousign, Brevo, Qonto avec IBAN et OAuth `client_invoices.read`, `payment_link.read`, `payment_link.write`. Le paiement par carte doit être activé dans Qonto. Aucun identifiant supplémentaire n’est stocké dans ce module.
- Une fois envoyé, le contenu contractuel est figé. Les opérations distantes sont journalisées avant émission, protégées par un verrou de dossier et récupérées par leur référence externe en cas de réponse incertaine.
- Les anomalies apparaissent dans la modale. « Actualiser le suivi » relance une vérification. Une création distante ambiguë ne provoque pas de seconde facture ou demande de signature ; une réponse e-mail incertaine au-delà de la fenêtre de déduplication nécessite de vérifier l’historique Brevo.

## Validation

42 tests propres au module couvrent tarifs des formations, dates, gratuités, signature, intégrité PDF, facturation et paiements partiels, reprise, accès aux documents, callbacks et exclusion des effectifs. Les API distantes sont simulées ; aucun test n’envoie de convention ou facture réelle.

Vérifications ciblées de régression : 122 tests réussis, 4 ignorés et 12 sous-tests réussis. Deux assertions préexistantes ont été reproduites sur le commit de référence puis exclues de ce contrôle : `test_cases_1_to_6_normalize` (surpaiement) et `test_trainee_dashboard_hides_schedule_until_mandate_is_validated` (ancienne chaîne JavaScript attendue). Rendu PDF vérifié et interactions du formulaire contrôlées sur un DOM de test ; le navigateur local n’est pas disponible dans l’environnement d’exécution.
