# Temps des examens blancs APS — 14 octobre 2026

Les pages des 15 examens blancs de module n'ouvraient pas de session de suivi.
Seuls le résultat et la date de remise étaient enregistrés dans
`aps_exam_attempts`. Leur durée ne contribuait donc pas au module.

Chaque page utilise désormais le lecteur de suivi existant avec un accès signé
limité à l'examen de son module affecté. Les questions, la lecture du corrigé et
les nouvelles tentatives alimentent le même `active_seconds` que les cours.
Les pauses d'inactivité, la visibilité, la fermeture de page et la protection
contre les onglets concurrents restent contrôlées par le serveur habituel.

Le budget reste inchangé : pour APS 01, 3 h 30 de cours et 30 minutes actives
d'examen atteignent les 4 heures. Le parcours, le lecteur, le suivi administratif
et les exports utilisent cette même progression. Une activité de suivi nommée
« Examen blanc du module · questions et corrigé » permet d'identifier l'examen
dans le suivi. Les réponses et les résultats de cours restent séparés des
tentatives d'examen. Aucune soumission n'attribue de durée forfaitaire.

La correction s'applique aux éditions APS déjà affectées qui possèdent ces
examens, sans migration ni nouvelle exigence de validation. L'aperçu
administrateur n'enregistre aucun temps. Les examens VTC, A3P, MAC APS et
l'examen final transversal conservent leur fonctionnement.

Les anciens temps d'examen ne peuvent pas être reconstitués de façon fiable :
aucun début, intervalle actif ni durée n'était enregistré. L'historique existant
est conservé. Les pages déjà ouvertes doivent être rechargées pour activer le
suivi nouvellement ajouté.

## Vérification ciblée

```bash
python -m pytest -q tests/test_aps_exam_time.py tests/test_native_elearning_exams.py tests/test_native_elearning.py -k 'APSExamTimeTests or ExamWebTests or NativeTrackingTests or test_questions_balance_and_grading or test_retakes_idempotence_and_isolation'
NODE_PATH=/path/to/node_modules node --test tests/test_native_elearning_exam_ui.cjs tests/test_native_elearning_player_ui.cjs
```

La suite couvre les 15 modules, les anciennes éditions disponibles, le passage
de 3 h 30 à 4 h, la reprise, les pauses, les requêtes répétées, les onglets
concurrents, le maintien du suivi sur le corrigé, les droits d'accès, les aperçus
et la conservation des réponses, vidéos et résultats. Les tests utilisent des
apprenants fictifs et une base temporaire, sans modifier de dossier stagiaire.
