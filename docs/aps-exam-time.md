# Temps des examens blancs APS — 14 octobre 2026

Les pages des 15 examens blancs de module n'ouvraient pas de session de suivi.
Seuls le résultat et la date de remise étaient enregistrés dans
`aps_exam_attempts`. Leur durée ne contribuait donc pas au module.

Chaque page utilise désormais le lecteur de suivi existant avec un accès signé
limité à l'examen de son module affecté. Les questions, la lecture du corrigé et
les nouvelles tentatives alimentent le même `active_seconds` que les cours.
La pause d'inactivité et la protection contre les onglets concurrents restent
contrôlées par le serveur. Le réglage APS est désormais de **10 minutes**.
Changer d'onglet ou perdre le focus ne suspend plus le compteur. Les retards
de heartbeat des onglets en arrière-plan sont comptés jusqu'à la dernière
échéance d'inactivité confirmée, jamais au-delà. Un reçu de lecture vidéo
valide constitue aussi une activité ; une vidéo masquée ne gagne aucune
progression de lecture et se met en pause.

Lors d'une navigation dans le même onglet (activité, examen ou autre module),
le serveur clôture la session précédente et conserve ses dernières secondes
dans le module d'origine avant d'ouvrir le nouveau suivi. Cela fonctionne même
si la requête de fermeture précédente est retardée ou perdue. Ses éventuelles
requêtes tardives ne comptent rien de plus. La fermeture du lecteur arrête le
suivi ; la page de présentation du parcours n'est pas chronométrée. Les autres
formations conservent leur propre délai de 5 minutes et leurs règles de focus.

Le budget reste inchangé : pour APS 01, 3 h 30 de cours et 30 minutes actives
d'examen atteignent les 4 heures. Le parcours, le lecteur, le suivi administratif
et les exports utilisent cette même progression. Une activité de suivi nommée
« Examen blanc du module · questions et corrigé » permet d'identifier l'examen
dans le suivi. Les réponses et les résultats de cours restent séparés des
tentatives d'examen. Aucune soumission n'attribue de durée forfaitaire.

La correction s'applique aux éditions APS déjà affectées qui possèdent ces
examens, sans migration ni nouvelle exigence de validation. L'aperçu
administrateur n'enregistre aucun temps. Les examens VTC, A3P et MAC APS
conservent leur fonctionnement.

## Examen blanc final et durée globale

L'examen final APS, ses corrections et ses nouvelles tentatives utilisent aussi
le suivi actif, avec un contexte séparé `academy-aps62-final` et l'activité
`aps62-final-examen-blanc`. Ce contexte n'est ni un seizième module à affecter,
ni un crédit appliqué aux quinze modules. Les durées obligatoires et les
conditions d'accès à l'examen final sont conservées : tous les modules complets
de la même édition et leurs durées doivent d'abord être terminés.

Le temps réel de l'examen s'ajoute au total du parcours. Ainsi, 62 h effectivement
enregistrées dans les modules et 1 h 30 dans l'examen donnent un total de 63 h 30.
Le parcours élève, les suivis des organismes (y compris les listes de groupes),
le relevé de connexions CSV et l'attestation PDF incluent cette durée une seule
fois. Le PDF détaille séparément les modules et l'examen. Un suivi administrateur
dédié, accessible depuis le catalogue APS, présente les trois valeurs et un
export CSV : `/admin/elearning/exams/final/time`.

La même protection contre les doublons et le même délai de 10 minutes
s'appliquent. Une navigation vers un cours clôture le suivi de l'examen et
conserve ses dernières secondes, sans les transférer au module. Les accès sont
signés, réservés au suivi de cet examen et revérifiés côté serveur. Les relevés
restent limités à l'organisme, au stagiaire et à l'édition affectée.

Les anciens temps d'examen ne peuvent pas être reconstitués de façon fiable :
aucun début, intervalle actif ni durée n'était enregistré. L'historique existant
est conservé. Les pages déjà ouvertes doivent être rechargées pour activer le
suivi nouvellement ajouté.

## Vérification ciblée

```bash
python -m pytest -q tests/test_aps_final_time.py tests/test_aps_exam_time.py tests/test_native_elearning_exams.py tests/test_native_elearning.py tests/test_native_elearning_video_presence.py -k 'APSFinalTimeTests or APSExamTimeTests or ExamWebTests or NativeTrackingTests or LongViewingPresenceTests or test_questions_balance_and_grading or test_retakes_idempotence_and_isolation'
python -m pytest -q tests/test_elearning_reporting.py tests/test_elearning_certificate_connections.py tests/test_native_elearning_tenant_exports.py
NODE_PATH=/path/to/node_modules node --test tests/test_native_elearning_exam_ui.cjs tests/test_native_elearning_player_ui.cjs
```

La suite couvre les 15 modules, les anciennes éditions disponibles, le passage
de 3 h 30 à 4 h, le décompte à 9 min 59 puis la pause à 10 min, la reprise,
les heartbeats retardés, la navigation avant réception de la fermeture, les
requêtes répétées, les onglets concurrents, le maintien du suivi sur le corrigé,
les exports, les droits d'accès, les aperçus et la conservation des réponses,
vidéos et résultats. Les tests utilisent des
apprenants fictifs et une base temporaire, sans modifier de dossier stagiaire.
