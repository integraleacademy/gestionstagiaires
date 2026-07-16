from pathlib import Path

JS = Path("static/js/postal_city_lookup.js").read_text(encoding="utf-8")


def test_postal_lookup_rejects_letters_limits_to_five_and_waits_for_complete_zip():
    assert "replace(/\\D+/g" in JS
    assert "slice(0, 5)" in JS
    assert 'setAttribute("maxlength", "5")' in JS
    assert "cleaned.length !== 5" in JS


def test_postal_lookup_uses_official_geo_api_with_timeout_debounce_and_abort():
    assert "https://geo.api.gouv.fr/communes" in JS
    assert "codePostal=" in JS
    assert "fields=nom,code,codesPostaux&format=json" in JS
    assert "DEBOUNCE_MS = 300" in JS
    assert "REQUEST_TIMEOUT_MS" in JS
    assert "AbortController" in JS


def test_postal_lookup_handles_single_multiple_empty_and_error_results():
    assert "cities.length === 1" in JS
    assert "cities.length > 1" in JS
    assert "Aucune commune trouvée pour ce code postal" in JS
    assert "Recherche de ville indisponible, saisie manuelle possible" in JS


def test_postal_lookup_keyboard_selection_and_safe_rendering():
    assert 'event.key === "ArrowDown"' in JS
    assert 'event.key === "ArrowUp"' in JS
    assert 'event.key === "Enter"' in JS
    assert 'event.key === "Escape"' in JS
    assert "textContent = city.nom" in JS
    assert "innerHTML" not in JS


def test_postal_lookup_is_loaded_on_create_and_existing_trainee_forms():
    for template in [
        "templates/admin_trainees.html",
        "templates/admin_sessions.html",
        "templates/admin_afc_candidate_sheet.html",
        "templates/public_trainee.html",
    ]:
        assert "js/postal_city_lookup.js" in Path(template).read_text(encoding="utf-8")
    assert '["tZipCode", "tCity"]' in JS
    assert '["sessionTZipCode", "sessionTCity"]' in JS
    assert '["enrollZipCode", "enrollCity"]' in JS
    assert '["zip_code", "city"]' in JS


def test_postal_lookup_suggestions_are_attached_to_zip_field_container():
    assert 'zipWrapper.classList.add("postal-city-field")' in JS
    assert 'const list = createList(zipInput)' in JS
    assert '(zipWrapper || zipInput).appendChild(list)' in JS
    assert '(cityWrapper || cityInput).appendChild(list)' not in JS


def test_french_address_autocomplete_uses_geopf_with_safe_params_and_mapping():
    assert "https://data.geopf.fr/geocodage/completion/" in JS
    assert "text: query" in JS
    assert "type: \"StreetAddress\"" in JS
    assert "maximumResponses: \"6\"" in JS
    assert "api-adresse.data.gouv.fr" not in JS
    for prop in ["fulltext", "name", "housenumber", "houseNumber", "number", "street", "zipcode", "city", "kind"]:
        assert prop in JS


def test_french_address_autocomplete_debounce_abort_timeout_and_short_input():
    assert "function usefulLength" in JS
    assert "usefulLength(query) < 3" in JS
    assert "DEBOUNCE_MS = 300" in JS
    assert "AbortController" in JS
    assert "controller.abort()" in JS
    assert "REQUEST_TIMEOUT_MS" in JS
    assert "address_rate_limited" in JS


def test_french_address_autocomplete_safe_rendering_accessibility_and_keyboard():
    assert 'setAttribute("role", "combobox")' in JS
    assert 'setAttribute("aria-expanded", "false")' in JS
    assert 'setAttribute("aria-controls", list.id)' in JS
    assert 'setAttribute("aria-autocomplete", "list")' in JS
    assert 'setAttribute("role", "listbox")' in JS
    assert 'setAttribute("role", "option")' in JS
    assert 'setAttribute("aria-selected", "false")' in JS
    assert "main.textContent" in JS
    assert "meta.textContent" in JS
    assert 'event.key === "ArrowDown"' in JS
    assert 'event.key === "ArrowUp"' in JS
    assert 'event.key === "Enter"' in JS
    assert 'event.key === "Escape"' in JS


def test_french_address_autocomplete_selection_updates_three_fields_without_postal_loop():
    assert "isApplyingSelectedAddress = true" in JS
    assert "if(isApplyingSelectedAddress) return" in JS
    assert "postalCodeInput.value = item.postcode" in JS
    assert "cityInput.value = item.city" in JS
    assert "dispatchValueEvents(addressInput)" in JS
    assert "dispatchValueEvents(postalCodeInput)" in JS
    assert "dispatchValueEvents(cityInput)" in JS
    assert '"change"' in JS


def test_french_address_autocomplete_initialized_for_create_and_session_forms_and_styled():
    assert 'function initFrenchAddressAutocomplete(options)' in JS
    assert '["tAddress", "tZipCode", "tCity"]' in JS
    assert '["sessionTAddress", "sessionTZipCode", "sessionTCity"]' in JS
    css = Path("static/style.css").read_text(encoding="utf-8")
    assert ".french-address-field{position:relative;}" in css or ".french-address-field,.address-field-wrapper{position:relative;}" in css
    assert ".french-address-list{position:absolute" in css or ".french-address-list,.address-suggestions{position:absolute" in css
    assert "width:100%" in css
    assert "max-height:260px" in css
    assert "overflow-y:auto" in css
