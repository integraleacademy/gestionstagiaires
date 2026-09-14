# Calcul du financement BTS

Les nouveaux dossiers utilisent le NPEC officiel du couple RNCP × branche de
l’employeur. L’IDCC provient des compléments CERFA de l’entreprise et est relié à
la CPNE par l’onglet 4 du référentiel France compétences. L’IDCC 3252 étant relié
à trois CPNE dans l’édition de septembre 2026, le formulaire demande de choisir
la branche au lieu de retenir arbitrairement un montant.

La date de **conclusion**, et non la rentrée ou la date du jour, choisit l’édition.
Le NPEC retenu reste le même sur les années de ce contrat. Un contrat conclu le
31 août 2026 conserve le barème 2025, même s’il débute en septembre 2026.

## Sources publiques intégrées

- [France compétences, référentiels NPEC](https://www.francecompetences.fr/referentiels-et-bases-de-donnees/).
- [Septembre 2026, publié le 31 août 2026](https://www.francecompetences.fr/app/uploads/2026/08/Referentiel-unique-des-NPEC-1er-septembre-2026.zip) : 84 certifications BTS, 274 IDCC.
- [Septembre 2025, codes actualisés le 28 mai 2026](https://www.francecompetences.fr/app/uploads/2026/05/Referentiel-des-NPEC-01.09.2025_vMAJ-28.05.2026.zip) : 95 certifications BTS, 348 IDCC.
- [Décret du 29 août 2026](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000054762162) : application aux contrats conclus depuis le 1er septembre 2026.
- [Décret du 27 juin 2025](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000051808276) : prorata journalier et participation employeur réservée aux niveaux 6 et supérieurs.
- [OPCO EP, modalités et questions-réponses](https://www.opcoep.fr/prestataire-de-formation/connaitre-la-reglementation/la-reforme-du-financement-de-l-apprentissage-2025) : premier et dernier jours inclus ; années de 365 ou 366 jours ; réduction pour le distanciel.
- [Arrêté d’exemption du 26 novembre 2025](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000052950504) : aucun BTS dans cette liste.

`data/bts_npec.json.gz` contient exclusivement des données publiques, les dates
d’applicabilité de chaque ligne, le statut, les URL officielles et les SHA-256
des classeurs. Les codes RNCP groupés dans une ligne du classeur sont conservés
comme alias **dans cette édition uniquement**. Aucun report automatique d’un
ancien RNCP vers une édition où il n’apparaît plus.

Pour mettre à jour le fichier, adapter les éditions de
`scripts/build_bts_npec_reference.py`, télécharger les classeurs officiels puis
lancer ce script avec `--directory /chemin/des/classeurs`. Il extrait uniquement
les lignes dont le type de diplôme est BTS. La compression est reproductible
(`mtime=0`). La référence est livrée avec le code et ne nécessite aucune clé
d’API ni l’envoi de données de dossiers à un tiers.

## Calcul et conservation

Les périodes sont des années d’exécution du contrat, de date à date. Chacune
utilise sa durée annuelle réelle (365 ou 366 jours), et la dernière période est
proratisée. Les calculs sont effectués en centimes avec Decimal, arrondis au
centime à la fin de chaque période. L’interface montre les dates et les jours
pris en compte. L’exemple OPCO EP d’un NPEC de 8 000 € sur 370 jours donne
8 109,59 €.

### Formation commencée sans employeur

Le formulaire demande de confirmer le statut éligible lorsque l’entrée en CFA
précède la signature et le début du contrat. Ce statut ne se déduit pas des
dates seules. « Non » conserve le financement de la seule période du contrat.
« Oui » active le calcul pour un premier contrat (type 11), sous le régime de
[L. 6222-12-1](https://code.travail.gouv.fr/code-du-travail/l6222-12-1) et
[R. 6332-25 VI](https://code.travail.gouv.fr/code-du-travail/r6332-25).

La date de début de formation du CERFA est le point de départ. La signature doit
intervenir au plus tard trois mois calendaires après cette date (fin de mois
ajustée si nécessaire), et non dans un forfait de 90 jours. Une signature plus
tardive bloque ce supplément pour vérification OPCO ; on ne prélève pas
arbitrairement les trois derniers mois. Les contrats successifs sont également
renvoyés à une vérification pour éviter le double financement.

Les jours ajoutés s’arrêtent à la veille de la signature ou du début d’exécution,
selon la première de ces deux dates. Si la signature précède l’exécution, le
formulaire signale les jours intermédiaires non financés automatiquement.
Le supplément est proratisé au NPEC retenu (minoration distancielle incluse), avec
le dénominateur de la première année de contrat, puis ajouté à cette année dans
la convention. Les années d’exécution conservent leurs dates anniversaires ;
le détail séparé affiche les dates, jours et montant supplémentaires. Le barème
reste déterminé par la conclusion, même si la formation a commencé plus tôt.
Exemple : entrée le 01/07/2026, signature et début le 01/09/2026, NPEC 8 765 € :
62 jours supplémentaires, soit 1 488,85 € ajoutés à la première année.

Le recalcul conserve le reste à charge et les documents archivés. La modification
de la période financée invalide l’empreinte du paquet courant et impose sa
régénération avant signature/transmission. Une période antérieure non qualifiée
bloque la génération plutôt que de produire silencieusement un montant incomplet.

À partir de 80 % d’heures à distance (heures du CERFA), le NPEC est minoré de
20 %, avec plancher de 4 000 € sans augmenter le montant initial. Les BTS sont
de niveau 5 : aucune participation légale de 750 € n’est ajoutée. Le reste à
charge commercial vaut zéro par défaut ; un montant convenu peut être saisi.
Le tarif conventionné correspond au financement calculé plus ce reste à charge.
Les frais annexes restent séparés. Les majorations individuelles ne sont pas
inventées. Le résultat demeure soumis à la décision de prise en charge OPCO.

Un code manquant, une branche inconnue, un RNCP absent, des heures manquantes,
un barème antérieur à septembre 2025, un employeur public ou un avenant ne
produisent aucun montant automatique. Le formulaire précise le point à vérifier.
Les conventions ne peuvent pas être générées avec un financement incomplet.

Les anciens montants manuels et les empreintes des documents déjà générés
restent inchangés. Le bouton de recalcul constitue une modification explicite
du dossier, conserve les documents archivés et impose une nouvelle génération
avant signature/transmission. Pour les dossiers automatiques, les montants
OPCO et le nombre d’années sont recalculés sur le serveur ; des valeurs POST
modifiées ne permettent pas de les remplacer. Le paquet de documents conserve
le NPEC, la branche, la source et le détail du calcul utilisés.
