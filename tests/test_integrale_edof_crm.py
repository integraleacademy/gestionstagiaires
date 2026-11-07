from unittest.mock import Mock

from flask import Flask, jsonify, request

import edof_directory as directory
import integrale_edof_crm as feed
from integrale_edof_dashboard import category
from integrale_edof_crm_delivery import send


def test_authenticated_crm_feed_uses_verified_directory_only(monkeypatch):
    app = Flask(__name__)
    verified = directory.project({"id":"123456", "currentState":"validated",
        "changingStateDate":"2026-11-01", "attendee":{"firstName":"Anne", "lastName":"Exemple"},
        "trainingActionInfo":{"title":"APS", "solicitations":[{"fundingType":"9","status":"accepted"},
            {"fundingType":"Other","status":"refused"}]}})
    pending = {**verified, "folder_id":"234567", "state":"notProcessed", "filed_at":"2026-10-31",
               "email_proof":"private-digest", "session_start_date":"2026-12-01"}
    store = Mock(connector_key="present")
    private = Mock()
    private.get.return_value = {"234567":{"first_name":"Anne","last_name":"Exemple","email":"anne@example.test"},
                                "123456":{"first_name":"Else","last_name":"Exemple","email":"other@example.test"}}
    monkeypatch.setattr(feed.details, "known_details", lambda vault, owner: set())
    monkeypatch.setattr(feed.details, "request_read", Mock())
    monkeypatch.setattr(feed, "snapshot_owners", lambda vault: ["account"])
    monkeypatch.setattr(feed, "observed_rows", lambda store, owner, snapshot: snapshot["rows"])
    available = [True]
    snap = Mock(return_value={"checked":100, "rows":{"123456":verified,"234567":pending}})
    def auth(fn):
        def wrapped(**kwargs):
            if request.headers.get("Authorization") != "Bearer fixture":
                return jsonify(error="unauthorized"), 401
            return fn(**kwargs)
        return wrapped
    feed.register_crm_feed(app, store, lambda:private, snap, category, auth, lambda: available[0])
    client, url = app.test_client(), "/api/integrations/crm/integrale-edof"
    headers = {"Authorization":"Bearer fixture"}
    assert client.get(url+"/dossiers").status_code == 401
    snap.assert_not_called()
    assert client.get(url+"/status",headers=headers).json == {"provider":"integrale_edof","source_checked_at":100}
    listing = client.get(url+"/dossiers?scope=requests", headers=headers)
    assert listing.headers["Cache-Control"] == "private, no-store"
    assert listing.headers["X-Total-Count"] == "1"
    assert listing.json["items"][0]["createdAt"] == "2026-10-31"
    assert listing.json["items"][0]["attendee"]["email"] == "anne@example.test"
    assert b"private-digest" not in listing.data
    detail = client.get(url+"/dossiers/123456",headers=headers).json
    assert "email" not in detail["attendee"]
    assert [s["status"] for s in detail["trainingActionInfo"]["solicitations"]] == ["accepted"]
    assert client.get(url+"/dossiers?page=bad",headers=headers).status_code == 400
    assert client.get(url+"/dossiers/999999",headers=headers).status_code == 404
    assert client.get(url+"/dossiers?page=2",headers=headers).json == {"items":[]}
    assert snap.call_count == 1
    available[0] = False
    assert client.get(url+"/dossiers", headers=headers).status_code == 503


def test_crm_transfer_signs_native_body_and_checks_receipt(monkeypatch):
    import hmac
    import integrale_edof_crm_delivery as delivery
    monkeypatch.setenv("CRM_INTEGRATION_API_TOKEN","fixture")
    response = Mock(status_code=200)
    response.json.return_value = {"ok":True, "processed":True}
    post = Mock(return_value=response)
    monkeypatch.setattr(delivery.requests,"post",post)
    entry = {"payload":{"externalId":"123456","provider":"integrale_edof"}}
    assert send(entry)[1] == 200 and entry["crm_processed"]
    url, = post.call_args.args
    assert url.endswith("/api/webhooks/integrale-edof")
    kw = post.call_args.kwargs
    assert kw["allow_redirects"] is False
    assert hmac.compare_digest(kw["headers"]["X-Integrale-EDOF-Signature"],
        hmac.digest(b"fixture", b"integrale-edof-crm-v1\0" + kw["data"], "sha256").hex())
