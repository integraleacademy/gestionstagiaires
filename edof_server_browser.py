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
from urllib.parse import parse_qs, urlsplit

from edof_readonly_test import (
    ATTENDEE_FIELDS, INFO_FIELDS, SIRET, TEST_SERVICE_ID, TOP_FIELDS,
    normalize_observation,
)
from edof_gmail import Vault, GmailCodes, GmailError

EDOF_HOST = "of.moncompteformation.gouv.fr"
EFP_HOST = "efpconnect.emploi.gouv.fr"
EDOF_CALLBACK_PATH = "/idp/edof/api/v2/callback"
EDOF_TOKEN_PATH = "/idp/edof/api/v2/token"
LOGIN_URL = f"https://{EDOF_HOST}/espace-prive/html/#/redirect-to-mire-connexion"
LIST_URL = f"https://{EDOF_HOST}/espace-prive/html/#/dossiers/en-cours"
DETAIL_PREFIX = f"https://{EDOF_HOST}/espace-prive/html/#/dossiers/detail/"
WORKSPACE_API_PREFIX = f"/edof-api/v1/api/private/siret/{SIRET}/"
API_PREFIX = WORKSPACE_API_PREFIX + "organisms/current/registration-folders/"
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
OTP_SELECTOR = 'input[autocomplete="one-time-code"]:visible, input[name="otp"]:visible, input[name="totp"]:visible, input[name="code"]:visible'
SIRET_TEXT = re.compile(r"(?<!\d)" + r"[\s.]*".join(SIRET) + r"(?!\d)")
CHOOSER_ROUTE = re.compile(r"(?:choix|choisir|select|selection|selectionner)[-/]?(?:du[-/]|de[-/]l[-/])?(?:sirets?|organismes?|etablissements?)\b")
CHOOSER_TEXT = re.compile(r"\b(?:choisir|choisissez|choix|selection|selectionner|selectionnez)\b.{0,55}\b(?:siret|organisme|etablissement)s?\b")
CONFIRM_ESTABLISHMENT = re.compile(
    r"^(?:(?:Valider|Confirmer)(?: (?:mon choix|ma sélection|le SIRET))?|Continuer|"
    r"Acc[ée]der(?: à (?:mon|votre|cet|l[’'])\s*espace(?: (?:professionnel|EDOF))?| à EDOF)?|"
    r"(?:Me |Se )?connecter(?: à (?:mon espace|EDOF))?)$", re.I)
ESTABLISHMENT_STEPS = {"waiting", "keyboard", "opened", "filtered", "searched", "selected", "confirmed"}
CHOOSER_ACTIONS = {"open_keyboard", "open_click", "select_native", "select_radio", "select_text",
                   "filter", "search", "confirm", "dismiss_cookies", "close_notice"}
SIRET_FIELD = re.compile(r"siret|[ée]tablissement|organisme", re.I)
CHOOSER_CONTROLS = {
    "list": 'select:visible, [role="listbox"]:visible',
    "combo": '[role="combobox"]:visible, [aria-haspopup="listbox"]:visible',
    "radio": 'input[type="radio"]:visible, [role="radio"]:visible',
    "input": 'input:not([type]):visible, input[type="text"]:visible, input[type="search"]:visible, input[type="tel"]:visible, input[type="number"]:visible',
    "button": 'button:visible, input[type="submit"]:visible, [role="button"]:visible',
}
CHOOSER_WORDS = frozenset("""
    acceder acces a au aux avec ce cet cette changer choix choisir choisissez confirmer
    connexion connecter connectez continuer edof effectuer entrer etablissements etablissement
    espace formation inscription l la le les liste ma me mon organisme organismes professionnel
    professionnels rechercher recherche saisir se selection selectionnez selectionner siret sirets
    sous suivant suivante un une valider validation votre vous de des du en mes sur
    accepter cookies consentement continuer fermer ma sans refuser tout tous les parametres
""".split())
DIALOG_WORDS = CHOOSER_WORDS | set("""
    je j ai compris ok non merci plus tard passer visite fermer fermez cette fenetre boite
    dialogue modale pop in message information informations important importante importantes
    notification actualite actualites nouveaute nouveautes nouveau nouvelle bienvenue decouvrir
    presentation changement lire prendre connaissance attention obligatoire obligatoires
    conditions generales utilisation charte regles mentions legales acceptez cgu accepter
    signature engagement consentement confidentialite politique protection donnees personnelles
    parametrer choix preferences enregistrer personnaliser traceurs essentiels necessaires
    erreurs erreur technique indisponible maintenance droit droits habilitation habilitations
    identite verification authentification securite compte profil session expiree expiration
    code telephone mail adresse service numerique site portail application organisme formation
    organismes selectionnez accueil connexion et es platforme plateforme sur ce par pour que
    ne pas afficher cet avertissement rappel plus prendre connaissance suite lecture cliquez
    poursuivre authentifier identification valide validez validation acceder fermer continuer
    derniere mise jour version activer vous devez vos le les ces ce des n d dit c est ai
    annuler retour enregistrer valider nouveau mot passe referencement obligatoire responsable
    references formation contrat declarations stagiaires factures dossiers temps chargement
""".split())
DIALOG_CLOSE = re.compile(r"^(?:Close|Fermer(?: (?:la|cette|le|ce|l[’'])\s*(?:fen[êe]tre(?: de dialogue)?|bo[iî]te de dialogue|modale|message|notification|pop[- ]?in|alerte))?)$", re.I)
DIALOG_ACK = re.compile(r"^(?:J[’']ai compris|Compris|Plus tard|Non merci|Passer la visite)$", re.I)
# Material includes a decorative icon before the visible refusal wording.
COOKIE_DECLINE = re.compile(r"^(?!.*\b(?:accepter|autoriser|ne pas)\b.*\brefuser\b)(?:.*\s)?(?:tout refuser(?: et (?:fermer|continuer))?|refuser tout|refuser tous les cookies|continuer sans accepter)[.!]?\s*$", re.I | re.S)
NAME_TAB = re.compile(r"\bpar\s+nom\s+du\s+stagiaire\b", re.I)
NAME_FIELD = re.compile(r"\bnom\s+(?:du\s+|de\s+)?stagiaire\b|\bpar\s+nom\b", re.I)
TRAINEE_SURNAME = 'input[name="searchByRegistrationFolderTraineeName"]:visible'
TRAINEE_FIRST_NAME = 'input[name="searchByRegistrationFolderTraineeFirstName"]:visible'


def decline_cookies_control(root):
    return root.get_by_role("button", name=COOKIE_DECLINE).or_(root.get_by_role("link", name=COOKIE_DECLINE)).filter(visible=True)


def activate_cookie_refusal(page, target):
    # Follow the modal's natural tab order. Enter is sent only when the exact
    # visible refusal action, or a child of it, has keyboard focus.
    for _ in range(24):
        focused = target.evaluate_all("""els => {
            if (els.length !== 1) return false;
            const e = els[0], root = e.getRootNode();
            return !!root.activeElement && e.contains(root.activeElement);
        }""")
        if focused:
            page.keyboard.press("Enter")
            return "keyboard"
        if target.count() != 1:
            return "disappeared"
        page.keyboard.press("Tab")
    # Some legitimate cookie banners do not include their links in tab order.
    # A normal click still requires the target to receive pointer events.
    target.click(no_wait_after=True, timeout=6000)
    return "pointer"


def dialog_labels(values):
    """Mask any word outside the fixed UI vocabulary, including names and IDs."""
    labels = []
    for value in values[:12]:
        words = [word if word in DIALOG_WORDS else "…" for word in identity(value).split()[:18]]
        label = " ".join(word for i, word in enumerate(words) if word != "…" or i == 0 or words[i-1] != "…")
        if label and label != "…" and label not in labels:
            labels.append(label)
    return labels


def dialog_kind(text):
    words = identity(text)
    if any(x in words for x in ("conditions generales", "j accepte", "accepter les conditions", "la charte", "sur l honneur", "je certifie", "je m engage")):
        return "terms"
    if any(x in words for x in ("cookie", "traceurs")):
        return "cookies"
    if workspace_screen(text) in {"access_denied", "error", "session_expired"}:
        return "error"
    if any(x in words for x in ("identite", "mot de passe", "code de securite", "habilitation", "authentification")):
        return "account"
    if any(x in words for x in ("information", "nouveau", "nouveaute", "nouvelle", "bienvenue", "visite guidee", "actualite")):
        return "notice"
    return "other"


def handle_chooser_dialog(page, signals):
    """Handle a visible EDOF notice; return whether the chooser is still covered."""
    layer = page.locator(".cdk-overlay-container:visible").filter(has=page.locator(".cdk-overlay-backdrop:visible"))
    texts = layer.all_inner_texts()
    if len(texts) != 1 or layer.get_by_role("listbox").count():
        if signals.get("cookies_dismissed"):
            signals["cookie_dialog_closed"] = True
        return False
    text = texts[0]
    # Material sometimes attaches the backdrop before rendering the panel.
    if not text.strip() and not layer.locator("iframe:visible").count():
        signals["dialog_kind"] = "loading" if layer.locator('[role=progressbar],mat-spinner,mat-progress-spinner,.spinner').count() else "empty"
        return True
    buttons = layer.get_by_role("button").or_(layer.get_by_role("link")).filter(visible=True)
    kind = dialog_kind(text)
    if kind == "cookies" and signals.get("cookies_dismissed"):
        return True
    signals["dialog_kind"] = kind
    signals["dialog_headings"] = dialog_labels(layer.locator('h1,h2,h3,[role=heading],[mat-dialog-title],.mat-mdc-dialog-title').all_inner_texts())
    signals["dialog_buttons"] = dialog_labels(buttons.evaluate_all("""nodes => nodes.map(n =>
        n.getAttribute('aria-label') || n.innerText?.trim() || n.getAttribute('title') || '')"""))
    # A short redacted excerpt helps identify a notice whose title is not a heading.
    signals["dialog_prompt"] = dialog_labels([line for line in text.splitlines() if line.strip()][:3])
    frames_or_inputs = layer.locator('iframe:visible,input:visible,select:visible,textarea:visible,[role=checkbox]:visible,[role=combobox]:visible')
    if kind in {"terms", "error", "account"} or (kind != "cookies" and frames_or_inputs.count()):
        raise StopRun("workspace_dialog_required")
    dismissed = "cookies_dismissed" if kind == "cookies" else "notice_closed"
    if signals.get(dismissed):
        return True
    if kind == "cookies":
        target = decline_cookies_control(layer)
    else:
        target = layer.get_by_role("button", name=DIALOG_CLOSE)
        if target.count() != 1 and kind == "notice":
            target = layer.get_by_role("button", name=DIALOG_ACK)
    if target.count() != 1 or not target.is_visible() or not target.is_enabled():
        raise StopRun("workspace_dialog_required")
    signals["chooser_action"] = "dismiss_cookies" if kind == "cookies" else "close_notice"
    signals[dismissed] = True
    if kind == "cookies":
        signals["cookie_activation"] = activate_cookie_refusal(page, target)
    else:
        target.click(timeout=3000)
    return True

# A custom select can expose a clipped ARIA control next to the visible trigger.
# Identify a real, unobstructed pointer target within the same widget. An
# unrelated overlay, iframe or dialog never becomes a target.
CHOOSER_HIT_TEST = r"""e => {
    const popup = 'dialog,[role="dialog"],[role="alertdialog"],[aria-modal="true"],.modal,.modal-backdrop,iframe';
    const center = n => {
        const r = n.getBoundingClientRect();
        return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    };
    const hit = center(e);
    const info = {surface: 'covered', depth: 0};
    if (hit?.closest(popup)) return {...info, surface:'dialog'};
    if (hit && e.contains(hit)) return {...info, surface:'control'};
    if (hit?.closest('label')?.control === e) return {...info, surface:'label'};

    for (let n=e.parentElement, depth=1; n && depth<=7; n=n.parentElement, depth++) {
        if (n.matches('body,html,form,main,section,fieldset,' + popup)) break;
        const type = n.localName + ' ' + Array.from(n.classList).join(' ');
        if (!/select|dropdown|combobox|listbox|list-box|menu-deroulant/i.test(type)) continue;
        const controls = n.querySelectorAll('[role=combobox],select');
        if (controls.length > 1 || n.querySelector('input[type=password],input[type=checkbox],button[type=submit]')) continue;
        const r = n.getBoundingClientRect(), target = center(n);
        if (r.width < 22 || r.height < 14 || r.height > 130 || !target || !n.contains(target) || target.closest(popup)) continue;
        const button = target.closest('button,a,input');
        if (button && button !== e && !button.matches('[aria-haspopup=listbox],[aria-expanded],button[type=button]:empty')) continue;
        return {surface:'widget', depth};
    }
    if (!hit) return {...info, surface:'offscreen'};
    if (e.parentElement !== document.body && e.parentElement?.contains(hit)) return {...info, surface:'parent'};
    return info;
}"""


def chooser_element_shape(components):
    """Retain generic markup vocabulary only; no text, IDs or arbitrary class names."""
    words = set("""div span label ul li select input i svg path button p body html section main form
        mat mdc cdk ng p ui fr dsfr edof angular react select select2 choices dropdown combobox
        control container trigger value wrapper field hidden accessible visually sr only placeholder
        overlay modal backdrop dialog banner cookie cookies consent fixed sticky header footer
        icon arrow panel options content box group list disabled block screen blockui
        tarteaucitron didomi onetrust preference preferences drupal""".split())
    shape = []
    for component in components[:6]:
        parts = re.findall(r"[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1-\2", component).lower())
        known = list(dict.fromkeys(word for word in parts if word in words))
        shape.append("-".join(known[:8]) or "*")
    return shape


def standard_choice_labels(labels):
    """Only known navigation words may appear in the private test diagnostics."""
    result = []
    for label in labels:
        words = identity(label).split()
        if 0 < len(words) <= 10 and all(word in CHOOSER_WORDS for word in words):
            value = " ".join(words)
            if value not in result:
                result.append(value)
    return result[:8]


def session_cookies(state):
    allowed = {EFP_HOST, "emploi.gouv.fr", EDOF_HOST, "moncompteformation.gouv.fr"}
    return {"cookies": [cookie for cookie in state.get("cookies", []) if cookie.get("domain", "").lstrip(".") in allowed and cookie.get("secure")], "origins": []}


def private_page(url):
    parsed = urlsplit(url)
    route = parsed.fragment.partition("?")[0].rstrip("/")
    return (parsed.hostname == EDOF_HOST and parsed.path.startswith("/espace-prive/")
            and route.startswith("/") and route != "/redirect-to-mire-connexion")


def confirmed_dashboard(url, signals):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc == EDOF_HOST
            and private_page(url) and parsed.fragment.partition("?")[0].rstrip("/") == "/tableau-de-bord"
            and signals.get("chooser_action") == "confirm" and signals.get("workspace_status") == 200)


def restored_workspace(page, signals):
    if not private_page(page.url):
        return False
    if signals.get("workspace_status") == 200:
        return True
    return (location_category(page.url) == "edof_select_siret"
            and page.locator('mat-select[role="combobox"]:visible').count() == 1)


def inactive_saved_view(page, signals):
    if location_category(page.url) not in {"edof_initialisation", "edof_folder_list", "edof_login_redirect"}:
        return False
    if signals.get("workspace_status") or signals.get("workspace_denied"):
        return False
    body = " ".join(page.locator("body").all_inner_texts())
    if workspace_screen(body) not in {"empty", "loading", "session_expired", "other"} or classify_text(body):
        return False
    return not page.locator('[aria-modal=true]:visible,[role=alertdialog]:visible,[role=dialog]:visible,'
                            'iframe[title*="captcha" i]:visible,input:visible').count()


def open_workspace_or_login(page, context, saved, signals, checkpoint):
    # A restored browser enters the actual workspace. The explicit login route
    # is for signing in and may leave an already authenticated browser on a blank shell.
    entries = (LIST_URL, LOGIN_URL) if saved else (LOGIN_URL,)
    for entry in entries:
        if saved and entry == LOGIN_URL:
            # Only an inert first-party shell can take this recovery path. Keep
            # EFP's existing sign-in and device cookies for its normal SSO flow.
            if not inactive_saved_view(page, signals):
                raise StopRun("authentication_unconfirmed")
            context.clear_cookies(domain=re.compile(r"^\.?(?:of\.)?moncompteformation\.gouv\.fr$"))
        page.goto(entry, wait_until="domcontentloaded", timeout=45000)
        deadline = time.monotonic() + (18 if saved else 30)
        while time.monotonic() < deadline:
            checkpoint()
            if urlsplit(page.url).hostname == EFP_HOST and page.locator('input[name="username"]:visible').count():
                return False
            if saved and restored_workspace(page, signals):
                return True
            page.wait_for_timeout(500)
    if saved and inactive_saved_view(page, signals):
        # No password or code has been sent in this run. The caller can open a
        # clean browser and use the regular login flow exactly once.
        raise StopRun("saved_session_unavailable")
    raise StopRun("authentication_unconfirmed")


def open_folder_view(page, url, arrived, timeout_error):
    """A hash navigation may already have delivered the requested view when it times out."""
    if page.url == url and arrived():
        return
    try:
        page.goto(url, wait_until="commit", timeout=18000)
    except timeout_error:
        if page.url != url or not arrived():
            raise


def matches_name_query(query, surname, first_name, paired):
    filters = parse_qs(query, keep_blank_values=True)
    names = [value.strip().casefold() for value in filters.get("attendeeName", [])]
    given = [value.strip().casefold() for value in filters.get("attendeeFirstName", [])]
    if not surname or not first_name or names != [surname.strip().casefold()]:
        return False
    return given == [first_name.strip().casefold()] or (not paired and given in ([], [""]))


def submit_name_search(page, surname, first_name, lists, signals, timeout_error):
    inputs = page.locator("input:visible")
    named_surname = page.locator(TRAINEE_SURNAME)
    given = page.locator(TRAINEE_FIRST_NAME)
    name_field = named_surname.or_(page.get_by_placeholder(NAME_FIELD)).or_(page.get_by_label(NAME_FIELD)).and_(inputs)
    search = name_field
    if name_field.count() != 1:
        signals["search_step"] = "name_mode"
        tab = page.get_by_text(NAME_TAB).filter(visible=True)
        try:
            tab.click(no_wait_after=True, timeout=8000)
        except timeout_error:
            if name_field.count() != 1:
                raise
        try:
            name_field.wait_for(state="visible", timeout=3000)
        except timeout_error:
            search = page.get_by_placeholder(re.compile(r"rechercher un dossier de formation", re.I)).and_(inputs)
    signals["search_step"] = "input"
    search.wait_for(state="visible", timeout=8000)
    paired = named_surname.count() == 1 or given.count() == 1
    signals["paired_name_search"] = paired
    lists.clear()
    search.fill(surname, timeout=8000)
    if paired:
        given.fill(first_name, timeout=8000)
        search = given
    signals["search_step"] = "submit"
    # The visible blue search arrow shares a small container with the field.
    # If it is not a unique, identifiable search control, use the field's Enter action.
    for depth in (1, 2, 3):
        group = search.locator("xpath=" + "/".join([".."] * depth))
        buttons = group.get_by_role("button").filter(visible=True)
        count = group.locator("input:visible").count()
        both_fields = paired and count == 2 and group.locator(TRAINEE_SURNAME).count() == 1
        if buttons.count() != 1 or (count != 1 and not both_fields):
            continue
        label = buttons.evaluate("e => [e.getAttribute('aria-label'),e.title,e.innerText].filter(Boolean).join(' ')")
        if (re.fullmatch(r"(?:rechercher|lancer la recherche|valider la recherche|search|arrow[_ ](?:forward|right(?:_alt)?))", label.strip(), re.I)
                or (not label.strip() and buttons.get_attribute("type") == "submit")):
            buttons.click(no_wait_after=True, timeout=5000)
            break
    else:
        search.press("Enter", no_wait_after=True, timeout=5000)
    signals["search_step"] = "results"


def permitted_request(url, method, *, edof_identity=False, frame_url=""):
    """Block business mutations even if the frontend initiates one itself."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if method in READ_METHODS:
        return True
    if parsed.scheme != "https" or method != "POST":
        return False
    # EDOF exchanges the completed EFP login before its private SPA loads.
    # This single same-origin identity endpoint cannot write a dossier.
    if edof_identity and parsed.netloc == EDOF_HOST and parsed.path == EDOF_TOKEN_PATH:
        origin = urlsplit(frame_url)
        return (origin.scheme == "https" and origin.netloc == EDOF_HOST
                and (origin.path.startswith("/espace-prive/") or origin.path == EDOF_CALLBACK_PATH))
    return parsed.netloc == EFP_HOST and (
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
        if parsed.path == EDOF_CALLBACK_PATH:
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
            return "edof_select_siret" if CHOOSER_ROUTE.search(route.lower()) else "edof_private"
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
    accueil home choix choisir selectionner etablissement etablissements organisme organismes
    siret sirets habilitation habilitations mes mon espace espaces tableau bord dashboard
    dossiers liste detail en cours erreur error acces droits profil profils bienvenue
    choix de du d l un une votre mon mes landing page selection structure structures
    maintenance unavailable indisponible forbidden unauthorized droits cgu charte legal
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


def workspace_screen(text):
    visible = identity(text)
    groups = (
        ("access_denied", ("acces refuse", "vous n etes pas habilite", "vous n avez pas acces", "acces interdit",
                           "demander un acces", "demander l acces", "demande d habilitation")),
        ("session_expired", ("session a expire", "session est expiree", "veuillez vous reconnecter")),
        ("terms", ("j accepte les conditions", "accepter les conditions", "accepter la charte")),
        ("folders", ("dossiers en cours",)), ("dashboard", ("tableau de bord",)),
        ("error", ("une erreur", "erreur technique", "probleme technique", "service indisponible", "en maintenance")),
        ("loading", ("chargement", "redirection en cours", "veuillez patienter")),
    )
    for key, phrases in groups:
        if any(phrase in visible for phrase in phrases):
            return key
    if CHOOSER_TEXT.search(visible):
        return "select_organisation"
    return "other" if visible else "empty"


def diagnostic_summary(location, password_visible, error_visible, signals):
    """Allowlist scalar signals; deliberately no page/error/input text."""
    result = {"location": location_category(location), "password_form_visible": bool(password_visible), "error_banner_visible": bool(error_visible)}
    if private_page(location):
        fragment = urlsplit(location).fragment.partition("?")[0]
        result["private_route"] = safe_edof_route(f"https://{EDOF_HOST}" + fragment)
        if signals.get("workspace_denied") is True:
            result["workspace_denied"] = True
        if signals.get("search_step") in {"opening_list", "name_mode", "input", "submit", "results"}:
            result["search_step"] = signals["search_step"]
        for key in ("name_tab_visible", "name_field_visible", "folder_field_visible"):
            if isinstance(signals.get(key), bool):
                result[key] = signals[key]
        if signals.get("timeout_cause") in {"covered", "hidden", "disabled", "navigation", "locator", "other"}:
            result["timeout_cause"] = signals["timeout_cause"]
        if isinstance(signals.get("expected_establishment_visible"), bool):
            result["expected_establishment_visible"] = signals["expected_establishment_visible"]
        if signals.get("establishment_step") in ESTABLISHMENT_STEPS:
            result["establishment_step"] = signals["establishment_step"]
        if isinstance(signals.get("chooser_controls"), list):
            result["chooser_controls"] = [kind for kind in CHOOSER_CONTROLS if kind in signals["chooser_controls"]]
        if isinstance(signals.get("chooser_actions"), list):
            result["chooser_actions"] = standard_choice_labels(signals["chooser_actions"])
        if signals.get("chooser_action") in CHOOSER_ACTIONS:
            result["chooser_action"] = signals["chooser_action"]
        if signals.get("chooser_surface") in {"control", "label", "parent", "widget", "dialog", "covered", "offscreen"}:
            result["chooser_surface"] = signals["chooser_surface"]
        for key in ("control_shape", "cover_shape"):
            if isinstance(signals.get(key), list):
                result[key] = chooser_element_shape(signals[key])
        if signals.get("dialog_kind") in {"terms", "cookies", "error", "account", "notice", "other", "loading", "empty"}:
            result["dialog_kind"] = signals["dialog_kind"]
            for key in ("dialog_headings", "dialog_buttons", "dialog_prompt"):
                labels = signals.get(key, [])
                if isinstance(labels, list):
                    result[key] = [label for label in labels[:12] if isinstance(label, str) and
                                   0 < len(label.split()) <= 18 and all(w in DIALOG_WORDS or w == "…" for w in label.split())]
        if signals.get("cookie_activation") in {"keyboard", "pointer", "disappeared"}:
            result["cookie_activation"] = signals["cookie_activation"]
        if signals.get("cookie_dialog_closed") is True:
            result["cookie_dialog_closed"] = True
    for key in ("login_post_status", "callback_status", "edof_token_status", "workspace_status", "folder_list_status", "folder_detail_status", "blocked_efp_posts", "blocked_edof_posts", "blocked_other_posts", "invalid_form_fields"):
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


def select_establishment(page, step, signals):
    """Advance one visible control at a time in the existing workspace chooser."""
    if step == "confirmed":
        return step
    verified_chooser = location_category(page.url) == "edof_select_siret"
    confirm = page.get_by_role("button", name=CONFIRM_ESTABLISHMENT).filter(visible=True)
    if step == "selected":
        if verified_chooser and confirm.count() == 1 and confirm.is_enabled():
            signals["chooser_action"] = "confirm"
            confirm.click(no_wait_after=True)
            return "confirmed"
        return step
    # The live EDOF selector is Angular Material. Open its visible trigger
    # normally, then pick the one option with the configured SIRET.
    material = page.locator('mat-select[role="combobox"]:visible')
    if verified_chooser and material.count() == 1:
        if material.get_attribute("aria-expanded") == "true":
            option = page.get_by_role("listbox").get_by_role("option", name=SIRET_TEXT).filter(visible=True)
            if option.count() == 1 and option.is_enabled():
                signals["chooser_action"] = "select_text"
                option.click(timeout=3000)
                return "selected"
        elif SIRET_TEXT.search(material.inner_text()):
            return "selected"
        elif step == "waiting" and material.is_enabled():
            signals["chooser_action"] = "open_click"
            material.click(timeout=3000)
            return "opened"
        return step
    for select in page.locator("select:visible").all():
        matched = []
        for index, option in enumerate(select.locator("option").all()):
            if option.get_attribute("value") == SIRET or SIRET_TEXT.search(option.text_content() or ""):
                matched.append(index)
        if len(matched) == 1:
            signals["chooser_action"] = "select_native"
            select.select_option(index=matched[0])
            return "selected"
    radio = page.get_by_role("radio", name=SIRET_TEXT).or_(page.locator(f'input[type="radio"][value="{SIRET}"]')).filter(visible=True)
    if radio.count() == 1:
        signals["chooser_action"] = "select_radio"
        radio.check()
        return "selected"
    choice = page.get_by_text(SIRET_TEXT).filter(visible=True)
    if choice.count() == 1 and SIRET_TEXT.search(page.locator("body").inner_text()):
        signals["chooser_action"] = "select_text"
        choice.click()
        return "selected"
    if not verified_chooser:
        return step

    # The exact /select-sirets screen may initially show only a collapsed
    # combobox or a search field. Only filter with the configured SIRET.
    fields = page.locator(CHOOSER_CONTROLS["input"])
    labelled = fields.and_(page.get_by_label(SIRET_FIELD).or_(page.get_by_placeholder(SIRET_FIELD)))
    if labelled.count() == 1:
        fields = labelled
    if step in {"waiting", "keyboard", "opened"} and fields.count() == 1 and fields.is_editable():
        signals["chooser_action"] = "filter"
        fields.fill(SIRET)
        return "filtered"
    if step in {"waiting", "keyboard"}:
        dropdown = page.locator('[role="combobox"]:not(select):visible, [aria-haspopup="listbox"]:visible, button.dropdown-toggle:visible').or_(
            page.get_by_role("button", name=re.compile(r"^(?:Choisir|S[ée]lectionner|Choisissez|S[ée]lectionnez)\b.*(?:SIRET|[ée]tablissement|organisme)", re.I)))
        if dropdown.count() == 1 and dropdown.is_enabled() and dropdown.get_attribute("aria-expanded") != "true":
            dropdown.scroll_into_view_if_needed(timeout=3000)
            target = dropdown.evaluate(CHOOSER_HIT_TEST)
            surface = target["surface"]
            signals["chooser_surface"] = surface
            if surface == "widget":
                signals["chooser_action"] = "open_click"
                widget = dropdown.locator("xpath=" + "/".join([".."] * target["depth"]))
                widget.click(timeout=3000)
                return "opened"
            if surface in {"covered", "dialog"} and "cover_shape" not in signals:
                structure = dropdown.evaluate("""e => {
                    function chain(node) {
                        const tags = [];
                        for (; node && tags.length < 6; node=node.parentElement)
                            tags.push(node.localName + ' ' + Array.from(node.classList).join(' '));
                        return tags;
                    }
                    const r=e.getBoundingClientRect();
                    return [chain(e), chain(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))];
                }""")
                signals["control_shape"], signals["cover_shape"] = map(chooser_element_shape, structure)
            if surface not in {"control", "label", "parent"}:
                return step
            if step == "waiting":
                signals["chooser_action"] = "open_keyboard"
                dropdown.press("ArrowDown", timeout=3000)
                return "keyboard"
            signals["chooser_action"] = "open_click"
            dropdown.click(timeout=3000)
            return "opened"
    if step == "filtered" and fields.count() == 1 and fields.input_value() == SIRET:
        search = page.get_by_role("button", name=re.compile(r"^Rechercher$", re.I)).filter(visible=True)
        if search.count() == 1 and search.is_enabled():
            signals["chooser_action"] = "search"
            search.click()
            return "searched"
        if labelled.count() == 1 and confirm.count() == 1 and confirm.is_enabled():
            signals["chooser_action"] = "confirm"
            confirm.click(no_wait_after=True)
            return "confirmed"
    return step


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
            if not spec.get("fresh_login"):
                saved = vault.get("browser")
        except Exception:
            return {"code": "private_storage_unavailable"}

    def route_request(route):
        nonlocal blocked
        request = route.request
        returned = 200 <= signals.get("callback_status", 0) < 400
        allow_identity = spec["mode"] == "read" and (returned or bool(saved))
        frame_url = ""
        if allow_identity and request.method == "POST" and urlsplit(request.url).netloc == EDOF_HOST:
            try:
                frame_url = request.frame.url
            except Exception:
                pass  # Unknown initiator: the identity POST stays blocked.
        if permitted_request(request.url, request.method, edof_identity=allow_identity, frame_url=frame_url):
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
        if parsed.netloc == EDOF_HOST and parsed.path == EDOF_CALLBACK_PATH:
            signals["callback_status"] = response.status
        if parsed.netloc == EDOF_HOST and parsed.path == EDOF_TOKEN_PATH and response.request.method == "POST":
            signals["edof_token_status"] = response.status
        if response.request.method != "GET" or parsed.hostname != EDOF_HOST or not parsed.path.startswith(WORKSPACE_API_PREFIX):
            return
        if response.status == 403:
            signals["workspace_denied"] = True
        if 200 <= response.status < 300:
            signals["workspace_status"] = response.status
        if not parsed.path.startswith(API_PREFIX):
            return
        tail = parsed.path[len(API_PREFIX):]
        if tail == "pad":
            signals["folder_list_status"] = response.status
            if (stage != "search" or "paired_name_search" not in signals
                    or not matches_name_query(parsed.query, spec["last_name"], spec["first_name"], signals["paired_name_search"])):
                return
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
        def browser_page(state):
            context = browser.new_context(locale="fr-FR", accept_downloads=False, service_workers="block", storage_state=state)
            context.route("**/*", route_request)
            page = context.new_page()
            page.set_default_timeout(12000)
            page.on("response", observe)
            return context, page

        try:
            context, page = browser_page(saved)
            def diagnostics():
                try:
                    signals["invalid_form_fields"] = page.locator('input:invalid:visible').count()
                    if urlsplit(page.url).hostname == EDOF_HOST:
                        body = page.locator("body").inner_text(timeout=2000)
                        signals["expected_establishment_visible"] = bool(SIRET_TEXT.search(body))
                        signals["edof_screen"] = workspace_screen(body)
                        if location_category(page.url) == "edof_folder_list":
                            inputs = page.locator("input:visible")
                            signals["name_tab_visible"] = page.get_by_text(NAME_TAB).filter(visible=True).count() == 1
                            signals["name_field_visible"] = page.locator(TRAINEE_SURNAME).or_(page.get_by_placeholder(NAME_FIELD)).or_(page.get_by_label(NAME_FIELD)).and_(inputs).count() == 1
                            signals["folder_field_visible"] = page.get_by_placeholder(re.compile(r"rechercher un dossier de formation", re.I)).and_(inputs).count() == 1
                        if location_category(page.url) == "edof_select_siret":
                            signals["chooser_controls"] = [kind for kind, selector in CHOOSER_CONTROLS.items()
                                                          if page.locator(selector).count()]
                            buttons = page.locator(CHOOSER_CONTROLS["button"] + ", a[href]:visible, [role=combobox]:visible")
                            labels = buttons.evaluate_all("""els => els.map(e => e.getAttribute('aria-label') || e.innerText || e.title || '')""")
                            signals["chooser_actions"] = standard_choice_labels(labels)
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
                if stage in {"organism", "search", "dossier"}:
                    bodies = page.locator("body").all_inner_texts()
                    if not bodies:
                        return "loading"
                    text = bodies[0]
                else:
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
                if stage == "organism" and private_page(page.url):
                    return workspace_screen(text)

            stage = "login_page"
            try:
                reused = open_workspace_or_login(page, context, saved, signals, checkpoint)
            except StopRun as exc:
                if exc.code != "saved_session_unavailable" or not saved:
                    raise
                context.close()
                saved = None
                signals.clear()
                signals.update(blocked_efp_posts=0, blocked_edof_posts=0, blocked_other_posts=0)
                context, page = browser_page(None)
                open_workspace_or_login(page, context, None, signals, checkpoint)
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
            establishment_step = "waiting"
            dossier_menu = page.locator('a[href$="/dossiers/en-cours"]')
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                try:
                    screen = checkpoint()
                except BrowserTimeout:
                    if confirmed_dashboard(page.url, signals):
                        break
                    raise
                if private_page(page.url):
                    if location_category(page.url) == "edof_select_siret":
                        try:
                            covered = handle_chooser_dialog(page, signals)
                        except BrowserTimeout:
                            # The portal can remove its panel between observing
                            # the buttons and acting on the refusal.
                            if page.locator(".cdk-overlay-container .cdk-overlay-backdrop:visible").count():
                                raise StopRun("workspace_dialog_required")
                            covered = False
                        if covered:
                            page.wait_for_timeout(300)
                            continue
                    if screen in {"access_denied", "session_expired", "terms", "error"}:
                        raise StopRun("organism_selection_required")
                    if signals.get("workspace_status") or dossier_menu.count():
                        break
                    chooser = location_category(page.url) == "edof_select_siret" or screen == "select_organisation"
                    if chooser:
                        signals["establishment_step"] = establishment_step
                        try:
                            establishment_step = select_establishment(page, establishment_step, signals)
                        except BrowserTimeout:
                            action = signals.get("chooser_action")
                            if action == "confirm":
                                establishment_step = "confirmed"
                                if confirmed_dashboard(page.url, signals):
                                    break
                            elif action in {"open_click", "select_text"}:
                                # A dispatched click may time out after Material replaces
                                # the trigger with the option list or selected value.
                                widget = page.locator('mat-select[role="combobox"]:visible')
                                if widget.count() != 1:
                                    raise
                                if widget.get_attribute("aria-expanded") == "true":
                                    establishment_step = "opened"
                                elif SIRET_TEXT.search(" ".join(widget.all_inner_texts())):
                                    establishment_step = "selected"
                                else:
                                    raise
                            else:
                                raise
                page.wait_for_timeout(300)
            else:
                raise StopRun("workspace_dialog_required" if signals.get("dialog_kind") in {"empty", "loading"} else "organism_selection_required")

            if not spec.get("folder_id"):
                stage = "search"
                signals["search_step"] = "opening_list"
                open_folder_view(page, LIST_URL, lambda: signals.get("folder_list_status") == 200, BrowserTimeout)
                try:
                    submit_name_search(page, spec["last_name"], spec["first_name"], lists, signals, BrowserTimeout)
                except BrowserTimeout:
                    if signals.get("search_step") != "submit" or not lists:
                        raise
                    signals["search_step"] = "results"
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
            open_folder_view(page, DETAIL_PREFIX + folder_id, lambda: folder_id in details, BrowserTimeout)
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
        except BrowserTimeout as exc:
            # Keep only a fixed cause. Playwright messages can contain private values.
            reason = str(exc).lower()
            signals["timeout_cause"] = next((cause for needle, cause in (
                ("intercepts pointer events", "covered"), ("not visible", "hidden"),
                ("not enabled", "disabled"), ("navigation", "navigation"), ("locator", "locator")
            ) if needle in reason), "other")
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
