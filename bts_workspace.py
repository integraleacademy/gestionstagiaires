"""Register the independent BTS application in the existing Gunicorn entrypoint.

No writes to AKTO, Qonto, Yousign or the historical data.json. All remote calls
are explicit administrative POST actions. Rendering bypasses legacy navigation
context processors so opening a BTS dossier does not load historical sessions.
"""
from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import hmac
import json
import os
import secrets
from contextlib import contextmanager
from functools import wraps
from urllib.parse import urlparse

from flask import abort, flash, jsonify, make_response, redirect, request, session, url_for

from akto_bts import AktoApiError, AktoClient, AktoConfig, AktoConfigurationError
from wedof_service import WedofApiError, WedofConfigurationError
from wedof_bts import WedofBtsClient
from wedof_bts_sync import public_state, sync_step
from bts_workspace_store import (
    ALL_FIELDS, CHECKLIST, FEE_LABELS, FIELD_GROUPS, TABS, EditConflict,
    WorkspaceError, WorkspaceStore, billing_view, date_fr, euros, euros_cents,
    now, remote_number,
)

VERSION = "20260910-bts-wedof-2"


def configuration_id(config: AktoConfig) -> str:
    return hashlib.sha256(json.dumps(dataclasses.asdict(config), sort_keys=True).encode()).hexdigest()


def connection_config() -> AktoConfig:
    config = AktoConfig.from_env()
    config.require_ready()
    # Never send CFA/software credentials over HTTP or follow an embedded login.
    for value in (config.api_base_url, config.oauth_token_url):
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
            raise WorkspaceError("Les adresses AKTO doivent être des URL HTTPS sans identifiants intégrés.")
    return dataclasses.replace(config, timeout_seconds=min(config.timeout_seconds, 12))


def register_bts_workspace(legacy):
    app = legacy.app
    if app.extensions.get("bts_workspace"):
        return
    app.extensions["bts_workspace"] = {"version": VERSION}
    endpoints = {"admin_bts"}

    def store():
        return WorkspaceStore(legacy.AKTO_BTS_DB_FILE)

    def actor():
        return str(session.get("admin_username") or session.get("admin_email") or "Équipe Intégrale")[:120]

    def csrf_token():
        if not session.get("bts_csrf_token"):
            session["bts_csrf_token"] = secrets.token_urlsafe(32)
        return session["bts_csrf_token"]

    def protected(function, *, write=False):
        @wraps(function)
        def checked(*args, **kwargs):
            if write:
                actual = request.form.get("bts_csrf_token", "")
                expected = session.get("bts_csrf_token", "")
                if not expected or not hmac.compare_digest(str(actual), str(expected)):
                    abort(400, description="La session du formulaire a expiré. Rechargez la page puis réessayez.")
            return function(*args, **kwargs)
        wrapped = legacy.require_super_admin(checked)
        if write:
            wrapped = legacy.admin_write_required(wrapped)
        return legacy.admin_login_required(wrapped)

    def render(screen, **context):
        config = AktoConfig.from_env()
        diagnostic = store().diagnostic()
        if diagnostic and diagnostic.get("configuration_id") != configuration_id(config):
            diagnostic = None
        # Jinja globals still supply url_for, request, session and flashed messages.
        # No legacy context processor is invoked here: BTS stays independent.
        html = app.jinja_env.get_template("bts/workspace.html").render(
            screen=screen, version=VERSION, tabs=TABS, field_groups=FIELD_GROUPS,
            checklist=CHECKLIST, fee_labels=FEE_LABELS, csrf_token=csrf_token(),
            euros=euros, cents=euros_cents, date_fr=date_fr,
            config=config.diagnostics(), diagnostic=diagnostic,
            wedof_ready=bool(os.environ.get("WEDOF_API_KEY", "").strip()),
            wedof_sync=public_state(store().wedof_state()),
            wedof_diagnostic=wedof_diagnostic(),
            running=legacy._akto_bts_sync_is_running(),
            **context,
        )
        return make_response(html)

    def wedof_config_id():
        return hashlib.sha256(os.environ.get("WEDOF_API_KEY", "").strip().encode()).hexdigest()

    def wedof_diagnostic():
        result = store().wedof_state("connection")
        return result if result.get("configuration_id") == wedof_config_id() else {}

    def get_record(record_id):
        try:
            result = store().record(record_id)
        except WorkspaceError:
            abort(404)
        if result is None:
            abort(404)
        return result

    def detail_context(record):
        billing = billing_view(record)
        draft_keys = {draft["schedule_key"] for draft in record["drafts"] if draft["payer"] == "opco"}
        for card in billing["cards"]:
            card["draft_exists"] = card["key"] in draft_keys
        fee_totals = {key: sum(fee["amount_cents"] for fee in record["fees"] if fee["nature"] == key) for key in FEE_LABELS}
        for draft in record["drafts"]:
            card = next((card for card in billing["cards"] if card["key"] == draft["schedule_key"]), None)
            draft["needs_review"] = draft["payer"] == "opco" and (card is None or not card["can_draft"] or card["remaining"] != draft["amount_cents"])
        return {"record": record, "billing": billing, "fee_totals": fee_totals}

    @contextmanager
    def api_lock():
        path = legacy.AKTO_BTS_SYNC_LOCK_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = open(path, "a+", encoding="utf-8")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkspaceError("Une opération AKTO est déjà en cours. Réessayez à sa fin.") from None
            yield
        finally:
            handle.close()

    def home():
        try:
            page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            page = 1
        listing = store().listing(request.args.get("q", ""), request.args.get("source", ""), page)
        return render("home", title="Dossiers d’apprentissage", listing=listing)

    def new_dossier():
        if request.method == "POST":
            try:
                record_id = store().create_local(request.form, actor())
                flash("Dossier créé. Vous pouvez compléter l’étudiant, l’entreprise et le contrat sans attendre AKTO.", "success")
                return redirect(url_for("bts_dossier", record_id=record_id, tab="etudiant"))
            except WorkspaceError as exc:
                flash(str(exc), "error")
                response = render("new", title="Nouveau dossier", values=request.form)
                response.status_code = 422
                return response
        return render("new", title="Nouveau dossier", values={})

    def dossier(record_id):
        record = get_record(record_id)
        tab = request.args.get("tab", "comptabilite" if record["source"] in {"akto", "wedof"} else "suivi")
        if tab not in {key for key, _ in TABS}:
            tab = "suivi"
        return render("dossier", title=record["name"], tab=tab, **detail_context(record))

    def save_dossier(record_id):
        record = get_record(record_id)
        tab = request.form.get("tab", "etudiant")
        if tab not in FIELD_GROUPS:
            abort(400)
        try:
            revision = int(request.form.get("revision", "-1"))
            fields = {name: request.form.get(name, "") for name, _, _ in FIELD_GROUPS[tab]}
            store().save_fields(record_id, fields, revision, actor())
            flash("Informations enregistrées dans votre espace BTS.", "success")
        except (WorkspaceError, ValueError) as exc:
            flash(str(exc) if isinstance(exc, WorkspaceError) else "Version du formulaire invalide.", "error")
            # Keep the submitted values visible, but do not overwrite a concurrent edit.
            record["form_values"] = dict(request.form)
            response = render("dossier", title=record["name"], tab=tab, **detail_context(record))
            response.status_code = 409 if isinstance(exc, EditConflict) else 422
            return response
        return redirect(url_for("bts_dossier", record_id=record_id, tab=tab))

    def save_notes(record_id):
        get_record(record_id)
        try:
            store().annotate(record_id, request.form.get("notes", ""), request.form.getlist("checked"),
                             int(request.form.get("revision", "-1")), actor())
            flash("Suivi interne enregistré. Aucun statut OPCO n’a été modifié.", "success")
        except (WorkspaceError, ValueError) as exc:
            flash(str(exc) if isinstance(exc, WorkspaceError) else "Version du suivi invalide.", "error")
            record = get_record(record_id)
            record["annotation"]["notes"] = request.form.get("notes", "")
            record["annotation"]["revision"] = request.form.get("revision", "-1")
            record["checked"] = request.form.getlist("checked")
            response = render("dossier", title=record["name"], tab="gestion", **detail_context(record))
            response.status_code = 409 if isinstance(exc, EditConflict) else 422
            return response
        return redirect(url_for("bts_dossier", record_id=record_id, tab="gestion"))

    def add_fee(record_id):
        get_record(record_id)
        try:
            store().add_fee(record_id, request.form.get("nature", ""), request.form.get("amount"), request.form.get("description", ""), actor())
            flash("Frais annexe enregistré localement. Il n’est pas encore transmis ni accepté par AKTO.", "success")
        except WorkspaceError as exc:
            flash(str(exc), "error")
        return redirect(url_for("bts_dossier", record_id=record_id, tab="comptabilite"))

    def add_draft(record_id):
        get_record(record_id)
        try:
            store().create_invoice_draft(record_id, request.form.get("payer", ""), request.form.get("schedule_key", ""),
                                         request.form.get("amount"), request.form.get("description", ""), actor())
            flash("Brouillon de facture enregistré. Aucune facture n’a été émise ou transmise.", "success")
        except WorkspaceError as exc:
            flash(str(exc), "error")
        return redirect(url_for("bts_dossier", record_id=record_id, tab="comptabilite", payer=request.form.get("payer", "opco")))

    def remove_item(record_id):
        get_record(record_id)
        try:
            store().remove_local_item(record_id, request.form.get("item_id", ""), request.form.get("kind", ""), actor())
            flash("Élément local supprimé. Les données AKTO restent inchangées.", "success")
        except WorkspaceError as exc:
            flash(str(exc), "error")
        return redirect(url_for("bts_dossier", record_id=record_id, tab="comptabilite", payer=request.form.get("payer", "opco")))

    def settings():
        return render("settings", title="Connexion AKTO")

    def wedof_test():
        result = {"ok": False, "checked_at": now(), "configuration_id": wedof_config_id()}
        client = None
        try:
            with api_lock():
                client = WedofBtsClient()
                items, more, total = client.contracts_page(limit=1)
                result.update(ok=True, total=total, sample_count=len(items),
                              message=(f"Lecture AKTO via WEDOF vérifiée : {total} contrat(s) annoncé(s)." if total is not None
                                       else "Lecture des contrats AKTO via WEDOF vérifiée."))
        except (WedofApiError, WedofConfigurationError, WorkspaceError) as exc:
            result["message"] = str(exc)
        except Exception:
            app.logger.error("[BTS_WEDOF] connection_test_failed")
            result["message"] = "La lecture WEDOF n’a pas pu être vérifiée. Réessayez plus tard."
        finally:
            if client:
                client.close()
        store().save_wedof_state(result, "connection")
        flash(result["message"], "success" if result["ok"] else "error")
        return redirect(url_for("bts_settings"))

    def wedof_sync_step():
        client = None
        action = request.form.get("action", "start")
        if action not in {"start", "resume", "continue"}:
            abort(400)
        try:
            with api_lock():
                client = WedofBtsClient()
                result = sync_step(store(), client, actor(), config_id=wedof_config_id(), action=action,
                                   run_id=request.form.get("run_id", ""), revision=int(request.form.get("revision", "-1")))
            if request.headers.get("Accept") == "application/json":
                return jsonify(result)
            flash(result.get("message", "Synchronisation préparée."), "info")
        except (WedofApiError, WedofConfigurationError, WorkspaceError, ValueError) as exc:
            message = str(exc) if not isinstance(exc, ValueError) or isinstance(exc, WorkspaceError) else "Paramètres de synchronisation invalides."
            if request.headers.get("Accept") == "application/json":
                return jsonify(status="paused", message=message), 409
            flash(message, "error")
        except Exception:
            app.logger.error("[BTS_WEDOF] sync_step_failed")
            if request.headers.get("Accept") == "application/json":
                return jsonify(status="paused", message="Import interrompu. Les contrats déjà enregistrés sont conservés ; vous pouvez reprendre."), 500
            flash("Import interrompu. Les contrats déjà enregistrés sont conservés.", "error")
        finally:
            if client:
                client.close()
        return redirect(url_for("admin_bts"))

    def refresh_wedof_record(record):
        client = None
        try:
            with api_lock():
                client = WedofBtsClient()
                key = record["working_contract_id"]
                summary = client.contract(key)
                store().upsert_wedof_summary(summary, actor())
                if summary.get("registration_id"):
                    fields = client.folder(summary["registration_id"])
                    store().update_wedof_details(key, {**fields, "needs_detail": False})
                try:
                    fields = client.raw(key, summary)
                    store().update_wedof_details(key, fields)
                    flash("Contrat et données OPCO disponibles actualisés via WEDOF.", "success")
                except WedofApiError as exc:
                    store().update_wedof_details(key, {"raw_error": exc.user_message})
                    flash("Contrat actualisé. Données OPCO détaillées non récupérées : " + exc.user_message, "info")
        except (WedofApiError, WedofConfigurationError, WorkspaceError) as exc:
            flash(str(exc), "error")
        except Exception:
            app.logger.error("[BTS_WEDOF] refresh_failed")
            flash("Actualisation interrompue. Les données enregistrées sont conservées.", "error")
        finally:
            if client:
                client.close()
        return redirect(url_for("bts_dossier", record_id=record["id"], tab="comptabilite"))

    def test_connection():
        initial = AktoConfig.from_env()
        result = {"ok": False, "stage": "configuration", "checked_at": now(), "configuration_id": configuration_id(initial)}
        client = None
        try:
            config = connection_config()
            with api_lock():
                client = AktoClient(config)
                result["stage"] = "authentification"
                client._get_access_token()
                result["stage"] = "acces_dossiers"
                payload = client._page_container(client._request_json("/v2/dossiers/etats", params={"numeroPage": 1}))
                if not isinstance(payload.get("EtatDossierResult"), list):
                    raise WorkspaceError("AKTO a répondu, mais le format des dossiers ne correspond pas à la norme attendue.")
                result.update(ok=True, stage="lecture_verifiee", message="Authentification acceptée et lecture des états des dossiers vérifiée. Aucun contrat n’a été envoyé.")
        except AktoConfigurationError:
            result["message"] = "Configuration incomplète : renseignez les paramètres AKTO manquants dans Render."
        except AktoApiError as exc:
            result["message"] = f"AKTO refuse ou ne termine pas le contrôle ({exc.code}" + (f", HTTP {exc.status_code}" if exc.status_code else "") + "). Aucune donnée n’a été modifiée."
        except WorkspaceError as exc:
            result["message"] = str(exc)
        except Exception:
            app.logger.error("[BTS_WORKSPACE] connection_test_failed")
            result["message"] = "Le contrôle n’a pas pu aboutir. Aucun secret ni détail de dossier n’est exposé."
        finally:
            if client is not None:
                client.http.close()
        store().save_diagnostic(result)
        flash(result["message"], "success" if result["ok"] else "error")
        return redirect(url_for("bts_settings"))

    def refresh_record(record_id):
        record = get_record(record_id)
        if record["source"] == "wedof":
            return refresh_wedof_record(record)
        if record["source"] != "akto":
            flash("Ce dossier local n’a pas encore de référence AKTO. Aucun envoi n’a été effectué.", "info")
            return redirect(url_for("bts_dossier", record_id=record_id))
        client = None
        try:
            config = connection_config()
            with api_lock():
                client = AktoClient(config)
                number = remote_number(record_id)
                detail = client.get_dossier(number)
                store().update_remote_detail(number, detail, actor())
            flash("Ce dossier et ses échéances ont été actualisés depuis AKTO. Les factures conservent leur date de dernière synchronisation.", "success")
        except AktoConfigurationError:
            flash("Connexion AKTO incomplète. Les données existantes sont conservées.", "error")
        except (AktoApiError, WorkspaceError) as exc:
            flash(str(exc) if isinstance(exc, WorkspaceError) else "AKTO n’a pas permis l’actualisation. Les données existantes sont conservées.", "error")
        except Exception:
            app.logger.error("[BTS_WORKSPACE] targeted_refresh_failed")
            flash("Actualisation impossible. Le cache existant est conservé.", "error")
        finally:
            if client is not None:
                client.http.close()
        return redirect(url_for("bts_dossier", record_id=record_id, tab="comptabilite"))

    def export():
        response = make_response(json.dumps(store().export_workspace(), ensure_ascii=False, indent=2))
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        response.headers["Content-Disposition"] = 'attachment; filename="espace-bts-export.json"'
        return response

    def export_draft(record_id, draft_id):
        record = get_record(record_id)
        draft = next((item for item in record["drafts"] if item["id"] == draft_id), None)
        if draft is None:
            abort(404)
        payload = {"nature": "BROUILLON_NON_EMIS_NON_TRANSMIS", "dossier": record["name"], "brouillon": draft}
        response = make_response(json.dumps(payload, ensure_ascii=False, indent=2))
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        response.headers["Content-Disposition"] = f'attachment; filename="{draft_id}.json"'
        return response

    def full_sync():
        return legacy.admin_bts_akto_sync()

    routes = [
        ("/admin/BTS/nouveau", "bts_new", new_dossier, ["GET"], False),
        ("/admin/BTS/nouveau", "bts_create", new_dossier, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>", "bts_dossier", dossier, ["GET"], False),
        ("/admin/BTS/dossiers/<record_id>/enregistrer", "bts_save", save_dossier, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>/suivi", "bts_notes", save_notes, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>/frais", "bts_fee", add_fee, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>/brouillons", "bts_draft", add_draft, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>/supprimer-element", "bts_remove", remove_item, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>/actualiser", "bts_refresh", refresh_record, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>/brouillons/<draft_id>.json", "bts_draft_export", export_draft, ["GET"], False),
        ("/admin/BTS/connexion", "bts_settings", settings, ["GET"], False),
        ("/admin/BTS/connexion/tester", "bts_test_connection", test_connection, ["POST"], True),
        ("/admin/BTS/wedof/tester", "bts_wedof_test", wedof_test, ["POST"], True),
        ("/admin/BTS/wedof/synchroniser", "bts_wedof_sync", wedof_sync_step, ["POST"], True),
        ("/admin/BTS/synchroniser", "bts_sync", full_sync, ["POST"], True),
        ("/admin/BTS/export.json", "bts_export", export, ["GET"], False),
        ("/admin/bts", "bts_lowercase", lambda: redirect(url_for("admin_bts")), ["GET"], False),
    ]
    app.view_functions["admin_bts"] = protected(home)
    for path, endpoint, function, methods, write in routes:
        endpoints.add(endpoint)
        app.add_url_rule(path, endpoint, protected(function, write=write), methods=methods)
    forbidden = getattr(legacy, "PARTNER_SPACE_FORBIDDEN_ENDPOINTS", None)
    if isinstance(forbidden, set):
        forbidden.update(endpoints)

    @app.after_request
    def bts_no_cache(response):
        if request.endpoint in endpoints:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
