import os
import json
import uuid
import datetime
from typing import Dict, Any, Optional

import requests
from flask import Flask, request, redirect, url_for, jsonify, render_template, abort, send_file

import zipfile
from io import BytesIO
from docx import Document


app = Flask(__name__)

# =========================
# Persistent disk (Render)
# =========================
PERSIST_DIR = os.environ.get("PERSIST_DIR", "/data")
os.makedirs(PERSIST_DIR, exist_ok=True)
DATA_FILE = os.path.join(PERSIST_DIR, "data.json")

UPLOADS_DIR = os.path.join(PERSIST_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

def trainee_upload_dir(session_id: str, stagiaire_id: str) -> str:
    d = os.path.join(UPLOADS_DIR, session_id, stagiaire_id)
    os.makedirs(d, exist_ok=True)
    return d


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
CNAPS_STATUS_ENDPOINT = os.environ.get("CNAPS_STATUS_ENDPOINT", "")              # optional
HEBERGEMENT_STATUS_ENDPOINT = os.environ.get("HEBERGEMENT_STATUS_ENDPOINT", "")  # optional


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


def dossier_is_complet(st: Dict[str, Any]) -> bool:
    docs = st.get("documents", []) or []
    if not docs:
        return False
    return all((d.get("status") or "").upper() == "CONFORME" for d in docs)


def dossier_status_label(st: Dict[str, Any]) -> str:
    return "DOSSIER COMPLET" if dossier_is_complet(st) else "DOSSIER INCOMPLET"


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
    url = "https://api.brevo.com/v3/transactionalSMS/sms"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }
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
    if col in ("convention",):
        return {"prochainement": "red", "en cours de signature": "yellow", "signée": "green"}.get(value, "gray")
    if col in ("test_francais",):
        return {"prochainement": "red", "en cours": "yellow", "validé": "green", "relancé": "orange"}.get(value, "gray")
    if col in ("dossier",):
        return {"complet": "green", "incomplet": "red"}.get(value, "gray")
    if col in ("financement",):
        return {"prochainement": "red", "en cours de validation": "orange", "validé": "green"}.get(value, "gray")
    if col in ("cnaps",):
        v = (value or "").strip().upper()
        v = " ".join(v.split())

        if v in ("", "INCONNU", "INCONNUE"):
            return "gray"
        if v == "TRANSMIS":
            return "gray"
        if v in ("ENREGISTRÉ", "ENREGISTRE"):
            return "orange"
        if v == "INSTRUCTION":
            return "yellow"
        if v in ("ACCEPTÉ", "ACCEPTE"):
            return "green"
        if v in ("REFUSÉ", "REFUSE"):
            return "black"
        if v in ("DOCS COMPLÉMENTAIRES", "DOCS COMPLEMENTAIRES"):
            return "red"
        return "gray"

    if col in ("hebergement",):
        return {"réservé": "green", "inconnu": "black"}.get(value, "gray")
    if col in ("vae",):
        return {"validé": "green", "en cours": "yellow", "prochainement": "red", "non concerné": "gray"}.get(value, "gray")
    return "gray"


# =========================
# Routes
# =========================

@app.post("/admin/sessions/<session_id>/stagiaires/<stagiaire_id>/test-fr/relance")
def admin_test_fr_relance(session_id: str, stagiaire_id: str):
    code = (request.form.get("code") or "").strip()
    deadline = (request.form.get("deadline") or "").strip()
    if not code or not deadline:
        return redirect(url_for("admin_stagiaire_space", session_id=session_id, stagiaire_id=stagiaire_id))

    data = load_data()
    session = find_session(data, session_id)
    if not session:
        abort(404)

    st = find_stagiaire(session, stagiaire_id)
    if not st:
        abort(404)

    link = "https://testb1.lapreventionsecurite.org/Public/"

    subject = "Relance – Test de français à réaliser"
    html = f"""
      <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
        <div style="background:white;padding:18px;border-radius:12px">
          <h2 style="margin:0 0 10px 0">Relance – Test de français</h2>
          <p>Nous n’avons pas encore reçu votre test. Merci de le réaliser via :</p>
          <p><a href="{link}">{link}</a></p>
          <p><strong>Nouveau code :</strong> {code}</p>
          <p><strong>À réaliser avant :</strong> {deadline}</p>
          <p style="color:#666;font-size:13px;margin-top:12px">Intégrale Academy</p>
        </div>
      </div>
    """

    sms = f"Relance Intégrale Academy : Test FR. Lien: {link} Code: {code} Avant: {deadline}"

    if st.get("email"):
        brevo_send_email(st["email"], subject, html)
    if st.get("telephone"):
        brevo_send_sms(st["telephone"], sms)

    st["test_francais"] = "RELANCÉ"
    st["test_fr_code"] = code
    st["test_fr_deadline"] = deadline
    st["test_fr_last_relance_at"] = _now_iso()
    save_data(data)

    return redirect(url_for("admin_stagiaire_space", session_id=session_id, stagiaire_id=stagiaire_id))


@app.post("/admin/sessions/<session_id>/stagiaires/<stagiaire_id>/test-fr/notify")
def admin_test_fr_notify(session_id: str, stagiaire_id: str):
    code = (request.form.get("code") or "").strip()
    deadline = (request.form.get("deadline") or "").strip()
    if not code or not deadline:
        return redirect(url_for("admin_stagiaire_space", session_id=session_id, stagiaire_id=stagiaire_id))

    data = load_data()
    session = find_session(data, session_id)
    if not session:
        abort(404)

    st = find_stagiaire(session, stagiaire_id)
    if not st:
        abort(404)

    link = "https://testb1.lapreventionsecurite.org/Public/"

    subject = "Test de français à réaliser – Intégrale Academy"
    html = f"""
      <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
        <div style="background:white;padding:18px;border-radius:12px">
          <h2 style="margin:0 0 10px 0">Test de français – à faire</h2>
          <p>Merci de réaliser votre test de français via le lien ci-dessous :</p>
          <p><a href="{link}">{link}</a></p>
          <p><strong>Code :</strong> {code}</p>
          <p><strong>À réaliser avant :</strong> {deadline}</p>
          <hr style="border:none;border-top:1px solid #eee;margin:16px 0">
          <p style="color:#666;font-size:13px;margin:0">Intégrale Academy</p>
        </div>
      </div>
    """

    sms = f"Intégrale Academy : Test de français à faire. Lien: {link} Code: {code} Avant: {deadline}"

    if st.get("email"):
        brevo_send_email(st["email"], subject, html)
    if st.get("telephone"):
        brevo_send_sms(st["telephone"], sms)

    st["test_francais"] = "EN COURS"
    st["test_fr_code"] = code
    st["test_fr_deadline"] = deadline
    st["test_fr_last_notified_at"] = _now_iso()
    save_data(data)

    return redirect(url_for("admin_stagiaire_space", session_id=session_id, stagiaire_id=stagiaire_id))


@app.get("/admin/sessions/<session_id>/stagiaires/<stagiaire_id>/documents.zip")
def admin_docs_zip(session_id: str, stagiaire_id: str):
    data = load_data()
    session = find_session(data, session_id)
    if not session:
        abort(404)

    st = find_stagiaire(session, stagiaire_id)
    if not st:
        abort(404)

    docs = st.get("documents", []) or []

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for d in docs:
            fp = (d.get("file") or "").strip()
            if not fp or not os.path.exists(fp):
                continue

            label = (d.get("label") or "document").replace("/", "-")
            prenom = (st.get("prenom") or "").strip()
            nom = (st.get("nom") or "").strip()

            ext = os.path.splitext(fp)[1] or ""
            newname = f"{label} {prenom} {nom}".strip().replace("  ", " ")
            z.write(fp, arcname=(newname + ext))

    buf.seek(0)
    zipname = f"Documents_{st.get('prenom','')}_{st.get('nom','')}.zip".replace(" ", "_")
    return send_file(buf, as_attachment=True, download_name=zipname, mimetype="application/zip")


@app.post("/api/sessions/<session_id>/stagiaires/<stagiaire_id>/documents/update")
def api_update_document(session_id: str, stagiaire_id: str):
    data = load_data()
    session = find_session(data, session_id)
    if not session:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    st = find_stagiaire(session, stagiaire_id)
    if not st:
        return jsonify({"ok": False, "error": "stagiaire_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    doc_key = payload.get("key")
    field = payload.get("field")
    value = payload.get("value")

    if field not in ("status", "comment"):
        return jsonify({"ok": False, "error": "invalid_field"}), 400

    docs = st.get("documents", []) or []
    for d in docs:
        if d.get("key") == doc_key:
            d[field] = value
            break

    st["updated_at"] = _now_iso()
    save_data(data)

    return jsonify({"ok": True, "dossier_complet": dossier_is_complet(st)})


@app.post("/admin/sessions/<session_id>/stagiaires/<stagiaire_id>/send-access")
def admin_stagiaire_send_access(session_id: str, stagiaire_id: str):
    data = load_data()
    session = find_session(data, session_id)
    if not session:
        abort(404)

    st = find_stagiaire(session, stagiaire_id)
    if not st:
        abort(404)

    public_link = f"{PUBLIC_STUDENT_PORTAL_BASE}?token={st.get('public_token','')}"
    formation_name = session.get("nom", "Votre formation")

    subject = "Accès à votre espace stagiaire – Intégrale Academy"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        <h2>Votre espace stagiaire est disponible</h2>
        <p>Formation : <strong>{formation_name}</strong></p>
        <p>
          <a href="{public_link}" style="display:inline-block;background:#1f8f4a;color:white;padding:10px 14px;border-radius:10px;text-decoration:none">
            Accéder à mon espace stagiaire
          </a>
        </p>
        <p style="color:#666;font-size:13px">Intégrale Academy</p>
      </div>
    </div>
    """

    sms = f"Intégrale Academy : votre espace stagiaire est disponible : {public_link}"

    if st.get("email"):
        brevo_send_email(st["email"], subject, html)
    if st.get("telephone"):
        brevo_send_sms(st["telephone"], sms)

    st["access_sent_at"] = _now_iso()
    save_data(data)

    return redirect(url_for("admin_stagiaire_space", session_id=session_id, stagiaire_id=stagiaire_id))


@app.get("/admin/sessions/<session_id>/stagiaires/<stagiaire_id>/etiquette.docx")
def admin_stagiaire_etiquette_docx(session_id: str, stagiaire_id: str):
    data = load_data()
    session = find_session(data, session_id)
    if not session:
        abort(404)

    st = find_stagiaire(session, stagiaire_id)
    if not st:
        abort(404)

    doc = Document()
    doc.add_heading("Étiquette dossier", level=1)
    doc.add_paragraph(f"Nom : {st.get('nom','')}")
    doc.add_paragraph(f"Prénom : {st.get('prenom','')}")
    doc.add_paragraph(f"Formation : {session.get('nom','')}")
    doc.add_paragraph(f"Type : {session.get('type_formation','')}")
    doc.add_paragraph(f"Dates : {session.get('date_debut','')} → {session.get('date_fin','')}")

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)

    filename = f"etiquette_{st.get('nom','')}_{st.get('prenom','')}.docx".replace(" ", "_")
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@app.post("/admin/sessions/<session_id>/stagiaires/<stagiaire_id>/delete")
def admin_stagiaire_delete(session_id: str, stagiaire_id: str):
    data = load_data()
    session = find_session(data, session_id)
    if not session:
        abort(404)

    session["stagiaires"] = [st for st in session.get("stagiaires", []) if st.get("id") != stagiaire_id]
    save_data(data)
    return redirect(url_for("admin_stagiaires", session_id=session_id))


@app.get("/admin/sessions/<session_id>/stagiaires/<stagiaire_id>")
def admin_stagiaire_space(session_id: str, stagiaire_id: str):
    data = load_data()
    session = find_session(data, session_id)
    if not session:
        abort(404)

    st = find_stagiaire(session, stagiaire_id)
    if not st:
        abort(404)

    st["_dossier_calc"] = dossier_status_label(st)
    public_link = f"{PUBLIC_STUDENT_PORTAL_BASE}?token={st.get('public_token','')}"

    # ✅ Ici on utilise un fichier template (à créer)
    return render_template(
        "admin_trainee_space.html",
        session=session,
        st=st,
        public_link=public_link,
        badge_class=badge_class
    )


@app.get("/")
def home():
    return redirect(url_for("admin_sessions"))


@app.get("/admin/sessions")
def admin_sessions():
    data = load_data()
    sessions = data.get("sessions", [])
    for s in sessions:
        s["_conforme"] = session_is_conforme(s)
        s["_counts"] = count_conformes(s)

    # ✅ fichier template
    return render_template("admin_sessions.html", sessions=sessions, formation_types=FORMATION_TYPES)


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

        # Hébergement uniquement pour A3P
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

    # ✅ fichier template
    return render_template(
        "admin_trainees.html",
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

        "convention": "prochainement",
        "dossier": "incomplet",
        "cnaps": "inconnu",
        "financement": "prochainement",
        "commentaire": "",

        # Conditional
        "vae": "prochainement" if session.get("type_formation") == "DIRIGEANT VAE" else "non concerné",
        "hebergement": "inconnu" if session.get("type_formation") == "A3P" else None,

        "created_at": _now_iso(),

        # --- Espace public stagiaire ---
        "public_token": uuid.uuid4().hex,

        # --- Test de français ---
        "test_francais": "A FAIRE",
        "test_fr_code": "",
        "test_fr_deadline": "",
        "test_fr_last_notified_at": "",
        "test_fr_last_relance_at": "",

        # --- Gestion des documents ---
        "docs_notified_at": "",
        "docs_last_relance_at": "",
        "docs_last_nonconform_notified_at": "",

        "documents": [
            {"key": "id", "label": "Pièce d'identité", "status": "A CONTRÔLER", "comment": "", "file": ""},
            {"key": "dom", "label": "Justificatif de domicile (-3 mois)", "status": "A CONTRÔLER", "comment": "", "file": ""},
            {"key": "photo", "label": "Photo d'identité", "status": "A CONTRÔLER", "comment": "", "file": ""},
        ],

        "deliverables": {
            "diplome": "",
            "carte_sst": "",
            "certificat_sst": "",
            "attestation_fin_formation": "",
            "dossier_fin_formation": ""
        },
    }

    session.setdefault("stagiaires", []).insert(0, st)
    save_data(data)

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

    status = fetch_cnaps_status_by_name(nom, prenom) or "INCONNU"
    return jsonify({"ok": True, "nom": nom, "prenom": prenom, "statut_cnaps": status})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
