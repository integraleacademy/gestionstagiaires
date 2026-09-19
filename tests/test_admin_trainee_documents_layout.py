from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "admin_trainee.html").read_text(encoding="utf-8")


def test_documents_toolbar_gives_every_action_its_own_grid_cell():
    assert 'class="documents-actions"' in TEMPLATE
    assert ".documents-actions > form," in TEMPLATE
    assert ".documents-actions > a," in TEMPLATE
    assert ".documents-actions > button{" in TEMPLATE
    assert 'id="btnDocsRelance"' in TEMPLATE


def test_documents_table_has_scoped_columns_and_local_horizontal_scroll():
    assert 'class="table-wrap documents-table-wrap"' in TEMPLATE
    assert "#docsTable{" in TEMPLATE
    assert "min-width:1120px !important;" in TEMPLATE
    assert "table-layout:fixed;" in TEMPLATE
    assert "#docsTable td:nth-child(4){width:26%;}" in TEMPLATE


def test_document_file_links_and_delete_actions_share_button_styling():
    assert TEMPLATE.count('class="documents-file-cell"') >= 2
    assert TEMPLATE.count('class="document-file-actions"') >= 2
    assert TEMPLATE.count("document-file-action") >= 8
    assert 'class="mono" style="max-width:320px;"' not in TEMPLATE
