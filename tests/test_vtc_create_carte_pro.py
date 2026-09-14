import subprocess
import unittest
from pathlib import Path

import app as gestion_app


class VtcCreateCarteProTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_fetch_cnaps = gestion_app.fetch_cnapsv3_tracking_requests
        self.data = {
            "sessions": [
                {
                    "id": "S-VTC",
                    "name": "Session VTC",
                    "training_type": "VTC",
                    "date_start": "2026-10-01",
                    "date_end": "2026-10-05",
                    "trainees": [],
                },
                {
                    "id": "S-APS",
                    "name": "Session APS",
                    "training_type": "APS",
                    "date_start": "2026-10-01",
                    "date_end": "2026-10-30",
                    "trainees": [],
                },
            ]
        }
        gestion_app.load_data = lambda: self.data
        gestion_app.save_data = lambda payload: None
        gestion_app.fetch_cnapsv3_tracking_requests = lambda: ([], None)
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app.fetch_cnapsv3_tracking_requests = self.original_fetch_cnaps

    def test_vtc_session_create_form_omits_carte_professionnelle(self):
        vtc_html = self.client.get("/admin/sessions/S-VTC/trainees").get_data(as_text=True)
        aps_html = self.client.get("/admin/sessions/S-APS/trainees").get_data(as_text=True)

        self.assertNotIn('id="tCarteProOk"', vtc_html)
        self.assertIn('id="tCarteProOk"', aps_html)
        self.assertIn("Dates réelles de formation VTC", vtc_html)

    def test_global_create_form_resets_and_disables_carte_pro_for_vtc(self):
        html = self.client.get("/admin/sessions").get_data(as_text=True)

        self.assertIn('id="sessionCarteProField"', html)
        self.assertIn('const isVtc = selectedTrainingForCreate === "VTC";', html)
        self.assertIn('carteProField.style.display = isVtc ? "none" : "flex";', html)
        self.assertIn("if(isVtc) carteProInput.checked = false;", html)
        self.assertIn("carteProInput.disabled = isVtc;", html)
        self.assertIn(
            'selectedTrainingForCreate = normalizeTrainingChoice(crmPrefillTransfer.training_type || "");',
            html,
        )

    def test_global_create_form_executes_vtc_then_non_vtc_visibility(self):
        template = Path("templates/admin_sessions.html").read_text(encoding="utf-8")
        normalize_start = template.index("  function normalizeTrainingChoice(value){")
        normalize_end = template.index("\n\n  function closeQuickCreateMenu", normalize_start)
        refresh_start = template.index("  function refreshTrainingSpecificFields(){")
        refresh_end = template.index("\n\n  function refreshSessionChoices", refresh_start)
        javascript = template[normalize_start:normalize_end] + "\n" + template[refresh_start:refresh_end]

        script = r'''
const vm = require("vm");
const source = process.argv[1];
const elements = {
  sessionVtcRealTrainingDatesField: {style: {}},
  sessionTVtcRealTrainingDates: {value: "10/05/2026 au 12/05/2026"},
  sessionCarteProField: {
    style: {}, attributes: {},
    setAttribute(name, value){ this.attributes[name] = value; }
  },
  sessionTCarteProOk: {checked: true, disabled: false}
};
const context = {
  selectedTrainingForCreate: "Chauffeur VTC",
  document: {getElementById(id){ return elements[id] || null; }}
};
vm.createContext(context);
vm.runInContext(source, context);
context.selectedTrainingForCreate = context.normalizeTrainingChoice(context.selectedTrainingForCreate);
context.refreshTrainingSpecificFields();
if (context.selectedTrainingForCreate !== "VTC") throw new Error("VTC label was not normalized");
if (elements.sessionVtcRealTrainingDatesField.style.display !== "block")
  throw new Error("VTC dates were hidden");
if (elements.sessionTVtcRealTrainingDates.value !== "10/05/2026 au 12/05/2026")
  throw new Error("VTC dates were cleared");
if (elements.sessionCarteProField.style.display !== "none" ||
    elements.sessionCarteProField.attributes["aria-hidden"] !== "true")
  throw new Error("carte pro field was not hidden for VTC");
if (elements.sessionTCarteProOk.checked || !elements.sessionTCarteProOk.disabled)
  throw new Error("carte pro input was not reset and disabled for VTC");

context.selectedTrainingForCreate = "APS";
context.refreshTrainingSpecificFields();
if (elements.sessionVtcRealTrainingDatesField.style.display !== "none" ||
    elements.sessionTVtcRealTrainingDates.value !== "")
  throw new Error("VTC dates were not reset outside VTC");
if (elements.sessionCarteProField.style.display !== "flex" ||
    elements.sessionCarteProField.attributes["aria-hidden"] !== "false" ||
    elements.sessionTCarteProOk.disabled)
  throw new Error("carte pro field was not restored outside VTC");
'''
        subprocess.run(["node", "-e", script, javascript], check=True, cwd=Path.cwd())

    def test_api_ignores_carte_pro_for_vtc_but_keeps_it_for_aps(self):
        vtc_response = self.client.post(
            "/api/sessions/S-VTC/trainees/create",
            json={"last_name": "Test", "first_name": "Vtc", "carte_pro_ok": True, "send_access": False},
        )
        aps_response = self.client.post(
            "/api/sessions/S-APS/trainees/create",
            json={"last_name": "Test", "first_name": "Aps", "carte_pro_ok": True, "send_access": False},
        )

        self.assertEqual(vtc_response.status_code, 200)
        self.assertEqual(aps_response.status_code, 200)
        self.assertEqual(self.data["sessions"][0]["trainees"][0]["cnaps"], "INCONNU")
        self.assertEqual(self.data["sessions"][1]["trainees"][0]["cnaps"], "CARTE PROFESSIONNELLE OK")


if __name__ == "__main__":
    unittest.main()
