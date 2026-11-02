"""Exercise the official documented form sequence via Chromium with entirely local responses."""
import json
import os

import pytest

from edof_declaration_form import SingleWrite, transmit
from edof_server_browser import API_PREFIX, DETAIL_PREFIX, EDOF_HOST
from test_edof_declarations import ENTRY, EXIT, FOLDER, ROW, prepare


PAGE = """
<html lang="fr"><meta charset="utf-8"><body><main></main><script>
const action=ACTION, folder=FOLDER, base=PREFIX;
let day="", rate=100;
const root=document.querySelector('main');
function paint(html){root.innerHTML=html}
function begin(){paint(action==="entry_training" ? '<button onclick="question()">Déclarer l’entrée en formation</button>' : '<button onclick="dateForm()">Déclarer la sortie de formation</button>')}
function question(){paint('<div role="dialog"><button onclick="dateForm()">Oui, continuer</button></div>')}
function dateForm(){paint('<label>Le stagiaire est '+(action==='entry_training'?'entré en formation le':'sorti de formation le')+'<input type="date"></label><button onclick="nextDate()">'+(action==="entry_training"?"Enregistrer":"Suivant")+'</button>')}
function nextDate(){day=root.querySelector('input').value;if(action==="entry_training"){send();return}paint('<button onclick="completion()">Déclarer le service fait</button>')}
function completion(){paint('<button onclick="saveForm(false)">Suivi intégralement</button><button onclick="saveForm(true)">Suivi partiellement</button>')}
function saveForm(part){paint((part?'<button onclick="choose(false)">Non, il n’y a pas de cas de force majeure</button><button onclick="choose(true)">Oui, du stagiaire</button><div id="partial"></div>':'')+'<button onclick="confirmForm()">Enregistrer</button>')}
function choose(force){document.querySelector('#partial').innerHTML=(force?'':'<label>Motif de sortie<select><option></option><option>Le stagiaire a été absent ou a abandonné sans force majeure.</option></select></label>')+'<label>Taux de réalisation<input type="number" oninput="rate=Number(this.value)"></label>'}
function confirmForm(){paint('<div role="dialog">Confirmez-vous votre déclaration ? Taux de réalisation '+rate+' % <button onclick="send()">Oui, enregistrer</button></div>')}
async function send(){await fetch(base+folder+(action==="entry_training"?"/in-training":"/service-done"),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({date:day,trainingCompletionRate:rate})});paint('<p>Déclaration prise en compte</p>')}
begin();
</script></body></html>
"""


@pytest.mark.parametrize("draft", [ENTRY, EXIT, {**EXIT, "rate": 100, "motif": ""}, {**EXIT, "motif": "trainee_force"}])
def test_isolated_chromium_form_to_receipt(tmp_path, draft):
    pw = pytest.importorskip("playwright.sync_api")
    spec = prepare(tmp_path, draft)
    origin = "https://"+EDOF_HOST
    entry = draft["action"] == "entry_training"
    fields = {**ROW, "state": "accepted" if entry else "inTraining", "start_date": "2026-01-02"}
    outcome = {}
    gate = SingleWrite(spec, EDOF_HOST, API_PREFIX, tmp_path)
    html = PAGE.replace("ACTION", json.dumps(draft["action"])).replace(
        "FOLDER", json.dumps(FOLDER)).replace("PREFIX", json.dumps(origin+API_PREFIX))
    with pw.sync_playwright() as runner:
        executable = os.environ.get("EDOF_TEST_CHROMIUM")
        if not executable and not os.path.exists(runner.chromium.executable_path):
            pytest.skip("Chromium is not installed")
        browser = runner.chromium.launch(executable_path=executable, args=[
                                         "--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(locale="fr-FR", service_workers="block")
        page = context.new_page()

        def local(route):
            request = route.request
            if request.resource_type == "document":
                route.fulfill(status=200, content_type="text/html", body=html)
            elif request.method == "PUT" and gate.allows(request):
                payload = request.post_data_json
                assert payload["date"] == draft["actual_date"]
                outcome.update(fields, state="inTraining" if entry else "serviceDoneDeclared")
                outcome["start_date" if entry else "end_date"] = payload["date"]
                outcome["completion_rate"] = str(payload["trainingCompletionRate"])
                route.fulfill(status=200, content_type="application/json", body="{}")
            else:
                route.abort()
        context.route("**/*", local)
        page.on("response", gate.observe)
        page.goto(DETAIL_PREFIX+FOLDER)
        result = transmit(page, spec, fields, gate, lambda: outcome)
        assert result["code"] == "declaration_confirmed", (page.locator("body").inner_text(),gate.sent,gate.rejected)
        assert gate.sent and gate.response_status == 200
        browser.close()
