import json
from pathlib import Path
import shutil
import subprocess


TEMPLATE = Path("templates/admin_trainee_adef_sheet.html")


def _template_source():
    return TEMPLATE.read_text(encoding="utf-8")


def test_cnaps_validity_is_rendered_immediately_after_pre_or_car():
    source = _template_source()

    pre_or_car = source.index("Numéro PRE ou CAR")
    validity = source.index('id="adefCnapsValidityRow"')

    assert pre_or_car < validity
    assert "Date de fin de validité" in source
    assert 'id="adefCnapsValidity"' in source
    assert 'aria-live="polite"' in source


def test_cnaps_validity_reuses_authenticated_annuaire_endpoint():
    source = _template_source()

    assert "extract_nub_from_pre_car(adef.pre_or_car)" in source
    assert "/api/cnaps_public_annuaire" in source
    assert "new URLSearchParams({ nom, prenom, nub })" in source
    assert "payload.active_titles" in source
    assert "title.display_status" in source
    assert "title.date_fin_validite || title.valid_until" in source


def test_cnaps_validity_formats_expiration_and_handles_missing_data():
    source = _template_source()

    assert "`${isoMatch[3]}/${isoMatch[2]}/${isoMatch[1]}`" in source
    assert "`${frenchMatch[1]}/${frenchMatch[2]}/${frenchMatch[3]}`" in source
    assert "return value;" in source
    assert "Expire le ${validUntil}" in source
    assert "NUB absent — validité CNAPS non vérifiable." in source
    assert "Aucun titre CNAPS actif trouvé." in source
    assert "Date d’expiration non renseignée" in source
    assert "Validité CNAPS momentanément indisponible." in source


def test_cnaps_validity_formatter_preserves_french_dates_and_converts_iso():
    source = _template_source()
    start = source.index("const formatFrenchDate = (rawDate) => {")
    end = source.index("\n      };", start) + len("\n      };")
    formatter = source[start:end]
    node = shutil.which("node")
    if not node:
        return

    script = formatter + """
console.log(JSON.stringify([
  formatFrenchDate("2027-01-22"),
  formatFrenchDate("2027-01-22T00:00:00Z"),
  formatFrenchDate("16/08/2026"),
  formatFrenchDate("31 décembre 2027"),
  formatFrenchDate("")
]));
"""
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == [
        "22/01/2027",
        "22/01/2027",
        "16/08/2026",
        "31 décembre 2027",
        "",
    ]


def test_print_waits_until_cnaps_lookup_has_finished():
    source = _template_source()

    assert 'id="btnPrintAdef"' in source
    assert "await adefCnapsValidityPromise;" in source
    assert source.index("await adefCnapsValidityPromise;") < source.index("window.print();")
