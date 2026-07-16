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


def test_build_postal_address_preserves_numbers_suffixes_and_fulltext_fallback():
    assert 'function buildPostalAddress(result)' in JS
    assert 'result.housenumber ?? result.number' in JS
    assert 'parseInt' not in JS[JS.index('function buildPostalAddress'):JS.index('function mapAddressCompletionResult')]
    assert '`${houseNumber} ${street}`.trim()' in JS
    assert 'return extractStreetAddressFromFulltext(result && result.fulltext || "", result);' in JS
    assert '650 Route d’Aumont' not in JS  # examples are covered by executable backend/static tests, not hardcoded behavior


def test_fulltext_fallback_removes_only_trailing_zipcode_and_city():
    block = JS[JS.index('function extractStreetAddressFromFulltext'):JS.index('function buildPostalAddress')]
    assert 'function extractStreetAddressFromFulltext(fulltext, result)' in JS
    assert 'replace(/\\s+/g, " ").trim()' in block
    assert '${escapeRegExp(zipcode)}\\\\s+${escapeRegExp(city)}$' in block
    assert 'replace(/\\D+/g' not in block


def test_completion_result_keeps_raw_api_shape_for_diagnostics():
    assert 'console.debug("[ADDRESS] sample result", results[0]);' in JS
    assert 'housenumber' in JS
    assert 'number' in JS
    assert 'return {address, postcode: zipcode, city, label, kind, raw: result || {}};' in JS


def test_selection_uses_built_address_not_street_directly():
    mapping_block = JS[JS.index('function mapAddressCompletionResult'):JS.index('function initFrenchAddressAutocomplete')]
    selection_block = JS[JS.index('function selectAddress'):JS.index('async function fetchAddresses')]
    assert 'const address = buildPostalAddress(result || {});' in mapping_block
    assert 'addressInput.value = item.address || item.label || "";' in selection_block
    assert 'addressInput.value = selectedResult.street' not in JS
    assert 'addressInput.value = item.street' not in JS


def test_build_postal_address_executable_examples(tmp_path):
    import json
    import subprocess

    cases = [
        ({"housenumber": "650", "street": "Route d’Aumont"}, "650 Route d’Aumont"),
        ({"housenumber": "12 bis", "street": "Rue des Écoles"}, "12 bis Rue des Écoles"),
        ({"number": "4 ter", "street": "Avenue de la République"}, "4 ter Avenue de la République"),
        ({"street": "Rue sans numéro"}, "Rue sans numéro"),
        ({"housenumber": "8 quater", "street": "Impasse des Lilas"}, "8 quater Impasse des Lilas"),
        ({"number": "12 bis", "street": "Rue des Écoles"}, "12 bis Rue des Écoles"),
        ({"fulltext": "650 Route d’Aumont 15130 Arpajon-sur-Cère", "zipcode": "15130", "city": "Arpajon-sur-Cère"}, "650 Route d’Aumont"),
    ]
    script = tmp_path / "address_check.js"
    script.write_text(
        """
const fs = require('fs');
const vm = require('vm');
const context = {
  console,
  MutationObserver: function(){ this.observe = () => {}; },
  Event: function(){},
  window: { addEventListener: () => {} },
  document: {
    readyState: 'loading', body: null, addEventListener: () => {}, getElementById: () => null,
    createElement: () => ({ className: '', hidden: false, setAttribute: () => {}, appendChild: () => {}, classList: { add: () => {}, toggle: () => {}, remove: () => {} } })
  }
};
context.window.window = context.window;
context.window.document = context.document;
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/js/postal_city_lookup.js', 'utf8'), context);
const cases = JSON.parse(process.argv[2]);
for (const [input, expected] of cases) {
  const actual = context.window.buildPostalAddress(input);
  if (actual !== expected) throw new Error(`${JSON.stringify(input)} => ${actual}, expected ${expected}`);
}
"""
    )
    subprocess.run(["node", str(script), json.dumps(cases, ensure_ascii=False)], check=True, cwd=Path.cwd())
