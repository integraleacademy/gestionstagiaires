"""Short-lived, read-only EDOF browser used by the Test V2 access experiment.

Input is a small search specification on stdin. Output is one allowlisted JSON
result. No screenshots, traces, browser storage, raw responses or credentials
are persisted. A fresh browser is created on EVERY run, including repeat runs.
"""

import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import urlsplit

from edof_readonly_test import (
    ATTENDEE_FIELDS, INFO_FIELDS, SIRET, TEST_SERVICE_ID, TOP_FIELDS,
    normalize_observation,
)

EDOF_HOST = "of.moncompteformation.gouv.fr"
EFP_HOST = "efpconnect.emploi.gouv.fr"
LOGIN_URL = f"https://{EDOF_HOST}/espace-prive/html/#/redirect-to-mire-connexion"
LIST_URL = f"https://{EDOF_HOST}/espace-prive/html/#/dossiers/en-cours"
DETAIL_PREFIX = f"https://{EDOF_HOST}/espace-prive/html/#/dossiers/detail/"
API_PREFIX = f"/edof-api/v1/api/private/siret/{SIRET}/organisms/current/registration-folders/"
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def permitted_request(url, method):
    """Block business mutations even if the frontend initiates one itself."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if method in READ_METHODS:
        return True
    # Only the actual EFP password form / OIDC exchange may submit data.
    # All EDOF mutations (including read acknowledgments) remain blocked.
    return parsed.scheme == "https" and parsed.hostname == EFP_HOST and method == "POST" and (
        parsed.path == "/auth/realms/efp/login-actions/authenticate"
        or parsed.path == "/auth/realms/efp/protocol/openid-connect/token"
    )


def identity(value):
    value = unicodedata.normalize("NFKD", value or "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(c for c in value if not unicodedata.combining(c)).lower()).split())


def project_folder(raw):
    """Discard all unneeded PII before normalization or output."""
    folder = {key: raw.get(key) for key in TOP_FIELDS}
    folder["attendee"] = {key: (raw.get("attendee") or {}).get(key) for key in ATTENDEE_FIELDS}
    folder["trainingActionInfo"] = {key: (raw.get("trainingActionInfo") or {}).get(key) for key in INFO_FIELDS}
    return normalize_observation({"siret": SIRET, "folder": folder}, raw["id"])


def classify_text(text):
    text = identity(text)
    if any(term in text for term in ("verify you are human", "verifiez que vous etes humain", "je ne suis pas un robot", "captcha", "checking your browser", "automated traffic")):
        return "human_verification"
    if any(term in text for term in ("code de verification", "code a usage unique", "code d authentification", "code de securite", "authentification a deux facteurs", "one time code")):
        return "verification_code"
    if any(term in text for term in ("identifiant ou mot de passe invalide", "identifiant ou mot de passe incorrect", "invalid username or password", "identifiants incorrects", "nom d utilisateur ou mot de passe invalide", "nom d utilisateur ou mot de passe incorrect", "invalid credentials")):
        return "credentials_rejected"
    if any(term in text for term in ("compte temporairement bloque", "compte est verrouille", "compte est desactive", "account is disabled", "account temporarily disabled")):
        return "account_unavailable"
    return None


def location_category(url):
    """Return a fixed label, never an auth URL, query, fragment or identifier."""
    parsed = urlsplit(url)
    if parsed.hostname == EFP_HOST:
        if parsed.path.startswith("/auth/realms/efp/login-actions/required-action"):
            return "efp_required_action"
        if parsed.path.startswith("/auth/"):
            return "efp_login"
        return "efp_account"
    if parsed.hostname == EDOF_HOST:
        if parsed.path == "/idp/edof/api/v2/callback":
            return "edof_callback"
        if parsed.path.startswith("/espace-prive/"):
            return "edof_select_siret" if "select-siret" in parsed.fragment else "edof_private"
        if parsed.path.startswith("/espace-public/"):
            return "edof_public"
        if parsed.path.startswith("/edof-api/"):
            return "edof_api"
        return "edof_other"
    return "other_origin"


def diagnostic_summary(location, password_visible, error_visible, signals):
    """Allowlist scalar signals; deliberately no page/error/input text."""
    result = {"location": location_category(location), "password_form_visible": bool(password_visible), "error_banner_visible": bool(error_visible)}
    for key in ("login_post_status", "callback_status", "blocked_efp_posts", "blocked_edof_posts", "blocked_other_posts", "invalid_form_fields"):
        value = signals.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 9999:
            result[key] = value
    return result


class StopRun(Exception):
    def __init__(self, code):
        self.code = code


def run_browser(spec):
    if os.environ.get("RENDER_SERVICE_ID") != TEST_SERVICE_ID:
        return {"code": "wrong_environment"}
    from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout

    stage = "browser"
    blocked = 0
    lists = []
    details = {}
    invalid_response = False
    signals = {"blocked_efp_posts": 0, "blocked_edof_posts": 0, "blocked_other_posts": 0}

    def route_request(route):
        nonlocal blocked
        if permitted_request(route.request.url, route.request.method):
            route.continue_()
        else:
            blocked += 1
            host = urlsplit(route.request.url).hostname
            key = "blocked_efp_posts" if host == EFP_HOST else "blocked_edof_posts" if host == EDOF_HOST else "blocked_other_posts"
            signals[key] += 1
            route.abort()

    def observe(response):
        nonlocal invalid_response
        parsed = urlsplit(response.url)
        if response.request.method == "POST" and parsed.hostname == EFP_HOST and parsed.path == "/auth/realms/efp/login-actions/authenticate":
            signals["login_post_status"] = response.status
        if parsed.hostname == EDOF_HOST and parsed.path == "/idp/edof/api/v2/callback":
            signals["callback_status"] = response.status
        if response.request.method != "GET" or response.status != 200 or parsed.hostname != EDOF_HOST or not parsed.path.startswith(API_PREFIX):
            return
        tail = parsed.path[len(API_PREFIX):]
        if tail != "pad" and not re.fullmatch(r"[0-9]{6,20}", tail):
            return
        try:
            # Bound the body we parse; no complete response ever reaches stdout.
            body = response.body()
            if len(body) > 2_000_000:
                return
            raw = json.loads(body)
            if tail == "pad" and isinstance(raw, dict) and isinstance(raw.get("items"), list):
                items = []
                for item in raw["items"][:100]:
                    attendee = item.get("attendee") or {}
                    folder_id = item.get("id", "")
                    if isinstance(folder_id, str) and re.fullmatch(r"[0-9]{6,20}", folder_id):
                        items.append({"id": folder_id, "first_name": attendee.get("firstName"), "last_name": attendee.get("lastName")})
                lists.append({"items": items, "total": raw.get("numberOfItems")})
                del lists[:-2]
            elif isinstance(raw, dict) and raw.get("id") == tail:
                # Keep only the specifically requested dossier, or a shortlisted
                # result subsequently opened by this runner.
                if tail == spec.get("folder_id") or tail == spec.get("selected_id"):
                    details[tail] = project_folder(raw)
        except Exception:
            invalid_response = True

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(locale="fr-FR", accept_downloads=False, service_workers="block")
            context.route("**/*", route_request)
            page = context.new_page()
            page.set_default_timeout(12000)
            page.on("response", observe)

            def diagnostics():
                try:
                    signals["invalid_form_fields"] = page.locator('input:invalid:visible').count()
                    return diagnostic_summary(page.url,
                        page.locator('input[type="password"]:visible').count() > 0,
                        page.locator('#input-error:visible, .alert-error:visible, .pf-m-danger:visible, .fr-alert--error:visible').count() > 0,
                        signals)
                except Exception:
                    return diagnostic_summary(page.url, False, False, signals)

            def checkpoint():
                # Only derive categorical signals; never return the page body,
                # which could contain identity information or an auth code.
                text = page.locator("body").inner_text(timeout=3000)
                code = classify_text(text)
                if code:
                    raise StopRun(code)
                if page.locator('input[autocomplete="one-time-code"]:visible, input[name="otp"]:visible, input[name="totp"]:visible, input[name="code"]:visible').count():
                    raise StopRun("verification_code")
                if page.locator('iframe[title*="captcha" i]:visible, iframe[title*="challenge" i]:visible').count():
                    raise StopRun("human_verification")
                if location_category(page.url) == "efp_required_action":
                    raise StopRun("account_action_required")
                if stage == "authentication" and page.locator('#input-error:visible, .alert-error:visible, .pf-m-danger:visible, .fr-alert--error:visible').count():
                    raise StopRun("sign_in_error")

            stage = "login_page"
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_url(f"https://{EFP_HOST}/auth/**", timeout=30000)
            page.locator('input[name="username"]').wait_for(state="visible")
            checkpoint()
            if spec["mode"] == "access":
                return {"code": "login_reachable", "stage": stage, "fresh_session": True}

            username = os.environ.get("EDOF_EFP_USERNAME", "").strip()
            password = os.environ.get("EDOF_EFP_PASSWORD", "")
            if not username or not password:
                return {"code": "credentials_missing", "stage": stage, "fresh_session": True}
            # Fail closed before sending credentials if navigation changed host.
            if urlsplit(page.url).hostname != EFP_HOST:
                raise StopRun("unexpected_page")
            stage = "authentication"
            target = page.locator('input[name="username"]').evaluate("el => el.form ? {action: el.form.action, method: el.form.method.toUpperCase()} : null")
            if not target or not permitted_request(target["action"], target["method"]) or target["method"] != "POST":
                raise StopRun("login_form_not_allowed")
            target = None
            page.locator('input[name="username"]').fill(username)
            page.locator('input[name="password"]').fill(password)
            page.locator("#kc-login").click()
            username = password = None
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                checkpoint()
                if urlsplit(page.url).hostname == EDOF_HOST and "/espace-prive/" in page.url:
                    break
                page.wait_for_timeout(500)
            else:
                raise StopRun("authentication_unconfirmed")

            stage = "organism"
            # EDOF can ask which establishment to open. Only select our SIRET.
            if "select-siret" in page.url:
                choice = page.get_by_text(SIRET, exact=False)
                if choice.count() != 1:
                    raise StopRun("organism_selection_required")
                choice.click()
                page.wait_for_timeout(1000)
                checkpoint()

            if not spec.get("folder_id"):
                stage = "search"
                page.goto(LIST_URL, wait_until="domcontentloaded")
                page.get_by_text("Par Nom de stagiaire", exact=True).click()
                search = page.get_by_placeholder(re.compile("Rechercher un dossier de formation", re.I))
                if search.count() != 1:
                    raise StopRun("search_unconfirmed")
                search.fill(spec["last_name"])
                lists.clear()
                search.press("Enter")
                deadline = time.monotonic() + 15
                while not lists and time.monotonic() < deadline:
                    checkpoint()
                    page.wait_for_timeout(250)
                if not lists:
                    raise StopRun("search_unconfirmed")
                result = lists[-1]
                candidates = [item for item in result["items"] if identity(item["first_name"]) == identity(spec["first_name"]) and identity(item["last_name"]) == identity(spec["last_name"])]
                # Never infer uniqueness from a truncated/paginated result.
                if not isinstance(result["total"], int) or result["total"] > len(result["items"]):
                    raise StopRun("search_incomplete")
                if not candidates:
                    raise StopRun("no_match")
                if len(candidates) != 1:
                    return {"code": "ambiguous", "stage": stage, "candidate_count": len(candidates), "fresh_session": True}
                spec["selected_id"] = candidates[0]["id"]
            else:
                spec["selected_id"] = spec["folder_id"]

            stage = "dossier"
            folder_id = spec["selected_id"]
            page.goto(DETAIL_PREFIX + folder_id, wait_until="domcontentloaded")
            deadline = time.monotonic() + 20
            while folder_id not in details and time.monotonic() < deadline:
                checkpoint()
                page.wait_for_timeout(250)
            if folder_id not in details:
                raise StopRun("response_unrecognized" if invalid_response else "read_unconfirmed")
            fields = details[folder_id]
            if spec.get("first_name") and (identity(fields["first_name"]) != identity(spec["first_name"]) or identity(fields["last_name"]) != identity(spec["last_name"])):
                raise StopRun("identity_mismatch")
            return {"code": "read_success", "stage": stage, "fields": fields, "fresh_session": True, "blocked_writes": blocked}
        except StopRun as exc:
            return {"code": exc.code, "stage": stage, "fresh_session": True, "blocked_writes": blocked, "diagnostics": diagnostics()}
        except BrowserTimeout:
            try:
                checkpoint()
            except StopRun as exc:
                return {"code": exc.code, "stage": stage, "fresh_session": True, "diagnostics": diagnostics()}
            except Exception:
                pass
            return {"code": "timeout", "stage": stage, "fresh_session": True, "diagnostics": diagnostics()}
        except Exception:
            # Playwright exception text may include filled values or URLs with
            # authentication parameters; never print or log it.
            return {"code": "browser_error", "stage": stage, "fresh_session": True, "diagnostics": diagnostics()}
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        specification = json.loads(sys.stdin.read(4096))
        result = run_browser(specification)
    except ImportError:
        result = {"code": "browser_missing"}
    except Exception:
        result = {"code": "browser_error"}
    print(json.dumps(result, ensure_ascii=False))
