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
        self.original_vae_data_file = gestion_app.VAE_DATA_FILE
        gestion_app.DATA_FILE = os.path.join(self.temp_dir.name, "data.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        gestion_app.VAE_DATA_FILE = os.path.join(self.temp_dir.name, "data_vae.json")
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
        gestion_app.VAE_DATA_FILE = self.original_vae_data_file
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

    def lookup(self, crm_contact_id="contact-42", token="secret-token"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        query = {} if crm_contact_id is None else {"crm_contact_id": crm_contact_id}
        return self.client.get("/api/integrations/crm/stagiaires", query_string=query, headers=headers)

    def link_existing(self, payload=None, token="secret-token"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        link_payload = payload or {
            "crm_contact_id": "contact-new", "prenom": "Lina", "nom": "Martin",
            "email": "lina@example.com", "telephone": "0600000000",
            "source": "integrale_connect",
        }
        return self.client.post(
            "/api/integrations/crm/stagiaires/link-existing", json=link_payload, headers=headers,
        )

    def add_unlinked_trainee(self, trainee_id="trainee-manual", **overrides):
        values = {
            "id": trainee_id, "first_name": "Lina", "last_name": "Martin",
            "email": "lina@example.com", "phone": "0600000000", "cnaps_history": [],
        }
        values.update(overrides)
        data = self.read()
        data["sessions"][0].update({"date_start": "2026-09-01", "training_type": "DIRIGEANT VAE"})
        data["sessions"][0]["trainees"].append(values)
        self.write(data)
        return values

    def add_trainee(self, **overrides):
        data = self.read()
        trainee = {
            "id": "trainee-1", "crm_contact_id": "contact-42", "first_name": "Lina",
            "last_name": "Martin", "cnaps": "TRANSMIS", "cnaps_history": [],
            "nub": "1000731",
        }
        trainee.update(overrides)
        data["sessions"][0].update({"date_start": "2026-09-01"})
        data["sessions"][0]["trainees"].append(trainee)
        self.write(data)
        return trainee

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

    def test_lookup_uses_same_authentication_and_requires_contact_id(self):
        self.assertEqual(self.lookup(token=None).status_code, 401)
        self.assertEqual(self.lookup(token="wrong").status_code, 401)
        self.assertEqual(self.lookup(crm_contact_id=None).status_code, 400)

    def test_link_existing_requires_valid_bearer(self):
        self.assertEqual(self.link_existing(token=None).status_code, 401)
        self.assertEqual(self.link_existing(token="wrong").status_code, 401)

    def test_link_existing_by_exact_email_preserves_data_and_vae_fields(self):
        self.add_unlinked_trainee(
            email=" Lina.Example@Example.com ", phone="", custom_data={"keep": True},
            vae_status="livret_2_analysis", vae_jury_date="2026-10-12",
            vae_action_dates={"livret_1_received": "2026-01-02"}, crm_source="",
        )
        payload = {
            "crm_contact_id": "new-42", "prenom": "Lína", "nom": "MARTIN",
            "email": "lina.example@example.com", "telephone": "", "source": "integrale_connect",
        }
        before = self.read()["sessions"][0]["trainees"][0]
        response = self.link_existing(payload)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["link_created"])
        self.assertTrue(body["vae"]["applicable"])
        self.assertEqual(body["vae"]["status_code"], "livret_2_analysis")
        after = self.read()["sessions"][0]["trainees"][0]
        for key in ("email", "phone", "custom_data", "vae_status", "vae_jury_date", "vae_action_dates"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(after["crm_contact_id"], "new-42")
        self.assertEqual(after["crm_source"], "integrale_connect")
        self.assertEqual(after["activity_history"][0]["label"], "Liaison avec la piste CRM créée")
        self.assertNotIn("secret-token", json.dumps(body))

    def test_link_existing_by_phone_and_normalizes_french_prefix(self):
        self.add_unlinked_trainee(email="", phone="06 12 34 56 78")
        payload = {
            "crm_contact_id": "phone-42", "prenom": "Lina", "nom": "Martin",
            "email": "", "telephone": "+33 6 12 34 56 78",
        }
        response = self.link_existing(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.read()["sessions"][0]["trainees"][0]["crm_contact_id"], "phone-42")

    def test_link_existing_checks_identity(self):
        self.add_unlinked_trainee()
        payload = {
            "crm_contact_id": "new-42", "prenom": "Autre", "nom": "Martin",
            "email": "lina@example.com", "telephone": "",
        }
        response = self.link_existing(payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["reason"], "identity_mismatch")
        self.assertNotIn("crm_contact_id", self.read()["sessions"][0]["trainees"][0])

    def test_link_existing_not_found(self):
        response = self.link_existing()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["reason"], "trainee_not_found")

    def test_link_existing_rejects_ambiguous_email(self):
        self.add_unlinked_trainee()
        self.add_unlinked_trainee("trainee-manual-2")
        response = self.link_existing({
            "crm_contact_id": "new-42", "prenom": "Lina", "nom": "Martin",
            "email": "lina@example.com", "telephone": "",
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["reason"], "ambiguous_match")
        self.assertTrue(all(not trainee.get("crm_contact_id") for trainee in self.read()["sessions"][0]["trainees"]))

    def test_link_existing_rejects_conflicting_email_and_phone(self):
        self.add_unlinked_trainee(phone="0611111111")
        self.add_unlinked_trainee("trainee-manual-2", email="other@example.com", phone="0600000000")
        response = self.link_existing()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["reason"], "conflicting_matches")

    def test_link_existing_rejects_used_contact_id_and_already_linked_trainee(self):
        self.add_unlinked_trainee(crm_contact_id="used-by-this-record")
        response = self.link_existing()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["reason"], "trainee_already_linked")

        data = self.read()
        data["sessions"][0]["trainees"][0].update({
            "first_name": "Other", "email": "other@example.com", "phone": "0611111111",
            "crm_contact_id": "contact-new",
        })
        data["sessions"][0]["trainees"].append({
            "id": "target", "first_name": "Lina", "last_name": "Martin",
            "email": "lina@example.com", "phone": "0600000000",
        })
        self.write(data)
        response = self.link_existing()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["reason"], "crm_contact_id_already_used")

    def test_link_existing_is_idempotent_and_get_finds_complete_vae(self):
        self.add_unlinked_trainee(vae_status="jury", vae_jury_date="2026-11-03")
        first = self.link_existing()
        second = self.link_existing()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.get_json()["link_created"])
        trainee = self.read()["sessions"][0]["trainees"][0]
        self.assertEqual(len(trainee["activity_history"]), 1)
        fetched = self.lookup("contact-new")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.get_json()["vae"], second.get_json()["vae"])
        self.assertEqual(fetched.get_json()["vae"]["jury"]["date"], "2026-11-03")

    def test_link_existing_isolated_to_integrale_partner(self):
        self.add_unlinked_trainee()
        data = self.read()
        data["sessions"][0]["partner_id"] = "other-partner"
        self.write(data)
        response = self.link_existing()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["reason"], "trainee_not_found")

    def test_lookup_returns_linked_trainee_and_regulatory_data_without_nub(self):
        self.add_trainee(cnaps="STATUT PERSONNALISÉ")
        annuaire = {
            "check_status": "success", "checked_at": "2026-08-03T12:00:00+00:00", "message": None,
            "titles": [{
                "code": "CP SH", "label": "Carte professionnelle - Surveillance humaine ou gardiennage",
                "status": "ACTIF", "valid_until": "2031-06-30",
            }],
        }
        with mock.patch.object(gestion_app, "fetch_cnaps_public_annuaire", return_value=annuaire) as fetch:
            response = self.lookup()
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["cnaps"]["status"], "STATUT PERSONNALISÉ")
        self.assertEqual(body["trainee"], {
            "id": "trainee-1",
            "url": "https://gestionstagiaires-r5no.onrender.com/stagiaires/trainee-1",
            "session_name": self.payload["session"], "session_start": "2026-09-01",
        })
        self.assertEqual(body["card_pro"]["titles"][0]["display_status"], "CP SH ACTIF")
        self.assertNotIn("nub", json.dumps(body).lower())
        self.assertNotIn("pre_number", body["card_pro"])
        self.assertEqual(body["vae"], {"applicable": False})
        fetch.assert_called_once_with("Martin", "1000731")

    def test_vae_without_dossier_returns_operational_status(self):
        data = self.read()
        data["sessions"][0]["training_type"] = "DIRIGEANT VAE"
        self.write(data)
        self.add_trainee(nub="", vae_status="livret_2_analysis")
        body = self.lookup().get_json()["vae"]
        self.assertTrue(body["applicable"])
        self.assertEqual((body["status_code"], body["status_label"], body["progress_percent"]),
                         ("livret_2_analysis", "Réception livret 2", 65))
        self.assertEqual(body["next_action"]["code"], "analyse_livret_2")
        self.assertEqual(body["dossier"], {
            "found": False, "id": None, "status_code": None, "status_label": None,
            "updated_at": None, "dossier_count": 0, "multiple_dossiers": False, "admin_url": None,
        })
        self.assertFalse(Path(gestion_app.VAE_DATA_FILE).exists(), "a GET request must not create data_vae.json")

    def test_all_canonical_statuses_and_legacy_alias_are_computed(self):
        expected = {
            "livret_1_todo": (10, "complete_livret_1"), "livret_1_analysis": (20, "analyse_livret_1"),
            "non_recevable": (20, None), "complement_requested": (20, "provide_complements"),
            "livret_1_validated": (30, "validate_financing"), "financement_validated": (40, "complete_livret_2"),
            "livret_2_todo": (50, "complete_livret_2"), "livret_2_analysis": (65, "analyse_livret_2"),
            "livret_2_validated": (75, "validate_livret_2_financing"),
            "financement_l2_validated": (85, "schedule_jury"), "jury": (95, "jury"), "certified": (100, None),
        }
        for status, (percent, action) in expected.items():
            with self.subTest(status=status):
                progress = gestion_app.get_vae_crm_progress(status)
                self.assertEqual(progress["progress_percent"], percent)
                result = gestion_app.get_vae_crm_next_action(status)
                self.assertEqual(result["code"] if result else None, action)
        self.assertTrue(gestion_app.get_vae_crm_progress("complement_requested")["is_blocked"])
        self.assertEqual(gestion_app.get_vae_crm_progress("non_recevable"), {
            "progress_percent": 20, "is_terminal": True, "is_success": False, "is_blocked": True,
        })
        self.assertEqual(gestion_app.get_vae_crm_progress("certification obtenue"), {
            "progress_percent": 100, "is_terminal": True, "is_success": True, "is_blocked": False,
        })

    def test_vae_dossier_is_safe_scoped_and_latest_is_selected(self):
        data = self.read()
        data["sessions"][0]["training_type"] = "DIRIGEANT VAE"
        self.write(data)
        self.add_trainee(nub="", vae_status="certified", vae_jury_date="2026-09-15",
                         vae_action_dates={"diplome_obtenu": "20/09/2026"},
                         deliverables={"attestation_recevabilite": "private-document-token"})
        dossiers = [
            {"id": "old", "statut_dossier": "soumis", "created_at": "2026-07-01T00:00:00Z",
             "meta": {"trainee_id": "trainee-1", "session_id": "session-1", "public_token": "secret"},
             "experiences": [{"description": "private prose"}]},
            {"id": "latest", "statut_dossier": "recevable", "updated_at": "2026-08-04T09:32:00+02:00",
             "meta": {"trainee_id": "trainee-1", "session_id": "session-1", "trainee_token": "secret"},
             "livret": "private content"},
            {"id": "other", "updated_at": "2027-01-01T00:00:00Z", "meta": {"trainee_id": "trainee-2"}},
            {"id": "other-session", "updated_at": "2028-01-01T00:00:00Z",
             "meta": {"trainee_id": "trainee-1", "session_id": "session-2"}},
        ]
        Path(gestion_app.VAE_DATA_FILE).write_text(json.dumps({"dossiers": dossiers}), encoding="utf-8")
        first = self.lookup().get_json()["vae"]
        second = self.lookup().get_json()["vae"]
        self.assertEqual(first["dossier"]["id"], "latest")
        self.assertEqual((first["dossier"]["dossier_count"], first["dossier"]["multiple_dossiers"]), (2, True))
        self.assertEqual(first["dossier"]["admin_url"],
                         "https://gestionstagiaires-r5no.onrender.com/admin/vae/latest")
        self.assertEqual(first["jury"], {"scheduled": True, "date": "2026-09-15", "location": None})
        self.assertEqual(first["final_result"], {"code": "certified", "label": "Diplôme obtenu",
                                                  "diploma_obtained_at": "20/09/2026"})
        self.assertEqual(first["updated_at"], "20/09/2026")
        self.assertEqual(first["updated_at"], second["updated_at"])
        serialized = json.dumps(first)
        for forbidden in ("public_token", "trainee_token", "private prose", "private content", "onrender.com/vae/latest"):
            self.assertNotIn(forbidden, serialized)

    def test_non_certified_has_no_fictitious_final_result_and_complements_are_blocked(self):
        data = self.read()
        data["sessions"][0]["training_type"] = "DIRIGEANT VAE"
        self.write(data)
        self.add_trainee(nub="", vae_status="complement_requested")
        vae = self.lookup().get_json()["vae"]
        self.assertEqual(vae["final_result"], {"code": None, "label": None, "diploma_obtained_at": None})
        self.assertEqual(vae["complements"], {"requested": True, "missing_items_supported": False,
                                               "missing_items_count": None, "missing_items": []})

    def test_lookup_is_limited_to_integrale_partner(self):
        self.add_trainee(nub="")
        data = self.read()
        data["sessions"][0]["partner_id"] = "another-partner"
        self.write(data)
        self.assertEqual(self.lookup().status_code, 404)

    def test_lookup_returns_not_found_and_duplicate(self):
        self.assertEqual(self.lookup().status_code, 404)
        self.add_trainee(nub="")
        data = self.read()
        data["sessions"].append({
            "id": "session-2", "name": "Autre", "date_start": "2026-10-01",
            "trainees": [{"id": "trainee-2", "crm_contact_id": "contact-42"}],
        })
        self.write(data)
        self.assertEqual(self.lookup().status_code, 409)

    def test_lookup_reports_missing_nub_without_calling_annuaire(self):
        self.add_trainee(nub="", cnaps_nub="", cnaps_tracking_nub="", pre_number="")
        with mock.patch.object(gestion_app, "fetch_cnaps_public_annuaire") as fetch:
            response = self.lookup()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["card_pro"]["check_status"], "missing_nub")
        self.assertEqual(response.get_json()["card_pro"]["titles"], [])
        fetch.assert_not_called()

    def test_lookup_flags_active_ap_sh_expiring_before_training(self):
        self.add_trainee(nub="", pre_number="PRE-2026-01-01-00001000731")
        annuaire = {"check_status": "success", "checked_at": "now", "message": None, "titles": [{
            "code": "AP SH", "label": "Autorisation préalable - Surveillance humaine ou gardiennage",
            "status": "ACTIF", "date_fin_validite": "2026-08-31",
        }]}
        with mock.patch.object(gestion_app, "fetch_cnaps_public_annuaire", return_value=annuaire):
            response = self.lookup()
        self.assertTrue(response.get_json()["card_pro"]["titles"][0]["expires_before_training"])

    def test_lookup_keeps_http_200_when_cnaps_annuaire_fails(self):
        self.add_trainee()
        failure = {"check_status": "error", "checked_at": "now", "message": "Vérification CNAPS impossible"}
        with mock.patch.object(gestion_app, "fetch_cnaps_public_annuaire", return_value=failure):
            response = self.lookup()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["cnaps"]["status"], "TRANSMIS")
        self.assertEqual(response.get_json()["card_pro"]["check_status"], "error")

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
