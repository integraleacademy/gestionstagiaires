"""Explicit reference lookup. Only exact matches enter a short-lived preview.

WEDOF has no documented AKTO/DECA number filter on workingContracts. Catalogue
pages are read on demand; unrelated contracts never enter the BTS dossier store.
The route must hold the API lock. A separate, protected POST adds one selection.
"""
import re
import unicodedata
import uuid

from wedof_bts import stamp
from wedof_service import WedofApiError


def reference(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    if len(value) > 120 or not re.fullmatch(r"[\w\s./-]+", value, flags=re.UNICODE):
        raise ValueError("Saisissez un numéro de contrat AKTO ou un numéro DECA valide.")
    normalized = "".join(value.split()).casefold()
    if len(normalized) < 3 or not any(c.isdigit() for c in normalized):
        raise ValueError("Saisissez le numéro complet du contrat AKTO ou du contrat DECA.")
    return normalized


def matches(summary, number):
    for field in ("external_number", "deca_number"):
        try:
            if reference(summary.get(field)) == number:
                return True
        except ValueError:
            pass
    return False


def public_lookup(state):
    result = {key: state[key] for key in (
        "id", "revision", "status", "phase", "number", "message", "requests", "updated_at"
    ) if key in state}
    fields = ("working_contract_id", "external_number", "deca_number", "apprentice_first_name",
              "apprentice_last_name", "employer_name", "employer_siret", "training_title",
              "contract_start", "contract_end", "state_label", "engagement", "details_error")
    result["candidates"] = [{key: item[key] for key in fields if key in item} for item in state.get("candidates", [])] if state.get("status") == "ready" else []
    return result


def search_step(store, client, owner, *, config_id, action="start", number="", run_id="", revision=-1):
    state = store.wedof_lookup(owner)
    if action == "start":
        number = reference(number)
        state = {"id": uuid.uuid4().hex, "revision": 0, "number": number, "config_id": config_id,
                 "phase": "list", "status": "running", "page": 1, "seen": [], "candidates": [],
                 "index": 0, "requests": 0, "budget_start": 0, "total": None}
    elif not state or state.get("id") != run_id or state.get("config_id") != config_id:
        raise ValueError("Cette recherche a expiré ou a été remplacée. Saisissez de nouveau le numéro.")
    elif state["revision"] != revision or state["status"] == "ready":
        return public_lookup(state)
    elif action == "resume":
        state["budget_start"] = state["requests"]
    state.update(status="running", message="Recherche du contrat dans WEDOF…")
    try:
        if state["requests"] - state["budget_start"] >= 20:
            raise WedofApiError("La recherche est en pause après 20 lectures. Vous pouvez la poursuivre ; aucun dossier n’a été ajouté.", "lookup_batch_limit")
        if state["phase"] == "list":
            state["requests"] += 1
            items, more, total = client.contracts_page(state["page"])
            keys = [item["working_contract_id"] for item in items]
            if set(keys) & set(state["seen"]) or (state["total"] is not None and total != state["total"]):
                raise WedofApiError("La liste WEDOF a changé pendant la recherche. Relancez la recherche avec le même numéro.", "lookup_catalog_changed")
            state["seen"].extend(keys)
            state["total"] = total
            state["candidates"].extend(item for item in items if matches(item, state["number"]))
            if len(state["candidates"]) > 20:
                raise WedofApiError("Plus de 20 contrats correspondent. Utilisez le numéro de dossier AKTO pour préciser la recherche.", "lookup_ambiguous")
            if more:
                if state["page"] >= 100:
                    raise WedofApiError("La recherche atteint la limite de 100 pages. Précisez le numéro auprès de WEDOF.", "lookup_page_limit")
                state["page"] += 1
            else:
                if total is not None and total != len(state["seen"]):
                    raise WedofApiError("Le nombre de contrats WEDOF a changé. Relancez la recherche avec le même numéro.", "lookup_catalog_changed")
                state["phase"] = "preview"
        elif state["phase"] == "preview" and state["index"] < len(state["candidates"]):
            candidate = state["candidates"][state["index"]]
            if candidate.get("registration_id"):
                try:
                    state["requests"] += 1
                    candidate.update(client.folder(candidate["registration_id"]))
                except WedofApiError as exc:
                    if exc.retryable or exc.http_status in {401, 403, 429} or exc.code in {"wedof_quota_exceeded", "wedof_governor_unavailable"}:
                        raise
                    candidate["details_error"] = exc.user_message
            else:
                candidate["details_error"] = "WEDOF ne fournit pas encore de fiche apprenti pour ce contrat."
            state["index"] += 1
        if state["phase"] == "preview" and state["index"] >= len(state["candidates"]):
            state.update(status="ready", phase="complete")
            state["message"] = (f"{len(state['candidates'])} contrat(s) trouvé(s). Vérifiez les informations puis ajoutez le dossier choisi."
                                if state["candidates"] else "Aucun contrat ne correspond à ce numéro dans WEDOF. Vérifiez le numéro ; si la connexion AKTO vient d’être activée, réessayez après la synchronisation WEDOF.")
        else:
            state["message"] = "Recherche en cours. Aucun dossier n’est ajouté à cette étape."
    except WedofApiError as exc:
        state.update(status="paused", message=exc.user_message)
        if exc.code in {"lookup_catalog_changed", "lookup_page_limit", "lookup_ambiguous"}:
            state.update(phase="list", page=1, seen=[], candidates=[], index=0, total=None)
    state["revision"] += 1
    state["updated_at"] = stamp()
    store.save_wedof_lookup(owner, state)
    return public_lookup(state)


def add_selection(store, client, state, key, actor, *, config_id, run_id):
    if not state or state.get("id") != run_id or state.get("config_id") != config_id or state.get("status") != "ready":
        raise ValueError("La recherche a expiré ou n’est pas terminée. Recherchez de nouveau le contrat.")
    candidate = next((item for item in state["candidates"] if item["working_contract_id"] == key), None)
    if not candidate:
        raise ValueError("Ce contrat ne fait pas partie des résultats de votre recherche.")
    record_id = "w-" + key
    if store.record(record_id):
        return record_id, False
    summary = client.contract(key)
    if not matches(summary, state["number"]) or summary["summary_hash"] != candidate["summary_hash"]:
        raise ValueError("Le contrat a changé depuis la recherche. Recherchez-le de nouveau avant de l’ajouter.")
    fields = {"needs_detail": True, "details_error": "WEDOF ne fournit pas encore de fiche apprenti pour ce contrat."}
    if summary.get("registration_id"):
        fields = {**client.folder(summary["registration_id"]), "needs_detail": False}
    outcome = store.upsert_wedof_summary(summary, actor, details=fields, only_new=True)
    return record_id, outcome == "added"
