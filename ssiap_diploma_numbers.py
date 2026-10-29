"""Keep issued SSIAP numbers consecutive when examination results are corrected.

Call reconcile inside the same data transaction as the result/number mutation.
Unnumbered candidates are deliberately left alone: previews never issue numbers.
"""
import copy

import ssiap_exam as exam


def eligible(services, training, trainee):
    return (not services._trainee_registration_is_cancelled(trainee)
            and services._ssiap_exam_status(trainee) == "certified"
            and exam.candidate_settings(exam.for_family(training, "ssiap"), trainee)["included"])


def scope(services, data, training):
    owner = training.get("partner_id") or services.INTEGRALE_PARTNER_ID
    trainings = [s for s in data.get("sessions", [])
                 if (s.get("partner_id") or services.INTEGRALE_PARTNER_ID) == owner]
    if owner != services.INTEGRALE_PARTNER_ID and not services._is_partner_data_scope_session():
        container = data.setdefault("partner_scoped_data", {}).setdefault(owner, {})
    else:
        container = data
    return trainings, container.setdefault("ssiap_diploma_sequences", {})


def change_number(services, training, trainee, number, reason):
    old = str(trainee.get("ssiap_diploma_number") or "")
    if old == number:
        return None
    timestamp = services._now_iso()
    if old:
        trainee.setdefault("ssiap_diploma_number_history", []).append({
            "previous_number": old, "number": number, "reason": reason, "at": timestamp,
        })
    if number:
        trainee["ssiap_diploma_number"] = number
        trainee.setdefault("ssiap_diploma_issued_at", timestamp)
    else:
        trainee.pop("ssiap_diploma_number", None)
        trainee.pop("ssiap_diploma_issued_at", None)
    trainee["ssiap_diploma_number_updated_at"] = timestamp
    return {"session_id": str(training["id"]), "trainee_id": str(trainee["id"]),
            "previous_number": old, "number": number}


def reconcile(services, data, training, *, deleted=(), years=()):
    """Compact affected annual series in their existing issuance order.

    Keep the starting offset of an imported series (e.g. 8 after seven historical
    diplomas). Include revoked/deleted numbers when finding that starting point,
    so withdrawing the first or last diploma also releases its number.
    """
    parse = services.SSIAP_DIPLOMA_NUMBER_RE.fullmatch
    affected = services._session_trainees_list(training) + list(deleted)
    matches = [m for t in affected if (m := parse(str(t.get("ssiap_diploma_number") or "").strip()))]
    years = set(years) | {int(m.group(1)) for m in matches}
    if not years:
        return []
    trainings, sequences = scope(services, data, training)
    changes = []
    for year in sorted(years):
        entries = []
        positions = [int(m.group(2)) for m in matches if int(m.group(1)) == year]
        for current in trainings:
            for trainee in services._session_trainees_list(current):
                match = parse(str(trainee.get("ssiap_diploma_number") or "").strip())
                if match and int(match.group(1)) == year:
                    position = int(match.group(2))
                    positions.append(position)
                    entries.append((position, str(current["id"]), str(trainee["id"]), current, trainee))
        if not positions:
            continue
        sequence = min(positions) - 1
        for _, _, _, current, trainee in sorted(entries, key=lambda item: item[:3]):
            if eligible(services, current, trainee):
                sequence += 1
                number = f"083-8323-1-{year}-{sequence:05d}"
                reason = "renumbered_after_exam_correction"
            else:
                number = ""
                reason = "no_longer_certified_or_presented"
            change = change_number(services, current, trainee, number, reason)
            if change:
                changes.append(change)
        if sequence:
            sequences[str(year)] = sequence
        else:
            sequences.pop(str(year), None)
    return changes


def preserve_state(payload, canonical):
    """A legacy form loaded before renumbering must not restore obsolete numbers."""
    current_sessions = {str(s.get("id")): s for s in canonical.get("sessions", [])}
    protected = ("ssiap_diploma_number", "ssiap_diploma_issued_at",
                 "ssiap_diploma_number_history", "ssiap_diploma_number_updated_at")
    for training in payload.get("sessions", []):
        current = current_sessions.get(str(training.get("id")), {})
        trainees = {str(t.get("id")): t for t in current.get("trainees", current.get("stagiaires", []))}
        for trainee in training.get("trainees", training.get("stagiaires", [])):
            saved = trainees.get(str(trainee.get("id")), {})
            if str(saved.get("ssiap_diploma_number_updated_at") or "") <= str(trainee.get("ssiap_diploma_number_updated_at") or ""):
                continue
            for key in protected + ("ssiap_exam_status",):
                if key in saved:
                    trainee[key] = copy.deepcopy(saved[key])
                else:
                    trainee.pop(key, None)
    # These counters are owned by atomic numbering writes, not legacy forms.
    if "ssiap_diploma_sequences" in canonical:
        payload["ssiap_diploma_sequences"] = copy.deepcopy(canonical["ssiap_diploma_sequences"])
