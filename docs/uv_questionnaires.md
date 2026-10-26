# Questionnaire de fin d’UV - Evaluation formative

Les formations initiales APS (dont le volet APS des sessions AFC) et A3P disposent respectivement de 13 et 8 questionnaires de 20 questions. Les UV SST sont exclues sans renuméroter les autres unités. Les autres formations, MAC et VAE, sont exclues. La structure reprend les programmes APS et A3P Intégrale Academy transmis le 24 octobre 2026. Il s’agit d’évaluations formatives, pas de sujets officiels ADEF ni d’épreuves certificatives.

## Accès et présentation

Le module n’est affiché que pour les sessions dont `date_start` est le 26/10/2026 ou une date ultérieure. Cette limite est aussi appliquée aux URL administratives, aux PDF et aux URL publiques. Une date individuelle ou de présentiel ultérieure n’active pas une ancienne session.

Le début du présentiel conditionne ensuite l’accès du stagiaire : date du présentiel APS, début individuel AFC, début de session A3P présentielle. Un APS sans date de présentiel reste fermé. Une inscription annulée ne peut pas répondre. Le bloc public est entièrement masqué tant que cet accès n’est pas ouvert. Les blocs public et administrateur sont des accordéons fermés au chargement. La fiche administrative affiche une ligne compacte par questionnaire et propose les PDF vierges, corrigés et complétés, avec le logo Intégrale Academy sur chaque page, sous authentification administrateur et dans le périmètre partenaire existant.

Le bouton **Tester le questionnaire** ouvre le même parcours chronométré en mode démonstration, y compris avant le début du présentiel. Les réponses de démonstration restent dans le navigateur ; aucun résultat, tentative ou note n’est écrit dans le dossier. Ce mode est réservé aux administrateurs et conserve les restrictions de formation, de date de session et d’UV.

## Déroulement chronométré

Le stagiaire confirme sa présence en cours avec le formateur avant de commencer. Cette déclaration ne constitue pas une vérification technique de sa présence physique. Le serveur conserve une tentative sous `uv_questionnaire_attempts`, avec la version, l’index, les réponses validées et une échéance de 45 secondes pour la question affichée. Une seule question, sans réponse correcte ni explication, est transmise à la fois.

Recharger la page ne réinitialise pas le délai. À expiration, la question est enregistrée sans réponse ; la suivante dispose de 45 secondes dès sa mise à disposition. Une réponse arrivée après l’échéance n’est pas comptabilisée. Les requêtes concurrentes ou répétées ne remplacent pas une réponse déjà enregistrée. En cas de coupure réseau, la reprise se fait à partir de l’état conservé côté serveur.

Après la vingtième question, le score et la remise définitive sont enregistrés atomiquement sous `trainee.uv_questionnaires[course][uv]`. La correction expliquée devient alors accessible. Il n’existe pas de seuil de certification associé au score. Les PDF sont générés à la demande sans fichier public permanent.

## Maintenance des questions

`uv_questionnaires/20261024.json` conserve la banque initiale de 460 questions, options et explications pour la traçabilité. Les deux unités SST restent archivées dans cette banque mais ne sont ni affichées ni accessibles : 420 questions sont proposées. L’UV 6 A3P couvre anglais, cadre international, préparation, déplacements à pied, véhicules et communication.

Ne pas modifier une version déjà utilisée : créer un nouveau fichier daté et changer `VERSION`. Conserver les anciennes banques pour relire les remises et produire leurs corrigés fidèlement. Une tentative commencée continue avec sa version initiale.

### Révision du 26 octobre 2026

La version active `20261026.json` conserve les 21 questionnaires accessibles, soit 420 questions : 13 UV APS et 8 UV A3P, toujours 20 questions par UV, 45 secondes par question et une seule bonne réponse. Les UV SST restent exclues. La banque du 24 octobre est conservée sans modification pour les tentatives commencées et les résultats antérieurs.

180 questions ont été réécrites : 8 dans chacune des 13 UV APS, 8 dans chacune des UV A3P 2, 3, 4, 5, 7, 8 et 9, et les 20 questions de l'UV 6 A3P. Les autres questions sont conservées. Les révisions introduisent des situations de mission, quatre propositions plausibles (deux pour le vrai/faux) et des corrections expliquant les limites de la bonne réponse. Les positions des bonnes réponses varient. Le champ `revised_in` identifie les questions révisées.

Les sept captures A3P fournies le 26 octobre sont reprises dans les questions 1 à 7 de l'UV 6 : définition et fonctions de S2, lecture des lieux par l'épaule, conciergerie, mallette triptyque, posture professionnelle face aux opinions politiques et porte à tambour. S2 est présenté comme la terminologie du dispositif étudié, pas comme une désignation universelle. L'usage de la porte latérale suppose un passage disponible, vérifié et coordonné. La question politique porte sur le prosélytisme en mission, sans inventer une interdiction légale générale de toute expression.

Les références consultées figurent dans `sources` de la nouvelle banque : fiche RNCP38002 de France compétences ; CSI L613-2, R631-9, R631-27 ; CPP article 73 ; prévention incendie et ATEX de l'INRS ; plan d'intervention SST ; consignes gouvernementales en cas d'attaque. Elles étayent les notions générales et ne rendent pas ces questions officielles. La formation pratique reste nécessaire, notamment pour les palpations, interventions physiques et gestes de secours.

Les tests de régression couvrent le contenu des deux versions, les choix à deux et quatre réponses, l'absence de corrigé transmis avant remise, la notation, la reprise d'une tentative du 24 octobre après activation de la nouvelle banque et ses corrigés historiques HTML/PDF. Les règles d'éligibilité, de présence déclarée et de remise définitive restent celles décrites ci-dessus.

La pagination des PDF vierges s'adapte à la hauteur des questions : chaque carte reste entière et le saut forcé après quatre questions est supprimé pour éviter une page presque vide lorsque les nouveaux choix occupent davantage de place.

Références pédagogiques : programmes fournis ; Code de la sécurité intérieure, livre VI et L613-2 ; Code de procédure pénale, article 73 ; Code pénal, articles 122-5 et 122-7 ; principes SST de l’INRS. Les questions de gestes pratiques renvoient aux techniques enseignées et à leur évaluation encadrée.

## Documents AFC et A3P

Les modèles AFC sont adaptés des modèles APS : convention avec règlement intérieur, attestations d’entrée et de fin. Leur en-tête, leurs signatures et leur identité visuelle sont conservés. Le financement figure dans la convention uniquement, sans dette de frais pédagogiques pour le stagiaire. Les convocations ne mentionnent ni financement ni RAN et n’utilisent plus le macaron SSIAP 1. Une durée individuelle non renseignée renvoie au programme individuel de formation dans les attestations.

Les trois attestations A3P ont des accents distincts : vert pour la fin, bleu pour conducteur d’autorité, terre cuite pour STU. Les deux phrases de réserve spécifiques aux attestations complémentaires ont été retirées à la demande de l’organisme. L’envoi manuel ou automatique génère les trois PDF avant l’envoi. Si l’un ne peut pas être généré, aucun courriel partiel n’est envoyé. Les deux attestations complémentaires disposent d’un aperçu dans la fiche administrative.

Les PDF conducteur d’autorité et STU figurent aussi dans **Mes diplômes et attestations** de l’espace A3P. Ils sont accessibles au stagiaire authentifié dès leur génération ou la délivrance de l’attestation de fin. Pour les anciens dossiers terminés, un document complémentaire manquant est généré au premier téléchargement, sans nouvel e-mail. Les inscriptions annulées sont exclues.

Les sessions AFC proposent quatre actions groupées dans la liste des stagiaires : générer ou envoyer les conventions, générer ou envoyer les convocations. Un écran présente les dossiers admissibles, les exclusions et un aperçu PDF avant exécution. Chaque dossier est traité et enregistré séparément ; une erreur ne fait pas perdre les autres résultats. Les conventions sont envoyées par lien de signature, les convocations en pièce jointe. Les générations seules n’envoient aucun message et ne créent aucune demande de signature. Les conventions signées ou déjà envoyées, les convocations déjà envoyées et les inscriptions annulées sont exclues. Une opération dont le résultat d’envoi est incertain reste bloquée pour vérification dans la fiche ; elle n’est pas relancée automatiquement. Les données et dates individuelles sont recontrôlées avant chaque action.

Les coupures réseau et les réponses HTML temporaires pendant un redémarrage déclenchent une reprise automatique pendant trois minutes, avec le même identifiant d’opération. Au-delà, le bouton **Reprendre le traitement** conserve les dossiers terminés et l’identifiant du dossier en attente. Une authentification expirée demande de se reconnecter ; un jeton CSRF perdu est renouvelé sans changer les documents approuvés. Les PDF déjà préparés sont conservés tant que leur contenu est à jour et leur fichier existe.

La clé d’envoi transmise à Brevo est un UUID de 36 caractères, stable pour une même opération et distinct entre documents, conformément à son [contrat d’idempotence](https://developers.brevo.com/docs/heterogenous-versions-batch-emails). Les anciennes clés préfixées étaient refusées avant envoi. Après cette erreur, fermer puis rouvrir **Envoyer toutes les conventions** permet de relancer les dossiers : les demandes Yousign actives sont réutilisées et les envois déjà réussis restent exclus. Les tests traversent le véritable adaptateur e-mail, avec un fournisseur simulé qui refuse les clés trop longues ou non UUID, pour des lots de 12 conventions et convocations.

Un verrou fichier par dossier et document protège le traitement entre threads et processus du service à disque persistant. Le système libère ce verrou à l’arrêt du processus : une préparation interrompue peut alors reprendre. Les étapes précédant les appels Yousign et e-mail sont enregistrées avant leur exécution. Si le serveur s’arrête pendant un appel externe, son résultat est déclaré incertain et aucun envoi automatique supplémentaire n’est lancé. Les tests `test_afc_bulk_documents.py` et `test_afc_documents_ui.cjs` couvrent les redémarrages, réponses perdues, renouvellements CSRF et reprises sans doublons.
