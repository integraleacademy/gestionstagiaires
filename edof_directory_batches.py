"""Encrypted, account-bound checkpoints; partial lists are never published."""
import time

PAGES_PER_BATCH = 2
MAX_AGE = 1800


class BatchPending(Exception):
    pass


class Cursor:
    def __init__(self, vault, spec):
        self.vault = vault
        self.key = "directory-batch:" + spec["owner"]
        self.binding = [spec.get("provider"), spec.get("revision"),
                        spec.get("recovery_since"), spec.get("sync_until"),
                        vault.get("directory-generation") or 0]
        saved = vault.get(self.key)
        self.value = saved if (isinstance(saved, dict) and saved.get("binding") == self.binding
                               and time.time()-saved.get("started",0) < MAX_AGE) else None
        if saved and not self.value:
            vault.delete(self.key)

    def save(self, value):
        self.value = {**value, "binding":self.binding,
                      "started":(self.value or {}).get("started", time.time())}
        self.vault.put(self.key, self.value, ttl=MAX_AGE)

    def clear(self):
        self.vault.delete(self.key)
        self.value = None
