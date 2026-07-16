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
