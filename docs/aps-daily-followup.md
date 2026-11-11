# Mails quotidiens de suivi APS

Le diagnostic est calculé à partir du suivi réel. Un gain depuis la veille ne
diminue jamais le niveau d'alerte établi à partir du travail restant et des dates.
Le message HTML, sa version texte, l'objet et le pré-en-tête utilisent le même
diagnostic. Les mails envoyés restent archivés sans régénération.

## Dates et charge de travail

- Échéance : fin du distanciel (`aps_remote_end`), au plus tard la veille du
  présentiel. Sans fin du distanciel, utiliser la veille du présentiel.
- Nombre de jours : jours calendaires disponibles, journée courante comprise.
  Une échéance passée donne zéro jour, jamais un jour fictif.
- Repère indicatif d'avancement : fraction de la période écoulée, plafonnée à
  100 %. Il ne s'agit pas d'une nouvelle condition de validation.
- Charge quotidienne : temps encore requis par les modules divisé par les jours
  disponibles, arrondi à la minute supérieure. Les activités doivent aussi être
  terminées ; cette estimation n'est pas une garantie de validation.
- Au-delà de huit heures par jour, ne pas prescrire un planning irréaliste :
  expliquer la charge et demander un contact immédiat avec l'équipe.
- Des dates absentes ou incohérentes n'autorisent aucun délai inventé. Un suivi
  indisponible n'autorise aucun mail alarmant construit sur une progression nulle.

## Niveaux, par ordre de priorité

1. **Validé** : uniquement si les activités ET les temps requis sont validés.
2. **Critique** : échéance dépassée ; plus de huit heures par jour encore
   nécessaires ; ou trois jours au plus et moins de 50 % d'avancement.
3. **Urgent** : plus de six heures par jour ; dernier jour et parcours incomplet ;
   trois jours au plus et moins de 90 % ; sept jours au plus et moins de 50 % ;
   ou quatorze jours au plus avec au moins trente points sous le repère calendrier.
4. **Vigilance** : plus de dix points sous le repère calendrier ou au moins vingt
   points sous la médiane du groupe comparable. Pas de retard déclaré au premier
   jour sur ces seuls critères.
5. **Avancé** : au moins 75 %, dates exploitables et aucun risque ci-dessus.
6. **Suivi courant** : organiser les créneaux et rappeler l'objectif de validation.

Une journée sans activité donne un constat factuel. En situation à risque,
l'alerte précède tout commentaire sur le progrès récent : ni félicitations ni
encadré vert. Un parcours avancé mais inactif reçoit une invitation à finaliser,
sans supposer une régularité non observée.

## Comparaison de groupe

Lire une fois les rapports des stagiaires éligibles de la même session, y compris
ceux qui ont terminé et ceux sans adresse mail. Exclure les inscriptions annulées,
les rapports indisponibles, le destinataire et les programmes non comparables
(versions, durée requise, nombre d'activités). Afficher des statistiques seulement
à partir de trois autres rapports comparables : effectif, médiane, nombre de
parcours réellement validés et nombre d'autres stagiaires à au moins 80 %.

Aucun nom, classement individuel ou identifiant de camarade ne figure dans le
mail. Le repère collectif peut déclencher une vigilance, jamais atténuer une
urgence de calendrier ou de charge. Les statistiques sont omises pour un parcours
déjà validé. Une défaillance de lecture est omise, sans être convertie en zéro.

## Exécution et contrôle

L'aperçu non envoyé et le cron appellent le même générateur avec les mêmes
statistiques. La fenêtre d'envoi, la signature Cassandre, les coordonnées d'aide,
la protection contre les doubles envois et les archives ne changent pas.

Validation :

```sh
python -m pytest tests/test_aps_learning_followup.py tests/test_elearning_mail_identity.py tests/test_daily_recap.py -q
```
