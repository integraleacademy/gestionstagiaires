# Aperçu de narration D.02 — 13 octobre 2026

## Choix retenu : Henri

L’utilisateur préfère Henri et a confirmé conserver cette voix, sans
ralentissement supplémentaire. Le générateur principal utilise désormais
`fr-FR-HenriNeural` à `-2%`, comme les vidéos existantes, avec une lecture à 1×.
Le texte plus oral reste prêt dans `scripts/vtc/voice_preview_d02.json`.

La nouvelle vérification du 13 octobre avec Henri a renvoyé HTTP 403 avant
réception du moindre octet audio. Aucun aperçu Henri révisé n’a donc été généré
ou mis en ligne. Le précédent essai féminin n’est pas retenu et ne doit pas
servir de remplacement automatique. La synthèse D.02 vers Microsoft a déjà été
autorisée par l’utilisateur ; aucune nouvelle autorisation n’est attendue.

Préparer puis générer Henri lorsque le service permet de nouveau la synthèse :

```sh
python scripts/vtc/render_voice_preview.py
python scripts/vtc/render_voice_preview.py --render
```

La sortie est isolée dans `media/vtc/voice-preview-d02-henri/`. Les sous-titres
seront recalculés sur les mots réellement générés et contrôlés à 1×. Ne pas
ralentir Henri pour résoudre un éventuel problème de lisibilité : ajuster la
ponctuation du texte, puis refaire la synthèse et les contrôles.

## Essai féminin antérieur — non retenu

Un aperçu autonome de 136,05 secondes a été généré avec une voix française
féminine, Kokoro-82M / ff_siwis. Il est destiné à la comparaison par l’utilisateur.
Il ne remplace aucune des 104 vidéos et ne modifie ni le manifeste ni la
progression des stagiaires. Son naturel reste à apprécier à l’écoute.

## Contenu et voix

La leçon « Trouver l’information exacte » conserve les quatre scènes, les
identifiants de chapitres et les notions de l’original : information explicite,
contexte, unités, messages corrigés, réservation et prise en charge. Le texte
emploie des phrases complètes et des transitions orales.

Le débit est réglé à 0,90 lors de la synthèse ; lecture à 1×, sans étirement audio.
Les sous-titres et les cartes utilisent les durées des phonèmes produites par
le modèle et la prononciation de la phrase complète. Un écart entre mots écrits
et groupes phonétiques provoque un arrêt, sans timing proportionnel au texte.

L’essai initial Remy Multilingual a échoué avec HTTP 403 du service Microsoft,
en local et dans GitHub Actions, malgré le transfert explicitement autorisé par
l’utilisateur le 13 octobre. La solution Kokoro télécharge uniquement des poids
publics ; aucun texte n’est transmis à un nouveau service vocal.

## Reproduire l’aperçu local

Dans un environnement Python 3.12 isolé :

```sh
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install kokoro==0.9.4 transformers==5.19.0 huggingface-hub==2.2.0 soundfile==0.14.0 socksio edge-tts==7.2.8 Pillow==12.3.0 av==19.0.1 imageio-ffmpeg==0.6.0
python scripts/vtc/render_voice_preview_local.py
python scripts/vtc/render_voice_preview_local.py --render
```

La première commande du script ne génère rien. La seconde écrit le MP4,
l’affiche, le VTT et les métadonnées sous
`elearning_native/vtc/assets/media/vtc/voice-preview-d02-local/`.
Ces médias ne sont pas référencés par le cours ; le fichier est remis séparément.

## Contrôles effectués

- Décodage intégral du MP4 avec `ffmpeg -xerror` réussi.
- 33 sous-titres : texte intégral conservé, sans chevauchement, au maximum deux
  lignes de 44 caractères et 19,93 caractères/seconde à 1× ; durée minimale 1,95 s.
- Contrôle visuel de trois images du MP4, dont le passage d’exemple.
- 14 tests du générateur et des protections de l’aperçu réussis.
- SHA-256 du MP4 remis :
  `73e4d242b7af9143a5673f2d9c272a527b07f3378c5c51fa43ce932008d45411`.

Ces contrôles ne constituent pas une écoute subjective ni un alignement par
reconnaissance vocale indépendante. La comparaison auditive précède toute
généralisation aux autres leçons.

Modèle : Kokoro-82M (Apache-2.0), voix française ff_siwis / SIWIS.
