# Intégrale Connect — évolution commerciale du 12 octobre 2026

## Fonctionnalités livrées

- Catalogue classé en cinq domaines, pages dédiées aux 14 USB et aux parcours e-learning disponibles.
- Fiches, métadonnées et tarifs des cours dérivés de la configuration existante. Un tarif absent reste « sur devis ».
- Panier local limité aux références/quantités, cloisonné par organisme et utilisateur, expiration 30 jours. Validation des quantités et prix toujours côté serveur. Le paiement reste le flux Qonto existant.
- Étapes sélection, coordonnées, récapitulatif ; panier fixe ; reprise d’une commande avec recalcul des prix.
- Récupération de mot de passe par lien signé de 30 minutes, lié au hash courant ; consommation atomique ; limitation des tentatives ; invalidation des anciennes sessions.
- Logos après commande ; BAT versionnés, empreinte SHA-256, validation/correction client ; contrôle du paiement et du BAT avant production ; suivi transporteur ; notifications transactionnelles avec état d’envoi et relance explicite des échecs.
- Conditions de vente versionnées et empreinte enregistrée dans les commandes manuels/USB et e-learning ; mentions et confidentialité publiques.
- Compteurs agrégés sans identifiant visiteur (90 jours), tableau commercial sur 30 jours ; aucune extension publicitaire.
- Images WebP, navigation mobile, contrastes, liens canoniques, métadonnées de partage, données Product, favicon, robots et sitemap.

## Contenus sources et limites

Les nouveaux extraits de huit pages proviennent des six manuels déposés : SSIAP 2, MAC APS, recyclage SSIAP 1, H0B0, BS-BE et MAC SST. Ils sont filigranés. Cela porte à 12 les spécimens disponibles. Les fichiers intérieurs SSIAP 3, recyclage SSIAP 2 et recyclage SSIAP 3 ne sont pas présents dans les sources accessibles ; leurs fiches restent liées à la brochure sans simuler d’intérieur. Aucun exemple PowerPoint authentique n’a été fourni : les fiches permettent de demander un aperçu. Ni grammage, ni reliure, ni délai standard, ni durée d’accès e-learning arbitraire n’ont été annoncés.

Les mentions de l’éditeur ont été vérifiées sur https://www.integraleacademy.com/mentions-l%C3%A9gales ; l’hébergeur de cet espace est Render (https://render.com/terms et https://render.com/dpa). Conservation comptable et information : https://www.cnil.fr/fr/passer-laction/les-durees-de-conservation-des-donnees. Paiements professionnels : https://entreprendre.service-public.gouv.fr/vosdroits/F23211.

## Réglages de mise en service

`MANUALS_PUBLIC_URL` doit être l’origine HTTPS canonique du domaine commercial effectivement raccordé. `MANUALS_INDEXABLE=true` autorise ensuite l’indexation de cette origine seulement. Les domaines `onrender.com`, localhost, test et preview restent exclus. Ne pas activer l’indexation ni changer les liens des e-mails avant le raccordement DNS/TLS effectif. `MANUALS_BASE_URL` gouverne les liens transactionnels existants.

Service actuel : `srv-d928tc19rddc7388qie0`, branche `test-v2`, disque `/var/data`, région Frankfurt. Le contrôle `/healthz` existe et doit être sélectionné comme Health Check Path dans les réglages Render de **ce service**. Le Blueprint historique vise un autre service : ne pas le synchroniser aveuglément sur test-v2. Le connecteur disponible ne permet pas cette mutation et le tableau de bord exige une connexion distincte.

Le disque impose un seul exemplaire de service et empêche le déploiement sans interruption. Ne pas détacher le disque pour contourner cette limite : il contient des données et fichiers clients. Une séparation vitrine/application ou une migration des fichiers vers un stockage objet demande un environnement distinct, une copie vérifiée et un basculement explicite. Aucun service payant ni déplacement de données clients n’est créé par cette évolution.

## Exploitation

Les BAT sont privés dans `partners/<id>/documents/manuals-bat`, les logos dans le répertoire existant. Inclure ces fichiers et `manuals-metrics.sqlite3` dans la sauvegarde du disque, en plus de JSON/PostgreSQL. Les états de paiement restent ceux vérifiés par Qonto. Une notification de suivi à état incertain ne doit pas être renvoyée sans vérifier Brevo, afin d’éviter un doublon.

Les conditions publiées dans `templates/manuals/legal/conditions_2026-10-12.html` sont immuables. Pour une prochaine version, ajouter un fichier et une entrée à `TERMS_TEMPLATES`, puis changer `TERMS_VERSION`. Ne pas réécrire le texte d’une version déjà acceptée.

## Validation

Tests de commerce et de sécurité exécutés avec e-mails et paiements simulés, en stockage JSON et PostgreSQL simulé. Le contrôle navigateur local couvre le mobile 320/390 px, le bureau 1440 px, l’intention conservée à l’inscription, la restauration du panier, l’erreur sous filtre, les trois étapes et la remise à zéro après confirmation. Les vérifications axe portent sur les pages publiques principales. Aucun paiement réel ni e-mail à un client réel n’est effectué pour cette vérification.

Les tests d’ouverture des cursus nécessitent les fichiers pédagogiques/vidéos du dépôt complet ; ils ne doivent pas être confondus avec un défaut de la boutique dans une extraction Git partielle.
