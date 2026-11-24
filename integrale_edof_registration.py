"""Create an enrolment from a verified accepted dossier within one local store transaction."""
import datetime as dt
import re
import ssiap_pathways
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
        choice = ssiap_pathways.suggested_choice(row.get("title"))
        if choice and ssiap_pathways.level_one(group):
            days = ssiap_pathways.settings(group)[choice + "_dates"]
            if days:
                first, last = days[0], days[-1]
        exact = bool(first and last and first == start and last == end)
        if last and last < today and not exact:
            continue
        options.append({**group, "registration_start":first, "registration_end":last,
                        "dates_match":exact, "family":family or group.get("training_type") or "Formation"})
    return sorted(options, key=lambda s:(not s["dates_match"], s["registration_start"] or "9999", s.get("name") or ""))


def insert_registration(legacy, data, folder, session_id, fields, trainee):
    """Attach a reviewed standard enrolment and its CPF link in one transaction."""
    from integrale_edof_dashboard import category
    row = canonical_dates(fields)
    if (row.get("folder_id") != folder or category(row) != "accepted"
            or not row.get("session_start_date") or row["session_start_date"] < FIRST_SESSION
            or not all(row.get(k) for k in ("first_name", "last_name", "session_end_date"))):
        raise ValueError("La fiche EDOF doit confirmer le dossier accepté, son identité et ses dates.")
    partner = legacy.INTEGRALE_PARTNER_ID
    group = next((s for s in data.get("sessions", []) if str(s.get("id")) == session_id), None)
    if not group or not any(str(s["id"]) == session_id for s in matching_sessions(data, partner, row)):
        raise ValueError("La session sélectionnée ne correspond pas à la formation du dossier ou n’est plus disponible.")
    if any(x.get("active") and str(x.get("external_id")) == folder for x in data.get("wedof_links", [])):
        raise ValueError("Ce dossier possède déjà une association. Ouvrez sa fiche stagiaire.")
    trainees = legacy._session_trainees_list(group)
    for t in trainees:
        same_name = all(normalized(t.get(k) or t.get(alias) or "") == normalized(trainee.get(k) or "")
                        for k, alias in (("first_name", "prenom"), ("last_name", "nom")))
        same_email = trainee.get("email") and (t.get("email") or t.get("mail") or "").strip().casefold() == trainee["email"].casefold()
        if same_name or same_email:
            raise ValueError("Une inscription existe déjà dans cette session. Utilisez « Associer ce stagiaire ».")
    trainee["financing_type"] = "CPF"
    # SSIAP maintenance has its own reviewed course price. The EDOF amount
    # stays on the source dossier until the administrator allocates funding.
    if not ssiap_pathways.short_course(trainee) and row.get("total_incl") is not None:
        trainee["training_price"] = row["total_incl"]
    trainee["edof_registration"] = {k: v for k, v in row.items() if v is not None and v != ""}
    if save_manual_wedof_link(data, external_id=folder, session_id=session_id, trainee_id=trainee["id"],
                             state="accepted", date_start=row["session_start_date"], date_end=row["session_end_date"]) != "created":
        raise ValueError("Ce dossier possède déjà une association.")
    trainees.insert(0, trainee)
    group["trainees"] = trainees
    group.pop("stagiaires", None)
    legacy._apply_pending_cnaps_imports_for_trainee(data, group, trainee)
    legacy.increment_partner_trainee_usage(data, partner, trainee)
    return {"ok": True}


def create_registration(legacy, folder, session_id, fields):
    """Compatibility for already queued imports; new UI uses the standard form."""
    def apply(data):
        group = next((s for s in data.get("sessions", []) if str(s.get("id")) == session_id), None)
        links = [x for x in data.get("wedof_links", []) if x.get("active") and str(x.get("external_id")) == folder]
        if group and len(links) == 1 and str(links[0].get("session_id")) == session_id and any(
                str(t.get("id")) == str(links[0].get("trainee_id")) for t in legacy._session_trainees_list(group)):
            return data
        if not group:
            raise ValueError("La session sélectionnée n’est plus disponible.")
        choice = ssiap_pathways.suggested_choice(fields.get("title"))
        trainee = legacy._new_session_trainee(group, {**fields, **({"ssiap_pathway": choice} if choice else {})})
        insert_registration(legacy, data, folder, session_id, fields, trainee)
        return data
    return legacy._atomic_update_data(apply)
