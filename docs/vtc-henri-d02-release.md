# Publication de la voix Henri validée — D.02

L’aperçu « Henri, rythme retravaillé » a été validé le 13 octobre 2026.
Cette livraison publie exactement ce MP4, sans nouvelle synthèse ni changement
de timbre, dans la leçon D.02. Les 103 autres vidéos conservent leur média.

- Voix : `fr-FR-HenriNeural` ; quinze groupes de phrases dirigés.
- Débit de synthèse : de −2 % à +4 %, hauteur de −1 à +2 Hz.
- Lecture : 1×, sans étirement du signal et sans sélecteur de vitesse.
- Durée : 136,65 secondes ; 33 sous-titres synchronisés.
- SHA-256 du MP4 validé :
  `a9e6aae708388e899694043f90576e5b748b26b7be8a8673b63a3cdb1bed06fc`.

Les sources de génération et leurs dépendances restent consultables à la
[révision de l’aperçu](https://github.com/integraleacademy/gestionstagiaires/commit/852d9c157369f2618d805e20eeb0fa1af96de073).
Le serveur de cours ne génère pas de voix et ne reçoit aucune dépendance de
synthèse supplémentaire.

## Intégration et reprise

Les médias approuvés sont placés dans `media/vtc/v14/` avec une URL distincte de
V11. `video_voice_v14.json` déclare uniquement D.02. La collection V11 complète
reste intacte et sert de prédécesseur vérifié.

L’identifiant vidéo et ceux des activités restent inchangés. Une vidéo terminée
reste terminée. Une lecture partielle est reportée dans le même chapitre, sans
accorder de fin de vidéo ni de temps de formation supplémentaire. Les anciens
enregistrements V10 passent par la correspondance V10 → V11 déjà établie avant
la correspondance V11 → voix validée. Les durées inconnues ne sont pas acceptées
comme preuve de progression.

La révision du lecteur du module D passe à 14 afin qu’un onglet déjà ouvert
demande un rechargement avant d’envoyer des positions sur l’ancienne chronologie.
Les autres modules restent à la révision 13.

## Vérification

77 tests réussis : fichier livré identique à l’aperçu, sous-titres servis,
contrôle d’accès et requêtes HTTP Range, obligations de visionnage, reprise V10
et V11, validations acquises, durée de formation inchangée, 104 vidéos à 1× et
rejet d’un manifeste non validé ou incohérent.

Le décodage intégral, les sous-titres et les images du MP4 ont déjà été vérifiés
lors de la génération. L’approbation du naturel vient de l’écoute de l’utilisateur.
