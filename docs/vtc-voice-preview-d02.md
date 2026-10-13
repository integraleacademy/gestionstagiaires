# Préparation de la narration D.02

Statut : texte et générateur préparés ; nouvelle narration non générée, non
écoutée et non publiée. Les 104 vidéos existantes restent inchangées.

La leçon « Trouver l’information exacte » comporte quatre scènes. Le texte
préparé reprend les mêmes notions : information explicite, contexte, unités,
messages corrigés et distinction entre réservation et prise en charge. Les
listes nominales sont reformulées en phrases complètes. La voix proposée pour
comparaison est Remy Multilingual, en français, au débit natif. Son rendu devra
être écouté avant d’étendre le changement aux autres leçons.

## Préparation locale

```sh
python scripts/vtc/render_voice_preview.py
python -m pytest -q tests/test_vtc_voice_preview.py tests/test_vtc_quality_renderer_v11.py
```

La première commande valide les sources, les quatre scènes, les cartes et leurs
ancrages sans contacter le service de synthèse. Les tests emploient des données
de timing et un signal PCM synthétiques : ils ne valident pas une vraie narration.

## Génération à autoriser

Le contrôle automatique d’autorisation de cette session a refusé une tentative
de synthèse, car il exige l’accord explicite de l’utilisateur avant le transfert
du texte vers Microsoft. Ne pas lancer la commande suivante avant cet accord.
Seuls les textes de cette leçon sont concernés, sans données de stagiaires,
identifiants ni documents administratifs.

Après cet accord, avec edge-tts, PyAV, Pillow et imageio-ffmpeg installés :

```sh
python scripts/vtc/render_voice_preview.py --render
```

Les médias sont écrits sous `media/vtc/voice-preview-d02/`, sans modification du
manifeste des cours. Les sous-titres et les apparitions des cartes sont calculés
depuis les horodatages des mots réellement générés. Les contraintes de lisibilité
sont mesurées à 1×. Aucun filtre d’étirement audio ne modifie la voix.

Avant publication de l’aperçu : vérifier le décodage intégral, écouter la voix,
contrôler visuellement les sous-titres et les apparitions de cartes. La génération
seule ne met rien en ligne et ne modifie aucune progression de stagiaire.
