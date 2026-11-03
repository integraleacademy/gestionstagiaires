"""Create an enrolment from a verified accepted dossier within one local store transaction."""
from edof_directory import FIRST_SESSION, canonical_dates, normalized
from wedof_links import save_manual_wedof_link


def eligible_sessions(data, partner_id):
    return [s for s in data.get("sessions", []) if s.get("id") and not (s.get("archived") or s.get("is_archived"))
            and normalized(s.get("status") or "") not in {"archived", "archivee"}
            and (s.get("partner_id") or partner_id) == partner_id]


def create_registration(legacy, folder, session_id, fields):
    from integrale_edof_dashboard import category
    row = canonical_dates(fields)
    if (row.get("folder_id") != folder or category(row) != "accepted" or row["session_start_date"] < FIRST_SESSION
            or not all(row.get(k) for k in ("first_name", "last_name", "session_end_date"))):
        raise ValueError("La fiche EDOF doit confirmer le dossier accepté, son identité et ses dates.")
    partner = legacy.INTEGRALE_PARTNER_ID

    def apply(data):
        group = next((s for s in eligible_sessions(data, partner) if str(s["id"]) == session_id), None)
        if not group:
            raise ValueError("La session sélectionnée n’est plus disponible.")
        trainees = legacy._session_trainees_list(group)
        links = [x for x in data.get("wedof_links", []) if x.get("active") and str(x.get("external_id")) == folder]
        if links:
            if len(links) == 1 and str(links[0].get("session_id")) == session_id and any(
                    str(t.get("id")) == str(links[0].get("trainee_id")) for t in trainees):
                return data
            raise ValueError("Ce dossier possède déjà une association. Vérifiez-la dans la fiche.")
        for t in trainees:
            same_name = all(normalized(t.get(k) or t.get(alias) or "") == normalized(row[k])
                            for k, alias in (("first_name","prenom"),("last_name","nom")))
            same_email = row.get("email") and (t.get("email") or t.get("mail") or "").strip().casefold() == row["email"].casefold()
            if same_name or same_email:
                raise ValueError("Une inscription existe déjà dans cette session. Utilisez « Associer ce stagiaire ».")
        trainee = legacy._new_session_trainee(group, row)
        if row.get("total_incl") is not None:
            trainee["training_price"] = row["total_incl"]
        # The official total can include co-financing. Do not assign it all to CPF.
        trainee["edof_registration"] = {k:v for k,v in row.items() if v is not None and v != ""}
        trainees.insert(0, trainee)
        group["trainees"] = trainees
        group.pop("stagiaires", None)
        legacy._apply_pending_cnaps_imports_for_trainee(data, group, trainee)
        legacy.increment_partner_trainee_usage(data, partner, trainee)
        if save_manual_wedof_link(data, external_id=folder, session_id=session_id, trainee_id=trainee["id"],
                                  state="accepted", date_start=row["session_start_date"], date_end=row["session_end_date"]) != "created":
            raise ValueError("Ce dossier possède déjà une association.")
        return data

    legacy._atomic_update_data(apply)
