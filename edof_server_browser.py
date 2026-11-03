"""Short-lived EDOF browser. Reads are isolated from explicitly queued declarations.

Input is a small search specification on stdin. Output is one allowlisted JSON
result. No screenshots, traces, raw responses or mail bodies are persisted.
Only server-created authentication cookies may be saved in the encrypted vault;
no cookie or token is taken from the user's Chrome.
"""

from contextlib import nullcontext
import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

from edof_readonly_test import (
    ATTENDEE_FIELDS, INFO_FIELDS, SIRET, TEST_SERVICE_ID, TOP_FIELDS,
    normalize_observation,
)
from edof_gmail import Vault, GmailCodes, GmailError
import edof_directory as directory

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
SEARCH_TEXTBOXES = 'input:not([type]):visible,input[type=text]:visible,input[type=search]:visible'


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


def returned_to_organisation(url, signals):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc == EDOF_HOST and private_page(url)
            and location_category(url) in {"edof_select_siret", "edof_dashboard", "edof_folder_list"}
            and signals.get("callback_status") == 200 and signals.get("edof_token_status") == 200)


def returning_shell(url, signals):
    return (location_category(url) == "edof_initialisation" and urlsplit(url).scheme == "https"
            and signals.get("callback_status") == 200 and not signals.get("workspace_denied"))


def restored_workspace(page, signals):
    if not private_page(page.url):
        return False
    if signals.get("workspace_status") == 200:
        return True
    return (location_category(page.url) == "edof_select_siret"
            and page.locator('mat-select[role="combobox"]:visible').count() == 1)


def stalled_before_login(diag):
    return (diag.get("location") in {"edof_initialisation", "edof_folder_list", "edof_login_redirect"}
            and diag.get("edof_screen") in {"empty", "loading", "other", "session_expired"}
            and diag.get("error_banner_visible") is False and diag.get("password_form_visible") is False
            and not any(diag.get(key) for key in ("workspace_status", "workspace_denied", "login_post_status",
                                                  "callback_status", "edof_token_status", "folder_list_status",
                                                  "blocked_edof_posts", "blocked_efp_posts", "blocked_other_posts")))


def can_restart_saved_login(code, page, diagnostics, checkpoint):
    if code == "saved_session_unavailable":
        return True
    if code != "authentication_unconfirmed" or not stalled_before_login(diagnostics()):
        return False
    # The list URL alone does not establish a session. Before signing in
    # normally, check again for a challenge or an account-related dialog.
    checkpoint()
    dialogs = page.locator('dialog[open]:visible,[role=dialog]:visible,'
                           '[role=alertdialog]:visible,[aria-modal=true]:visible').all_inner_texts()
    return all(dialog_kind(text) == "cookies" for text in dialogs)


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


def navigation_in_progress(exc):
    text = str(exc).lower()
    return any(part in text for part in ("execution context was destroyed", "cannot find context", "frame was detached",
        "interrupted by another navigation", "net::err_aborted", "most likely because of a navigation"))


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
        try:
            page.goto(entry, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            if not navigation_in_progress(exc) or urlsplit(page.url).hostname not in {EDOF_HOST, EFP_HOST}:
                raise
        deadline = time.monotonic() + (18 if saved else 30)
        while time.monotonic() < deadline:
            try:
                checkpoint()
                if urlsplit(page.url).hostname == EFP_HOST and page.locator('input[name="username"]:visible').count():
                    return False
                if restored_workspace(page, signals):
                    return True
            except Exception as exc:
                if not navigation_in_progress(exc) or urlsplit(page.url).hostname not in {EDOF_HOST, EFP_HOST}:
                    raise
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


def directory_list_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme, parsed.netloc, parsed.path) != ("https", EDOF_HOST, API_PREFIX + "pad"):
        return False
    return not any(value and key.casefold() in {"attendeename", "attendeefirstname", "folderid",
                   "registrationfolderid", "externalid", "search"} for key, value in parse_qsl(parsed.query))


def is_directory_view(url, target_url=LIST_URL):
    parsed = urlsplit(url)
    target = urlsplit(target_url)
    return ((parsed.scheme, parsed.netloc, parsed.path) == (target.scheme, target.netloc, target.path)
            and parsed.fragment.split("?", 1)[0].rstrip("/") == target.fragment)


def all_dossiers_link(page):
    # Follow the official menu link itself so route changes cannot direct the
    # browser to another host, a filtered search or an individual dossier.
    from urllib.parse import urljoin
    link = page.get_by_role("link", name=re.compile(r"^Tous les dossiers$", re.I)).filter(visible=True)
    if link.count() != 1 or not link.is_visible():
        return None
    target = urljoin(page.url, link.get_attribute("href") or "")
    parsed = urlsplit(target)
    home = urlsplit(LIST_URL)
    if ((parsed.scheme, parsed.netloc, parsed.path) != (home.scheme, home.netloc, home.path)
            or parsed.query or "?" in parsed.fragment or not re.fullmatch(r"/dossiers(?:/[a-z-]+)?", parsed.fragment)
            or parsed.fragment == home.fragment):
        return None
    return target


def exported_directory(page, source, checkpoint, progress, timeout_error, target_url=LIST_URL):
    from pathlib import Path

    first = source.json()
    progress["expected"] = first.get("numberOfItems", 0)
    label = re.compile(r"^(?:(?:download|file_download)\s+)?exporter\b.*$", re.I)
    control = page.get_by_role("button", name=label).or_(page.get_by_role("link", name=label))
    if not control.count():
        control = page.get_by_text(re.compile(r"^Exporter$", re.I), exact=True)
    if control.count() != 1 or not control.is_visible() or not control.is_enabled():
        progress["export"] = "absent"
        return None
    downloads = []
    listener = lambda item: downloads.append(item)
    page.on("download", listener)
    try:
        checkpoint()
        if not is_directory_view(page.url, target_url):
            raise StopRun("directory_unavailable")
        control.click(timeout=4000)
        confirmed = False
        deadline = time.monotonic() + 15
        while not downloads and time.monotonic() < deadline:
            checkpoint()
            dialog = page.get_by_role("dialog").filter(has_text=re.compile(r"export|télécharg", re.I))
            if not confirmed and dialog.count() == 1:
                confirm = dialog.get_by_role("button", name=re.compile(r"^(exporter|télécharger)(?: les dossiers)?$", re.I))
                if confirm.count() == 1 and confirm.is_visible() and confirm.is_enabled():
                    confirm.click(timeout=3500)
                    confirmed = True
            page.wait_for_timeout(250)
        if len(downloads) != 1:
            progress["export"] = "no_download"
            return None
        item = downloads[0]
        parsed = urlsplit(item.url.removeprefix("blob:"))
        if parsed.scheme != "https" or parsed.netloc != EDOF_HOST:
            raise StopRun("directory_unavailable")
        path = item.path()
        if path is None or not Path(path).is_file() or Path(path).stat().st_size > 24_000_000:
            progress["export"] = "unreadable"
            return None
        try:
            snapshot = directory.csv_snapshot(Path(path).read_bytes(), first, progress)
            progress["export"] = "complete"
            return snapshot
        except (ValueError, UnicodeError, KeyError, TypeError):
            progress["export"] = "format_or_scope"
            return None
        finally:
            item.delete()
    except timeout_error:
        progress["export"] = "button_timeout"
        return None
    finally:
        page.remove_listener("download", listener)


def directory_pages(page, response, checkpoint, progress=None):
    """Only paginate the exact GET that the authenticated EDOF list just used."""
    progress = progress if progress is not None else {}

    def read(reply):
        progress["http"] = reply.status
        if reply.status != 200 or not directory_list_url(reply.url):
            raise directory.IncompleteDirectory()
        body = reply.body()
        if len(body) > 8_000_000:
            raise directory.IncompleteDirectory()
        return json.loads(body)

    result = read(response)
    parsed = urlsplit(response.url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    page_keys = {"page", "pagenumber", "pageindex", "numpage", "indexpage"}
    offset_keys = {"offset", "first", "start", "startindex", "firstresult", "skip"}
    size_keys = {"size", "pagesize", "limit", "maxresults", "resultsperpage", "perpage", "itemsperpage", "numberofitemsperpage"}
    cursors = [(key, value) for key, value in pairs if key.lower() in page_keys | offset_keys]
    sizes = [key for key, value in pairs if key.lower() in size_keys and value.isdigit()]
    if len(cursors) == 1 and cursors[0][1] in {"0", "1"}:
        progress["method"] = "pages"
        key, value = cursors[0]
        if key.lower() in offset_keys and value != "0":
            raise directory.IncompleteDirectory()
        position = int(value)
        # Reuse only the same-origin header names required for this read.
        headers = {k: v for k, v in response.request.all_headers().items()
                   if k.lower() in {"accept", "authorization", "x-xsrf-token", "x-csrf-token", "x-requested-with"}}
        def get_batch(index, page_size=None):
            values = {key: str(index)}
            if page_size:
                values[sizes[0]] = str(page_size)
            query = [(k, values.get(k, v)) for k, v in pairs]
            url = parsed._replace(query=urlencode(query), fragment="").geturl()
            reply = page.context.request.get(url, headers=headers, max_redirects=0, timeout=12000)
            try:
                if reply.status == 429:
                    progress["http"] = 429
                    retry = reply.headers.get("retry-after", "60")
                    if not retry.isdigit() or int(retry) > 90:
                        raise directory.IncompleteDirectory()
                    page.wait_for_timeout(max(1, int(retry)) * 1000)
                    checkpoint()
                    reply.dispose()
                    reply = page.context.request.get(url, headers=headers, max_redirects=0, timeout=12000)
                if page_size and reply.status in {400, 422}:
                    return None
                return read(reply)
            finally:
                reply.dispose()

        batch_size = None
        if (len(sizes) == 1 and len(result["items"]) < 100
                and result["numberOfItems"] > len(result["items"])):
            larger = get_batch(position, 100)
            if larger is not None:
                original_ids = [item.get("id") for item in result["items"]]
                if (larger.get("numberOfItems") != result["numberOfItems"]
                        or [item.get("id") for item in larger["items"][:len(original_ids)]] != original_ids):
                    raise directory.IncompleteDirectory()
                result, batch_size = larger, 100
        while True:
            yield result
            page.wait_for_timeout(1400)
            position += len(result["items"]) if key.lower() in offset_keys else 1
            result = get_batch(position, batch_size)
            if result is None:
                raise directory.IncompleteDirectory()
    else:
        progress["method"] = "ui"
        yield result
        while True:
            page.wait_for_timeout(1400)
            checkpoint()
            next_page = page.locator(
                'button[aria-label*="suivant" i]:visible, a[aria-label*="suivant" i]:visible, '
                'button[title*="suivant" i]:visible, a[title*="suivant" i]:visible, '
                'button.mat-mdc-paginator-navigation-next:visible, button.mat-paginator-navigation-next:visible, '
                '.fr-pagination__link--next:visible, button[aria-label="Next page" i]:visible').first
            if not next_page.count() or not next_page.is_enabled():
                raise directory.IncompleteDirectory()
            with page.expect_response(lambda r: r.request.method == "GET" and directory_list_url(r.url), timeout=12000) as pending:
                next_page.click(timeout=4500)
            yield read(pending.value)


def matches_name_query(query, surname, first_name, paired):
    filters = parse_qs(query, keep_blank_values=True)
    names = [value.strip().casefold() for value in filters.get("attendeeName", [])]
    given = [value.strip().casefold() for value in filters.get("attendeeFirstName", [])]
    if not surname or not first_name or names != [surname.strip().casefold()]:
        return False
    return given == [first_name.strip().casefold()] or (not paired and given in ([], [""]))


def activate_name_tab(page, tab, signals):
    tab.wait_for(state="visible", timeout=25000)
    backdrop = page.locator(".cdk-overlay-container .cdk-overlay-backdrop:visible")
    if backdrop.count():
        layer = page.locator(".cdk-overlay-container:visible")
        if signals.get("cookie_dialog_closed") and decline_cookies_control(layer).count() == 1:
            signals.pop("cookies_dismissed", None)
        if handle_chooser_dialog(page, signals):
            backdrop.wait_for(state="hidden", timeout=8000)
    if page.locator('dialog[open]:visible,[role=dialog]:visible,[aria-modal=true]:visible').count():
        raise StopRun("workspace_dialog_required")
    signals["search_step"] = "activate_tab"
    # Activate the labelled control itself. A Material tab may put keyboard
    # focus on its parent or on the input associated with a visible label.
    for _ in range(55):
        key = tab.evaluate_all("""els => {
            if (els.length !== 1) return '';
            const text = els[0], active = text.ownerDocument.activeElement;
            const control = text.closest('button,a,label,[role=tab],[role=button],[role=radio],[tabindex]') || text;
            if (!active || active === document.body || active.matches(':disabled,[aria-disabled=true]')) return '';
            if (!control.contains(active) && !(control.matches('label') && control.control === active)) return '';
            return active.matches('input[type=radio],input[type=checkbox],[role=radio]') ? 'Space' : 'Enter';
        }""")
        if key in {"Enter", "Space"}:
            signals["name_activation"] = "keyboard"
            page.keyboard.press(key)
            return
        page.keyboard.press("Tab")
    signals["name_activation"] = "pointer"
    tab.click(no_wait_after=True, timeout=12000)


def name_search_inputs(page, signals):
    boxes = page.locator(SEARCH_TEXTBOXES)
    kinds = boxes.evaluate_all(r"""nodes => nodes.map(e => {
        const labels = e.labels ? Array.from(e.labels, l => l.textContent) : [];
        const labelled = (e.getAttribute('aria-labelledby') || '').split(/\s+/)
            .map(id => e.ownerDocument.getElementById(id)?.textContent);
        for (const value of [e.name, e.getAttribute('formcontrolname'), e.id,
                             e.getAttribute('aria-label'), e.placeholder, ...labels, ...labelled]) {
            const words = (value || '').replace(/([a-z])([A-Z])/g, '$1 $2').normalize('NFD')
                .replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z]+/g, ' ').trim();
            const last = /\b(nom|surname|lastname|(?:last|family|trainee|attendee) name)\b/.test(words);
            const first = /\b(prenom|firstname|(?:first|given) name)\b/.test(words);
            if (last !== first) return last ? 'surname' : 'given';
        }
        return 'other';
    })""")
    signals["name_form_fields"] = kinds[:10]
    if kinds.count("surname") != 1 or kinds.count("given") > 1:
        return None, None
    if "given" not in kinds and len(kinds) != 1:
        return None, None
    return boxes.nth(kinds.index("surname")), boxes.nth(kinds.index("given")) if "given" in kinds else None


def submit_name_search(page, surname, first_name, lists, signals, timeout_error):
    search, given = name_search_inputs(page, signals)
    if search is None:
        signals["search_step"] = "name_mode"
        tab = page.get_by_text(NAME_TAB).filter(visible=True)
        try:
            activate_name_tab(page, tab, signals)
        except timeout_error:
            search, given = name_search_inputs(page, signals)
            if search is None:
                raise
        signals["search_step"] = "waiting_inputs"
        deadline = time.monotonic() + 15
        while search is None and time.monotonic() < deadline:
            search, given = name_search_inputs(page, signals)
            if search is None:
                page.wait_for_timeout(250)
        if search is None:
            raise StopRun("search_unconfirmed")
    signals["search_step"] = "input"
    paired = given is not None
    signals["paired_name_search"] = paired
    lists.clear()
    search.fill(surname, timeout=8000)
    surname_field = search
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
        both_fields = paired and count == 2 and group.locator("input:visible").and_(surname_field).count() == 1
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
        if signals.get("search_step") in {"opening_list", "name_mode", "activate_tab", "waiting_inputs", "input", "submit", "results"}:
            result["search_step"] = signals["search_step"]
        if signals.get("name_activation") in {"keyboard", "pointer"}:
            result["name_activation"] = signals["name_activation"]
        if isinstance(signals.get("name_form_fields"), list):
            result["name_form_fields"] = [k for k in signals["name_form_fields"][:10] if k in {"surname", "given", "other"}]
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


def run_browser(spec, *, live=None):
    if os.environ.get("RENDER_SERVICE_ID") != TEST_SERVICE_ID:
        return {"code": "wrong_environment"}
    from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout

    stage = "browser"
    blocked = 0
    lists = []
    directory_responses = []
    target_directory = LIST_URL
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
    business_modes = {"declare", "reconcile"}
    authenticated = spec["mode"] in {"read", "directory", "inspect_forms"} | business_modes
    gate = None
    if authenticated and os.environ.get("EDOF_CONNECTOR_KEY"):
        try:
            vault = Vault(os.environ["EDOF_CONNECTOR_DIRECTORY"], os.environ["EDOF_CONNECTOR_KEY"])
            if spec["mode"] in business_modes:
                from edof_declaration_form import SingleWrite
                gate = SingleWrite(spec, EDOF_HOST, API_PREFIX, os.environ["EDOF_CONNECTOR_DIRECTORY"])
            if not spec.get("fresh_login"):
                saved = vault.get("browser")
        except Exception:
            return {"code": "private_storage_unavailable"}

    def route_request(route):
        nonlocal blocked
        request = route.request
        returned = 200 <= signals.get("callback_status", 0) < 400
        allow_identity = authenticated and (returned or bool(saved) or bool(live and (live.get("verified") or live.get("return_pending"))))
        frame_url = ""
        if allow_identity and request.method == "POST" and urlsplit(request.url).netloc == EDOF_HOST:
            try:
                frame_url = request.frame.url
            except Exception:
                pass  # Unknown initiator: the identity POST stays blocked.
        if (permitted_request(request.url, request.method, edof_identity=allow_identity, frame_url=frame_url)
                or (gate and gate.allows(request))):
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
        if gate:
            gate.observe(response)
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
            if spec["mode"] == "directory":
                if response.status == 200 and directory_list_url(response.url) and is_directory_view(response.frame.url, target_directory):
                    directory_responses[:] = [response]
                return
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

    if live is not None and spec["mode"] != "directory":
        raise ValueError("The working-day browser only reads the directory.")
    with (nullcontext(live["pw"]) if live is not None else sync_playwright()) as pw:
        browser = live["browser"] if live is not None else pw.chromium.launch(headless=True)
        def browser_page(state):
            if live is not None and "page" in live:
                context, page = live["page"]
            else:
                context = browser.new_context(locale="fr-FR", accept_downloads=spec["mode"] == "directory", service_workers="block", storage_state=state)
                if live is not None:
                    # With no active read policy, the idle page cannot send requests.
                    context.route("**/*", lambda route: route.abort())
                page = context.new_page()
                if live is not None:
                    live["page"] = (context, page)
            context.route("**/*", route_request)
            page.set_default_timeout(12000)
            page.on("response", observe)
            return context, page

        try:
            warm = live is not None and "page" in live
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
                            name_field, _ = name_search_inputs(page, signals)
                            signals["name_field_visible"] = name_field is not None
                            signals["folder_field_visible"] = page.get_by_placeholder(re.compile(r"rechercher un dossier de formation", re.I)).and_(inputs).count() == 1
                        if location_category(page.url) == "edof_select_siret":
                            signals["chooser_controls"] = [kind for kind, selector in CHOOSER_CONTROLS.items()
                                                          if page.locator(selector).count()]
                            buttons = page.locator(CHOOSER_CONTROLS["button"] + ", a[href]:visible, [role=combobox]:visible")
                            labels = buttons.evaluate_all("""els => els.map(e => e.getAttribute('aria-label') || e.innerText || e.title || '')""")
                            signals["chooser_actions"] = standard_choice_labels(labels)
                    return {**({"directory": signals["directory"]} if "directory" in signals else {}), **diagnostic_summary(page.url,
                        page.locator('input[type="password"]:visible').count() > 0,
                        page.locator('#input-error:visible, .alert-error:visible, .pf-m-danger:visible, .fr-alert--error:visible').count() > 0,
                        signals)}
                except Exception:
                    return diagnostic_summary(page.url, False, False, signals)

            def check_document(allow_otp=True):
                nonlocal otp_attempted, gmail_code_used
                # Only derive categorical signals; never return the page body,
                # which could contain identity information or an auth code.
                # During the redirects the old document can disappear before a
                # body exists on the new one. Keep polling inside the deadline.
                bodies = page.locator("body").all_inner_texts()
                if not bodies:
                    return "loading"
                text = bodies[0]
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

            def checkpoint(allow_otp=True):
                try:
                    return check_document(allow_otp)
                except Exception as exc:
                    if navigation_in_progress(exc) and urlsplit(page.url).hostname in {EDOF_HOST, EFP_HOST}:
                        return "loading"
                    raise

            stage = "login_page"
            if warm:
                # Refresh this tab with its original session storage and current cookies.
                page.reload(wait_until="domcontentloaded", timeout=45000)
            try:
                reused = open_workspace_or_login(page, context, saved or (warm and live.get("return_pending")), signals, checkpoint)
            except StopRun as exc:
                if not saved or not can_restart_saved_login(exc.code, page, diagnostics, checkpoint):
                    raise
                context.close()
                if live is not None:
                    live.pop("page", None)
                if vault:
                    # The stored cookies just failed the explicit safe restore
                    # check; leave a subsequent run free to start at normal EFP.
                    vault.delete("browser")
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
                from edof_day_session import allow_login
                if not allow_login(vault, automatic=bool(spec.get("day_session")),
                                   manual_until=spec.get("manual_until", 0), recover_return=bool(spec.get("recover_return")),
                                   owner=spec.get("owner"), verified_tab=bool(warm and live.get("verified"))):
                    raise StopRun("day_login_used")
                requested_at = time.time()
                page.locator("#kc-login").click()
                username = password = None
                deadline = time.monotonic() + 160
                shell_since = None
                recovered_shell = False
                while time.monotonic() < deadline:
                    try:
                        checkpoint()
                    except BrowserTimeout:
                        # The callback can arrive while the SPA has no body. An
                        # intermediate shell is not evidence of private access.
                        if not (returned_to_organisation(page.url, signals) or
                                gmail_code_used and returning_shell(page.url, signals)):
                            raise
                    if returning_shell(page.url, signals):
                        shell_since = shell_since or time.monotonic()
                        if not recovered_shell and time.monotonic()-shell_since > 25 and inactive_saved_view(page, signals):
                            recovered_shell = True
                            # Load the official dossier list in this same signed-in
                            # tab. The subsequent organisation and private GET
                            # checks remain mandatory; no password is resubmitted.
                            page.goto(LIST_URL, wait_until="commit", timeout=30000)
                    elif private_page(page.url):
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
            chooser_limit = deadline + 55
            progress_steps = set()
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
                            if signals.get("cookies_dismissed") and "cookies_dismissed" not in progress_steps:
                                progress_steps.add("cookies_dismissed")
                                deadline = min(chooser_limit, max(deadline, time.monotonic() + 25))
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
                        if establishment_step in {"opened", "selected", "confirmed"} and establishment_step not in progress_steps:
                            # Selecting the correct SIRET at the end of the initial
                            # window still needs time for the official Continue action.
                            progress_steps.add(establishment_step)
                            deadline = min(chooser_limit, max(deadline, time.monotonic() + 25))
                page.wait_for_timeout(300)
            else:
                raise StopRun("workspace_dialog_required" if signals.get("dialog_kind") in {"empty", "loading"} else "organism_selection_required")

            if spec.get("fresh_login") and vault and signals.get("workspace_status") == 200:
                # The normal sign-in worked. Retire the unusable cached browser
                # even if the separate name search later fails.
                vault.delete("browser")
            if spec["mode"] == "inspect_forms":
                from edof_declaration_form import ENTRY, EXIT, button
                inspected = {}
                for kind, folder in spec["probes"].items():
                    spec["selected_id"] = folder
                    stage = "dossier"
                    open_folder_view(page, DETAIL_PREFIX+folder, lambda: folder in details, BrowserTimeout)
                    until = time.monotonic()+15
                    while folder not in details and time.monotonic() < until:
                        checkpoint()
                        page.wait_for_timeout(150)
                    control = button(page, ENTRY if kind == "entry_training" else EXIT)
                    try:
                        control.wait_for(state="visible", timeout=5000)
                        available = control.count() == 1 and control.is_visible()
                    except BrowserTimeout:
                        available = False
                    inspected[kind] = {"read": folder in details, "control": available}
                if inspected and all(i["read"] for i in inspected.values()) and vault:
                    vault.put("browser", session_cookies(context.storage_state()), ttl=86400)
                return {"code": "declaration_inspected", "stage": stage, "diagnostics": {"forms": inspected}}
            if spec["mode"] == "directory":
                stage = "directory"
                if not is_directory_view(page.url):
                    directory_responses.clear()
                open_folder_view(page, LIST_URL, lambda: bool(directory_responses), BrowserTimeout)
                full_list = all_dossiers_link(page)
                if not full_list and spec.get("manual_until"):
                    # The official “Tous les dossiers” page also works when the responsive menu is collapsed.
                    full_list = LIST_URL.rsplit("/", 1)[0] + "/tous"
                if full_list:
                    target_directory = full_list
                    directory_responses.clear()
                    open_folder_view(page, target_directory, lambda: bool(directory_responses), BrowserTimeout)
                deadline = time.monotonic() + 18
                while not directory_responses and time.monotonic() < deadline:
                    checkpoint()
                    page.wait_for_timeout(200)
                if not directory_responses or not vault:
                    raise StopRun("directory_unavailable")
                checkpoint()
                try:
                    signals["directory"] = {"seen": 0, "pages": 0}
                    source = directory_responses[-1]
                    initial = source.json()
                    if isinstance(initial, dict) and type(initial.get("numberOfItems")) is int and isinstance(initial.get("items"), list):
                        # A verified private list already proves an authenticated
                        # session, independent of the later export/pagination.
                        vault.put("browser", session_cookies(context.storage_state()), ttl=86400)
                    snapshot = exported_directory(page, source, checkpoint, signals["directory"], BrowserTimeout, target_directory)
                    if snapshot is None:
                        snapshot = directory.from_pages(directory_pages(page, source, checkpoint, signals["directory"]), signals["directory"])
                except (ValueError, KeyError, TypeError):
                    raise StopRun("directory_incomplete") from None
                snapshot["scope"] = "all" if target_directory != LIST_URL else "open"
                vault.put(directory.record_key(spec["owner"]), snapshot, ttl=directory.TTL)
                vault.put("browser", session_cookies(context.storage_state()), ttl=86400)
                return {"code": "directory_ready", "stage": stage, "candidate_count": len(snapshot["rows"]),
                        "diagnostics": {"directory": signals["directory"]},
                        "fresh_session": not reused, "gmail_code_used": gmail_code_used, "session_saved": True}
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
            if spec["mode"] in business_modes:
                from edof_declaration_form import transmit

                def reload_fields():
                    # A fresh top-level load causes a new authenticated GET for this exact folder.
                    details.pop(folder_id, None)
                    page.reload(wait_until="domcontentloaded", timeout=20000)
                    until = time.monotonic()+15
                    while folder_id not in details and time.monotonic() < until:
                        checkpoint()
                        page.wait_for_timeout(150)
                    return details.get(folder_id)
                stage = "declaration"
                if not gate:
                    raise StopRun("private_storage_unavailable")
                return transmit(page, spec, fields, gate, reload_fields)
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
        except Exception as exc:
            # Expose a fixed category only. Exception text may contain auth material.
            name = type(exc).__name__
            fault = name if name in {"Error", "AttributeError", "TypeError", "KeyError", "ValueError", "OSError"} else "other"
            reason = str(exc).lower()
            for needle, tag in (("execution context", "document_changed"), ("net::err_", "network"), ("closed", "closed"),
                                ("strict mode", "ambiguous_control"), ("detached", "detached")):
                if needle in reason:
                    fault = tag
                    break
            return {"code": "browser_error", "stage": stage, "fresh_session": not reused, "gmail_code_used": gmail_code_used,
                    "diagnostics": {**diagnostics(), "fault": fault}}
        finally:
            if live is None:
                browser.close()
            elif live.get("page"):
                context, page = live["page"]
                page.remove_listener("response", observe)
                context.unroute("**/*", route_request)


if __name__ == "__main__":
    try:
        specification = json.loads(sys.stdin.read(4096))
        result = run_browser(specification)
    except ImportError:
        result = {"code": "browser_missing"}
    except Exception:
        result = {"code": "browser_error"}
    print(json.dumps(result, ensure_ascii=False))
