# Contrôle des vidéos VTC — 13 octobre 2026

## Modification du lecteur
Lecture fixe à 1×, sans sélecteur de vitesse ; suppression du bloc « Texte de la voix ». Sous-titres intégrés et repères de scène conservés. Le serveur conserve les exigences de visionnage et les acquis. La révision du lecteur passe à 13 ; les médias, leurs durées et leurs identifiants ne changent pas.

## Contrôles des médias
104 fichiers MP4 décodés intégralement sans erreur (run 38343190440). Vérification des empreintes des 104 vidéos, affiches et WebVTT, des pistes AAC originales, de 624 scènes, de 4 354 sous-titres et de 1 554 repères visuels : aucune erreur technique (runs 38344191938 et 38345108119).

Comparaison indépendante de la voix avec les sous-titres sur un extrait de huit secondes dans chacune des 104 vidéos : 832 secondes contrôlées. Six extraits peu reconnus par le premier modèle ont été revérifiés avec un modèle plus précis : B.05, E.06, G.07, H.02 et synthèses G/H. Aucun décalage supérieur au seuil de contrôle de 0,65 seconde entre un mot reconnu et sa plage de sous-titres ; écart maximal observé avec le premier modèle : 0,377 seconde. Le passage A.02 de la capture utilisateur est inclus (extrait de 60 à 68 secondes). Ces contrôles par extraits ne constituent pas une écoute humaine intégrale de la collection.

## Contrôles du logiciel
117 tests serveur ciblés et 4 tests JavaScript. Vérification Chromium en 1440, 390 et 320 pixels : vitesse fixe à 1×, absence de doublon textuel et de sélecteur, conservation des repères synchronisés, agrandissement/réduction et absence de débordement horizontal. Aucun changement aux contenus ni aux progressions APS, A3P et MAC APS.

Les exécutions de contrôle sont sur la branche isolée codex/vtc-video-sync-20261013. Les scripts reproductibles sont dans scripts/vtc_sync_review ; ils ne lisent ni ne modifient les données des stagiaires.
