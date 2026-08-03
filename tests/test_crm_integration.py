import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from unittest import mock

import app as gestion_app


class CrmIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_file = gestion_app.DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR
        gestion_app.DATA_FILE = os.path.join(self.temp_dir.name, "data.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        os.makedirs(gestion_app.BACKUP_DIR)
        self.payload = {
            "source": "integrale-connect-crm", "crm_contact_id": "contact-42",
            "prenom": "Lina", "nom": "Martin", "email": "lina@example.com",
            "telephone": "0600000000", "formation": "APS", "parcours": "",
            "centre": "Paris", "session": "Du 1 au 5 septembre 2026", "commentaires": "Note CRM interne",
        }
        data = gestion_app._empty_data_payload()
        data["sessions"] = [{
            "id": "session-1", "name": self.payload["session"], "training_type": "APS",
            "crm_center": "Paris", "partner_id": gestion_app.INTEGRALE_PARTNER_ID, "trainees": [],
        }]
        self.write(data)
        self.client = gestion_app.app.test_client()
        self.env = mock.patch.dict(os.environ, {"CRM_INTEGRATION_API_TOKEN": "secret-token"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        gestion_app.DATA_FILE = self.original_data_file
        gestion_app.BACKUP_DIR = self.original_backup_dir
        self.temp_dir.cleanup()

    def read(self):
        with open(gestion_app.DATA_FILE, encoding="utf-8") as handle:
            return json.load(handle)

    def write(self, data):
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def prepare(self, payload=None, token="secret-token"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.post("/api/integrations/crm/stagiaires", json=payload or self.payload, headers=headers)

    def transfer_id(self, response):
        return parse_qs(urlparse(response.get_json()["url"]).query)["crm_prefill"][0]

    def login(self):
        with self.client.session_transaction() as admin_session:
            admin_session["admin_logged_in"] = True
            admin_session["admin_role"] = "admin"
            admin_session["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID

    def test_token_is_required(self):
        self.assertEqual(self.prepare(token=None).status_code, 401)
        self.assertEqual(self.prepare(token="wrong").status_code, 401)

    def test_preparation_creates_no_trainee_and_url_contains_no_personal_data(self):
        response = self.prepare()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.read()["sessions"][0]["trainees"], [])
        url = response.get_json()["url"]
        self.assertTrue(url.startswith("https://gestionstagiaires-r5no.onrender.com/admin/sessions?crm_prefill="))
        for personal_value in ("Lina", "Martin", "lina@example.com", "0600000000", "contact-42"):
            self.assertNotIn(personal_value, url)
        self.assertGreaterEqual(len(self.transfer_id(response)), 40)

    def test_page_opens_existing_modal_and_prefills_every_field_and_exact_session(self):
        transfer_id = self.transfer_id(self.prepare())
        self.login()
        html = self.client.get(f"/admin/sessions?crm_prefill={transfer_id}").get_data(as_text=True)
        self.assertIn('id="createTraineeFromSessionsModal"', html)
        self.assertIn("initializeTraineeCreateFromSessions();", html)
        self.assertIn("openModal(\"createTraineeFromSessionsModal\")", html)
        for field_id in ("sessionTLastName", "sessionTFirstName", "sessionTEmail", "sessionTPhone"):
            self.assertIn(field_id, html)
        self.assertIn('"matched_session_id": "session-1"', html)
        self.assertIn('"training_type": "APS"', html)
        self.assertIn("select.value = targetId", html)

    def test_prefill_waits_for_dom_and_open_modal_then_runs_once(self):
        template = Path("templates/admin_sessions.html").read_text(encoding="utf-8")
        apply_start = template.index("  function applyCrmPrefillFromSessions(){")
        apply_end = template.index("\n\n  document.querySelectorAll", apply_start)
        start = template.index("  function startCrmPrefillWhenReady(){")
        end = template.index("\n\n  const importFromSessionsBtn", start)
        javascript = template[apply_start:apply_end] + "\n" + template[start:end]

        script = r'''
const vm = require("vm");
const source = process.argv[1];
const listeners = {};
const timers = [];
const elements = {};
for (const id of ["crmPrefillStatus", "sessionTLastName", "sessionTFirstName", "sessionTEmail", "sessionTPhone"])
  elements[id] = {value: "", style: {}};
elements.traineeTargetSession = {
  value: "", disabled: true, options: [], innerHTML: "",
  add(option){ this.options.push(option); }
};
const context = {
  crmPrefillRequested: true,
  crmPrefillTransfer: {
    payload: {nom: "Martin", prenom: "Lina", email: "lina@example.com", telephone: "0600000000"},
    training_type: "APS", matched_session_id: "session-1"
  },
  availableSessionsForCreate: [{id: "session-1", name: "Septembre", training_type: "APS"}],
  selectedTrainingForCreate: "",
  initializeTraineeCreateFromSessions(){}, refreshTrainingButtons(){},
  refreshVtcRealTrainingDatesVisibility(){}, refreshSessionChoices(){},
  sessionDisplayName(session){ return session.name; },
  Option: function(text, value){ this.text = text; this.value = value; },
  document: {
    readyState: "loading",
    addEventListener(name, callback, options){ listeners[name] = {callback, options}; },
    getElementById(id){ return elements[id] || null; }
  },
  window: {setTimeout(callback, delay){ timers.push({callback, delay}); }}
};
vm.createContext(context);
vm.runInContext(source, context);
if (!listeners.DOMContentLoaded || listeners.DOMContentLoaded.options.once !== true)
  throw new Error("DOMContentLoaded must be registered once");
if (elements.sessionTLastName.value) throw new Error("prefill ran before DOMContentLoaded");
listeners.DOMContentLoaded.callback();
if (timers.length !== 1 || timers[0].delay !== 50)
  throw new Error("openModal readiness retry was not scheduled");
let opened = 0;
context.window.openModal = id => {
  if (id !== "createTraineeFromSessionsModal") throw new Error(`unexpected modal ${id}`);
  opened += 1;
};
context.openModal = context.window.openModal;
timers.shift().callback();
if (opened !== 1) throw new Error(`modal opened ${opened} times`);
if (timers.length) throw new Error("a retry remained after successful prefill");
if (elements.sessionTLastName.value !== "Martin" || elements.sessionTFirstName.value !== "Lina" ||
    elements.sessionTEmail.value !== "lina@example.com" || elements.sessionTPhone.value !== "0600000000")
  throw new Error("CRM fields were not prefilled");
if (context.selectedTrainingForCreate !== "APS") throw new Error("training was not selected");
if (elements.traineeTargetSession.value !== "session-1" || elements.traineeTargetSession.disabled)
  throw new Error("session was not selected");
'''
        subprocess.run(["node", "-e", script, javascript], check=True, cwd=Path.cwd())

    def test_unknown_session_still_opens_modal_without_random_selection(self):
        response = self.prepare(dict(self.payload, session="Session inexistante"))
        transfer_id = self.transfer_id(response)
        transfer = self.read()["crm_prefill_transfers"][0]
        self.assertEqual(transfer["matched_session_id"], "")
        self.login()
        html = self.client.get(f"/admin/sessions?crm_prefill={transfer_id}").get_data(as_text=True)
        self.assertIn("Session correspondante introuvable", html)
        self.assertIn('select.value = ""', html)
        self.assertIn("openModal(\"createTraineeFromSessionsModal\")", html)

    def test_expired_transfer_is_not_prefilled(self):
        transfer_id = self.transfer_id(self.prepare())
        data = self.read()
        data["crm_prefill_transfers"][0]["expires_at"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)).isoformat()
        self.write(data)
        self.login()
        html = self.client.get(f"/admin/sessions?crm_prefill={transfer_id}").get_data(as_text=True)
        self.assertIn("Ce transfert CRM est introuvable ou a expiré.", html)
        self.assertEqual(self.read()["crm_prefill_transfers"], [])

    def test_save_preserves_crm_metadata_comment_and_consumes_transfer(self):
        transfer_id = self.transfer_id(self.prepare())
        self.login()
        response = self.client.post("/api/sessions/session-1/trainees/create", json={
            "last_name": "Martin", "first_name": "Lina", "email": "lina@example.com",
            "phone": "0600000000", "crm_prefill": transfer_id, "send_access": False,
        })
        self.assertEqual(response.status_code, 200)
        data = self.read()
        trainee = data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["crm_contact_id"], "contact-42")
        self.assertEqual(trainee["comment"], "Note CRM interne")
        self.assertEqual(data["crm_prefill_transfers"], [])
        repeated = self.client.post("/api/sessions/session-1/trainees/create", json={
            "last_name": "Martin", "first_name": "Lina", "crm_prefill": transfer_id, "send_access": False,
        })
        self.assertEqual(repeated.status_code, 410)

    def test_login_redirect_preserves_crm_prefill(self):
        response = self.prepare()
        transfer_id = self.transfer_id(response)
        redirect_response = self.client.get(f"/admin/sessions?crm_prefill={transfer_id}")
        self.assertEqual(redirect_response.status_code, 302)
        location = redirect_response.headers["Location"]
        self.assertIn("next=/admin/sessions?crm_prefill%3D", location)
        self.assertIn(transfer_id, location)

    def test_crm_training_mapping(self):
        cases = [("APS", "", "APS"), ("A3P", "", "A3P"), ("SSIAP 1", "", "SSIAP"),
                 ("DESP", "INITIAL", "DIRIGEANT initial"), ("DESP", "VAE", "DIRIGEANT VAE"),
                 ("Chauffeur VTC", "", "VTC")]
        for formation, parcours, expected in cases:
            with self.subTest(formation=formation, parcours=parcours):
                response = self.prepare(dict(self.payload, formation=formation, parcours=parcours))
                self.assertEqual(response.status_code, 201)
                self.assertEqual(self.read()["crm_prefill_transfers"][-1]["training_type"], expected)


if __name__ == "__main__":
    unittest.main()
