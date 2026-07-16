from pathlib import Path

JS = Path('static/js/postal_city_lookup.js').read_text()
CSS = Path('static/style.css').read_text()
BASE = Path('templates/base.html').read_text()
TRAINEES = Path('templates/admin_trainees.html').read_text()


def test_dynamic_modal_initialization_and_single_listener_guard():
    assert 'modal:opened' in JS
    assert 'MutationObserver' in JS
    assert 'dataset.addressAutocompleteInitialized === "true"' in JS
    assert 'dataset.addressAutocompleteInitialized = "true"' in JS
    assert 'window.dispatchEvent(new CustomEvent("modal:opened"' in BASE
    assert 'window.dispatchEvent(new CustomEvent("modal:opened"' in TRAINEES


def test_no_address_call_before_three_useful_characters():
    assert 'if(usefulLength(query) < 3) return;' in JS
    assert 'const DEBOUNCE_MS = 300;' in JS
    assert 'AbortController' in JS
    assert 'requestId !== state.requestId' in JS


def test_completion_endpoint_and_parameters_are_used():
    assert 'https://data.geopf.fr/geocodage/completion/' in JS
    assert 'text: query' in JS
    assert 'type: "StreetAddress"' in JS
    assert 'maximumResponses: "6"' in JS
    address_block = JS[JS.index('async function fetchAddresses'):JS.index('function onAddressInput')]
    assert 'q:' not in address_block
    assert 'limit:' not in address_block
    assert 'index:' not in address_block


def test_completion_results_are_rendered_and_selected():
    assert 'Array.isArray(data.results) ? data.results : []' in JS
    assert 'fulltext' in JS
    assert 'street' in JS
    assert 'zipcode' in JS
    assert 'city' in JS
    assert 'address-suggestions' in JS
    assert 'addressInput.value = item.address || item.label || "";' in JS
    assert 'postalCodeInput.value = item.postcode || "";' in JS
    assert 'cityInput.value = item.city || "";' in JS
    assert 'dispatchValueEvents(addressInput)' in JS
    assert 'dispatchValueEvents(postalCodeInput)' in JS
    assert 'dispatchValueEvents(cityInput)' in JS


def test_visible_diagnostics_errors_and_no_postal_city_loop():
    assert 'console.debug("[ADDRESS] input", query)' in JS
    assert 'console.debug("[ADDRESS] request", url)' in JS
    assert 'console.debug("[ADDRESS] status", response.status)' in JS
    assert 'console.debug("[ADDRESS] result count", suggestions.length)' in JS
    assert 'console.error("[ADDRESS] autocomplete failed", error)' in JS
    assert 'Recherche d’adresse indisponible, saisie manuelle possible.' in JS
    assert 'isApplyingSelectedAddress = true' in JS
    assert 'if(isApplyingSelectedAddress) return;' in JS


def test_address_suggestions_positioning():
    assert '.address-field-wrapper{position:relative;}' in CSS or '.french-address-field,.address-field-wrapper{position:relative;}' in CSS
    assert 'top:calc(100% + 6px)' in CSS
    assert 'z-index:10000' in CSS
    assert 'max-height:260px' in CSS
    assert 'overflow-y:auto' in CSS
