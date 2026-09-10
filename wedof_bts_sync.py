"""Resumable explicit import; one catalogue page or three dossier reads per POST.

State and cache live in the dedicated BTS SQLite DB. A file lock in the routes
serialises steps; revision tokens make duplicate browser requests idempotent.
Opening a page never starts or resumes API work.
"""
import uuid

from wedof_bts import stamp
from wedof_service import WedofApiError

PUBLIC_KEYS = ("id", "revision", "phase", "status", "added", "updated", "unchanged", "discovered",
               "details_done", "details_total", "errors", "requests", "message", "updated_at", "completed_at", "started_at")


def public_state(state):
    return {key: state[key] for key in PUBLIC_KEYS if key in state}


def sync_step(store, client, actor, *, config_id, action="continue", run_id="", revision=-1):
    state = store.wedof_state()
    if action in {"start", "resume"}:
        if not state or state.get("phase") == "complete" or state.get("config_id") != config_id:
            state = {"id": uuid.uuid4().hex, "revision": 0, "phase": "list", "page": 1,
                     "seen": [], "pending": [], "index": 0, "added": 0, "updated": 0, "unchanged": 0,
                     "discovered": 0, "details_done": 0, "details_total": 0, "errors": 0, "requests": 0,
                     "started_at": stamp(), "config_id": config_id}
        state["budget_start"] = state["requests"]
    elif state.get("id") != run_id or state.get("revision") != revision:
        # A retried POST cannot advance the cursor twice.
        return public_state(state)
    if state.get("config_id") != config_id:
        raise WedofApiError("La connexion a changé. Relancez la synchronisation.", "bts_connection_changed")
    if state.get("phase") == "complete":
        return public_state(state)
    state.update(status="running", message="Récupération en cours.")
    try:
        if state["requests"] - state.get("budget_start", 0) >= 80:
            raise WedofApiError("80 lectures ont été effectuées. Cliquez sur Poursuivre pour reprendre ; les plafonds partagés restent appliqués.", "bts_batch_limit")
        if state["phase"] == "list":
            state["requests"] += 1
            items, more, total = client.contracts_page(state["page"])
            keys = [item["working_contract_id"] for item in items]
            if keys and set(keys).issubset(set(state["seen"])):
                raise WedofApiError("WEDOF répète une page déjà reçue. L’import est arrêté et les dossiers conservés.", "repeated_contract_page")
            for item in items:
                key = item["working_contract_id"]
                result = store.upsert_wedof_summary(item, actor)
                if key not in state["seen"]:
                    state[result] += 1
                    state["seen"].append(key)
            state["discovered"] = len(state["seen"])
            if more:
                if state["page"] >= 100:
                    raise WedofApiError("La limite de 100 pages a été atteinte. Le catalogue importé reste disponible.", "bts_page_limit")
                state["page"] += 1
            else:
                if total is not None and total != len(state["seen"]):
                    raise WedofApiError("Le nombre de contrats a changé pendant la lecture. Relancez la liste pour vérifier son intégralité.", "bts_total_changed")
                store.mark_wedof_listing(state["seen"])
                state.update(phase="details", pending=store.wedof_details_pending(state["seen"]), index=0)
                state["details_total"] = len(state["pending"])
        elif state["phase"] == "details":
            for _ in range(3):
                if state["index"] >= len(state["pending"]) or state["requests"] - state.get("budget_start", 0) >= 80:
                    break
                key = state["pending"][state["index"]]
                record = store.record("w-" + key)
                try:
                    if not record or not record.get("registration_id"):
                        raise WedofApiError("Le contrat ne référence pas encore de dossier de formation WEDOF.", "missing_registration_folder")
                    state["requests"] += 1
                    fields = client.folder(record["registration_id"])
                    store.update_wedof_details(key, {**fields, "needs_detail": False})
                except WedofApiError as exc:
                    # Global authentication/quota/network errors stop the batch and retain its cursor.
                    if exc.http_status in {401, 403, 429} or exc.retryable or exc.code in {"wedof_quota_exceeded", "wedof_governor_unavailable"}:
                        raise
                    store.update_wedof_details(key, {"details_error": exc.user_message, "needs_detail": True})
                    state["errors"] += 1
                state["index"] += 1
                state["details_done"] += 1
        if state["phase"] == "details" and state["index"] >= len(state["pending"]):
            state.update(phase="complete", status="complete", completed_at=stamp())
            state["message"] = (f"{state['discovered']} contrat(s) AKTO récupéré(s) : {state['added']} ajouté(s), "
                                f"{state['updated']} actualisé(s), {state['unchanged']} inchangé(s).")
            if not state["discovered"]:
                state["message"] = "WEDOF est accessible mais ne retourne aucun contrat AKTO pour ce compte. Vérifiez la remontée des contrats dans WEDOF."
            if state["errors"]:
                state["message"] += f" {state['errors']} fiche(s) restent à compléter ; leurs contrats sont conservés."
        elif state["phase"] == "list":
            state["message"] = f"{state['discovered']} contrat(s) repéré(s). Lecture de la page suivante…"
        else:
            state["message"] = f"{state['discovered']} contrat(s) récupéré(s). Fiches apprentis : {state['details_done']} / {state['details_total']}."
    except WedofApiError as exc:
        state.update(status="paused", message=exc.user_message, error_code=exc.code)
        if exc.code in {"repeated_contract_page", "bts_total_changed", "bts_page_limit"}:
            # Restart the catalogue on the next explicit click, never erase the cache.
            state.update(page=1, seen=[], added=0, updated=0, unchanged=0, discovered=0)
    state["revision"] += 1
    state["updated_at"] = stamp()
    store.save_wedof_state(state)
    return public_state(state)
