"""Respect portal retry deadlines without imposing an unconditional hour."""
from datetime import datetime
from email.utils import parsedate_to_datetime
import math
import time
from zoneinfo import ZoneInfo

KEY = "edof-throttled"
HISTORY = "edof-throttle-history"


class PortalThrottled(Exception):
    code = "portal_throttled"

    def __init__(self, retry_after):
        super().__init__(self.code)
        self.at = time.time()
        self.recorded = False
        delay = None
        try:
            text = str(retry_after).strip()
            if text.isascii() and text.isdigit():
                delay = int(text)
            else:
                stamp = parsedate_to_datetime(text)
                if stamp.tzinfo is not None:
                    delay = stamp.timestamp() - self.at
        except (ValueError, TypeError, OverflowError):
            pass
        self.explicit = delay is not None
        self.delay = max(1, math.ceil(delay)) if self.explicit else 60

    def remember(self, vault):
        if self.recorded:
            return
        self.recorded = True
        active = vault.get(KEY)
        # Older deployments did not retain Retry-After. Never shorten an unknown deadline.
        if active and not isinstance(active, dict):
            return
        previous = vault.get(HISTORY) or {}
        count = (previous.get("count", 0) + 1) if not active else active.get("count", 1)
        count = min(count, 6)
        if not self.explicit:
            self.delay = min(60 * 2 ** (count - 1), 900)
        until = self.at + self.delay
        source = "portal" if self.explicit else "backoff"
        if active and active.get("until", 0) > until:
            until, source = active["until"], active["source"]
        now = time.time()
        if until <= now:
            return
        vault.put(KEY, {"until":until, "source":source, "count":count}, ttl=until-now)
        vault.put(HISTORY, {"count":count}, ttl=until-now+3600)


def status(vault):
    value = vault.get(KEY)
    if not value:
        return None
    if not isinstance(value, dict):
        return {"source":"legacy", "until":None, "remaining":None}
    remaining = max(0, math.ceil(value["until"] - time.time()))
    return {"source":value["source"], "until":value["until"], "remaining":remaining} if remaining else None


def message(vault):
    pause = status(vault)
    if not pause:
        return "La pause de protection est terminée. Vérifiez le résultat du précédent essai avant toute nouvelle transmission."
    if pause["until"] is None:
        return "EDOF ou EFP limite les requêtes. Une pause est déjà en cours ; son échéance exacte n’a pas été enregistrée par la version précédente. Aucun nouvel envoi n’est lancé pendant cette pause."
    deadline = datetime.fromtimestamp(pause["until"], ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %Hh%M:%S")
    minutes, seconds = divmod(pause["remaining"], 60)
    duration = f"{minutes} min {seconds:02d} s" if minutes else f"{seconds} s"
    reason = "Délai demandé par EDOF/EFP" if pause["source"] == "portal" else "EDOF/EFP n’a pas indiqué de délai ; pause progressive de protection"
    return f"{reason}. Nouvel essai possible à partir du {deadline} (dans {duration}), si le portail accepte de nouveau les requêtes. La proposition n’est pas renvoyée automatiquement."
