import os
import json
import uuid
import datetime
from typing import Dict, Any, Optional, List
from functools import wraps
from flask import session
from PIL import Image
import tempfile
from docx.shared import Inches

import requests
from flask import Flask, request, redirect, url_for, jsonify, render_template, abort, send_file

import zipfile
from io import BytesIO
from docx import Document


app = Flask(__name__)

# =========================
# Auth (admin)
# =========================
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

ADMIN_USER = os.environ.get("ADMIN_USER", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))

app.config.update(
    SESSION_COOKIE_NAME="integrale_admin",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,  # Render = https
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=SESSION_DAYS),
)

def admin_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

@app.get("/admin/login")
def admin_login():
    # mini page sans template (pour aller vite)
    next_url = request.args.get("next") or url_for("admin_sessions")
    return f"""
    <!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Connexion admin</title></head>
    <body style="font-family:Arial,sans-serif;max-width:420px;margin:60px auto;padding:20px">
      <h2>Connexion</h2>
      <form method="post" action="/admin/login">
        <input type="hidden" name="next" value="{next_url}">
        <div style="margin:10px 0">
          <label>Identifiant</label><br>
          <input name="username" autocomplete="username" style="width:100%;padding:10px">
        </div>
        <div style="margin:10px 0">
          <label>Mot de passe</label><br>
          <input name="password" type="password" autocomplete="current-password" style="width:100%;padding:10px">
        </div>
        <button style="padding:10px 14px">Se connecter</button>
      </form>
    </body></html>
    """

@app.post("/admin/login")
def admin_login_post():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    next_url = request.form.get("next") or url_for("admin_sessions")

    # sécurité minimale : si pas configuré, on refuse
    if not ADMIN_USER or not ADMIN_PASSWORD:
        abort(500, "ADMIN_USER/ADMIN_PASSWORD non configurés")

    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        session["admin_logged_in"] = True
        session.permanent = True  # ✅ cookie persistant
        return redirect(next_url)

    return redirect(url_for("admin_login", next=next_url))

@app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

def fr_date(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    try:
        dt = datetime.datetime.strptime(s[:10], "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return value

def fr_datetime(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.datetime.strptime(s[:len(fmt)], fmt)
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
    return fr_date(s)


# ✅ Filtres utilisables dans tous tes templates
app.add_template_filter(fr_date, "frdate")
app.add_template_filter(fr_datetime, "frdatetime")


# =========================
# Persistent disk (Render)
# =========================
PERSIST_DIR = os.environ.get("PERSIST_DIR", "/data")
os.makedirs(PERSIST_DIR, exist_ok=True)
DATA_FILE = os.path.join(PERSIST_DIR, "data.json")

UPLOADS_DIR = os.path.join(PERSIST_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

def trainee_upload_dir(session_id: str, trainee_id: str) -> str:
    d = os.path.join(UPLOADS_DIR, session_id, trainee_id)
    os.makedirs(d, exist_ok=True)
    return d


# =========================
# Brevo (Sendinblue) config
# =========================
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "ecole@integraleacademy.com")
BREVO_SENDER_NAME = os.environ.get("BREVO_SENDER_NAME", "Intégrale Academy")
CNAPS_LOOKUP_ENDPOINT = os.environ.get("CNAPS_LOOKUP_ENDPOINT", "")

PUBLIC_STUDENT_PORTAL_BASE = os.environ.get(
    "PUBLIC_STUDENT_PORTAL_BASE",
    "https://gestionstagiaires-r5no.onrender.com"
)

PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "https://gestionstagiaires-r5no.onrender.com"
)


CNAPS_STATUS_ENDPOINT = os.environ.get("CNAPS_STATUS_ENDPOINT", "")
HEBERGEMENT_STATUS_ENDPOINT = os.environ.get("HEBERGEMENT_STATUS_ENDPOINT", "")


def normalize_phone_fr(phone: str) -> str:
    p = (phone or "").strip().replace(" ", "").replace(".", "").replace("-", "")
    if not p:
        return ""
    if p.startswith("+"):
        return p
    if p.startswith("00"):
        return "+" + p[2:]
    if p.startswith("0") and len(p) == 10 and p[1:].isdigit():
        return "+33" + p[1:]
    return p



import base64

def brevo_send_email(to_email: str, subject: str, html: str) -> bool:
    if not BREVO_API_KEY or not to_email:
        return False

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }

    attachments = []  # ✅ pas d'inline CID, Gmail casse souvent

    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }

    if attachments:
        payload["attachment"] = attachments

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=12)
        return r.status_code in (200, 201, 202)
    except Exception:
        return False


def brevo_send_sms(phone: str, message: str) -> bool:
    phone = normalize_phone_fr(phone)
    if not BREVO_API_KEY or not phone:
        print("[SMS] Missing BREVO_API_KEY or phone")
        return False

    url = "https://api.brevo.com/v3/transactionalSMS/sms"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }

    # (souvent requis selon config Brevo) : nom d’expéditeur SMS
    sms_sender = os.environ.get("BREVO_SMS_SENDER", "").strip()

    payload = {
        "recipient": phone,
        "content": message,
        "type": "transactional",
    }
    if sms_sender:
        payload["sender"] = sms_sender  # ex: "INTEGRALE"

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=12)

        # ✅ logs indispensables (status + réponse Brevo)
        print("[SMS] status=", r.status_code)
        print("[SMS] response=", r.text)

        return r.status_code in (200, 201, 202)
    except Exception as e:
        print("[SMS] exception=", repr(e))
        return False


def mail_layout(inner_html: str) -> str:
    # ✅ logo en URL HTTPS (fiable dans Gmail)
    logo_src = f"{PUBLIC_BASE_URL.rstrip('/')}/static/logo-integrale.png"

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        <div style="text-align:center;margin-bottom:18px">
          <img src="{logo_src}" alt="Intégrale Academy"
               style="height:60px;width:auto;display:block;margin:0 auto;border:0;outline:none;text-decoration:none">
        </div>

        {inner_html}

        <p style="margin-top:30px;color:#666;font-size:13px;text-align:center">
          Intégrale Academy
        </p>
      </div>
    </div>
    """
# =========================
# Helpers
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
            data = json.load(f)

        # ✅ Assure que tous les stagiaires ont un public_token
        changed = False

        if ensure_public_tokens(data):
            changed = True

        # ✅ IMPORTANT : normalise en "trainees" partout (sinon admin/public désynchronisés)
        if normalize_sessions_schema(data):
            changed = True

        if changed:
            save_data(data)

        return data


    except Exception:
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


def ensure_public_tokens(data):
    changed = False

    for session in data.get("sessions", []):
        trainees = session.get("trainees") or session.get("stagiaires") or []

        for trainee in trainees:
            if "public_token" not in trainee or not trainee["public_token"]:
                trainee["public_token"] = uuid.uuid4().hex
                changed = True

    return changed



def find_trainee(session: Dict[str, Any], trainee_id: str) -> Optional[Dict[str, Any]]:
    for t in session.get("trainees", []):
        if t.get("id") == trainee_id:
            return t
    return None


def _session_get(s: Dict[str, Any], key: str, fallback: str = "") -> str:
    """
    Backward compatible getter: support old FR keys if needed.
    """
    if key in s and s.get(key) not in (None, ""):
        return s.get(key)

    # old keys from previous versions
    fr_map = {
        "name": "nom",
        "date_start": "date_debut",
        "date_end": "date_fin",
        "exam_date": "date_examen",
        "training_type": "type_formation",
        "trainees": "stagiaires",
    }
    fr_key = fr_map.get(key)
    if fr_key and fr_key in s and s.get(fr_key) not in (None, ""):
        return s.get(fr_key)

    return fallback


def _session_trainees_list(s: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "trainees" in s and isinstance(s.get("trainees"), list):
        return s.get("trainees", [])
    if "stagiaires" in s and isinstance(s.get("stagiaires"), list):
        # convert on the fly (non destructif)
        out = []
        for st in s.get("stagiaires", []):
            out.append(_convert_old_stagiaire_to_trainee(st))
        return out
    return []


def _convert_old_stagiaire_to_trainee(st: Dict[str, Any]) -> Dict[str, Any]:
    # best-effort mapping
    return {
        "id": st.get("id") or ("TRN-" + uuid.uuid4().hex[:8].upper()),
        "personal_id": st.get("id") or "",
        "last_name": st.get("nom") or "",
        "first_name": st.get("prenom") or "",
        "email": st.get("email") or "",
        "phone": st.get("telephone") or "",
        "comment": st.get("commentaire") or "",
        "cnaps": (st.get("cnaps") or "INCONNU"),
        "convention_status": _map_convention_to_enum(st.get("convention")),
        "test_fr_status": _map_testfr_to_enum(st.get("test_francais")),
        "dossier_status": "complete" if (st.get("dossier") == "complet") else "incomplete",
        "financement_status": _map_financement_to_enum(st.get("financement")),
        "vae_status": _map_vae_to_enum(st.get("vae")),
        "hosting_status": _map_hosting_to_enum(st.get("hebergement")),
        "documents": st.get("documents") or [],
        "public_token": st.get("public_token") or "",
        "created_at": st.get("created_at") or "",
        "updated_at": st.get("updated_at") or "",
    }


def _map_convention_to_enum(v: Optional[str]) -> str:
    v = (v or "").strip().lower()
    if v in ("signée", "signee", "signed"):
        return "signed"
    if "signature" in v or v in ("en cours de signature", "signing"):
        return "signing"
    return "soon"


def _map_testfr_to_enum(v: Optional[str]) -> str:
    v = (v or "").strip().lower()
    if v in ("validé", "valide", "validated"):
        return "validated"
    if v in ("relancé", "relance", "relancé(e)", "relancee"):
        return "relance"
    if v in ("en cours", "in progress", "in_progress", "en_cours"):
        return "in_progress"
    return "soon"


def _map_financement_to_enum(v: Optional[str]) -> str:
    v = (v or "").strip().lower()
    if v in ("validé", "valide", "validated"):
        return "validated"
    if "validation" in v or v in ("en cours de validation", "in_review"):
        return "in_review"
    return "soon"


def _map_vae_to_enum(v: Optional[str]) -> str:
    v = (v or "").strip().lower()
    if v in ("validé", "valide", "validated"):
        return "validated"
    if v in ("en cours", "in_progress", "in progress"):
        return "in_progress"
    return "soon"


def _map_hosting_to_enum(v: Optional[str]) -> str:
    v = (v or "").strip().lower()
    if v in ("réservé", "reserve", "reserved"):
        return "reserved"
    return "unknown"




# =========================
# Conformity logic (matching your enums)
# =========================

def trainee_is_conform(t: Dict[str, Any], training_type: str) -> bool:
    if t.get("convention_status") != "signed":
        return False
    if t.get("test_fr_status") != "validated":
        return False
    if t.get("dossier_status") != "complete":
        return False
    if t.get("financement_status") != "validated":
        return False
    if training_type == "DIRIGEANT VAE":
        if t.get("vae_status") != "validated":
            return False
    return True


def session_is_conform(session: Dict[str, Any]) -> bool:
    training_type = _session_get(session, "training_type", "")
    trainees = _session_trainees_list(session)
    if not trainees:
        return False
    return all(trainee_is_conform(t, training_type) for t in trainees)

def normalize_sessions_schema(data: Dict[str, Any]) -> bool:
    changed = False
    for s in data.get("sessions", []):
        # Si pas de trainees, on convertit depuis stagiaires
        if "trainees" not in s or not isinstance(s.get("trainees"), list):
            s["trainees"] = _session_trainees_list(s)
            changed = True

        # On supprime l’ancienne clé pour éviter 2 sources
        if "stagiaires" in s:
            s.pop("stagiaires", None)
            changed = True

    return changed


def compute_stats(session: Dict[str, Any]) -> Dict[str, Any]:
    training_type = _session_get(session, "training_type", "")
    trainees = _session_trainees_list(session)
    conform_count = sum(1 for t in trainees if trainee_is_conform(t, training_type))
    total = len(trainees)
    return {
        "total": total,
        "conform_count": conform_count,
        "non_conform_count": total - conform_count,
        "session_is_conform": (total > 0 and conform_count == total),
    }


# =========================
# CNAPS / Hosting fetchers
# =========================

def fetch_cnaps_status_by_name(nom: str, prenom: str) -> Optional[str]:
    if not CNAPS_LOOKUP_ENDPOINT:
        return None
    try:
        r = requests.get(CNAPS_LOOKUP_ENDPOINT, params={"nom": nom, "prenom": prenom}, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("statut_cnaps") or data.get("status")
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
            return "reserved"
        if data.get("reserved") is False:
            return "unknown"
        return data.get("status")
    except Exception:
        return None


# =========================
# UI enums (for template)
# =========================

FORMATION_TYPES = ["APS", "A3P", "DIRIGEANT initial", "DIRIGEANT VAE", "SSIAP 1", "CHEF DE POSTE"]

ENUMS = {
    "convention": ["soon", "signing", "signed"],
    "test_fr": ["soon", "in_progress", "validated", "relance"],
    "dossier": ["complete", "incomplete"],
    "financement": ["soon", "in_review", "validated"],
    "vae": ["soon", "in_progress", "validated"],
}

# =========================
# Documents requis par formation
# =========================

REQUIRED_DOCS = {
    "COMMON": [
        {"key": "id", "label": "Passeport OU Carte d’identité recto/verso OU Titre de séjour", "accept": "application/pdf"},
        {"key": "photo", "label": "Photo d’identité officielle (photo de face de votre visage sur fond neutre)", "accept": "image/jpeg,image/png"},
        {"key": "carte_vitale_doc", "label": "Carte vitale", "accept": "application/pdf"},
        {"key": "cnaps_doc", "label": "Autorisation CNAPS ou Carte professionnelle CNAPS (en cours de validité)", "accept": "application/pdf"},
    ],
    "A3P_ONLY": [
        {"key": "permis", "label": "Permis de conduire (obligatoire sauf si vous n’avez pas le permis)", "accept": "application/pdf"},
        {"key": "certif_med", "label": "Certificat médical (-3 mois)", "accept": "application/pdf"},
        {"key": "assurance_rc", "label": "Attestation d’assurance responsabilité civile", "accept": "application/pdf"},
    ],
}

def required_docs_for_training(training_type: str) -> List[Dict[str, Any]]:
    tt = (training_type or "").strip().upper()
    docs = list(REQUIRED_DOCS["COMMON"])
    if tt == "A3P":
        docs += list(REQUIRED_DOCS["A3P_ONLY"])
    return docs

def ensure_documents_schema_for_trainee(t: Dict[str, Any], training_type: str) -> bool:
    """
    S'assure que t["documents"] contient tous les docs requis pour la formation,
    sans écraser fichiers/statuts existants. Supprime l'ancien doc 'dom' (domicile).
    """
    required = required_docs_for_training(training_type)
    existing = t.get("documents") or []
    changed = False

    # index existant
    by_key = {d.get("key"): d for d in existing if isinstance(d, dict) and d.get("key")}

    out = []
    for rd in required:
        k = rd["key"]
        if k in by_key:
            d = by_key[k]
            if not d.get("label"):
                d["label"] = rd["label"]; changed = True
            if "accept" not in d:
                d["accept"] = rd.get("accept", ""); changed = True
            if "status" not in d:
                d["status"] = "NON DÉPOSÉ"; changed = True
            if "comment" not in d:
                d["comment"] = ""; changed = True
            if "file" not in d:
                d["file"] = ""; changed = True
            if "files" not in d or not isinstance(d.get("files"), list):
                d["files"] = []
                changed = True
            out.append(d)
        else:
            out.append({
                "key": k,
                "label": rd["label"],
                "accept": rd.get("accept", ""),
                "status": "NON DÉPOSÉ",
                "comment": "",
                "file": "",
                "files": [],
            })
            changed = True

    # 🔥 on vire dom (plus utilisé)
    if "dom" in by_key:
        changed = True

    t["documents"] = out
    return changed

def allowed_doc_keys_for_training(training_type: str) -> set:
    return {d["key"] for d in required_docs_for_training(training_type)}

def dossier_is_complete(trainee: Dict[str, Any], training_type: str) -> bool:
    """
    Complet si TOUS les docs requis sont CONFORME,
    sauf permis si trainee a coché no_permis=True (A3P).
    """
    docs = trainee.get("documents") or []
    if not docs:
        return False

    by_key = {d.get("key"): d for d in docs if isinstance(d, dict)}

    tt = (training_type or "").strip().upper()
    no_permis = bool(trainee.get("no_permis"))  # checkbox "je n'ai pas le permis"

    for rd in required_docs_for_training(training_type):
        k = rd["key"]

        # permis optionnel si no_permis
        if tt == "A3P" and k == "permis" and no_permis:
            continue

        d = by_key.get(k)
        if not d:
            return False

        st = (d.get("status") or "").strip().upper()
        if st != "CONFORME":
            return False

    return True

    
import re

def infos_is_complete(t: Dict[str, Any]) -> bool:
    # Champs obligatoires
    required = [
        "birth_date",
        "birth_city",
        "birth_country",
        "nationality",
        "address",
        "zip_code",
        "city",
    ]
    for k in required:
        if not (t.get(k) or "").strip():
            return False

    # Sécu : 15 chiffres
    secu_digits = re.sub(r"\D+", "", (t.get("carte_vitale") or ""))
    if len(secu_digits) != 15:
        return False

    # PRE : format PRE-083-2025-12-01-20250000000 ou CAR-...
    pre = (t.get("pre_number") or "").strip().upper().replace(" ", "")
    if not re.match(r"^(PRE|CAR)-\d{3}-\d{4}-\d{2}-\d{2}-\d{11,}$", pre):
        return False

    return True

def dossier_is_complete_total(trainee: Dict[str, Any], training_type: str) -> bool:
    # ✅ complet seulement si infos OK + tous docs CONFORME
    return infos_is_complete(trainee) and dossier_is_complete(trainee, training_type)


# =========================
# Pages (templates)
# =========================

@app.get("/")
def home():
    return redirect(url_for("admin_sessions"))


@app.get("/admin/sessions")
@admin_login_required
def admin_sessions():
    data = load_data()
    out_sessions = []
    for s in data.get("sessions", []):
        if bool(s.get("archived")):
            continue
        trainees = _session_trainees_list(s)
        st = compute_stats(s)
        out_sessions.append({
            "id": s.get("id"),
            "name": _session_get(s, "name", ""),
            "training_type": _session_get(s, "training_type", ""),
            "date_start": _session_get(s, "date_start", ""),
            "date_end": _session_get(s, "date_end", ""),
            "exam_date": _session_get(s, "exam_date", ""),
            "total": st["total"],
            "session_is_conform": st["session_is_conform"],
        })
    return render_template(
        "admin_sessions.html",
        sessions=out_sessions,
        formation_types=FORMATION_TYPES,
    )


@app.get("/admin/sessions/<session_id>/trainees")
@admin_login_required
def admin_trainees(session_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    # normalize session view
    session_view = {
        "id": s.get("id"),
        "name": _session_get(s, "name", ""),
        "training_type": _session_get(s, "training_type", ""),
        "date_start": _session_get(s, "date_start", ""),
        "date_end": _session_get(s, "date_end", ""),
        "exam_date": _session_get(s, "exam_date", ""),
    }

    trainees = _session_trainees_list(s)

    # refresh CNAPS (best-effort) using last_name/first_name
    for t in trainees:
        ln = (t.get("last_name") or "").strip()
        fn = (t.get("first_name") or "").strip()

        # ✅ si déjà validé manuellement, on ne touche pas
        if (t.get("cnaps") or "").strip().upper() == "CARTE PROFESSIONNELLE OK":
            pass
        else:
            if ln and fn:
                cn = fetch_cnaps_status_by_name(ln, fn)

                # ✅ n'écrase jamais avec INCONNU
                if cn:
                    cn_u = str(cn).strip().upper()
                    if cn_u not in ("INCONNU", "UNKNOWN", ""):
                        t["cnaps"] = cn_u

        # valeur par défaut si vide
        if not (t.get("cnaps") or "").strip():
            t["cnaps"] = "INCONNU"

        # hosting only for A3P
        if session_view["training_type"] == "A3P":
            email = t.get("email") or ""
            hb = fetch_hebergement_status(email) if email else None
            t["hosting_status"] = hb if hb else (t.get("hosting_status") or "unknown")
        else:
            t.pop("hosting_status", None)

    # persist normalized trainees back into storage
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)
    stats = compute_stats(s)
    show_hosting = (session_view["training_type"] == "A3P")
    show_vae = (session_view["training_type"] == "DIRIGEANT VAE")

    return render_template(
        "admin_trainees.html",
        session=session_view,
        trainees=trainees,
        stats=stats,
        show_hosting=show_hosting,
        show_vae=show_vae,
        enums=ENUMS,
    )


# =========================
# FICHE STAGIAIRE (HTML)
# =========================



# =========================
# API - Sessions (used by your modal JS)
# =========================

@app.post("/api/sessions/create")
@admin_login_required
def api_create_session():
    data = load_data()
    payload = request.get_json(silent=True) or {}

    name = (payload.get("name") or "").strip()
    training_type = (payload.get("training_type") or "").strip()
    date_start = (payload.get("date_start") or "").strip()
    date_end = (payload.get("date_end") or "").strip()
    exam_date = (payload.get("exam_date") or "").strip()

    if not name or not training_type:
        return jsonify({"ok": False, "error": "missing_name_or_training_type"}), 400

    session_id = uuid.uuid4().hex[:10]
    s = {
        "id": session_id,
        "name": name,
        "training_type": training_type,
        "date_start": date_start,
        "date_end": date_end,
        "exam_date": exam_date,
        "created_at": _now_iso(),
        "trainees": [],
        "archived": False, 
    }
    data["sessions"].insert(0, s)
    save_data(data)
    return jsonify({"ok": True, "id": session_id})


@app.post("/api/sessions/<session_id>/delete")
@admin_login_required
def api_delete_session(session_id: str):
    data = load_data()
    before = len(data.get("sessions", []))
    data["sessions"] = [s for s in data.get("sessions", []) if s.get("id") != session_id]
    save_data(data)
    return jsonify({"ok": True, "deleted": (len(data["sessions"]) != before)})

@app.post("/api/sessions/<session_id>/archive")
@admin_login_required
def api_archive_session(session_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    s["archived"] = True
    s["archived_at"] = _now_iso()
    save_data(data)
    return jsonify({"ok": True})


@app.post("/api/sessions/<session_id>/unarchive")
@admin_login_required
def api_unarchive_session(session_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    s["archived"] = False
    # optionnel: garder archived_at pour l'historique, ou le vider
    # s["archived_at"] = ""
    save_data(data)
    return jsonify({"ok": True})


# =========================
# API - Trainees (create + update for autosave)
# =========================

@app.post("/api/sessions/<session_id>/trainees/create")
@admin_login_required
def api_create_trainee(session_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    last_name = (payload.get("last_name") or "").strip()
    first_name = (payload.get("first_name") or "").strip()
    email = (payload.get("email") or "").strip()
    phone = (payload.get("phone") or "").strip()
    carte_pro_ok = bool(payload.get("carte_pro_ok"))

    # ✅ nouveau : choisir si on envoie l'accès tout de suite
    send_access = payload.get("send_access", True)
    send_access = True if send_access in (True, "true", "1", 1, "yes", "on") else False

    if not last_name or not first_name:
        return jsonify({"ok": False, "error": "missing_name"}), 400

    trainee_id = "TRN-" + uuid.uuid4().hex[:8].upper()

    training_type = _session_get(s, "training_type", "")
    show_hosting = (training_type == "A3P")
    show_vae = (training_type == "DIRIGEANT VAE")

    public_token = uuid.uuid4().hex

    t = {
        "id": trainee_id,
        "personal_id": trainee_id,
        "last_name": last_name,
        "first_name": first_name,
        "email": email,
        "phone": phone,
        "comment": "",
        "cnaps": "CARTE PROFESSIONNELLE OK" if carte_pro_ok else "INCONNU",
        "convention_status": "soon",
        "test_fr_status": "soon",
        "dossier_status": "incomplete",
        "financement_status": "soon",
        "vae_status": "soon" if show_vae else "",
        "hosting_status": "unknown" if show_hosting else "",
        "public_token": public_token,
        "no_permis": False,
        "documents": [],
        "created_at": _now_iso(),
    }

    ensure_documents_schema_for_trainee(t, training_type)
    t["dossier_status"] = "complete" if dossier_is_complete_total(t, training_type) else "incomplete"

    trainees = _session_trainees_list(s)
    trainees.insert(0, t)
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)

    # ✅ ENVOI MAIL + SMS à la création (optionnel)
    link = f"{PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')}/espace/{public_token}"

    if send_access:
        formation_type = _session_get(s, "training_type", "").strip()
        dstart = fr_date(_session_get(s, "date_start", ""))
        dend = fr_date(_session_get(s, "date_end", ""))

        subject = "Votre inscription en formation – Intégrale Academy"

        html = mail_layout(f"""
          <h2 style="text-align:center">🎉 Confirmation d’inscription</h2>
          <p>Bonjour <strong>{first_name}</strong>,</p>
          <p>
            Je vous confirme que vous êtes inscrit(e) en formation
            <strong>{formation_type}</strong>, qui se déroulera
            du <strong>{dstart}</strong> au <strong>{dend}</strong>.
          </p>
          <p>Je vous remercie pour votre confiance !</p>
          <p>
            Vous recevrez prochainement par mail votre <strong>Contrat de formation</strong>
            que je vous invite à signer dès réception (signature électronique).
          </p>
          <p>
            📂 Je vous remercie de bien vouloir compléter dès que possible votre
            <strong>Dossier Formation</strong> depuis votre Espace Stagiaire en cliquant sur le bouton ci-dessous.
          </p>
          <p style="color:#b91c1c;font-weight:bold">
            ⚠️ Attention : votre dossier doit être complet au plus tard <u>10 jours avant le début de votre formation</u> !
          </p>

          <p style="text-align:center">
            <a href="{link}"
               style="display:inline-block;background:#1f8f4a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">
              👉 Accéder à mon espace stagiaire
            </a>
          </p>

          <p style="margin-top:25px">
            ☎️ Pour tous renseignements, vous pouvez nous contacter au <strong>04 22 47 07 68</strong>
            ou utiliser notre formulaire d’assistance :
          </p>

          <p style="text-align:center">
            <a href="https://assistance-alw9.onrender.com/"
               style="display:inline-block;background:#2563eb;color:white;padding:10px 16px;border-radius:10px;text-decoration:none;font-weight:bold">
              🛠️ Formulaire d’assistance
            </a>
          </p>

          <p style="margin-top:30px">
            Je reste à votre disposition pour tous renseignements complémentaires,<br>
            <strong>Clément VAILLANT</strong><br>
            Directeur Intégrale Academy
          </p>

          <hr style="margin:30px 0;border:none;border-top:1px solid #e5e7eb">

          <p style="font-size:12px;color:#6b7280;text-align:center;line-height:1.6">
            © Intégrale Academy — Merci de votre confiance 💛<br>
            54 chemin du Carreou 83480 PUGET SUR ARGENS / 142 rue de Rivoli 75001 PARIS<br>
            SIREN 840 899 884 - NDA 93830600283 - Certification Nationale QUALIOPI : n°03169 en date du 21/10/2024<br>
            UAI Côte d'Azur 0831774C - UAI Paris 0756548K<br>
            <a href="https://www.integraleacademy.com" style="color:#1f8f4a;text-decoration:none;font-weight:bold">
              integraleacademy.com
            </a>
          </p>
        """)

        sms = (
            f"Intégrale Academy 🎓 Bonjour {first_name}, Votre inscription en formation {formation_type} est confirmée. "
            f"({dstart} au {dend}). Vous allez prochainement recevoir par mail votre Contrat de formation (signature électronique). "
            f"Vous devez à présent compléter votre Dossier Formation : {link} "
            f"(votre dossier doit être COMPLET au plus tard 10 jours avant votre entrée en formation). "
            f"Pour toute demande d'assistance vous pouvez nous contacter au 04 22 47 07 68."
        )

        email_ok = brevo_send_email(email, subject, html) if email else False
        sms_ok = brevo_send_sms(phone, sms) if phone else False

        t["access_sent_at"] = _now_iso()
        t["access_sent_email_ok"] = bool(email_ok)
        t["access_sent_sms_ok"] = bool(sms_ok)
    else:
        # pas d'envoi maintenant
        email_ok = False
        sms_ok = False
        t["access_sent_at"] = ""
        t["access_sent_email_ok"] = False
        t["access_sent_sms_ok"] = False

    save_data(data)

    return jsonify({
        "ok": True,
        "id": trainee_id,
        "access_email_ok": email_ok,
        "access_sms_ok": sms_ok,
        "public_link": link
    })





@app.post("/api/sessions/<session_id>/stagiaires/<trainee_id>/update")
@admin_login_required
def api_update_trainee(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    trainees = _session_trainees_list(s)
    t = None
    for x in trainees:
        if x.get("id") == trainee_id:
            t = x
            break
    if not t:
        return jsonify({"ok": False, "error": "trainee_not_found"}), 404

    payload = request.get_json(silent=True) or {}

    # Your template uses:
    # - convention_status, test_fr_status, dossier_status, financement_status, vae_status, comment, cnaps
    allowed = {
        "convention_status",
        "test_fr_status",
        "dossier_status",
        "financement_status",
        "vae_status",
        "comment",
        "financement_comment",
        "vae_status_label",
        "cnaps",
        "no_permis", 
    }

    for k, v in payload.items():
        if k in allowed:
            t[k] = v

    t["updated_at"] = _now_iso()
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    training_type = _session_get(s, "training_type", "")
    t["dossier_status"] = "complete" if dossier_is_complete_total(t, training_type) else "incomplete"
    save_data(data)
    return jsonify({"ok": True})


@app.post("/api/sessions/<session_id>/trainees/<trainee_id>/delete")
@admin_login_required
def api_delete_trainee(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    trainees = _session_trainees_list(s)
    before = len(trainees)
    trainees = [x for x in trainees if x.get("id") != trainee_id]
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)
    return jsonify({"ok": True, "deleted": (len(trainees) != before)})


# =========================
# CNAPS lookup API (used by your refresh button)
# =========================

@app.get("/api/cnaps_lookup")
def api_cnaps_lookup():
    nom = (request.args.get("nom") or "").strip()
    prenom = (request.args.get("prenom") or "").strip()

    if not nom or not prenom:
        return jsonify({"ok": False, "error": "missing_nom_or_prenom"}), 400

    status = fetch_cnaps_status_by_name(nom, prenom) or "INCONNU"
    return jsonify({"ok": True, "nom": nom, "prenom": prenom, "statut_cnaps": str(status).upper()})


# =========================
# Health
# =========================

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "data_file": DATA_FILE})

from werkzeug.utils import secure_filename



# =========================
# Upload helpers
# =========================
ALLOWED_EXT = {".pdf",".png",".jpg",".jpeg",".doc",".docx",".webp"}

def _safe_ext(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()

def _store_file(session_id: str, trainee_id: str, folder: str, f) -> str:
    base = trainee_upload_dir(session_id, trainee_id)
    target_dir = os.path.join(base, folder)
    os.makedirs(target_dir, exist_ok=True)

    filename = secure_filename(f.filename or "file")
    ext = _safe_ext(filename)
    if ext and ext not in ALLOWED_EXT:
        raise ValueError("extension_not_allowed")

    name = uuid.uuid4().hex[:10] + (ext or "")
    path = os.path.join(target_dir, name)
    f.save(path)
    return path

def _tokenize_path(path: str) -> str:
    # on ne renvoie pas le chemin réel au template
    # token = path relatif à PERSIST_DIR
    rel = os.path.relpath(path, PERSIST_DIR).replace("\\","/")
    return rel

def _detokenize_path(token: str) -> str:
    token = (token or "").replace("..","").lstrip("/").replace("\\","/")
    return os.path.join(PERSIST_DIR, token)

@app.get("/admin/uploads/<path:path>")
@admin_login_required
def admin_view_upload(path: str):
    full = _detokenize_path(path)
    if not os.path.exists(full):
        abort(404)
    # simple serve
    return send_file(full, as_attachment=False)

@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/documents/<doc_key>/upload")
@admin_login_required
def admin_upload_doc_file(session_id: str, trainee_id: str, doc_key: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    training_type = _session_get(s, "training_type", "")

    # ✅ s'assure que la liste de documents correspond à la formation (et supprime dom)
    ensure_documents_schema_for_trainee(t, training_type)

    # ✅ refuse les doc_key inconnus pour cette formation
    if doc_key not in allowed_doc_keys_for_training(training_type):
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    f = request.files.get("file")
    if not f or not f.filename:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    try:
        stored = _store_file(session_id, trainee_id, "documents", f)
    except Exception:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    token = _tokenize_path(stored)

    docs = t.get("documents") or []
    for d in docs:
        if d.get("key") == doc_key:
            cur_files = d.get("files")
            if not isinstance(cur_files, list):
                cur_files = []

            old = (d.get("file") or "").strip()
            if old and old not in cur_files:
                cur_files.append(old)

            cur_files.append(token)

            d["files"] = cur_files
            d["file"] = cur_files[0] if cur_files else ""

            cur = (d.get("status") or "").strip().upper()
            if cur in ("", "NON DÉPOSÉ", "NON DEPOSE", "NON_DEPOSE"):
                d["status"] = "A CONTRÔLER"
            if d.get("status") == "A CONTROLER":
                d["status"] = "A CONTRÔLER"
            break

    t["updated_at"] = _now_iso()

    # ✅ recalcul dossier_status
    t["dossier_status"] = "complete" if dossier_is_complete_total(t, training_type) else "incomplete"

    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)

    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/documents/<doc_key>/delete")
@admin_login_required
def admin_delete_doc_file(session_id: str, trainee_id: str, doc_key: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    training_type = _session_get(s, "training_type", "")
    ensure_documents_schema_for_trainee(t, training_type)

    # sécurité: n'accepte que les doc_key requis
    if doc_key not in allowed_doc_keys_for_training(training_type):
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    docs = t.get("documents") or []
    target = next((d for d in docs if d.get("key") == doc_key), None)
    if not target:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    # tokens à supprimer (multi ou mono)
    tokens = []
    if isinstance(target.get("files"), list) and target["files"]:
        tokens = [x for x in target["files"] if x]
    else:
        tok = (target.get("file") or "").strip()
        if tok:
            tokens = [tok]

    # suppression fichiers sur disque
    for tok in tokens:
        try:
            fp = _detokenize_path(tok)
            if os.path.exists(fp):
                os.remove(fp)
        except Exception:
            pass

    # reset du doc
    target["file"] = ""
    target["files"] = []
    target["status"] = "NON DÉPOSÉ"
    # on garde le commentaire (pratique), ou tu peux le vider si tu préfères

    t["updated_at"] = _now_iso()

    # recalcul dossier_status
    t["dossier_status"] = "complete" if dossier_is_complete_total(t, training_type) else "incomplete"

    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)

    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))




# =========================
# Documents logic
# =========================


def docs_summary_text(trainee: Dict[str, Any]) -> str:
    lines=[]
    for d in (trainee.get("documents") or []):
        st = (d.get("status") or "A CONTRÔLER").upper()
        com = (d.get("comment") or "").strip()
        if com:
            lines.append(f"- {d.get('label','document')} : {st} — {com}")
        else:
            lines.append(f"- {d.get('label','document')} : {st}")
    return "\n".join(lines)


import re

def infos_missing_text(trainee: dict) -> str:
    """
    Retourne une liste texte des infos à compléter (ou invalides),
    exactement comme dans l'espace stagiaire (Infos à compléter).
    """
    missing = []

    # --- champs simples obligatoires ---
    simple_required = [
        ("birth_date", "Date de naissance"),
        ("birth_city", "Ville de naissance"),
        ("birth_country", "Pays de naissance"),
        ("nationality", "Nationalité"),
        ("address", "Adresse postale"),
        ("zip_code", "Code postal"),
        ("city", "Ville"),
    ]
    for key, label in simple_required:
        if not (trainee.get(key) or "").strip():
            missing.append(f"- {label}")

    # --- Numéro de sécu : 15 chiffres ---
    secu_raw = (trainee.get("carte_vitale") or "").strip()
    secu_digits = re.sub(r"\D+", "", secu_raw)
    if not secu_raw:
        missing.append("- Numéro de sécurité sociale")
    elif len(secu_digits) != 15:
        missing.append("- Numéro de sécurité sociale (15 chiffres)")

    # --- PRE/CAR ---
    pre_raw = (trainee.get("pre_number") or "").strip()
    pre = pre_raw.upper().replace(" ", "")
    if not pre_raw:
        missing.append("- Numéro PRE / CAR")
    elif not re.match(r"^(PRE|CAR)-\d{3}-\d{4}-\d{2}-\d{2}-\d{11,}$", pre):
        missing.append("- Numéro PRE / CAR (format invalide)")

    return "\n".join(missing)


# =========================
# Admin actions — trainee
# =========================
@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/delete")
@admin_login_required
def admin_delete_trainee(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)
    trainees = _session_trainees_list(s)
    trainees = [x for x in trainees if x.get("id") != trainee_id]
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)
    return redirect(url_for("admin_trainees", session_id=session_id))

def _replace_in_docx(doc: Document, replacements: dict) -> None:
    def replace_in_paragraph(p):
        # Remplace dans les runs pour garder le style
        for run in p.runs:
            for k, v in replacements.items():
                if k in run.text:
                    run.text = run.text.replace(k, v)

    def replace_in_table(table):
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    replace_in_paragraph(p)
                for t2 in cell.tables:
                    replace_in_table(t2)

    # Corps du document
    for p in doc.paragraphs:
        replace_in_paragraph(p)

    for table in doc.tables:
        replace_in_table(table)

    # En-têtes / pieds de page
    for section in doc.sections:
        for p in section.header.paragraphs:
            replace_in_paragraph(p)
        for table in section.header.tables:
            replace_in_table(table)

        for p in section.footer.paragraphs:
            replace_in_paragraph(p)
        for table in section.footer.tables:
            replace_in_table(table)


@app.get("/admin/sessions/<session_id>/stagiaires/<trainee_id>/etiquette.docx")
def admin_etiquette_docx(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    # 1) Choix du modèle Word selon le type de formation
    training_type = (_session_get(s, "training_type", "") or "").strip().upper()

    TEMPLATE_MAP = {
        "A3P": "etiquette_a3p.docx",
        "APS": "etiquette_aps.docx",
        "CHAUFFEUR VTC": "etiquette_vtc.docx",
        "DIRIGEANT": "etiquette_dirigeant.docx",
        "DIRIGEANT INITIAL": "etiquette_dirigeant_initial.docx",
        "DIRIGEANT VAE": "etiquette_dirigeant.docx",
    }

    template_name = TEMPLATE_MAP.get(training_type)
    if not template_name:
        abort(400, f"Aucun modèle Word prévu pour la formation : {training_type}")

    template_path = os.path.join("templates_word", template_name)
    if not os.path.exists(template_path):
        abort(500, f"Fichier Word manquant : {template_name} (dans /templates_word)")

    # 2) Ouvrir le modèle
    doc = Document(template_path)

    # 3) Remplacements
    replacements = {
        "{{NOM}}": (t.get("last_name", "") or "").upper(),
        "{{PRENOM}}": (t.get("first_name", "") or "").upper(),
        "{{FORMATION}}": _session_get(s, "name", ""),
        "{{TYPE_FORMATION}}": training_type,
        "{{DATES}}": f"{fr_date(_session_get(s,'date_start',''))} → {fr_date(_session_get(s,'date_end',''))}",
    }

    _replace_in_docx(doc, replacements)

    # ✅ Photo identité dans l'étiquette (même taille, sans déformation)
    photo_token = (t.get("identity_photo") or "").strip()
    if photo_token:
        photo_path = _detokenize_path(photo_token)
        _insert_label_photo(doc, "{{PHOTO}}", photo_path, width_cm=5.41, height_cm=6.41)
    else:
        # si pas de photo, on enlève le placeholder
        _replace_in_docx(doc, {"{{PHOTO}}": ""})

    # 4) Télécharger
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)

    filename = f"etiquette_{t.get('last_name','')}_{t.get('first_name','')}.docx".replace(" ", "_")
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

def _prepare_photo_for_label(src_path: str, target_ratio: float) -> str:
    """
    Recadre la photo au centre au bon ratio (sans déformation),
    et retourne un chemin vers un JPG temporaire compatible Word.
    """
    im = Image.open(src_path).convert("RGB")
    w, h = im.size
    src_ratio = w / h

    if src_ratio > target_ratio:
        # image trop large → on coupe sur les côtés
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        im = im.crop((left, 0, left + new_w, h))
    else:
        # image trop haute → on coupe en haut/bas
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        im = im.crop((0, top, w, top + new_h))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    im.save(tmp.name, "JPEG", quality=90)
    return tmp.name


def _insert_label_photo(doc: Document, placeholder: str, photo_path: str, width_cm: float, height_cm: float) -> bool:
    if not photo_path or not os.path.exists(photo_path):
        return False

    target_ratio = width_cm / height_cm
    prepared = _prepare_photo_for_label(photo_path, target_ratio)

    width = Inches(width_cm / 2.54)
    height = Inches(height_cm / 2.54)

    def process_paragraph(p) -> bool:
        full = "".join(run.text for run in p.runs)
        if placeholder not in full:
            return False

        # vide le paragraphe
        for run in p.runs:
            run.text = ""

        # insère l'image recadrée au bon ratio, donc pas de déformation
        r = p.add_run()
        r.add_picture(prepared, width=width, height=height)
        return True

    def process_table(table) -> bool:
        ok = False
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    ok = process_paragraph(p) or ok
                for t2 in cell.tables:
                    ok = process_table(t2) or ok
        return ok

    inserted = False
    for p in doc.paragraphs:
        inserted = process_paragraph(p) or inserted
    for table in doc.tables:
        inserted = process_table(table) or inserted

    return inserted


@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/send-access")
@admin_login_required
def admin_send_access(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)
    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    link = f"{PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')}/espace/{t.get('public_token','')}"
    subject = "Accès à votre espace stagiaire – Intégrale Academy"

    html = mail_layout(f"""
      <h2>Votre espace stagiaire est disponible</h2>
      <p>Formation : <strong>{_session_get(s,'name','')}</strong></p>
      <p>
        <a href="{link}" style="display:inline-block;background:#1f8f4a;color:white;padding:10px 14px;border-radius:10px;text-decoration:none">
          Accéder à mon espace stagiaire
        </a>
      </p>
    """)

    sms = f"Intégrale Academy : votre espace stagiaire est disponible : {link}"

    brevo_send_email(t.get("email", ""), subject, html)
    brevo_send_sms(t.get("phone", ""), sms)

    t["access_sent_at"] = _now_iso()
    s["trainees"] = trainees
    save_data(data)
    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

# =========================
# Test de français — notify/relance
# =========================
@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/test-fr/notify")
@admin_login_required
def admin_test_fr_notify(session_id: str, trainee_id: str):
    code = (request.form.get("code") or "").strip()
    deadline = (request.form.get("deadline") or "").strip()
    if not code or not deadline:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)
    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id")==trainee_id), None)
    if not t:
        abort(404)

    link = "https://testb1.lapreventionsecurite.org/Public/"
    subject = "Test de français à réaliser – Intégrale Academy"

    formation_type = (_session_get(s, "training_type", "") or _session_get(s, "name", "")).strip()
    dstart = fr_date(_session_get(s, "date_start", ""))
    dend = fr_date(_session_get(s, "date_end", ""))

    html = mail_layout(f"""
      <h2 style="text-align:center">📝 Test de français obligatoire</h2>

      <p>Bonjour <strong>{t.get("first_name","").strip() or "Madame, Monsieur"}</strong>,</p>

      <p>
        Je me permets de revenir vers vous concernant votre inscription en formation
        <strong>{formation_type}</strong>, qui se déroulera du <strong>{dstart}</strong> au <strong>{dend}</strong>.
      </p>

      <p>
        Conformément à la réglementation, nous vous demandons de bien vouloir procéder au
        <strong>Test de français obligatoire</strong> avant votre entrée en formation.
      </p>

      <div style="background:#f3f4f6;border:1px solid #e5e7eb;border-radius:12px;padding:14px;margin:16px 0">
        <p style="margin:0 0 10px 0"><strong>🔗 Lien du test :</strong>
          <a href="{link}" style="color:#1f8f4a;text-decoration:none;font-weight:bold">{link}</a>
        </p>

        <p style="margin:0 0 10px 0"><strong>🔑 Code d’activation :</strong>
          <span style="font-size:16px;letter-spacing:1px">{code}</span>
        </p>

        <p style="margin:0;color:#b91c1c;font-weight:bold">
          ⚠️ Attention : le test doit être réalisé le <u>{fr_date(deadline)}</u>.
        </p>
      </div>

      <p>Je vous remercie par avance et je vous souhaite une excellente journée,</p>

      <p style="margin-top:22px">
        <strong>Clément VAILLANT</strong><br>
        Directeur Intégrale Academy
      </p>

      <p style="text-align:center;margin-top:18px">
        <a href="{link}"
           style="display:inline-block;background:#1f8f4a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">
          👉 Accéder au test de français
        </a>
      </p>
    """)
    deadline_fr = fr_date(deadline)

    sms = (
        f"Intégrale Academy 📝 Bonjour {t.get('first_name','')}, "
        f"Vous devez réalsier le Test de français obligatoire pour votre formation {formation_type}. "
        f"Lien : {link} | Code : {code} | À faire le {deadline_fr}. "
        f"Besoin d’aide ? 04 22 47 07 68"
    )

    brevo_send_email(t.get("email",""), subject, html)
    brevo_send_sms(t.get("phone",""), sms)

    t["test_fr_status"] = "in_progress"
    t["test_fr_code"] = code
    t["test_fr_deadline"] = deadline
    t["test_fr_last_notified_at"] = _now_iso()
    t["updated_at"] = _now_iso()

    s["trainees"] = trainees
    save_data(data)
    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/test-fr/relance")
@admin_login_required
def admin_test_fr_relance(session_id: str, trainee_id: str):
    code = (request.form.get("code") or "").strip()
    deadline = (request.form.get("deadline") or "").strip()
    if not code or not deadline:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    link = "https://testb1.lapreventionsecurite.org/Public/"
    subject = "Relance – Test de français à réaliser"

    formation_type = (_session_get(s, "training_type", "") or _session_get(s, "name", "")).strip()
    dstart = fr_date(_session_get(s, "date_start", ""))
    dend = fr_date(_session_get(s, "date_end", ""))
    deadline_fr = fr_date(deadline)

    html = mail_layout(f"""
      <h2 style="text-align:center;color:#b91c1c">⏰ Relance – Test de français obligatoire</h2>

      <p>Bonjour <strong>{t.get("first_name","").strip() or "Madame, Monsieur"}</strong>,</p>

      <p>
        Nous revenons vers vous concernant votre inscription en formation
        <strong>{formation_type}</strong> (du <strong>{dstart}</strong> au <strong>{dend}</strong>).
      </p>

      <p>
        À ce jour, nous n’avons pas encore reçu la validation de votre <strong>Test de français obligatoire</strong>.
        Merci de le réaliser dès que possible.
      </p>

      <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:14px;margin:16px 0">
        <p style="margin:0 0 10px 0"><strong>🔗 Lien du test :</strong>
          <a href="{link}" style="color:#1f8f4a;text-decoration:none;font-weight:bold">{link}</a>
        </p>

        <p style="margin:0 0 10px 0"><strong>🔑 Code d’activation :</strong>
          <span style="font-size:16px;letter-spacing:1px">{code}</span>
        </p>

        <p style="margin:0;color:#b91c1c;font-weight:bold">
          ⚠️ Date limite : <u>{deadline_fr}</u>
        </p>
      </div>

      <p style="margin-top:22px">
        Si vous avez la moindre difficulté, contactez-nous au <strong>04 22 47 07 68</strong>.
      </p>

      <p style="margin-top:22px">
        Merci par avance,<br>
        <strong>Clément VAILLANT</strong><br>
        Directeur Intégrale Academy
      </p>

      <p style="text-align:center;margin-top:18px">
        <a href="{link}"
           style="display:inline-block;background:#1f8f4a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">
          👉 Accéder au test de français
        </a>
      </p>
    """)

    sms = (
        f"Intégrale Academy ⏰ Relance : Bonjour {t.get('first_name','')}, "
        f"Vous n'avez pas encore réalisé votre Test de français obligatoire avant votre entrée en formation {formation_type}. "
        f"Lien : {link} | Code : {code} | Date limite : {deadline_fr}. "
        f"Besoin d’aide ? 04 22 47 07 68"
    )

    brevo_send_email(t.get("email", ""), subject, html)
    brevo_send_sms(t.get("phone", ""), sms)

    t["test_fr_status"] = "relance"
    t["test_fr_code"] = code
    t["test_fr_deadline"] = deadline
    t["test_fr_last_relance_at"] = _now_iso()
    t["updated_at"] = _now_iso()

    s["trainees"] = trainees
    save_data(data)
    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

# =========================
# Documents — notify / nonconform / relance / zip
# =========================
@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/docs/notify")
@admin_login_required
def admin_docs_notify(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    link = f"{PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')}/espace/{t.get('public_token','')}"
    subject = "Envoi de documents – Action requise (Intégrale Academy)"

    formation_type = (_session_get(s, "training_type", "") or _session_get(s, "name", "")).strip()
    dstart = fr_date(_session_get(s, "date_start", ""))
    dend = fr_date(_session_get(s, "date_end", ""))

    first_name = (t.get("first_name") or "").strip() or "Madame, Monsieur"

    html = mail_layout(f"""
      <h2 style="text-align:center">📄 Envoi de documents – Dossier formation</h2>

      <p>Bonjour <strong>{first_name}</strong>,</p>

      <p>
        Dans le cadre de votre inscription en formation
        <strong>{formation_type}</strong> (du <strong>{dstart}</strong> au <strong>{dend}</strong>),
        nous vous invitons à compléter votre Dossier Formation via votre espace stagiaire.
      </p>

      <div style="background:#f3f4f6;border:1px solid #e5e7eb;border-radius:12px;padding:14px;margin:16px 0">
        <p style="margin:0 0 10px 0">
          <strong>📍 Accès à votre espace stagiaire :</strong><br>
          <a href="{link}" style="color:#1f8f4a;text-decoration:none;font-weight:bold">{link}</a>
        </p>

        <p style="margin:0;color:#b91c1c;font-weight:bold">
          ⚠️ Pour un meilleur traitement de votre inscription, nous vous invitons à compléter votre dossier dès que possible. Attention, votre dossier doit être complet au plus tard 10 jours avant votre entrée en formation.
        </p>
      </div>

      <p style="margin-top:22px">
        Si vous avez la moindre difficulté, vous pouvez nous contacter au <strong>04 22 47 07 68</strong>.
      </p>

      <p style="margin-top:22px">
        Merci par avance,<br>
        <strong>Clément VAILLANT</strong><br>
        Directeur Intégrale Academy
      </p>

      <p style="text-align:center;margin-top:18px">
        <a href="{link}"
           style="display:inline-block;background:#1f8f4a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">
          👉 Accéder à mon espace stagiaire
        </a>
      </p>
    """)

    sms = (
        f"Intégrale Academy 📄 Bonjour {t.get('first_name','')}, "
        f"Nous vous remercions de bien vouloir compléter votre Dossier Formation concernant votre formation {formation_type} "
        f"({dstart} au {dend}) via votre espace : {link} "
        f"Besoin d’aide ? 04 22 47 07 68"
    )

    brevo_send_email(t.get("email", ""), subject, html)
    brevo_send_sms(t.get("phone", ""), sms)

    t["docs_notified_at"] = _now_iso()
    t["updated_at"] = _now_iso()

    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)

    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))
    
@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/docs/nonconform/notify")
@admin_login_required
def admin_docs_nonconform_notify(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    link = f"{PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')}/espace/{t.get('public_token','')}"
    training_type = _session_get(s, "training_type", "")
    ensure_documents_schema_for_trainee(t, training_type)

    details = docs_summary_text(t)

    subject = "Documents non conformes – Action requise (Intégrale Academy)"

    html = mail_layout(f"""
      <h2 style="text-align:center;color:#b91c1c">❌ Documents non conformes / à corriger</h2>

      <p>Bonjour <strong>{(t.get("first_name") or "").strip() or "Madame, Monsieur"}</strong>,</p>

      <p>
        Certains documents déposés dans votre dossier ne sont pas conformes (ou doivent être corrigés).
        Merci de consulter le détail ci-dessous et de déposer les documents corrigés depuis votre espace stagiaire.
      </p>

      <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:14px;margin:16px 0">
        <p style="margin:0 0 10px 0"><strong>📌 Détail de vos documents :</strong></p>
        <pre style="white-space:pre-wrap;background:#fff;border:1px solid #fee2e2;padding:10px;border-radius:10px;margin:0">{details or "Aucun détail disponible."}</pre>

        <p style="margin:14px 0 0 0">
          <strong>📍 Déposer les documents corrigés :</strong><br>
          <a href="{link}" style="color:#1f8f4a;text-decoration:none;font-weight:bold">{link}</a>
        </p>

        <p style="margin:10px 0 0 0;color:#b91c1c;font-weight:bold">
          ⚠️ Merci de corriger et renvoyer dès que possible pour valider votre inscription.
        </p>
      </div>

      <p style="margin-top:22px">
        Besoin d’aide ? Contactez-nous au <strong>04 22 47 07 68</strong>.
      </p>

      <p style="margin-top:22px">
        Merci par avance,<br>
        <strong>Clément VAILLANT</strong><br>
        Directeur Intégrale Academy
      </p>

      <p style="text-align:center;margin-top:18px">
        <a href="{link}"
           style="display:inline-block;background:#1f8f4a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">
          👉 Accéder à mon espace stagiaire
        </a>
      </p>
    """)

    sms = (
        f"Intégrale Academy ❌ Bonjour {t.get('first_name','')}, "
        f"Certains documents déposés sont NON CONFORMES. Nous vous invitons à corriger votre dépôt. La liste détaillée des non conformités vous a été adressée par mail. "
        f"Merci de déposer les documents corrigés sur votre espace : {link} "
        f"Aide : 04 22 47 07 68"
    )

    brevo_send_email(t.get("email",""), subject, html)
    brevo_send_sms(t.get("phone",""), sms)

    t["docs_last_nonconform_notified_at"] = _now_iso()
    t["updated_at"] = _now_iso()
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)

    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/docs/relance")
@admin_login_required
def admin_docs_relance(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    link = f"{PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')}/espace/{t.get('public_token','')}"
    training_type = _session_get(s, "training_type", "")
    ensure_documents_schema_for_trainee(t, training_type)
    
    docs_details = docs_summary_text(t)
    infos_details = infos_missing_text(t)

    formation_type = (_session_get(s, "training_type", "") or _session_get(s, "name", "")).strip()
    dstart = fr_date(_session_get(s, "date_start", ""))
    dend = fr_date(_session_get(s, "date_end", ""))

    first_name = (t.get("first_name") or "").strip() or "Madame, Monsieur"

    subject = "Relance : Dossier Formation incomplet"

    html = mail_layout(f"""
      <h2 style="text-align:center;color:#b91c1c">⏰ Relance – Votre Dossier Formation est incomplet</h2>

      <p>Bonjour <strong>{first_name}</strong>,</p>

      <p>
        Nous revenons vers vous concernant votre inscription en formation
        <strong>{formation_type}</strong> (du <strong>{dstart}</strong> au <strong>{dend}</strong>).
      </p>

      <p>
        À ce jour, votre dossier est INCOMPLET (éléments manquants et/ou à corriger).
        Merci de déposer les éléments nécessaires dès que possible via votre espace stagiaire.
      </p>

      <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:14px;margin:16px 0">
        <p style="margin:0 0 10px 0"><strong>📌 Votre dossier détaillé :</strong></p>
       <pre style="white-space:pre-wrap;background:#fff;border:1px solid #fee2e2;padding:10px;border-radius:10px;margin:0">{docs_details or "Aucun document en attente."}</pre>

    <p style="margin:14px 0 10px 0"><strong>🧾 Informations à compléter :</strong></p>
    <pre style="white-space:pre-wrap;background:#fff;border:1px solid #fee2e2;padding:10px;border-radius:10px;margin:0">{infos_details or "Aucune information manquante."}</pre>

        <p style="margin:12px 0 0 0">
          <strong>📍 Informations à compléter et Dépôt des documents :</strong><br>
          <a href="{link}" style="color:#1f8f4a;text-decoration:none;font-weight:bold">{link}</a>
        </p>

        <p style="margin:10px 0 0 0;color:#b91c1c;font-weight:bold">
          ⚠️ Nous vous remercions de bien vouloir compléter votre dossier dès que possible !
        </p>
      </div>

      <p style="margin-top:22px">
        Si vous avez la moindre difficulté, contactez-nous au <strong>04 22 47 07 68</strong>.
      </p>

      <p style="margin-top:22px">
        Merci par avance,<br>
        <strong>Clément VAILLANT</strong><br>
        Directeur Intégrale Academy
      </p>

      <p style="text-align:center;margin-top:18px">
        <a href="{link}"
           style="display:inline-block;background:#1f8f4a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">
          👉 Accéder à mon espace stagiaire
        </a>
      </p>
    """)

    sms = (
        f"Intégrale Academy ⏰ Relance : Bonjour {t.get('first_name','')}, "
        f"Nous revenons vers vous au sujet de votre formation {formation_type}. A ce jour votre Dossier Formation est INCOMPLET. Votre formation approche, et pour un meilleur suivi de votre inscription, nous vous remercions de bien vouloir compléter votre dossier dès que possible. "
        f"({dstart} au {dend}). Vous pouvez compléter votre dossier en cliquant ici : {link} "
        f"Besoin d’aide ? 04 22 47 07 68"
    )

    brevo_send_email(t.get("email", ""), subject, html)
    brevo_send_sms(t.get("phone", ""), sms)

    t["docs_last_relance_at"] = _now_iso()
    t["updated_at"] = _now_iso()

    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)

    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

@app.get("/admin/sessions/<session_id>/stagiaires/<trainee_id>/documents.zip")
@admin_login_required
def admin_docs_zip(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    docs = t.get("documents") or []
    buf = BytesIO()

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for d in docs:
            tokens = []

            # ✅ multi-fichiers en priorité
            if isinstance(d.get("files"), list) and d["files"]:
                tokens = [x for x in d["files"] if x]
            else:
                # compat: 1 fichier
                tok = (d.get("file") or "")
                if tok:
                    tokens = [tok]

            if not tokens:
                continue

            label = (d.get("label") or "document").replace("/", "-")
            prenom = (t.get("first_name") or "").strip()
            nom = (t.get("last_name") or "").strip()

            for i, token in enumerate(tokens, start=1):
                fp = _detokenize_path(token)
                if not os.path.exists(fp):
                    continue

                ext = os.path.splitext(fp)[1] or ""
                base = f"{label} {prenom} {nom}".strip().replace("  ", " ")

                # ✅ si plusieurs fichiers: suffixe _1, _2...
                arc = (base + ext) if len(tokens) == 1 else (f"{base}_{i}{ext}")
                z.write(fp, arcname=arc)

    buf.seek(0)
    zipname = f"Documents_{t.get('first_name','')}_{t.get('last_name','')}.zip".replace(" ", "_")
    return send_file(buf, as_attachment=True, download_name=zipname, mimetype="application/zip")

# =========================
# API docs autosave (status/comment)
# =========================
@app.post("/api/sessions/<session_id>/stagiaires/<trainee_id>/documents/update")
@admin_login_required
def api_docs_update(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        return jsonify({"ok": False, "error": "trainee_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    doc_key = payload.get("key")
    field = payload.get("field")
    value = payload.get("value")

    if field not in ("status", "comment"):
        return jsonify({"ok": False, "error": "invalid_field"}), 400

    docs = t.get("documents") or []
    for d in docs:
        if d.get("key") == doc_key:
            d[field] = value
            break

    t["updated_at"] = _now_iso()

    # ✅ Synchronisation automatique du statut dossier
    training_type = _session_get(s, "training_type", "")
    t["dossier_status"] = "complete" if dossier_is_complete_total(t, training_type) else "incomplete"

    # ✅ PERSISTENCE (sinon ça se perd au refresh)
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)

    return jsonify({
        "ok": True,
        "dossier_is_complete": dossier_is_complete_total(t, training_type),
        "dossier_status": t["dossier_status"]
    })




# =========================
# Deliverables upload (diplôme/SST/etc)
# =========================
DELIVERABLE_LABELS = {
    "carte_sst": "Carte SST",
    "diplome": "Diplôme",
    "attestation_fin_formation": "Attestation fin de formation",
}

@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/deliverables/<kind>/upload")
@admin_login_required
def admin_upload_deliverable(session_id: str, trainee_id: str, kind: str):
    if kind not in DELIVERABLE_LABELS:
        abort(404)

    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    f = request.files.get("file")
    if not f or not f.filename:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    try:
        stored = _store_file(session_id, trainee_id, "deliverables", f)
    except Exception:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    token = _tokenize_path(stored)

    t.setdefault("deliverables", {})
    t["deliverables"][kind] = token
    t["updated_at"] = _now_iso()

    link = f"{PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')}/espace/{t.get('public_token','')}"
    label = DELIVERABLE_LABELS[kind]

    # =========================
    # ✅ Jolis mails + SMS
    # =========================
    first_name = (t.get("first_name") or "").strip() or "Madame, Monsieur"
    formation_type = (_session_get(s, "training_type", "") or _session_get(s, "name", "")).strip()
    dstart = fr_date(_session_get(s, "date_start", ""))
    dend = fr_date(_session_get(s, "date_end", ""))

    extra_line = ""
    if kind == "diplome":
        extra_line = "🎉 Félicitations ! Votre diplôme est maintenant disponible."
    elif kind == "attestation_fin_formation":
        extra_line = "📄 Votre attestation de fin de formation est disponible et peut être téléchargée à tout moment."
    elif kind == "carte_sst":
        extra_line = "🩺 Votre carte SST est disponible. Conservez-la précieusement, elle peut être demandée par un employeur."

    subject = f"{label} disponible – Intégrale Academy"

    html = mail_layout(f"""
      <h2 style="text-align:center">✅ {label} disponible</h2>

      <p>Bonjour <strong>{first_name}</strong>,</p>

      <p>
        Nous avons le plaisir de vous informer que votre <strong>{label}</strong>
        est désormais disponible dans votre espace stagiaire.
      </p>

      {"<p style='margin-top:10px;font-weight:700'>" + extra_line + "</p>" if extra_line else ""}

      <div style="background:#f3f4f6;border:1px solid #e5e7eb;border-radius:12px;padding:14px;margin:16px 0">
        <p style="margin:0 0 10px 0">
          <strong>📌 Formation :</strong> {formation_type}
          {" — <strong>Dates :</strong> " + dstart + " au " + dend if (dstart or dend) else ""}
        </p>

        <p style="margin:0">
          <strong>📍 Accéder à votre espace stagiaire :</strong><br>
          <a href="{link}" style="color:#1f8f4a;text-decoration:none;font-weight:bold">{link}</a>
        </p>
      </div>

      <p style="text-align:center;margin-top:18px">
        <a href="{link}"
           style="display:inline-block;background:#1f8f4a;color:white;padding:12px 18px;border-radius:10px;
                  text-decoration:none;font-weight:bold">
          👉 Accéder à mon espace stagiaire
        </a>
      </p>

      <p style="margin-top:22px">
        Pour toute question, vous pouvez nous contacter au <strong>04 22 47 07 68</strong>.
      </p>

      <p style="margin-top:22px">
        Bien cordialement,<br>
        <strong>Clément VAILLANT</strong><br>
        Directeur Intégrale Academy
      </p>

      <hr style="margin:26px 0;border:none;border-top:1px solid #e5e7eb">

      <p style="font-size:12px;color:#6b7280;text-align:center;line-height:1.6">
        © Intégrale Academy — Merci de votre confiance 💛<br>
        54 chemin du Carreou 83480 PUGET SUR ARGENS / 142 rue de Rivoli 75001 PARIS<br>
        <a href="https://www.integraleacademy.com"
           style="color:#1f8f4a;text-decoration:none;font-weight:bold">
          integraleacademy.com
        </a>
      </p>
    """)

    sms_name = (t.get("first_name") or "").strip()
    sms = (
        f"Intégrale Academy ✅ {sms_name + ', ' if sms_name else ''}"
        f"votre {label} est disponible sur votre espace : {link} "
        f"(Aide : 04 22 47 07 68)"
    )

    brevo_send_email(t.get("email", ""), subject, html)
    brevo_send_sms(t.get("phone", ""), sms)

    # ✅ persistance
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)

    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

def find_session_and_trainee_by_token(data: Dict[str, Any], token: str):
    token = (token or "").strip()
    if not token:
        return None, None

    sessions = data.get("sessions", []) or []
    for s in sessions:
        trainees = s.get("trainees") or s.get("stagiaires") or []
        for t in trainees:
            if (t.get("public_token") or "").strip() == token:
                return s, t
    return None, None


@app.get("/espace/<token>")
def public_trainee_space(token):
    data = load_data()
    s, t = find_session_and_trainee_by_token(data, token)

    if not s or not t:
        abort(404)

    training_type = _session_get(s, "training_type", "")

    # ✅ aligne la liste des docs requis
    ensure_documents_schema_for_trainee(t, training_type)

    for d in (t.get("documents") or []):
        d["file_token"] = d.get("file") or ""

    show_hosting = ((training_type or "").strip().upper() == "A3P")
    show_vae = ("VAE" in (training_type or "").upper())

    # ✅ persistance
    s["trainees"] = _session_trainees_list(s)
    s.pop("stagiaires", None)
    save_data(data)

    return render_template(
        "public_trainee.html",
        session=s,
        trainee=t,
        token=token,
        show_hosting=show_hosting,
        show_vae=show_vae,
        dossier_ok=dossier_is_complete_total(t, training_type),
    )
    

@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/identity-photo/upload")
@admin_login_required
def admin_upload_identity_photo(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    f = request.files.get("file")
    if not f or not f.filename:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    # ✅ on limite aux images
    ext = _safe_ext(f.filename)
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    try:
        stored = _store_file(session_id, trainee_id, "identity_photo", f)
    except Exception:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    token = _tokenize_path(stored)

    # ✅ on sauvegarde le token dans le stagiaire
    t["identity_photo"] = token
    t["updated_at"] = _now_iso()

    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)

    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))


@app.post("/espace/<token>/infos/update")
def public_infos_update(token: str):
    data = load_data()
    s, t = find_session_and_trainee_by_token(data, token)
    if not s or not t:
        return jsonify({"ok": False}), 404

    payload = request.get_json(silent=True) or {}

    # champs autorisés (sécurité)
    allowed = {
        "carte_vitale",
        "pre_number",
        "birth_date",
        "birth_city",
        "birth_country",
        "nationality",
        "address",
        "zip_code",
        "city",
        "no_permis",
    }

    for k, v in payload.items():
        if k not in allowed:
            continue

        # no_permis = bool
        if k == "no_permis":
            t["no_permis"] = bool(v)
            continue

        # strings : on n'écrase PAS avec vide
        if v is None:
            continue
        if isinstance(v, str):
            vv = v.strip()
            if vv == "":
                continue
            t[k] = vv
        else:
            # si jamais tu envoies autre chose
            t[k] = v

    training_type = _session_get(s, "training_type", "")
    t["dossier_status"] = "complete" if dossier_is_complete_total(t, training_type) else "incomplete"
    t["updated_at"] = _now_iso()

    # ✅ IMPORTANT : persister la session normalisée comme ailleurs
    s["trainees"] = _session_trainees_list(s)
    s.pop("stagiaires", None)
    save_data(data)

    return jsonify({"ok": True})



@app.post("/espace/<token>/documents/<doc_key>/upload")
def public_doc_upload(token: str, doc_key: str):
    data = load_data()
    s, t = find_session_and_trainee_by_token(data, token)
    if not s or not t:
        abort(404)

    training_type = _session_get(s, "training_type", "")
    ensure_documents_schema_for_trainee(t, training_type)

    # ✅ doc_key doit être dans la liste requise
    if doc_key not in allowed_doc_keys_for_training(training_type):
        return redirect(url_for("public_trainee_space", token=token))

    # ✅ 1 fichier par envoi (mais on peut en envoyer plusieurs fois)
    f = request.files.get("file")
    if not f or not f.filename:
        return redirect(url_for("public_trainee_space", token=token))

    # ✅ garder le nom original pour la popup (GET params)
    original_name = secure_filename(f.filename or "document")

    # ✅ retrouver la config du doc (accept)
    docs = t.get("documents") or []
    target = next((d for d in docs if d.get("key") == doc_key), None)
    if not target:
        return redirect(url_for("public_trainee_space", token=token))

    accept = (target.get("accept") or "").lower()

    def _accepts_file(ext: str) -> bool:
        acc = [a.strip().lower() for a in accept.split(",") if a.strip()]
        if "application/pdf" in acc:
            return ext == ".pdf"
        if any(a.startswith("image/") for a in acc) or ("image/jpeg" in acc) or ("image/png" in acc):
            return ext in (".jpg", ".jpeg", ".png", ".webp")
        return ext in ALLOWED_EXT

    ext = _safe_ext(f.filename)
    if not _accepts_file(ext):
        return redirect(url_for("public_trainee_space", token=token))

    # ✅ stockage du fichier
    session_id = s.get("id")
    trainee_id = t.get("id")
    stored = _store_file(session_id, trainee_id, "public_documents", f)
    new_token = _tokenize_path(stored)

    # ✅ MAJ du doc: on APPEND dans files (sans écraser)
    for d in docs:
        if d.get("key") == doc_key:
            cur_files = d.get("files")
            if not isinstance(cur_files, list):
                cur_files = []

            # compat: si un ancien "file" existe mais pas dans files, on le garde
            old = (d.get("file") or "").strip()
            if old and old not in cur_files:
                cur_files.append(old)

            cur_files.append(new_token)

            # on garde le premier fichier dans "file" (pour compat template/admin)
            d["files"] = cur_files
            d["file"] = cur_files[0] if cur_files else ""

            cur = (d.get("status") or "").strip().upper()
            if cur in ("", "NON DÉPOSÉ", "NON DEPOSE", "NON_DEPOSE"):
                d["status"] = "A CONTRÔLER"
            if d.get("status") == "A CONTROLER":
                d["status"] = "A CONTRÔLER"
            break

    t["updated_at"] = _now_iso()
    t["dossier_status"] = "complete" if dossier_is_complete_total(t, training_type) else "incomplete"

    # ✅ persistance
    s["trainees"] = _session_trainees_list(s)
    s.pop("stagiaires", None)
    save_data(data)

    # ✅ IMPORTANT: on renvoie l’info au GET (pour popup + scroll ensuite)
    return redirect(url_for(
        "public_trainee_space",
        token=token,
        uploaded=doc_key,
        fname=original_name
    ))




# =========================
# ✅ Remplace ta page JSON par une vraie page HTML
# =========================
@app.get("/admin/sessions/<session_id>/stagiaires/<trainee_id>")
@admin_login_required
def admin_trainee_page(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    session_view = {
        "id": s.get("id"),
        "name": _session_get(s, "name", ""),
        "training_type": _session_get(s, "training_type", ""),
        "date_start": _session_get(s, "date_start", ""),
        "date_end": _session_get(s, "date_end", ""),
        "exam_date": _session_get(s, "exam_date", ""),
    }

    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not t:
        abort(404)

    training_type = session_view["training_type"]

    # ✅ IMPORTANT : on impose la liste de documents selon la formation (et supprime dom)
    ensure_documents_schema_for_trainee(t, training_type)

    # ✅ deliverables
    t.setdefault("deliverables", {})

    # file tokens for template links (documents)
    for d in (t.get("documents") or []):
        # compat: 1 fichier
        token = d.get("file") or ""
        d["file_token"] = token
    
        # ✅ multi-fichiers
        files = d.get("files")
        if isinstance(files, list) and files:
            d["file_tokens"] = [x for x in files if x]
        else:
            d["file_tokens"] = []

    # deliverables view
    deliverables_view = []
    for k, label in DELIVERABLE_LABELS.items():
        token = (t.get("deliverables", {}) or {}).get(k, "")
        deliverables_view.append({
            "key": k,
            "label": label,
            "file": token,
            "file_token": token,
        })

    show_vae = (training_type == "DIRIGEANT VAE")
    vae_steps = [
        {"key":"livret_1_redaction","label":"Livret 1 en cours de rédaction"},
        {"key":"livret_1_recu","label":"Livret 1 reçu"},
        {"key":"demande_modif_l1","label":"Demande modif livret 1"},
        {"key":"modif_l1_recue","label":"Modif livret 1 reçue"},
        {"key":"recevabilite_ok","label":"Recevabilité OK"},
        {"key":"livret_2_recu","label":"Livret 2 reçu"},
        {"key":"demande_modif_l2","label":"Demande modif livret 2"},
        {"key":"modif_l2_recue","label":"Modif livret 2 reçue"},
        {"key":"jury","label":"Passage devant jury"},
    ]

    # ✅ s'assure que no_permis est bien un bool
    t["no_permis"] = bool(t.get("no_permis"))

    # ✅ dossier_status cohérent avec les docs requis
    dossier_complete = dossier_is_complete_total(t, training_type)
    t["dossier_status"] = "complete" if dossier_complete else "incomplete"
    t["updated_at"] = _now_iso()

    # ✅ persistance
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)

    return render_template(
        "admin_trainee.html",
        session=session_view,
        trainee=t,
        show_vae=show_vae,
        vae_steps=vae_steps,
        dossier_is_complete=dossier_complete,
        deliverables_view=deliverables_view,
        PUBLIC_STUDENT_PORTAL_BASE=PUBLIC_STUDENT_PORTAL_BASE,
    )

@app.get("/api/docs_to_control")
@admin_login_required
def api_docs_to_control():
    data = load_data()
    out = []

    for s in data.get("sessions", []):
        session_id = s.get("id")
        session_name = _session_get(s, "name", "")
        training_type = _session_get(s, "training_type", "")

        trainees = _session_trainees_list(s)

        for t in trainees:
            # s'assure que les docs requis existent (sinon liste vide => pas détecté)
            ensure_documents_schema_for_trainee(t, training_type)

            docs = t.get("documents") or []
            pending = 0
            for d in docs:
                st = (d.get("status") or "").strip().upper()
                if st in ("A CONTRÔLER", "A CONTROLER"):
                    pending += 1

            if pending > 0:
                out.append({
                    "session_id": session_id,
                    "session_name": session_name,
                    "training_type": training_type,
                    "trainee_id": t.get("id"),
                    "last_name": t.get("last_name", ""),
                    "first_name": t.get("first_name", ""),
                    "pending_count": pending,
                    "admin_url": f"/admin/sessions/{session_id}/stagiaires/{t.get('id')}",
                })

    # tri: plus urgent d'abord (plus de docs à contrôler)
    out.sort(key=lambda x: x.get("pending_count", 0), reverse=True)

    return jsonify({"ok": True, "items": out, "count": len(out)})


from flask import make_response

@app.get("/docs_to_control.json")
def public_docs_to_control():
    data = load_data()
    out = []

    for s in data.get("sessions", []):
        session_id = s.get("id")
        session_name = _session_get(s, "name", "")
        training_type = _session_get(s, "training_type", "")

        trainees = _session_trainees_list(s)

        for t in trainees:
            ensure_documents_schema_for_trainee(t, training_type)

            docs = t.get("documents") or []
            pending = 0
            for d in docs:
                st = (d.get("status") or "").strip().upper()
                if st in ("A CONTRÔLER", "A CONTROLER"):
                    pending += 1

            if pending > 0:
                out.append({
                    "session_id": session_id,
                    "session_name": session_name,
                    "training_type": training_type,
                    "trainee_id": t.get("id"),
                    "last_name": t.get("last_name", ""),
                    "first_name": t.get("first_name", ""),
                    "pending_count": pending,
                    "admin_url": f"/admin/sessions/{session_id}/stagiaires/{t.get('id')}",
                })

    out.sort(key=lambda x: x.get("pending_count", 0), reverse=True)

    resp = make_response(jsonify({"ok": True, "items": out, "count": len(out)}))

    # ✅ autorise le fetch depuis ton dashboard (autre domaine)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"

    return resp


@app.get("/api/trainees_search")
@admin_login_required
def api_trainees_search():
    q = (request.args.get("q") or "").strip().lower()
    if not q or len(q) < 2:
        return jsonify({"ok": True, "items": []})

    data = load_data()
    out = []

    for s in data.get("sessions", []):
        session_id = s.get("id")
        session_name = _session_get(s, "name", "")
        training_type = _session_get(s, "training_type", "")

        trainees = _session_trainees_list(s)

        for t in trainees:
            fn = (t.get("first_name") or "").strip()
            ln = (t.get("last_name") or "").strip()
            full = f"{fn} {ln}".strip().lower()

            # match prénom/nom (contient)
            if q in full or q in fn.lower() or q in ln.lower():
                out.append({
                    "session_id": session_id,
                    "session_name": session_name,
                    "training_type": training_type,
                    "trainee_id": t.get("id"),
                    "first_name": fn,
                    "last_name": ln,
                    "admin_url": f"/admin/sessions/{session_id}/stagiaires/{t.get('id')}",
                })

    # tri: nom puis prénom
    out.sort(key=lambda x: ((x.get("last_name") or "").lower(), (x.get("first_name") or "").lower()))

    # limite pour éviter des réponses énormes
    out = out[:30]

    return jsonify({"ok": True, "items": out, "count": len(out)})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
