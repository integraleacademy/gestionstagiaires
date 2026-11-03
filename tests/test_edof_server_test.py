from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock

from flask import Flask, jsonify, session
import pytest

import edof_server_browser as browser
import edof_server_test as server


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_all_edof_business_writes_blocked(method):
    assert not browser.permitted_request(f"https://{browser.EDOF_HOST}{browser.API_PREFIX}123456789012/inTraining", method)
    assert not browser.permitted_request(f"https://{browser.EDOF_HOST}/unknown-mutation", method)


def test_only_official_efp_login_can_post():
    path = "/auth/realms/efp/login-actions/authenticate?session_code=synthetic"
    assert browser.permitted_request(f"https://{browser.EFP_HOST}" + path, "POST")
    assert not browser.permitted_request(f"http://{browser.EFP_HOST}" + path, "POST")
    assert not browser.permitted_request("https://example.invalid" + path, "POST")
    assert not browser.permitted_request(f"https://{browser.EFP_HOST}/account/password", "POST")
    assert browser.permitted_request(f"https://{browser.EDOF_HOST}{browser.API_PREFIX}123456789012", "GET")


def test_observed_edof_token_post_needs_a_verified_return_and_same_origin_frame():
    origin = "https://" + browser.EDOF_HOST
    target = origin + "/idp/edof/api/v2/token"
    frame = origin + "/espace-prive/html/#/redirect-to-mire-connexion"
    assert browser.permitted_request(target, "POST", edof_identity=True, frame_url=frame)
    assert browser.permitted_request(target, "POST", edof_identity=True, frame_url=origin + browser.EDOF_CALLBACK_PATH)
    assert not browser.permitted_request(target, "POST", frame_url=frame)
    for other_frame in ("", "https://example.invalid/espace-prive/", origin + "/espace-public/"):
        assert not browser.permitted_request(target, "POST", edof_identity=True, frame_url=other_frame)
    for destination in (target + "/extra", target.replace("https:", "http:"), target.replace("fr/", "fr:8443/"),
                        target.replace("fr/", "fr.example.invalid/"), origin + browser.API_PREFIX + "123456/inTraining"):
        assert not browser.permitted_request(destination, "POST", edof_identity=True, frame_url=frame)
    for method in ("PUT", "PATCH", "DELETE"):
        assert not browser.permitted_request(target, method, edof_identity=True, frame_url=frame)


def test_projection_removes_pii_and_preserves_unknowns():
    raw = {"id": "123456789012", "title": "0", "attendee": {"firstName": "Camille", "lastName": "EXEMPLE", "phoneNumber": "synthetic-private", "birthDate": "synthetic-private"},
        "trainingActionInfo": {"title": "Formation exemple", "totalIncl": 1600},
        "authorization": "synthetic-private", "history": ["synthetic-private"]}
    result = browser.project_folder(raw)
    assert "synthetic-private" not in json.dumps(result)
    assert result["title"] == "Formation exemple"
    assert result["billing_state"] is None and result["payment_state"] is None


@pytest.mark.parametrize("text,code", [("Je ne suis pas un robot", "human_verification"), ("Saisissez le code de vérification", "verification_code"), ("Identifiant ou mot de passe incorrect", "credentials_rejected"), ("Connexion à EDOF", None), ("403 Forbidden", None)])
def test_classification_does_not_infer_bot_block_from_http(text, code):
    assert browser.classify_text(text) == code


@pytest.mark.parametrize("payload", [{"mode": "read"}, {"mode": "read", "folder_id": "../../other"}, {"mode": "read", "first_name": "Camille"}, {"mode": "read", "folder_id": "123456789012", "password": "synthetic"}, {"mode": "write", "folder_id": "123456789012"}])
def test_search_input_rejects_injection_and_credential_submission(payload):
    with pytest.raises(ValueError):
        server.validate_spec(payload)


def test_search_spec_and_identity():
    assert server.validate_spec({"mode": "read", "first_name": " Camille ", "last_name": "EXEMPLE"})["first_name"] == "Camille"
    assert browser.identity(" Jean-François ") == browser.identity("JEAN FRANCOIS")


def test_diagnostics_only_expose_categories_not_auth_parameters():
    url = f"https://{browser.EFP_HOST}/auth/realms/efp/login-actions/authenticate?session_code=synthetic-secret&username=synthetic@example.invalid"
    signals = {"login_post_status": 200, "callback_status": None, "blocked_efp_posts": 0, "raw_error": "synthetic-secret", "cookie": "synthetic-secret"}
    result = browser.diagnostic_summary(url, True, False, signals)
    assert result["location"] == "efp_login"
    assert result["login_post_status"] == 200
    assert "synthetic" not in json.dumps(result)
    assert "cookie" not in result and "raw_error" not in result
    assert browser.location_category(f"https://{browser.EDOF_HOST}/idp/edof/api/v2/callback?code=synthetic-secret") == "edof_callback"
    assert browser.location_category(f"https://{browser.EFP_HOST}/auth/realms/efp/login-actions/required-action?execution=synthetic-secret") == "efp_required_action"


def test_private_page_waits_for_callback_and_folder_diagnostics_hide_identifiers():
    base = f"https://{browser.EDOF_HOST}/espace-prive/html/#"
    assert not browser.private_page(base + "/redirect-to-mire-connexion?state=synthetic-secret")
    assert browser.private_page(base + "/dossiers/en-cours")
    result = browser.diagnostic_summary(base + "/dossiers/detail/123456789012?state=synthetic", False, False,
        {"workspace_status": 200, "folder_detail_status": 403, "folder_list_status": "untrusted"})
    assert result == {"location": "edof_folder_detail", "error_banner_visible": False,
                      "private_route": "/dossiers/detail/*", "password_form_visible": False,
                      "workspace_status": 200, "folder_detail_status": 403}


def test_workspace_choice_recognizes_existing_establishment_and_keeps_unknowns_private():
    base = f"https://{browser.EDOF_HOST}/espace-prive/html/#"
    assert browser.location_category(base + "/choix-etablissement") == "edof_select_siret"
    assert browser.workspace_screen("Choisissez le SIRET de votre établissement") == "select_organisation"
    assert browser.workspace_screen("Demander un accès. Choisissez votre établissement") == "access_denied"
    assert browser.workspace_screen("J’accepte les conditions. Choisissez un établissement") == "terms"
    formatted = f"{browser.SIRET[:3]} {browser.SIRET[3:6]} {browser.SIRET[6:9]} {browser.SIRET[9:]}"
    assert browser.SIRET_TEXT.search("SIRET " + formatted)
    assert not browser.SIRET_TEXT.search(browser.SIRET + "1")
    result = browser.diagnostic_summary(base + "/choix-etablissement/private-name?state=secret", False, False,
                                       {"expected_establishment_visible": True})
    assert result["private_route"] == "/choix-etablissement/*" and result["expected_establishment_visible"]
    assert "secret" not in json.dumps(result) and "private-name" not in json.dumps(result)


def test_establishment_confirmation_requires_one_enabled_button_on_the_chooser():
    page = Mock()
    signals = {}
    page.url = f"https://{browser.EDOF_HOST}/espace-prive/html/#/select-sirets"
    confirm = page.get_by_role.return_value.filter.return_value
    confirm.count.return_value = 1
    confirm.is_enabled.return_value = False
    assert browser.select_establishment(page, "selected", signals) == "selected"
    confirm.is_enabled.return_value = True
    confirm.count.return_value = 2
    assert browser.select_establishment(page, "selected", signals) == "selected"
    confirm.count.return_value = 1
    page.url = browser.LIST_URL
    assert browser.select_establishment(page, "selected", signals) == "selected"
    confirm.click.assert_not_called()
    page.url = f"https://{browser.EDOF_HOST}/espace-prive/html/#/select-sirets"
    assert browser.select_establishment(page, "selected", signals) == "confirmed"
    assert browser.select_establishment(page, "confirmed", signals) == "confirmed"
    assert signals == {"chooser_action": "confirm"}
    confirm.click.assert_called_once()
    assert not browser.CONFIRM_ESTABLISHMENT.fullmatch("Valider le service fait")
    assert not browser.CONFIRM_ESTABLISHMENT.fullmatch("Accepter les conditions")
    assert browser.standard_choice_labels(["Valider mon choix", "Valider mon choix", "Exemple 123456",
                                          "Personne Privée", "À mon espace"]) == ["valider mon choix", "a mon espace"]


def test_completed_siret_confirmation_requires_the_official_dashboard_and_workspace_response():
    url = f"https://{browser.EDOF_HOST}/espace-prive/html/#/tableau-de-bord"
    signals = {"chooser_action": "confirm", "workspace_status": 200}
    assert browser.confirmed_dashboard(url, signals)
    assert not browser.confirmed_dashboard(url.replace("tableau-de-bord", "select-sirets"), signals)
    assert not browser.confirmed_dashboard(url.replace(browser.EDOF_HOST, "example.invalid"), signals)
    assert not browser.confirmed_dashboard(url, {"chooser_action": "confirm"})
    assert not browser.confirmed_dashboard(url, {"chooser_action": "confirm", "workspace_status": 403})


def test_new_read_uses_normal_signin_only_after_an_unconfirmed_workspace():
    diag = {"location": "edof_folder_list", "edof_screen": "other", "error_banner_visible": False,
            "password_form_visible": False, "blocked_edof_posts": 0}
    last = {"finished": True, "mode": "read", "stage": "login_page", "code": "authentication_unconfirmed",
            "gmail_code_used": False, "diagnostics": diag}
    assert server.last_read_stalled_at_login([last])
    lookup_timeout = {"stage": "search", "code": "timeout", "fresh_session": True, "gmail_code_used": True}
    assert server.last_read_stalled_at_login([lookup_timeout, last])
    assert not server.last_read_stalled_at_login([{"code": "read_success", "session_saved": True}, last])
    assert not server.last_read_stalled_at_login([])
    for changed in ({"code": "human_verification"}, {"stage": "authentication"}, {"gmail_code_used": True},
                    {"diagnostics": dict(diag, workspace_denied=True)}, {"diagnostics": dict(diag, edof_screen="terms")},
                    {"diagnostics": dict(diag, login_post_status=302)}, {"diagnostics": dict(diag, error_banner_visible=True)}):
        assert not server.last_read_stalled_at_login([{**last, **changed}])
    with pytest.raises(ValueError):
        server.validate_spec({"mode": "read", "folder_id": "123456789", "fresh_login": True})


def test_same_read_can_restart_a_stalled_restore_but_preserves_verification_walls():
    page, checkpoint = Mock(), Mock()
    dialogs = page.locator.return_value
    dialogs.all_inner_texts.return_value = []
    diag = {"location": "edof_folder_list", "edof_screen": "other", "error_banner_visible": False,
            "password_form_visible": False, "blocked_edof_posts": 0, "blocked_efp_posts": 0}
    def restart(**changed):
        return browser.can_restart_saved_login("authentication_unconfirmed", page, lambda: {**diag, **changed}, checkpoint)
    assert restart()
    for seen in ("login_post_status", "workspace_denied", "edof_token_status", "folder_list_status", "blocked_edof_posts"):
        assert not restart(**{seen: 1})
    dialogs.all_inner_texts.return_value = ["Accepter les conditions générales d’utilisation"]
    assert not restart()
    dialogs.all_inner_texts.return_value = ["Préférences de cookies"]
    assert restart()
    checkpoint.side_effect = browser.StopRun("human_verification")
    with pytest.raises(browser.StopRun, match="human_verification"):
        restart()


def test_restore_requires_the_private_workspace_and_goes_there_first():
    page, context, checkpoint = Mock(), Mock(), Mock()
    page.url = browser.LIST_URL
    assert not browser.restored_workspace(page, {})
    assert browser.open_workspace_or_login(page, context, True, {"workspace_status": 200}, checkpoint)
    page.goto.assert_called_once_with(browser.LIST_URL, wait_until="domcontentloaded", timeout=45000)
    context.clear_cookies.assert_not_called()
    page.url = browser.LOGIN_URL
    assert not browser.restored_workspace(page, {"workspace_status": 200})
    page.url = f"https://{browser.EFP_HOST}/auth/"
    page.locator.return_value.count.return_value = 1
    page.goto.reset_mock()
    assert not browser.open_workspace_or_login(page, context, False, {}, checkpoint)
    page.goto.assert_called_once_with(browser.LOGIN_URL, wait_until="domcontentloaded", timeout=45000)


def test_empty_restored_shell_can_start_sso_without_clearing_efp_or_replaying_credentials(monkeypatch):
    page, context, checkpoint = Mock(), Mock(), Mock()
    body, username, controls = Mock(), Mock(), Mock()
    body.all_inner_texts.return_value = [""]
    username.count.return_value, controls.count.return_value = 1, 0
    page.locator.side_effect = lambda selector: {"body": body, 'input[name="username"]:visible': username}.get(selector, controls)
    def navigate(url, **kwargs):
        page.url = (f"https://{browser.EDOF_HOST}/espace-prive/html/" if url == browser.LIST_URL
                    else f"https://{browser.EFP_HOST}/auth/")
    page.goto.side_effect = navigate
    monkeypatch.setattr(browser.time, "monotonic", Mock(side_effect=[0, 31, 32, 33]))
    assert not browser.open_workspace_or_login(page, context, True, {}, checkpoint)
    assert [call.args[0] for call in page.goto.call_args_list] == [browser.LIST_URL, browser.LOGIN_URL]
    domain = context.clear_cookies.call_args.kwargs["domain"]
    assert domain.fullmatch(browser.EDOF_HOST) and domain.fullmatch(".moncompteformation.gouv.fr")
    assert not domain.fullmatch(browser.EFP_HOST) and not domain.fullmatch("other.invalid")
    checkpoint.assert_called_once()


def test_saved_cookie_fallback_only_after_two_inactive_portal_views(monkeypatch):
    page, context = Mock(), Mock()
    page.locator.return_value.all_inner_texts.return_value = ["Mon Compte Formation"]
    page.locator.return_value.count.return_value = 0
    page.goto.side_effect = lambda url, **kwargs: setattr(page, "url", url)
    monkeypatch.setattr(browser.time, "monotonic", Mock(side_effect=[0, 20, 21, 41]))
    with pytest.raises(browser.StopRun, match="saved_session_unavailable"):
        browser.open_workspace_or_login(page, context, True, {}, Mock())
    assert [c.args[0] for c in page.goto.call_args_list] == [browser.LIST_URL, browser.LOGIN_URL]
    for signals in ({"workspace_status": 200}, {"workspace_denied": True}):
        assert not browser.inactive_saved_view(page, signals)
    page.locator.return_value.all_inner_texts.return_value = ["Accepter la charte"]
    assert not browser.inactive_saved_view(page, {})
    page.locator.return_value.all_inner_texts.return_value = [""]
    page.locator.return_value.count.return_value = 1
    assert not browser.inactive_saved_view(page, {})


def test_hash_navigation_timeout_needs_the_requested_url_and_its_successful_response():
    page = Mock()
    url = browser.DETAIL_PREFIX + "123456789"
    page.url = browser.LIST_URL
    def change_hash(*args, **kwargs):
        page.url = url
        raise TimeoutError()
    page.goto.side_effect = change_hash
    browser.open_folder_view(page, url, lambda: True, TimeoutError)
    with pytest.raises(TimeoutError):
        browser.open_folder_view(page, url, lambda: False, TimeoutError)
    page.goto.side_effect = TimeoutError()
    page.url = browser.LIST_URL
    with pytest.raises(TimeoutError):
        browser.open_folder_view(page, url, lambda: True, TimeoutError)


def test_name_search_submits_only_the_control_attached_to_the_named_field():
    page = Mock()
    boxes = page.locator.return_value
    boxes.evaluate_all.return_value = ["surname"]
    field = boxes.nth.return_value
    group = field.locator.return_value
    group.locator.return_value.count.return_value = 1
    button = group.get_by_role.return_value.filter.return_value
    button.count.return_value = 1
    button.evaluate.return_value = "arrow_forward"
    signals, lists = {}, ["previous"]
    browser.submit_name_search(page, "Exemple", "Camille", lists, signals, TimeoutError)
    assert signals["search_step"] == "results" and not lists
    page.get_by_text.assert_not_called()
    button.click.assert_called_once()
    field.fill.assert_called_once_with("Exemple", timeout=8000)
    field.press.assert_not_called()
    button.reset_mock()
    button.evaluate.return_value = "Exporter"
    browser.submit_name_search(page, "Exemple", "Camille", lists, signals, TimeoutError)
    button.click.assert_not_called()
    field.press.assert_called_once()


def test_visible_name_tab_waits_for_focus_before_activation():
    page, tab, signals = Mock(), Mock(), {}
    page.locator.return_value.count.return_value = 0
    tab.evaluate_all.side_effect = ["", "", "Space"]
    browser.activate_name_tab(page, tab, signals)
    assert [call.args[0] for call in page.keyboard.press.call_args_list] == ["Tab", "Tab", "Space"]
    tab.click.assert_not_called()
    assert signals["name_activation"] == "keyboard"
    page.keyboard.press.reset_mock()
    page.locator.return_value.count.side_effect = [0, 1]
    with pytest.raises(browser.StopRun, match="workspace_dialog_required"):
        browser.activate_name_tab(page, tab, signals)
    page.keyboard.press.assert_not_called()


def test_paired_form_fills_both_names_and_submits_their_search_button():
    page, surname, given = Mock(), Mock(), Mock()
    boxes = page.locator.return_value
    boxes.evaluate_all.return_value = ["other", "surname", "given"]
    boxes.nth.side_effect = [Mock(), surname, given].__getitem__
    group = given.locator.return_value
    group.locator("input:visible").count.return_value = 2
    group.locator("input:visible").and_.return_value.count.return_value = 1
    button = group.get_by_role.return_value.filter.return_value
    button.count.return_value = 1
    button.evaluate.return_value = "Rechercher"
    signals = {}
    browser.submit_name_search(page, "Le Test", "André", [], signals, TimeoutError)
    surname.fill.assert_called_once_with("Le Test", timeout=8000)
    given.fill.assert_called_once_with("André", timeout=8000)
    button.click.assert_called_once()
    assert signals["paired_name_search"] is True


def test_ambiguous_name_fields_do_not_receive_a_search_value():
    page, signals = Mock(), {}
    page.locator.return_value.evaluate_all.return_value = ["surname", "surname", "given"]
    assert browser.name_search_inputs(page, signals) == (None, None)
    page.locator.return_value.nth.assert_not_called()


@pytest.mark.parametrize("query,paired,found", [
    ("page=0&attendeeName=LE+TEST&attendeeFirstName=Andr%C3%A9", True, True),
    ("page=0", True, False), ("tag=Le+Test&attendeeFirstName=Andr%C3%A9", True, False),
    ("attendeeName=Le+Test", True, False), ("attendeeName=Le+Test", False, True),
    ("attendeeName=Le+Test&attendeeFirstName=autre", False, False),
    ("attendeeName=Le+Test&attendeeName=autre&attendeeFirstName=Andr%C3%A9", True, False),
])
def test_only_the_requested_edof_name_filter_can_supply_candidates(query, paired, found):
    assert browser.matches_name_query(query, "Le Test", "André", paired) == found


def test_establishment_dropdown_uses_standard_keyboard_action_and_respects_an_overlay():
    page = Mock()
    page.url = f"https://{browser.EDOF_HOST}/espace-prive/html/#/select-sirets"
    locator = page.locator.return_value
    locator.all.return_value = []
    locator.count.return_value = 0
    locator.and_.return_value.count.return_value = 0
    page.get_by_role.return_value.or_.return_value.filter.return_value.count.return_value = 0
    page.get_by_text.return_value.filter.return_value.count.return_value = 0
    dropdown = locator.or_.return_value
    dropdown.count.return_value = 1
    dropdown.is_enabled.return_value = True
    dropdown.get_attribute.return_value = "false"
    dropdown.evaluate.side_effect = [
        {"surface": "dialog", "depth": 0}, [["span private-name"], ["div modal secret"]],
        {"surface": "control", "depth": 0}, {"surface": "widget", "depth": 2},
    ]
    signals = {}
    assert browser.select_establishment(page, "waiting", signals) == "waiting"
    dropdown.press.assert_not_called()
    dropdown.click.assert_not_called()
    assert browser.select_establishment(page, "waiting", signals) == "keyboard"
    dropdown.press.assert_called_once_with("ArrowDown", timeout=3000)
    assert signals["chooser_surface"] == "control" and signals["chooser_action"] == "open_keyboard"
    assert signals["cover_shape"] == ["div-modal"] and signals["control_shape"] == ["span"]
    assert browser.select_establishment(page, "waiting", signals) == "opened"
    dropdown.locator.assert_called_once_with("xpath=../..")
    dropdown.locator.return_value.click.assert_called_once_with(timeout=3000)


def test_blocked_request_diagnostics_do_not_disclose_paths_ids_queries_or_body_values():
    root = "https://" + browser.EDOF_HOST
    url = root + "/idp/edof/api/v2/exchange-token?code=synthetic-secret#extra"
    folder = root + "/edof-api/v1/api/private/siret/12345678900000/registration-folders/123456/makeChange"
    route = browser.safe_edof_route(url)
    assert route == "/idp/edof/api/v2/exchange-token"
    assert browser.safe_edof_route(folder) == "/edof-api/v1/api/private/siret/*/registration-folders/*/*"
    assert browser.safe_edof_route("https://example.invalid/private") == "other_origin"
    result = browser.diagnostic_summary(root + "/espace-prive/html/#/redirect-to-mire-connexion?code=synthetic-secret", False, False, {
        "edof_blocked_routes": [route, "/secret/person-name", "/api?token=synthetic-secret"],
        "edof_screen": "untrusted text"})
    assert result["edof_blocked_routes"] == [route]
    assert result["location"] == "edof_login_redirect" and "edof_screen" not in result
    assert "synthetic-secret" not in json.dumps(result)


def test_edof_dialog_only_closes_a_dismissible_notice():
    page = Mock()
    layer = page.locator.return_value.filter.return_value
    layer.count.return_value = 1
    layer.get_by_role.return_value.count.return_value = 0
    layer.locator.return_value.count.return_value = 0
    layer.locator.return_value.all_inner_texts.return_value = ["Informations du compte Personne Exemple"]
    actions = layer.get_by_role.return_value.or_.return_value.filter.return_value
    actions.evaluate_all.return_value = ["Fermer cette fenêtre", "Personne Exemple 12345"]
    layer.all_inner_texts.return_value = ["J’accepte les conditions générales. Personne Exemple."]
    signals = {}
    with pytest.raises(browser.StopRun, match="workspace_dialog_required"):
        browser.handle_chooser_dialog(page, signals)
    assert signals["dialog_kind"] == "terms" and signals["dialog_buttons"] == ["fermer cette fenetre"]
    layer.get_by_role.return_value.click.assert_not_called()
    layer.all_inner_texts.return_value = ["Bienvenue. Une nouvelle fonctionnalité est disponible."]
    target = Mock()
    target.count.return_value = 1
    target.is_visible.return_value = target.is_enabled.return_value = True
    original = layer.get_by_role.return_value
    layer.get_by_role.side_effect = lambda role, **kw: target if kw.get("name") is browser.DIALOG_CLOSE else original
    assert browser.handle_chooser_dialog(page, signals)
    assert browser.handle_chooser_dialog(page, signals)
    target.click.assert_called_once()
    assert "personne" not in json.dumps(signals) and "12345" not in json.dumps(signals)


@pytest.mark.parametrize("label,refuse", [
    ("close Tout refuser et fermer", True), ("Continuer sans accepter", True),
    ("Tout accepter et fermer", False), ("Paramétrer les cookies", False),
    ("Ne pas tout refuser et fermer", False),
])
def test_cookie_refusal_uses_the_action_seen_in_edof(label, refuse):
    assert bool(browser.COOKIE_DECLINE.search(label)) is refuse


def test_cookie_keyboard_only_activates_the_observed_refusal_when_focused():
    page, target = Mock(), Mock()
    target.count.return_value = 1
    target.evaluate_all.side_effect = [False, False, True]
    assert browser.activate_cookie_refusal(page, target) == "keyboard"
    assert [c.args[0] for c in page.keyboard.press.call_args_list] == ["Tab", "Tab", "Enter"]
    target.click.assert_not_called()
    target.evaluate_all.side_effect = [False]
    target.count.return_value = 0
    page.keyboard.press.reset_mock()
    assert browser.activate_cookie_refusal(page, target) == "disappeared"
    page.keyboard.press.assert_not_called()


def test_disappearing_cookie_panel_does_not_wait_for_a_stale_locator():
    page = Mock()
    layer = page.locator.return_value.filter.return_value
    layer.all_inner_texts.return_value = []
    signals = {"cookies_dismissed": True}
    assert browser.handle_chooser_dialog(page, signals) is False and signals["cookie_dialog_closed"] is True
    layer.inner_text.assert_not_called()


def test_real_material_select_opens_then_requires_the_unique_matching_option():
    page = Mock()
    page.url = f"https://{browser.EDOF_HOST}/espace-prive/html/#/select-sirets"
    material = page.locator.return_value
    material.count.return_value = 1
    material.get_attribute.return_value = "false"
    material.inner_text.return_value = "Sélectionnez un SIRET"
    signals = {}
    assert browser.select_establishment(page, "waiting", signals) == "opened"
    material.click.assert_called_once_with(timeout=3000)
    material.get_attribute.return_value = "true"
    option = page.get_by_role.return_value.get_by_role.return_value.filter.return_value
    option.count.return_value = 2
    assert browser.select_establishment(page, "opened", signals) == "opened"
    option.click.assert_not_called()
    option.count.return_value = 1
    assert browser.select_establishment(page, "opened", signals) == "selected"
    option.click.assert_called_once_with(timeout=3000)


@pytest.mark.parametrize("text,code", [("Nom d’utilisateur ou mot de passe invalide.", "credentials_rejected"), ("Votre compte est désactivé.", "account_unavailable"), ("Saisissez votre code d’authentification.", "verification_code")])
def test_additional_authentication_outcomes(text, code):
    assert browser.classify_text(text) == code


def test_store_owner_isolation_expiry_cooldown_and_interruption(tmp_path, monkeypatch):
    now = 1000000.0
    monkeypatch.setattr(server.time, "time", lambda: now)
    store = server.ServerTestStore(tmp_path)
    job = store.reserve("owner-a", "read")
    assert store.latest("owner-b") == []
    with pytest.raises(ValueError):
        store.reserve("owner-b", "access")
    now += server.JOB_TIMEOUT + 31
    assert store.latest("owner-a")[0]["code"] == "interrupted"
    with pytest.raises(ValueError):
        store.reserve("owner-a", "read")
    now += 121
    job2 = store.reserve("owner-a", "read")
    store.finish(job2, {"code": "read_success", "fresh_session": True})
    assert store.latest("owner-a")[0]["finished"]
    assert (store.path.stat().st_mode & 0o777) == 0o600
    now += 86401
    assert store.latest("owner-a") == []


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.delenv("EDOF_EFP_USERNAME", raising=False)
    monkeypatch.delenv("EDOF_EFP_PASSWORD", raising=False)
    root = Path(server.__file__).parent
    app = Flask(__name__, template_folder=str(root / "templates"))
    app.config.update(TESTING=True, SECRET_KEY="synthetic-test-only")
    store = server.ServerTestStore(tmp_path)
    def required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("admin"):
                return jsonify(ok=False), 401
            return view(*args, **kwargs)
        return wrapper
    server.register_routes(app, store, admin_required=required, can_access=lambda: not session.get("partner"))
    @app.context_processor
    def forbidden_context():
        raise AssertionError("Legacy business context must not run")
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin"] = True
    assert client.get("/admin/edof-test/server").status_code == 200
    with client.session_transaction() as sess:
        csrf = sess["edof_server_csrf"]
    return app, client, store, csrf


def test_route_auth_csrf_secrets_missing_and_no_start(web, monkeypatch):
    app, client, store, csrf = web
    monkeypatch.setattr(server, "start_job", lambda *a: pytest.fail("Must not start browser"))
    assert app.test_client().get("/admin/edof-test/server/status").status_code == 401
    assert client.post("/admin/edof-test/server/run", json={"mode": "access"}).status_code == 403
    response = client.post("/admin/edof-test/server/run", json={"mode": "read", "folder_id": "123456789012"}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409
    with client.session_transaction() as sess:
        sess["partner"] = True
    assert client.get("/admin/edof-test/server/status").status_code == 403


def test_readonly_routes_do_not_leak_env_or_other_owner_results(web, monkeypatch):
    app, client, store, csrf = web
    monkeypatch.setenv("EDOF_EFP_USERNAME", "synthetic@example.invalid")
    monkeypatch.setenv("EDOF_EFP_PASSWORD", "synthetic-private-password")
    job = store.reserve("someone-else", "access")
    store.finish(job, {"code": "read_success", "fields": {"email": "other@example.invalid"}})
    response = client.get("/admin/edof-test/server/status")
    assert response.json["config"]["credentials_configured"] is True
    assert response.json["jobs"] == []
    text = response.get_data(as_text=True) + client.get("/admin/edof-test/server").get_data(as_text=True)
    assert "synthetic-private-password" not in text and "synthetic@example.invalid" not in text and "other@example.invalid" not in text


def test_connection_indicator_only_reports_private_checks_and_never_signs_in(web, monkeypatch):
    _, client, store, _ = web
    store.connector_key = server.connector_key("synthetic-secret-long-enough-for-a-test")
    vault = server.Vault(store.directory, store.connector_key)
    monkeypatch.setattr(server, "start_job", lambda *a: pytest.fail("A status check must stay local"))
    now = server.time.time()
    monkeypatch.setattr(server.time, "time", lambda: now)
    with client.session_transaction() as sess:
        owner = hashlib.sha256(sess["edof_server_owner"].encode()).hexdigest()
    path = "/admin/edof-test/server/connection-status"
    assert client.get(path).json["state"] == "missing"
    vault.put("browser", {"cookies": [{"value": "synthetic-cookie"}]}, ttl=86400)
    store.finish(store.reserve(owner, "access"), {"code": "login_reachable"})
    assert client.get(path).json == {"state": "unknown", "label": "État à confirmer", "checked_at": None}
    store.finish(store.reserve(owner, "directory"), {"code": "directory_ready"})
    expected_time = server.dt.datetime.fromtimestamp(now, server.ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H h %M")
    assert client.get(path).json == {"state": "confirmed", "label": "Active au dernier contrôle", "checked_at": expected_time}
    now += 301
    store.finish(store.reserve("another-admin", "read"), {"code": "sign_in_error"})
    html = client.get("/admin/edof-test/server").get_data(as_text=True)
    assert "Active au dernier contrôle" in html and html.index('id="connexion-efp"') < html.index('id="dossier-lu"')
    assert "synthetic-cookie" not in html + client.get(path).get_data(as_text=True)
    for result, expected in [
        ({"code": "timeout"}, "unknown"),
        ({"code": "organism_selection_required", "diagnostics": {"edof_screen": "session_expired"}}, "expired"),
        ({"code": "credentials_rejected"}, "reconnect"),
    ]:
        now += 301
        store.finish(store.reserve(owner, "read"), result)
        assert client.get(path).json["state"] == expected
    now += 86401
    assert client.get(path).json["state"] == "missing"
    with client.session_transaction() as sess:
        sess["partner"] = True
    assert client.get(path).status_code == 403


def test_old_success_follows_only_the_same_account_and_stays_visible_after_failed_attempts(web, monkeypatch):
    app, first, store, _ = web
    now = server.time.time()
    monkeypatch.setattr(server.time, "time", lambda: now)
    with first.session_transaction() as sess:
        old = hashlib.sha256(sess["edof_server_owner"].encode()).hexdigest()
        sess["admin_username"] = "Owner@example.invalid"
    job = store.reserve(old, "read")
    fields = {"first_name": "Camille", "last_name": "Exemple", "folder_id": "123456789", "state": "serviceDoneValidated"}
    store.finish(job, {"code": "read_success", "fields": fields})
    for _ in range(3):
        now += 301
        store.finish(store.reserve(old, "read"), {"code": "timeout"})
    assert first.get("/admin/edof-test/server").get_data(as_text=True).count("Camille Exemple") == 1
    assert not store.latest(old)
    second = app.test_client()
    with second.session_transaction() as sess:
        sess.update(admin=True, admin_username="owner@example.invalid")
    path = "/admin/edof-test/server?result=" + job
    assert "Service fait validé" in second.get(path).get_data(as_text=True)
    assert all(j["code"] == "timeout" for j in second.get("/admin/edof-test/server/status").json["jobs"])
    with first.session_transaction() as sess:
        account = sess["edof_history_account"]
    now += 301
    active = store.reserve(account, "read")
    assert 'data-running="true"' in second.get("/admin/edof-test/server").get_data(as_text=True)
    pinned = second.get(path).get_data(as_text=True)
    assert 'data-running="true"' not in pinned and "Camille Exemple" in pinned
    store.finish(active, {"code": "timeout"})
    with second.session_transaction() as sess:
        sess["admin_username"] = "other@example.invalid"
    text = second.get(path).get_data(as_text=True)
    assert "Camille" not in text and "Cette lecture n’est pas disponible" in text
    assert "Camille" not in second.get("/admin/edof-test/server").get_data(as_text=True)
    with second.session_transaction() as sess:
        sess.update(admin_username="owner@example.invalid", partner=True)
    assert second.get(path).status_code == 403
    assert app.test_client().get(path).status_code == 401
    now += 86401
    assert "Camille" not in first.get(path).get_data(as_text=True)


def test_cached_read_during_shared_cooldown_and_accurate_retry_time(web, monkeypatch):
    app, client, store, csrf = web
    now = server.time.time()
    monkeypatch.setattr(server.time, "time", lambda: now)
    monkeypatch.setenv("EDOF_EFP_USERNAME", "synthetic@example.invalid")
    monkeypatch.setenv("EDOF_EFP_PASSWORD", "synthetic-private")
    with client.session_transaction() as sess:
        owner = hashlib.sha256(sess["edof_server_owner"].encode()).hexdigest()
    fields = {"first_name": "Camille", "last_name": "Exemple", "folder_id": "123456789"}
    job = store.reserve(owner, "read")
    store.finish(job, {"code": "read_success", "fields": fields})
    now += 280.2
    spec = {"mode": "read", "first_name": "camille", "last_name": "EXEMPLE"}
    endpoint, headers = "/admin/edof-test/server/run", {"X-CSRF-Token": csrf}
    response = client.post(endpoint + "?prefer_saved=1", json=spec, headers=headers)
    assert response.status_code == 200 and response.json["saved"] and response.json["job_id"] == job
    assert "Camille Exemple" in client.get(response.json["result_url"]).get_data(as_text=True)
    for url, query in ((endpoint, spec), (endpoint + "?prefer_saved=1", {**spec, "folder_id": "987654321"})):
        wait = client.post(url, json=query, headers=headers)
        assert wait.status_code == 429 and wait.json["retry_after"] == 20 and wait.headers["Retry-After"] == "20"
    assert len(store.latest(owner)) == 1
    now += 40
    store.finish(store.reserve(owner, "read"), {"code": "read_success", "fields": {**fields, "folder_id": "987654321"}})
    assert store.successful_read(owner, spec=server.validate_spec(spec)) is None
    assert store.successful_read(owner, spec=server.validate_spec({**spec, "folder_id": "123456789"}))["id"] == job


def test_service_gate_blocks_production(monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_ID", "production")
    monkeypatch.setattr(server, "register_routes", lambda *a, **k: pytest.fail("Production route registered"))
    server.register_edof_server_test(None)
    assert browser.run_browser({"mode": "access"})["code"] == "wrong_environment"


@pytest.mark.parametrize("reasons,summary", [
    ({}, "aucun nouveau message de l’expéditeur EFP attendu"),
    ({"code_unrecognized": 1}, "Format du code non reconnu"),
])
def test_admin_sees_absent_mail_or_precise_verification_failure(web, reasons, summary):
    app, client, store, csrf = web
    with client.session_transaction() as sess:
        owner = hashlib.sha256(sess["edof_server_owner"].encode()).hexdigest()
    job = store.reserve(owner, "read")
    store.finish(job, {"code": "gmail_code_missing", "stage": "authentication", "diagnostics":
        {"gmail_messages_checked": sum(reasons.values()), "gmail_rejections": reasons}})
    page = client.get("/admin/edof-test/server")
    assert page.status_code == 200 and summary in page.get_data(as_text=True)


@pytest.mark.parametrize("stage,used,confirmed", [
    ("search", True, True), ("search", False, False), ("authentication", True, False),
])
def test_only_confirm_completed_gmail_login_after_leaving_efp(web, stage, used, confirmed):
    _, client, store, _ = web
    with client.session_transaction() as sess:
        owner = hashlib.sha256(sess["edof_server_owner"].encode()).hexdigest()
    job = store.reserve(owner, "read")
    store.finish(job, {"code": "timeout", "stage": stage, "gmail_code_used": used})
    page = client.get("/admin/edof-test/server").get_data(as_text=True)
    assert ("Connexion EFP réussie avec le code reçu dans Gmail." in page) is confirmed


def test_timeout_kills_process_tree_and_hides_diagnostics(tmp_path, monkeypatch):
    store = server.ServerTestStore(tmp_path)
    job = store.reserve("owner", "read")
    calls = []
    temporary_paths = []
    monkeypatch.setenv("DATABASE_URL", "synthetic-database-secret")
    monkeypatch.setenv("EDOF_EFP_PASSWORD", "synthetic-efp-secret")
    class Child:
        pid = 12345
        def communicate(self, input=None, timeout=None):
            if timeout:
                raise subprocess.TimeoutExpired("synthetic-private-command", timeout)
            return "", ""
    def popen(*args, **kwargs):
        assert "DATABASE_URL" not in kwargs["env"]
        assert kwargs["env"]["EDOF_EFP_PASSWORD"] == "synthetic-efp-secret"
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["start_new_session"] is True
        temporary_paths.append(Path(kwargs["env"]["TMPDIR"]))
        (temporary_paths[-1] / "synthetic-profile").write_text("synthetic-temporary-secret")
        return Child()
    monkeypatch.setattr(server.subprocess, "Popen", popen)
    monkeypatch.setattr(server.os, "killpg", lambda pid, sig: calls.append(pid))
    fd = os.open(tmp_path / "lock", os.O_CREAT | os.O_RDWR, 0o600)
    server.execute_job(store, job, {"mode": "read", "folder_id": "123456789012"}, fd)
    assert calls == [12345]
    assert not temporary_paths[0].exists()
    assert store.latest("owner")[0]["code"] == "timeout"
    assert "synthetic-private" not in json.dumps(store.latest("owner"))


def test_directory_requires_all_pages_and_only_keeps_list_fields():
    import edof_directory as directory
    first = {"id": "123456", "attendee": {"firstName": "André", "lastName": "LE TEST", "email": "private@invalid"}}
    second = {**first, "id": "654321"}
    before = {"numberOfItems": 2, "items": [first]}
    after = {"numberOfItems": 2, "items": [second]}
    snapshot = directory.from_pages([before, after])
    assert len(snapshot["rows"]) == 2 and "private@invalid" not in str(snapshot)
    query = {"first_name": "ANDRE", "last_name": "le-test", "folder_id": ""}
    assert len(directory.matches(snapshot, query)) == 2
    assert directory.matches(snapshot, {**query, "folder_id": "654321"}) == [snapshot["rows"]["654321"]]
    for pages in ([before], [before, before], [before, {**after, "numberOfItems": 3}],
                  [{"numberOfItems": 1, "items": [{"id": "../other"}]}]):
        with pytest.raises(directory.IncompleteDirectory):
            directory.from_pages(pages)
    assert directory.from_pages([{"numberOfItems": 0, "items": []}])["rows"] == {}


def test_directory_paginates_only_the_witnessed_official_list():
    from urllib.parse import parse_qs, urlsplit
    import edof_directory as directory
    official = "https://" + browser.EDOF_HOST + browser.API_PREFIX + "pad"
    def response(url, ids, total=3):
        r = Mock(url=url, status=200)
        r.body.return_value = json.dumps({"numberOfItems": total, "items": [
            {"id": str(100000 + i), "attendee": {"firstName": "Test", "lastName": "Exemple"}} for i in ids]}).encode()
        return r
    first = response(official + "?page=0&size=1&state=accepted", [0])
    first.request.all_headers.return_value = {"authorization": "synthetic", "other": "excluded"}
    tab = Mock()
    def get_batch(url, **kwargs):
        assert url.startswith(official + "?") and kwargs["max_redirects"] == 0
        assert kwargs["headers"] == {"authorization": "synthetic"}
        q = parse_qs(urlsplit(url).query)
        assert q["state"] == ["accepted"] and q["size"] == ["100"]
        return response(url, [0, 1] if q["page"] == ["0"] else [2])
    tab.context.request.get.side_effect = get_batch
    assert len(directory.from_pages(browser.directory_pages(tab, first, Mock()))["rows"]) == 3
    assert browser.is_directory_view(browser.LIST_URL)
    assert not browser.is_directory_view(browser.DETAIL_PREFIX + "123456")
    assert not browser.directory_list_url(official + "?attendeeName=Example")
    assert not browser.directory_list_url(official.replace(browser.EDOF_HOST, "elsewhere.invalid"))
    assert not browser.directory_list_url(official.replace("/siret/" + browser.SIRET, "/siret/other"))


def test_unseen_name_local_lookup_is_isolated_and_never_starts_a_browser(web, monkeypatch):
    import edof_directory as directory
    app, client, store, csrf = web
    store.connector_key = server.connector_key("s" * 48)
    with client.session_transaction() as sess:
        user = hashlib.sha256(sess["edof_server_owner"].encode()).hexdigest()
    vault = server.Vault(store.directory, store.connector_key)
    monkeypatch.setattr(server, "start_job", lambda *args: pytest.fail("Local lookup must not start EFP"))
    path = "/admin/edof-test/server/directory/lookup"
    payload = {"mode": "read", "first_name": "Andre", "last_name": "LE TEST"}
    headers = {"X-CSRF-Token": csrf}
    assert client.post(path, json=payload).status_code == 403
    assert "première synchronisation" in client.post(path, json=payload, headers=headers).json["message"]
    item = {"id": "123456", "beginDate":"01/01/2026", "attendee": {"firstName": "André", "lastName": "Le-Test"}, "currentState": "accepted"}
    def seed(items):
        snapshot = directory.from_pages([{"numberOfItems": len(items), "items": items}])
        vault.put(directory.record_key(user), snapshot, ttl=86400)
    seed([item])
    hit = client.post(path, json=payload, headers=headers).json["matches"][0]
    assert store.latest(user) == []
    assert "LISTE EDOF SYNCHRONISÉE" in client.get(hit["url"]).get_data(as_text=True)
    assert "Aucun dossier" in client.post(path, json={**payload, "folder_id": "999999"}, headers=headers).json["message"]
    other = app.test_client()
    with other.session_transaction() as sess:
        sess["admin"] = True
    assert "André Le-Test" not in other.get(hit["url"]).get_data(as_text=True)
    seed([item, {**item, "id": "234567"}])
    assert len(client.post(path, json=payload, headers=headers).json["matches"]) == 2


def test_directory_scheduler_pauses_after_failure_and_shares_login_cooldown(tmp_path, monkeypatch):
    import edof_directory as directory
    now = 1000000.0
    monkeypatch.setattr(server.time, "time", lambda: now)
    store = server.ServerTestStore(tmp_path)
    store.use_directory("user", enable=True)
    store.finish(store.reserve("user", "directory"), {"code": "directory_ready"})
    with pytest.raises(server.JobCooldown):
        store.reserve("user", "read")
    now += directory.REFRESH_INTERVAL + 1
    assert store.due_directories() == ["user"]
    store.finish(store.reserve("user", "directory"), {"code": "human_verification"})
    now += directory.REFRESH_INTERVAL + 1
    assert not store.due_directories()


def test_directory_keeps_refreshing_while_idle_until_paused(tmp_path, monkeypatch):
    import edof_directory as directory
    now = 1000000.0
    monkeypatch.setattr(server.time, "time", lambda: now)
    store = server.ServerTestStore(tmp_path)
    store.use_directory("user", enable=True)
    store.finish(store.reserve("user", "directory"), {"code": "directory_ready"})
    now += 3601
    assert not store.due_directories()
    now += directory.IDLE_REFRESH_INTERVAL
    assert store.due_directories() == ["user"]
    store.pause_directory("user")
    store.use_directory("user")
    assert not store.directory_enabled("user") and not store.due_directories()


def test_official_export_checks_scope_count_identity_and_drops_unused_columns():
    import edof_directory as directory
    header = "N° de dossier;Nom du titulaire;Prénom du titulaire;Statut du dossier;Intitulé de la formation;Date de début de session;Courriel\r\n"
    content = header + "123456;Exemple;André;Accepté;VTC;02/11/2026;private@example.invalid\r\n"
    first = {"numberOfItems": 1, "items": [{"id": "123456", "attendee": {"firstName": "ANDRE", "lastName": "EXEMPLE"}}]}
    snapshot = directory.csv_snapshot(content.encode("cp1252"), first, {})
    assert snapshot["rows"]["123456"]["title"] == "VTC"
    assert snapshot["rows"]["123456"]["session_start_date"] == "2026-11-02"
    assert "private@" not in str(snapshot)
    for bad in (content.replace("123456", "654321"), content.replace("Exemple", "Autre"), header, content + content):
        with pytest.raises(directory.IncompleteDirectory):
            directory.csv_snapshot(bad.encode("utf-8-sig"), first, {})


def test_efp_navigation_timeout_requires_two_official_callbacks_and_a_private_view():
    signals = {"callback_status": 200, "edof_token_status": 200}
    chooser = "https://" + browser.EDOF_HOST + "/espace-prive/html/#/select-sirets"
    assert browser.returned_to_organisation(chooser, signals)
    assert not browser.returned_to_organisation(chooser, {"callback_status": 200})
    assert not browser.returned_to_organisation(chooser.replace("https:", "http:"), signals)
    assert not browser.returned_to_organisation(browser.LOGIN_URL, signals)
    assert not browser.returned_to_organisation(chooser.replace(browser.EDOF_HOST, "other.invalid"), signals)
