# Lecture et contrôle des durées : APS, MAC APS, A3P et VTC

Révision du lecteur : `20261015-all-reading-125`.

## Fonctionnement commun

Les lecteurs conservent les étapes Précédent / Suivant, la reprise, les liens
internes, le lecteur vidéo, les exercices et les couleurs de leur formation.
Les pages de cours MAC APS, A3P et VTC utilisent désormais le même contrôle
serveur des secondes de lecture que les pages APS : 1 minute pour les repères
courts, 2 minutes pour une explication et 5 minutes pour une page dense.

Le plan est construit à partir des fragments réellement affichés, y compris
le découpage des paragraphes VTC. Aucun nombre de pages, temps obligatoire ou
temps acquis envoyé par le navigateur ne fait autorité. Les identifiants des
nouvelles pages dépendent de leur texte, afin de ne pas réattribuer du temps
à une autre page si un contenu est ensuite déplacé ou remplacé. Les plans APS
et leurs identifiants existants sont conservés.

Le compte à rebours anime l’attente ; seul un reçu serveur débloque la page.
Les ancres et les requêtes directes ne permettent pas de sauter cette lecture.
Les vidéos obligatoires conservent leur contrôle de visionnage ; elles ne
reçoivent pas une deuxième attente de lecture. Les vidéos complémentaires
restent facultatives. L’aperçu administrateur reste libre et ne crée pas de
progression. Les activités déjà terminées restent relisibles sans nouveau
blocage. Les secondes par page ne s’ajoutent pas une deuxième fois au total.

Les ressources de préparation au présentiel A3P et les compléments MAC APS
restent dans leurs espaces de consultation, hors des totaux du parcours.
Les ateliers facultatifs VTC, les examens, les affectations et les règles
commerciales ne sont pas modifiés.

## Audit de contenu

Le lien « Vérifier les contenus et les durées » est disponible en haut des
quatre catalogues. La page `/admin/elearning/calibrage/contenus` présente les
34 modules courants : volumes de lecture, minimum des pages, vidéos obligatoires,
questions, exercices interactifs et budgets des séquences. Elle ne lit aucune
donnée stagiaire et ne produit aucune attestation de durée.

Constat du 15 octobre 2026, sur les activités principales actuelles :

| Parcours | Durée affichée | Leçons | Pages | Mots affichés | Minimum des pages |
| --- | ---: | ---: | ---: | ---: | ---: |
| APS | 62 h | 62 | 648 | 117 517 | 1 290 min |
| MAC APS | 14 h | 28 | 184 | 26 616 | 312 min |
| A3P, périmètre à distance | 157 h 30 | 57 | 270 | 45 328 | 474 min |
| VTC | 105 h | 96 | 1 871 | 116 278 | 2 068 min |

Le nombre de mots comprend les repères répétés des pages. Il ne mesure ni
le nombre de notions nouvelles ni le temps effectif d’apprentissage. Les vidéos,
exercices, applications et examens sont à examiner séparément.

### Écart A3P à traiter

Les 228 activités à distance ne possèdent pas de budget détaillé par séquence.
Les 57 cours et 167 questions existants, les exemples et les synthèses ne
justifient pas à eux seuls les 157 h 30 affichées. Les huit vidéos de synthèse
sont actuellement des compléments, exclus du temps obligatoire à distance.
Le rapport signale chaque module comme nécessitant enrichissement et calibrage.
Cette livraison n’invente pas un budget en multipliant les attentes et ne
présente pas A3P comme pédagogiquement validé.

Priorités de reprise : objectifs précis, cours développés, exemples commentés,
documents à analyser et exercices à choix fermé, puis essais avec plusieurs
profils. Aucun nouvel exercice de rédaction n’est ajouté. Les séquences
présentielles ne doivent pas être comptées dans le volume à distance.

### MAC APS et VTC

Les budgets par activité existent pour MAC APS et VTC. Cela ne suffit pas à
prouver leur durée réelle : prévoir des essais apprenants. Le rapport identifie
aussi les 878 minutes du budget VTC associées aux productions facultatives,
afin de calibrer le parcours lorsqu’elles ne sont pas réalisées.

## Vérifications

Les tests utilisent des stagiaires fictifs. Les 219 leçons MAC APS/A3P/VTC sont
rendues et paginées dans le DOM réel pour comparer leurs pages au plan serveur.
Les tests API vérifient les trois parcours : blocage anticipé, sauts, reprise,
validation après lecture et conservation d’une ancienne activité terminée.
Les contrôles APS existants restent applicables. Dans une copie de travail
sans fichiers médias, les tests de texte utilisent uniquement leur présence
dans l’inventaire Git ; ils ne prétendent pas valider les octets vidéo.

Validation ciblée : 28 tests Python et 16 sous-tests réussis ; contrôle DOM de
toutes les leçons et du déblocage confirmé par le serveur. Un essai élargi des
vidéos comporte deux échecs extérieurs à cette modification : une attente de
sous-titres VTC déjà en échec avec le gabarit précédent, et une lecture partielle
de fichier vidéo absent de la copie de travail. Aucun média ni réglage de
sous-titres n’est modifié. La validation visuelle par Chromium local n’a pas pu
être effectuée (archive du navigateur indisponible) ; les rendus HTTP et les
interactions DOM ont été vérifiés.
