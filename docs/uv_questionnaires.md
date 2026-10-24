# Questionnaires de fin d’UV

Les formations initiales APS (dont le volet APS des sessions AFC) et A3P disposent respectivement de 14 et 9 questionnaires de 20 questions. Les autres formations, MAC et VAE sont exclus. La structure reprend les programmes APS et A3P Intégrale Academy transmis le 24 octobre 2026. Il s’agit de questionnaires pédagogiques de connaissances, pas de sujets officiels ADEF ni d’épreuves certificatives.

Le module `uv_questionnaires.py` détermine l’accès côté serveur : date du présentiel APS, début individuel AFC, début de session A3P présentielle. Un APS sans date de présentiel reste fermé. Une inscription annulée ne peut pas répondre. Le rappel de réalisation pendant les cours et en présence du formateur apparaît dans l’espace public, sur le formulaire et dans les PDF. Le stagiaire confirme cette condition ; cette déclaration ne constitue pas une vérification technique de sa présence physique.

Les corrections sont retirées des données de la page publique avant remise. Après validation des 20 réponses, le serveur calcule le score et enregistre atomiquement une remise définitive sous `trainee.uv_questionnaires[course][uv]`, avec la version, les réponses, le score, l’horodatage et la confirmation. Un second envoi conserve la première remise. Il n’existe pas de seuil de certification associé à ce score.

La fiche administrative propose la prévisualisation et les PDF vierges, corrigés et complétés. Ces routes nécessitent une connexion administrateur et utilisent la recherche de session avec le périmètre partenaire existant. Les PDF sont générés à la demande sans fichier public permanent.

## Maintenance des questions

`uv_questionnaires/20261024.json` contient les 460 questions, options et explications. Les thèmes juridiques et opérationnels reprennent en partie les contenus pédagogiques internes APS62/A3P existants. Les thèmes incendie, surveillance, bagages, surveillance électronique, prévention, conflits dégradés et SST ont été complétés. L’UV 6 A3P couvre anglais, cadre international, préparation, déplacements à pied, véhicules et communication.

Ne pas modifier une version déjà utilisée : créer un nouveau fichier daté et changer `VERSION`. Conserver les anciennes banques pour relire les remises et produire leurs corrigés fidèlement. Le formulaire refuse une remise issue d’une ancienne version après changement de banque.

Références vérifiées pour les principes employés : programmes fournis ; Code de la sécurité intérieure, livre VI et L613-2 ; Code de procédure pénale, article 73 ; Code pénal, articles 122-5 et 122-7 ; principes SST de l’INRS. Les questions de gestes pratiques renvoient aux techniques enseignées et à leur évaluation encadrée.

## Documents liés

Le parcours AFC utilise ses propres modèles de convention, convocation, entrée et fin, sans reste à charge stagiaire. Le volume individualisé reprend les composantes déjà configurées dans `afc_hours` et le profil RAN du dossier. Une RAN non renseignée reste explicitement à préciser selon le PIF.

L’envoi manuel ou automatique de l’attestation de fin A3P initiale génère les attestations de conducteur d’autorité et STU avant l’envoi. Si l’un des trois PDF ne peut pas être généré, aucun courriel partiel n’est envoyé. Les deux attestations complémentaires disposent d’un aperçu dans la fiche administrative. Les autres formations conservent leur envoi habituel.
