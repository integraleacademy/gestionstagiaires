# APS : répartition corrigée du 6 octobre 2026

L'édition `20261006-aps62-v4` corrige la répétition de la v3. Une main courante
n'est plus ajoutée à chacun des 62 dossiers. Les fichiers historiques v1, v2 et
v3, leurs identifiants et les affectations existantes ne sont pas modifiés.
La nouvelle édition devient celle proposée dans le catalogue.

## Choix pédagogiques

- Quatre exercices de main courante, tous sans saisie libre :
  - 08.03 : heures, sources et constat vérifié ;
  - 08.05 : action ouverte et transmission à la relève ;
  - 13.01 : rectification traçable ;
  - 13.02 : reprise après panne et prévention des doublons.
- Les 62 dossiers reçoivent chacun une explication ciblée, un exemple expliqué
  et une nouvelle situation de transfert avec correction argumentée.
- Les missions conservent le constat et deux décisions successives. Les deux
  questions génériques de document et de relève sont retirées de chaque mission.
- Quatorze études de documents sont situées là où elles servent le thème :
  planning, chronologies contradictoires, portée des indices, données à
  transmettre, règle d'accueil, déontologie, dialogue, version de consigne,
  justification, coactivité industrielle, risque électrique, sources d'une
  alerte, dossier pour le relais judiciaire et dispositif événementiel.
- Le module 13 utilise ses deux simulations numériques comme études de documents
  et ne reçoit pas un atelier documentaire supplémentaire.
- Les transferts gardent leur premier cas et remplacent deux questions répétées
  par une nouvelle application propre au dossier.

La nouvelle édition comprend 452 activités, dont 142 ateliers (62 missions,
62 transferts, 14 études et 4 mains courantes), 124 questions de cours et les
62 capsules existantes. Les examens blancs restent les mêmes banques de
30 questions par module et 100 questions au final. Aucune nouvelle vidéo n'est
annoncée ou créée par cette répartition.

## Durée et limites

Le budget total reste un **objectif pédagogique de 62 h** avec les mêmes durées
par module. Il ne s'agit pas d'une preuve que chaque apprenant effectuera 62 h
utiles. Les durées indicatives des dossiers varient désormais : elles ne sont
plus toutes forcées à 60 minutes. Les études ciblées disposent de 14 minutes,
les mains courantes de 10 minutes, le reste est réparti entre les cours,
comparaisons et exercices. Le moteur de temps n'est pas allongé ou modifié.

La répartition exacte est disponible dans
`elearning_native/aps62/allocation_v4.json`. Un essai avec des apprenants doit
mesurer le temps actif, les erreurs, les relectures et le besoin d'aide avant
que la charge réelle puisse être validée. Ajouter un compteur ne valide pas
une durée pédagogique.

Le rapprochement réglementaire de la v3 et ses limites restent applicables :
62 h ministérielles ne sont pas 62 h automatiquement imputables au TFP APS de
branche ; les compléments spécialisés du module 12 et les évaluations pratiques
avec le formateur restent nécessaires. Aucune conformité globale n'est affirmée.

## Sources de contrôle des nouveaux exemples

Les pièces, chiffres, noms et consignes de cas sont fictifs. Ils servent au
raisonnement et ne sont pas présentés comme des citations légales ni comme des
consignes universelles pour un site réel.

- CSI, surveillance et gardiennage : https://www.legifrance.gouv.fr/codes/id/LEGISCTA000025507569
- CPP, article 73 : https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000029000766
- Code pénal, responsabilité : https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006070719/LEGISCTA000006136037/
- CNIL, finalités : https://www.cnil.fr/fr/passer-laction/definir-une-finalite
- CNIL, RGPD : https://www.cnil.fr/fr/rgpd-de-quoi-parle-t-on
- INRS, évaluation des risques : https://www.inrs.fr/demarche/document-unique/ce-qu-il-faut-retenir.html
- INRS, prévention ATEX : https://www.inrs.fr/risques/explosion/demarche-prevention-risques.html
- INRS, habilitation électrique : https://www.inrs.fr/risques/electriques/habilitation-electrique-foire-aux-questions
- INRS, prévention électrique : https://www.inrs.fr/risques/electriques/prevention-risque-electrique.html
- SGDSN, signalements : https://www.sgdsn.gouv.fr/publications/signalement-des-situations-suspectes-recommandations-lusage-du-grand-public
- SGDSN, Vigipirate : https://www.sgdsn.gouv.fr/vigipirate/le-plan-vigipirate-faire-face-ensemble

## Maintenance et vérification

Sources d'auteur : `scripts/aps62_v4/focus.txt` et
`scripts/aps62_v4/casefiles.py`. Génération : `python scripts/build_aps62_v4.py`.
Le générateur lit la v3 sans la réécrire et produit une édition reproductible.
Les tests vérifient la répartition, le rendu de toutes les activités, la
correction côté serveur, l'absence de rédaction et la continuité des éditions
archivées. Toute modification future d'activités affectées nécessite une
nouvelle édition.
