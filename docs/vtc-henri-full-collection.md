# Voix Henri pour toute la collection VTC

Collection terminée le 14 octobre 2026 : les 96 leçons et les huit synthèses
sont présentes. Les six synthèses C à H ont été reprises depuis le cache vocal,
puis les 103 nouveaux MP4 ont passé le contrôle complet hors ligne. Le pilote
D.02 validé conserve exactement ses fichiers. Le manifeste final remplace le
point de reprise `.pending.json` ; le rapport est conservé dans
`docs/vtc-henri-validation.json`.

La validation d’intégration du 14 octobre réussit les 113 tests ciblés du lecteur,
des sous-titres, de l’accès aux médias et des progressions. Les 416 combinaisons
de chronologie antérieure et d’état de visionnage sont conservées sur les 104
vidéos, sans ajout de temps de formation. Les modifications récentes de `test-v2`
ont été intégrées avant cette vérification.

Cette livraison étend le principe de narration validé le 13 octobre 2026 aux
96 leçons et aux huit synthèses des modules A à H. Le pilote D.02 reste celui
approuvé : son MP4 conserve l’empreinte SHA-256
`a9e6aae708388e899694043f90576e5b748b26b7be8a8673b63a3cdb1bed06fc`
et sa durée de 136,65 secondes.

## Narration et médias

- Henri (`fr-FR-HenriNeural`) lit les passages français en groupes de phrases.
  Les questions restent liées à leurs réponses et les amorces courtes à leurs
  explications. Les variations restent dans l’enveloppe approuvée : débit de
  −2 % à +4 %, hauteur de −1 à +2 Hz, respirations ajoutées de 0 à 0,16 seconde.
- Les exemples anglais conservent Ryan (`en-GB-RyanNeural`), au débit de
  synthèse −6 % déjà utilisé. La lecture des vidéos reste à 1×.
- Aucun étirement temporel de la voix. Les limites audio conservent les marges
  autour des mots ; les pauses pédagogiques tombent dans les fins silencieuses.
- Le texte des 103 vidéos régénérées est conservé intégralement. Les exceptions
  dans `voice_delivery_overrides_v15.json` ne dirigent que la ponctuation de la
  synthèse : une comparaison des mots normalisés interdit tout ajout ou retrait.
- Les passages denses peuvent repasser au débit de synthèse −2 % ou recevoir
  des respirations entre propositions complètes. Les réglages réellement utilisés
  figurent dans les segments de chaque vidéo et dans `delivery_adjustments`.

Les nouveaux MP4, affiches et VTT utilisent les URL immuables `media/vtc/v15/`.
`video_voice_v15.json` contient les 104 entrées ; D.02 y reprend à l’identique
l’entrée et les fichiers de `video_voice_v14.json`. Un ensemble incomplet ou
une référence différente au pilote sont refusés.

## Sous-titres et contrôles

Les repères et sous-titres sont reconstruits depuis les limites de mots réelles
du fournisseur vocal. Les sous-titres conservent tous les mots, sur deux lignes
de 44 caractères maximum, à 20 caractères par seconde maximum et avec au moins
une seconde d’affichage à 1×. Pour les passages denses, une frontière d’affichage
peut précéder le mot suivant de 0,16 seconde maximum ou le suivre de 0,39 seconde
maximum ; les horodatages audio et les repères des cartes restent inchangés.

Le générateur décode chaque image et toute la piste audio de chaque nouveau
MP4. Il vérifie les continuités, les durées, les limites des sous-titres, les
empreintes, les citations servant aux cartes, les silences des pauses et
l’absence d’écrêtage. Le manifeste complet n’est écrit qu’après ces contrôles.
Les prises intermédiaires et les fichiers de travail permettent de reprendre
une génération interrompue sans renvoyer une narration déjà mise en cache.

## Progression et publication

Les identifiants de cours, d’activités et de vidéos, les obligations de
visionnage, les durées pédagogiques et le registre du temps de formation sont
conservés. Les progressions reconnues sont projetées par chapitre, depuis les
anciennes versions vers V11 puis vers la nouvelle narration. Une validation
déjà acquise reste acquise ; une position partielle n’octroie ni validation
supplémentaire ni temps de formation. Les durées inconnues restent inchangées.

La révision de média des huit cours passe à 15. Un lecteur ouvert sur une
ancienne chronologie doit recharger sa page avant d’envoyer de nouvelles
positions. Le pilote D.02 reste inchangé malgré cette révision de collection.

Après publication, une nouvelle modification du rendu doit utiliser une nouvelle
révision et de nouvelles URL de média.

La publication vise la branche `test-v2` et son service Render existant. Elle
n’ajoute aucune variable d’environnement, aucun service et aucune dépendance
de synthèse au serveur applicatif.

## Reproduction

Utiliser un environnement de construction isolé avec les dépendances épinglées
de `scripts/vtc/voice_preview_requirements.txt`, dont le correctif de protocole
du client vocal déjà utilisé pour D.02. Le transfert autorisé ne contient que
les narrations publiques des cours, sans aucune donnée de stagiaire.

```sh
python scripts/vtc/render_henri_collection.py
python scripts/vtc/render_henri_collection.py --render
```

`VTC_HENRI_WORK` permet de choisir le répertoire de travail. `--only A.01,E.01`
sert au diagnostic ; un sous-ensemble ne publie jamais le manifeste complet.
La validation auditive de référence reste celle de D.02 par l’utilisateur ;
les contrôles des 103 autres vidéos sont des contrôles techniques complets.

Après des générations par lots, la commande locale suivante assemble les
résultats et refait les contrôles de toute la collection sans aucun appel vocal :

```sh
python scripts/vtc/assemble_henri_collection.py
```
