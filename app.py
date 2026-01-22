import os
import json
import uuid
import datetime
from typing import Dict, Any, Optional, List

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

PUBLIC_STUDENT_PORTAL_BASE = os.environ.get("PUBLIC_STUDENT_PORTAL_BASE", "https://example.com/espace-stagiaire")

CNAPS_STATUS_ENDPOINT = os.environ.get("CNAPS_STATUS_ENDPOINT", "")
HEBERGEMENT_STATUS_ENDPOINT = os.environ.get("HEBERGEMENT_STATUS_ENDPOINT", "")


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
            return json.load(f)
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
# Pages (templates)
# =========================

@app.get("/")
def home():
    return redirect(url_for("admin_sessions"))


@app.get("/admin/sessions")
def admin_sessions():
    data = load_data()
    out_sessions = []
    for s in data.get("sessions", []):
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
        if ln and fn:
            cn = fetch_cnaps_status_by_name(ln, fn)
            if cn:
                t["cnaps"] = str(cn).upper()
        if not t.get("cnaps"):
            t["cnaps"] = "INCONNU"

        # hosting only for A3P
        if session_view["training_type"] == "A3P":
            email = t.get("email") or ""
            hb = fetch_hebergement_status(email) if email else None
            t["hosting_status"] = hb if hb else (t.get("hosting_status") or "unknown")
        else:
            t.pop("hosting_status", None)

    # persist normalized trainees back into storage (so future pages are consistent)
    s["trainees"] = trainees
    s.pop("stagiaires", None)  # optional cleanup
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
    }
    data["sessions"].insert(0, s)
    save_data(data)
    return jsonify({"ok": True, "id": session_id})


@app.post("/api/sessions/<session_id>/delete")
def api_delete_session(session_id: str):
    data = load_data()
    before = len(data.get("sessions", []))
    data["sessions"] = [s for s in data.get("sessions", []) if s.get("id") != session_id]
    save_data(data)
    return jsonify({"ok": True, "deleted": (len(data["sessions"]) != before)})


# =========================
# API - Trainees (create + update for autosave)
# =========================

@app.post("/api/sessions/<session_id>/trainees/create")
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

    if not last_name or not first_name:
        return jsonify({"ok": False, "error": "missing_name"}), 400

    trainee_id = "TRN-" + uuid.uuid4().hex[:8].upper()

    training_type = _session_get(s, "training_type", "")
    show_hosting = (training_type == "A3P")
    show_vae = (training_type == "DIRIGEANT VAE")

    t = {
        "id": trainee_id,
        "personal_id": trainee_id,

        "last_name": last_name,
        "first_name": first_name,
        "email": email,
        "phone": phone,

        "comment": "",
        "cnaps": "INCONNU",

        "convention_status": "soon",
        "test_fr_status": "soon",
        "dossier_status": "incomplete",
        "financement_status": "soon",
        "vae_status": "soon" if show_vae else "",
        "hosting_status": "unknown" if show_hosting else "",

        "public_token": uuid.uuid4().hex,

        "documents": [
            {"key": "id", "label": "Pièce d'identité", "status": "A CONTRÔLER", "comment": "", "file": ""},
            {"key": "dom", "label": "Justificatif de domicile (-3 mois)", "status": "A CONTRÔLER", "comment": "", "file": ""},
            {"key": "photo", "label": "Photo d'identité", "status": "A CONTRÔLER", "comment": "", "file": ""},
        ],

        "created_at": _now_iso(),
    }

    trainees = _session_trainees_list(s)
    trainees.insert(0, t)
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)
    return jsonify({"ok": True, "id": trainee_id})


@app.post("/api/sessions/<session_id>/stagiaires/<trainee_id>/update")
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
        "vae_status_label",
        "cnaps",
    }

    for k, v in payload.items():
        if k in allowed:
            t[k] = v

    t["updated_at"] = _now_iso()
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)
    return jsonify({"ok": True})


@app.post("/api/sessions/<session_id>/trainees/<trainee_id>/delete")
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
# Brevo Email + SMS (si pas déjà)
# =========================
def brevo_send_email(to_email: str, subject: str, html: str) -> bool:
    if not BREVO_API_KEY or not to_email:
        return False
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {"accept":"application/json","api-key":BREVO_API_KEY,"content-type":"application/json"}
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
    if not BREVO_API_KEY or not phone:
        return False
    url = "https://api.brevo.com/v3/transactionalSMS/sms"
    headers = {"accept":"application/json","api-key":BREVO_API_KEY,"content-type":"application/json"}
    payload = {"recipient": phone, "content": message, "type":"transactional"}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=12)
        return r.status_code in (200, 201, 202)
    except Exception:
        return False


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
def admin_view_upload(path: str):
    full = _detokenize_path(path)
    if not os.path.exists(full):
        abort(404)
    # simple serve
    return send_file(full, as_attachment=False)

@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/documents/<doc_key>/upload")
def admin_upload_doc_file(session_id: str, trainee_id: str, doc_key: str):
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
        stored = _store_file(session_id, trainee_id, "documents", f)
    except Exception:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    token = _tokenize_path(stored)

    docs = t.get("documents") or []
    found = False
    for d in docs:
        if d.get("key") == doc_key:
            d["file"] = token
            found = True
            break

    # si doc_key inconnu, on refuse silencieusement
    if not found:
        return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

    t["updated_at"] = _now_iso()

    # IMPORTANT: recalc dossier_status (voir point 3)
    t["dossier_status"] = "complete" if dossier_is_complete(t) else "incomplete"

    s["trainees"] = trainees
    save_data(data)
    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))



# =========================
# Documents logic
# =========================
def dossier_is_complete(trainee: Dict[str, Any]) -> bool:
    docs = trainee.get("documents") or []
    if not docs:
        return False
    for d in docs:
        if (d.get("status") or "").upper() != "CONFORME":
            return False
    return True

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


# =========================
# Admin actions — trainee
# =========================
@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/delete")
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
        "{{NOM}}": t.get("last_name", ""),
        "{{PRENOM}}": t.get("first_name", ""),
        "{{FORMATION}}": _session_get(s, "name", ""),
        "{{TYPE_FORMATION}}": training_type,
        "{{DATES}}": f"{_session_get(s,'date_start','')} → {_session_get(s,'date_end','')}",
    }

    for p in doc.paragraphs:
        for key, val in replacements.items():
            if key in p.text:
                p.text = p.text.replace(key, val)

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


@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/send-access")
def admin_send_access(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)
    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id")==trainee_id), None)
    if not t:
        abort(404)

    link = f"{PUBLIC_STUDENT_PORTAL_BASE}?token={t.get('public_token','')}"
    subject = "Accès à votre espace stagiaire – Intégrale Academy"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        <h2>Votre espace stagiaire est disponible</h2>
        <p>Formation : <strong>{_session_get(s,'name','')}</strong></p>
        <p><a href="{link}" style="display:inline-block;background:#1f8f4a;color:white;padding:10px 14px;border-radius:10px;text-decoration:none">Accéder à mon espace stagiaire</a></p>
        <p style="color:#666;font-size:13px">Intégrale Academy</p>
      </div>
    </div>
    """
    sms = f"Intégrale Academy : votre espace stagiaire est disponible : {link}"

    brevo_send_email(t.get("email",""), subject, html)
    brevo_send_sms(t.get("phone",""), sms)

    t["access_sent_at"] = _now_iso()
    s["trainees"] = trainees
    save_data(data)
    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))


# =========================
# Test de français — notify/relance
# =========================
@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/test-fr/notify")
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
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        <h2>Test de français – à faire</h2>
        <p>Merci de réaliser votre test via : <a href="{link}">{link}</a></p>
        <p><strong>Code :</strong> {code}</p>
        <p><strong>À réaliser avant :</strong> {deadline}</p>
        <p style="color:#666;font-size:13px">Intégrale Academy</p>
      </div>
    </div>
    """
    sms = f"Intégrale Academy : Test FR à faire. Lien: {link} Code: {code} Avant: {deadline}"

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
    t = next((x for x in trainees if x.get("id")==trainee_id), None)
    if not t:
        abort(404)

    link = "https://testb1.lapreventionsecurite.org/Public/"
    subject = "Relance – Test de français à réaliser"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        <h2>Relance – Test de français</h2>
        <p>Nous n’avons pas encore reçu votre test. Merci de le réaliser via : <a href="{link}">{link}</a></p>
        <p><strong>Nouveau code :</strong> {code}</p>
        <p><strong>À réaliser avant :</strong> {deadline}</p>
        <p style="color:#666;font-size:13px">Intégrale Academy</p>
      </div>
    </div>
    """
    sms = f"Relance Intégrale Academy : Test FR. Lien: {link} Code: {code} Avant: {deadline}"

    brevo_send_email(t.get("email",""), subject, html)
    brevo_send_sms(t.get("phone",""), sms)

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
def admin_docs_notify(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)
    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id")==trainee_id), None)
    if not t:
        abort(404)

    link = f"{PUBLIC_STUDENT_PORTAL_BASE}?token={t.get('public_token','')}"
    subject = "Documents à transmettre – Intégrale Academy"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        <h2>Documents à transmettre</h2>
        <p>Merci de nous transmettre vos documents pour la formation :</p>
        <p><a href="{link}" style="display:inline-block;background:#1f8f4a;color:white;padding:10px 14px;border-radius:10px;text-decoration:none">Accéder à mon espace stagiaire</a></p>
        <p style="color:#666;font-size:13px">Intégrale Academy</p>
      </div>
    </div>
    """
    sms = f"Intégrale Academy : merci d’envoyer vos documents : {link}"

    brevo_send_email(t.get("email",""), subject, html)
    brevo_send_sms(t.get("phone",""), sms)

    t["docs_notified_at"] = _now_iso()
    t["updated_at"] = _now_iso()
    s["trainees"] = trainees
    save_data(data)
    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/docs/nonconform-notify")
def admin_docs_nonconform_notify(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)
    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id")==trainee_id), None)
    if not t:
        abort(404)

    link = f"{PUBLIC_STUDENT_PORTAL_BASE}?token={t.get('public_token','')}"
    details = docs_summary_text(t)

    subject = "Documents non conformes – Action requise"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        <h2>Documents non conformes</h2>
        <p>Certains documents sont non conformes ou à contrôler. Merci de consulter le détail :</p>
        <pre style="white-space:pre-wrap;background:#f2f2f2;padding:10px;border-radius:10px">{details}</pre>
        <p>Vous pouvez déposer des documents corrigés ici :</p>
        <p><a href="{link}" style="display:inline-block;background:#1f8f4a;color:white;padding:10px 14px;border-radius:10px;text-decoration:none">Accéder à mon espace stagiaire</a></p>
        <p style="color:#666;font-size:13px">Intégrale Academy</p>
      </div>
    </div>
    """
    sms = f"Intégrale Academy : documents non conformes. Merci de consulter votre espace : {link}"

    brevo_send_email(t.get("email",""), subject, html)
    brevo_send_sms(t.get("phone",""), sms)

    t["docs_last_nonconform_notified_at"] = _now_iso()
    t["updated_at"] = _now_iso()
    s["trainees"] = trainees
    save_data(data)
    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/docs/relance")
def admin_docs_relance(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)
    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id")==trainee_id), None)
    if not t:
        abort(404)

    link = f"{PUBLIC_STUDENT_PORTAL_BASE}?token={t.get('public_token','')}"
    details = docs_summary_text(t)

    subject = "Relance – Documents à transmettre / corriger"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        <h2>Relance – Documents</h2>
        <p>Nous n’avons pas encore reçu tous les documents conformes. Détail actuel :</p>
        <pre style="white-space:pre-wrap;background:#f2f2f2;padding:10px;border-radius:10px">{details}</pre>
        <p>Merci d’envoyer / corriger via :</p>
        <p><a href="{link}" style="display:inline-block;background:#1f8f4a;color:white;padding:10px 14px;border-radius:10px;text-decoration:none">Accéder à mon espace stagiaire</a></p>
        <p style="color:#666;font-size:13px">Intégrale Academy</p>
      </div>
    </div>
    """
    sms = f"Relance Intégrale Academy : merci d’envoyer / corriger vos documents : {link}"

    brevo_send_email(t.get("email",""), subject, html)
    brevo_send_sms(t.get("phone",""), sms)

    t["docs_last_relance_at"] = _now_iso()
    t["updated_at"] = _now_iso()
    s["trainees"] = trainees
    save_data(data)
    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))

@app.get("/admin/sessions/<session_id>/stagiaires/<trainee_id>/documents.zip")
def admin_docs_zip(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)
    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id")==trainee_id), None)
    if not t:
        abort(404)

    docs = t.get("documents") or []
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for d in docs:
            token = (d.get("file") or "")
            if not token:
                continue
            fp = _detokenize_path(token)
            if not os.path.exists(fp):
                continue

            label = (d.get("label") or "document").replace("/", "-")
            prenom = (t.get("first_name") or "").strip()
            nom = (t.get("last_name") or "").strip()
            ext = os.path.splitext(fp)[1] or ""
            newname = f"{label} {prenom} {nom}".strip().replace("  ", " ")
            z.write(fp, arcname=(newname + ext))

    buf.seek(0)
    zipname = f"Documents_{t.get('first_name','')}_{t.get('last_name','')}.zip".replace(" ", "_")
    return send_file(buf, as_attachment=True, download_name=zipname, mimetype="application/zip")


# =========================
# API docs autosave (status/comment)
# =========================
@app.post("/api/sessions/<session_id>/stagiaires/<trainee_id>/documents/update")
def api_docs_update(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        return jsonify({"ok": False, "error": "session_not_found"}), 404
    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id")==trainee_id), None)
    if not t:
        return jsonify({"ok": False, "error": "trainee_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    doc_key = payload.get("key")
    field = payload.get("field")
    value = payload.get("value")

    if field not in ("status","comment"):
        return jsonify({"ok": False, "error": "invalid_field"}), 400

    docs = t.get("documents") or []
    for d in docs:
        if d.get("key") == doc_key:
            d[field] = value
            break

    t["updated_at"] = _now_iso()
    
    # ✅ Synchronisation automatique du statut dossier
    t["dossier_status"] = "complete" if dossier_is_complete(t) else "incomplete"
    
    s["trainees"] = trainees
    save_data(data)
    return jsonify({
        "ok": True,
        "dossier_is_complete": dossier_is_complete(t),
        "dossier_status": t["dossier_status"]
    })



# =========================
# Deliverables upload (diplôme/SST/etc)
# =========================
DELIVERABLE_LABELS = {
    "certificat_sst": "Certificat SST",
    "carte_sst": "Carte SST",
    "diplome": "Diplôme",
    "attestation_fin_formation": "Attestation fin de formation",
    "dossier_fin_formation": "Dossier fin de formation",
}

@app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/deliverables/<kind>/upload")
def admin_upload_deliverable(session_id: str, trainee_id: str, kind: str):
    if kind not in DELIVERABLE_LABELS:
        abort(404)

    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)
    trainees = _session_trainees_list(s)
    t = next((x for x in trainees if x.get("id")==trainee_id), None)
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

    link = f"{PUBLIC_STUDENT_PORTAL_BASE}?token={t.get('public_token','')}"
    label = DELIVERABLE_LABELS[kind]

    subject = f"{label} disponible – Intégrale Academy"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        <h2>{label} disponible</h2>
        <p>Votre document est disponible sur votre espace stagiaire :</p>
        <p><a href="{link}" style="display:inline-block;background:#1f8f4a;color:white;padding:10px 14px;border-radius:10px;text-decoration:none">Accéder à mon espace stagiaire</a></p>
        <p style="color:#666;font-size:13px">Intégrale Academy</p>
      </div>
    </div>
    """
    sms = f"Intégrale Academy : {label} disponible sur votre espace stagiaire : {link}"

    brevo_send_email(t.get("email",""), subject, html)
    brevo_send_sms(t.get("phone",""), sms)

    s["trainees"] = trainees
    save_data(data)
    return redirect(url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee_id))


# =========================
# ✅ Remplace ta page JSON par une vraie page HTML
# =========================
@app.get("/admin/sessions/<session_id>/stagiaires/<trainee_id>")
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
    t = next((x for x in trainees if x.get("id")==trainee_id), None)
    if not t:
        abort(404)

    # ensure fields exist
    t.setdefault("documents", [
        {"key":"id","label":"Pièce d'identité","status":"A CONTRÔLER","comment":"","file":""},
        {"key":"dom","label":"Justificatif de domicile (-3 mois)","status":"A CONTRÔLER","comment":"","file":""},
        {"key":"photo","label":"Photo d'identité","status":"A CONTRÔLER","comment":"","file":""},
    ])
    t.setdefault("deliverables", {})

    # file tokens for template links
    for d in t.get("documents", []):
        token = d.get("file") or ""
        d["file_token"] = token

    deliverables_view = []
    for k, label in DELIVERABLE_LABELS.items():
        token = (t.get("deliverables", {}) or {}).get(k, "")
        deliverables_view.append({
            "key": k,
            "label": label,
            "file": token,
            "file_token": token,
        })

    show_vae = (session_view["training_type"] == "DIRIGEANT VAE")
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

    # dossier status
    dossier_complete = dossier_is_complete(t)

    # persist normalized
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
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
