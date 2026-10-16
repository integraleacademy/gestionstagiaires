# VTC v6 — 10 octobre 2026

Cette édition réduit la charge obligatoire et sépare les variantes facultatives. Elle conserve les éditions v1 à v5 et leurs résultats : aucune migration d’affectation ni de suivi n’est exécutée. Les nouvelles affectations utilisent `20261010-vtc-v6-pedagogie`.

## Contenu

- 1 279 exercices au maximum (1 979 auparavant), 1 809 décisions élémentaires ; 1 064 exercices complémentaires accessibles sans progression ni temps supplémentaire.
- 96 cours, 96 dossiers, 16 missions et les 48 écoutes conservés. 371 variantes de contexte/support retirées en v5 sont restaurées, distinctes des copies strictes.
- A.06 : sanctions et interlocuteurs ; A.07 : distinctions entre comportements et consentement ; B.01 : sept cas comparant EI, EURL, SASU, régimes et trésorerie ; douze approfondissements G spécifiques.
- 100 situations finales originales et 30 questions d’anglais originales ; réponses d’examen mélangées par tentative, stables pendant une reprise. Les examens pédagogiques ne reproduisent pas le format complet ni les coefficients de l’examen officiel.
- Les 404 questions d’annales et leurs 552 notes dans les cours restent inchangées.

## Révision et accès

Une révision garde les compétences insuffisamment démontrées. Deux situations distinctes réussies dès le premier essai parmi les activités antérieures terminées permettent une révision allégée. Au moins quatre contrôles sont conservés. La sélection est recalculée côté serveur à l’affichage, à la correction et à la validation ; les choix envoyés par le navigateur ne déterminent pas la sélection.

La banque libre n’écrit ni progression, ni temps, ni résultats d’examen. Les choix restent dans l’onglet. Elle respecte les modules/leçons attribués et conserve la version des autorisations de médias. Pour les éditions v1/v2 dépourvues de ces fichiers audio, les dialogues et traductions sont proposés à l’écrit.

## Durées et affectations

Les 5 422 minutes (90 h 22) sont une estimation initiale du parcours principal avant réduction adaptative, pas un temps mesuré ni une garantie. Les calculs sont détaillés dans `elearning_native/vtc/programme_pedagogie.json`. Les estimations de lecture et vidéo existantes sont conservées ; les pratiques sont recalculées selon leur contenu. Aucun temps actif artificiel n’est ajouté. Le paramétrage d’affectation continue de proposer des durées modifiables, enregistrées seulement lors de la sauvegarde par l’administrateur. Les affectations déjà enregistrées restent inchangées.

Un pilote avec de vrais stagiaires reste nécessaire pour mesurer durée, difficulté, compréhension et abandon. Le suivi existant permet de relever premières erreurs et temps actif ; aucune efficacité pédagogique n’a été présumée à partir des seuls tests logiciels.

## Reproduction et validation

Depuis la racine du dépôt :

```
python scripts/vtc/revision_v6/build_courses.py
python scripts/vtc/revision_v6/exams.py
```

Les générateurs n’écrivent que la nouvelle édition, ses compléments et le manifeste courant. Le programme historique de 105 h est conservé séparément.

Validation locale : 106 tests Python et 32 tests JavaScript réussis ; 336 activités v6 et 115 pages libres rendues sans erreur ; essai navigateur sur ordinateur et mobile, correction, reprise, audio, sélection adaptative et menu clavier. Les empreintes des 85 fichiers cours/examens v1–v5 sont inchangées. Le contrôle historique de métadonnées des huit MP4 n’a pas été relancé : `ffprobe` est absent de l’environnement local. Aucun média vidéo n’est modifié par cette version.
