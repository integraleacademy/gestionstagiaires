import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BASE_TEMPLATE = ROOT / "templates" / "base.html"


def _open_convention_transmission_source() -> str:
    source = BASE_TEMPLATE.read_text(encoding="utf-8")
    start = source.index("  function openConventionTransmission(")
    end = source.index("\n  function openConventionPreview(", start)
    return source[start:end]


def _run_ssiap_price_case(
    *,
    combined: bool,
    existing_price: str = "",
    training_type: str = "SSIAP 1",
    modern_modal: bool = True,
) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js est requis pour exécuter le comportement JavaScript de la modale.")

    function_source = _open_convention_transmission_source()
    script = f"""
const functionSource = {json.dumps(function_source)};
const combined = {json.dumps(combined)};
const existingPrice = {json.dumps(existing_price)};
const trainingType = {json.dumps(training_type)};
const modernModal = {json.dumps(modern_modal)};
let promptOptions = null;
let nativePrompt = null;

const makeElement = () => ({{
  value: "",
  disabled: false,
  hidden: false,
  onclick: null,
  style: {{}},
  classList: {{ add() {{}}, remove() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  setAttribute() {{}},
  removeAttribute() {{}},
}});

const elements = {{
  conventionTransmissionModal: makeElement(),
  conventionTransmissionYes: makeElement(),
  conventionTransmissionNo: makeElement(),
  conventionTransmissionPreview: makeElement(),
  conventionTrainingPrice: makeElement(),
  conventionCpfAmount: makeElement(),
  conventionPersonalAmount: makeElement(),
  conventionOtherAmount: makeElement(),
  conventionFinanceError: makeElement(),
}};

global.document = {{ getElementById: (id) => elements[id] || null }};
global.window = {{
  confirm: (message) => {{ nativePrompt = message; return combined; }},
}};
if (modernModal) {{
  window.AppModal = {{
    confirm: async (options) => {{ promptOptions = options; return combined; }},
  }};
}}
global.openModal = () => {{}};
global.closeModal = () => {{}};
eval(functionSource);

(async () => {{
  const pending = openConventionTransmission({{
    trainingType,
    defaults: {{
      training_price: existingPrice,
      cpf_amount: "",
      personal_amount: "",
      other_amount: "",
    }},
  }});
  await new Promise((resolve) => setImmediate(resolve));
  elements.conventionTransmissionNo.onclick();
  const payload = await pending;
  process.stdout.write(JSON.stringify({{ payload, promptOptions, nativePrompt }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_ssiap_combined_option_applies_1230_euros_and_names_aps():
    result = _run_ssiap_price_case(combined=True)

    assert result["payload"]["training_price"] == "1230"
    assert result["promptOptions"]["primaryText"] == "Avec APS — 1 230 €"
    assert "combinée avec l’APS" in result["promptOptions"]["message"]


def test_ssiap_only_option_keeps_980_euros():
    result = _run_ssiap_price_case(combined=False)

    assert result["payload"]["training_price"] == "980"
    assert result["promptOptions"]["secondaryText"] == "SSIAP seul — 980 €"


def test_existing_ssiap_price_is_preserved_without_prompt():
    result = _run_ssiap_price_case(combined=True, existing_price="1110")

    assert result["payload"]["training_price"] == "1110"
    assert result["promptOptions"] is None


def test_native_fallback_names_aps_and_applies_1230_euros():
    result = _run_ssiap_price_case(combined=True, modern_modal=False)

    assert result["payload"]["training_price"] == "1230"
    assert "SSIAP + APS" in result["nativePrompt"]
    assert "1 230 €" in result["nativePrompt"]
    assert result["promptOptions"] is None


def test_non_ssiap_training_is_not_prompted_or_changed():
    result = _run_ssiap_price_case(combined=True, training_type="APS")

    assert result["payload"]["training_price"] == ""
    assert result["promptOptions"] is None
    assert result["nativePrompt"] is None
