"""Short-lived, read-only EDOF browser used by the Test V2 access experiment.

Input is a small search specification on stdin. Output is one allowlisted JSON
result. No screenshots, traces, raw responses or mail bodies are persisted.
Only server-created authentication cookies may be saved in the encrypted vault;
no cookie or token is taken from the user's Chrome.
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
from edof_gmail import Vault, GmailCodes, GmailError

EDOF_HOST = "of.moncompteformation.gouv.fr"
EFP_HOST = "efpconnect.emploi.gouv.fr"
LOGIN_URL = f"https://{EDOF_HOST}/espace-prive/html/#/redirect-to-mire-connexion"
LIST_URL = f"https://{EDOF_HOST}/espace-prive/html/#/dossiers/en-cours"
DETAIL_PREFIX = f"https://{EDOF_HOST}/espace-prive/html/#/dossiers/detail/"
WORKSPACE_API_PREFIX = f"/edof-api/v1/api/private/siret/{SIRET}/"
API_PREFIX = WORKSPACE_API_PREFIX + "organisms/current/registration-folders/"
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
OTP_SELECTOR = 'input[autocomplete="one-time-code"]:visible, input[name="otp"]:visible, input[name="totp"]:visible, input[name="code"]:visible'


def session_cookies(state):
    allowed = {EFP_HOST, "emploi.gouv.fr", EDOF_HOST, "moncompteformation.gouv.fr"}
    return {"cookies": [cookie for cookie in state.get("cookies", []) if cookie.get("domain", "").lstrip(".") in allowed and cookie.get("secure")], "origins": []}


def private_page(url):
    parsed = urlsplit(url)
    route = parsed.fragment.partition("?")[0].rstrip("/")
    return (parsed.hostname == EDOF_HOST and parsed.path.startswith("/espace-prive/")
            and route.startswith("/") and route != "/redirect-to-mire-connexion")


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
            route = parsed.fragment.partition("?")[0].rstrip("/")
            if not route or not route.startswith("/"):
                return "edof_initialisation"
            if route == "/redirect-to-mire-connexion":
                return "edof_login_redirect"
            if route == "/dossiers/en-cours":
                return "edof_folder_list"
            if re.fullmatch(r"/dossiers/detail/[0-9]{6,20}", route):
                return "edof_folder_detail"
            return "edof_select_siret" if "select-siret" in route.split("/") else "edof_private"
        if parsed.path.startswith("/espace-public/"):
            return "edof_public"
        if parsed.path.startswith("/edof-api/"):
            return "edof_api"
        return "edof_other"
    return "other_origin"


# Render short route shapes using only fixed public vocabulary. Unknown
# components, ids, query strings, fragments, headers and bodies never leave
# the browser, including when a provider adds a new authentication step.
ROUTE_WORDS = frozenset("""
    idp edof api v1 v2 v3 public private espace prive html auth authentication
    authentification authorization authorize oauth oauth2 openid connect protocol
    real realm realms login signin logout connexion callback redirect redirection
    mire code grant token tokens access refresh exchange generate validate check
    session sessions user users userinfo info me account current of organismes
    organisms siret select selection switch unknown establishment etablissement
    client clients identity credentials get post create set init initialize return
    registration folders pad in training service done declared validated notifications
    message messages read unread acknowledge accept acceptance consent consents cgu
    authenticate exchange logout-ticket jwt jwts cas keycloak tickets ticket validate
    provider providers identification tokeninfo verifier verify callback request
    saml2 authorize-idp connexion-efp authentifier portal portail credentials
    terms conditions preferences profile profiles trace traces analytics telemetry
    collect events event monitoring log logs tracking stats statistics matomo js environments
    saml sso federation state status context contexts connection proxy authenticationgateway
""".split())


def safe_edof_route(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != EDOF_HOST:
        return "other_origin"
    shape = []
    for segment in parsed.path.strip("/").split("/")[:12]:
        words = re.sub(r"([a-z])([A-Z])", r"\1-\2", segment).lower().split("-")
        shape.append("-".join(words) if words and all(w in ROUTE_WORDS for w in words) else "*")
    return "/" + "/".join(shape)


def diagnostic_summary(location, password_visible, error_visible, signals):
    """Allowlist scalar signals; deliberately no page/error/input text."""
    result = {"location": location_category(location), "password_form_visible": bool(password_visible), "error_banner_visible": bool(error_visible)}
    for key in ("login_post_status", "callback_status", "workspace_status", "folder_list_status", "folder_detail_status", "blocked_efp_posts", "blocked_edof_posts", "blocked_other_posts", "invalid_form_fields"):
        value = signals.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 9999:
            result[key] = value
    # The only source of these paths is the fixed vocabulary above.
    blocked = signals.get("edof_blocked_routes")
    if isinstance(blocked, list):
        result["edof_blocked_routes"] = [path for path in blocked[:4]
            if isinstance(path, str) and path.startswith("/") and len(path) < 200
            and safe_edof_route(f"https://{EDOF_HOST}" + path) == path]
    screen = signals.get("edof_screen")
    if screen in {"access_denied", "session_expired", "terms", "select_organisation",
                  "dashboard", "folders", "error", "loading", "empty", "other"}:
        result["edof_screen"] = screen
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
    vault = None
    saved = None
    reused = False
    otp_attempted = False
    gmail_code_used = False
    session_saved = False
    mailbox = None
    requested_at = None
    if spec["mode"] == "read" and os.environ.get("EDOF_CONNECTOR_KEY"):
        try:
            vault = Vault(os.environ["EDOF_CONNECTOR_DIRECTORY"], os.environ["EDOF_CONNECTOR_KEY"])
            saved = vault.get("browser")
        except Exception:
            return {"code": "private_storage_unavailable"}

    def route_request(route):
        nonlocal blocked
        if permitted_request(route.request.url, route.request.method):
            route.continue_()
        else:
            blocked += 1
            host = urlsplit(route.request.url).hostname
            key = "blocked_efp_posts" if host == EFP_HOST else "blocked_edof_posts" if host == EDOF_HOST else "blocked_other_posts"
            signals[key] += 1
            if host == EDOF_HOST and route.request.method == "POST":
                routes = signals.setdefault("edof_blocked_routes", [])
                shape = safe_edof_route(route.request.url)
                if len(routes) < 4 and shape not in routes:
                    routes.append(shape)
            route.abort()

    def observe(response):
        nonlocal invalid_response
        parsed = urlsplit(response.url)
        if response.request.method == "POST" and parsed.hostname == EFP_HOST and parsed.path == "/auth/realms/efp/login-actions/authenticate":
            signals["login_post_status"] = response.status
        if parsed.hostname == EDOF_HOST and parsed.path == "/idp/edof/api/v2/callback":
            signals["callback_status"] = response.status
        if response.request.method != "GET" or parsed.hostname != EDOF_HOST or not parsed.path.startswith(WORKSPACE_API_PREFIX):
            return
        if 200 <= response.status < 300:
            signals["workspace_status"] = response.status
        if not parsed.path.startswith(API_PREFIX):
            return
        tail = parsed.path[len(API_PREFIX):]
        if tail == "pad":
            signals["folder_list_status"] = response.status
        elif tail and tail in (spec.get("folder_id"), spec.get("selected_id")):
            signals["folder_detail_status"] = response.status
        else:
            return
        if response.status != 200:
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
            context = browser.new_context(locale="fr-FR", accept_downloads=False, service_workers="block", storage_state=saved)
            context.route("**/*", route_request)
            page = context.new_page()
            page.set_default_timeout(12000)
            page.on("response", observe)

            def diagnostics():
                try:
                    signals["invalid_form_fields"] = page.locator('input:invalid:visible').count()
                    if urlsplit(page.url).hostname == EDOF_HOST:
                        visible = identity(page.locator("body").inner_text(timeout=2000))
                        groups = (
                            ("access_denied", ("acces refuse", "vous n etes pas habilite", "vous n avez pas acces", "acces interdit")),
                            ("session_expired", ("session a expire", "session est expiree", "veuillez vous reconnecter")),
                            ("terms", ("j accepte les conditions", "accepter les conditions", "accepter la charte")),
                            ("select_organisation", ("selectionnez votre etablissement", "choisissez votre etablissement", "selectionnez un etablissement")),
                            ("folders", ("dossiers en cours",)), ("dashboard", ("tableau de bord",)),
                            ("error", ("une erreur", "erreur technique", "probleme technique")),
                            ("loading", ("chargement", "redirection en cours", "veuillez patienter")),
                        )
                        signals["edof_screen"] = next((key for key, phrases in groups if any(s in visible for s in phrases)), "other" if visible else "empty")
                    return diagnostic_summary(page.url,
                        page.locator('input[type="password"]:visible').count() > 0,
                        page.locator('#input-error:visible, .alert-error:visible, .pf-m-danger:visible, .fr-alert--error:visible').count() > 0,
                        signals)
                except Exception:
                    return diagnostic_summary(page.url, False, False, signals)

            def checkpoint(allow_otp=True):
                nonlocal otp_attempted, gmail_code_used
                # Only derive categorical signals; never return the page body,
                # which could contain identity information or an auth code.
                text = page.locator("body").inner_text(timeout=3000)
                code = classify_text(text)
                if code and code != "verification_code":
                    raise StopRun(code)
                if page.locator('iframe[title*="captcha" i]:visible, iframe[title*="challenge" i]:visible').count():
                    raise StopRun("human_verification")
                otp_fields = page.locator(OTP_SELECTOR)
                if code == "verification_code" or otp_fields.count():
                    if not allow_otp:
                        return
                    if otp_attempted:
                        raise StopRun("otp_rejected")
                    if stage != "authentication" or requested_at is None:
                        raise StopRun("verification_code")
                    if not mailbox:
                        raise StopRun("gmail_not_connected")
                    if urlsplit(page.url).hostname != EFP_HOST or otp_fields.count() != 1:
                        raise StopRun("otp_form_unrecognized")
                    target = otp_fields.evaluate("el => el.form ? {action: el.form.action, method: el.form.method.toUpperCase()} : null")
                    if not target or target["method"] != "POST" or not permitted_request(target["action"], target["method"]):
                        raise StopRun("otp_form_unrecognized")
                    otp_attempted = True
                    code_value = mailbox.wait_for_code(requested_at, tick=lambda: checkpoint(False))
                    # Recheck destination after the mail wait, before filling.
                    current = otp_fields.evaluate("el => el.form ? {action: el.form.action, method: el.form.method.toUpperCase()} : null")
                    if urlsplit(page.url).hostname != EFP_HOST or current != target:
                        raise StopRun("otp_form_unrecognized")
                    otp_fields.fill(code_value)
                    code_value = None
                    otp_fields.press("Enter")
                    gmail_code_used = True
                    # Give the normal form navigation a chance to finish; no
                    # repeat submission, resend or new code on any failure.
                    page.wait_for_timeout(1200)
                    return
                if location_category(page.url) == "efp_required_action":
                    raise StopRun("account_action_required")
                if stage == "authentication" and page.locator('#input-error:visible, .alert-error:visible, .pf-m-danger:visible, .fr-alert--error:visible').count():
                    raise StopRun("sign_in_error")

            stage = "login_page"
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if saved and private_page(page.url):
                    reused = True
                    break
                if urlsplit(page.url).hostname == EFP_HOST and page.locator('input[name="username"]:visible').count():
                    break
                checkpoint()
                page.wait_for_timeout(500)
            else:
                raise StopRun("authentication_unconfirmed")
            if spec["mode"] == "access":
                checkpoint()
                return {"code": "login_reachable", "stage": stage, "fresh_session": True}

            username = os.environ.get("EDOF_EFP_USERNAME", "").strip()
            password = os.environ.get("EDOF_EFP_PASSWORD", "")
            if not username or not password:
                return {"code": "credentials_missing", "stage": stage, "fresh_session": True}
            if not reused:
                checkpoint()
                if urlsplit(page.url).hostname != EFP_HOST:
                    raise StopRun("unexpected_page")
                stage = "authentication"
                target = page.locator('input[name="username"]').evaluate("el => el.form ? {action: el.form.action, method: el.form.method.toUpperCase()} : null")
                if not target or not permitted_request(target["action"], target["method"]) or target["method"] != "POST":
                    raise StopRun("login_form_not_allowed")
                if not vault:
                    raise StopRun("private_storage_unavailable")
                # Refresh Google and record pre-existing mail BEFORE requesting
                # an EFP code. This cannot reuse a code from an earlier run.
                mailbox = GmailCodes(vault, username)
                target = None
                page.locator('input[name="username"]').fill(username)
                page.locator('input[name="password"]').fill(password)
                requested_at = time.time()
                page.locator("#kc-login").click()
                username = password = None
                deadline = time.monotonic() + 70
                while time.monotonic() < deadline:
                    checkpoint()
                    if private_page(page.url):
                        break
                    page.wait_for_timeout(500)
                else:
                    raise StopRun("authentication_unconfirmed")

            stage = "organism"
            # The OAuth callback may open the SPA before its organisation
            # session is ready. Let EDOF complete that flow before navigating.
            choice_clicked = False
            dossier_menu = page.locator('a[href$="/dossiers/en-cours"]')
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                checkpoint()
                if location_category(page.url) == "edof_select_siret":
                    choice = page.get_by_text(SIRET, exact=False).filter(visible=True)
                    if not choice_clicked and choice.count() == 1:
                        choice.click()
                        choice_clicked = True
                elif private_page(page.url) and (signals.get("workspace_status") or dossier_menu.count()):
                    break
                page.wait_for_timeout(300)
            else:
                raise StopRun("organism_selection_required")

            if not spec.get("folder_id"):
                stage = "search"
                page.goto(LIST_URL, wait_until="domcontentloaded")
                page.get_by_text(re.compile(r"^Par nom d(?:u|e) stagiaire$", re.I)).click()
                search = page.get_by_placeholder(
                    re.compile(r"rechercher un dossier de formation|nom (?:du |de )?stagiaire", re.I)
                ).and_(page.locator("input:visible"))
                search.wait_for(state="visible")
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
                    return {"code": "ambiguous", "stage": stage, "candidate_count": len(candidates), "fresh_session": not reused, "gmail_code_used": gmail_code_used}
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
            if vault:
                # Save only after a real authorised dossier response; never
                # save an incomplete/OTP/challenge session or local storage.
                vault.put("browser", session_cookies(context.storage_state()), ttl=86400)
                session_saved = True
            return {"code": "read_success", "stage": stage, "fields": fields, "fresh_session": not reused, "gmail_code_used": gmail_code_used, "session_saved": session_saved, "blocked_writes": blocked}
        except GmailError as exc:
            return {"code": exc.code, "stage": stage, "fresh_session": not reused, "gmail_code_used": gmail_code_used, "diagnostics": exc.diagnostics}
        except StopRun as exc:
            if vault and exc.code in {"credentials_rejected", "account_unavailable", "otp_rejected", "verification_code", "sign_in_error"}:
                vault.delete("browser")
            return {"code": exc.code, "stage": stage, "fresh_session": not reused, "gmail_code_used": gmail_code_used, "blocked_writes": blocked, "diagnostics": diagnostics()}
        except BrowserTimeout:
            try:
                checkpoint(False)
            except StopRun as exc:
                return {"code": exc.code, "stage": stage, "fresh_session": not reused, "gmail_code_used": gmail_code_used, "diagnostics": diagnostics()}
            except Exception:
                pass
            return {"code": "timeout", "stage": stage, "fresh_session": not reused, "gmail_code_used": gmail_code_used, "diagnostics": diagnostics()}
        except Exception:
            # Playwright exception text may include filled values or URLs with
            # authentication parameters; never print or log it.
            return {"code": "browser_error", "stage": stage, "fresh_session": not reused, "gmail_code_used": gmail_code_used, "diagnostics": diagnostics()}
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
