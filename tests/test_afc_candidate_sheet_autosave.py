from pathlib import Path


TEMPLATE = Path("templates/admin_afc_candidate_sheet.html").read_text()


def test_afc_candidate_sheet_autosaves_identity_and_decision_fields():
    assert "function scheduleCandidateAutosave()" in TEMPLATE
    assert "decision.addEventListener('change', ()=>{ refreshUI(); scheduleCandidateAutosave(); });" in TEMPLATE
    for field_id in ("identifiant_ft", "nom", "prenom", "email", "telephone", "date_icop"):
        assert f"'{field_id}'" in TEMPLATE
    assert "el.addEventListener('input', scheduleCandidateAutosave);" in TEMPLATE


def test_afc_candidate_sheet_silent_autosave_includes_icop_date():
    assert "const ok = await saveCandidate({silent:true});" in TEMPLATE
    assert "date_icop: dateIcop.value" in TEMPLATE
    assert "if(!options.silent) alert('Erreur sauvegarde');" in TEMPLATE
