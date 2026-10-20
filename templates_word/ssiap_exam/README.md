# Modèles SSIAP 1 fournis par le centre

Les deux fichiers `_source.doc` sont les originaux joints le 19 octobre 2026, conservés octet pour octet.

- Individuel SHA-256 : `14e0698a970eb62ee0e7c9c37e425d1f9608fbce2d9dc60077ca09c525dbbda4`
- Collectif SHA-256 : `111fb2fd5afbae8eb6d1ca2748cce491a3a410c7cbd526377cd919700baf8d88`

Les PDF sont des exports des originaux avec leur police Comic Sans MS incorporée. Seuls la date d'exemple et les noms d'exemple ont été retirés. Aucun titre, logo, tableau, texte fixe, zone d'évaluation ou emplacement de signature n'a été redessiné. La ressource incorporée `ExamRegular` permet de renseigner les données variables avec la même police, sans dépendance aux polices du serveur.

`ssiap_exam_pdf.py` renseigne les champs administratifs : date, identité du candidat ou liste des candidats, jury et outils pour le collectif. Le tableau de résultats, les notes, appréciations, dates de réussite et signatures du jury restent vierges. Le collectif possède 14 places ; au-delà, une nouvelle copie du même formulaire est utilisée. Le PV individuel est inséré à l'identique dans le dossier.

À la demande du centre du 19 octobre 2026, les deux PV utilisent les mêmes coordonnées et le même agrément que l'organisation de l'examen. L'agrément figure également en pied de page sur chaque page du dossier. Ces ajouts préservent les grilles et zones d'évaluation des modèles.

Les signatures et cachets automatiques concernent les deux attestations et la zone réservée à l'organisme de formation sur les deux PV. Ils proviennent des images d'origine de `conventionssiap.docx`. Les zones de signature du membre et du président du jury ne sont jamais signées automatiquement.

Ne pas substituer ces formulaires SSIAP 1 pour un autre niveau.

La couverture du dossier utilise la photo d’identité enregistrée sur la fiche stagiaire, avec contrôle d’accès au fichier et respect de son orientation. Le SSIAP 1 utilise `static/img/ssiap1-exam-cover-illustration.png` : un dessin dans le style des manuels, cadré de près, avec « SSIAP 1 » en blanc sur le polo rouge. L’image générique `static/img/ssiap-exam-cover-illustration.png` reste réservée aux autres niveaux pour ne pas leur afficher une tenue SSIAP 1. Ces illustrations sont indépendantes de la photo du candidat. Les accents viennent des données d’identité, sans translittération. Les attestations reprennent le SIRET, le NDA et le code NAF de la convention SSIAP, ainsi que la raison sociale et le RCS de l’identité légale du centre.

La feuille de présence est un document distinct : candidats présentés et membres du jury réunis sur une page, avec des cases vierges pour leurs signatures du matin et de l’après-midi. La hauteur des lignes s’adapte à l’effectif ; seuls les groupes trop nombreux pour conserver des cases lisibles débordent sur une page supplémentaire, sans page systématiquement réservée au jury. Les deux modèles de PV restent inchangés.

Les rappels automatiques passent par le cron existant `document-reminders` (secret obligatoire), à J−7 entre 09:00 et 20:00 Europe/Paris. Ils utilisent le même modèle que l’aperçu manuel et le même historique. Réservation atomique par session/date/adresse, exclusion des inscriptions annulées et sessions archivées, aucun rattrapage des dates dépassées. Un rappel manuel envoyé à partir de J−7 remplace l’automatique. Un refus explicite permet au plus trois tentatives espacées de 30 minutes ; une réponse incertaine reste à vérifier pour éviter les doublons.
