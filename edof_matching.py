"""Pure, read-only suggestions from a browser observation and local registrations.

No WEDOF client, external request, business write or automatic association.
Names are useful for suggesting a review, never sufficient to establish a link.
"""

import datetime as dt
import re
import unicodedata


MAX_CANDIDATES = 6


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _id(value):
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ""


def _name(value):
    value = unicodedata.normalize("NFKD", _text(value).casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[’'`\-\s]+", " ", value).strip()


def _email(value):
    return _text(value).casefold()


def _date(value):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(_text(value), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _dates(source, first, last):
    return _date(source.get(first)), _date(source.get(last))


def _remote_dates(observation):
    dates = _dates(observation, "session_start_date", "session_end_date")
    # Do not combine a session boundary with a dossier boundary.
    return dates if all(dates) else _dates(observation, "start_date", "end_date")


def _equal_complete(left, right):
    return left == right if all(left) and all(right) else None


def _session(group):
    archived = bool(group.get("archived") or group.get("is_archived")) or _name(group.get("status")) in {"archived", "archivee"}
    return {
        "session_id": _id(group.get("id")),
        "session_name": _text(group.get("name")),
        "training_type": _text(group.get("training_type")),
        "start_date": _date(group.get("date_start") or group.get("date_debut")),
        "end_date": _date(group.get("date_end") or group.get("date_fin")),
        "archived": archived,
    }


def _registration(group, trainee):
    return {
        **_session(group),
        "trainee_id": _id(trainee.get("id")),
        "first_name": _text(trainee.get("first_name") or trainee.get("prenom")),
        "last_name": _text(trainee.get("last_name") or trainee.get("nom")),
        "email": _text(trainee.get("email") or trainee.get("mail")),
    }


def _checks(candidate, observation, linked_folders):
    identity = _equal_complete(
        (_name(candidate["first_name"]), _name(candidate["last_name"])),
        (_name(observation.get("first_name")), _name(observation.get("last_name"))),
    )
    email = _equal_complete((_email(candidate["email"]),), (_email(observation.get("email")),))
    dates = _equal_complete((candidate["start_date"], candidate["end_date"]), _remote_dates(observation))
    conflicts = linked_folders.get((candidate["session_id"], candidate["trainee_id"]), set()) - {observation.get("folder_id")}
    checks = []
    for key, value, identical, different, missing in (
        ("identity", identity, "Nom et prénom concordants", "Nom ou prénom différent", "Identité incomplète"),
        ("email", email, "E-mail identique", "E-mail différent", "E-mail non comparable"),
        ("dates", dates, "Dates de session identiques", "Dates de session différentes", "Dates non comparables"),
    ):
        checks.append({"key": key, "matches": value,
                       "label": identical if value is True else different if value is False else missing})
    issues = []
    if candidate["archived"]:
        issues.append("Cette session est archivée.")
    if conflicts:
        issues.append("Cette inscription possède déjà un autre lien CPF actif.")
    if not candidate["session_id"] or not candidate["trainee_id"]:
        issues.append("Un identifiant local manque : rattachement impossible en l’état.")
    return {**candidate, "checks": checks, "issues": issues,
            "identity_match": identity, "email_match": email, "dates_match": dates,
            "concordant": identity is True and email is True and dates is True and not issues}


def build_comparison(data, observation):
    """Return bounded proposals and evidence. This function never mutates data."""
    if not isinstance(data, dict) or not isinstance(data.get("sessions", []), list):
        raise ValueError("Invalid local sessions")
    raw_links = data.get("wedof_links", [])
    if not isinstance(raw_links, list):
        raise ValueError("Invalid local links")
    links = [item for item in raw_links if isinstance(item, dict) and item.get("active") is True]
    linked_folders = {}
    for link in links:
        pair = (_id(link.get("session_id")), _id(link.get("trainee_id")))
        if all(pair):
            linked_folders.setdefault(pair, set()).add(_id(link.get("external_id")))
    sessions, registrations = [], []
    for group in data.get("sessions", []):
        if not isinstance(group, dict):
            continue
        sessions.append(_session(group))
        trainees = group.get("trainees", group.get("stagiaires", []))
        if not isinstance(trainees, list):
            continue
        registrations.extend(_registration(group, trainee) for trainee in trainees if isinstance(trainee, dict))

    same_dates = [group for group in sessions
                  if _equal_complete((group["start_date"], group["end_date"]), _remote_dates(observation)) is True]
    same_dates.sort(key=lambda group: (group["archived"], group["session_name"], group["session_id"]))
    result = {"status": "absent", "candidates": [], "candidate_count": 0,
              "session_count": len(sessions), "registration_count": len(registrations),
              "matching_session_count": len(same_dates), "matching_sessions": same_dates[:MAX_CANDIDATES]}
    folder_id = _id(observation.get("folder_id"))
    exact_links = [link for link in links if folder_id and _id(link.get("external_id")) == folder_id]
    # An existing conflict must not silently become a new identity-based suggestion.
    if len(exact_links) > 1:
        return {**result, "status": "ambiguous_link"}
    if exact_links:
        link = exact_links[0]
        matches = [candidate for candidate in registrations
                   if candidate["session_id"] and candidate["trainee_id"]
                   and candidate["session_id"] == _id(link.get("session_id"))
                   and candidate["trainee_id"] == _id(link.get("trainee_id"))]
        if len(matches) != 1:
            return {**result, "status": "ambiguous_link" if matches else "stale"}
        return {**result, "status": "found", "candidate_count": 1,
                "candidates": [_checks(matches[0], observation, linked_folders)]}

    candidates = []
    for registration in registrations:
        candidate = _checks(registration, observation, linked_folders)
        if candidate["identity_match"] is True or candidate["email_match"] is True:
            candidates.append(candidate)
    candidates.sort(key=lambda candidate: (
        not candidate["concordant"], candidate["dates_match"] is not True,
        candidate["identity_match"] is not True, candidate["email_match"] is not True,
        candidate["archived"], candidate["session_name"], candidate["trainee_id"],
    ))
    if len(candidates) == 1:
        result["status"] = "suggested" if candidates[0]["concordant"] else "review"
    elif candidates:
        result["status"] = "ambiguous"
    result.update(candidates=candidates[:MAX_CANDIDATES], candidate_count=len(candidates))
    return result


def manual_options(data, observation, *, query="", pair=None):
    """Recheck a selected local enrolment, including homonyms and existing CPF links."""
    search = _name(query)
    if pair is None and len(search) < 3:
        return []
    links = {}
    for item in data.get("wedof_links", []):
        if isinstance(item, dict) and item.get("active"):
            ids = (_id(item.get("session_id")), _id(item.get("trainee_id")))
            links.setdefault(ids, set()).add(_id(item.get("external_id")))
    results = []
    for group in data.get("sessions", []):
        if not isinstance(group,dict):
            continue
        for trainee in group.get("trainees") or group.get("stagiaires") or []:
            if not isinstance(trainee,dict):
                continue
            reg = _registration(group, trainee)
            ids = reg["session_id"], reg["trainee_id"]
            if pair is not None:
                if ids != pair:
                    continue
            else:
                label = _name(" ".join(reg[k] for k in ("first_name","last_name","session_name","email")))
                if not all(word in label for word in search.split()):
                    continue
            results.append(_checks(reg, observation, links))
            if pair is None and len(results) >= 20:
                return results
    return results
