"""Account-scoped, paginated automation journal and French presentation."""
from collections import Counter
from contextlib import closing
import datetime as dt
import json
import math
from zoneinfo import ZoneInfo

import edof_automation_audit as audit
import edof_declarations as declarations
import edof_directory as directory
import edof_proposal_jobs as proposals
from integrale_edof_sync import event_tables

PARIS = ZoneInfo("Europe/Paris")
TYPES = {"entry": "Entrée déclarée", "out": "Sortie déclarée", "declared": "Service fait déclaré",
         "billable": "À facturer", "invoiced": "Facturé", "paid": "Payé",
         "proposal": "Proposition au titulaire", "sync": "Synchronisation EDOF", "control": "Contrôle du connecteur"}
RESULTS = {"all": "Tous les résultats", "confirmed": "Confirmées", "observed": "Changements détectés",
           "issues": "Anomalies et blocages", "pending": "En attente ou en cours"}
SOURCES = {"declaration": "Transmission Intégrale EDOF", "proposal": "Proposition depuis Gestion Stagiaires",
           "edof": "Changement détecté dans EDOF", "discovery": "Contrôle des prérequis",
           "connector": "Activité du connecteur", "legacy": "Trace antérieure reprise"}
EXPLANATIONS = {
    "discovery_blocked": "Un blocage est enregistré sur le dossier. Aucune transmission n’a été lancée.",
    "discovery_missing": "La date effective ou le justificatif de réalisation manque. Aucune transmission n’a été lancée.",
    "discovery_review": "Les informations ou justificatifs du dossier doivent être vérifiés avant transmission.",
    "state_observed": "Statut constaté lors de la synchronisation. L’heure indiquée est celle de la détection, pas celle de l’action dans EDOF.",
}
STATUS_LABELS = {"confirmed": "Confirmée", "observed": "Détecté dans EDOF", "queued": "En attente",
                 "sending": "En cours de vérification", "uncertain": "Réception à vérifier", "review": "À vérifier",
                 "paused": "Bloquée / Suspendue", "error": "Échec", "saving": "En cours",
                 "validating": "En cours", "checking": "En cours de vérification"}


def timestamp(value):
    date = dt.datetime.fromtimestamp(value, PARIS)
    return {"date": date.strftime("%d/%m/%Y"), "time": date.strftime("%Hh%M"), "iso": date.isoformat()}


def page(store, owner, snapshot, args):
    from edof_server_test import MESSAGES
    visible = (snapshot or {}).get("rows", {})
    # Initialise each audit alongside the operational table it observes.
    with closing(proposals.database(store.directory)):
        pass
    with closing(store.connect()):
        pass
    with closing(declarations.database(store.directory)) as db:
        with db:
            event_tables(db)
            audit.import_directory_events(db, owner, visible)
        db.execute("ATTACH DATABASE ? AS server_history", (str(store.path),))
        db.create_function("edof_normalized", 1, directory.normalized, deterministic=True)
        # A verified receipt is stronger than a later observation of that same
        # milestone. Retain both in storage but show that milestone only once.
        cte = """WITH raw AS (
            SELECT *, 'd:'||id AS uid FROM main.edof_automation_events WHERE owner=?
            UNION ALL SELECT *, 'j:'||id AS uid FROM server_history.edof_automation_events WHERE owner=?
        ), events AS (
            SELECT *, CASE WHEN status='queued' AND detail NOT IN ('','declaration_exit_confirmed') THEN 'issues'
                WHEN status IN ('review','uncertain','paused','error') THEN 'issues'
                WHEN status IN ('confirmed','observed') THEN status ELSE 'pending' END AS result
            FROM raw e WHERE NOT (status='observed' AND EXISTS (
                SELECT 1 FROM raw r WHERE r.folder=e.folder AND r.kind=e.kind AND r.status='confirmed' AND r.occurred<=e.occurred))
        ) """
        params = [owner, owner]
        where = []
        query = args.get("q", "")[:140].strip()
        if query:
            where.append("instr(edof_normalized(folder||' '||COALESCE(json_extract(context,'$.first_name'),'')||' '||COALESCE(json_extract(context,'$.last_name'),'')||' '||COALESCE(json_extract(context,'$.title'),'')),?)>0")
            params.append(directory.normalized(query))
        dates = {}
        for key, comparison in [("from", ">="), ("until", "<")]:
            value = directory.session_date(args.get(key))
            dates[key] = value
            if value:
                day = dt.date.fromisoformat(value) + dt.timedelta(days=1 if key == "until" else 0)
                where.append(f"occurred {comparison} ?")
                params.append(dt.datetime.combine(day, dt.time(), PARIS).timestamp())
        kind = args.get("type", "all")
        if kind not in TYPES:
            kind = "all"
        result = args.get("result", "all")
        if result not in RESULTS:
            result = "all"
        base = " AND ".join(where) or "1=1"
        type_counts = dict(db.execute(cte + f"SELECT kind,COUNT(*) FROM events WHERE {base} GROUP BY kind", params))
        if kind != "all":
            where.append("kind=?")
            params.append(kind)
        base = " AND ".join(where) or "1=1"
        counts = Counter(dict(db.execute(cte + f"SELECT result,COUNT(*) FROM events WHERE {base} GROUP BY result", params)))
        counts["all"] = sum(counts.values())
        if result != "all":
            where.append("result=?")
            params.append(result)
        base = " AND ".join(where) or "1=1"
        total = counts[result]
        pages = max(1, math.ceil(total / 25))
        number = max(1, min(args.get("page", 1, type=int) or 1, pages))
        records = db.execute(cte + f"SELECT * FROM events WHERE {base} ORDER BY occurred DESC,uid DESC LIMIT 25 OFFSET ?",
                             [*params, (number-1)*25]).fetchall()
        started = db.execute("SELECT value FROM edof_history_meta WHERE name='started'").fetchone()[0]
    entries = []
    for record in records:
        item = dict(record)
        fields = json.loads(item["context"])
        # Enrich old minimal traces without changing their recorded timestamp.
        fields = {**visible.get(item["folder"], {}), **{k:v for k,v in fields.items() if v}}
        note = EXPLANATIONS.get(item["detail"]) or MESSAGES.get(item["detail"])
        if not note:
            note = item["detail"] if item["source"] in {"proposal", "legacy"} and " " in item["detail"] else {
                "queued": "Déclaration préparée et mise en file de transmission.",
                "sending": "Transmission engagée. La réception reste à confirmer par la relecture du dossier.",
                "paused": "Traitement suspendu. Consultez le dossier avant toute reprise.",
            }.get(item["status"], "Consultez le dossier pour retrouver les informations de l’opération.")
        label = "Envoi différé · problème de connexion" if item["status"] == "queued" and item["result"] == "issues" else STATUS_LABELS.get(item["status"], "À vérifier")
        entries.append({**item, **timestamp(item["occurred"]), "fields": fields, "note": note,
                        "label": label, "source_label": SOURCES[item["source"]], "available": item["folder"] in visible})
    return {"entries": entries, "counts": counts, "type_counts": type_counts, "total": total,
            "page": number, "pages": pages, "type": kind, "result": result, "q": query,
            "from": dates["from"], "until": dates["until"], "types": TYPES, "results": RESULTS,
            "started": timestamp(started)}
