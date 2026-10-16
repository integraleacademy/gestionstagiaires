# APS : édition à lecture facilitée

Les 62 entrées de `courses.txt` contiennent chacune une explication, un exemple,
un résumé et trois définitions. Les vidéos narrent uniquement ces trois parties.
Elles ne contiennent ni quiz, ni instruction de pause. Les exercices restent dans
le parcours interactif. Les boutons normaux du lecteur restent disponibles.

La voix reste `fr-FR-HenriNeural`, au débit approuvé `-2%`.
Les sous-titres sont reconstruits à partir du texte original et des repères
temporels de la voix. Toute différence de mots interrompt la génération.
Ponctuation conservée, deux lignes maximum, 44 caractères maximum par ligne,
police Manrope de 38 pixels sur vidéo 1280 × 720 et bande sombre réservée.
Le fichier VTT et la transcription reprennent le même texte que la voix.

Construction (dépendances de génération : edge-tts, Pillow, ffmpeg) :

```sh
APS62_WORK=/tmp/aps62-v5 python scripts/render_aps62_v5.py
python scripts/build_aps62_v5.py
python -m unittest tests.test_aps62_readability -q
```

`APS62_ONLY=aps62-01-01` permet un premier rendu. Les caches sont réutilisables ;
les fichiers audio sont identifiés par leur texte et leur voix. La signature des
vidéos inclut aussi le code de rendu et celui des sous-titres.

Les paragraphes du cours de référence sont raccourcis sans suppression de phrases.
Les anciennes éditions, les identifiants d'activités, les budgets par module,
les 4 simulations de main courante et les 14 études documentaires sont conservés.
Les durées des capsules sont mesurées ; les 62 heures du parcours restent un
objectif pédagogique global, et non la durée cumulée des vidéos.

Repères éditoriaux : mots usuels, phrases courtes, exemples concrets, définitions
proches du cours et consignes limitées à l'action demandée.
Référence de méthode : https://www.w3.org/WAI/tips/writing/
Les limites juridiques restent celles du cours et de `regulatory_review.json`.
Cette réécriture ne constitue ni une certification FALC ni une validation de
compréhension par le public cible. Une séance avec les apprenants concernés
reste nécessaire pour observer les difficultés réelles.
