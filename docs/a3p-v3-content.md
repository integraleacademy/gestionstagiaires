# A3P : édition de contenus du 15 octobre 2026

Version : `20261015-a3p-v3-contenus`. Publication prévue sur `test-v2`.

Cette édition enrichit le parcours existant. Elle **ne permet pas encore de
présenter les 157 h 30 comme un volume pédagogique complet et calibré**.

## Contenus livrés

- Les 57 leçons éligibles au parcours à distance reçoivent des explications
  supplémentaires, un dossier professionnel et une correction argumentée.
- 66 dossiers, comprenant chacun trois pièces et quatre décisions, fournissent
  264 nouveaux choix corrigés. Neuf dossiers supplémentaires approfondissent
  l'évacuation, les décisions sous contrainte et l'analyse de signaux.
- Les réponses se donnent par clic. La correction est calculée par le serveur,
  sans exposer les réponses attendues dans le contenu public initial.
- Les 95 leçons du catalogue et les 245 questions des questionnaires existants
  sont conservées. Les ressources complémentaires, vidéos et objectifs à
  travailler en présentiel restent hors du volume à distance.
- Les éditions précédentes restent chargeables. Les affectations existantes
  conservent leur version et leur progression ; les nouvelles affectations
  utilisent cette édition.

Le lecteur conserve ses pages successives et ses minima de 1, 2 ou 5 minutes.
Ces minima ne représentent pas la durée totale d'apprentissage. Les estimations
ci-dessous n'attribuent aucun temps aux stagiaires et ne modifient pas les
conditions de comptabilisation du temps actif.

## Estimation détaillée et écart restant

L'estimation se calcule à partir du contenu disponible : étude du cours à
60 mots par minute ; lecture des pièces à 90 mots par minute ; deux minutes
par décision et une minute pour sa correction ; deux minutes par question du
QCM ; cinq minutes pour la synthèse. Les minima éditoriaux sont de cinq minutes
pour un cours ou un dossier et quatre minutes pour un QCM. Ce sont des
hypothèses de conception, sans essais auprès d'apprenants.

| Unité | Volume du parcours | Activités estimées | Écart positif par unité |
| --- | ---: | ---: | ---: |
| UV 02 – Cadre juridique et déontologie | 25 h | 6 h 57 | 18 h 03 |
| UV 03 – Gestion des conflits | 5 h | 4 h 16 | 44 min |
| UV 04 – Consignes et transmissions | 15 h | 4 h 26 | 10 h 34 |
| UV 05 – Prévention du risque terroriste | 7 h | 3 h 26 | 3 h 34 |
| UV 06 – Protection physique des personnes | 62 h | 13 h | 49 h |
| UV 07 – Techniques professionnelles et capacités | 10 h | 2 h 30 | 7 h 30 |
| UV 08 – Gestion des risques et situations dégradées | 33 h | 5 h 23 | 27 h 37 |
| UV 09 – Reconnaissance des blessures spécifiques | 30 min | 31 min | 0 min |
| **Total** | **157 h 30** | **40 h 29** | **117 h 02** |

La somme des écarts par unité ne compense pas un déficit par un excédent dans
une autre unité : UV 09 dépasse son repère d'une minute. La différence globale
arithmétique est de 117 h 01. Ces chiffres ne constituent ni une attestation
de durée ni une mesure du travail réel.

Le catalogue administratif affiche l'estimation et son statut incomplet. Le
rapport `/admin/elearning/calibrage/contenus` donne le détail par module,
séquence et activité. Les écarts les plus importants concernent UV 06, UV 08
et UV 02. Ils demandent encore des contenus substantiels, puis des essais
apprenants. Des attentes automatiques ou la répétition de questions identiques
ne constituent pas une réponse à cet écart.

## Vérification

- 24 tests Python réussis sur les contenus A3P, les routes d'aperçu et stagiaire,
  la correction, la sauvegarde des réponses, les protections CSRF, les éditions
  antérieures et les durées serveur.
- Huit tests DOM réussis : parcours guidé, reprise après erreur réseau,
  pagination des 219 leçons MAC APS/A3P/VTC, compte à rebours et déblocage sur
  confirmation du serveur.
- Les deux tests qui lisent les octets des vidéos sont exclus de cette copie
  de travail, limitée au code et aux textes. Les autres tests utilisent
  l'inventaire des médias déjà suivis par Git ; aucun média n'a été modifié.
- Ces vérifications portent sur le rendu HTML et le comportement DOM. Elles
  ne remplacent pas une revue visuelle dans un navigateur ni les essais
  pédagogiques auprès de stagiaires.

Commandes utilisées :

```sh
python - <<'PY'
import pytest
from tests.shared_reader_fixtures import published_media_inventory
with published_media_inventory():
    raise SystemExit(pytest.main([
        'tests/test_a3p_enrichment.py',
        'tests/test_native_elearning_a3p.py',
        'tests/test_shared_lesson_timing.py',
        '-q', '-k', 'not versions_and_media and not video_private_range',
        '--disable-warnings', '--maxfail=3',
    ]))
PY

# Nécessite jsdom dans NODE_PATH ou les dépendances locales.
node --test tests/test_shared_lesson_timing_ui.cjs tests/test_aps62_guided_ui.cjs
```
