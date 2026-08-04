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

## Applicabilité et champs VAE

Le parcours est applicable **uniquement** si `session.training_type` vaut exactement `DIRIGEANT VAE`. Un nom de session contenant « VAE » ne suffit pas. Pour toute autre formation, l'objet complet est :

```json
{"vae": {"applicable": false}}
```

Pour un parcours applicable, les champs sont : statut canonique et libellé serveur, progression et indicateurs calculés, prochaine action, dernière mise à jour fiable, sept dates d'action, recevabilité, jury, résultat final, compléments, dossier administratif et URL administrative du stagiaire. Une valeur indisponible vaut `null`, et non une chaîne vide.

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

### Dossier absent ou multiple

Sans dossier, le statut opérationnel demeure disponible et `dossier` vaut :

```json
{"found": false, "id": null, "status_code": null, "status_label": null, "updated_at": null,
 "dossier_count": 0, "multiple_dossiers": false, "admin_url": null}
```

Les dossiers sont associés par `meta.trainee_id`, puis isolés par `meta.session_id` quand ce dernier existe. Si plusieurs dossiers correspondent, le plus récemment mis à jour (sinon créé) est retenu, `dossier_count` les compte et `multiple_dossiers` vaut `true`. `updated_at` global est la date fiable la plus récente parmi dossier, actions et jury; une consultation ne le modifie jamais.

## Sécurité et confidentialité

- Le Bearer existant est comparé côté serveur au secret `CRM_INTEGRATION_API_TOKEN`; aucun nouveau secret n'est introduit.
- La recherche est limitée aux sessions du partenaire autorisé par cette intégration.
- Les URL retournées pour le suivi sont des routes administratives. La route publique de possession `/vae/<id>` n'est jamais exposée.
- La réponse ne contient ni `public_token`, ni `trainee_token`, ni documents ou pièces jointes, ni expériences, contenu rédactionnel des livrets, données personnelles complètes, notes/commentaires internes, motivation ou avis interne détaillé.
- Le CRM est une interface de consultation : cette API `GET` ne modifie ni le stagiaire ni son dossier, et Gestion Stagiaires demeure la source officielle.
