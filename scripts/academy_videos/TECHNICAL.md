# Reproduction du modèle validé

La capsule de référence est `aps-missions-limites-20260920.mp4`. Son fichier reste inchangé.
Les sources originales ont été récupérées dans `APS_Missions_et_limites_sources.zip`.

## Paramètres verrouillés

`reference_settings.json` reprend exactement la narration originale : `fr-FR-HenriNeural`, débit `-2%`, hauteur et volume par défaut. Aucun remplacement automatique de voix n'est permis.
Le moteur est edge-tts 7.2.8. Les prises sont conservées et réutilisées. Le certificat TLS est vérifié avec le magasin de certificats de l'environnement.
La synthèse n'envoie que les phrases publiées dans le dépôt au commit `806432ea1af278eb493c2c2b2f6ada71f70f0fe0` ; le script vérifie leur présence dans le blob Git `0379e5f0d46df6be01062de152476eabfb79a263` avant toute requête.

Le son est traité comme dans le modèle : PCM mono 48 kHz, suppression des silences avec marges de 90 et 160 ms, rampes de 250 échantillons, pause de 220 ms entre prises, entrée de scène de 580 ms (900 ms au début), sortie de 500 ms. La normalisation finale est `loudnorm=I=-16:TP=-1.5:LRA=11`, AAC 192 kbit/s.

`approved_style.py` contient les primitives graphiques du modèle. Le logo, Manrope variable, les poids, les couleurs, les animations d'entrée, le balayage des transitions et les sous-titres sont repris à l'identique. Le titre du pied de page varie selon le module.
Les sous-titres utilisent Manrope 600, taille logique 30, ivoire `#F4F1E9`, sur fond noir arrondi `#080E11`, rayon 11, une ou deux lignes aux positions originales. Ils sont dessinés nativement, sans substitution de police par un moteur de sous-titres.
Les scènes conservent la présentation anthracite et or, les diagrammes, les cartes, le cas pratique, la synthèse ivoire et le générique du modèle. Les exemples et les pictogrammes s'adaptent au sujet.

## Reconstruction

Python 3.12, Pillow, NumPy, edge-tts 7.2.8 et FFmpeg.

```sh
python author_series.py
export ACADEMY_WORK=/chemin/vers/intermediaires
python build_audio.py
python render_series.py --preview
python render_keyframes.py
python build_manifest.py
```

Les scripts acceptent une liste d'identifiants pour limiter les exports. Les prises audio sont mises en cache par contenu. Une vidéo n'est réutilisée que si les sources et la chronologie correspondent à leur empreinte enregistrée.
Le rendu est natif en 3840 × 2160 à 25 images/seconde, H.264 CRF 17, AAC. `render_series.py` est le moteur graphique de référence ; `render_keyframes.py` réutilise les images stables et anime la progression dans FFmpeg pour accélérer les exports. Les fenêtres d’entrée des textes gardent leurs images natives. Les prises restent indépendantes de cette optimisation. L'export temporaire est vérifié par ffprobe avant remplacement du fichier final.
Les identifiants des nouvelles versions portent la date 20260925 pour éviter la réutilisation des anciens médias en cache.
Les informations techniques de synthèse restent dans ce fichier ; aucun crédit de voix n'apparaît dans les vidéos ou dans les références pédagogiques.
