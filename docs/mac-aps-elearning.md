# Parcours pédagogique MAC APS

Édition `20261012-macaps-v1`. Catalogue : `/admin/elearning/mac-aps`.

## Contenu et usage

Le parcours comprend cinq modules : premiers secours, principes de la République,
cadre juridique et déontologie, gestion des conflits et filtrage, prévention des
risques terroristes. Ses 28 chapitres suivent quatre étapes : comprendre le cours,
prendre trois décisions dans une situation professionnelle, répondre à trois
questions, puis retrouver la fiche de révision. Les exercices sont à choix
cliquables, sans production écrite demandée au stagiaire.

Les cinq synthèses vidéo originales utilisent la voix française Henri, des
illustrations et des schémas progressifs, des sous-titres incrustés et des pistes
WebVTT. Chaque vidéo contient au moins cinq minutes de narration réelle ; le
script de fabrication refuse d'atteindre cette durée en ajoutant du silence.
Les durées, les chapitres, les transcriptions et les empreintes de fichiers sont
conservés dans `elearning_native/mac_aps/media_manifest.json`.

Les examens blancs comportent 30 questions par module et 100 questions finales
distinctes, soit 250 questions, en plus des 84 questions de cours et des 84
décisions en situation. Les réponses sont corrigées côté serveur. Le seuil
de 80 % est pédagogique. Les examens blancs ne créditent ni temps, ni présence,
ni achèvement du stage réglementaire.

## Affectation et progression

La formation `MAC APS` est disponible dans les types de session. Depuis le
catalogue, ouvrir le composeur de la session, ajouter le parcours MAC APS complet,
adapter les durées pédagogiques indicatives, puis enregistrer. L'ajout complète
la sélection existante sans effacer les autres modules. Aucune session réelle
n'est affectée par la simple ouverture du catalogue ou d'un aperçu.

Le parcours utilise le moteur natif : accès individuel à partir de la date de
début, versions conservées, reprise des réponses, suivi du temps actif, nouvelles
tentatives, contrôle du visionnage requis et ouverture progressive des modules.
Les durées affichées dans le lecteur sont des estimations pédagogiques, ajustables
dans le composeur. Elles ne sont jamais transformées automatiquement en heures
effectuées. L'examen final stagiaire nécessite les cinq modules complets de la
même édition et leur achèvement. L'administrateur peut le prévisualiser librement.

Les médias passent par les URLs signées et les contrôles d'accès existants.
Les aperçus administrateur n'ouvrent pas de session de suivi stagiaire. Le
catalogue propose le suivi des stagiaires et les outils d'export existants.

## Cadre réglementaire vérifié le 12 octobre 2026

L'article 4 de l'[arrêté du 27 février 2017](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000034104578/)
fixe les durées de référence : 7 h de premiers secours, 3 h de principes de la
République, 4 h de cadre juridique, 7 h de conflits/filtrage et 13 h de prévention
des risques terroristes, soit 34 h. La dispense documentée des 7 h de secourisme
général, dans les conditions de cet article, ramène le stage à 27 h. Elle ne
supprime pas le secourisme tactique et les autres objectifs de secours du module
terrorisme. Le positionnement initial prévu par cet article comporte dix questions
à réponse courte, distinctes des QCM d'entraînement. Des repères sont proposés au
formateur dans le catalogue ; la réalisation du positionnement reste à organiser.

L'[arrêté du 27 janvier 2025](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000051058748/)
ouvrait certains objectifs au distanciel jusqu'au 31 décembre 2025 inclus.
Aucune prorogation officielle pour 2026 n'a été trouvée lors de cette vérification.
L'[article 8 de l'arrêté du 23 octobre 2024](https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000050400272)
encadre l'organisation des objectifs éligibles au distanciel ; il ne rend pas
automatiquement tous les objectifs MAC APS éligibles.

Cette édition constitue donc un support pédagogique de formation et de révision.
Le lecteur ne délivre ni attestation réglementaire MAC APS ni certification SST.
L'organisme conserve la responsabilité du stage, du positionnement, des
justificatifs de dispense et des séquences pratiques. La qualification des
activités numériques n'est pas déduite de leur durée de connexion.

Les cours citent leurs sources officielles. Ils intègrent notamment la rédaction
2026 de l'[article L. 613-2-1 du CSI](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000054718795)
sur l'inspection visuelle des véhicules et les trois stades du nouveau
[plan Vigipirate](https://www.sgdsn.gouv.fr/vigipirate).

## Fichiers et vérification

- `elearning_native/mac_aps.py` : chargement versionné, parcours, examens et accès aux médias.
- `elearning_native/mac_aps/lessons.json` : les 28 chapitres et leurs exercices corrigés.
- `elearning_native/mac_aps/exams.json` : les 250 questions d'examens blancs.
- `elearning_native/mac_aps/regulatory_review.json` : périmètre, sources et repères pour le formateur.
- `scripts/mac_aps_content.py` : génération reproductible des leçons.
- `scripts/render_mac_aps.py` : narration, écrans, sous-titres et contrôle des médias.
- `.github/workflows/mac-aps-media.yml` : production isolée sur la branche MAC APS, sans publication directe sur TEST.

Vérification avant publication, avec les médias existants du dépôt présents :

```bash
MACAPS_REQUIRE_MEDIA=1 python -m pytest tests/test_native_elearning.py tests/test_native_elearning_web.py tests/test_native_elearning_mac_aps.py -q
python scripts/render_mac_aps.py --merge --verify
git diff --check
```

Les contrôles MAC APS couvrent le contenu, les banques de questions, la correction,
les versions, les accès administrateur/stagiaire, les protections CSRF, l'absence
de suivi en aperçu, les tentatives incorrectes, les prérequis, les médias et les
réponses HTTP partielles nécessaires à la lecture vidéo. La vérification visuelle
complémentaire porte sur le catalogue et le lecteur sur ordinateur et téléphone.
