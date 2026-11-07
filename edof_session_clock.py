"""Observation of the shared EDOF browser. Records only times and event types."""
from datetime import datetime
import sqlite3
import time

from edof_day_session import PARIS, POLL_SECONDS


def clock_key(owner):
    return "edof-session-clock-v1:" + owner


def read_clock(vault, owner):
    try:
        return vault.get(clock_key(owner)) or {}
    except (OSError, sqlite3.Error):
        return {}


def record(vault, owner, event, *, fresh=False, now=None):
    # Writers share the day browser or its recovery lock. Measuring the session
    # must never prevent a directory read or an EDOF declaration.
    if not vault or not owner:
        return
    now = time.time() if now is None else now
    try:
        key = clock_key(owner)
        state = vault.get(key) or {}
        current = state.get("current")
        if event == "verified":
            state.pop("restart_login_day", None)
            if not current or current.get("interrupted"):
                current = state["current"] = {"start":now, "authenticated":fresh}
            current["last"] = max(now, current["start"], current.get("last", 0))
        elif not current or current.get("interrupted"):
            return
        elif event == "server_restart":
            # Only the elected scheduler records a service restart. An expired portal
            # session or a Chromium retry never creates a free authentication.
            day = datetime.fromtimestamp(now, PARIS).date()
            if datetime.fromtimestamp(current["last"], PARIS).date() == day:
                state["restart_login_day"] = day.isoformat()
            current["interrupted"] = True
        elif event == "interrupted":
            current["interrupted"] = True
        elif event == "reauth":
            state["previous"] = {**current, "detected":max(now, current["last"])}
            del state["current"]
        else:
            return
        vault.put(key, state)
    except (OSError, sqlite3.Error):
        pass


def duration(seconds):
    hours, remainder = divmod(max(0, int(seconds)), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def paris_stamp(value):
    return datetime.fromtimestamp(value, PARIS).strftime("%d/%m à %H h %M min %S s")


def legacy_observation(db, owner):
    # Legacy jobs did not distinguish browser restarts from portal expiry.
    # Show their verified span only; never infer an expiry or start a live timer.
    row = db.execute("""SELECT finished FROM jobs WHERE owner=? AND mode='directory'
        AND json_extract(result,'$.session_saved')=1 AND json_extract(result,'$.fresh_session')=1
        AND json_extract(result,'$.gmail_code_used')=1 ORDER BY finished DESC LIMIT 1""", (owner,)).fetchone()
    if not row:
        return {}
    start = last = row["finished"]
    for job in db.execute("""SELECT json_extract(result,'$.session_saved'),json_extract(result,'$.fresh_session'),finished
        FROM jobs WHERE owner=? AND mode='directory' AND finished>? ORDER BY finished""", (owner,start)):
        if job[0] != 1 or job[1] != 0:
            break
        last = job["finished"]
    return {"current":{"start":start, "last":last, "interrupted":True, "authenticated":True, "legacy":True}}


def clock_view(state, now, *, open_now, verified):
    current, previous = state.get("current"), state.get("previous")
    view = {"label":"En attente d’un accès EDOF vérifié", "display":"—", "elapsed":0, "tick_for":0, "confirmed":"—",
            "detail":"La mesure commence à la première lecture confirmée du portail.",
            "previous":"Aucune expiration observée dans une session suivie."}
    if previous:
        start, last, detected = previous["start"], previous["last"], previous["detected"]
        origin = "après l’authentification" if previous["authenticated"] else "depuis le premier accès observé"
        view["previous"] = (f"Reconnexion demandée le {paris_stamp(detected)}. La durée observée {origin} se situe "
                            f"entre {duration(last-start)} et {duration(detected-start)}. "
                            f"Dernier accès confirmé le {paris_stamp(last)}.")
        if not current:
            view.update(label="Dernière session · durée confirmée", display=duration(last-start),
                        detail="Le portail a demandé une nouvelle authentification.")
    if current:
        last, start = current["last"], current["start"]
        # Only extrapolate between normal checks. If an observation goes
        # missing or the watch closes, freeze at the last real success.
        running = open_now and verified and not current.get("interrupted") and 0 <= now-last < POLL_SECONDS*2
        elapsed = int((now if running else last) - start)
        window = max(0,int(POLL_SECONDS*2 - (now-last))) if running else 0
        label = "Session en cours" if running else "Durée confirmée au dernier accès"
        origin = "Authentification confirmée" if current["authenticated"] else "Session déjà ouverte au premier contrôle"
        detail = f"{origin} le {paris_stamp(start)}. Dernier accès vérifié le {paris_stamp(last)}."
        if current.get("legacy"):
            detail += " Mesure issue des anciens contrôles, sans expiration vérifiée."
        elif not running:
            detail += " Le compteur est arrêté au dernier accès vérifié."
        view.update(label=label, detail=detail, display=duration(elapsed), elapsed=elapsed, tick_for=window, confirmed=duration(last-start))
    return view
