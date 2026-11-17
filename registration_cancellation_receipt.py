"""Preview and send the initial cancellation acknowledgement independently of the financial assessment."""
import hashlib
import hmac
import time
import uuid

from flask import jsonify, render_template, request

from email_design import PUBLIC_ASSETS

ACCOUNT = "https://www.moncompteformation.gouv.fr/"
HELP = ACCOUNT + "espace-public/quelles-consequences-en-cas-dannulation-de-mon-inscription-a-une-formation"
RULES = (
    ("Pendant la rétractation", "Vous disposez de 14 jours ouvrés après la validation de votre dossier, jusqu’au début de la formation. Si vous annulez dans ce délai, vos droits sont recrédités et vos versements personnels remboursés."),
    ("Au moins 7 jours ouvrés avant le début de formation", "Vous pouvez annuler sans frais ni justificatif. Vous récupérez vos droits CPF et les sommes versées sur la plateforme."),
    ("Moins de 7 jours ouvrés avant le début de formation, ou en cas d’absence", "Hors rétractation et force majeure, vos droits CPF sont débités. Le complément personnel reste disponible en avoir pour une autre formation. La participation financière obligatoire vous est remboursée."),
    ("Après le début de la formation", "En cas d’abandon sans force majeure, vos droits restent débités et votre complément personnel n’est ni remboursé ni transformé en avoir."),
    ("En cas de force majeure", "Déclarez le motif dans votre espace personnel et joignez votre justificatif. Si le motif est reconnu, le remboursement porte sur la totalité avant le début et sur la part non réalisée après le début. En cas d’interruption, transmettez votre justificatif dans les 5 jours ouvrés suivant votre sortie."),
)
CPF_ACTION = "Vous devez procéder à l’annulation de votre dossier sur votre Compte Personnel de Formation (CPF)."
CPF_RULES_TITLE = "Les règles du Compte Personnel de Formation (CPF) :"
FOLLOW_UP = (
    "Si votre formation est financée entièrement ou partiellement par votre CPF, vous devez effectuer votre demande d'annulation directement depuis votre espace Mon Compte Formation.",
    "Notre équipe va procéder à un examen de votre dossier conformément aux conditions d'annulation prévues dans votre contrat de formation et nos conditions générales de vente.",
    "À l'issue de cette vérification, nous vous adresserons un e-mail récapitulatif vous précisant si des frais d'annulation sont applicables et, selon les sommes déjà versées, si un montant reste à régler de votre part ou si nous devons procéder à un remboursement.",
)
CNAPS = ("si votre annulation est liée à un refus d'autorisation du CNAPS (ministère de l'Intérieur), "
         "ou si cette autorisation n'a pas été délivrée à temps, aucun frais d'annulation ne sera appliqué par Intégrale Academy.")
REFUND = ("Si nous devons procéder à un remboursement, et pour gagner du temps, nous vous demandons de bien vouloir "
          "nous faire parvenir un RIB par retour de mail")


def message(host, group, trainee):
    recipient = str(trainee.get("email") or trainee.get("mail") or "").strip()
    who = str(trainee.get("first_name") or trainee.get("prenom") or "").strip()
    greeting = f"Bonjour {who}," if who else "Bonjour,"
    course = host._registration_cancellation_training_label(group)
    subject = f"Votre demande d’annulation a bien été prise en compte – {course}"
    try:
        schedule = host._convention_training_session(group, trainee)
    except ValueError:
        # An individual VTC period may still be unknown when a trainee cancels.
        schedule = {}
    start = host._diploma_date_fr(host._session_get(schedule, "date_start", ""))
    end = host._diploma_date_fr(host._session_get(schedule, "date_end", ""))
    dates = f", prévue du {start} au {end}" if start and end else ""
    intro = f"Nous avons bien pris en compte votre demande d’annulation concernan la formation « {course} »{dates}."
    steps = ("Connectez-vous à Mon Compte Formation, ouvrez « Dossiers » et sélectionnez la formation concernée. "
             "Cliquez sur « Annuler mon dossier », confirmez votre choix et conservez la confirmation.")
    info = ("Les jours ouvrés vont du lundi au vendredi, hors jours fériés. Les remboursements dus par la plateforme "
            "interviennent sous 30 jours calendaires. Les conditions applicables à votre dossier font foi.")
    body = render_template("emails/registration_cancellation_receipt.html", greeting=greeting, intro=intro,
                           steps=steps, rules=RULES, info=info, cpf_action=CPF_ACTION, rules_title=CPF_RULES_TITLE,
                           follow_up=FOLLOW_UP, cnaps=CNAPS, refund=REFUND, help_url=HELP,
                           account=ACCOUNT, email_base_url=PUBLIC_ASSETS, email_preheader=intro)
    text = "\n\n".join([greeting, intro, "Si vous avez utilisé votre CPF", CPF_ACTION, steps,
                       f"Ouvrir Mon Compte Formation → {ACCOUNT}", CPF_RULES_TITLE,
                       *(f"{title}\n{detail}" for title, detail in RULES), info, f"Consulter les règles de Mon Compte Formation : {HELP}",
                       "Les suites de votre annulation :", *(f"{i}. {step}" for i, step in enumerate(FOLLOW_UP, 1)),
                       f"À noter : {CNAPS}", REFUND,
                       "Clément VAILLANT\nDirecteur du centre de formation Intégrale Academy"])
    return recipient, subject, body, text


def register(app, host):
    route = "/api/sessions/<session_id>/stagiaires/<trainee_id>/accuse-annulation/"

    def prepare(data, sid, tid):
        group, roster, trainee = host._find_session_trainee(data, sid, tid)
        if not trainee or not group:
            raise ValueError("Inscription introuvable.")
        if not host._trainee_registration_is_cancelled(trainee):
            raise ValueError("Cette inscription doit être annulée pour préparer son accusé de réception.")
        recipient, subject, body, text = message(host, group, trainee)
        if not recipient:
            raise ValueError("Ajoutez une adresse e-mail sur la fiche du stagiaire.")
        episode = str(trainee.get("registration_cancelled_at") or trainee.get("inscription_annulee_at") or "ancienne")
        delivery = str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(("accuse-annulation", sid, tid, episode, recipient))))
        proof = hmac.new(app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key,
                         (delivery + subject + body).encode(), hashlib.sha256).hexdigest()
        return group, roster, trainee, dict(recipient=recipient, subject=subject, html=body, text=text,
                                           delivery=delivery, preview_token=proof)

    @app.post(route + "apercu")
    @host.admin_login_required
    @host.admin_write_required
    def cancellation_receipt_preview(session_id, trainee_id):
        try:
            _, _, trainee, prepared = prepare(host.load_data(run_background_tasks=False), session_id, trainee_id)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 409
        saved = trainee.get("cancellation_receipt") or {}
        return jsonify(ok=True, recipient=prepared["recipient"], subject=prepared["subject"], html=prepared["html"],
                       preview_token=prepared["preview_token"],
                       already_sent=saved.get("key") == prepared["delivery"] and bool(saved.get("sent_at")))

    @app.post(route + "envoyer")
    @host.admin_login_required
    @host.admin_write_required
    def cancellation_receipt_send(session_id, trainee_id):
        proof = (request.get_json(silent=True) or {}).get("preview_token")
        if not isinstance(proof, str) or not proof.isascii():
            return jsonify(ok=False, error="Prévisualisez le mail avant son envoi."), 409

        def reserve(data):
            group, roster, trainee, prepared = prepare(data, session_id, trainee_id)
            if not hmac.compare_digest(proof, prepared["preview_token"]):
                raise ValueError("La fiche a changé. Rouvrez l’aperçu avant l’envoi.")
            saved = trainee.get("cancellation_receipt") or {}
            if saved.get("key") == prepared["delivery"]:
                if saved.get("sent_at"):
                    return {"already_sent": True, "recipient": prepared["recipient"]}
                if saved.get("started", 0) > time.time()-60:
                    raise ValueError("Un envoi est déjà en cours pour cette inscription.")
            trainee["cancellation_receipt"] = {"key": prepared["delivery"], "started": time.time()}
            group["trainees"] = roster
            group.pop("stagiaires", None)
            return prepared

        try:
            prepared = host._atomic_update_data(reserve)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 409
        if prepared.get("already_sent"):
            return jsonify(ok=True, **prepared)
        result = host.brevo_send_email(
            prepared["recipient"], prepared["subject"], prepared["html"], text_content=prepared["text"],
            sender_name="Clément Vaillant · Intégrale Academy",
            reply_to={"name":"Intégrale Academy", "email":"ecole@integraleacademy.com"},
            metadata={"purpose":"registration_cancellation_receipt", "session_id":session_id, "trainee_id":trainee_id,
                      "idempotency_key":prepared["delivery"]})
        sent = bool(isinstance(result, dict) and result.get("ok"))

        def record(data):
            group, roster, trainee = host._find_session_trainee(data, session_id, trainee_id)
            saved = (trainee or {}).get("cancellation_receipt") or {}
            if saved.get("key") != prepared["delivery"] or saved.get("sent_at"):
                return
            saved["started"] = 0
            if sent:
                saved["sent_at"] = host._now_iso()
                entry = {"sent_at":saved["sent_at"], "subject":prepared["subject"], "to_email":prepared["recipient"], "html":prepared["html"]}
                trainee["sent_email_history"] = [entry, *(trainee.get("sent_email_history") or [])][:200]
            group["trainees"] = roster
            group.pop("stagiaires", None)

        host._atomic_update_data(record)
        if not sent:
            return jsonify(ok=False, error="L’envoi du mail n’a pas été confirmé. Vous pouvez le reprendre depuis la fiche."), 502
        return jsonify(ok=True, recipient=prepared["recipient"])
