"""Gmail OAuth and strictly bounded EFP-code reads for the Gestion Stagiaires connector.

No message, code or token is returned by the admin API. Gmail's readonly scope
is mailbox-wide; filtering here is an application restriction, not a Google
permission restricted to one sender. No Gmail write/send operation exists.
"""

import base64
from contextlib import contextmanager
import hashlib
import hmac
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from email.utils import getaddresses
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken
import requests

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CALLBACK = "https://gestionstagiaires-r5no.onrender.com/admin/edof-test/server/gmail/callback"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
SENDER = "no-reply@efpconnect.emploi.gouv.fr"
EFP_SENDERS = (SENDER, "no-reply@emploi.gouv.fr")


class GmailError(Exception):
    def __init__(self, code, *, diagnostics=None):
        self.code = code
        self.diagnostics = diagnostics or {}
        super().__init__(code)


def connector_key(secret):
    if not isinstance(secret, str) or len(secret) < 32 or secret == "dev-secret-change-me":
        return None
    return base64.urlsafe_b64encode(hmac.new(secret.encode(), b"edof-test-v2-private-v1", hashlib.sha256).digest()).decode()


def account_binding(username=None):
    return hashlib.sha256((username if username is not None else os.environ.get("EDOF_EFP_USERNAME", "")).strip().lower().encode()).hexdigest()


class Vault:
    def __init__(self, directory, key):
        self.path = Path(directory) / "edof_connector_private.sqlite3"
        self.cipher = Fernet(key.encode() if isinstance(key, str) else key)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA secure_delete=ON")
        db.execute("CREATE TABLE IF NOT EXISTS private_records (name TEXT PRIMARY KEY, sealed BLOB NOT NULL)")
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, name, value, *, ttl=None):
        payload = {"binding": account_binding(), "expires": time.time() + ttl if ttl else None, "value": value}
        sealed = self.cipher.encrypt(json.dumps(payload).encode())
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO private_records VALUES (?, ?)", (name, sealed))

    def get(self, name, *, consume=False, keep=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT sealed FROM private_records WHERE name=?", (name,)).fetchone()
            if consume and row:
                db.execute("DELETE FROM private_records WHERE name=?", (name,))
        if not row:
            return None
        try:
            payload = json.loads(self.cipher.decrypt(row[0]))
            if payload["binding"] != account_binding() or (payload["expires"] and payload["expires"] <= time.time()):
                with self.connect() as db:
                    db.execute("DELETE FROM private_records WHERE name=? AND sealed=?", (name, row[0]))
                return None
            if keep and payload["expires"] and not consume:
                # Promote an existing directory snapshot without reviving expired data
                # or overwriting a newer sync (or an explicit disconnect).
                payload["expires"] = None
                sealed = self.cipher.encrypt(json.dumps(payload).encode())
                with self.connect() as db:
                    db.execute("UPDATE private_records SET sealed=? WHERE name=? AND sealed=?", (sealed, name, row[0]))
            return payload["value"]
        except (InvalidToken, ValueError, KeyError, TypeError):
            return None

    def clear(self):
        with self.connect() as db:
            db.execute("DELETE FROM private_records")

    def delete(self, name):
        with self.connect() as db:
            db.execute("DELETE FROM private_records WHERE name=?", (name,))


def oauth_configured():
    return bool(os.environ.get("EDOF_GOOGLE_CLIENT_ID") and os.environ.get("EDOF_GOOGLE_CLIENT_SECRET"))


def authorization_url(state, verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return AUTH_URL + "?" + urlencode({"client_id": os.environ["EDOF_GOOGLE_CLIENT_ID"],
        "redirect_uri": CALLBACK, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent select_account", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})


def google_json(method, url, **kwargs):
    # URLs are constants or validated Gmail message IDs. Never follow redirects
    # carrying credentials, and never surface requests/Google error strings.
    try:
        with requests.Session() as http:
            http.trust_env = False
            with http.request(method, url, timeout=(5, 10), allow_redirects=False, stream=True, **kwargs) as response:
                data = bytearray()
                for chunk in response.iter_content(8192):
                    data.extend(chunk)
                    if len(data) > 1_000_000:
                        raise GmailError("gmail_response_invalid")
                body = json.loads(data)
                if response.status_code != 200:
                    if response.status_code == 401 or (isinstance(body, dict) and body.get("error") == "invalid_grant"):
                        raise GmailError("gmail_reconnect_required")
                    raise GmailError("gmail_unavailable")
                if not isinstance(body, dict):
                    raise GmailError("gmail_response_invalid")
                return body
    except GmailError:
        raise
    except Exception:
        raise GmailError("gmail_unavailable") from None


def token_request(data):
    if not oauth_configured():
        raise GmailError("gmail_not_configured")
    return google_json("POST", TOKEN_URL, data={**data,
        "client_id": os.environ["EDOF_GOOGLE_CLIENT_ID"], "client_secret": os.environ["EDOF_GOOGLE_CLIENT_SECRET"]})


def finish_authorization(vault, code, verifier):
    token = token_request({"grant_type": "authorization_code", "code": code,
        "redirect_uri": CALLBACK, "code_verifier": verifier})
    if SCOPE not in token.get("scope", "").split() or not token.get("refresh_token") or not token.get("access_token"):
        raise GmailError("gmail_permission_missing")
    profile = google_json("GET", GMAIL_URL + "/profile", headers={"Authorization": "Bearer " + token["access_token"]})
    if account_binding(profile.get("emailAddress", "")) != account_binding():
        raise GmailError("gmail_account_mismatch")
    vault.put("gmail", {"refresh_token": token["refresh_token"]})
    vault.delete("browser")


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "div", "td", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def normal_text(text):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower().split())


def sender_authentication(headers):
    """Check only the first Google ingress verdict. Never mix result clauses."""
    for value in headers.get("authentication-results", []):
        authority, separator, results = value.lower().partition(";")
        if separator and authority.strip() == "mx.google.com":
            break
    else:
        return "authentication_header_missing"
    # Ignore quoted reasons and nested comments: neither is an auth result.
    clean = []
    depth = 0
    quoted = escaped = False
    if len(results) > 16000:
        return "sender_authentication_failed"
    for char in results:
        if escaped:
            escaped = False
        elif (quoted or depth) and char == "\\":
            escaped = True
        elif not depth and char == '"':
            quoted = not quoted
            clean.append('"')
        elif not quoted and char == "(":
            depth += 1
            clean.append(" ")
        elif depth and char == ")":
            depth -= 1
        elif not quoted and not depth:
            clean.append(char)
    if depth or quoted or escaped:
        return "sender_authentication_failed"
    trusted_domain = r"(?:[a-z0-9-]+\.)*emploi\.gouv\.fr"
    for clause in "".join(clean).split(";"):
        words = clause.split()
        if not words or words[0] not in {"dkim=pass", "dmarc=pass"}:
            continue
        props = {}
        for word in words[1:]:
            key, equals, val = word.partition("=")
            if equals:
                props.setdefault(key, []).append(val)
        def aligned(key, pattern):
            values = props.get(key, [])
            return len(values) == 1 and re.fullmatch(pattern, values[0]) is not None
        if words[0] == "dmarc=pass":
            if aligned("header.from", trusted_domain):
                return None
        elif "header.d" in props:
            if aligned("header.d", trusted_domain):
                return None
        # RFC 8601 also allows the verified DKIM identity (header.i). Do not
        # use it to override a different signing domain in the same clause.
        elif aligned("header.i", r"[^@;\s]*@" + trusted_domain):
            return None
    return "sender_authentication_failed"


def extract_code(message, recipient, started, *, rejections=None):
    """Accept one recent authenticated EFP message addressed to this account."""
    def reject(reason):
        # Only fixed categories and counts leave the mail reader.
        if rejections is not None:
            rejections[reason] = rejections.get(reason, 0) + 1
        return None

    try:
        received = int(message["internalDate"]) / 1000
        if received < started:
            return reject("before_attempt")
        if received > time.time() + 30:
            return reject("future_date")
        if time.time() - received > 180:
            return reject("expired")
        payload = message["payload"]
        headers = {}
        for header in payload.get("headers", []):
            headers.setdefault(header["name"].lower(), []).append(header["value"])
        senders = getaddresses(headers.get("from", []))
        if len(senders) != 1 or senders[0][1].lower() not in EFP_SENDERS:
            return reject("sender_mismatch")
        if recipient.lower() not in [address.lower() for _, address in getaddresses(headers.get("to", []) + headers.get("delivered-to", []))]:
            return reject("recipient_mismatch")
        auth_error = sender_authentication(headers)
        if auth_error:
            return reject(auth_error)
        texts = []
        def visit(part, depth=0):
            if depth > 8 or part.get("filename"):
                return
            mime = part.get("mimeType", "")
            encoded = part.get("body", {}).get("data", "")
            if mime in {"text/plain", "text/html"} and encoded and len(encoded) < 60000:
                text = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8", "replace")
                if mime == "text/html":
                    parser = PlainHTML()
                    parser.feed(text)
                    text = " ".join(parser.parts)
                texts.append(text)
            for child in part.get("parts", [])[:20]:
                visit(child, depth + 1)
        visit(payload)
        sources = [normal_text(value) for value in headers.get("subject", []) + texts]
        text = " ".join(sources)
        if "efp" not in text and "edof" not in text:
            return reject("not_efp")
        if any(term in text for term in ("reinitialiser", "reinitialisation", "reset password", "creer votre compte", "creation de compte", "responsable des acces")):
            return reject("account_management")
        patterns = (
            r"\bcode(?:\s+d['’ ]authentification|\s+de\s+(?:verification|securite|connexion)|\s+a\s+usage\s+unique)?(?:\s+(?:est|suivant|personnel|unique))?\s*[:：\-]?\s*(\d{6,8})\b",
            # Current EFP login subject and body. Match explicit labels, never
            # arbitrary numbers elsewhere in the message (dates, IDs, etc.).
            r"\b([0-9]{6,8}) est votre code de securite efp connect pour acceder au service numerique edof\b",
            r"\bcode de securite ci[-\u2010\u2011 ]dessous sur efp connect\s*[:：\-]\s*([0-9]{6,8})\b",
        )
        # Inspect each MIME representation independently: a label in one part
        # must not become attached to a number in a different part. Repeated
        # copies of the same code are fine; conflicting values fail closed.
        codes = {code for source in sources for pattern in patterns for code in re.findall(pattern, source)}
        if not codes:
            return reject("code_unrecognized")
        if len(codes) > 1:
            return reject("code_ambiguous")
        return next(iter(codes))
    except (KeyError, TypeError, ValueError):
        return reject("message_invalid")


class GmailCodes:
    def __init__(self, vault, recipient):
        self.vault = vault
        self.recipient = recipient.strip().lower()
        if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+", self.recipient):
            raise GmailError("gmail_account_mismatch")
        saved = vault.get("gmail")
        if not saved:
            raise GmailError("gmail_not_connected")
        try:
            token = token_request({"grant_type": "refresh_token", "refresh_token": saved["refresh_token"]})
        except GmailError as exc:
            if exc.code == "gmail_reconnect_required":
                vault.delete("gmail")
                vault.delete("browser")
            raise
        if not token.get("access_token") or (token.get("scope") and SCOPE not in token["scope"].split()):
            raise GmailError("gmail_permission_missing")
        self.headers = {"Authorization": "Bearer " + token["access_token"]}
        if token.get("refresh_token"):
            vault.put("gmail", {"refresh_token": token["refresh_token"]})
        self.baseline = set(self.list_ids(time.time() - 180))

    def list_ids(self, since):
        # No broad inbox enumeration and no mailbox changes. Maximum 10 hits.
        sender_filter = "{" + " ".join(f"from:{address}" for address in EFP_SENDERS) + "}"
        result = google_json("GET", GMAIL_URL + "/messages", headers=self.headers,
            params={"q": f"{sender_filter} to:({self.recipient}) after:{int(since)}", "maxResults": 10})
        if result.get("nextPageToken"):
            raise GmailError("gmail_messages_ambiguous")
        return [item["id"] for item in result.get("messages", []) if re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", item.get("id", ""))]

    def wait_for_code(self, started, *, timeout=35, tick=None):
        deadline = time.monotonic() + timeout
        seen = set(self.baseline)
        diagnostics = {"gmail_messages_checked": 0, "gmail_rejections": {}}
        while time.monotonic() < deadline:
            matches = []
            for message_id in self.list_ids(started):
                if message_id in seen:
                    continue
                message = google_json("GET", GMAIL_URL + "/messages/" + message_id,
                    headers=self.headers, params={"format": "full"})
                diagnostics["gmail_messages_checked"] += 1
                code = extract_code(message, self.recipient, started, rejections=diagnostics["gmail_rejections"])
                seen.add(message_id)
                if code:
                    matches.append(code)
            if len(matches) > 1:
                raise GmailError("gmail_messages_ambiguous", diagnostics=diagnostics)
            if matches:
                return matches[0]
            if tick:
                tick()
            time.sleep(2)
        raise GmailError("gmail_code_missing", diagnostics=diagnostics)
