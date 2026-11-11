"""Create an enrolment from a verified accepted dossier within one local store transaction."""
import datetime as dt
import re
from zoneinfo import ZoneInfo

from edof_directory import FIRST_SESSION, canonical_dates, normalized, session_date
from wedof_links import save_manual_wedof_link


def eligible_sessions(data, partner_id):
    return [s for s in data.get("sessions", []) if s.get("id") and not (s.get("archived") or s.get("is_archived"))
            and normalized(s.get("status") or "") not in {"archived", "archivee"}
            and (s.get("partner_id") or partner_id) == partner_id]


def training_family(title):
    """Recognize catalogue labels without mixing levels, VAE or combined packs."""
    value = normalized(title or "")
    has = lambda pattern: re.search(pattern, value) is not None
    if has(r"\bvtc\b|voiture de transport avec chauffeur"):
        return "VTC"
    if has(r"\bdesp\b|\bdirigeant\b"):
        return "DIRIGEANT VAE" if has(r"\bvae\b|validation des acquis") else "DIRIGEANT initial"
    if has(r"\ba3p\b|\bapr\b|protection rapprochee|protection physique des personnes"):
        return "A3P"
    if has(r"\bcpsp\b|chef de poste"):
        return "CPSP"
    aps = has(r"\baps\b|agent de prevention et de securite")
    if aps and has(r"\bmac\b|maintien et actualisation"):
        return "MAC APS"
    level = re.search(r"ssiap\s*([123])", value)
    if aps:
        return "APS + SSIAP 1" if "ssiap" in value else "APS"
    if level:
        return "SSIAP " + level[1]
    if "ssiap" in value:
        return "SSIAP"
    return ""


def session_family(group):
    family = training_family(group.get("training_type"))
    if family == "SSIAP":
        return training_family(group.get("name")) or "SSIAP 1"
    return family or training_family(group.get("name"))


def matching_sessions(data, partner_id, row, *, today=None):
    """Current/upcoming compatible sessions; keep exact historical dates for catch-up."""
    today = today or dt.datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    family = training_family(row.get("title"))
    start, end = row.get("session_start_date"), row.get("session_end_date")
    options = []
    for group in eligible_sessions(data, partner_id):
        compatible = session_family(group) == family if family else normalized(group.get("name") or "") == normalized(row.get("title") or "")
        if not compatible or not row.get("title"):
            continue
        first = session_date(group.get("date_start") or group.get("date_debut"))
        last = session_date(group.get("date_end") or group.get("date_fin"))
        exact = bool(first and last and first == start and last == end)
        if last and last < today and not exact:
            continue
        options.append({**group, "registration_start":first, "registration_end":last,
                        "dates_match":exact, "family":family or group.get("training_type") or "Formation"})
    return sorted(options, key=lambda s:(not s["dates_match"], s["registration_start"] or "9999", s.get("name") or ""))


def create_registration(legacy, folder, session_id, fields):
    from integrale_edof_dashboard import category
    row = canonical_dates(fields)
    if (row.get("folder_id") != folder or category(row) != "accepted" or row["session_start_date"] < FIRST_SESSION
            or not all(row.get(k) for k in ("first_name", "last_name", "session_end_date"))):
        raise ValueError("La fiche EDOF doit confirmer le dossier accepté, son identité et ses dates.")
    partner = legacy.INTEGRALE_PARTNER_ID

    def apply(data):
        group = next((s for s in data.get("sessions", []) if str(s.get("id")) == session_id), None)
        if not group:
            raise ValueError("La session sélectionnée n’est plus disponible.")
        trainees = legacy._session_trainees_list(group)
        links = [x for x in data.get("wedof_links", []) if x.get("active") and str(x.get("external_id")) == folder]
        if links:
            if len(links) == 1 and str(links[0].get("session_id")) == session_id and any(
                    str(t.get("id")) == str(links[0].get("trainee_id")) for t in trainees):
                return data
            raise ValueError("Ce dossier possède déjà une association. Vérifiez-la dans la fiche.")
        if not any(str(s["id"]) == session_id for s in matching_sessions(data, partner, row)):
            raise ValueError("La session sélectionnée ne correspond pas à la formation du dossier ou n’est plus disponible.")
        for t in trainees:
            same_name = all(normalized(t.get(k) or t.get(alias) or "") == normalized(row[k])
                            for k, alias in (("first_name","prenom"),("last_name","nom")))
            same_email = row.get("email") and (t.get("email") or t.get("mail") or "").strip().casefold() == row["email"].casefold()
            if same_name or same_email:
                raise ValueError("Une inscription existe déjà dans cette session. Utilisez « Associer ce stagiaire ».")
        trainee = legacy._new_session_trainee(group, row)
        trainee["financing_type"] = "CPF"
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
