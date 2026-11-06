"""Durable, process-safe guard for automatic SEPA subscription creation.

The journal is independent of billing snapshots. An uncertain POST is never
repeated: a later call must find the subscription in Qonto or stop for review.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path


def ensure_subscription(directory, identity, payload, find_existing, create):
    root = Path(directory) / "qonto_sepa_creation"
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(identity.encode()).hexdigest()
    path = root / (key + ".json")
    with (root / (key + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = json.loads(path.read_text()) if path.exists() else {}

        def save(value):
            tmp = path.with_suffix(".tmp")
            with tmp.open("w") as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            directory_fd = os.open(root, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

        if record and record.get("payload") != payload:
            raise ValueError("Cette échéance a déjà été programmée avec d’autres paramètres. Vérifiez son suivi Qonto.")
        if record.get("subscription_id"):
            return record["subscription_id"], False
        found = find_existing()
        if found:
            save({"payload": payload, "subscription_id": found})
            return found, False
        if record:
            raise ValueError("Une programmation précédente reste à vérifier dans Qonto. Aucun nouveau prélèvement n’a été créé.")
        save({"payload": payload, "pending": True})
        response = create(payload)
        item = response.get("direct_debit_subscription") or response.get("subscription") or response
        subscription_id = str(item.get("id") or "")
        if not subscription_id:
            raise ValueError("Qonto n’a pas confirmé l’identifiant du prélèvement. Vérifiez Qonto avant toute nouvelle programmation.")
        save({"payload": payload, "subscription_id": subscription_id})
        return subscription_id, True
