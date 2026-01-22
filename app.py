import os
import json
import uuid
import datetime
from typing import Dict, Any, List, Optional

import requests
from flask import Flask, request, redirect, url_for, jsonify, render_template_string, abort

app = Flask(__name__)

# =========================
# Persistent disk (Render)
# =========================
PERSIST_DIR = os.environ.get("PERSIST_DIR", "/data")
os.makedirs(PERSIST_DIR, exist_ok=True)
DATA_FILE = os.path.join(PERSIST_DIR, "data.json")

# =========================
# Brevo (Sendinblue) config
# =========================
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "ecole@integraleacademy.com")
BREVO_SENDER_NAME = os.environ.get("BREVO_SENDER_NAME", "Intégrale Academy")
CNAPS_LOOKUP_ENDPOINT = os.environ.get("CNAPS_LOOKUP_ENDPOINT", "")


# Placeholder: public student portal base URL (we'll build later)
PUBLIC_STUDENT_PORTAL_BASE = os.environ.get("PUBLIC_STUDENT_PORTAL_BASE", "https://example.com/espace-stagiaire")

# =========================
# External integrations (placeholders)
# =========================
# You will replace these with your Render URLs later
CNAPS_STATUS_ENDPOINT = os.environ.get("CNAPS_STATUS_ENDPOINT", "")         # e.g. https://xxx.onrender.com/api/cnaps_status?email=
HEBERGEMENT_STATUS_ENDPOINT = os.environ.get("HEBERGEMENT_STATUS_ENDPOINT", "")  # e.g. https://yyy.onrender.com/api/hebergement?email=


# =========================
# Data model helpers
# =========================

def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        base = {"sessions": []}
        save_data(base)
        return base
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Safety: if corrupted, keep a backup and reset minimal structure
        try:
            backup = DATA_FILE + ".corrupt." + str(int(datetime.datetime.utcnow().timestamp()))
            os.replace(DATA_FILE, backup)
        except Exception:
            pass
        base = {"sessions": []}
        save_data(base)
        return base


def save_data(data: Dict[str, Any]) -> None:
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def find_session(data: Dict[str, Any], session_id: str) -> Optional[Dict[str, Any]]:
    for s in data.get("sessions", []):
        if s.get("id") == session_id:
            return s
    return None


def find_stagiaire(session: Dict[str, Any], stagiaire_id: str) -> Optional[Dict[str, Any]]:
    for st in session.get("stagiaires", []):
        if st.get("id") == stagiaire_id:
            return st
    return None


# =========================
# Business rules (Conformité)
# =========================

def stagiaire_is_conforme(st: Dict[str, Any], formation_type: str) -> bool:
    """
    Definition (modifiable later):
    - convention == 'signée'
    - test_francais == 'validé'
    - dossier == 'complet'
    - financement == 'validé'
    - if formation_type == 'DIRIGEANT VAE': vae == 'validé'
    """
    if st.get("convention") != "signée":
        return False
    if st.get("test_francais") != "validé":
        return False
    if st.get("dossier") != "complet":
        return False
    if st.get("financement") != "validé":
        return False
    if formation_type == "DIRIGEANT VAE":
        if st.get("vae") != "validé":
            return False
    return True


def session_is_conforme(session: Dict[str, Any]) -> bool:
    formation_type = session.get("type_formation", "")
    stagiaires = session.get("stagiaires", [])
    if not stagiaires:
        return False
    return all(stagiaire_is_conforme(st, formation_type) for st in stagiaires)


def count_conformes(session: Dict[str, Any]) -> Dict[str, int]:
    formation_type = session.get("type_formation", "")
    stagiaires = session.get("stagiaires", [])
    conformes = sum(1 for st in stagiaires if stagiaire_is_conforme(st, formation_type))
    non_conformes = len(stagiaires) - conformes
    return {"conformes": conformes, "non_conformes": non_conformes}


# =========================
# Brevo Email + SMS
# =========================

def brevo_send_email(to_email: str, subject: str, html: str) -> bool:
    if not BREVO_API_KEY:
        return False
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }
    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=12)
        return r.status_code in (200, 201, 202)
    except Exception:
        return False


def brevo_send_sms(phone: str, message: str) -> bool:
    if not BREVO_API_KEY:
        return False
    # Brevo SMS endpoint
    url = "https://api.brevo.com/v3/transactionalSMS/sms"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }
    # Note: sender is optional; your Brevo account may require an approved sender
    payload = {
        "recipient": phone,
        "content": message,
        "type": "transactional",
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=12)
        return r.status_code in (200, 201, 202)
    except Exception:
        return False


def send_welcome_messages(stagiaire: Dict[str, Any], session: Dict[str, Any]) -> Dict[str, bool]:
    # Public portal link placeholder (we'll build later)
    # We'll attach a token-like id for later mapping
    portal_link = f"{PUBLIC_STUDENT_PORTAL_BASE}?id={stagiaire.get('id')}"

    formation_name = session.get("nom", "Votre formation")
    date_debut = session.get("date_debut", "xx")
    date_fin = session.get("date_fin", "xx")

    subject = f"Bienvenue à Intégrale Academy – Inscription {formation_name}"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        <h2 style="margin:0 0 10px 0">Bienvenue à Intégrale Academy 👋</h2>
        <p>Vous êtes bien inscrit(e) en formation <strong>{formation_name}</strong> prévue du <strong>{date_debut}</strong> au <strong>{date_fin}</strong>.</p>
        <p>Vous devez nous faire parvenir vos documents dès que possible afin de compléter votre dossier.</p>
        <p>
          Pour fournir vos documents, cliquez ici :
          <br>
          <a href="{portal_link}" style="display:inline-block;margin-top:8px;background:#1f8f4a;color:white;padding:10px 14px;border-radius:10px;text-decoration:none">
            Accéder à mon espace stagiaire
          </a>
        </p>
        <p style="margin-top:14px">Rassurez-vous : même si vous n’avez pas encore tous les documents, vous pouvez les envoyer au fur et à mesure.</p>
        <hr style="border:none;border-top:1px solid #eee;margin:16px 0">
        <p style="color:#666;font-size:13px;margin:0">Intégrale Academy</p>
      </div>
    </div>
    """

    sms = f"Intégrale Academy : bienvenue ! Vous êtes inscrit(e) à {formation_name} du {date_debut} au {date_fin}. Docs à transmettre : {portal_link}"

    ok_mail = brevo_send_email(stagiaire.get("email", ""), subject, html) if stagiaire.get("email") else False
    ok_sms = brevo_send_sms(stagiaire.get("telephone", ""), sms) if stagiaire.get("telephone") else False
    return {"email": ok_mail, "sms": ok_sms}


# =========================
# External status fetchers (optional)
# =========================

def fetch_cnaps_status(email: str) -> Optional[str]:
    if not CNAPS_STATUS_ENDPOINT:
        return None
    try:
        r = requests.get(CNAPS_STATUS_ENDPOINT, params={"email": email}, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        # Expecting: {"status": "..."}  (adapt later)
        return data.get("status")
    except Exception:
        return None


def fetch_hebergement_status(email: str) -> Optional[str]:
    if not HEBERGEMENT_STATUS_ENDPOINT:
        return None
    try:
        r = requests.get(HEBERGEMENT_STATUS_ENDPOINT, params={"email": email}, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        # Expecting: {"reserved": true/false} (adapt later)
        if data.get("reserved") is True:
            return "réservé"
        if data.get("reserved") is False:
            return "inconnu"
        return data.get("status")
    except Exception:
        return None

def fetch_cnaps_status_by_name(nom: str, prenom: str) -> Optional[str]:
    if not CNAPS_LOOKUP_ENDPOINT:
        return None
    try:
        r = requests.get(
            CNAPS_LOOKUP_ENDPOINT,
            params={"nom": nom, "prenom": prenom},
            timeout=10
        )
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("statut_cnaps") or data.get("status")
    except Exception:
        return None



# =========================
# UI helpers
# =========================

FORMATION_TYPES = ["APS", "A3P", "DIRIGEANT initial", "DIRIGEANT VAE", "SSIAP 1", "CHEF DE POSTE"]

CONVENTION_STATUSES = ["prochainement", "en cours de signature", "signée"]
TEST_FR_STATUSES = ["prochainement", "en cours", "validé", "relancé"]
DOSSIER_STATUSES = ["complet", "incomplet"]
FINANCEMENT_STATUSES = ["prochainement", "en cours de validation", "validé"]
VAE_STATUSES = ["prochainement", "en cours", "validé", "non concerné"]

def badge_class(value: str, col: str) -> str:
    # Simple mapping to CSS classes
    if col in ("convention",):
        return {"prochainement":"red","en cours de signature":"yellow","signée":"green"}.get(value, "gray")
    if col in ("test_francais",):
        return {"prochainement":"red","en cours":"yellow","validé":"green","relancé":"orange"}.get(value, "gray")
    if col in ("dossier",):
        return {"complet":"green","incomplet":"red"}.get(value, "gray")
    if col in ("financement",):
        return {"prochainement":"red","en cours de validation":"orange","validé":"green"}.get(value, "gray")
    if col in ("cnaps",):
        return "red" if value in ("inconnu", "", None) else "green"
    if col in ("hebergement",):
        return {"réservé":"green","inconnu":"black"}.get(value, "gray")
    if col in ("vae",):
        return {"validé":"green","en cours":"yellow","prochainement":"red","non concerné":"gray"}.get(value, "gray")
    return "gray"


# =========================
# Routes
# =========================

@app.get("/")
def home():
    return redirect(url_for("admin_sessions"))


@app.get("/admin/sessions")
def admin_sessions():
    data = load_data()
    sessions = data.get("sessions", [])
    # compute flags
    for s in sessions:
        s["_conforme"] = session_is_conforme(s)
        s["_counts"] = count_conformes(s)

    return render_template_string(TPL_ADMIN_SESSIONS, sessions=sessions, formation_types=FORMATION_TYPES)


@app.post("/admin/sessions/create")
def admin_sessions_create():
    data = load_data()
    payload = request.form
    nom = (payload.get("nom") or "").strip()
    date_debut = (payload.get("date_debut") or "").strip()
    date_fin = (payload.get("date_fin") or "").strip()
    date_examen = (payload.get("date_examen") or "").strip()
    type_formation = (payload.get("type_formation") or "").strip()

    if not nom or not type_formation:
        return redirect(url_for("admin_sessions"))

    session_id = uuid.uuid4().hex[:10]
    session = {
        "id": session_id,
        "nom": nom,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "date_examen": date_examen,
        "type_formation": type_formation,
        "created_at": _now_iso(),
        "stagiaires": []
    }
    data["sessions"].insert(0, session)
    save_data(data)
    return redirect(url_for("admin_sessions"))


@app.post("/admin/sessions/<session_id>/delete")
def admin_sessions_delete(session_id: str):
    data = load_data()
    data["sessions"] = [s for s in data.get("sessions", []) if s.get("id") != session_id]
    save_data(data)
    return redirect(url_for("admin_sessions"))


@app.get("/admin/sessions/<session_id>/stagiaires")
def admin_stagiaires(session_id: str):
    data = load_data()
    session = find_session(data, session_id)
    if not session:
        abort(404)

# refresh CNAPS / hebergement (optional, best-effort)
for st in session.get("stagiaires", []):
    nom = (st.get("nom") or "").strip()
    prenom = (st.get("prenom") or "").strip()

    # CNAPS par nom + prénom
    if nom and prenom:
        cn = fetch_cnaps_status_by_name(nom, prenom)
        st["cnaps"] = cn if cn else "INCONNU"
    else:
        st["cnaps"] = "INCONNU"

    # Hébergement uniquement pour A3P (on garde l’email)
    if session.get("type_formation") == "A3P":
        email = st.get("email", "")
        if email:
            hb = fetch_hebergement_status(email)
            st["hebergement"] = hb if hb else "inconnu"
        else:
            st["hebergement"] = "inconnu"
    else:
        st.pop("hebergement", None)

save_data(data)


    counts = count_conformes(session)
    conforme = session_is_conforme(session)

    return render_template_string(
        TPL_ADMIN_STAGIAIRES,
        session=session,
        counts=counts,
        session_conforme=conforme,
        badge_class=badge_class,
        convention_statuses=CONVENTION_STATUSES,
        test_fr_statuses=TEST_FR_STATUSES,
        dossier_statuses=DOSSIER_STATUSES,
        financement_statuses=FINANCEMENT_STATUSES,
        vae_statuses=VAE_STATUSES,
    )


@app.post("/admin/sessions/<session_id>/stagiaires/add")
def admin_stagiaires_add(session_id: str):
    data = load_data()
    session = find_session(data, session_id)
    if not session:
        abort(404)

    payload = request.form
    nom = (payload.get("nom") or "").strip()
    prenom = (payload.get("prenom") or "").strip()
    email = (payload.get("email") or "").strip()
    telephone = (payload.get("telephone") or "").strip()

    if not nom or not prenom:
        return redirect(url_for("admin_stagiaires", session_id=session_id))

    stagiaire_id = "STG-" + uuid.uuid4().hex[:8].upper()

    st = {
        "id": stagiaire_id,
        "nom": nom,
        "prenom": prenom,
        "email": email,
        "telephone": telephone,
        # defaults
        "convention": "prochainement",
        "test_francais": "prochainement",
        "dossier": "incomplet",
        "cnaps": "inconnu",
        "financement": "prochainement",
        "commentaire": "",
        # conditional:
        "vae": "prochainement" if session.get("type_formation") == "DIRIGEANT VAE" else "non concerné",
        "hebergement": "inconnu" if session.get("type_formation") == "A3P" else None,
        "created_at": _now_iso(),
    }

    session.setdefault("stagiaires", []).insert(0, st)
    save_data(data)

    # Send welcome messages (best-effort)
    send_welcome_messages(st, session)

    return redirect(url_for("admin_stagiaires", session_id=session_id))


# =========================
# Autosave API
# =========================

@app.post("/api/sessions/<session_id>/stagiaires/<stagiaire_id>/update")
def api_update_stagiaire(session_id: str, stagiaire_id: str):
    data = load_data()
    session = find_session(data, session_id)
    if not session:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    st = find_stagiaire(session, stagiaire_id)
    if not st:
        return jsonify({"ok": False, "error": "stagiaire_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    # allow only safe keys
    allowed = {"convention", "test_francais", "dossier", "financement", "commentaire", "vae", "cnaps"}

    for k, v in payload.items():
        if k in allowed:
            st[k] = v

    st["updated_at"] = _now_iso()
    save_data(data)
    return jsonify({"ok": True})


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "data_file": DATA_FILE})

@app.get("/api/cnaps_lookup")
def api_cnaps_lookup():
    nom = (request.args.get("nom") or "").strip()
    prenom = (request.args.get("prenom") or "").strip()

    if not nom or not prenom:
        return jsonify({"ok": False, "error": "missing_nom_or_prenom"}), 400

    status = fetch_cnaps_status_by_name(nom, prenom)
    if not status:
        status = "INCONNU"

    return jsonify({"ok": True, "nom": nom, "prenom": prenom, "statut_cnaps": status})



# =========================
# Templates (embedded, so you can deploy fast)
# You can split into templates/*.html later if you want
# =========================

BASE_CSS = """
<style>
  body{font-family:Arial, sans-serif;background:#f6f6f6;margin:0}
  .topbar{background:#0f3d2a;color:#fff;padding:14px 18px;display:flex;align-items:center;justify-content:space-between}
  .topbar a{color:#fff;text-decoration:none;font-weight:700}
  .container{max-width:1150px;margin:18px auto;padding:0 14px}
  .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
  .card{background:#fff;border-radius:14px;padding:14px;box-shadow:0 6px 18px rgba(0,0,0,.06);border:1px solid #eee}
  .muted{color:#666;font-size:13px}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  .btn{border:none;border-radius:10px;padding:10px 12px;font-weight:700;cursor:pointer}
  .btn-green{background:#1f8f4a;color:#fff}
  .btn-red{background:#d64545;color:#fff}
  .btn-gray{background:#eee}
  .btn-outline{background:#fff;border:1px solid #ddd}
  .pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:6px 10px;font-size:12px;font-weight:700}
  .b-red{background:#ffe3e3;color:#a40000}
  .b-yellow{background:#fff4cf;color:#7a5b00}
  .b-orange{background:#ffe8d1;color:#8a3d00}
  .b-green{background:#dff7e8;color:#0f6b31}
  .b-gray{background:#efefef;color:#444}
  .b-black{background:#eee;color:#111}
  .bigflag{font-size:34px;line-height:1}
  table{width:100%;border-collapse:separate;border-spacing:0 10px}
  th{font-size:12px;color:#666;text-align:left;padding:0 8px}
  td{background:#fff;padding:10px 8px;border-top:1px solid #eee;border-bottom:1px solid #eee}
  tr td:first-child{border-left:1px solid #eee;border-top-left-radius:12px;border-bottom-left-radius:12px}
  tr td:last-child{border-right:1px solid #eee;border-top-right-radius:12px;border-bottom-right-radius:12px}
  select,input[type="text"]{padding:8px;border-radius:10px;border:1px solid #ddd;width:100%;box-sizing:border-box}
  .highlight{outline:2px solid #ffcc00}
  .modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;align-items:center;justify-content:center;padding:14px;z-index:50}
  .modal{background:#fff;border-radius:16px;max-width:520px;width:100%;padding:16px;box-shadow:0 14px 40px rgba(0,0,0,.22)}
  .modal h3{margin:0 0 10px 0}
  .modal .row{margin-top:10px}
  .right{margin-left:auto}
  .notice{font-size:12px;color:#777}
</style>
"""

TPL_ADMIN_SESSIONS = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Admin Sessions</title>
  {BASE_CSS}
</head>
<body>
  <div class="topbar">
    <div><a href="/admin/sessions">Intégrale Academy • Admin Sessions</a></div>
    <button class="btn btn-green" onclick="openModal()">➕ Nouvelle session</button>
  </div>

  <div class="container">
    <div class="muted">Toutes les sessions apparaissent ici sous forme de cartes. ✅ = conforme, ❌ = non conforme.</div>
    <div style="height:12px"></div>

    <div class="grid">
      {{% for s in sessions %}}
      <div class="card">
        <div class="row">
          <div style="font-weight:800">{{{{ s.nom }}}}</div>
          <div class="right bigflag">{{{{ "✅" if s._conforme else "❌" }}}}</div>
        </div>
        <div class="muted" style="margin-top:6px">
          <div><strong>Type :</strong> {{{{ s.type_formation }}}}</div>
          <div><strong>Formation :</strong> {{{{ s.date_debut or "—" }}}} → {{{{ s.date_fin or "—" }}}}</div>
          <div><strong>Examen :</strong> {{{{ s.date_examen or "—" }}}}</div>
          <div><strong>Stagiaires :</strong> {{{{ (s.stagiaires|length) }}}} • Conformes: {{{{ s._counts.conformes }}}} • Non: {{{{ s._counts.non_conformes }}}}</div>
        </div>

        <div class="row" style="margin-top:12px">
          <form method="post" action="/admin/sessions/{{{{ s.id }}}}/delete" onsubmit="return confirm('Supprimer cette session ?')">
            <button class="btn btn-red" type="submit">🗑️ Supprimer</button>
          </form>
          <a class="btn btn-outline" href="/admin/sessions/{{{{ s.id }}}}/stagiaires" style="text-decoration:none;display:inline-block">👥 Voir les stagiaires</a>
        </div>
      </div>
      {{% endfor %}}
    </div>

    {{% if sessions|length == 0 %}}
      <div class="card" style="margin-top:14px">
        Aucune session pour l’instant. Clique sur <strong>Nouvelle session</strong>.
      </div>
    {{% endif %}}
  </div>

  <div class="modal-backdrop" id="modal">
    <div class="modal">
      <div class="row">
        <h3>Nouvelle session</h3>
        <button class="btn btn-gray right" onclick="closeModal()">✖</button>
      </div>

      <form method="post" action="/admin/sessions/create">
        <div class="row">
          <div style="flex:1">
            <div class="muted">Nom de la session</div>
            <input type="text" name="nom" required placeholder="ex : APS Janvier 2026">
          </div>
        </div>

        <div class="row">
          <div style="flex:1">
            <div class="muted">Date début</div>
            <input type="text" name="date_debut" placeholder="ex : 30/03/2026">
          </div>
          <div style="flex:1">
            <div class="muted">Date fin</div>
            <input type="text" name="date_fin" placeholder="ex : 02/06/2026">
          </div>
        </div>

        <div class="row">
          <div style="flex:1">
            <div class="muted">Date d’examen</div>
            <input type="text" name="date_examen" placeholder="ex : 03/06/2026">
          </div>
        </div>

        <div class="row">
          <div style="flex:1">
            <div class="muted">Type de formation</div>
            <select name="type_formation" required>
              <option value="">— Choisir —</option>
              {{% for t in formation_types %}}
                <option value="{{{{ t }}}}">{{{{ t }}}}</option>
              {{% endfor %}}
            </select>
          </div>
        </div>

        <div class="row" style="margin-top:14px">
          <button class="btn btn-green" type="submit">✅ Valider</button>
          <span class="notice">La session apparaîtra immédiatement sur la page.</span>
        </div>
      </form>
    </div>
  </div>

<script>
  function openModal() {{
    document.getElementById('modal').style.display = 'flex';
  }}
  function closeModal() {{
    document.getElementById('modal').style.display = 'none';
  }}
</script>

</body>
</html>
"""


TPL_ADMIN_STAGIAIRES = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Admin Stagiaires</title>
  {BASE_CSS}
</head>
<body>
  <div class="topbar">
    <div class="row" style="gap:14px">
      <a href="/admin/sessions">← Retour sessions</a>
      <div style="font-weight:800">{{{{ session.nom }}}}</div>
    </div>
    <button class="btn btn-green" onclick="openModal()">➕ Ajouter un stagiaire</button>
  </div>

  <div class="container">
    <div class="card">
      <div class="row">
        <div>
          <div class="muted"><strong>Formation :</strong> {{{{ session.type_formation }}}}</div>
          <div class="muted"><strong>Dates :</strong> {{{{ session.date_debut or "—" }}}} → {{{{ session.date_fin or "—" }}}}</div>
          <div class="muted"><strong>Examen :</strong> {{{{ session.date_examen or "—" }}}}</div>
          <div class="muted"><strong>Nombre stagiaires :</strong> {{{{ session.stagiaires|length }}}}</div>
        </div>

        <div class="right" style="text-align:right">
          <div style="font-weight:800;font-size:18px">
            Statut session : {{{{ "Conforme ✅" if session_conforme else "Non conforme ❌" }}}}
          </div>
          <div class="muted" style="margin-top:6px">
            Conformes : <strong>{{{{ counts.conformes }}}}</strong> • Non conformes : <strong>{{{{ counts.non_conformes }}}}</strong>
          </div>
        </div>
      </div>
    </div>

    <div style="height:14px"></div>

    <div class="card">
      <div style="font-weight:800;margin-bottom:10px">Stagiaires</div>

      <table>
        <thead>
          <tr>
            <th>Nom</th>
            <th>Prénom</th>
            <th>Mail</th>
            <th>Téléphone</th>
            <th>Convention</th>
            <th>Test FR</th>
            <th>Dossier</th>
            <th>CNAPS</th>
            {{% if session.type_formation == "A3P" %}}<th>Hébergement</th>{{% endif %}}
            <th>Commentaire</th>
            {{% if session.type_formation == "DIRIGEANT VAE" %}}<th>VAE</th>{{% endif %}}
            <th>Financement</th>
            <th>Fiche</th>
          </tr>
        </thead>

        <tbody>
          {{% for st in session.stagiaires %}}
          {{% set has_comment = (st.commentaire or "")|length > 0 %}}
          <tr class="{{{{ 'highlight' if has_comment else '' }}}}">
            <td><strong>{{{{ st.nom }}}}</strong></td>
            <td>{{{{ st.prenom }}}}</td>
            <td>{{{{ st.email or '' }}}}</td>
            <td>{{{{ st.telephone or '' }}}}</td>

            <td>
              <select onchange="autosave('{{{{ st.id }}}}', 'convention', this.value)">
                {{% for v in convention_statuses %}}
                  <option value="{{{{ v }}}}" {{% if st.convention == v %}}selected{{% endif %}}>{{{{ v }}}}</option>
                {{% endfor %}}
              </select>
              <div class="pill b-{{{{ badge_class(st.convention, 'convention') }}}}" style="margin-top:6px">{{{{ st.convention }}}}</div>
            </td>

            <td>
              <select onchange="autosave('{{{{ st.id }}}}', 'test_francais', this.value)">
                {{% for v in test_fr_statuses %}}
                  <option value="{{{{ v }}}}" {{% if st.test_francais == v %}}selected{{% endif %}}>{{{{ v }}}}</option>
                {{% endfor %}}
              </select>
              <div class="pill b-{{{{ badge_class(st.test_francais, 'test_francais') }}}}" style="margin-top:6px">{{{{ st.test_francais }}}}</div>
            </td>

            <td>
              <select onchange="autosave('{{{{ st.id }}}}', 'dossier', this.value)">
                {{% for v in dossier_statuses %}}
                  <option value="{{{{ v }}}}" {{% if st.dossier == v %}}selected{{% endif %}}>{{{{ v }}}}</option>
                {{% endfor %}}
              </select>
              <div class="pill b-{{{{ badge_class(st.dossier, 'dossier') }}}}" style="margin-top:6px">{{{{ st.dossier }}}}</div>
            </td>

            <td>
              {{% set cn = st.cnaps if st.cnaps else "inconnu" %}}
              <div class="pill b-{{{{ badge_class(cn, 'cnaps') }}}}">{{{{ cn }}}}</div>
            </td>

            {{% if session.type_formation == "A3P" %}}
            <td>
              {{% set hb = st.hebergement if st.hebergement else "inconnu" %}}
              <div class="pill b-{{{{ badge_class(hb, 'hebergement') }}}}">{{{{ hb }}}}</div>
            </td>
            {{% endif %}}

            <td>
              <input type="text" value="{{{{ st.commentaire or '' }}}}" placeholder="Ajouter un commentaire…"
                     oninput="debouncedSave('{{{{ st.id }}}}', 'commentaire', this.value)">
              {{% if has_comment %}}
                <div class="muted" style="margin-top:6px">⚠️ Commentaire présent</div>
              {{% endif %}}
            </td>

            {{% if session.type_formation == "DIRIGEANT VAE" %}}
            <td>
              <select onchange="autosave('{{{{ st.id }}}}', 'vae', this.value)">
                {{% for v in vae_statuses %}}
                  <option value="{{{{ v }}}}" {{% if st.vae == v %}}selected{{% endif %}}>{{{{ v }}}}</option>
                {{% endfor %}}
              </select>
              <div class="pill b-{{{{ badge_class(st.vae, 'vae') }}}}" style="margin-top:6px">{{{{ st.vae }}}}</div>
            </td>
            {{% endif %}}

            <td>
              <select onchange="autosave('{{{{ st.id }}}}', 'financement', this.value)">
                {{% for v in financement_statuses %}}
                  <option value="{{{{ v }}}}" {{% if st.financement == v %}}selected{{% endif %}}>{{{{ v }}}}</option>
                {{% endfor %}}
              </select>
              <div class="pill b-{{{{ badge_class(st.financement, 'financement') }}}}" style="margin-top:6px">{{{{ st.financement }}}}</div>
            </td>

            <td>
              <button class="btn btn-outline" onclick="alert('Page fiche stagiaire (admin) : on la crée ensuite 😉')">📄</button>
              <div class="muted" style="margin-top:6px">{{{{ st.id }}}}</div>
            </td>
          </tr>
          {{% endfor %}}
        </tbody>
      </table>

      {{% if session.stagiaires|length == 0 %}}
        <div class="muted">Aucun stagiaire pour l’instant. Clique sur <strong>Ajouter un stagiaire</strong>.</div>
      {{% endif %}}
    </div>

  </div>

  <div class="modal-backdrop" id="modal">
    <div class="modal">
      <div class="row">
        <h3>Ajouter un stagiaire</h3>
        <button class="btn btn-gray right" onclick="closeModal()">✖</button>
      </div>

      <form method="post" action="/admin/sessions/{{{{ session.id }}}}/stagiaires/add">
        <div class="row">
          <div style="flex:1">
            <div class="muted">Nom</div>
            <input type="text" name="nom" required>
          </div>
          <div style="flex:1">
            <div class="muted">Prénom</div>
            <input type="text" name="prenom" required>
          </div>
        </div>

        <div class="row">
          <div style="flex:1">
            <div class="muted">Adresse mail</div>
            <input type="text" name="email" placeholder="ex : prenom.nom@email.com">
          </div>
        </div>

        <div class="row">
          <div style="flex:1">
            <div class="muted">Téléphone</div>
            <input type="text" name="telephone" placeholder="ex : +33612345678">
          </div>
        </div>

        <div class="row" style="margin-top:14px">
          <button class="btn btn-green" type="submit">✅ Sauvegarder</button>
          <span class="notice">Un email + SMS de bienvenue seront envoyés automatiquement (si Brevo est configuré).</span>
        </div>
      </form>
    </div>
  </div>

<script>
  const SESSION_ID = "{{{{ session.id }}}}";
  function openModal() {{
    document.getElementById('modal').style.display = 'flex';
  }}
  function closeModal() {{
    document.getElementById('modal').style.display = 'none';
  }}

  async function autosave(stagiaireId, field, value) {{
    try {{
      await fetch(`/api/sessions/${{SESSION_ID}}/stagiaires/${{stagiaireId}}/update`, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ [field]: value }})
      }});
      // quick refresh to update highlight / counts visually (simple approach)
      // You can remove this later and do partial updates
      window.location.reload();
    }} catch (e) {{
      alert("Erreur autosave : " + e);
    }}
  }}

  let _t = null;
  function debouncedSave(stagiaireId, field, value) {{
    if (_t) clearTimeout(_t);
    _t = setTimeout(() => autosave(stagiaireId, field, value), 500);
  }}
</script>

</body>
</html>
"""


if __name__ == "__main__":
    # local dev
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
