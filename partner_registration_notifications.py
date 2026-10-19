"""Durable internal alerts for new self-service partner accounts."""

import copy
import time
import uuid
from urllib.parse import quote

ADMIN_EMAIL = "clement@integraleacademy.com"
STATE_KEY = "registration_admin_email"


def _due(state, now):
    return (state.get("status") in {"pending", "failed", "sending"}
            and state.get("next_attempt", 0) <= now
            and state.get("lease_until", 0) <= now)


def process_pending(host, data):
    """Use the existing commerce worker; old accounts are never backfilled."""
    for partner in data.get("partners", []):
        if not _due(partner.get(STATE_KEY) or {}, time.time()):
            continue
        try:
            _deliver(host, partner["id"])
        except Exception:
            # A store/delivery error must not stop other partners or orders.
            host.app.logger.exception("partner_registration_notification_failed partner_id=%s", partner.get("id"))


def _deliver(host, partner_id):
    now, token = time.time(), str(uuid.uuid4())

    def claim(data):
        partner = host._partner_or_404(data, partner_id)
        state = partner.get(STATE_KEY) or {}
        if not _due(state, now):
            return {}
        state.update(status="sending", lease_token=token, lease_until=now + 60,
                     attempts=state.get("attempts", 0) + 1, last_attempt_at=host._now_iso())
        return {"partner": copy.deepcopy(partner)}

    claimed = host._atomic_update_data(claim, partner_id=partner_id)
    if not claimed:
        return
    partner = claimed["partner"]
    state = partner[STATE_KEY]
    try:
        from manuals_shop import base_url
        origin = base_url(host)
        link = origin + "/admin/partners/" + quote(partner_id, safe="")
        contact = " ".join(filter(None, (partner.get("contact_first_name"), partner.get("contact_last_name"))))
        created_at = host.fr_datetime(partner.get("created_at", ""))
        name = " ".join(str(partner.get("name", "")).split())
        subject = "Nouvel organisme inscrit · " + name
        body = host.app.jinja_env.get_template("manuals/registration_admin_email.html").render(
            partner=partner, contact=contact, created_at=created_at, link=link, email_base_url=origin)
        text = (f"Bonjour Clément,\n\nUn nouvel organisme vient de créer son compte sur Intégrale Connect.\n\n"
                f"Organisme : {partner.get('name', '')}\nSIRET : {partner.get('siret', '')}\n"
                f"Contact : {contact}\nE-mail : {partner.get('email', '')}\n"
                f"Inscription : {created_at} (heure de Paris)\n\nVoir la fiche organisme : {link}")
        result = host.brevo_send_email(ADMIN_EMAIL, subject, body, text_content=text,
            metadata={"partner_id": partner_id, "user_id": state.get("user_id"),
                      "purpose": "partner_registration_admin",
                      "idempotency_key": "partner-registration-" + partner_id})
    except Exception:
        host.app.logger.exception("partner_registration_email_failed partner_id=%s", partner_id)
        result = {"ok": False}
    sent = bool(result.get("ok"))

    def record(data):
        current = host._partner_or_404(data, partner_id).get(STATE_KEY) or {}
        if current.get("lease_token") != token:
            return {}
        current.update(status="sent" if sent else "failed", lease_until=0,
                       message_id=result.get("message_id", ""),
                       next_attempt=0 if sent else time.time() + min(60 * 2 ** min(current["attempts"] - 1, 6), 3600))
        if sent:
            current["sent_at"] = host._now_iso()
        return {}

    host._atomic_update_data(record, partner_id=partner_id)
    host.app.logger.info("partner_registration_notification partner_id=%s status=%s", partner_id, "sent" if sent else "retry_pending")
