"""Dates exposed by EDOF, kept distinct from when a status was first observed."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def stamp(value):
    if not isinstance(value, str) or not 8 <= len(value.strip()) <= 40:
        return ""
    value = value.strip()
    try:
        if len(value) == 10:
            if value[2] in "/.-":
                return datetime.strptime(value, "%d" + value[2] + "%m" + value[2] + "%Y").date().isoformat()
            return date.fromisoformat(value).isoformat()
        if value[2] == "/":
            when = datetime.strptime(value, "%d/%m/%Y %H:%M:%S" if value.count(":") == 2 else "%d/%m/%Y %H:%M")
        else:
            when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=PARIS)
        return when.astimezone(PARIS).isoformat()
    except (ValueError, OverflowError):
        return ""


def first(record, *fields):
    return next((value for field in fields if (value := stamp(record.get(field)))), "")


def instant(value):
    if not value:
        return float("-inf")
    when = datetime.fromisoformat(value)
    return (when if when.tzinfo else when.replace(tzinfo=PARIS)).timestamp()


def display(value):
    if not value:
        return ""
    return datetime.fromisoformat(value).strftime("%d/%m/%Y" if len(value) == 10 else "%d/%m/%Y à %H h %M")


def from_history(raw, normalize):
    events = []
    for field in ("states", "history", "stateDates"):
        history = raw.get(field)
        if isinstance(history, dict):
            history = [{"state": key, "date": val} for key, val in history.items()]
        if not isinstance(history, list):
            continue
        for item in history:
            if not isinstance(item, dict):
                continue
            state = item.get("state") or item.get("currentState") or item.get("status")
            when = first(item, "changingStateDate", "stateDate", "date", "timestamp")
            if isinstance(state, str) and when:
                events.append((normalize(state), when))
    return events


def project(raw, info, solicitations, pending, refused, normalize, request_states):
    events = from_history(raw, normalize)
    current = normalize(raw.get("currentState") or "") if isinstance(raw.get("currentState"), str) else ""
    state_at = first(raw, "changingStateDate") or max(
        (when for state, when in events if state == current), key=instant, default="")
    filed = first(raw, "registrationDate", "submissionDate", "requestDate", "subscriptionDate")
    filed = filed or min((when for state, when in events if state in request_states), key=instant, default="")
    dates = {"filed_at": filed or (state_at if current in request_states else ""), "state_at": state_at,
             "created_at": first(raw, "creationDate", "createdAt", "dateCreated"),
             "billing_at": first(raw, "billingDate") if raw.get("currentBillingState") else "",
             "payment_at": first(raw, "paymentDate", "paidAt"),
             "service_validated_at": first(info, "serviceDoneValidationDate", "validatedServiceDoneDate")}
    if pending or refused:
        statuses = {"inprogress"} if pending else {"refused", "rejected", "denied", "refuse", "refusee"}
        candidates = [s for s in solicitations if isinstance(s, dict) and str(s.get("fundingType")) == "9"
                      and isinstance(s.get("status"), str) and normalize(s["status"]) in statuses]
        def funding_date(item):
            return first(item, "changingStateDate", "inProgressDate", "submissionDate") if pending else first(
                item, "refusalDate", "rejectionDate", "decisionDate", "responseDate", "answerDate", "changingStateDate")
        # A previous refusal must not date a newer, undated solicitation.
        if len(candidates) == 1:
            dates["funding_at"] = funding_date(candidates[0])
            dates["funding_request_at"] = first(candidates[0], "submissionDate")
        elif candidates and all(first(s, "submissionDate") for s in candidates):
            newest = max(instant(first(s, "submissionDate")) for s in candidates)
            latest = [s for s in candidates if instant(first(s, "submissionDate")) == newest]
            dates["funding_request_at"] = first(latest[0], "submissionDate")
            same = {funding_date(s) for s in latest}
            if len(same) == 1:
                dates["funding_at"] = same.pop()
    return {key: value for key, value in dates.items() if value}


def source_dates(row, category):
    kind = category(row)
    state_at = stamp(row.get("state_at")) or stamp(row.get("request_date"))  # Earlier directory snapshots.
    native = category({"state": row.get("state")})
    filed = stamp(row.get("filed_at")) or (state_at if native == "request" else "")
    overlay = {"ft": "funding_at", "ft_refused": "funding_at", "paid": "payment_at",
               "invoiced": "billing_at", "billable": "service_validated_at"}.get(kind)
    exact = stamp(row.get(overlay)) if overlay else ""
    if kind == "paid" and not exact and category({"billing_state": row.get("billing_state")}) == "paid":
        exact = stamp(row.get("billing_at"))
    if not exact and native == kind:
        exact = state_at
    return filed, exact


def stage_key(row, kind):
    return (row.get("funding_request_at") or "") if kind in {"ft", "ft_refused"} else ""


def annotate(rows, saved, checked, category):
    for row in rows:
        filed, exact = source_dates(row, category)
        created = stamp(row.get("created_at"))
        previous = saved.get(row["folder_id"])
        observed = row.get("observed_at") or checked
        if previous:
            filed = filed or previous["filed"]
            created = created or previous["created"]
            key = stage_key(row, row["kind"])
            same = not key or not previous["stage_key"] or key == previous["stage_key"]
            if same and previous["kind"] == row["kind"] and observed >= previous["observed"]:
                exact = exact or previous["exact_at"]
                observed = previous["observed"]
        since = exact or (datetime.fromtimestamp(observed, PARIS).isoformat() if observed else "")
        row.update(filed_label=display(filed or created), creation_only=bool(created and not filed),
                   stage_label=display(since), stage_observed=not exact,
                   stage_exact_label=display(exact),
                   stage_unknown_label=('Date du refus inconnue' if row['kind'] == 'ft_refused' else 'Date de changement inconnue'),
                   filing_order=instant(filed or created), stage_order=instant(since))


def newest_first(rows):
    rows.sort(key=lambda r: (r["filing_order"], r["stage_order"], r["folder_id"]), reverse=True)
