from pathlib import Path


TEMPLATE = Path("templates/admin_afc.html").read_text()


def test_afc_import_modal_only_closes_from_explicit_actions():
    assert "document.getElementById('afcCancelImport').addEventListener('click',closeAfcImport);" in TEMPLATE
    assert "afcImportModal.addEventListener('click'" not in TEMPLATE
