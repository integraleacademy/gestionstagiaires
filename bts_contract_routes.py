"""Protected BTS candidate import, document generation and contract lifecycle."""
from __future__ import annotations

import hashlib
import io
import os
import re

from flask import abort, flash, jsonify, redirect, request, send_file, url_for

from bts_cerfa import effective_values, readiness
from bts_contract_store import ContractStore
from bts_contract_documents import (DOC_LABELS, SETTINGS_FIELDS, MODES, defaults, validate_settings,
    fingerprint, generate_documents, document_errors, signature_errors)
from bts_contract_yousign import YousignClient, send_signature, refresh_signature, cancel_signature, ensure_files, ACTIVE_SIGNATURE_STATUSES
from bts_contract_wedof import SubmissionClient, advance_submission, check_submission
from bts_inscriptions import InscriptionsClient
from bts_workspace_store import WorkspaceError, now
from wedof_service import WedofApiError, WedofConfigurationError

PORTALS = {"opcoCfaAkto": "https://www.akto.fr/", "opcoCfaEp": "https://www.opcoep.fr/",
           "opcoCfaOpcommerce": "https://www.lopcommerce.com/", "opcoCfaMobilites": "https://www.opcomobilites.fr/"}
SOURCE_LABELS = {"numero_dossier": "Numéro de préinscription", "created_at": "Préinscription créée le", "updated_at": "Dernière mise à jour source",
    "sexe": "Sexe", "ville_naissance": "Ville de naissance", "cp_naissance": "Code postal de naissance", "pays_naissance": "Pays de naissance",
    "nationalite": "Nationalité déclarée", "bts": "BTS demandé", "mode": "Mode de formation", "bac_status": "Statut du baccalauréat",
    "bac_type": "Type de baccalauréat", "bac_autre": "Autre baccalauréat", "baccalaureat": "Baccalauréat", "permis_b": "Permis B",
    "resp_nom": "Nom du représentant légal", "resp_prenom": "Prénom du représentant légal", "resp_email": "E-mail du représentant légal", "resp_tel": "Téléphone du représentant légal",
    "mos_parcours": "Parcours MOS", "aps_souhaitee": "Formation APS souhaitée", "aps_session": "Session APS",
    "projet_pourquoi": "Projet · pourquoi ce BTS", "projet_objectif": "Projet · objectif", "projet_passions": "Projet · passions",
    "projet_qualites": "Projet · qualités", "projet_motivation": "Projet · motivation", "projet_recherche": "Projet · recherche", "projet_travail": "Projet · travail",
    "statut": "Statut de préinscription", "commentaires": "Commentaires de préinscription", "entreprise_trouvee": "Entreprise trouvée",
    "recherches_commencees": "Recherches commencées", "souhaite_accompagnement": "Accompagnement souhaité",
    "label_aps": "Suivi APS", "label_aut_ok": "Autorisation préalable", "label_cheque_ok": "Chèque reçu", "label_carte_etudiante": "Carte étudiante",
    "date_validee": "Candidature validée le", "date_confirmee": "Inscription confirmée le", "date_reconfirmee": "Inscription reconfirmée le"}


def contract_context(legacy, record):
    store = ContractStore(legacy.AKTO_BTS_DB_FILE)
    values = effective_values(record, store.cerfa_complements(record["id"])["values"])
    saved = store.settings(record["id"])
    settings = defaults(values, saved["values"])
    package = store.package(record["id"])
    current_hash = fingerprint(values, settings)
    stale = bool(package and package["fingerprint"] != current_hash)
    imported = store.imported(record["id"])
    source = imported["values"] if imported else {}
    errors = signature_errors(values, settings)
    if readiness(values):
        errors.append("Compléter les informations du CERFA")
    signed = False
    if package and package["signature"].get("completed_at"):
        try:
            ensure_files(store, package, signed=True)
            signed = package["signature"].get("status") == "done"
        except WorkspaceError:
            pass
    state = package["signature"] if package else {}
    return {"contract_flow": {"settings": settings, "revision": saved["revision"], "settings_fields": SETTINGS_FIELDS, "modes": MODES,
        "fingerprint": current_hash, "package": package, "stale": stale, "errors": errors,
        "signed": signed, "signature_active": bool(state.get("pending") or state.get("status") in ACTIVE_SIGNATURE_STATUSES),
        "yousign_ready": bool(getattr(legacy, "_yousign_is_configured", lambda: False)()), "doc_labels": DOC_LABELS,
        "portal": PORTALS.get(settings.get("financer")),
        "history": store.packages(record["id"])[1:],
        "source": [{"label": label, "value": source[key]} for key,label in SOURCE_LABELS.items() if source.get(key) not in (None, "")],
        "imported": bool(imported), "source_documents": source.get("documents", [])}}


def register_contract_routes(legacy, protected, actor, get_record, endpoints):
    app = legacy.app

    def store():
        return ContractStore(legacy.AKTO_BTS_DB_FILE)

    def destination(record_id):
        return url_for("bts_dossier", record_id=record_id, tab="contrat") + "#contract-workflow"

    def search_candidates():
        try:
            data = InscriptionsClient().search(request.form.get("q", ""))
            return jsonify(data)
        except WorkspaceError as exc:
            return jsonify(error=str(exc), items=[]), 503

    def import_candidate():
        try:
            candidate = InscriptionsClient().candidate(request.form.get("candidate_id"))
            record_id, created = store().import_candidate(candidate, actor())
            flash("Dossier ajouté avec les informations des inscriptions BTS." if created else "Cette préinscription est déjà ajoutée : le dossier existant a été ouvert.", "success")
            return redirect(url_for("bts_dossier", record_id=record_id, tab="etudiant"))
        except WorkspaceError as exc:
            flash(str(exc), "error")
            return redirect(url_for("bts_new"))

    def source_document(record_id, document_id):
        get_record(record_id)
        imported = store().imported(record_id)
        documents = imported["values"].get("documents", []) if imported else []
        selected = next((d for d in documents if d.get("id") == document_id), None)
        if not selected:
            abort(404)
        try:
            content = InscriptionsClient().download(imported["source_id"], document_id)
            return send_file(io.BytesIO(content), mimetype="application/octet-stream", as_attachment=True,
                             download_name=selected["name"], max_age=0)
        except WorkspaceError as exc:
            flash(str(exc), "error")
            return redirect(url_for("bts_dossier", record_id=record_id, tab="etudiant"))

    def save_settings(record_id):
        get_record(record_id)
        db = store()
        try:
            with db.lock(record_id):
                values = validate_settings(request.form)
                db.save_settings(record_id, values, int(request.form.get("revision", "-1")), actor())
            flash("Paramètres des conventions enregistrés.", "success")
        except (WorkspaceError, ValueError) as exc:
            flash(str(exc) if isinstance(exc, WorkspaceError) else "Version du formulaire invalide.", "error")
        return redirect(destination(record_id))

    def get_current(db, record_id, *, check_hash=True):
        record = get_record(record_id)
        package = db.package(record_id)
        if not package or request.form.get("package_id") != package["id"]:
            raise WorkspaceError("La version des documents a changé. Rechargez le dossier.")
        values = effective_values(record, db.cerfa_complements(record_id)["values"])
        settings = defaults(values, db.settings(record_id)["values"])
        if check_hash and package["fingerprint"] != fingerprint(values, settings):
            raise WorkspaceError("Le dossier a été modifié. Régénérez et faites signer la nouvelle version avant de poursuivre.")
        return record, package

    def generate(record_id):
        db = store()
        try:
            with db.lock(record_id):
                record = get_record(record_id)
                values = effective_values(record, db.cerfa_complements(record_id)["values"])
                settings = defaults(values, db.settings(record_id)["values"])
                if fingerprint(values, settings) != request.form.get("fingerprint"):
                    raise WorkspaceError("Des informations ont changé. Rechargez le dossier avant de générer.")
                old = db.package(record_id)
                if old and (old["signature"].get("pending") or old["signature"].get("status") in ACTIVE_SIGNATURE_STATUSES):
                    raise WorkspaceError("Annulez d’abord la demande Yousign en cours avant de générer une nouvelle version.")
                if old and (old["opco"].get("pending") or old["opco"].get("sent")):
                    raise WorkspaceError("Le contrat a déjà été transmis ou reste à vérifier dans WEDOF. Conservez cette version et traitez un éventuel avenant séparément.")
                package = generate_documents(db, record_id, values, settings, legacy._training_center_signature_assets())
                db.save_package(record_id, package, event="Contrat et conventions générés depuis les modèles de l’école", actor=actor())
            flash("Documents générés. Relisez chaque PDF avant l’envoi groupé en signature.", "success")
        except (WorkspaceError, ValueError, RuntimeError) as exc:
            flash(str(exc), "error")
        return redirect(destination(record_id))

    def document(record_id, package_id, kind):
        get_record(record_id)
        db = store(); package = db.package(record_id, package_id)
        if not package or kind not in DOC_LABELS or kind not in package["documents"]:
            abort(404)
        doc = package["documents"][kind]
        signed = request.args.get("signed") == "1"
        path = db.path(doc.get("signed_pdf" if signed else "pdf", ""))
        if not path.is_file():
            abort(404)
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc.get("signed_sha256" if signed else "sha256"):
            abort(409, description="L’intégrité du document doit être vérifiée.")
        return send_file(path, mimetype="application/pdf", as_attachment=request.args.get("download") == "1",
                         download_name=kind + ("-signe" if signed else "") + ".pdf", conditional=False, max_age=0)

    def signature_action(record_id, action):
        db = store()
        try:
            with db.lock(record_id):
                _, package = get_current(db, record_id, check_hash=action == "envoyer")
                api = YousignClient(legacy)
                if action == "envoyer":
                    if request.form.get("reviewed") != "yes":
                        raise WorkspaceError("Confirmez la relecture des documents avant l’envoi.")
                    send_signature(db, record_id, package, api, actor())
                    message = "Une seule invitation Yousign par signataire a été envoyée pour ses documents."
                elif action == "actualiser":
                    refresh_signature(db, record_id, package, api, actor())
                    message = "Suivi Yousign actualisé."
                elif action == "annuler":
                    cancel_signature(db, record_id, package, api, actor())
                    message = "Demande annulée. Vous pouvez générer une nouvelle version."
                else:
                    abort(404)
            flash(message, "success")
        except (WorkspaceError, RuntimeError) as exc:
            flash(str(exc), "error")
        return redirect(destination(record_id))

    def opco_action(record_id, action):
        db = store()
        try:
            with db.lock(record_id):
                record, package = get_current(db, record_id, check_hash=action == "transmettre")
                if action == "depot-manuel":
                    if not package["opco"].get("sent"):
                        raise WorkspaceError("La télétransmission doit être confirmée avant d’enregistrer le dépôt de la convention.")
                    ensure_files(db, package, signed=True)
                    package["opco"].update(manual_deposit=True, manual_deposit_at=now(), manual_deposit_by=actor(),
                        manual_deposit_reference=request.form.get("reference", "").strip()[:200])
                    db.save_package(record_id, package, event="Dépôt manuel de la convention sur le portail OPCO confirmé par l’équipe", actor=actor())
                    result = {"done": True, "message": "Dépôt manuel enregistré."}
                elif action == "verifier":
                    result = {"done": True, "message": check_submission(db, record_id, package, SubmissionClient(origin="bts-submission"))}
                elif action == "transmettre":
                    if request.form.get("reviewed") != "yes":
                        raise WorkspaceError("Confirmez l’OPCO et le dépôt manuel à effectuer ensuite.")
                    if record["source"] != "local":
                        raise WorkspaceError("Ce contrat existe déjà chez l’OPCO. Aucun second contrat n’est transmis.")
                    result = advance_submission(db, record_id, package, SubmissionClient(origin="bts-submission"), actor())
                else:
                    abort(404)
            if request.headers.get("Accept") == "application/json":
                return jsonify(**result, redirect_url=destination(record_id))
            flash(result["message"] + (" Cliquez à nouveau pour poursuivre." if not result["done"] else ""), "success")
        except (WorkspaceError, WedofApiError, WedofConfigurationError) as exc:
            if request.headers.get("Accept") == "application/json":
                return jsonify(done=True, error=str(exc), message=str(exc)), 422
            flash(str(exc), "error")
        return redirect(destination(record_id))

    routes = [
        ("/admin/BTS/inscriptions/rechercher", "bts_candidates_search", search_candidates, ["POST"], True),
        ("/admin/BTS/inscriptions/importer", "bts_candidate_import", import_candidate, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>/inscription/documents/<document_id>", "bts_source_document", source_document, ["GET"], False),
        ("/admin/BTS/dossiers/<record_id>/conventions/parametres", "bts_contract_settings", save_settings, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>/documents/generer", "bts_documents_generate", generate, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>/documents/<package_id>/<kind>.pdf", "bts_contract_document", document, ["GET"], False),
        ("/admin/BTS/dossiers/<record_id>/signature/<action>", "bts_signature_action", signature_action, ["POST"], True),
        ("/admin/BTS/dossiers/<record_id>/opco/<action>", "bts_opco_action", opco_action, ["POST"], True),
    ]
    for path, name, function, methods, write in routes:
        app.add_url_rule(path, name, protected(function, write=write), methods=methods)
        endpoints.add(name)

    def webhook(request_id):
        db = store()
        with db._connect() as conn:
            row = conn.execute("SELECT dossier_id,id FROM bts_contract_packages WHERE json_extract(payload_json,'$.signature.request_id')=?", (request_id,)).fetchone()
        if not row:
            return None
        try:
            with db.lock(row["dossier_id"]):
                package = db.package(row["dossier_id"], row["id"])
                refresh_signature(db, row["dossier_id"], package, YousignClient(legacy), "Yousign")
            return jsonify(ok=True, document_type="bts", updated=True)
        except (WorkspaceError, RuntimeError):
            # Yousign retries the verified webhook; errors never mark PDFs signed.
            return jsonify(ok=False, error="bts_signature_refresh_pending"), 503

    app.extensions["bts_yousign_webhook"] = webhook

    @app.before_request
    def bts_verified_yousign_callback():
        # Intercept only our authenticated callbacks. All other Yousign requests
        # continue through the existing convention/mandate webhook unchanged.
        if request.endpoint != "webhooks_yousign" or request.method != "POST":
            return None
        verify = getattr(legacy, "_verify_yousign_webhook_signature", None)
        if not verify or not verify(request.get_data(cache=True)):
            return None
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            return None
        signature = payload["data"].get("signature_request")
        if not isinstance(signature, dict) or not isinstance(signature.get("id"), str):
            return None
        return webhook(signature["id"].strip())
