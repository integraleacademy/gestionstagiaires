# Production reproductible

Python 3.12, Pillow 12.3, kokoro-onnx 0.6.1, ONNX Runtime 1.30, soundfile 0.14 et FFmpeg.
Les fichiers de modèle Kokoro v1.0 ONNX et voices-v1.0.bin sont téléchargés séparément depuis la publication officielle thewh1teagle/kokoro-onnx (model-files-v1.1) et ne sont pas inclus dans l'application.
La synthèse utilise ff_siwis, vitesse 1.015, langue fr-fr. Il s’agit d’une voix différente de celle de la capsule historique.

`offline_guard.py` interdit les appels système réseau avant l'import du moteur ; la télémétrie ONNX est désactivée.
Aucun texte de cours n'est envoyé à un service de synthèse.

```sh
python author_series.py
export ACADEMY_MODEL=/chemin/vers/modeles
export ACADEMY_WORK=/chemin/vers/intermediaires
python build_audio.py
python render_series.py
python build_manifest.py
```

Les deux scripts acceptent une liste d'identifiants pour ne traiter que certaines capsules. Ils reprennent les étapes déjà terminées.
Le rendu est natif en 3840 × 2160, 25 images/seconde, H.264/AAC, texte et diagrammes nets, sous-titres incrustés.
Les polices statiques Manrope 600/800 sont dérivées de Manrope sous SIL OFL ; la licence est fournie dans assets/OFL.txt.
Les génériques, les écrans et les références pédagogiques ne contiennent aucun crédit de synthèse vocale.

L’export utilise un fichier temporaire `.partial.mp4`, contrôle les pistes et la durée par ffprobe, puis renomme le résultat.
Limiter explicitement le décodeur PNG à un thread évite une allocation excessive de mémoire sur les machines à nombreux cœurs.
