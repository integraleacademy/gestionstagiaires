"""Coordinate the Test V2 operator switch with the production CPF worker."""
from contextlib import closing
import hmac
import os
import re
import time
import uuid

from flask import Blueprint, jsonify, request
import requests

from cpf_provider import (PROD_SERVICE_ID, PROVIDERS, ProviderUnavailable, current_store,
                          on_test_service, provider_operation)
from cpf_transfer_history import TARGETS, historical_delivery, receipt, receipts, respect_native_receipt

CONTROL_URL = "https://gestionstagiaires-r5no.onrender.com/internal/cpf/provider"
SCOPE = "84089988400026"
SECRET_NAME = "CPF_PROVIDER_BRIDGE_KEY"
FOLDER = re.compile(r"[0-9]{6,20}\Z")
RECEIPT_STATES = {"sent", "processing", "uncertain"}
BUSY = "La bascule n’est pas confirmée. Vérifiez la production puis reprenez la bascule."


def production_request(body=None, *, path=""):
    secret = os.environ.get(SECRET_NAME, "")
    if len(secret) < 32:
        raise ProviderUnavailable("La liaison avec la production n’est pas configurée.")
    try:
        response = requests.request("GET" if body is None else "POST", CONTROL_URL + path,
                                    json=body, headers={"X-Cpf-Control": secret}, allow_redirects=False,
                                    timeout=(2, 25 if path == "/entry-pilot" else 5))
        if response.status_code == 409:
            raise ProviderUnavailable("Un traitement est en cours ou le choix a changé. Actualisez puis réessayez.")
        if response.status_code != 200:
            raise ProviderUnavailable(BUSY)
        data = response.json()
    except ProviderUnavailable:
        raise
    except (requests.RequestException, ValueError):
        raise ProviderUnavailable(BUSY) from None
    if (not isinstance(data, dict) or data.get("scope") != SCOPE or data.get("protocol") != 1
            or not isinstance(data.get("provider"), str) or data["provider"] not in PROVIDERS
            or type(data.get("revision")) is not int or data["revision"] < 0):
        raise ProviderUnavailable(BUSY)
    return data


def public_state(state):
    return {"scope": SCOPE, "protocol": 1, "provider": state["provider"], "revision": state["revision"]}


def coordinated_switch(store, target, revision, actor, remote=None):
    if remote is None:
        if not on_test_service():
            return store.switch(target, revision, actor)
        remote = production_request
    if target not in PROVIDERS:
        raise ValueError("Système CPF inconnu.")
    fd = store.lock(exclusive=True)
    try:
        with closing(store.connect()) as db:
            state = store.state(db)
            if state["revision"] != revision:
                raise ProviderUnavailable("Le choix a changé. Actualisez la page.")
            pending = state["pending"]
            if pending and pending["target"] != target:
                raise ProviderUnavailable("Terminez la bascule en attente avant de changer de système.")
            if not pending:
                previous = remote()
                # Persist before sending: a lost reply or process death leaves both
                # local providers fenced until this exact operation is acknowledged.
                with db:
                    db.execute("INSERT INTO pending_provider_switch VALUES (1, ?, ?, ?, ?)",
                               (target, previous["revision"], uuid.uuid4().hex, actor))
                pending = store.state(db)["pending"]
            with db:
                receipts(db)
            transfers = ([list(row) for row in db.execute(
                "SELECT folder,target,state FROM cpf_transfers WHERE state IN ('processing','uncertain','sent')")]
                         if target == "wedof" else [])
            confirmed = remote({"target": target, "revision": pending["remote_revision"],
                                "operation": pending["operation"], "actor": pending["actor"], "receipts": transfers})
            if confirmed.get("operation") != pending["operation"] or confirmed.get("provider") != target:
                raise ProviderUnavailable(BUSY)
            with db:
                store.set_locked(db, target, revision, pending["actor"], record=True)
                db.execute("DELETE FROM pending_provider_switch WHERE id=1")
            return store.state(db)
    finally:
        os.close(fd)


def register_production_control(legacy):
    if os.environ.get("RENDER_SERVICE_ID") != PROD_SERVICE_ID:
        return
    store = current_store()
    bp = Blueprint("cpf_provider_control", __name__, url_prefix="/internal/cpf/provider")

    @bp.before_request
    def authorize():
        expected = os.environ.get(SECRET_NAME, "").encode()
        supplied = request.headers.get("X-Cpf-Control", "").encode()
        if len(expected) < 32 or not hmac.compare_digest(expected, supplied):
            return jsonify(error="forbidden"), 403

    @bp.after_request
    def no_store(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.errorhandler(ProviderUnavailable)
    def busy(_error):
        return jsonify(error="provider_busy"), 409

    @bp.get("")
    def status():
        return jsonify(public_state(store.state()))

    @bp.post("/evidence")
    def cpf_evidence():
        from cpf_production_evidence import read_evidence
        body = request.get_json(silent=True)
        ids = body.get("folders") if isinstance(body, dict) else None
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(i, str) or not FOLDER.fullmatch(i) for i in ids):
            return jsonify(error="invalid_request"), 400
        with provider_operation("integrale"):
            return jsonify(**public_state(store.state()), evidence=read_evidence(legacy, ids))

    @bp.post("/receipt")
    def check_receipt():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="invalid_request"), 400
        folder, target = body.get("folder"), body.get("target")
        if not isinstance(folder, str) or not FOLDER.fullmatch(folder) or not isinstance(target, str) or target not in TARGETS:
            return jsonify(error="invalid_request"), 400
        with provider_operation("integrale"):
            known = receipt(store, folder, target) or historical_delivery(legacy, folder, target)
            return jsonify(**public_state(store.state()), receipt=known)

    @bp.post("")
    def change():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="invalid_request"), 400
        target, revision, operation = body.get("target"), body.get("revision"), body.get("operation")
        actor, transfers = body.get("actor"), body.get("receipts", [])
        if (not isinstance(target, str) or target not in PROVIDERS or type(revision) is not int or revision < 0
                or not isinstance(operation, str) or not re.fullmatch(r"[0-9a-f]{32}", operation)
                or not isinstance(actor, str) or not 1 <= len(actor) <= 254 or not isinstance(transfers, list)):
            return jsonify(error="invalid_request"), 400
        if (target != "wedof" and transfers) or any(
                not isinstance(row, list) or len(row) != 3 or not all(isinstance(x, str) for x in row)
                or not FOLDER.fullmatch(row[0]) or row[1] not in TARGETS or row[2] not in RECEIPT_STATES
                for row in transfers):
            return jsonify(error="invalid_receipts"), 400
        fd = store.lock(exclusive=True)
        try:
            with closing(store.connect()) as db, db:
                db.execute("""CREATE TABLE IF NOT EXISTS applied_provider_switch (
                    id INTEGER PRIMARY KEY CHECK(id=1), operation TEXT NOT NULL, target TEXT NOT NULL)""")
                previous = db.execute("SELECT operation,target FROM applied_provider_switch WHERE id=1").fetchone()
                state = store.state(db)
                if previous and previous["operation"] == operation and previous["target"] == target and state["provider"] == target:
                    return jsonify(**public_state(state), operation=operation)
                if state["revision"] != revision:
                    raise ProviderUnavailable(BUSY)
                receipts(db)
                # Import only anti-duplicate receipts. Names and contact details stay local.
                db.executemany("""INSERT INTO cpf_transfers (folder,target,state,changed) VALUES (?,?,?,?)
                    ON CONFLICT(folder,target) DO UPDATE SET state=excluded.state,changed=excluded.changed
                    WHERE cpf_transfers.state != 'sent'""",
                               ((folder, dest, status, time.time()) for folder, dest, status in transfers))
                state = store.set_locked(db, target, revision, actor, record=True)
                db.execute("INSERT OR REPLACE INTO applied_provider_switch VALUES (1,?,?)", (operation, target))
            return jsonify(**public_state(state), operation=operation)
        finally:
            os.close(fd)

    from cpf_entry_pilot import register_pilot
    register_pilot(legacy, bp, store, public_state, FOLDER)
    legacy.app.register_blueprint(bp)
    legacy._send_wedof_entry_to_crm = respect_native_receipt("crm")(legacy._send_wedof_entry_to_crm)
    legacy._send_wedof_entry_to_salesforce = respect_native_receipt("salesforce")(legacy._send_wedof_entry_to_salesforce)
