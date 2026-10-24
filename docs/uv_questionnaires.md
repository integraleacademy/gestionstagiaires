# Questionnaire de fin d’UV - Evaluation formative

Les formations initiales APS (dont le volet APS des sessions AFC) et A3P disposent respectivement de 13 et 8 questionnaires de 20 questions. Les UV SST sont exclues sans renuméroter les autres unités. Les autres formations, MAC et VAE, sont exclues. La structure reprend les programmes APS et A3P Intégrale Academy transmis le 24 octobre 2026. Il s’agit d’évaluations formatives, pas de sujets officiels ADEF ni d’épreuves certificatives.

## Accès et présentation

Le module n’est affiché que pour les sessions dont `date_start` est le 26/10/2026 ou une date ultérieure. Cette limite est aussi appliquée aux URL administratives, aux PDF et aux URL publiques. Une date individuelle ou de présentiel ultérieure n’active pas une ancienne session.

Le début du présentiel conditionne ensuite l’accès du stagiaire : date du présentiel APS, début individuel AFC, début de session A3P présentielle. Un APS sans date de présentiel reste fermé. Une inscription annulée ne peut pas répondre. Les blocs public et administrateur sont des accordéons fermés au chargement. La fiche administrative propose la prévisualisation et les PDF vierges, corrigés et complétés, sous authentification administrateur et dans le périmètre partenaire existant.

## Déroulement chronométré

Le stagiaire confirme sa présence en cours avec le formateur avant de commencer. Cette déclaration ne constitue pas une vérification technique de sa présence physique. Le serveur conserve une tentative sous `uv_questionnaire_attempts`, avec la version, l’index, les réponses validées et une échéance de 45 secondes pour la question affichée. Une seule question, sans réponse correcte ni explication, est transmise à la fois.

Recharger la page ne réinitialise pas le délai. À expiration, la question est enregistrée sans réponse ; la suivante dispose de 45 secondes dès sa mise à disposition. Une réponse arrivée après l’échéance n’est pas comptabilisée. Les requêtes concurrentes ou répétées ne remplacent pas une réponse déjà enregistrée. En cas de coupure réseau, la reprise se fait à partir de l’état conservé côté serveur.

Après la vingtième question, le score et la remise définitive sont enregistrés atomiquement sous `trainee.uv_questionnaires[course][uv]`. La correction expliquée devient alors accessible. Il n’existe pas de seuil de certification associé au score. Les PDF sont générés à la demande sans fichier public permanent.

## Maintenance des questions

`uv_questionnaires/20261024.json` conserve la banque initiale de 460 questions, options et explications pour la traçabilité. Les deux unités SST restent archivées dans cette banque mais ne sont ni affichées ni accessibles : 420 questions sont proposées. L’UV 6 A3P couvre anglais, cadre international, préparation, déplacements à pied, véhicules et communication.

Ne pas modifier une version déjà utilisée : créer un nouveau fichier daté et changer `VERSION`. Conserver les anciennes banques pour relire les remises et produire leurs corrigés fidèlement. Une tentative commencée continue avec sa version initiale.

Références pédagogiques : programmes fournis ; Code de la sécurité intérieure, livre VI et L613-2 ; Code de procédure pénale, article 73 ; Code pénal, articles 122-5 et 122-7 ; principes SST de l’INRS. Les questions de gestes pratiques renvoient aux techniques enseignées et à leur évaluation encadrée.

## Documents AFC et A3P

Les modèles AFC sont adaptés des modèles APS : convention avec règlement intérieur, attestations d’entrée et de fin. Leur en-tête, leurs signatures et leur identité visuelle sont conservés. Le financement figure dans la convention uniquement, sans dette de frais pédagogiques pour le stagiaire. Les convocations ne mentionnent ni financement ni RAN et n’utilisent plus le macaron SSIAP 1. Une durée individuelle non renseignée renvoie au programme individuel de formation dans les attestations.

Les trois attestations A3P ont des accents distincts : vert pour la fin, bleu pour conducteur d’autorité, terre cuite pour STU. Les deux phrases de réserve spécifiques aux attestations complémentaires ont été retirées à la demande de l’organisme. L’envoi manuel ou automatique génère les trois PDF avant l’envoi. Si l’un ne peut pas être généré, aucun courriel partiel n’est envoyé. Les deux attestations complémentaires disposent d’un aperçu dans la fiche administrative.
