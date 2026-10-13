# APS — narration et illustrations, 13 octobre 2026

Les 62 vidéos de l’édition courante utilisent de nouveau la prise Henri d’origine
(fr-FR-HenriNeural, débit de synthèse −2 %), sans le traitement `atempo=0.87`
appliqué dans v9. La voix reste une narration de synthèse.

`restore_aps_natural_voice.py` décode la prise v8, vérifie l’identité du texte,
conserve tous ses échantillons PCM dans l’ordre et replace les silences de
réflexion. L’encodage final reste AAC. Les horodatages des images, des sous-titres
incrustés, des VTT et des chapitres suivent le même facteur 0,87. Les anciens
médias restent disponibles ; les nouvelles URL sont immuables dans v13.

La préparation a réussi pour les 62 vidéos dans GitHub Actions, exécution
38353056412, commit ae9068e93675fcae1808ebc7f923c3828c35a09b. Chaque sortie a subi
un décodage intégral et une comparaison de l’empreinte du flux d’images avec v9.
`natural_voice_v13.json` conserve les empreintes et la correspondance des durées.
`check_aps_natural_voice.py` vérifie les 8 642 sous-titres, leur texte intégral et
leur chronologie. Sur 5 536 groupes de phrases non ambigus communs à v8, l’écart
médian des débuts est de 9,64 ms, le 95e percentile de 10,39 ms et le maximum de
184,04 ms. Il s’agit d’un contrôle technique, pas d’une évaluation d’écoute humaine.

La compatibilité des historiques n’accepte que la durée exacte du prédécesseur
connu. Un visionnage partiel reste partiel ; une validation acquise reste acquise.
Les heures de formation, les identifiants des activités et les résultats ne sont
pas réécrits. Les narrations différentes des anciennes éditions restent intactes.

Treize scènes supplémentaires accompagnent les 62 leçons : trois scènes distinctes
par leçon, choisies selon le sujet, au sein des étapes existantes. Elles proposent
un agrandissement et un texte alternatif. Les prompts sont conservés dans
`illustration_prompts_v13.json`. Les images WebP représentent environ 1,47 Mo au
total. Les textes pédagogiques et leur ordre restent identiques.

Vérification : reprise et validation par les vraies routes HTTP, 180 sous-tests
sur les éditions existantes, contrôle navigateur des 62 leçons (186 placements),
agrandissement, affichage mobile sans débordement et coche verte après validation
et rechargement. Le mode aperçu administrateur n’enregistre pas de progression.
