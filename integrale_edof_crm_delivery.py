"""Authenticated delivery from the native EDOF dashboard to the CRM."""

import hmac
import json
import os

import requests


def send(entry):
    secret = os.environ.get("CRM_INTEGRATION_API_TOKEN", "").strip()
    if not secret:
        return {"success": False}, 503
    body = json.dumps(entry["payload"], ensure_ascii=False, separators=(",", ":")).encode()
    signature = hmac.digest(secret.encode(), b"integrale-edof-crm-v1\0" + body, "sha256").hex()
    url = os.getenv("CRM_INTEGRALE_EDOF_WEBHOOK_URL") or "https://assistance-alw9.onrender.com/api/webhooks/integrale-edof"
    response = requests.post(url, data=body, timeout=15, allow_redirects=False,
                             headers={"Content-Type": "application/json", "X-Integrale-EDOF-Signature": signature})
    if response.status_code != 200:
        return {"success": False}, response.status_code
    reply = response.json()
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        return {"success": False}, 502
    entry.update(crm_sent=True, crm_processed=reply.get("processed") is True,
                 crm_duplicate=reply.get("duplicate") is True)
    return {"success": True}, 200
