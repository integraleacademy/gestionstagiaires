# Contrat de consultation CRM — stagiaire et suivi VAE

## Requête et authentification

Cette API **en lecture seule** expose les informations réglementaires déjà disponibles et, de manière additive, le suivi VAE calculé par Gestion Stagiaires.

| Élément | Valeur |
|---|---|
| Méthode | `GET` |
| URL | `https://gestionstagiaires-r5no.onrender.com/api/integrations/crm/stagiaires?crm_contact_id=<identifiant>` |
| Paramètre | `crm_contact_id` (chaîne obligatoire, correspondance exacte) |
| En-tête | `Authorization: Bearer <CRM_INTEGRATION_API_TOKEN>` |
| Secret serveur | variable d'environnement existante `CRM_INTEGRATION_API_TOKEN` |

```bash
curl --get 'https://gestionstagiaires-r5no.onrender.com/api/integrations/crm/stagiaires' \
  --data-urlencode 'crm_contact_id=contact-42' \
  --header "Authorization: Bearer ${CRM_INTEGRATION_API_TOKEN}"
```

## Codes HTTP

| Code | Signification |
|---:|---|
| `200` | Un stagiaire lié a été trouvé. Une panne de consultation CNAPS reste représentée dans `card_pro.check_status`. |
| `400` | Paramètre `crm_contact_id` absent ou vide. |
| `401` | Bearer absent/invalide ou secret serveur non configuré. |
| `404` | Aucun stagiaire accessible à l'intégration n'est lié à cet identifiant. |
| `409` | Plusieurs stagiaires accessibles utilisent le même identifiant. |

## Réponse complète

Les propriétés historiques `ok`, `linked`, `crm_contact_id`, `trainee`, `cnaps` et `card_pro` sont inchangées. Seule `vae` est ajoutée.

```json
{
  "ok": true,
  "linked": true,
  "crm_contact_id": "contact-42",
  "trainee": {
    "id": "TRN-12345678",
    "url": "https://gestionstagiaires-r5no.onrender.com/stagiaires/TRN-12345678",
    "session_name": "DIRIGEANT VAE septembre 2026",
    "session_start": "2026-09-01"
  },
  "cnaps": {"status": "TRANSMIS", "history": []},
  "card_pro": {
    "check_status": "success",
    "checked_at": "2026-08-04T08:00:00+00:00",
    "message": null,
    "titles": [{
      "code": "CP SH", "label": "Carte professionnelle - Surveillance humaine ou gardiennage",
      "status": "ACTIF", "display_status": "CP SH ACTIF", "valid_until": "2031-06-30",
      "expires_before_training": false
    }]
  },
  "vae": {
    "applicable": true,
    "training_type": "DIRIGEANT VAE",
    "status_code": "livret_2_analysis",
    "status_label": "Réception livret 2",
    "progress_percent": 65,
    "is_terminal": false,
    "is_success": false,
    "is_blocked": false,
    "next_action": {"code": "analyse_livret_2", "label": "Analyser le Livret 2"},
    "updated_at": "2026-08-04T09:32:00+02:00",
    "action_dates": {
      "livret_1_received_at": null,
      "livret_1_validated_at": null,
      "livret_1_transmitted_scotia_at": null,
      "livret_2_received_at": "2026-08-04T09:32:00+02:00",
      "livret_2_validated_at": null,
      "livret_2_transmitted_scotia_at": null,
      "diploma_obtained_at": null
    },
    "recevabilite": {"status_code": "recevable", "status_label": "Recevable", "attestation_available": false},
    "jury": {"scheduled": true, "date": "2026-09-15", "location": null},
    "final_result": {"code": null, "label": null, "diploma_obtained_at": null},
    "complements": {"requested": false, "missing_items_supported": false, "missing_items_count": null, "missing_items": []},
    "scotia": {
      "status_label": "En attente documents complémentaires",
      "status_tone": "warning",
      "comment": "62h Scotia en cours & renvoi L1 M.E"
    },
    "dossier": {
      "found": true, "id": "UUID-DOSSIER", "status_code": "soumis", "status_label": "Soumis",
      "updated_at": "2026-08-04T09:32:00+02:00", "dossier_count": 1, "multiple_dossiers": false,
      "admin_url": "https://gestionstagiaires-r5no.onrender.com/admin/vae/UUID-DOSSIER"
    },
    "trainee_admin_url": "https://gestionstagiaires-r5no.onrender.com/admin/sessions/SESSION-ID/stagiaires/TRN-12345678"
  }
}
```

`card_pro.check_status` vaut `success`, `missing_nub` ou `error`. Chaque titre contient `code`, `label`, `status`, `display_status`, `valid_until` et `expires_before_training`.

## Rattacher un stagiaire existant

`POST /api/integrations/crm/stagiaires/link-existing` rattache une piste CRM à un stagiaire déjà présent, sans créer de stagiaire. La route utilise exactement le même en-tête `Authorization: Bearer <CRM_INTEGRATION_API_TOKEN>` que la consultation.

```json
{
  "crm_contact_id": "identifiant permanent de la piste CRM",
  "prenom": "Jean",
  "nom": "Dupont",
  "email": "jean.dupont@example.com",
  "telephone": "0612345678",
  "source": "integrale_connect"
}
```

`crm_contact_id`, `prenom` et `nom` sont obligatoires, ainsi qu'au moins l'un des champs `email` ou `telephone`. `source` est facultatif. Toutes les valeurs transmises doivent être des chaînes et aucun champ hors contrat n'est accepté.

Le rapprochement est limité aux sessions accessibles à l'intégration et appartenant au partenaire Intégrale. Il ne fait aucune recherche floue :

1. les espaces de l'e-mail sont supprimés, sa casse est ignorée, puis la comparaison est exacte ;
2. le téléphone ne conserve que ses chiffres et les préfixes français `+33`, `0033` et `33` sont ramenés au format national `0…`, puis la comparaison est exacte ;
3. le nom et le prénom sont comparés exactement après retrait des espaces externes, passage en minuscules et normalisation des accents.

L'e-mail est prioritaire sur le téléphone. Si les deux identifient des ensembles différents, la demande est refusée. Une liaison n'est créée que si un unique stagiaire correspond et si son nom et son prénom sont cohérents. Un `crm_contact_id` déjà rattaché au même stagiaire rend l'appel idempotent : la réponse vaut `200` avec `link_created: false`. Une création de liaison réussie vaut `200` avec `link_created: true`. Dans les deux cas, le reste de la réponse (`trainee`, `cnaps`, `card_pro` et `vae`) est strictement au même format que celui du `GET` documenté ci-dessus.

| Code | `reason` | Signification |
|---:|---|---|
| `200` | — | Liaison créée ou liaison identique déjà existante. |
| `400` | `invalid_request` | JSON invalide, type/champ non autorisé ou champ obligatoire absent. |
| `401` | — | Bearer absent/invalide ou secret serveur non configuré. |
| `404` | `trainee_not_found` | Aucun stagiaire accessible ne correspond exactement. |
| `409` | `conflicting_matches` | L'e-mail et le téléphone désignent des stagiaires différents. |
| `409` | `ambiguous_match` | Plusieurs stagiaires correspondent. |
| `409` | `identity_mismatch` | Le nom ou le prénom n'est pas cohérent avec le résultat. |
| `409` | `crm_contact_id_already_used` | L'identifiant CRM est déjà rattaché à un autre stagiaire. |
| `409` | `trainee_already_linked` | Le stagiaire correspondant possède déjà un autre identifiant CRM. |
| `500` | `storage_error` | La sauvegarde sécurisée n'a pas abouti. |

La liaison conserve tous les champs existants, notamment le dossier, le statut et les dates VAE. Elle renseigne `crm_source` avec `integrale_connect` uniquement si cette propriété est vide et ajoute une entrée d'activité sans donnée de contact.

## Applicabilité et champs VAE

Le parcours est applicable **uniquement** si `session.training_type` vaut exactement `DIRIGEANT VAE`. Un nom de session contenant « VAE » ne suffit pas. Pour toute autre formation, l'objet complet est :

```json
{"vae": {"applicable": false}}
```

Pour un parcours applicable, les champs sont : statut canonique et libellé serveur, progression et indicateurs calculés, prochaine action, dernière mise à jour fiable, sept dates d'action, recevabilité, jury, résultat final, compléments, dossier administratif et URL administrative du stagiaire. Une valeur indisponible vaut `null`, et non une chaîne vide.

### Statut et commentaire SCOTIA

`vae.scotia` est additif et contient `status_label`, `status_tone` et `comment`. Le libellé et le tone proviennent exactement du helper commun qui construit `trainee.scotia_admin_status` pour la liste administrative des stagiaires ; l'API ne maintient donc aucune table de correspondance SCOTIA parallèle. En l'absence de statut, le libellé vaut `""` et le tone neutre vaut `"grey"` (ou la valeur neutre produite par le helper administratif).

Le commentaire provient exclusivement de `trainee.comment`, le même champ que la colonne « Commentaire » de cette liste. Son contenu, y compris ses retours à la ligne et d'éventuels caractères HTML, est rendu comme une chaîne JSON sans transformation ; seule une valeur absente ou `null` devient `""`.

### Statuts, progression et prochaine action

Le pourcentage indique l'étape atteinte, pas une probabilité de réussite.

| `status_code` | Libellé canonique | % | `next_action.code` | `next_action.label` |
|---|---|---:|---|---|
| `livret_1_todo` | Livret 1 à compléter | 10 | `complete_livret_1` | Compléter le Livret 1 |
| `livret_1_analysis` | Livret 1 en cours d'analyse | 20 | `analyse_livret_1` | Analyser le Livret 1 |
| `non_recevable` | Non recevable | 20 | `null` | `null` |
| `complement_requested` | Demande de complément en cours | 20 | `provide_complements` | Transmettre les compléments demandés |
| `livret_1_validated` | Livret 1 validé | 30 | `validate_financing` | Valider le financement |
| `financement_validated` | Financement validé | 40 | `complete_livret_2` | Compléter le Livret 2 |
| `livret_2_todo` | Livret 2 à compléter | 50 | `complete_livret_2` | Compléter le Livret 2 |
| `livret_2_analysis` | Réception livret 2 | 65 | `analyse_livret_2` | Analyser le Livret 2 |
| `livret_2_validated` | Livret 2 validé | 75 | `validate_livret_2_financing` | Valider le financement du Livret 2 |
| `financement_l2_validated` | Financement L2 validé | 85 | `schedule_jury` | Planifier le passage devant le jury |
| `jury` | Passage devant le jury | 95 | `jury` | Passage devant le jury |
| `certified` | Diplôme obtenu | 100 | `null` | `null` |

`non_recevable` est terminal, bloqué et non réussi. `certified` est terminal et réussi. `complement_requested` est non terminal mais bloqué. Tous les autres statuts ont les trois indicateurs à `false`. Les alias historiques sont normalisés par le serveur avant calcul.

### Recevabilité, résultat et compléments

`recevabilite.status_code` donne priorité à l'état opérationnel `non_recevable`, puis reprend `statut_dossier` (`recevable`, `refuse`, `soumis`, `brouillon` ou une valeur connue). Une décision de faisabilité n'est jamais convertie en recevabilité. `attestation_available` indique seulement la présence du livrable.

Le seul résultat final fiable est `certified` / `Diplôme obtenu`; tout autre statut produit trois valeurs `null`. `complements.requested` est vrai uniquement pour `complement_requested`. La liste métier des pièces manquantes n'étant pas structurée, `missing_items_supported` reste faux, le compteur reste `null` et la liste reste vide.

### Dossier métier courant ou absent

Sans dossier, le statut opérationnel demeure disponible et `dossier` vaut :

```json
{"found": false, "id": null, "status_code": null, "status_label": null, "updated_at": null,
 "dossier_count": 0, "multiple_dossiers": false, "admin_url": null}
```

Les dossiers sont d'abord associés par `meta.trainee_id`. Les dossiers dont `meta.session_id` correspond exactement à la session consultée sont prioritaires et constituent seuls le périmètre retenu dès qu'il en existe au moins un. Les dossiers historiques dont `meta.session_id` est absent ou vide ne servent que de fallback lorsqu'aucun dossier de la session exacte n'existe ; ils ne sont jamais additionnés à ceux de la session. Un dossier rattaché à une autre session est toujours exclu.

Pour le CRM, une paire `meta.trainee_id` / `meta.session_id` représente exactement **un dossier VAE métier courant**. Plusieurs enregistrements techniques ou historiques peuvent porter des `dossier.id` ou `meta.linkage_id` différents sans être comptés comme plusieurs dossiers métier simultanés. Dès qu'au moins un enregistrement appartient au périmètre retenu, `dossier_count` vaut `1` et `multiple_dossiers` vaut `false`.

Le dossier canonique retourné est celui dont `updated_at` est le plus récent ; `created_at` sert de fallback lorsqu'`updated_at` est absent. Les formats de dates historiques restent normalisés par les règles existantes et les égalités sont départagées de manière stable et déterministe. Cette sélection est strictement une projection de lecture : elle ne supprime, ne fusionne et ne modifie aucun enregistrement source. `updated_at` global est la date fiable la plus récente parmi dossier, actions et jury ; une consultation ne le modifie jamais.

## Sécurité et confidentialité

- Le Bearer existant est comparé côté serveur au secret `CRM_INTEGRATION_API_TOKEN`; aucun nouveau secret n'est introduit.
- La recherche est limitée aux sessions du partenaire autorisé par cette intégration.
- Les URL retournées pour le suivi sont des routes administratives. La route publique de possession `/vae/<id>` n'est jamais exposée.
- La réponse ne contient ni `public_token`, ni `trainee_token`, ni documents ou pièces jointes, ni expériences, contenu rédactionnel des livrets, données personnelles complètes, notes SCOTIA, motivation ou avis interne détaillé. La seule exception documentaire est `vae.scotia.comment`, explicitement issu de `trainee.comment` selon le contrat ci-dessus.
- Le CRM est une interface de consultation : cette API `GET` ne modifie ni le stagiaire ni son dossier, et Gestion Stagiaires demeure la source officielle.
- Les réponses du `GET` portent `Cache-Control: no-store` afin qu'une actualisation ne réutilise pas une représentation mise en cache.
